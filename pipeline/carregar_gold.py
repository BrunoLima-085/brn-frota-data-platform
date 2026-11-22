"""
=========================================================
CARREGAR_GOLD.PY — dispara a montagem da gold (feita em SQL)
=========================================================
A modelagem dimensional mora no banco (banco/04_carga_gold.sql).
Este script só chama as funções e mostra o resultado de cada tabela.

Uso (na raiz do projeto):  py -m pipeline.carregar_gold
=========================================================
"""

from pipeline import config, utils

FUNCOES = [
    ("Dimensões", "SELECT * FROM gold.carregar_dimensoes()", ()),
    ("Fatos de telemetria", "SELECT * FROM gold.carregar_fatos_telemetria(%s)", (config.OCIOSO_MINIMO_MIN,)),
    ("Fato de manutenção", "SELECT * FROM gold.carregar_fato_manutencao()", ()),
]


def carregar(etapas: list = None) -> dict:
    utils.titulo("GOLD — modelo dimensional (funções SQL)")
    resumo = {}
    with config.conectar() as con, con.transaction(), con.cursor() as cur:
        cur.execute("SELECT to_regprocedure('gold.carregar_dimensoes()') IS NOT NULL "
                    "AND to_regprocedure('gold.carregar_fato_manutencao()') IS NOT NULL")
        if not cur.fetchone()[0]:
            raise SystemExit("Funções da gold não encontradas. Rode banco/04_carga_gold.sql no SQL Editor do Supabase.")
        for nome, comando, params in FUNCOES:
            if etapas and nome not in etapas:
                continue
            cur.execute(comando, params)
            utils.log().info(f"[{nome}]")
            for tabela, inseridos, atualizados in cur.fetchall():
                resumo[tabela] = (inseridos, atualizados)
                utils.log().info(f"    {tabela}: novos {utils.mil(inseridos)} | atualizados/removidos {utils.mil(atualizados)}")
        cur.execute("""
            SELECT 'dim_veiculo', count(*) FROM gold.dim_veiculo UNION ALL
            SELECT 'dim_alocacao', count(*) FROM gold.dim_alocacao UNION ALL
            SELECT 'fato_alertas', count(*) FROM gold.fato_alertas UNION ALL
            SELECT 'fato_utilizacao', count(*) FROM gold.fato_utilizacao UNION ALL
            SELECT 'fato_manutencao', count(*) FROM gold.fato_manutencao
            ORDER BY 1
        """)
        utils.log().info("Totais na gold: " + " | ".join(f"{t}: {utils.mil(n)}" for t, n in cur.fetchall()))
    return resumo


if __name__ == "__main__":
    carregar()
