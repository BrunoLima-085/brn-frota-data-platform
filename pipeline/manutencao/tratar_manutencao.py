"""
=========================================================
TRATAR_MANUTENCAO.PY — planilha de OS: bronze -> silver
=========================================================
A planilha de acompanhamento de manutenção é digitada à mão, então
chega suja. Para cada lote novo da bronze:

  1. datas: aceita data do Excel, "15/08/2026" (texto) e serial do Excel;
  2. valores: "1.250,00", "R$ 1.250,00" e 1250.5 viram NUMERIC;
  3. KM Atual: tipo misturado (85320, "85.320", "85320 km") -> só os dígitos;
  4. textos: espaços extras, caixa misturada e falta de acento ("CORRETIVA",
     " corretiva ", "Aguardando pecas", "Suspencao") são padronizados contra a
     lista de valores válidos de cada campo;
  4b. Nº da requisição de peças digitado de vários jeitos ("req 26 0031",
     "REQ260031") vira REQ-26-0031; "Veículo Substituto?" Sim/Não vira booleano;
  5. QUARENTENA: a OS que não pode entrar no modelo NÃO é descartada em
     silêncio — vai para silver.quarentena_manutencao com o motivo:
       - placa que não existe na frota
       - placa fora do padrão / sem número de OS / sem data da OS
       - valor fora da lista (ex.: tipo de manutenção desconhecido)
       - data de saída anterior à entrada
  6. upsert na silver pela chave natural (Controle de Pedido Interno = número da OS):
     a planilha é viva, então a versão nova da OS substitui a anterior.

Pré-requisito: cadastros da frota já tratados (pipeline.frota.tratar_frota).

Uso (na raiz do projeto):  py -m pipeline.manutencao.tratar_manutencao
=========================================================
"""

import json
import re
import unicodedata
from collections import Counter, defaultdict

from pipeline import config, utils

# Valores válidos de cada campo de categoria (iguais aos CHECKs da gold).
# A planilha é digitada sem acento ("Aguardando pecas"): a comparação ignora acento e caixa.
DOMINIOS = {
    "tipo_manutencao": ["Preventiva", "Corretiva", "Preditiva"],
    "criticidade": ["Baixa", "Média", "Alta"],
    "status_manutencao": ["Em agendamento", "Em diagnóstico", "Aguardando aprovação", "Aguardando peças",
                          "Em manutenção", "Concluída"],
    "status_operacional": ["Operando", "Parado", "Restrição"],
    "tipo_sistema": ["Ar-condicionado", "ARLA", "Carroceria", "Elétrica", "Freios", "Hidráulica", "Motor",
                     "Pneus", "Suspensão", "Transmissão", "Outro"],
    "tipo_aluguel": ["Diária", "Período"],
}
# Grafias erradas que são comuns na planilha
SINONIMOS = {"suspencao": "Suspensão"}
OBRIGATORIOS_NO_DOMINIO = ("tipo_manutencao", "status_manutencao", "tipo_sistema")

COLUNAS_DATA = [
    "data_os", "data_entrada_oficina", "data_prevista_saida", "data_real_saida", "data_orcamento",
    "data_solicitacao_aprovacao", "data_aprovacao", "data_pedido_compra", "data_compra_efetivada",
    "data_entrega_peca", "data_pagamento_oficina",
]
ORDEM_DO_FLUXO = [
    "data_os", "data_entrada_oficina", "data_orcamento", "data_solicitacao_aprovacao", "data_aprovacao",
    "data_pedido_compra", "data_compra_efetivada", "data_entrega_peca", "data_real_saida",
    "data_pagamento_oficina",
]
COLUNAS_VALOR = ["valor_orcamento", "valor_negociado", "valor_pecas", "valor_aluguel"]
COLUNAS_BRONZE = [
    "controle_pedido_interno", "placa", "modelo", "centro_custo", "contrato", "oficina", *COLUNAS_DATA,
    "tipo_manutencao", "criticidade", "valor_orcamento", "valor_negociado", "n_requisicao_pecas", "valor_pecas",
    "km_atual", "status_operacional", "veiculo_substituto", "placa_substituto", "tipo_aluguel", "valor_aluguel",
    "solicitante", "tipo_sistema", "descricao_problema", "status_manutencao", "responsavel_aprovacao",
    "observacoes_gerais",
]
COLUNAS_SILVER = [
    "numero_os", "placa", "modelo", "centro_custo", "contrato", "oficina", *COLUNAS_DATA, "tipo_manutencao",
    "criticidade", "valor_orcamento", "valor_negociado", "n_requisicao_pecas", "valor_pecas", "km_atual",
    "status_operacional", "veiculo_substituto", "placa_substituto", "tipo_aluguel", "valor_aluguel",
    "solicitante", "tipo_sistema", "descricao_problema", "status_manutencao", "responsavel_aprovacao",
    "observacoes_gerais", "id_lote",
]

