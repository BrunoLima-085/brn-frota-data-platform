"""
=========================================================
GERAR_MANUTENCAO.PY — planilha fictícia de ordens de serviço
=========================================================
Projeto: brn-frota-data-platform (dados 100% fictícios)

Gera entrada/manutencao/planilha_manutencao.xlsx, aba FATO_Manutencao,
com as 36 colunas da planilha de acompanhamento de manutenções (as
listas de valores são as da planilha, sem acento, como são digitadas).
O "Controle de Pedido Interno" (1ª coluna, BRN-26-0001) é o número da OS.

Regras da simulação:
- OS para 53 dos 123 veículos (todos os de perfil agressivo entram);
- preventivas a cada ~10.000 km (usa o mesmo odômetro da telemetria),
  corretivas e preditivas; agressivos têm mais corretivas de
  Freios, Suspensão e Pneus;
- fluxo de datas coerente: abertura da OS -> entrada na oficina -> orçamento
  -> solicitação de aprovação -> aprovação -> pedido de compra -> compra
  efetivada -> entrega da peça -> saída -> pagamento. Etapas que cairiam
  depois de "hoje" ficam vazias: a OS está parada nessa etapa (6 status:
  Em agendamento, Em diagnóstico, Aguardando aprovação, Aguardando peças,
  Em manutenção, Concluída). A entrega da peça é o gargalo;
- valor negociado entre 60% e 100% do orçamento; a Oficina Delta negocia mais;
- peças compradas à parte (Nº da requisição + valor das peças);
- parte das OS de criticidade alta recebe veículo substituto alugado
  (diária ou período), base do custo do veículo parado.

Problemas reais plantados DE PROPÓSITO:
  - datas e valores gravados como texto ("15/08/2026", "1.250,00")
  - KM Atual com tipo misturado (85320, "85.320", "85320 km")
  - 3 OS com placa que não existe na frota (quarentena)
  - espaços extras e caixa misturada em textos de categoria
  - Nº da requisição de peças em formatos diferentes ("req 26 0031", "REQ260031")
  - 3 OS com "Veículo Substituto? = Sim" e a placa do substituto vazia

Contagens em entrada/_gabarito/manutencao.json (o pipeline não lê).

Modo contínuo (--ate ontem): a planilha é "viva" — as OS em andamento avançam
de etapa conforme os dias passam e surgem OS novas, semana a semana.

Uso (na raiz do projeto):
    py gerador/gerar_manutencao.py --ate base    # situação em 31/10/2026 (base)
    py gerador/gerar_manutencao.py --ate ontem   # situação até ontem
=========================================================
"""

import json
import random
import string
from datetime import date, datetime, timedelta

from openpyxl import Workbook

import comum

ARQUIVO = comum.PASTA_MANUTENCAO / "planilha_manutencao.xlsx"
QTD_VEICULOS_COM_OS = 53

COLUNAS = [
    "Controle de Pedido Interno", "Placa", "Modelo", "Centro de Custo", "Contrato", "Oficina", "Data da OS",
    "Data Entrada Oficina", "Data Prevista Saída", "Data Real Saída", "Data Orçamento",
    "Data Solicitação Aprovação", "Data Aprovação", "Data Pedido Compra", "Data Compra Efetivada",
    "Data Entrega Peça", "Data Pagamento Oficina", "Tipo de Manutenção", "Criticidade", "Valor Orçamento",
    "Valor Negociado", "% Variação", "Nº Requisição Peças", "Valor Peças/Itens (R$)", "KM Atual",
    "Status Operacional", "Veículo Substituto?", "Placa Substituto", "Tipo de Aluguel", "Valor Aluguel (R$)",
    "Solicitante da Manutenção", "Tipo de Sistema", "Descrição do Problema", "Status da Manutenção",
    "Responsável pela aprovação", "Observações Gerais",
]
COLUNA_OS = "Controle de Pedido Interno"
COLUNAS_DATA = [c for c in COLUNAS if c.startswith("Data ")]
ETAPAS = ["Data Orçamento", "Data Solicitação Aprovação", "Data Aprovação", "Data Pedido Compra",
          "Data Compra Efetivada", "Data Entrega Peça", "Data Real Saída", "Data Pagamento Oficina"]

