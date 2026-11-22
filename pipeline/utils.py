"""
=========================================================
UTILS.PY — funções de apoio do pipeline
=========================================================
- log em tela e em arquivo (saida/logs/);
- conversão de formatos brasileiros (número, data, hh:mm:ss);
- id determinístico pela chave natural (hash);
- carga em massa com COPY e upsert pelo banco (INSERT ... ON CONFLICT).
=========================================================
"""

import hashlib
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from psycopg import sql

from pipeline import config

# =========================================================
# LOG
# =========================================================
_logger = None


def log() -> logging.Logger:
    """Logger único da execução: tela + saida/logs/pipeline_<data_hora>.txt"""
    global _logger
    if _logger:
        return _logger
    config.PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    arquivo = config.PASTA_LOGS / f"pipeline_{datetime.now():%Y%m%d_%H%M%S}.txt"
    _logger = logging.getLogger("pipeline")
    _logger.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(arquivo, encoding="utf-8")):
        handler.setFormatter(formato)
        _logger.addHandler(handler)
    return _logger


def mil(n) -> str:
    """12345 -> '12.345'"""
    return f"{n:,}".replace(",", ".")


def titulo(texto: str):
    log().info("=" * 60)
    log().info(texto)
    log().info("=" * 60)


# =========================================================
# CONVERSÕES
# =========================================================
def texto(valor) -> str | None:
    """Tira espaços extras; vazio vira None."""
    if valor is None:
        return None
    t = re.sub(r"\s+", " ", str(valor)).strip()
    return t or None


def numero(valor) -> float | None:
    """'1.250,00' / 'R$ 1.250,00' / '1250.5' / 1250 -> float. Inválido -> None."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    t = str(valor).strip().replace("R$", "").replace(" ", "")
    if not t:
        return None
    if "," in t:                       # padrão brasileiro: ponto = milhar, vírgula = decimal
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def inteiro(valor) -> int | None:
    n = numero(valor)
    return int(round(n)) if n is not None else None


def so_digitos(valor) -> int | None:
    """'85.320 km' / '85320' / 85320.0 -> 85320"""
    if valor is None:
        return None
    if isinstance(valor, float):
        return int(round(valor))
    digitos = re.sub(r"\D", "", str(valor).split(",")[0])
    return int(digitos) if digitos else None


def minutos(valor) -> float | None:
    """'01:15:30' -> 75.5"""
    t = texto(valor)
    if not t or ":" not in t:
        return None
    try:
        h, m, s = (int(p) for p in t.split(":")[:3])
    except ValueError:
        return None
    return round(h * 60 + m + s / 60, 2)


_EPOCA_EXCEL = datetime(1899, 12, 30)


def data_hora(valor) -> datetime | None:
    """Aceita dd/mm/aaaa [hh:mm:ss], aaaa-mm-dd [hh:mm:ss], datetime e serial do Excel."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day)
    if isinstance(valor, (int, float)):
        return _EPOCA_EXCEL + timedelta(days=float(valor))
    t = texto(valor)
    if not t:
        return None
    for formato in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(t, formato)
        except ValueError:
            pass
    if re.fullmatch(r"\d+(\.\d+)?", t):    # serial do Excel gravado como texto
        return _EPOCA_EXCEL + timedelta(days=float(t))
    return None


def data(valor) -> date | None:
    dh = data_hora(valor)
    return dh.date() if dh else None


def sim_nao(valor) -> bool | None:
    t = (texto(valor) or "").lower()
    if t in ("sim", "s", "true", "1"):
        return True
    if t in ("não", "nao", "n", "false", "0"):
        return False
    return None


def gerar_id(*partes) -> str:
    """Hash SHA-256 (32 primeiros caracteres) da chave natural."""
    bruto = "|".join("" if p is None else str(p).strip() for p in partes)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:32]


