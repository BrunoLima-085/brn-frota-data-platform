"""
=========================================================
OUTLIERS.PY — detecção e revisão manual de registros suspeitos
=========================================================
Regras (fisicamente impossível = erro do rastreador):
  viagem: distância negativa, consumo negativo, eficiência > 100 km/l,
          velocidade média implícita > 200 km/h (ex.: 300 mil km em 3 h)
  alerta: excesso de velocidade >= 150 km/h SEM variação de odômetro
          (com odômetro confirmando, o alerta é mantido)

Distância ou consumo negativos não podem ser aprovados (o banco também
recusa na gold, por CHECK). Os demais podem: o detector pode errar.

Fluxo de revisão (substitui a conferência manual em planilha):
  1. suspeito vai para silver.outliers_telemetria com status 'Pendente'
     e o registro completo em JSONB — fica fora da silver e da gold;
  2. o pipeline gera saida/outliers_para_revisao.xlsx com a coluna
     "Revisado" (lista: Pendente / Aprovado / Rejeitado);
  3. na rodada seguinte, as decisões da planilha voltam para o banco:
       Aprovado  -> o registro (guardado no JSONB) entra na silver;
       Rejeitado -> fica fora para sempre (se tinha entrado, sai);
       Pendente  -> continua aguardando.
=========================================================
"""

import json
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from pipeline import config, utils

STATUS_VALIDOS = ("Pendente", "Aprovado", "Rejeitado")
# valores que nunca podem estar certos: não aceitam "Aprovado" (o banco também recusaria na gold)
NAO_APROVAVEIS = ("Distância negativa", "Consumo negativo")


# ---------------------------------------------------------
# Regras
# ---------------------------------------------------------
def motivo_viagem(r: dict) -> str | None:
    dist, dur, cons, efic = r["distancia_km"], r["duracao_min"], r["consumo_l"], r["eficiencia_km_l"]
    if dist is not None and dist < 0:
        return "Distância negativa"
    if cons is not None and cons < 0:
        return "Consumo negativo"
    if dist is not None and dur and dur > 0 and dist / (dur / 60) > config.VELOCIDADE_IMPLICITA_MAX:
        return f"Velocidade implícita acima de {config.VELOCIDADE_IMPLICITA_MAX} km/h ({utils.mil(round(dist / (dur / 60)))} km/h)"
    if efic is not None and efic > config.EFICIENCIA_MAX_KM_L:
        return f"Eficiência acima de {config.EFICIENCIA_MAX_KM_L} km/l"
    return None


def motivo_alerta(r: dict) -> str | None:
    if (r["nome_regra"] == "Excesso de velocidade"
            and (r.get("_vel_max") or 0) >= config.VELOCIDADE_CONFIAVEL_KMH
            and r["odometro_final"] is not None
            and r["odometro_final"] == r["odometro_inicial"]):
        return f"Velocidade >= {config.VELOCIDADE_CONFIAVEL_KMH} km/h sem variação de odômetro (erro do equipamento)"
    return None


# ---------------------------------------------------------
# Banco
# ---------------------------------------------------------
def status_atuais(cur) -> dict:
    cur.execute("SELECT id_registro, status FROM silver.outliers_telemetria")
    return {i.strip(): s for i, s in cur.fetchall()}


def registrar(cur, suspeitos: list) -> int:
    """Grava suspeitos novos como Pendente. Já revisados não são tocados."""
    if not suspeitos:
        return 0
    novos = 0
    for tipo, id_registro, placa, motivo, dados in suspeitos:
        cur.execute("""
            INSERT INTO silver.outliers_telemetria (id_registro, tipo_registro, placa, motivo, dados)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (id_registro) DO UPDATE
               SET dados = EXCLUDED.dados, motivo = EXCLUDED.motivo
             WHERE silver.outliers_telemetria.status = 'Pendente'
            RETURNING (xmax = 0)
        """, (id_registro, tipo, placa, motivo, json.dumps(dados, default=str, ensure_ascii=False)))
        linha = cur.fetchone()
        novos += 1 if linha and linha[0] else 0
    return novos


def aprovados_fora_da_silver(cur, tipo: str) -> list:
    """Aprovados que ainda não estão na silver (ex.: aprovados depois da carga) -> reinjetar."""
    tabela, chave = ("silver.viagens", "id_viagem") if tipo == "viagem" else ("silver.alertas", "id_evento")
    cur.execute(f"""
        SELECT o.dados FROM silver.outliers_telemetria o
        WHERE o.tipo_registro = %s AND o.status = 'Aprovado'
          AND NOT EXISTS (SELECT 1 FROM {tabela} s WHERE s.{chave} = o.id_registro)
    """, (tipo,))
    return [linha[0] for linha in cur.fetchall()]


def remover_rejeitados_da_silver(cur) -> int:
    """Se alguém mudou um Aprovado para Rejeitado, o registro sai da silver."""
    total = 0
    for tabela, chave, tipo in (("silver.viagens", "id_viagem", "viagem"), ("silver.alertas", "id_evento", "alerta")):
        cur.execute(f"""
            DELETE FROM {tabela} s USING silver.outliers_telemetria o
            WHERE o.tipo_registro = %s AND o.status = 'Rejeitado' AND s.{chave} = o.id_registro
        """, (tipo,))
        total += cur.rowcount
    return total