# Como cada valor é digitado na planilha (listas da aba "Listas", sem acento)
NA_PLANILHA = {
    "Média": "Media", "Suspensão": "Suspencao", "Elétrica": "Eletrica", "Hidráulica": "Hidraulica",
    "Revisão": "Motor",   # a planilha não tem "Revisão": preventiva entra como Motor
    "Restrição": "Restricao",
}
STATUS_PLANILHA = ["Em agendamento", "Em diagnostico", "Aguardando aprovacao", "Aguardando pecas",
                   "Em manutenção", "Concluida"]

OFICINAS = ["Oficina Alfa", "Oficina Beta", "Oficina Gama", "Oficina Delta", "Oficina Épsilon", "Oficina Zeta"]
OFICINA_QUE_NEGOCIA = "Oficina Delta"

ORCAMENTO_POR_SISTEMA = {
    "Freios": (600, 3500), "Motor": (2000, 9000), "Suspensão": (800, 5000), "Pneus": (1200, 6000),
    "Elétrica": (300, 2500), "Transmissão": (1500, 8000), "Carroceria": (500, 6000),
    "Ar-condicionado": (400, 3000), "ARLA": (500, 3500), "Hidráulica": (900, 6000), "Outro": (200, 1500),
    "Revisão": (300, 1800),
}
MULT_TIPO = {"Leve": 1.0, "Pick-up": 1.3, "Van": 1.4, "Caminhão": 2.0, "Ônibus": 2.2, "Moto": 0.4}
SISTEMAS_CONDUCAO = ["Freios", "Suspensão", "Pneus"]
OUTROS_SISTEMAS = ["Motor", "Elétrica", "Transmissão", "Carroceria", "Ar-condicionado", "Outro"]
SISTEMAS_DIESEL = ["ARLA", "Hidráulica"]          # só caminhão e ônibus
TIPOS_DIESEL = ("Caminhão", "Ônibus")

DESCRICOES = {
    "Freios": ["Pastilhas gastas", "Ruído ao frear", "Disco de freio empenado", "Pedal de freio baixo"],
    "Motor": ["Perda de potência", "Vazamento de óleo", "Falha na partida", "Luz de injeção acesa",
              "Superaquecimento do motor", "Vazamento no radiador"],
    "Suspensão": ["Barulho na suspensão dianteira", "Amortecedor vazando", "Bucha da bandeja gasta"],
    "Pneus": ["Desgaste irregular dos pneus", "Pneu furado sem reparo", "Troca de pneus por desgaste"],
    "Elétrica": ["Bateria descarregando", "Farol queimado", "Falha no alternador"],
    "Transmissão": ["Embreagem patinando", "Dificuldade para engatar marcha", "Ruído no câmbio"],
    "ARLA": ["Sensor de ARLA com falha", "Bomba de ARLA sem pressão", "Luz de emissões acesa"],
    "Hidráulica": ["Vazamento no cilindro hidráulico", "Bomba hidráulica com ruído", "Mangueira hidráulica rompida"],
    "Outro": ["Troca de palhetas", "Reparo no banco do motorista", "Instalação de acessório"],
    "Carroceria": ["Avaria lateral", "Para-choque danificado", "Retrovisor quebrado"],
    "Ar-condicionado": ["Ar-condicionado não gela", "Ruído no compressor", "Recarga de gás"],
    "Revisão": ["Revisão periódica por quilometragem", "Revisão: troca de óleo e filtros"],
}
OBSERVACOES = ["Veículo liberado após teste", "Aguardando retorno da oficina", "Peça com prazo estendido",
               "Orçamento revisado", "Sem observações", "Acompanhar na próxima revisão"]

