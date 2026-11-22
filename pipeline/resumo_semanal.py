"""
=========================================================
RESUMO_SEMANAL.PY — relatório da semana, só com Python + SQL
=========================================================
Gera docs/resumos/resumo_semanal_<inicio>_a_<fim>.md (vai para o git) com:
  - indicadores da semana x semana anterior (km, viagens, alertas,
    alertas por 1.000 km, consumo, horas de motor ocioso);
  - os 5 veículos com mais alertas por 1.000 km (ranking com window function);
  - alertas por regra;
  - manutenção: OS abertas, concluídas, valor negociado, veículos parados
    e onde as OS em andamento estão travadas;
  - pendências de qualidade (outliers para revisar, OS em quarentena).
Sem IA: os textos são montados a partir dos números.

Semana padrão = a última semana FECHADA (segunda a domingo) com dados.
Rodando todo dia, o arquivo da semana é só reescrito até a semana virar.
Uso (na raiz do projeto):
    py -m pipeline.resumo_semanal
    py -m pipeline.resumo_semanal --ate 2026-10-24
=========================================================
"""

import argparse
from datetime import date, timedelta

from pipeline import config, utils

SQL_INDICADORES = """
WITH periodos AS (
    SELECT 'atual' AS periodo, %(ini)s::date AS ini, %(fim)s::date AS fim
    UNION ALL
    SELECT 'anterior', %(ini)s::date - 7, %(fim)s::date - 7
),
uso AS (
    SELECT p.periodo, sum(u.distancia_km) AS km, count(*) AS viagens, sum(u.consumo_l) AS litros,
           sum(u.motor_ocioso_min) / 60.0 AS horas_ociosas
    FROM periodos p JOIN gold.fato_utilizacao u ON u.data BETWEEN p.ini AND p.fim
    GROUP BY p.periodo
),
alertas AS (
    SELECT p.periodo, count(*) AS alertas
    FROM periodos p JOIN gold.fato_alertas a ON a.data BETWEEN p.ini AND p.fim
    GROUP BY p.periodo
)
SELECT p.periodo, COALESCE(u.km, 0), COALESCE(u.viagens, 0), COALESCE(a.alertas, 0),
       ROUND(COALESCE(a.alertas, 0) / NULLIF(u.km, 0) * 1000, 2), COALESCE(u.litros, 0), COALESCE(u.horas_ociosas, 0)
FROM periodos p LEFT JOIN uso u USING (periodo) LEFT JOIN alertas a USING (periodo)
"""

SQL_TOP_VEICULOS = """
WITH km AS (
    SELECT id_veiculo, sum(distancia_km) AS km
    FROM gold.fato_utilizacao WHERE data BETWEEN %(ini)s AND %(fim)s GROUP BY id_veiculo
),
al AS (
    SELECT id_veiculo, count(*) AS alertas,
           count(*) FILTER (WHERE nome_regra IN ('Freada brusca', 'Aceleração brusca', 'Curva brusca')) AS conducao
    FROM gold.fato_alertas WHERE data BETWEEN %(ini)s AND %(fim)s GROUP BY id_veiculo
),
ranking AS (
    SELECT v.placa, v.marca || ' ' || v.modelo AS modelo, cc.centro_custo, km.km, al.alertas, al.conducao,
           ROUND(al.alertas / km.km * 1000, 1) AS por_mil_km,
           RANK() OVER (ORDER BY al.alertas / km.km DESC) AS posicao
    FROM km JOIN al USING (id_veiculo)
    JOIN gold.dim_veiculo v USING (id_veiculo)
    LEFT JOIN gold.dim_alocacao a ON a.id_veiculo = v.id_veiculo
         AND %(fim)s BETWEEN a.data_inicio AND COALESCE(a.data_fim, 'infinity'::date)
    LEFT JOIN gold.dim_centro_custo cc ON cc.id_centro_custo = a.id_centro_custo
    WHERE km.km >= 100                        -- evita distorção de quem quase não rodou
)
SELECT posicao, placa, modelo, centro_custo, km, alertas, conducao, por_mil_km
FROM ranking WHERE posicao <= 5 ORDER BY posicao
"""

