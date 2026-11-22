"""
=========================================================
CARREGAR_BRONZE.PY — arquivos de entrada -> camada bronze
=========================================================
Lê tudo o que está em entrada/ e grava na bronze EXATAMENTE como veio:
tudo texto, com rodapés, linhas repetidas e alertas em aberto.

- cada arquivo vira um lote (bronze.lote_carga) com o hash do conteúdo;
- arquivo já carregado (mesmo hash) é pulado -> rodar 2x não duplica nada;
- cada arquivo é gravado numa transação: ou entra inteiro, ou não entra;
- a carga usa COPY (em massa), não INSERT linha a linha.

Uso (na raiz do projeto):  py -m pipeline.carregar_bronze
=========================================================
"""

import csv
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from pipeline import config, utils

# ---------------------------------------------------------
# Mapeamento: nome da coluna na fonte -> coluna na bronze
# ---------------------------------------------------------
MAPA_ALERTAS = {
    "Unidade rastreada": "unidade_rastreada", "Motorista": "motorista",
    "Nº ordem rastreador": "n_ordem_rastreador", "Telemetrias (mínima | máxima | média)": "telemetrias",
    "Áreas e rotas geográficas": "areas_rotas_geograficas", "Entradas": "entradas", "Saídas": "saidas",
    "Eventos de controle": "eventos_controle", "Nome da regra": "nome_regra",
    "Data da ocorrência": "data_ocorrencia", "Hora da ocorrência": "hora_ocorrencia",
    "Finalização da ocorrência": "finalizacao_ocorrencia", "Duração": "duracao",
    "Odômetro inicial": "odometro_inicial", "Odômetro final": "odometro_final", "Distância": "distancia",
    "Grupo de regras": "grupo_regras", "Requer tratamento": "requer_tratamento",
    "Situação do chamado": "situacao_chamado", "Status do chamado": "status_chamado", "Nível": "nivel",
    "Categoria do chamado": "categoria_chamado", "Ticket": "ticket", "Data da criação": "data_criacao",
    "Duração do chamado": "duracao_chamado", "Limite para fechar": "limite_fechar",
    "Usuário respónsável": "usuario_responsavel", "Tempo para abrir": "tempo_abrir",
    "Limite para abrir": "limite_abrir", "Grupo de unidades rastreadas": "grupo_unidades",
    "Unidade organizacional": "unidade_organizacional", "Local início": "local_inicio",
    "Local fim": "local_fim", "Modo de violação": "modo_violacao",
}
MAPA_BDV = {
    "Unidade rastreada": "unidade_rastreada", "Motorista": "motorista", "Data inicial": "data_inicial",
    "Data final": "data_final", "Distância (Odo)": "distancia_odo", "Duração (Dt)": "duracao_dt",
    "Motor ocioso (T)": "motor_ocioso", "Consumo (l)": "consumo_l", "Eficiência (km/l)": "eficiencia_km_l",
    "Meta consumo (%)": "meta_consumo_pct", "Economia (R$)": "economia_rs",
    "Gasto combustível movimento": "gasto_combustivel_movimento",
    "Gasto combustível ocioso": "gasto_combustivel_ocioso", "Gasto combustível total": "gasto_combustivel_total",
    "Vel. máxima": "vel_maxima", "Vel. média em movimento": "vel_media_movimento",
    "Grupo de unidades rastreadas": "grupo_unidades", "Unidade organizacional": "unidade_organizacional",
    "Endereço inicial": "endereco_inicial", "Endereço final": "endereco_final",
    "Quantidade de frenagem": "quantidade_frenagem", "Tempo de frenagem": "tempo_frenagem",
}
MAPA_OS = {
    "Controle de Pedido Interno": "controle_pedido_interno", "Placa": "placa", "Modelo": "modelo",
    "Centro de Custo": "centro_custo", "Contrato": "contrato", "Oficina": "oficina", "Data da OS": "data_os",
    "Data Entrada Oficina": "data_entrada_oficina", "Data Prevista Saída": "data_prevista_saida",
    "Data Real Saída": "data_real_saida", "Data Orçamento": "data_orcamento",
    "Data Solicitação Aprovação": "data_solicitacao_aprovacao", "Data Aprovação": "data_aprovacao",
    "Data Pedido Compra": "data_pedido_compra", "Data Compra Efetivada": "data_compra_efetivada",
    "Data Entrega Peça": "data_entrega_peca", "Data Pagamento Oficina": "data_pagamento_oficina",
    "Tipo de Manutenção": "tipo_manutencao", "Criticidade": "criticidade",
    "Valor Orçamento": "valor_orcamento", "Valor Negociado": "valor_negociado", "% Variação": "pct_variacao",
    "Nº Requisição Peças": "n_requisicao_pecas", "Valor Peças/Itens (R$)": "valor_pecas",
    "KM Atual": "km_atual", "Status Operacional": "status_operacional",
    "Veículo Substituto?": "veiculo_substituto", "Placa Substituto": "placa_substituto",
    "Tipo de Aluguel": "tipo_aluguel", "Valor Aluguel (R$)": "valor_aluguel",
    "Solicitante da Manutenção": "solicitante", "Tipo de Sistema": "tipo_sistema",
    "Descrição do Problema": "descricao_problema", "Status da Manutenção": "status_manutencao",
    "Responsável pela aprovação": "responsavel_aprovacao", "Observações Gerais": "observacoes_gerais",
}