DIARIA_POR_TIPO = {"Leve": (110, 180), "Pick-up": (180, 280), "Van": (220, 320), "Caminhão": (400, 650),
                   "Ônibus": (500, 800), "Moto": (60, 90)}
P_SUBSTITUTO = 0.40          # entre as OS de criticidade alta que já entraram na oficina

# Problemas plantados
P_REQ_SUJA = 0.15
QTD_SUBSTITUTO_SEM_PLACA = 3
P_DATA_TEXTO = 0.12
P_VALOR_TEXTO = 0.20
P_TEXTO_SUJO = 0.10


def _limitar(d: date):
    return d if d <= comum.FIM_PERIODO else None


def montar_fluxo(r, abertura: date, sistema: str, tipo_manut: str) -> dict:
    """Datas de cada etapa; o que passar de 'hoje' fica vazio (OS parada nessa etapa)."""
    d = {"Data da OS": abertura}
    entrada = abertura + timedelta(days=r.randint(0, 2))
    ra = comum.rng_de("agenda_execucao", abertura.isoformat(), sistema, tipo_manut, r.random())
    if ra.random() < 0.25:                       # oficina sem vaga: veículo espera para entrar
        entrada += timedelta(days=ra.randint(2, 6))
    dias_execucao = ra.randint(1, 4)             # serviço depois que a peça chega
    usa_peca = not (sistema == "Revisão" and r.random() < 0.6)
    prazo_peca = (r.randint(1, 4) if not usa_peca else r.randint(3, 10))

    seq = [
        ("Data Orçamento", r.randint(0, 3)),
        ("Data Solicitação Aprovação", r.randint(0, 1)),
        ("Data Aprovação", r.randint(1, 3)),
        ("Data Pedido Compra", r.randint(0, 1)),
        ("Data Compra Efetivada", r.randint(1, 3)),
        ("Data Entrega Peça", prazo_peca),
        ("Data Real Saída", (r.randint(1, 3), dias_execucao)[1]),
        ("Data Pagamento Oficina", r.randint(2, 10)),
    ]
    prevista = r.randint(5, 14) if r.random() < 0.5 else None
    d["Data Entrada Oficina"] = _limitar(entrada)
    parou = d["Data Entrada Oficina"] is None
    atual = entrada
    for etapa, dias in seq:
        atual = atual + timedelta(days=dias)
        if parou or _limitar(atual) is None:
            parou = True
            d[etapa] = None
        else:
            d[etapa] = atual
    d["Data Prevista Saída"] = entrada + timedelta(days=prevista) if prevista and d["Data Entrada Oficina"] else None
    d["_usa_peca"] = usa_peca
    return d


def status_da_os(d: dict) -> str:
    """Status (como na planilha) pela última etapa preenchida."""
    if d["Data Real Saída"]:
        return "Concluida"
    if d["Data Entrega Peça"]:
        return "Em manutenção"
    if d["Data Aprovação"]:
        return "Aguardando pecas"
    if d["Data Orçamento"]:
        return "Aguardando aprovacao"
    if d["Data Entrada Oficina"]:
        return "Em diagnostico"
    return "Em agendamento"