REGEX_REQUISICAO = re.compile(r"(?i)^\s*req\D*(\d{2})\D*(\d{1,4})\s*$")
REGEX_DATA_TEXTO = re.compile(r"^\d{2}/\d{2}/\d{4}")


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def chave_texto(valor) -> str:
    """Forma de comparação: sem espaços extras, sem acento e sem diferença de maiúscula/minúscula."""
    return sem_acento(utils.texto(valor) or "").casefold()


def padronizar(valor, validos: list):
    """'  CORRETIVA ' -> 'Corretiva'; 'Aguardando pecas' -> 'Aguardando peças'.
    Fora da lista -> (texto limpo, False)."""
    limpo = utils.texto(valor)
    if limpo is None:
        return None, True
    chave = chave_texto(limpo)
    mapa = {chave_texto(v): v for v in validos}
    if chave in mapa:
        return mapa[chave], True
    if SINONIMOS.get(chave) in validos:
        return SINONIMOS[chave], True
    return limpo, False


def padronizar_requisicao(valor):
    """'req 26 0031', 'REQ260031', ' Req-26-31' -> 'REQ-26-0031'. Fora do padrão -> texto limpo."""
    limpo = utils.texto(valor)
    if limpo is None:
        return None
    m = REGEX_REQUISICAO.match(limpo)
    return f"REQ-{m.group(1)}-{int(m.group(2)):04d}" if m else limpo


def grafia_mais_comum(valores: list) -> dict:
    """Para campos sem lista fixa (oficina): 'oficina alfa ' e 'OFICINA ALFA' viram a grafia
    mais usada entre as variantes."""
    variantes = defaultdict(Counter)
    for v in valores:
        limpo = utils.texto(v)
        if limpo:
            variantes[chave_texto(limpo)][limpo] += 1
    return {chave: contagem.most_common(1)[0][0] for chave, contagem in variantes.items()}