# ---------------------------------------------------------
# Planilha de revisão
# ---------------------------------------------------------
def aplicar_decisoes_da_planilha(cur) -> dict:
    """Lê a coluna 'Revisado' da planilha e atualiza o status no banco."""
    contagem = {"Aprovado": 0, "Rejeitado": 0, "Pendente": 0}
    arquivo = config.ARQUIVO_REVISAO_OUTLIERS
    if not arquivo.exists():
        return contagem
    wb = load_workbook(arquivo, read_only=True, data_only=True)
    linhas = list(wb.active.iter_rows(values_only=True))
    wb.close()
    if not linhas:
        return contagem
    cab = [str(c).strip() if c else "" for c in linhas[0]]
    if "id_registro" not in cab or "Revisado" not in cab:
        utils.log().warning(f"{arquivo.name}: colunas 'id_registro'/'Revisado' não encontradas; decisões ignoradas")
        return contagem
    i_id, i_rev = cab.index("id_registro"), cab.index("Revisado")
    atuais = status_atuais(cur)
    cur.execute("SELECT id_registro, motivo FROM silver.outliers_telemetria")
    motivos = {i.strip(): m for i, m in cur.fetchall()}
    for linha in linhas[1:]:
        id_registro = utils.texto(linha[i_id]) if i_id < len(linha) else None
        decisao = utils.texto(linha[i_rev]) if i_rev < len(linha) else None
        decisao = (decisao or "Pendente").capitalize()
        if not id_registro or decisao not in STATUS_VALIDOS or atuais.get(id_registro) in (None, decisao):
            continue
        if decisao == "Aprovado" and motivos.get(id_registro) in NAO_APROVAVEIS:
            utils.log().warning(f"  {id_registro}: '{motivos[id_registro]}' não pode ser aprovado "
                                "(valor fisicamente impossível) — decisão ignorada")
            contagem["recusadas"] = contagem.get("recusadas", 0) + 1
            continue
        cur.execute("""
            UPDATE silver.outliers_telemetria
               SET status = %s, revisado_em = CASE WHEN %s = 'Pendente' THEN NULL ELSE now() END
             WHERE id_registro = %s
        """, (decisao, decisao, id_registro))
        contagem[decisao] += 1
    return contagem


def exportar_planilha(cur):
    """Gera saida/outliers_para_revisao.xlsx com todos os suspeitos e o status atual."""
    cur.execute("""
        SELECT id_registro, tipo_registro, placa, motivo, status,
               COALESCE(dados->>'data_inicial', dados->>'data_hora_evento') AS data_registro,
               dados->>'distancia_km', dados->>'duracao_min', dados->>'eficiencia_km_l', dados->>'valor_metrica',
               detectado_em, revisado_em
        FROM silver.outliers_telemetria
        ORDER BY CASE status WHEN 'Pendente' THEN 0 ELSE 1 END, tipo_registro, placa, data_registro
    """)
    linhas = cur.fetchall()
    cab = ["id_registro", "tipo_registro", "placa", "motivo", "Revisado", "data_registro", "distancia_km",
           "duracao_min", "eficiencia_km_l", "velocidade_media", "detectado_em", "revisado_em"]
    wb = Workbook()
    ws = wb.active
    ws.title = "outliers"
    ws.append(cab)
    for linha in linhas:
        ws.append([v.replace(tzinfo=None) if isinstance(v, datetime) and v.tzinfo else v for v in linha])

    col = cab.index("Revisado") + 1
    letra = ws.cell(row=1, column=col).column_letter
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.cell(row=1, column=col).fill = PatternFill("solid", start_color="FFD966")
    ultima = max(ws.max_row, 500)
    for n in range(2, ultima + 1):
        celula = ws.cell(row=n, column=col)
        celula.fill = PatternFill("solid", start_color="FFF2CC")
        celula.alignment = Alignment(horizontal="center")
    dv = DataValidation(type="list", formula1='"Pendente,Aprovado,Rejeitado"', allow_blank=True)
    dv.error, dv.errorTitle = "Escolha Pendente, Aprovado ou Rejeitado.", "Valor inválido"
    ws.add_data_validation(dv)
    dv.add(f"{letra}2:{letra}{ultima}")
    for letra_col, largura in zip("ABCDEFGHIJKL", (34, 12, 10, 60, 12, 20, 13, 12, 15, 16, 20, 20)):
        ws.column_dimensions[letra_col].width = largura
    ws.freeze_panes = "A2"

    config.SAIDA.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(config.ARQUIVO_REVISAO_OUTLIERS)
    except PermissionError:
        utils.log().warning(f"{config.ARQUIVO_REVISAO_OUTLIERS.name} está aberta no Excel; "
                            "feche e rode de novo para atualizar a planilha de revisão.")
        return len(linhas), False
    return len(linhas), True