def escolher_os_do_veiculo(r, v, perfil, plano):
    """Lista de (data_entrada, tipo_manutencao, sistema)."""
    eventos = []
    # preventivas a cada ~10.000 km
    km_acum, proximo = 0.0, r.uniform(3000, 10000)
    for dia, km in plano.items():
        km_acum += km
        if km_acum >= proximo:
            eventos.append((dia + timedelta(days=r.randint(0, 5)), "Preventiva", "Revisão"))
            proximo += 10000
    # corretivas
    if perfil == "agressivo":
        for s in r.sample(SISTEMAS_CONDUCAO, r.randint(2, 3)):
            eventos.append((None, "Corretiva", s))
        if r.random() < 0.4:
            eventos.append((None, "Corretiva", r.choice(OUTROS_SISTEMAS)))
    else:
        # quem dirige mais bruscamente (estilo alto) quebra mais freio, suspensão e pneu
        estilo = comum.estilo_conducao(v["Placa"], perfil)
        p_conducao = 0.05 + 0.30 * (estilo - 0.5) / 1.4
        outros = OUTROS_SISTEMAS + (SISTEMAS_DIESEL if v["Tipo"] in TIPOS_DIESEL else [])
        for _ in range(r.randint(0, 2)):
            sistema = r.choice(SISTEMAS_CONDUCAO if r.random() < p_conducao else outros)
            eventos.append((None, "Corretiva", sistema))
        if estilo > 1.3 and r.random() < (estilo - 1.3) / 0.6:
            eventos.append((None, "Corretiva", r.choice(SISTEMAS_CONDUCAO)))
    # preditiva
    if r.random() < 0.3:
        eventos.append((None, "Preditiva", r.choice(["Motor", "Transmissão", "Elétrica", "Motor"])))

    limite = 5 if perfil == "agressivo" else 4
    preventivas = [e for e in eventos if e[1] == "Preventiva"]
    outras = [e for e in eventos if e[1] != "Preventiva"]
    eventos = outras + preventivas[: max(0, limite - len(outras))]
    while len(eventos) < 2:
        eventos.append((None, "Corretiva", r.choice(OUTROS_SISTEMAS)))

    # datas de entrada das que não têm (espalhadas no período, sem sobrepor)
    datas = []
    for e in eventos:
        if e[0] is None and r.random() < 0.25:
            # parte das OS abre no fim do período -> ficam paradas em etapas diferentes
            dia = comum.BASE_FIM - timedelta(days=r.randint(0, 40))
        elif e[0] is None:
            dia = comum.INICIO_PERIODO + timedelta(days=r.randint(0, (comum.BASE_FIM - comum.INICIO_PERIODO).days - 2))
        else:
            dia = min(e[0], comum.BASE_FIM)
        datas.append((dia, e[1], e[2]))
    datas.sort()
    ajustadas, ultimo = [], None
    for dia, tm, s in datas:
        if ultimo and dia <= ultimo + timedelta(days=20):
            dia = ultimo + timedelta(days=r.randint(21, 35))
        if dia > comum.BASE_FIM:
            continue
        ajustadas.append((dia, tm, s))
        ultimo = dia
    return ajustadas


def placa_falsa(r, existentes):
    while True:
        p = ("".join(r.choice(string.ascii_uppercase) for _ in range(3)) + r.choice(string.digits)
             + r.choice(string.ascii_uppercase) + "".join(r.choice(string.digits) for _ in range(2)))
        if p not in existentes:
            return p


def sujar_texto(r, texto):
    opcao = r.randint(0, 3)
    if opcao == 0:
        return f" {texto} "
    if opcao == 1:
        return texto.upper()
    if opcao == 2:
        return texto.lower() + "  "
    return texto.replace(" ", "  ")


def km_misturado(r, km):
    km = int(round(km))
    x = r.random()
    if x < 0.40:
        return km
    if x < 0.70:
        return f"{km:,}".replace(",", ".")
    if x < 0.85:
        return f"{km} km"
    return None  # não informado


def no_planilha(valor):
    """Valor como é digitado na planilha (lista sem acento)."""
    return NA_PLANILHA.get(valor, valor)


