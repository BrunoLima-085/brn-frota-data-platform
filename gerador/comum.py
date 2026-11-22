"""
=========================================================
COMUM.PY — funções compartilhadas pelos geradores
=========================================================
Projeto: brn-frota-data-platform (dados 100% fictícios)

O que tem aqui:
- caminhos do projeto (sempre relativos à raiz, via pathlib);
- parâmetros do período simulado e semente fixa;
- formatação no padrão brasileiro (vírgula decimal, hh:mm:ss);
- período da simulação: base fixa de 6 meses + (opcional) dias novos até
  "ontem", um por execução (--ate), sem alterar os dias anteriores;
- plano diário de km de cada veículo, usado pela telemetria E pela
  manutenção (assim o KM Atual da OS bate com o odômetro do rastreador);
- gravação de xlsx determinística: o Excel guarda data/hora de criação
  dentro do arquivo, o que mudaria o hash a cada execução. Aqui essas
  datas são fixadas, então rodar duas vezes gera arquivos idênticos.
=========================================================
"""

import csv
import hashlib
import io
import random
import re
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------
# Caminhos
# ---------------------------------------------------------
RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = RAIZ / "entrada"
PASTA_FROTA = ENTRADA / "frota"
PASTA_TELEMETRIA = ENTRADA / "telemetria"
PASTA_MANUTENCAO = ENTRADA / "manutencao"
PASTA_GABARITO = ENTRADA / "_gabarito"  # o que foi plantado de propósito (para conferência; o pipeline não lê)

# ---------------------------------------------------------
# Parâmetros da simulação
# ---------------------------------------------------------
SEMENTE = 42
INICIO_PERIODO = date(2026, 5, 1)
BASE_FIM = date(2026, 10, 31)             # base fixa de 6 meses (exportações semanais)
FIM_PERIODO = BASE_FIM                    # "hoje" da simulação; com --ate avança dia a dia
DATA_FIXA_ARQUIVO = datetime(2026, 11, 1, 0, 0, 0)  # data gravada dentro dos xlsx
FUSO = "America/Fortaleza"


def configurar_periodo(ate=None) -> date:
    """
    Define até que dia a simulação vai.
      None / "base"  -> 31/10/2026 (base fixa, reproduzível)
      "ontem"        -> ontem no fuso de Fortaleza (modo contínuo: um dia novo por execução)
      "AAAA-MM-DD"   -> até essa data
    Cada dia tem semente própria: avançar a data acrescenta dias novos e
    NÃO muda nenhum dia anterior.
    """
    global FIM_PERIODO
    if ate in (None, "", "base"):
        FIM_PERIODO = BASE_FIM
    elif ate == "ontem":
        from zoneinfo import ZoneInfo
        FIM_PERIODO = datetime.now(ZoneInfo(FUSO)).date() - timedelta(days=1)
    else:
        FIM_PERIODO = ate if isinstance(ate, date) else date.fromisoformat(str(ate))
    if FIM_PERIODO < BASE_FIM:
        raise SystemExit(f"--ate não pode ser antes de {BASE_FIM:%d/%m/%Y} (fim da base fixa)")
    return FIM_PERIODO


def argumentos(descricao: str):
    """Argumento --ate comum aos geradores."""
    import argparse
    parser = argparse.ArgumentParser(description=descricao)
    parser.add_argument("--ate", default=None,
                        help="base (padrão, até 31/10/2026) | ontem | AAAA-MM-DD")
    args = parser.parse_args()
    configurar_periodo(args.ate)
    return args

NOME_EMPRESA = "Frota Exemplo Locações"
UNIDADE_ORGANIZACIONAL = f"Admin - {NOME_EMPRESA}"


