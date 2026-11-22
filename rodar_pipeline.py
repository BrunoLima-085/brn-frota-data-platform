"""
=========================================================
RODAR_PIPELINE.PY — orquestrador: um comando roda tudo
=========================================================
Etapas, nesta ordem:
  gerar       (opcional) gera os dados fictícios em entrada/
  bronze      arquivos de entrada -> bronze (lote por hash)
  frota       cadastros -> silver
  telemetria  alertas e viagens -> silver (+ revisão de outliers)
  manutencao  OS -> silver (+ quarentena)
  gold        modelo dimensional montado pelas funções SQL
  testes      testes de qualidade (crítico falhando -> código de saída 1)
  retencao    apaga linhas brutas antigas da bronze (mantém o registro dos lotes)
  resumo      resumo semanal em docs/resumos/

No fim grava docs/status_pipeline.md (data da execução, resultado, totais).

Exemplos (na raiz do projeto):
  py rodar_pipeline.py --gerar-dados               # simulação até ontem (um dia novo por dia)
  py rodar_pipeline.py --gerar-dados --ate base    # só a base fixa de 6 meses (reproduzível)
  py rodar_pipeline.py --etapas telemetria,gold,testes
  py rodar_pipeline.py --testar-idempotencia

Código de saída: 0 = sucesso | 1 = erro ou teste crítico falhando
(o Agendador de Tarefas e o GitHub Actions registram a falha).
=========================================================
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg

from pipeline import carregar_bronze, carregar_gold, config, exportar_dashboard, resumo_semanal, testes_qualidade, utils
from pipeline.frota import tratar_frota
from pipeline.manutencao import tratar_manutencao
from pipeline.telemetria import tratar_telemetria

GERADORES = ["gerador/gerar_frota.py", "gerador/gerar_telemetria.py", "gerador/gerar_manutencao.py"]


def aplicar_retencao() -> dict:
    utils.titulo(f"RETENÇÃO — bronze (linhas de lotes tratados com mais de {config.RETENCAO_BRONZE_DIAS} dias)")
    with config.conectar() as con, con.transaction(), con.cursor() as cur:
        cur.execute("SELECT to_regprocedure('bronze.aplicar_retencao(integer)') IS NOT NULL")
        if not cur.fetchone()[0]:
            raise SystemExit("Função de retenção não encontrada. Rode banco/06_retencao_bronze.sql no SQL Editor do Supabase.")
        cur.execute("SELECT * FROM bronze.aplicar_retencao(%s)", (config.RETENCAO_BRONZE_DIAS,))
        apagadas = dict(cur.fetchall())
    total = sum(apagadas.values())
    utils.log().info(f"Linhas brutas apagadas: {utils.mil(total)}" + (f" {apagadas}" if total else ""))
    return apagadas


ETAPAS = {
    "bronze": carregar_bronze.carregar,
    "frota": tratar_frota.tratar,
    "telemetria": tratar_telemetria.tratar,
    "manutencao": tratar_manutencao.tratar,
    "gold": carregar_gold.carregar,
    "testes": testes_qualidade.rodar,
    "retencao": aplicar_retencao,
    "resumo": resumo_semanal.gerar,
    "dashboard": exportar_dashboard.exportar,
}
ETAPAS_DE_CARGA = ["bronze", "frota", "telemetria", "manutencao", "gold"]


def data_da_simulacao(ate: str) -> str:
    """Texto da data até onde a simulação vai (para o status)."""
    from datetime import date, timedelta
    if ate in (None, "", "base"):
        return "31/10/2026 (base fixa)"
    if ate == "ontem":
        return (datetime.now(ZoneInfo("America/Fortaleza")).date() - timedelta(days=1)).strftime("%d/%m/%Y")
    return date.fromisoformat(ate).strftime("%d/%m/%Y")


def gerar_dados(ate: str):
    utils.titulo(f"GERADOR — dados fictícios (semente fixa, simulação até: {ate})")
    for script in GERADORES:
        subprocess.run([sys.executable, script, "--ate", ate], check=True)


def executar(etapas: list, tempos: dict) -> dict:
    """Roda as etapas em ordem e devolve o retorno de cada uma."""
    retornos = {}
    for nome in etapas:
        inicio = time.perf_counter()
        try:
            retornos[nome] = ETAPAS[nome]()
        except psycopg.OperationalError as e:
            # conexão caiu no meio da etapa: como toda etapa é idempotente, roda de novo uma vez
            utils.log().warning(f"conexão caiu na etapa '{nome}' ({str(e).splitlines()[0]}); repetindo a etapa")
            time.sleep(20)
            retornos[nome] = ETAPAS[nome]()
        tempos[nome] = time.perf_counter() - inicio
        utils.log().info(f">> etapa '{nome}' concluída em {tempos[nome]:.1f} s")
        if nome == "testes" and retornos[nome] is False:
            raise RuntimeError("teste de qualidade crítico falhou (ver saida/relatorio_qualidade.txt)")
    return retornos


def mudou_algo(retornos: dict) -> list:
    """Na 2ª rodada nada pode entrar nem mudar: lista o que mudou."""
    mudancas = []
    if retornos.get("bronze", {}).get("arquivos_novos"):
        mudancas.append(f"bronze: {retornos['bronze']['arquivos_novos']} arquivo(s) novo(s)")
    for tabela, (novos, atual) in (retornos.get("frota") or {}).items():
        if novos or atual:
            mudancas.append(f"silver.{tabela}: {novos} novo(s), {atual} atualizado(s)")
    for nome, cont in (retornos.get("telemetria") or {}).items():
        if cont.get("silver_novos") or cont.get("silver_atualizados"):
            mudancas.append(f"silver.{nome}: {cont.get('silver_novos')} novo(s), {cont.get('silver_atualizados')} atualizado(s)")
    cont = retornos.get("manutencao") or {}
    if cont.get("silver_novos") or cont.get("silver_atualizados"):
        mudancas.append(f"silver.os_manutencao: {cont['silver_novos']} novo(s), {cont['silver_atualizados']} atualizado(s)")
    for tabela, (novos, atual) in (retornos.get("gold") or {}).items():
        if not tabela.startswith(("regra", "quarentena")) and (novos or atual):
            mudancas.append(f"gold.{tabela}: {novos} novo(s), {atual} atualizado(s)/removido(s)")
    return mudancas


def escrever_status(sucesso: bool, ate: str, tempos: dict, duracao: float, erro: str = None):
    """docs/status_pipeline.md: o commit diário desse arquivo também mantém o repositório ativo."""
    agora = datetime.now(ZoneInfo("America/Fortaleza"))
    linhas = [
        "# Status do pipeline", "",
        f"- **Última execução:** {agora:%d/%m/%Y %H:%M} (horário de Fortaleza)",
        f"- **Resultado:** {'✅ sucesso' if sucesso else '❌ falhou'}" + (f" — {erro}" if erro else ""),
        f"- **Simulação até:** {ate}",
        f"- **Duração:** {duracao:.0f} s ({', '.join(f'{k} {v:.0f} s' for k, v in tempos.items())})",
    ]
    try:
        with config.conectar() as con, con.cursor() as cur:
            cur.execute("""
                SELECT (SELECT to_char(min(data), 'DD/MM/YYYY') || ' a ' || to_char(max(data), 'DD/MM/YYYY')
                        FROM gold.fato_utilizacao),
                       (SELECT count(*) FROM gold.fato_utilizacao),
                       (SELECT count(*) FROM gold.fato_alertas),
                       (SELECT count(*) FROM gold.fato_manutencao),
                       (SELECT count(*) FROM silver.outliers_telemetria WHERE status = 'Pendente'),
                       (SELECT count(DISTINCT numero_os) FROM silver.quarentena_manutencao),
                       pg_size_pretty(pg_database_size(current_database()))
            """)
            periodo, viagens, alertas, os_, pendentes, quarentena, tamanho = cur.fetchone()
            indicadores = [("Período dos dados", periodo), ("Viagens (gold)", utils.mil(viagens)),
                           ("Alertas (gold)", utils.mil(alertas)), ("Ordens de serviço (gold)", utils.mil(os_)),
                           ("Outliers aguardando revisão", pendentes), ("OS em quarentena", quarentena),
                           ("Tamanho do banco", tamanho)]
            linhas += ["", "| Indicador | Valor |", "| --- | --- |"]
            linhas += [f"| {nome} | {valor} |" for nome, valor in indicadores]
    except (Exception, SystemExit) as e:
        linhas += ["", f"_Não foi possível ler os totais do banco: {e}_"]
    relatorio = config.SAIDA / "relatorio_qualidade.txt"
    if relatorio.exists():
        linhas += ["", "## Testes de qualidade", "", "```", relatorio.read_text(encoding="utf-8").strip(), "```"]
    config.PASTA_DOCS.mkdir(parents=True, exist_ok=True)
    config.ARQUIVO_STATUS.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    utils.log().info(f"Status gravado: {config.ARQUIVO_STATUS.relative_to(config.RAIZ)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline da brn-frota-data-platform (bronze -> silver -> gold).")
    parser.add_argument("--etapas", help=f"lista separada por vírgula: {','.join(ETAPAS)}")
    parser.add_argument("--gerar-dados", action="store_true", help="roda o gerador de dados fictícios antes")
    parser.add_argument("--ate", default="ontem",
                        help="até quando simular, com --gerar-dados: ontem (padrão) | base | AAAA-MM-DD")
    parser.add_argument("--testar-idempotencia", action="store_true",
                        help="roda a carga 2 vezes; a 2ª não pode inserir nem alterar nada")
    args = parser.parse_args()

    etapas = [e.strip() for e in args.etapas.split(",")] if args.etapas else list(ETAPAS)
    desconhecidas = [e for e in etapas if e not in ETAPAS]
    if desconhecidas:
        parser.error(f"etapa(s) desconhecida(s): {desconhecidas}. Use: {', '.join(ETAPAS)}")

    inicio, tempos = time.perf_counter(), {}
    try:
        if args.gerar_dados:
            t0 = time.perf_counter()
            gerar_dados(args.ate)
            tempos["gerar"] = time.perf_counter() - t0
        executar(etapas, tempos)
        if args.testar_idempotencia:
            utils.titulo("IDEMPOTÊNCIA — segunda rodada da carga")
            mudancas = mudou_algo(executar([e for e in etapas if e in ETAPAS_DE_CARGA], {}))
            if mudancas:
                for m in mudancas:
                    utils.log().error(f"  mudou na 2ª rodada: {m}")
                raise RuntimeError("pipeline NÃO é idempotente: a 2ª rodada alterou dados")
            utils.log().info("Idempotência OK: a 2ª rodada não inseriu nem alterou nada.")
    except (Exception, SystemExit) as erro:
        if isinstance(erro, SystemExit) and erro.code in (0, None):
            raise
        utils.log().error(f"PIPELINE FALHOU: {erro}")
        escrever_status(False, data_da_simulacao(args.ate) if args.gerar_dados else "(sem gerar dados)", tempos,
                        time.perf_counter() - inicio, str(erro))
        return 1
    duracao = time.perf_counter() - inicio
    escrever_status(True, data_da_simulacao(args.ate) if args.gerar_dados else "(sem gerar dados)", tempos, duracao)
    utils.log().info(f"PIPELINE CONCLUÍDO em {duracao:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