def montar_os(r, v, abertura, tipo_manut, sistema, frota, plano):
    """Uma OS completa. As etapas que cairiam depois de "hoje" ficam vazias."""
    fluxo = montar_fluxo(r, abertura, sistema, tipo_manut)
    usa_peca = fluxo.pop("_usa_peca")
    aloc = comum.centro_custo_na_data(frota["alocacao"], v["Placa"], abertura)
    oficina = r.choice(OFICINAS)
    lo, hi = ORCAMENTO_POR_SISTEMA[sistema]
    orcamento = round(min(max(r.uniform(lo, hi) * MULT_TIPO[v["Tipo"]], 300), 12000), 2)
    fator = r.uniform(0.60, 0.78) if oficina == OFICINA_QUE_NEGOCIA else r.uniform(0.82, 1.0)
    negociado = round(orcamento * fator, 2)
    if tipo_manut == "Preventiva":
        criticidade = r.choice(["Baixa", "Baixa", "Média"])
    elif tipo_manut == "Corretiva":
        criticidade = r.choice(["Média", "Alta", "Alta"])
    else:
        criticidade = r.choice(["Baixa", "Média"])
    status = status_da_os(fluxo)
    na_oficina = fluxo["Data Entrada Oficina"] is not None
    if status == "Concluida":
        operacional = "Operando"
    elif not na_oficina:
        operacional = "Operando" if criticidade == "Baixa" else "Restrição"
    else:
        operacional = "Restrição" if criticidade == "Baixa" else "Parado"
    regional = next(c["Regional"] for c in frota["centros"] if c["ID_Centro_Custo"] == aloc["ID_Centro_Custo"])
    # sorteios sempre feitos (mesmo quando o campo fica vazio): a OS não muda quando "hoje" avança
    solicitante = f"Supervisor {regional}" if r.random() < 0.3 else None
    descricao = r.choice(DESCRICOES[sistema])
    responsavel = r.choice(["Gestor de Frota", "Coordenação de Manutenção"])
    observacao = r.choice(OBSERVACOES)

    # peças e veículo substituto: semente própria, para não mudar o resto da OS
    rx = comum.rng_de("os_extra", v["Placa"], abertura.isoformat(), sistema)
    valor_pecas = round(orcamento * rx.uniform(0.35, 0.80), 2)
    sorteio_sub, sorteio_aluguel = rx.random(), rx.random()
    diaria = round(rx.uniform(*DIARIA_POR_TIPO[v["Tipo"]]), 2)
    periodo = round(diaria * rx.uniform(18, 24), 2)
    placa_sub = placa_falsa(rx, {})
    substituto = criticidade == "Alta" and na_oficina and sorteio_sub < P_SUBSTITUTO
    aluguel = "Diária" if sorteio_aluguel < 0.7 else "Período"

    return {
        "Placa": v["Placa"],
        "Modelo": f'{v["Marca"]} {v["Modelo"]}',
        "Centro de Custo": aloc["Centro_Custo"],
        "Contrato": aloc["Contrato"],
        "Oficina": oficina,
        **fluxo,
        "Tipo de Manutenção": tipo_manut,
        "Criticidade": no_planilha(criticidade),
        "Valor Orçamento": orcamento if fluxo["Data Orçamento"] else None,
        "Valor Negociado": negociado if fluxo["Data Aprovação"] else None,
        "% Variação": round((negociado - orcamento) / orcamento, 4) if fluxo["Data Aprovação"] else None,
        "_requisicao": usa_peca and fluxo["Data Pedido Compra"] is not None,
        "Valor Peças/Itens (R$)": valor_pecas if usa_peca and fluxo["Data Compra Efetivada"] else None,
        "KM Atual": comum.odometro_na_data(v, plano, abertura),
        "Status Operacional": no_planilha(operacional),
        "Veículo Substituto?": "Sim" if substituto else "Não",
        "Placa Substituto": placa_sub if substituto else None,
        "Tipo de Aluguel": aluguel if substituto else None,
        "Valor Aluguel (R$)": (diaria if aluguel == "Diária" else periodo) if substituto else None,
        "Solicitante da Manutenção": solicitante,
        "Tipo de Sistema": no_planilha(sistema),
        "Descrição do Problema": descricao,
        "Status da Manutenção": status,
        "Responsável pela aprovação": responsavel if fluxo["Data Aprovação"] else None,
        "Observações Gerais": observacao,
    }


