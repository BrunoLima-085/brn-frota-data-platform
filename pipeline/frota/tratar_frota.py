"""
=========================================================
TRATAR_FROTA.PY — cadastros da frota: bronze -> silver
=========================================================
Centros de custo, veículos, alocações e motoristas.
Processa só os lotes novos da bronze; tipa os campos e faz upsert
pela chave primária (a versão nova do cadastro substitui a antiga).

Uso (na raiz do projeto):  py -m pipeline.frota.tratar_frota
=========================================================
"""

import re

from pipeline import config, utils


def _ler_bronze(cur, tabela: str, colunas: list, id_lotes: list) -> list:
    cur.execute(
        f"SELECT id_lote, {', '.join(colunas)} FROM bronze.{tabela} "
        f"WHERE id_lote = ANY(%s) ORDER BY id_lote, linha_arquivo",
        (id_lotes,))
    return cur.fetchall()


def _ultima_versao(linhas: list, chave_idx: int) -> list:
    """Se a mesma chave vier em mais de um lote, fica a do lote mais recente."""
    por_chave = {}
    for linha in linhas:
        por_chave[linha[chave_idx]] = linha
    return list(por_chave.values())


def tratar_centros(cur, lotes):
    linhas = _ler_bronze(cur, "frota_centros_custo", ["id_centro_custo", "centro_custo", "cidade", "regional"], lotes)
    registros = [[utils.inteiro(r[1]), utils.texto(r[2]), utils.texto(r[3]), utils.texto(r[4]), r[0]] for r in linhas]
    registros = _ultima_versao([r for r in registros if r[0] is not None], 0)
    return utils.upsert(cur, "silver.centros_custo",
                        ["id_centro_custo", "centro_custo", "cidade", "regional", "id_lote"],
                        registros, ["id_centro_custo"])


def tratar_veiculos(cur, lotes):
    cols = ["id_veiculo", "placa", "marca", "modelo", "cor", "tipo", "ano_fabricacao", "ano_modelo",
            "blindagem", "rastreador", "status_veiculo", "valor_fipe", "chassi", "filial"]
    descartados = 0
    registros = []
    for r in _ler_bronze(cur, "frota_veiculos", cols, lotes):
        placa = (utils.texto(r[2]) or "").upper().replace("-", "").replace(" ", "")
        if not re.fullmatch(config.PADRAO_PLACA, placa):
            descartados += 1
            continue
        registros.append([
            utils.inteiro(r[1]), placa, utils.texto(r[3]), utils.texto(r[4]), utils.texto(r[5]),
            utils.texto(r[6]), utils.inteiro(r[7]), utils.inteiro(r[8]),
            bool(utils.sim_nao(r[9])), bool(utils.sim_nao(r[10])), utils.texto(r[11]),
            utils.numero(r[12]), (utils.texto(r[13]) or "").upper() or None, utils.texto(r[14]), r[0]])
    if descartados:
        utils.log().warning(f"  veículos com placa inválida descartados: {descartados}")
    registros = _ultima_versao(registros, 0)
    return utils.upsert(cur, "silver.veiculos",
                        ["id_veiculo", "placa", "marca", "modelo", "cor", "tipo", "ano_fabricacao", "ano_modelo",
                         "blindagem", "possui_rastreador", "status_veiculo", "valor_fipe", "chassi", "filial",
                         "id_lote"],
                        registros, ["id_veiculo"])


def tratar_alocacao(cur, lotes):
    cols = ["id_alocacao", "id_veiculo", "placa", "id_centro_custo", "contrato", "operacao",
            "data_inicio", "data_fim", "status_alocacao"]
    registros = []
    for r in _ler_bronze(cur, "frota_alocacao", cols, lotes):
        registros.append([
            utils.inteiro(r[1]), utils.inteiro(r[2]), (utils.texto(r[3]) or "").upper(), utils.inteiro(r[4]),
            utils.texto(r[5]), utils.texto(r[6]), utils.data(r[7]), utils.data(r[8]), utils.texto(r[9]), r[0]])
    registros = _ultima_versao(registros, 0)
    return utils.upsert(cur, "silver.alocacao",
                        ["id_alocacao", "id_veiculo", "placa", "id_centro_custo", "contrato", "operacao",
                         "data_inicio", "data_fim", "status_alocacao", "id_lote"],
                        registros, ["id_alocacao"])


def tratar_motoristas(cur, lotes):
    registros = [[utils.inteiro(r[1]), utils.texto(r[2]), r[0]]
                 for r in _ler_bronze(cur, "frota_motoristas", ["id_motorista", "motorista"], lotes)]
    registros = _ultima_versao([r for r in registros if r[0] is not None and r[1]], 0)
    return utils.upsert(cur, "silver.motoristas", ["id_motorista", "motorista", "id_lote"],
                        registros, ["id_motorista"])


ETAPAS = [
    ("frota_centros_custo", "centros_custo", tratar_centros),
    ("frota_veiculos", "veiculos", tratar_veiculos),
    ("frota_alocacao", "alocacao", tratar_alocacao),
    ("frota_motoristas", "motoristas", tratar_motoristas),
]


def tratar() -> dict:
    utils.titulo("SILVER — cadastros da frota")
    resumo = {}
    with config.conectar() as con, con.transaction(), con.cursor() as cur:
        for fonte, tabela, funcao in ETAPAS:
            lotes = [l[0] for l in utils.lotes_pendentes(cur, fonte)]
            if not lotes:
                utils.log().info(f"[{tabela}] nenhum lote novo")
                resumo[tabela] = (0, 0)
                continue
            novos, atualizados = funcao(cur, lotes)
            utils.marcar_processados(cur, lotes)
            resumo[tabela] = (novos, atualizados)
            utils.log().info(f"[{tabela}] {len(lotes)} lote(s) | novos: {novos} | atualizados: {atualizados}")
    return resumo


if __name__ == "__main__":
    tratar()