def rng_de(*partes) -> random.Random:
    """Gerador aleatório próprio para cada item (veículo, dia...).
    Depende só da semente e das partes, não da ordem em que o código roda."""
    texto = "|".join(str(p) for p in (SEMENTE, *partes))
    semente = int(hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(semente)


def dias_do_periodo(ate: date = None):
    d, fim = INICIO_PERIODO, ate or FIM_PERIODO
    while d <= fim:
        yield d
        d += timedelta(days=1)


# ---------------------------------------------------------
# Formatação brasileira
# ---------------------------------------------------------
def numero_br(valor: float, casas: int = 2) -> str:
    """1234.5 -> '1.234,50'"""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def hhmmss(minutos: float) -> str:
    """75.5 minutos -> '01:15:30'"""
    segundos = int(round(minutos * 60))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def data_br(d) -> str:
    return d.strftime("%d/%m/%Y")


def data_hora_br(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y %H:%M:%S")


# ---------------------------------------------------------
# Leitura da frota gerada (a "verdade" das dimensões)
# ---------------------------------------------------------
def ler_csv(caminho: Path) -> list:
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def gravar_csv(caminho: Path, linhas: list, colunas: list):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colunas, lineterminator="\n")
        w.writeheader()
        w.writerows(linhas)


def carregar_frota() -> dict:
    if not (PASTA_FROTA / "veiculos.csv").exists():
        raise SystemExit("Frota não encontrada. Rode antes: py gerador/gerar_frota.py")
    return {
        "veiculos": ler_csv(PASTA_FROTA / "veiculos.csv"),
        "alocacao": ler_csv(PASTA_FROTA / "alocacao.csv"),
        "centros": ler_csv(PASTA_FROTA / "centros_custo.csv"),
        "motoristas": ler_csv(PASTA_FROTA / "motoristas.csv"),
        "perfis": ler_csv(PASTA_GABARITO / "perfis_veiculos.csv"),
    }


def descricao_unidade(v: dict) -> str:
    """Texto da coluna 'Unidade rastreada': 'PLACA - MODELO Cor AA/AA'."""
    fab, mod = int(v["Ano_Fabricacao"]), int(v["Ano_Modelo"])
    return f'{v["Placa"]} - {v["Marca"]} {v["Modelo"]} {v["Cor"]} {fab % 100:02d}/{mod % 100:02d}'


def estilo_conducao(placa: str, perfil: str) -> float:
    """Multiplicador da taxa de alertas de condução do veículo (1 = média da frota).
    Normal varia de 0,5 a 1,9 (motoristas diferentes); agressivo fica perto de 3x."""
    r = rng_de("estilo_conducao", placa)
    base = r.uniform(0.5, 1.9)
    return 3.0 * r.uniform(0.85, 1.2) if perfil == "agressivo" else base


def centro_custo_na_data(alocacoes: list, placa: str, dia: date) -> dict:
    """Alocação vigente da placa na data (data_fim vazia = vigente)."""
    for a in alocacoes:
        if a["Placa"] != placa:
            continue
        ini = date.fromisoformat(a["Data_Inicio"])
        fim = date.fromisoformat(a["Data_Fim"]) if a["Data_Fim"] else date.max
        if ini <= dia <= fim:
            return a
    return {}


# ---------------------------------------------------------
# Plano diário de km (compartilhado por telemetria e manutenção)
# ---------------------------------------------------------
KM_DIA_POR_TIPO = {   # (mínimo, máximo) de km rodados num dia útil
    "Leve": (40, 140),
    "Pick-up": (60, 200),
    "Van": (60, 180),
    "Caminhão": (80, 260),
    "Ônibus": (120, 300),
    "Moto": (30, 110),
}


def odometro_inicial(v: dict) -> float:
    r = rng_de("odo_ini", v["Placa"])
    idade = min(max(BASE_FIM.year - int(v["Ano_Fabricacao"]), 0), 12)  # veículos antigos rodam menos por ano
    media_ano = {"Leve": 18000, "Pick-up": 28000, "Van": 32000,
                 "Caminhão": 50000, "Ônibus": 60000, "Moto": 12000}[v["Tipo"]]
    return round(idade * media_ano * r.uniform(0.7, 1.2) + r.uniform(500, 8000), 2)


def plano_km(v: dict, ate: date = None) -> dict:
    """{data: km_rodados_no_dia}. Domingo quase parado, sábado reduzido.
    Cada dia usa a própria semente: o plano de um dia nunca muda."""
    lo, hi = KM_DIA_POR_TIPO[v["Tipo"]]
    plano = {}
    for d in dias_do_periodo(ate):
        r = rng_de("km_dia", v["Placa"], d.isoformat())
        if d.weekday() == 6:
            km = r.uniform(0, lo * 0.4) if r.random() < 0.3 else 0.0
        elif d.weekday() == 5:
            km = r.uniform(lo * 0.3, hi * 0.6) if r.random() < 0.6 else 0.0
        else:
            km = r.uniform(lo, hi) if r.random() < 0.93 else 0.0
        plano[d] = round(km, 2)
    return plano


def odometro_na_data(v: dict, plano: dict, dia: date) -> float:
    """Odômetro no começo do dia."""
    total = odometro_inicial(v)
    for d, km in plano.items():
        if d >= dia:
            break
        total += km
    return round(total, 2)


# ---------------------------------------------------------
# xlsx determinístico
# ---------------------------------------------------------
_DATA_ZIP = (2026, 11, 1, 0, 0, 0)
_REGEX_DATAS_CORE = re.compile(r"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)")


def salvar_xlsx(wb, caminho: Path):
    """Grava o workbook com datas internas fixas -> mesmo conteúdo, mesmo hash."""
    wb.properties.creator = NOME_EMPRESA
    wb.properties.lastModifiedBy = NOME_EMPRESA
    wb.properties.created = DATA_FIXA_ARQUIVO
    wb.properties.modified = DATA_FIXA_ARQUIVO

    bruto = io.BytesIO()
    wb.save(bruto)
    bruto.seek(0)

    caminho.parent.mkdir(parents=True, exist_ok=True)
    fixa = DATA_FIXA_ARQUIVO.strftime("%Y-%m-%dT%H:%M:%SZ")
    with zipfile.ZipFile(bruto) as origem, zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as destino:
        for info in origem.infolist():
            dados = origem.read(info.filename)
            if info.filename == "docProps/core.xml":
                dados = _REGEX_DATAS_CORE.sub(lambda m: m.group(1) + fixa + m.group(2), dados.decode("utf-8")).encode("utf-8")
            novo = zipfile.ZipInfo(info.filename, date_time=_DATA_ZIP)
            novo.compress_type = zipfile.ZIP_DEFLATED
            novo.external_attr = 0o600 << 16
            destino.writestr(novo, dados)