def os_dos_dias_novos(v, perfil, plano):
    """Depois da base: cada veículo sorteia, semana a semana (semente própria por
    semana), se abre OS. Preventiva pela km rodada na semana; agressivo quebra mais
    freio, suspensão e pneu."""
    eventos = []
    # km da semana inteira, mesmo a que ainda não acabou: a decisão da semana não
    # pode mudar conforme "hoje" avança (o plano de cada dia tem semente própria)
    plano = comum.plano_km(v, ate=comum.FIM_PERIODO + timedelta(days=7))
    semana = comum.BASE_FIM + timedelta(days=1)
    while semana <= comum.FIM_PERIODO:
        r = comum.rng_de("os_semana", v["Placa"], semana.isoformat())
        km_semana = sum(plano.get(semana + timedelta(days=i), 0) for i in range(7))
        candidatos = []
        if r.random() < km_semana / 10000:
            candidatos.append(("Preventiva", "Revisão"))
        estilo = comum.estilo_conducao(v["Placa"], perfil)
        if r.random() < (0.10 if perfil == "agressivo" else 0.02 + 0.03 * estilo):
            outros = OUTROS_SISTEMAS + (SISTEMAS_DIESEL if v["Tipo"] in TIPOS_DIESEL else [])
            sistemas = SISTEMAS_CONDUCAO if perfil == "agressivo" and r.random() < 0.7 else outros + SISTEMAS_CONDUCAO
            candidatos.append(("Corretiva", r.choice(sistemas)))
        if r.random() < 0.01:
            candidatos.append(("Preditiva", r.choice(["Motor", "Transmissão", "Elétrica", "Motor"])))
        for tipo_manut, sistema in candidatos:
            entrada = semana + timedelta(days=r.randint(0, 6))
            if entrada <= comum.FIM_PERIODO:
                eventos.append((entrada, tipo_manut, sistema))
        semana += timedelta(days=7)
    return eventos


def numero_os(reg: dict, sequencia: int) -> str:
    """BRN-26-0001: ano da abertura com 2 dígitos + sequência."""
    return f"BRN-{reg['Data da OS'].year % 100:02d}-{sequencia:04d}"


def requisicao_suja(r, req: str) -> str:
    """REQ-26-0031 digitado de outros jeitos."""
    _, ano, num = req.split("-")
    return r.choice([f"req {ano} {num}", f"REQ{ano}{num}", f" Req-{ano}-{int(num)}", f"REQ {ano}/{num}"])