def hash_arquivo(caminho: Path) -> str:
    """Hash do CONTEÚDO do arquivo, não dos bytes.

    O mesmo dado salvo em outro computador (Windows x Linux, outra versão do
    openpyxl ou do zlib) gera um .xlsx com bytes diferentes. Se o hash fosse dos
    bytes, o pipeline carregaria o mesmo arquivo duas vezes. Por isso:
      - .xlsx: hash dos valores de todas as células, aba por aba;
      - .csv : hash do texto, sem BOM e com quebra de linha padronizada;
      - outros: hash dos bytes.
    """
    h = hashlib.sha256()
    sufixo = caminho.suffix.lower()
    if sufixo in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook   # import local: utils não depende do openpyxl para o resto
        wb = load_workbook(caminho, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                h.update(f"\x1eaba:{ws.title}\n".encode("utf-8"))
                for linha in ws.iter_rows(values_only=True):
                    valores = ["" if v is None else v.isoformat() if hasattr(v, "isoformat") else repr(v) for v in linha]
                    while valores and valores[-1] == "":      # células vazias no fim da linha não mudam o dado
                        valores.pop()
                    h.update(("\x1f".join(valores) + "\n").encode("utf-8"))
        finally:
            wb.close()
    elif sufixo == ".csv":
        texto = caminho.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        h.update(texto.encode("utf-8"))
    else:
        with open(caminho, "rb") as f:
            for bloco in iter(lambda: f.read(1 << 20), b""):
                h.update(bloco)
    return h.hexdigest()


# =========================================================
# BANCO: COPY e UPSERT
# =========================================================
def copiar(cur, tabela: str, colunas: list, linhas) -> int:
    """Carga em massa com COPY (muito mais rápido que INSERT linha a linha)."""
    schema, nome = tabela.split(".")
    comando = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(schema, nome), sql.SQL(", ").join(map(sql.Identifier, colunas)))
    n = 0
    with cur.copy(comando) as cp:
        for linha in linhas:
            cp.write_row(linha)
            n += 1
    return n


def upsert(cur, tabela: str, colunas: list, linhas: list, chave: list,
           modo: str = "substituir", tem_atualizado_em: bool = True) -> tuple:
    """
    Grava as linhas numa tabela temporária com COPY e faz o upsert pelo banco:
        INSERT ... ON CONFLICT (chave) DO UPDATE ... WHERE <algo mudou>
    modo='substituir' -> a versão nova substitui a antiga
    modo='completar'  -> só preenche o que veio vazio antes (COALESCE): um alerta
                         exportado em aberto e depois fechado fica com a versão completa
    Retorna (novos, atualizados). Linhas iguais às do banco não contam como atualizadas.
    """
    if not linhas:
        return 0, 0
    schema, nome = tabela.split(".")
    destino = sql.Identifier(schema, nome)
    temp = sql.Identifier(f"tmp_{nome}")
    cols = sql.SQL(", ").join(map(sql.Identifier, colunas))
    nao_chave = [c for c in colunas if c not in chave]

    cur.execute(sql.SQL("CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP").format(temp, destino))
    copiar(cur, f"pg_temp.tmp_{nome}", colunas, linhas)

    def novo_valor(c):
        if modo == "completar":
            return sql.SQL("COALESCE(EXCLUDED.{c}, {t}.{c})").format(c=sql.Identifier(c), t=sql.Identifier(nome))
        return sql.SQL("EXCLUDED.{}").format(sql.Identifier(c))

    sets = [sql.SQL("{} = {}").format(sql.Identifier(c), novo_valor(c)) for c in nao_chave]
    if tem_atualizado_em:
        sets.append(sql.SQL("atualizado_em = now()"))
    # o lote e o arquivo de origem mudam a cada carga: não contam como "o registro mudou"
    comparar = [c for c in nao_chave if c not in ("id_lote", "arquivo_origem")] or nao_chave
    antes = sql.SQL(", ").join(sql.SQL("{}.{}").format(sql.Identifier(nome), sql.Identifier(c)) for c in comparar)
    depois = sql.SQL(", ").join(novo_valor(c) for c in comparar)

    comando = sql.SQL("""
        INSERT INTO {destino} AS {alias} ({cols})
        SELECT {cols} FROM {temp}
        ON CONFLICT ({chave}) DO UPDATE SET {sets}
        WHERE ({antes}) IS DISTINCT FROM ({depois})
        RETURNING (xmax = 0) AS novo
    """).format(destino=destino, alias=sql.Identifier(nome), cols=cols, temp=temp,
                chave=sql.SQL(", ").join(map(sql.Identifier, chave)),
                sets=sql.SQL(", ").join(sets), antes=antes, depois=depois)
    cur.execute(comando)
    resultado = [r[0] for r in cur.fetchall()]
    cur.execute(sql.SQL("DROP TABLE {}").format(temp))
    novos = sum(resultado)
    return novos, len(resultado) - novos


def lotes_pendentes(cur, fonte: str) -> list:
    """Lotes da bronze daquela fonte que ainda não viraram silver (em ordem de chegada)."""
    cur.execute("""
        SELECT l.id_lote, l.arquivo
        FROM bronze.lote_carga l
        WHERE l.fonte = %s
          AND NOT EXISTS (SELECT 1 FROM silver.lote_processado p WHERE p.id_lote = l.id_lote)
        ORDER BY l.id_lote
    """, (fonte,))
    return cur.fetchall()


def marcar_processados(cur, ids_lote: list):
    if ids_lote:
        cur.executemany("INSERT INTO silver.lote_processado (id_lote) VALUES (%s) ON CONFLICT DO NOTHING",
                        [(i,) for i in ids_lote])