def _como_texto(valor):
    """Bronze guarda texto. Data/número do Excel viram texto sem perder informação."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    texto = str(valor)
    return texto if texto != "" else None


def _montar_linhas(cabecalho: list, linhas, mapa: dict, arquivo: str, primeira_linha: int):
    """Converte as linhas da fonte na ordem das colunas da bronze."""
    faltando = [nome for nome in mapa if nome not in cabecalho]
    if faltando:
        raise ValueError(f"{arquivo}: colunas esperadas não encontradas: {faltando}")
    indices = [cabecalho.index(nome) for nome in mapa]
    saida = []
    for n, linha in enumerate(linhas, start=primeira_linha):
        valores = [_como_texto(linha[i]) if i < len(linha) else None for i in indices]
        if any(v is not None for v in valores):     # linha totalmente vazia não é dado
            saida.append([n, *valores])
    return list(mapa.values()), saida


# ---------------------------------------------------------
# Leitores por tipo de fonte
# ---------------------------------------------------------
def ler_alertas(caminho: Path):
    """Cabeçalho em 2 linhas mescladas: vale o da linha 2 quando existir, senão o da linha 1."""
    wb = load_workbook(caminho, read_only=True, data_only=True)
    linhas = list(wb.active.iter_rows(values_only=True))
    wb.close()
    l1, l2 = linhas[0], linhas[1]
    cabecalho = [(b if b not in (None, "") else a) for a, b in zip(l1, l2)]
    cabecalho = [str(c).strip() if c is not None else None for c in cabecalho]
    return _montar_linhas(cabecalho, linhas[2:], MAPA_ALERTAS, caminho.name, primeira_linha=3)


def ler_planilha_simples(caminho: Path, mapa: dict, aba: str = None):
    wb = load_workbook(caminho, read_only=True, data_only=True)
    ws = wb[aba] if aba else wb.active
    linhas = list(ws.iter_rows(values_only=True))
    wb.close()
    cabecalho = [str(c).strip() if c is not None else None for c in linhas[0]]
    return _montar_linhas(cabecalho, linhas[1:], mapa, caminho.name, primeira_linha=2)


def ler_csv(caminho: Path):
    """CSVs da frota: cabeçalho 'ID_Veiculo' -> coluna 'id_veiculo'."""
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        leitor = csv.reader(f)
        cabecalho = next(leitor)
        linhas = list(leitor)
    mapa = {nome: nome.strip().lower() for nome in cabecalho}
    return _montar_linhas(cabecalho, linhas, mapa, caminho.name, primeira_linha=2)


# (fonte, tabela bronze, pasta, padrão de arquivo, leitor)
FONTES = [
    ("frota_centros_custo", "bronze.frota_centros_custo", "frota", "centros_custo.csv", ler_csv),
    ("frota_veiculos", "bronze.frota_veiculos", "frota", "veiculos.csv", ler_csv),
    ("frota_alocacao", "bronze.frota_alocacao", "frota", "alocacao.csv", ler_csv),
    ("frota_motoristas", "bronze.frota_motoristas", "frota", "motoristas.csv", ler_csv),
    ("telemetria_alertas", "bronze.telemetria_alertas", "telemetria", "*lertasenotificacoes_*.xlsx", ler_alertas),
    ("telemetria_bdv", "bronze.telemetria_bdv", "telemetria", "*PeriodosDeUtilizacao_*.xlsx",
     lambda c: ler_planilha_simples(c, MAPA_BDV)),
    ("manutencao_os", "bronze.manutencao_os", "manutencao", "*.xlsx",
     lambda c: ler_planilha_simples(c, MAPA_OS, aba="FATO_Manutencao")),
]


def carregar(fontes: list = None) -> dict:
    """Carrega na bronze os arquivos novos. fontes=None -> todas."""
    utils.titulo("BRONZE — carga dos arquivos de entrada")
    resumo = {"arquivos_novos": 0, "arquivos_ja_carregados": 0, "linhas": 0}
    with config.conectar() as con:
        for fonte, tabela, pasta, padrao, leitor in FONTES:
            if fontes and fonte not in fontes:
                continue
            arquivos = sorted(p for p in (config.ENTRADA / pasta).glob(padrao) if not p.name.startswith("~$"))
            if not arquivos:
                utils.log().warning(f"[{fonte}] nenhum arquivo em entrada/{pasta}/{padrao}")
                continue
            novos = linhas_fonte = 0
            for arquivo in arquivos:
                hash_ = utils.hash_arquivo(arquivo)
                with con.transaction(), con.cursor() as cur:
                    cur.execute("SELECT 1 FROM bronze.lote_carga WHERE fonte = %s AND hash_arquivo = %s", (fonte, hash_))
                    if cur.fetchone():
                        resumo["arquivos_ja_carregados"] += 1
                        continue
                    colunas, linhas = leitor(arquivo)
                    cur.execute(
                        "INSERT INTO bronze.lote_carga (fonte, arquivo, hash_arquivo, linhas) "
                        "VALUES (%s, %s, %s, %s) RETURNING id_lote",
                        (fonte, arquivo.name, hash_, len(linhas)))
                    id_lote = cur.fetchone()[0]
                    utils.copiar(cur, tabela, ["id_lote", "linha_arquivo", *colunas],
                                 ([id_lote, *linha] for linha in linhas))
                novos += 1
                linhas_fonte += len(linhas)
            resumo["arquivos_novos"] += novos
            resumo["linhas"] += linhas_fonte
            utils.log().info(f"[{fonte}] {len(arquivos)} arquivo(s): {novos} novo(s), "
                             f"{len(arquivos) - novos} já carregado(s) | {utils.mil(linhas_fonte)} linhas gravadas")
    utils.log().info(f"Bronze: {resumo['arquivos_novos']} arquivo(s) novo(s), "
                     f"{resumo['arquivos_ja_carregados']} pulado(s) (mesmo hash), {utils.mil(resumo['linhas'])} linhas")
    return resumo


if __name__ == "__main__":
    carregar()