def main():
    comum.argumentos("Gera a planilha fictícia de ordens de serviço.")
    frota = comum.carregar_frota()
    perfis = {p["Placa"]: p["Perfil"] for p in frota["perfis"]}
    veiculos = {v["Placa"]: v for v in frota["veiculos"]}
    r = random.Random(comum.SEMENTE + 1)

    rastreados = [v for v in frota["veiculos"] if v["Rastreador"] == "Sim"]
    agressivos = [v for v in rastreados if perfis[v["Placa"]] == "agressivo"]
    demais = [v for v in rastreados if perfis[v["Placa"]] != "agressivo"]
    # sorteio ponderado pelo estilo de condução (quem dirige pior tem mais chance de ter OS)
    peso = {v["Placa"]: comum.estilo_conducao(v["Placa"], "normal") ** 2 for v in demais}
    ordem = sorted(demais, key=lambda v: r.random() ** (1 / peso[v["Placa"]]), reverse=True)
    escolhidos = agressivos + ordem[: QTD_VEICULOS_COM_OS - len(agressivos)]
    escolhidos.sort(key=lambda v: int(v["ID_Veiculo"]))
    print(f"Gerando OS para {len(escolhidos)} veículos ({len(agressivos)} de perfil agressivo), "
          f"situação em {comum.FIM_PERIODO:%d/%m/%Y}...")

    # ---- OS da base fixa (01/05 a 31/10/2026) ----
    registros = []
    for v in escolhidos:
        rv = comum.rng_de("manutencao", v["Placa"])
        plano_base = comum.plano_km(v, ate=comum.BASE_FIM)
        for entrada, tipo_manut, sistema in escolher_os_do_veiculo(rv, v, perfis[v["Placa"]], plano_base):
            registros.append(montar_os(rv, v, entrada, tipo_manut, sistema, frota, plano_base))

    # ---- 3 OS com placa que não existe na frota (quarentena) ----
    # (a cópia herda a requisição da OS original; o número é refeito mais abaixo)
    rf = comum.rng_de("placas_falsas")
    placas_falsas = []
    for _ in range(3):
        base = dict(rf.choice(registros))
        base["Placa"] = placa_falsa(rf, veiculos)
        desloca = timedelta(days=rf.randint(1, 5))
        for col in COLUNAS_DATA:
            if base[col] is not None:
                base[col] = base[col] + desloca
        registros.append(base)
        placas_falsas.append(base["Placa"])

    # ---- Controle de Pedido Interno (número da OS), em ordem de abertura ----
    registros.sort(key=lambda x: (x["Data da OS"], x["Placa"]))
    for i, reg in enumerate(registros, start=1):
        reg[COLUNA_OS] = numero_os(reg, i)

    # ---- OS dos dias novos (modo contínuo): numeração continua depois da base ----
    novas = []
    for v in escolhidos:
        plano = comum.plano_km(v)
        for entrada, tipo_manut, sistema in os_dos_dias_novos(v, perfis[v["Placa"]], plano):
            r_os = comum.rng_de("os_nova", v["Placa"], entrada.isoformat(), sistema)
            novas.append(montar_os(r_os, v, entrada, tipo_manut, sistema, frota, plano))
    novas.sort(key=lambda x: (x["Data da OS"], x["Placa"], x["Tipo de Sistema"]))
    for i, reg in enumerate(novas, start=len(registros) + 1):
        reg[COLUNA_OS] = numero_os(reg, i)
    registros += novas

    # ---- Nº da requisição de peças: sequência pela data do pedido de compra ----
    com_req = sorted((x for x in registros if x["_requisicao"]), key=lambda x: (x["Data Pedido Compra"], x[COLUNA_OS]))
    for i, reg in enumerate(com_req, start=1):
        reg["Nº Requisição Peças"] = f"REQ-{reg['Data Pedido Compra'].year % 100:02d}-{i:04d}"

    # ---- 3 OS com substituto "Sim" e a placa do substituto vazia ----
    # (só entre OS antigas, que já não mudam: a escolha fica a mesma todo dia)
    rq = comum.rng_de("substituto_sem_placa")
    com_sub = [x for x in registros if x["Veículo Substituto?"] == "Sim" and x["Placa"] not in placas_falsas
               and x["Data da OS"] <= comum.BASE_FIM - timedelta(days=30)]
    substituto_sem_placa = rq.sample(com_sub, min(QTD_SUBSTITUTO_SEM_PLACA, len(com_sub)))
    for reg in substituto_sem_placa:
        reg["Placa Substituto"] = None

    # ---- sujeira de tipos e textos ----
    cont = {"datas_como_texto": 0, "valores_como_texto": 0, "km_numero": 0, "km_texto_com_ponto": 0,
            "km_texto_com_km": 0, "km_vazio": 0, "textos_sujos": 0, "requisicao_formato_diferente": 0,
            "substituto_sem_placa": len(substituto_sem_placa)}
    for reg in registros:
        # semente própria por OS e sorteio feito sempre: a "sujeira" de uma OS
        # não muda quando outras OS aparecem ou quando ela avança de etapa
        rs = comum.rng_de("sujeira_os", reg[COLUNA_OS])
        for col in COLUNAS_DATA:
            sorteio = rs.random()
            if reg[col] is not None and sorteio < P_DATA_TEXTO:
                reg[col] = comum.data_br(reg[col])
                cont["datas_como_texto"] += 1
        for col in ("Valor Orçamento", "Valor Negociado"):
            sorteio, prefixo = rs.random(), rs.random()
            if reg[col] is not None and sorteio < P_VALOR_TEXTO:
                reg[col] = ("R$ " if prefixo < 0.3 else "") + comum.numero_br(reg[col])
                cont["valores_como_texto"] += 1
        km = km_misturado(rs, reg["KM Atual"])
        reg["KM Atual"] = km
        if km is None:
            cont["km_vazio"] += 1
        elif isinstance(km, int):
            cont["km_numero"] += 1
        elif km.endswith("km"):
            cont["km_texto_com_km"] += 1
        else:
            cont["km_texto_com_ponto"] += 1
        for col in ("Oficina", "Tipo de Manutenção", "Criticidade", "Tipo de Sistema", "Status da Manutenção", "Centro de Custo"):
            if rs.random() < P_TEXTO_SUJO:
                reg[col] = sujar_texto(rs, reg[col])
                cont["textos_sujos"] += 1
        sorteio = rs.random()
        if reg.get("Nº Requisição Peças") and sorteio < P_REQ_SUJA:
            reg["Nº Requisição Peças"] = requisicao_suja(rs, reg["Nº Requisição Peças"])
            cont["requisicao_formato_diferente"] += 1

    # ---- gravação ----
    wb = Workbook()
    ws = wb.active
    ws.title = "FATO_Manutencao"
    ws.append(COLUNAS)
    for reg in registros:
        ws.append([reg.get(c) for c in COLUNAS])
    idx_datas = [COLUNAS.index(c) + 1 for c in COLUNAS_DATA]
    for linha in ws.iter_rows(min_row=2):
        for c in linha:
            if c.column in idx_datas and isinstance(c.value, (date, datetime)):
                c.number_format = "DD/MM/YYYY"
    comum.salvar_xlsx(wb, ARQUIVO)

    reais = [x for x in registros if x["Placa"] not in placas_falsas]
    status_limpo = lambda x: " ".join(x.split()).capitalize()
    tipos = {}
    for x in reais:
        t = status_limpo(x["Tipo de Manutenção"])
        tipos[t] = tipos.get(t, 0) + 1
    resumo = {
        "arquivo": ARQUIVO.name,
        "os_total": len(registros),
        "os_placa_valida": len(reais),
        "veiculos_com_os": len({x["Placa"] for x in reais}),
        "os_por_tipo": tipos,
        "os_por_status": {s: sum(1 for x in reais if status_limpo(x["Status da Manutenção"]) == status_limpo(s))
                          for s in STATUS_PLANILHA},
        "os_com_substituto": sum(1 for x in reais if x["Veículo Substituto?"] == "Sim"),
        "problemas": {**cont, "os_placa_inexistente": len(placas_falsas)},
        "placas_inexistentes": placas_falsas,
    }
    comum.PASTA_GABARITO.mkdir(parents=True, exist_ok=True)
    with open(comum.PASTA_GABARITO / "manutencao.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)

    print(f"  OS: {resumo['os_total']} ({resumo['os_placa_valida']} com placa válida, "
          f"{resumo['veiculos_com_os']} veículos) | por tipo: {tipos}")
    print(f"  Por status: {resumo['os_por_status']}")
    print("  Problemas plantados:")
    for chave, valor in resumo["problemas"].items():
        print(f"    {chave}: {valor}")
    print(f"  Placas inexistentes: {', '.join(placas_falsas)}")
    print(f"  Arquivo: {ARQUIVO}")


if __name__ == "__main__":
    main()