SQL_REGRAS = """
SELECT nome_regra,
       count(*) FILTER (WHERE data BETWEEN %(ini)s AND %(fim)s) AS atual,
       count(*) FILTER (WHERE data BETWEEN %(ini)s::date - 7 AND %(fim)s::date - 7) AS anterior
FROM gold.fato_alertas
WHERE data BETWEEN %(ini)s::date - 7 AND %(fim)s
GROUP BY nome_regra ORDER BY atual DESC
"""

SQL_MANUTENCAO = """
SELECT
    count(*) FILTER (WHERE data_os BETWEEN %(ini)s AND %(fim)s)                           AS abertas,
    count(*) FILTER (WHERE data_real_saida BETWEEN %(ini)s AND %(fim)s)                   AS concluidas,
    COALESCE(sum(valor_negociado) FILTER (WHERE data_aprovacao BETWEEN %(ini)s AND %(fim)s), 0) AS liberado,
    count(*) FILTER (WHERE data_entrada_oficina <= %(fim)s
                       AND (data_real_saida IS NULL OR data_real_saida > %(fim)s)
                       AND status_operacional = 'Parado')                                AS parados
FROM gold.fato_manutencao
"""

SQL_ETAPAS = """
-- etapa de cada OS no FIM da semana (não a de hoje): a última data preenchida até lá
WITH na_data AS (
    SELECT CASE
               WHEN data_entrega_peca    <= %(fim)s THEN 'Em manutenção'
               WHEN data_aprovacao       <= %(fim)s THEN 'Aguardando peças'
               WHEN data_orcamento       <= %(fim)s THEN 'Aguardando aprovação'
               WHEN data_entrada_oficina <= %(fim)s THEN 'Em diagnóstico'
               ELSE 'Em agendamento'
           END AS etapa,
           %(fim)s::date - data_os AS dias
    FROM gold.fato_manutencao
    WHERE data_os <= %(fim)s AND (data_real_saida IS NULL OR data_real_saida > %(fim)s)
)
SELECT etapa, count(*), ROUND(avg(dias), 1) AS dias_medios
FROM na_data
GROUP BY etapa ORDER BY 2 DESC
"""

SQL_PENDENCIAS = """
SELECT (SELECT count(*) FROM silver.outliers_telemetria WHERE status = 'Pendente'),
       (SELECT count(DISTINCT numero_os) FROM silver.quarentena_manutencao)
"""


def _variacao(atual, anterior) -> str:
    if not anterior:
        return "—"
    v = (float(atual) - float(anterior)) / float(anterior) * 100
    seta = "▲" if v > 0 else "▼" if v < 0 else "="
    return f"{seta} {abs(v):.1f}%".replace(".", ",")