def tratar() -> dict:
    utils.titulo("SILVER — manutenção (ordens de serviço)")
    cont = Counter()
    with config.conectar() as con, con.transaction(), con.cursor() as cur:
        lotes = [l[0] for l in utils.lotes_pendentes(cur, "manutencao_os")]
        if not lotes:
            utils.log().info("[os_manutencao] nenhum lote novo")
            return {}

        cur.execute("SELECT placa FROM silver.veiculos")
        placas_frota = {p for (p,) in cur.fetchall()}
        if not placas_frota:
            raise SystemExit("silver.veiculos está vazia: rode antes  py -m pipeline.frota.tratar_frota")
        cur.execute("SELECT centro_custo FROM silver.centros_custo")
        centros = [c for (c,) in cur.fetchall()]

        cur.execute(f"""
            SELECT id_lote, linha_arquivo, {', '.join(COLUNAS_BRONZE)}
            FROM bronze.manutencao_os WHERE id_lote = ANY(%s) ORDER BY id_lote, linha_arquivo
        """, (lotes,))
        linhas = [dict(zip(["id_lote", "linha_arquivo", *COLUNAS_BRONZE], r)) for r in cur.fetchall()]
        cont["linhas_bronze"] = len(linhas)
        oficinas = grafia_mais_comum([l["oficina"] for l in linhas])

        validas, quarentena = {}, []
        for b in linhas:
            os_ = {"numero_os": (utils.texto(b["controle_pedido_interno"]) or "").upper() or None,
                   "id_lote": b["id_lote"]}

            # ---- datas ----
            for c in COLUNAS_DATA:
                if b[c] and REGEX_DATA_TEXTO.match(b[c].strip()):
                    cont["datas_texto_convertidas"] += 1
                os_[c] = utils.data(b[c])
                if b[c] and os_[c] is None:
                    cont["datas_invalidas_viraram_vazio"] += 1

            # ---- valores ----
            for c in COLUNAS_VALOR:
                if b[c] and "," in b[c]:
                    cont["valores_texto_convertidos"] += 1
                os_[c] = utils.numero(b[c])

            # ---- KM Atual com tipo misturado ----
            km = b["km_atual"]
            if km is None:
                cont["km_vazio"] += 1
            elif "km" in km.lower():
                cont["km_texto_com_km"] += 1
            elif "." in km:
                cont["km_texto_com_ponto"] += 1
            else:
                cont["km_numero"] += 1
            os_["km_atual"] = utils.so_digitos(km)

            # ---- textos ----
            placa = (utils.texto(b["placa"]) or "").upper().replace("-", "").replace(" ", "")
            os_["placa"] = placa
            for c in ("modelo", "contrato", "solicitante", "descricao_problema", "responsavel_aprovacao",
                      "observacoes_gerais"):
                os_[c] = utils.texto(b[c])

            # ---- requisição de peças e veículo substituto ----
            os_["n_requisicao_pecas"] = padronizar_requisicao(b["n_requisicao_pecas"])
            if b["n_requisicao_pecas"] and os_["n_requisicao_pecas"] != b["n_requisicao_pecas"]:
                cont["requisicao_padronizada"] += 1
            os_["veiculo_substituto"] = utils.sim_nao(b["veiculo_substituto"])
            sub = (utils.texto(b["placa_substituto"]) or "").upper().replace("-", "").replace(" ", "")
            os_["placa_substituto"] = sub or None
            if os_["veiculo_substituto"] and not os_["placa_substituto"]:
                cont["aviso_substituto_sem_placa"] += 1
            os_["oficina"] = oficinas.get(chave_texto(b["oficina"])) if b["oficina"] else None
            os_["centro_custo"], _ = padronizar(b["centro_custo"], centros)
            fora_da_lista = []
            for c, validos in DOMINIOS.items():
                os_[c], ok = padronizar(b[c], validos)
                if not ok and c in OBRIGATORIOS_NO_DOMINIO:
                    fora_da_lista.append(f"{c} = '{os_[c]}'")
            for c in ("oficina", "centro_custo", *DOMINIOS):
                if b[c] is not None and b[c] != os_[c]:
                    cont["textos_padronizados"] += 1

            # ---- datas fora de ordem (aviso, não barra) ----
            preenchidas = [os_[c] for c in ORDEM_DO_FLUXO if os_[c]]
            if any(a > b_ for a, b_ in zip(preenchidas, preenchidas[1:])):
                cont["aviso_datas_do_fluxo_fora_de_ordem"] += 1

            # ---- quarentena ----
            motivo = None
            if not os_["numero_os"]:
                motivo = "OS sem número (Controle de Pedido Interno vazio)"
            elif not re.fullmatch(config.PADRAO_PLACA, placa):
                motivo = f"Placa fora do padrão: '{b['placa']}'"
            elif placa not in placas_frota:
                motivo = "Placa não existe na frota"
            elif not os_["data_os"]:
                motivo = "Sem data da OS"
            elif fora_da_lista:
                motivo = "Valor fora da lista: " + "; ".join(fora_da_lista)
            elif (os_["data_real_saida"] and os_["data_entrada_oficina"]
                  and os_["data_real_saida"] < os_["data_entrada_oficina"]):
                motivo = "Data de saída anterior à entrada"

            if motivo:
                cont[f"quarentena: {motivo.split(':')[0]}"] += 1
                bruto = {k: v for k, v in b.items() if k not in ("id_lote", "linha_arquivo")}
                quarentena.append((os_["numero_os"] or f"(linha {b['linha_arquivo']})", b["id_lote"],
                                   placa or None, motivo, json.dumps(bruto, ensure_ascii=False)))
                continue
            if os_["numero_os"] in validas:
                cont["os_repetida_versao_mais_recente_vale"] += 1
            validas[os_["numero_os"]] = os_

        # ---- gravação ----
        for q in quarentena:
            cur.execute("""
                INSERT INTO silver.quarentena_manutencao (numero_os, id_lote, placa, motivo, dados)
                VALUES (%s, %s, %s, %s, %s::jsonb) ON CONFLICT (numero_os, id_lote) DO NOTHING
            """, q)
        novos, atualizados = utils.upsert(cur, "silver.os_manutencao", COLUNAS_SILVER,
                                          [[o[c] for c in COLUNAS_SILVER] for o in validas.values()],
                                          ["numero_os"], modo="substituir")
        cont["silver_novos"], cont["silver_atualizados"] = novos, atualizados
        cont["os_em_quarentena"] = len(quarentena)
        utils.marcar_processados(cur, lotes)

    utils.log().info(f"[os_manutencao] {len(lotes)} lote(s) novo(s)")
    for k in sorted(cont, key=lambda k: (k.startswith("quarentena"), k.startswith("silver"), k)):
        utils.log().info(f"    {k}: {utils.mil(cont[k])}")
    if quarentena:
        utils.log().info("  OS em quarentena:")
        for numero, _, placa, motivo, _ in quarentena:
            utils.log().info(f"    {numero} | placa {placa} | {motivo}")
    return dict(cont)


if __name__ == "__main__":
    tratar()
