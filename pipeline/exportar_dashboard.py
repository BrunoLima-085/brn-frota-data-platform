"""
=========================================================
EXPORTAR_DASHBOARD.PY — gold (views) -> dashboard/dados.js
=========================================================
O dashboard é um HTML estático: não conecta no banco. Este script lê as
views da gold (banco/07_views.sql) e grava tudo num arquivo só,
dashboard/dados.js, no formato:

    window.DADOS = { ... };

Por ser .js (e não .json), o index.html abre com duplo clique, sem
servidor. Os dados vão em listas de listas, com as colunas descritas
uma vez em "colunas", para o arquivo ficar pequeno. Placa, regra,
centro de custo e data viram índices.

Uso (na raiz do projeto):  py -m pipeline.exportar_dashboard
=========================================================
"""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from pipeline import config, utils

PASTA_DASHBOARD = config.RAIZ / "dashboard"
ARQUIVO_DADOS = PASTA_DASHBOARD / "dados.js"
TOP_PONTOS = 15          # trechos por regra nos pontos de atenção


def _num(v):
    """Decimal -> int/float enxuto (sem .0 sobrando)."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        return int(v) if v.is_integer() else round(v, 2)
    return v


def _ler(cur, sql: str, params=()) -> list:
    cur.execute(sql, params)
    return cur.fetchall()


def exportar() -> dict:
    utils.titulo("DASHBOARD — exportando views da gold para dashboard/dados.js")
    with config.conectar() as con, con.cursor() as cur:
        cur.execute("SELECT to_regclass('gold.vw_os_situacao') IS NOT NULL")
        if not cur.fetchone()[0]:
            raise SystemExit("Views do dashboard não encontradas. Rode banco/07_views.sql no SQL Editor do Supabase.")

        data_ref, = _ler(cur, "SELECT data_ref FROM gold.vw_data_referencia")[0]
        inicio, = _ler(cur, "SELECT MIN(data) FROM gold.fato_utilizacao")[0]
        dias = [inicio + timedelta(days=i) for i in range((data_ref - inicio).days + 1)]
        idx_dia = {d: i for i, d in enumerate(dias)}

        # ---- dimensões ------------------------------------------------
        ccs = _ler(cur, "SELECT id_centro_custo, centro_custo, cidade, regional "
                        "FROM gold.dim_centro_custo ORDER BY centro_custo")
        idx_cc = {c[0]: i for i, c in enumerate(ccs)}

        veics = _ler(cur, """
            SELECT id_veiculo, placa, marca, modelo, tipo, ano_fabricacao, possui_rastreador,
                   id_centro_custo, contrato, operacao, valor_fipe, ano_modelo, cor, chassi, filial,
                   blindagem, status_veiculo
            FROM gold.vw_veiculo_atual ORDER BY placa""")
        idx_v = {v[0]: i for i, v in enumerate(veics)}

        regras = [r[0] for r in _ler(cur, "SELECT DISTINCT nome_regra FROM gold.fato_alertas ORDER BY 1")]
        idx_r = {r: i for i, r in enumerate(regras)}

        def cc(i):
            return idx_cc.get(i, -1)

        # ---- utilização -------------------------------------------------
        uso = [[idx_v[r[0]], idx_dia[r[1]], cc(r[2])] + [_num(x) for x in r[3:]]
               for r in _ler(cur, """
                   SELECT id_veiculo, data, id_centro_custo, viagens, km, horas_uso, horas_ocioso,
                          consumo_l, vel_maxima, frenagens
                   FROM gold.vw_utilizacao_diaria ORDER BY data, id_veiculo""")]

        sem_uso = [[idx_v[r[0]], idx_dia[r[1]], cc(r[2])]
                   for r in _ler(cur, "SELECT id_veiculo, data, id_centro_custo FROM gold.vw_dias_sem_uso "
                                      "WHERE data <= %s ORDER BY data, id_veiculo", (data_ref,))]

        # ---- alertas ----------------------------------------------------
        alertas = [[idx_v[r[0]], idx_dia[r[1]], r[2], cc(r[3]), idx_r[r[4]], r[5], _num(r[6]), _num(r[7])]
                   for r in _ler(cur, """
                       SELECT id_veiculo, data, hora, id_centro_custo, nome_regra, qtd, vel_maxima, ocioso_min
                       FROM gold.vw_alertas_hora WHERE data <= %s ORDER BY data, id_veiculo, hora""", (data_ref,))]

        pontos = [[r[0], r[1], r[2], r[3], r[4], _num(r[5]), _num(r[6]), r[7].isoformat()]
                  for r in _ler(cur, """
                      SELECT nome_regra, trecho, cidade, ocorrencias, veiculos, vel_maxima, ocioso_min, ultima
                      FROM (SELECT p.*, ROW_NUMBER() OVER (PARTITION BY nome_regra ORDER BY ocorrencias DESC, trecho) AS rk
                            FROM gold.vw_pontos_atencao p) t
                      WHERE rk <= %s ORDER BY nome_regra, ocorrencias DESC""", (TOP_PONTOS,))]

        # ---- manutenção -------------------------------------------------
        # (coluna exportada, coluna da view)
        mapa_os = [("numero_os", "numero_os"), ("veic", "id_veiculo"), ("cc", "id_centro_custo"),
                   ("contrato", "contrato"), ("data_os", "data_os"), ("oficina", "oficina"),
                   ("tipo_manutencao", "tipo_manutencao"), ("criticidade", "criticidade"),
                   ("tipo_sistema", "tipo_sistema"), ("descricao", "descricao_problema"),
                   ("status", "status_manutencao"), ("status_operacional", "status_operacional"),
                   ("etapa", "etapa_atual"), ("entrada", "data_entrada_oficina"), ("prevista", "data_prevista_saida"),
                   ("saida", "data_real_saida"), ("orcado", "valor_orcamento"), ("negociado", "valor_negociado"),
                   ("pct_variacao", "pct_variacao"), ("desconto", "desconto_obtido"),
                   ("requisicao", "n_requisicao_pecas"), ("pecas", "valor_pecas"),
                   ("substituto", "veiculo_substituto"), ("placa_substituto", "placa_substituto"),
                   ("tipo_aluguel", "tipo_aluguel"), ("valor_aluguel", "valor_aluguel"),
                   ("d_os_entrada", "dias_os_entrada"), ("d_entrada_orcamento", "dias_entrada_orcamento"),
                   ("d_orcamento_solicitacao", "dias_orcamento_solicitacao"),
                   ("d_solicitacao_aprovacao", "dias_solicitacao_aprovacao"),
                   ("d_aprovacao_pedido", "dias_aprovacao_pedido"), ("d_pedido_compra", "dias_pedido_compra"),
                   ("d_compra_entrega", "dias_compra_entrega"), ("d_entrada_saida", "dias_entrada_saida"),
                   ("dias_parado", "dias_parado"), ("dias_locacao", "dias_locacao"),
                   ("custo_locacao", "custo_locacao"), ("custo_total", "custo_total_parado"),
                   ("atrasada", "atrasada"), ("reincidente", "reincidente")]
        colunas_os = [m[0] for m in mapa_os]
        os_ = []
        for r in _ler(cur, f"SELECT {', '.join(m[1] for m in mapa_os)} "
                           "FROM gold.vw_os_situacao ORDER BY data_os, numero_os"):
            linha = list(r)
            linha[1] = idx_v[linha[1]]
            linha[2] = cc(linha[2])
            os_.append([x.isoformat() if isinstance(x, date) else (int(x) if isinstance(x, bool) else _num(x))
                        for x in linha])

        ultima = {r[0]: [r[1], r[2], r[3], r[4].isoformat() if r[4] else None, r[5]]
                  for r in _ler(cur, "SELECT id_veiculo, numero_os, tipo_manutencao, tipo_sistema, data_ultima, "
                                     "dias_desde FROM gold.vw_ultima_manutencao")}

        sla = [[r[0], r[1], r[2], r[3]] + [_num(x) for x in r[4:]]
               for r in _ler(cur, "SELECT ordem, etapa, meta_dias, os_medidas, media_dias, mediana_dias, "
                                  "p90_dias, pct_na_meta FROM gold.vw_sla_etapas ORDER BY ordem")]

        conducao = [[idx_v[r[0]]] + [_num(x) for x in r[1:]]
                    for r in _ler(cur, "SELECT id_veiculo, km, alertas_bruscos, bruscos_100km, corretivas, "
                                       "custo_corretivo, ordem_faixa FROM gold.vw_conducao_faixas "
                                       "ORDER BY id_veiculo")]
        corr = [_num(x) for x in _ler(cur, "SELECT veiculos, corr_alertas_corretivas, corr_alertas_custo "
                                           "FROM gold.vw_correlacao")[0]]

    dados = {
        "meta": {
            "data_ref": data_ref.isoformat(),
            "inicio": inicio.isoformat(),
            "gerado_em": datetime.now(ZoneInfo("America/Fortaleza")).strftime("%d/%m/%Y %H:%M"),
        },
        "dias": [d.isoformat() for d in dias],
        "cc": [[c[1], c[2], c[3]] for c in ccs],
        "veic": [[v[1], v[2], v[3], v[4], v[5], int(v[6]), cc(v[7]), v[8], v[9], _num(v[10]), v[11], v[12],
                  v[13], v[14], int(bool(v[15])), v[16]] + (ultima.get(v[0]) or [None] * 5) for v in veics],
        "regras": regras,
        "uso": uso,
        "sem_uso": sem_uso,
        "alertas": alertas,
        "pontos": pontos,
        "os": os_,
        "sla": sla,
        "conducao": conducao,
        "corr": corr,
        "colunas": {
            "cc": ["centro_custo", "cidade", "regional"],
            "veic": ["placa", "marca", "modelo", "tipo", "ano", "rastreador", "cc_atual", "contrato",
                     "operacao", "fipe", "ano_modelo", "cor", "chassi", "filial", "blindagem", "status",
                     "ultima_os", "ultima_tipo", "ultima_sistema", "ultima_data", "dias_desde_ultima"],
            "uso": ["veic", "dia", "cc", "viagens", "km", "horas_uso", "horas_ocioso", "consumo_l",
                    "vel_maxima", "frenagens"],
            "sem_uso": ["veic", "dia", "cc"],
            "alertas": ["veic", "dia", "hora", "cc", "regra", "qtd", "vel_maxima", "ocioso_min"],
            "pontos": ["regra", "trecho", "cidade", "ocorrencias", "veiculos", "vel_maxima", "ocioso_min",
                       "ultima"],
            "os": colunas_os,
            "sla": ["ordem", "etapa", "meta_dias", "os_medidas", "media", "mediana", "p90", "pct_na_meta"],
            "conducao": ["veic", "km", "alertas_bruscos", "bruscos_100km", "corretivas", "custo_corretivo",
                         "faixa"],
            "corr": ["veiculos", "corr_alertas_corretivas", "corr_alertas_custo"],
        },
    }

    PASTA_DASHBOARD.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    ARQUIVO_DADOS.write_text("// Gerado por pipeline/exportar_dashboard.py — não editar à mão\n"
                             f"window.DADOS = {texto};\n", encoding="utf-8")
    tamanho = ARQUIVO_DADOS.stat().st_size / 1024 / 1024
    resumo = {"veiculos": len(veics), "dias": len(dias), "uso": len(uso), "alertas": len(alertas),
              "os": len(os_), "mb": round(tamanho, 2)}
    utils.log().info(f"dados.js: {tamanho:.2f} MB | {utils.mil(len(uso))} linhas de uso | "
                     f"{utils.mil(len(alertas))} de alertas | {len(os_)} OS | data de referência {data_ref:%d/%m/%Y}")
    return resumo


if __name__ == "__main__":
    exportar()
