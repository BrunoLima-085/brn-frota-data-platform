"""
=========================================================
TESTES_QUALIDADE.PY — roda os testes de qualidade do banco
=========================================================
Chama gold.testes_qualidade() (banco/05_testes_qualidade.sql), mostra o
resultado, grava saida/relatorio_qualidade.txt e termina com código de
saída 1 se algum teste CRÍTICO falhar (o Agendador / GitHub Actions
registram a falha).

Uso (na raiz do projeto):  py -m pipeline.testes_qualidade
=========================================================
"""

import sys
from datetime import datetime

from pipeline import config, utils


def rodar() -> bool:
    """Retorna True se nenhum teste crítico falhou."""
    utils.titulo("TESTES DE QUALIDADE")
    with config.conectar() as con, con.cursor() as cur:
        cur.execute("SELECT to_regprocedure('gold.testes_qualidade(numeric)') IS NOT NULL")
        if not cur.fetchone()[0]:
            raise SystemExit("Função de testes não encontrada. Rode banco/05_testes_qualidade.sql no SQL Editor do Supabase.")
        cur.execute("SELECT * FROM gold.testes_qualidade(%s)", (config.OCIOSO_MINIMO_MIN,))
        resultados = cur.fetchall()
        cur.execute("""
            SELECT 'bronze', count(*) FROM bronze.lote_carga UNION ALL
            SELECT 'silver.alertas', count(*) FROM silver.alertas UNION ALL
            SELECT 'silver.viagens', count(*) FROM silver.viagens UNION ALL
            SELECT 'silver.os_manutencao', count(*) FROM silver.os_manutencao UNION ALL
            SELECT 'gold.fato_alertas', count(*) FROM gold.fato_alertas UNION ALL
            SELECT 'gold.fato_utilizacao', count(*) FROM gold.fato_utilizacao UNION ALL
            SELECT 'gold.fato_manutencao', count(*) FROM gold.fato_manutencao
        """)
        contagens = cur.fetchall()

    linhas = [f"Relatório de qualidade — {datetime.now():%d/%m/%Y %H:%M:%S}", ""]
    for camada, teste, critico, falhas, resultado in resultados:
        marca = {"OK": "OK    ", "AVISO": "AVISO ", "FALHOU": "FALHOU"}[resultado]
        texto = f"[{marca}] {camada:<6} | {teste}" + (f" -> {utils.mil(falhas)}" if falhas else "")
        linhas.append(texto)
        (utils.log().error if resultado == "FALHOU" else
         utils.log().warning if resultado == "AVISO" else utils.log().info)(texto)

    linhas += ["", "Contagens:"] + [f"  {t}: {utils.mil(n)}" for t, n in contagens]
    criticos = [r for r in resultados if r[4] == "FALHOU"]
    resumo = (f"{len(resultados)} testes | {sum(r[4] == 'OK' for r in resultados)} OK | "
              f"{sum(r[4] == 'AVISO' for r in resultados)} aviso(s) | {len(criticos)} crítico(s) falhando")
    linhas += ["", resumo]
    utils.log().info(resumo)

    config.SAIDA.mkdir(parents=True, exist_ok=True)
    (config.SAIDA / "relatorio_qualidade.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return not criticos


if __name__ == "__main__":
    sys.exit(0 if rodar() else 1)