def _n(valor, casas=0) -> str:
    texto = f"{float(valor):,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def gerar(ate: date = None) -> str:
    utils.titulo("RESUMO SEMANAL")
    with config.conectar() as con, con.cursor() as cur:
        if ate is None:
            cur.execute("SELECT max(data) FROM gold.fato_utilizacao")
            ultimo_dia = cur.fetchone()[0]
            if ultimo_dia is None:
                raise SystemExit("Sem dados na gold: rode o pipeline antes.")
            ate = ultimo_dia - timedelta(days=ultimo_dia.isoweekday() % 7)   # último domingo
        ini = ate - timedelta(days=6)
        p = {"ini": ini, "fim": ate}
        cur.execute(SQL_INDICADORES, p)
        ind = {linha[0]: linha[1:] for linha in cur.fetchall()}
        cur.execute(SQL_TOP_VEICULOS, p)
        top = cur.fetchall()
        cur.execute(SQL_REGRAS, p)
        regras = cur.fetchall()
        cur.execute(SQL_MANUTENCAO, p)
        abertas, concluidas, liberado, parados = cur.fetchone()
        cur.execute(SQL_ETAPAS, p)
        etapas = cur.fetchall()
        cur.execute(SQL_PENDENCIAS)
        outliers_pend, quarentena = cur.fetchone()

    atual, anterior = ind["atual"], ind["anterior"]
    nomes = ["Km rodados", "Viagens", "Alertas", "Alertas por 1.000 km", "Consumo (litros)", "Motor ocioso (horas)"]
    casas = [0, 0, 0, 2, 0, 1]

    md = [f"# Resumo semanal da frota — {ini:%d/%m/%Y} a {ate:%d/%m/%Y}", "",
          "_Gerado automaticamente pelo pipeline (Python + SQL), dados fictícios._", "",
          "## Indicadores da semana", "", "| Indicador | Semana | Semana anterior | Variação |",
          "| --- | ---: | ---: | ---: |"]
    for nome, c, a, b in zip(nomes, casas, atual, anterior):
        md.append(f"| {nome} | {_n(a or 0, c)} | {_n(b or 0, c)} | {_variacao(a or 0, b or 0)} |")

    md += ["", "## Veículos com mais alertas por 1.000 km", "",
           "| # | Placa | Modelo | Centro de custo | Km | Alertas | Freada/aceleração/curva | Alertas/1.000 km |",
           "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |"]
    for pos, placa, modelo, cc, km, al, cond, pmk in top:
        md.append(f"| {pos} | {placa} | {modelo} | {cc or '—'} | {_n(km)} | {al} | {cond} | {_n(pmk, 1)} |")

    md += ["", "## Alertas por regra", "", "| Regra | Semana | Semana anterior | Variação |",
           "| --- | ---: | ---: | ---: |"]
    for regra, a, b in regras:
        md.append(f"| {regra} | {a} | {b} | {_variacao(a, b)} |")

    md += ["", "## Manutenção", "",
           f"- OS abertas na semana: **{abertas}** | concluídas: **{concluidas}**",
           f"- Valor negociado (aprovações da semana): **R$ {_n(liberado, 2)}**",
           f"- Veículos parados na oficina no fim da semana: **{parados}**"]
    if etapas:
        md += ["", "| OS em andamento por etapa | Quantidade | Dias desde a abertura (média) |", "| --- | ---: | ---: |"]
        md += [f"| {etapa} | {qtd} | {_n(dias, 1)} |" for etapa, qtd, dias in etapas]

    md += ["", "## Pendências de qualidade", "",
           f"- Outliers aguardando revisão: **{outliers_pend}** (saida/outliers_para_revisao.xlsx)",
           f"- OS em quarentena: **{quarentena}**"]

    # destaque em texto, montado a partir dos números
    destaques = []
    if top:
        destaques.append(f"{top[0][1]} lidera os alertas por 1.000 km ({_n(top[0][7], 1)}), "
                         f"com {top[0][6]} eventos de condução brusca.")
    if anterior[3]:
        destaques.append(f"Alertas por 1.000 km: {_n(atual[3] or 0, 2)} ({_variacao(atual[3] or 0, anterior[3])} "
                         "em relação à semana anterior).")
    if etapas:
        etapa, qtd, dias = etapas[0]
        destaques.append(f"Etapa com mais OS paradas: {etapa} ({qtd} OS, {_n(dias, 1)} dias desde a abertura em média).")
    md[4:4] = ["## Destaques", ""] + [f"- {d}" for d in destaques] + [""]

    pasta = config.PASTA_RESUMOS
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"resumo_semanal_{ini:%Y-%m-%d}_a_{ate:%Y-%m-%d}.md"
    arquivo.write_text("\n".join(md) + "\n", encoding="utf-8")
    utils.log().info(f"Resumo gravado: {arquivo.relative_to(config.RAIZ)}")
    for d in destaques:
        utils.log().info(f"  {d}")
    return str(arquivo)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera o resumo semanal da frota.")
    parser.add_argument("--ate", type=date.fromisoformat, help="último dia da semana (AAAA-MM-DD)")
    gerar(parser.parse_args().ate)
