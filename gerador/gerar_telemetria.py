"""
=========================================================
GERAR_TELEMETRIA.PY — relatórios fictícios do rastreador
=========================================================
Projeto: brn-frota-data-platform (dados 100% fictícios)

Gera, em entrada/telemetria/, os dois relatórios que o rastreador
exporta, no MESMO formato do export real (moldes do Drive):

  Relatorio_Rastreamento_Alertasenotificacoes_<AAAAMMDD>.xlsx
      35 colunas, cabeçalho em 2 linhas mescladas, valores como texto
      (números com vírgula decimal, tempos em hh:mm:ss)
  Relatorio_Rastreamento_PeriodosDeUtilizacao_<AAAAMMDD>.xlsx  (BDV)
      22 colunas, cabeçalho em 1 linha

Período: base fixa de 6 meses (01/05 a 31/10/2026) em exportações semanais
de 8 dias (o último dia de cada arquivo se repete no seguinte) + com --ate,
os dias novos até "ontem", um arquivo por dia cobrindo ontem e hoje.

Comportamento por perfil (entrada/_gabarito/perfis_veiculos.csv):
  agressivo -> ~3x mais excesso de velocidade, freada, aceleração e curva brusca
  (os normais também variam: cada veículo tem seu estilo, de 0,5x a 1,9x)
  ocioso    -> motor ocioso bem acima da média

Problemas reais plantados DE PROPÓSITO (o pipeline tem que tratar):
  1. mesmo alerta/viagem em dois arquivos (períodos sobrepostos)
  2. alerta exportado em aberto e, no arquivo seguinte, fechado
  3. motorista vazio num arquivo e preenchido no seguinte
  4. linha repetida dentro do mesmo arquivo
  5. viagens impossíveis (300 mil km em 3 h, distância negativa,
     eficiência > 100 km/l) e alerta de velocidade >= 150 km/h sem
     variação de odômetro (erro do equipamento)
  6. linhas de rodapé TOTAL / MÉDIA no fim dos relatórios

As contagens de cada problema vão para entrada/_gabarito/telemetria.json
(só para conferência — o pipeline não lê o gabarito).

Uso (na raiz do projeto):
    py gerador/gerar_telemetria.py               # base fixa (reproduzível)
    py gerador/gerar_telemetria.py --ate ontem   # base + dias novos até ontem
=========================================================
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta

from openpyxl import Workbook

import comum

# ---------------------------------------------------------
# Layout exato dos relatórios
# ---------------------------------------------------------
# Alertas: linha 1 (grupos/colunas mescladas na vertical) e linha 2 (subcolunas)
ALERTAS_LINHA1 = {
    "B": "Unidade rastreada", "C": "Motorista", "D": "Nº ordem rastreador", "E": "Alerta",
    "S": "Chamado", "AE": "Grupo de unidades rastreadas", "AF": "Unidade organizacional",
    "AG": "Local início", "AH": "Local fim", "AI": "Modo de violação",
}
ALERTAS_LINHA2 = {
    "E": "Telemetrias (mínima | máxima | média)", "F": "Áreas e rotas geográficas", "G": "Entradas",
    "H": "Saídas", "I": "Eventos de controle", "J": "Nome da regra", "K": "Data da ocorrência",
    "L": "Hora da ocorrência", "M": "Finalização da ocorrência", "N": "Duração", "O": "Odômetro inicial",
    "P": "Odômetro final", "Q": "Distância", "R": "Grupo de regras", "S": "Requer tratamento",
    "T": "Situação do chamado", "U": "Status do chamado", "V": "Nível", "W": "Categoria do chamado",
    "X": "Ticket", "Y": "Data da criação", "Z": "Duração do chamado", "AA": "Limite para fechar",
    "AB": "Usuário respónsável", "AC": "Tempo para abrir", "AD": "Limite para abrir",
}
ALERTAS_MESCLAGENS = ["A1:A2", "B1:B2", "C1:C2", "D1:D2", "E1:R1", "S1:AD1",
                      "AE1:AE2", "AF1:AF2", "AG1:AG2", "AH1:AH2", "AI1:AI2"]

BDV_COLUNAS = [
    "Unidade rastreada", "Motorista", "Data inicial", "Data final", "Distância (Odo)", "Duração (Dt)",
    "Motor ocioso (T)", "Consumo (l)", "Eficiência (km/l)", "Meta consumo (%)", "Economia (R$)",
    "Gasto combustível movimento", "Gasto combustível ocioso", "Gasto combustível total", "Vel. máxima",
    "Vel. média em movimento", "Grupo de unidades rastreadas", "Unidade organizacional",
    "Endereço inicial", "Endereço final", "Quantidade de frenagem", "Tempo de frenagem",
]

# ---------------------------------------------------------
# Parâmetros físicos por tipo de veículo
# ---------------------------------------------------------
VIAGENS_DIA = {"Leve": (3, 8), "Pick-up": (3, 7), "Van": (3, 7), "Caminhão": (2, 5), "Ônibus": (3, 6), "Moto": (3, 8)}
VEL_MEDIA = {"Leve": 34, "Pick-up": 38, "Van": 33, "Caminhão": 36, "Ônibus": 30, "Moto": 30}
EFICIENCIA = {"Leve": 12.0, "Pick-up": 9.0, "Van": 8.5, "Caminhão": 3.8, "Ônibus": 3.0, "Moto": 32.0}
LIMITE_VEL = {"Leve": 80, "Pick-up": 80, "Van": 80, "Caminhão": 70, "Ônibus": 70, "Moto": 80}

# alertas por 100 km na média da frota; cada veículo tem seu multiplicador
# (comum.estilo_conducao): normal de 0,5x a 1,9x, agressivo perto de 3x
TAXA_ALERTA_100KM = {"Excesso de velocidade": 0.9, "Freada brusca": 0.7, "Aceleração brusca": 0.6, "Curva brusca": 0.3}

RUAS = ["Rua das Acácias", "Av. Central", "Rua do Comércio", "Rua Sete", "Av. dos Pioneiros",
        "Rua da Estação", "Rod. Estadual km 12", "Rua das Palmeiras", "Av. Beira Rio", "Rua Nova"]
BAIRROS = ["Centro", "Jardim Primavera", "Distrito Industrial", "Vila Nova", "Parque das Flores", "Alto da Serra"]

# Proporções dos problemas plantados
P_DUPLICADA_NO_ARQUIVO = 0.004   # linha repetida dentro do arquivo
P_ALERTA_EM_ABERTO = 0.10        # dos alertas do dia de sobreposição, no 1º arquivo
P_MOTORISTA_VAZIO_DEPOIS = 0.06  # dos registros do dia de sobreposição, no 1º arquivo
P_MOTORISTA_SEMPRE_VAZIO = 0.03  # motorista nunca identificado ("Indefinido" no pipeline)
P_VIAGEM_IMPOSSIVEL_DIA_NOVO = 0.00015   # ~1 a cada 2 semanas nos dias novos
P_VELOCIDADE_150_DIA_NOVO = 0.0013      # ~1 a cada 2 dias nos dias novos


def endereco(r, cidade):
    return f"{r.choice(RUAS)}, {r.randint(10, 2500)}, {r.choice(BAIRROS)}, {cidade}"


def regional_na_data(alocacao, centros, placa, dia):
    aloc = comum.centro_custo_na_data(alocacao, placa, dia)
    cc = next(c for c in centros if c["ID_Centro_Custo"] == aloc["ID_Centro_Custo"])
    return cc["Regional"], cc["Cidade"]


# ---------------------------------------------------------
# Simulação de viagens e alertas de um veículo
# ---------------------------------------------------------
def simular_veiculo(v, perfil, frota):
    placa, tipo = v["Placa"], v["Tipo"]
    plano = comum.plano_km(v)
    odo = comum.odometro_inicial(v)
    nomes = [m["Motorista"] for m in frota["motoristas"]]
    unidade = comum.descricao_unidade(v)
    viagens, alertas = [], []

    for dia, km_dia in plano.items():
        if km_dia <= 0:
            continue
        r = comum.rng_de("viagens", placa, dia.isoformat())
        regional, cidade = regional_na_data(frota["alocacao"], frota["centros"], placa, dia)
        grupo = f"Unidade {regional}"

        n = r.randint(*VIAGENS_DIA[tipo])
        pesos = [r.uniform(0.5, 1.5) for _ in range(n)]
        kms = [km_dia * p / sum(pesos) for p in pesos]
        inicio = datetime(dia.year, dia.month, dia.day, 6, 0) + timedelta(minutes=r.randint(0, 90))
        local = endereco(r, cidade)

        for km in kms:
            vel_mov = VEL_MEDIA[tipo] * r.uniform(0.75, 1.25)
            min_mov = km / vel_mov * 60
            if perfil["Perfil"] == "ocioso":
                ocioso = min_mov * r.uniform(0.25, 0.60)
            else:
                ocioso = min_mov * r.uniform(0.0, 0.10)
            duracao = min_mov + ocioso
            fim = inicio + timedelta(seconds=round(duracao * 60))
            if fim.date() != dia:
                break

            vel_max = min(vel_mov * r.uniform(1.6, 2.4), 125 if perfil["Perfil"] == "agressivo" else 110)
            eff = EFICIENCIA[tipo] * r.uniform(0.85, 1.12) * (0.88 if perfil["Perfil"] == "agressivo" else 1.0)
            consumo = km / eff + ocioso / 60 * (0.8 if tipo in ("Leve", "Moto") else 2.0)
            frenagens = int(km * r.uniform(0.3, 1.0) * (1.8 if perfil["Perfil"] == "agressivo" else 1.0))

            if r.random() < P_MOTORISTA_SEMPRE_VAZIO:
                motorista = ""
            elif r.random() < 0.85:
                motorista = perfil["Motorista_Principal"]
            else:
                motorista = r.choice(nomes)

            destino = endereco(r, cidade)
            viagem = {
                "placa": placa, "dia": dia, "inicio": inicio, "fim": fim,
                "linha": {
                    "Unidade rastreada": unidade,
                    "Motorista": motorista,
                    "Data inicial": comum.data_hora_br(inicio),
                    "Data final": comum.data_hora_br(fim),
                    "Distância (Odo)": comum.numero_br(km),
                    "Duração (Dt)": comum.hhmmss(duracao),
                    "Motor ocioso (T)": comum.hhmmss(ocioso),
                    "Consumo (l)": comum.numero_br(consumo),
                    "Eficiência (km/l)": comum.numero_br(km / consumo),
                    "Vel. máxima": str(round(vel_max)),
                    "Vel. média em movimento": str(round(vel_mov)),
                    "Grupo de unidades rastreadas": grupo,
                    "Unidade organizacional": comum.UNIDADE_ORGANIZACIONAL,
                    "Endereço inicial": local,
                    "Endereço final": destino,
                    "Quantidade de frenagem": frenagens,
                    "Tempo de frenagem": comum.hhmmss(frenagens * r.uniform(2, 4) / 60),
                },
            }
            viagens.append(viagem)

            # ---- alertas de condução ao longo da viagem ----
            mult = comum.estilo_conducao(v["Placa"], perfil["Perfil"])
            for regra, taxa in TAXA_ALERTA_100KM.items():
                esperado = km / 100 * taxa * mult
                qtd = int(esperado) + (1 if r.random() < esperado - int(esperado) else 0)
                for _ in range(qtd):
                    frac = r.random()
                    quando = inicio + timedelta(seconds=round(min_mov * 60 * frac))
                    odo_ini = odo + km * frac
                    if regra == "Excesso de velocidade":
                        lim = LIMITE_VEL[tipo]
                        dur = r.uniform(0.3, 3.0)
                        vmax = lim + r.uniform(5, 35) * (1.3 if perfil["Perfil"] == "agressivo" else 1)
                        vmed = (lim + vmax) / 2
                        vmin = lim + r.uniform(1, 4)
                        dist = vmed * dur / 60
                    else:
                        dur = r.uniform(2, 6) / 60
                        vmed = vel_mov * r.uniform(0.8, 1.3)
                        vmin, vmax = vmed * 0.6, vmed * 1.1
                        dist = vmed * dur / 60
                    alertas.append(_alerta(r, placa, unidade, motorista, regra, quando, dur,
                                           odo_ini, odo_ini + dist, (vmin, vmax, vmed), grupo, local, destino))

            # ---- alerta de motor ocioso (pipeline só conta >= 5 min) ----
            if ocioso >= 1 and r.random() < (0.9 if perfil["Perfil"] == "ocioso" else 0.10):
                dur = min(ocioso, r.uniform(1, 40))
                quando = inicio + timedelta(seconds=r.randint(0, max(int(duracao * 60 - dur * 60), 1)))
                alertas.append(_alerta(r, placa, unidade, motorista, "Motor ocioso", quando, dur,
                                       odo + km, odo + km, (0, 0, 0), grupo, local, destino))

            odo += km
            local = destino
            inicio = fim + timedelta(minutes=r.randint(10, 90))
            if inicio.date() != dia:
                break

    return viagens, alertas


def _alerta(r, placa, unidade, motorista, regra, quando, dur_min, odo_ini, odo_fim, vel, grupo, local, destino):
    fim = quando + timedelta(seconds=round(dur_min * 60))
    if regra == "Motor ocioso":
        telemetria = f"[RPM: {comum.numero_br(r.uniform(650, 750), 1)} | {comum.numero_br(r.uniform(800, 950), 1)} | {comum.numero_br(r.uniform(750, 820), 1)}]"
    else:
        vmin, vmax, vmed = vel
        telemetria = f"[Velocidade: {comum.numero_br(vmin, 1)} | {comum.numero_br(vmax, 1)} | {comum.numero_br(vmed, 1)}]"
    return {
        "placa": placa, "regra": regra, "quando": quando,
        "linha": {
            "B": unidade, "C": motorista, "E": telemetria, "J": regra,
            "K": comum.data_br(quando), "L": quando.strftime("%H:%M:%S"),
            "M": comum.data_hora_br(fim), "N": comum.hhmmss(dur_min),
            "O": comum.numero_br(odo_ini), "P": comum.numero_br(odo_fim),
            "Q": comum.numero_br(odo_fim - odo_ini),
            "R": "Eficiência" if regra == "Motor ocioso" else "Segurança",
            "S": "Não", "T": "Não tratado", "AA": "00:00:00", "AD": "00:00:00",
            "AE": grupo, "AF": comum.UNIDADE_ORGANIZACIONAL, "AG": local, "AH": destino,
            "AI": "Em tempo real",
        },
    }


# ---------------------------------------------------------
# Problemas plantados que não saem naturalmente da simulação
# ---------------------------------------------------------
def plantar_viagens_impossiveis(r, viagens, dias_sobrepostos, gabarito):
    """Corrompe viagens fora dos dias de sobreposição (cada uma aparece em 1 arquivo só)."""
    candidatas = [vg for vg in viagens if vg["dia"] <= comum.BASE_FIM and vg["dia"] not in dias_sobrepostos]
    escolhidas = r.sample(candidatas, 12)
    for i, vg in enumerate(escolhidas):
        ln = vg["linha"]
        if i < 4:
            motivo = "300 mil km em 3 h"
            ln["Distância (Odo)"] = comum.numero_br(300000 + r.uniform(0, 5000))
            ln["Duração (Dt)"] = "03:00:00"
        elif i < 8:
            motivo = "distância negativa"
            ln["Distância (Odo)"] = comum.numero_br(-r.uniform(5, 60))
        else:
            motivo = "eficiência acima de 100 km/l"
            ln["Consumo (l)"] = comum.numero_br(r.uniform(0.05, 0.2))
            ln["Eficiência (km/l)"] = comum.numero_br(r.uniform(110, 400))
        gabarito["viagens_impossiveis"].append(
            {"placa": vg["placa"], "data_inicial": ln["Data inicial"], "data_final": ln["Data final"], "motivo": motivo})


def plantar_velocidade_sem_odometro(r, alertas, dias_sobrepostos, gabarito):
    """Excesso de velocidade >= 150 km/h: 15 sem variação de odômetro (erro do equipamento)
    e 10 com odômetro confirmando (devem ser mantidos)."""
    candidatas = [a for a in alertas if a["regra"] == "Excesso de velocidade"
                  and a["quando"].date() <= comum.BASE_FIM and a["quando"].date() not in dias_sobrepostos]
    escolhidas = r.sample(candidatas, 25)
    for i, a in enumerate(escolhidas):
        ln = a["linha"]
        vmax = r.uniform(150, 190)
        vmed = r.uniform(140, vmax)
        ln["E"] = f"[Velocidade: {comum.numero_br(vmed - 20, 1)} | {comum.numero_br(vmax, 1)} | {comum.numero_br(vmed, 1)}]"
        chave = {"placa": a["placa"], "regra": a["regra"], "data_hora": comum.data_hora_br(a["quando"])}
        if i < 15:
            ln["P"] = ln["O"]
            ln["Q"] = comum.numero_br(0)
            gabarito["velocidade_sem_odometro"].append(chave)
        else:
            gabarito["velocidade_150_confirmada"].append(chave)


def plantar_dias_novos(viagens, alertas, gabarito):
    """Nos dias novos, cada viagem/alerta decide sozinho (semente própria) se vira
    problema — assim o passado não muda quando a simulação avança."""
    for vg in viagens:
        if vg["dia"] <= comum.BASE_FIM:
            continue
        ln = vg["linha"]
        r = comum.rng_de("impossivel", vg["placa"], ln["Data inicial"])
        if r.random() >= P_VIAGEM_IMPOSSIVEL_DIA_NOVO:
            continue
        tipo = r.randint(0, 2)
        if tipo == 0:
            motivo = "300 mil km em 3 h"
            ln["Distância (Odo)"] = comum.numero_br(300000 + r.uniform(0, 5000))
            ln["Duração (Dt)"] = "03:00:00"
        elif tipo == 1:
            motivo = "distância negativa"
            ln["Distância (Odo)"] = comum.numero_br(-r.uniform(5, 60))
        else:
            motivo = "eficiência acima de 100 km/l"
            ln["Consumo (l)"] = comum.numero_br(r.uniform(0.05, 0.2))
            ln["Eficiência (km/l)"] = comum.numero_br(r.uniform(110, 400))
        gabarito["viagens_impossiveis"].append(
            {"placa": vg["placa"], "data_inicial": ln["Data inicial"], "data_final": ln["Data final"], "motivo": motivo})
    for a in alertas:
        if a["quando"].date() <= comum.BASE_FIM or a["regra"] != "Excesso de velocidade":
            continue
        r = comum.rng_de("vel150", a["placa"], a["quando"].isoformat())
        if r.random() >= P_VELOCIDADE_150_DIA_NOVO:
            continue
        ln = a["linha"]
        vmax = r.uniform(150, 190)
        vmed = r.uniform(140, vmax)
        ln["E"] = f"[Velocidade: {comum.numero_br(vmed - 20, 1)} | {comum.numero_br(vmax, 1)} | {comum.numero_br(vmed, 1)}]"
        chave = {"placa": a["placa"], "regra": a["regra"], "data_hora": comum.data_hora_br(a["quando"])}
        if r.random() < 0.6:
            ln["P"] = ln["O"]
            ln["Q"] = comum.numero_br(0)
            gabarito["velocidade_sem_odometro"].append(chave)
        else:
            gabarito["velocidade_150_confirmada"].append(chave)


# ---------------------------------------------------------
# Exportações: semanais na base fixa, diárias nos dias novos
# ---------------------------------------------------------
def janelas_exportacao():
    """
    Lista de (inicio, fim, semente, ultimo_dia_se_repete).
    Base fixa: arquivos de 8 dias começando a cada 7 (o último dia se repete no
    arquivo seguinte). Dias novos (após 31/10/2026): um arquivo por dia cobrindo
    ontem e hoje (o dia se repete no arquivo do dia seguinte). Cada arquivo tem
    semente própria: o arquivo de um dia é sempre o mesmo, rode quando rodar.
    """
    janelas = []
    ini, k = comum.INICIO_PERIODO, 0
    while ini <= comum.BASE_FIM:
        fim = min(ini + timedelta(days=7), comum.BASE_FIM)
        janelas.append((ini, fim, ("exportacao", k), fim != comum.BASE_FIM))
        if fim == comum.BASE_FIM:
            break
        ini += timedelta(days=7)
        k += 1
    dia = comum.BASE_FIM + timedelta(days=1)
    while dia <= comum.FIM_PERIODO:
        janelas.append((dia - timedelta(days=1), dia, ("exportacao_dia", dia.isoformat()), True))
        dia += timedelta(days=1)
    return janelas


def _indices_por_dia(itens, dia_de):
    por_dia = defaultdict(list)
    for idx, item in enumerate(itens):
        por_dia[dia_de(item)].append(idx)
    return por_dia


def _indices_da_janela(por_dia, ini, fim):
    """Índices dos itens da janela, na ordem original (mantém a semente estável)."""
    idxs = []
    d = ini
    while d <= fim:
        idxs.extend(por_dia.get(d, []))
        d += timedelta(days=1)
    return sorted(idxs)


def escrever_alertas(caminho, linhas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    for col, txt in ALERTAS_LINHA1.items():
        ws[f"{col}1"] = txt
    for col, txt in ALERTAS_LINHA2.items():
        ws[f"{col}2"] = txt
    for faixa in ALERTAS_MESCLAGENS:
        ws.merge_cells(faixa)
    for i, ln in enumerate(linhas, start=3):
        for col, valor in ln.items():
            if valor != "" and valor is not None:
                ws[f"{col}{i}"] = valor
    comum.salvar_xlsx(wb, caminho)


def escrever_bdv(caminho, linhas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    ws.append(BDV_COLUNAS)
    for ln in linhas:
        ws.append([ln.get(c, None) if ln.get(c, "") != "" else None for c in BDV_COLUNAS])
    comum.salvar_xlsx(wb, caminho)


def rodape_bdv(linhas):
    dist = [comum_float(l["Distância (Odo)"]) for l in linhas]
    cons = [comum_float(l["Consumo (l)"]) for l in linhas]
    total = {"Unidade rastreada": "TOTAL", "Distância (Odo)": comum.numero_br(sum(dist)),
             "Consumo (l)": comum.numero_br(sum(cons))}
    media = {"Unidade rastreada": "MÉDIA", "Distância (Odo)": comum.numero_br(sum(dist) / len(dist)),
             "Consumo (l)": comum.numero_br(sum(cons) / len(cons))}
    return [total, media]


def comum_float(texto):
    return float(str(texto).replace(".", "").replace(",", "."))


def main():
    comum.argumentos("Gera os relatórios fictícios do rastreador.")
    frota = comum.carregar_frota()
    perfis = {p["Placa"]: p for p in frota["perfis"]}
    rastreados = [v for v in frota["veiculos"] if v["Rastreador"] == "Sim"]
    print(f"Simulando telemetria de {len(rastreados)} veículos com rastreador "
          f"({comum.INICIO_PERIODO:%d/%m/%Y} a {comum.FIM_PERIODO:%d/%m/%Y})...")

    viagens, alertas = [], []
    for v in rastreados:
        vg, al = simular_veiculo(v, perfis[v["Placa"]], frota)
        viagens.extend(vg)
        alertas.extend(al)

    janelas = janelas_exportacao()
    dias_sobrepostos = {fim for (_, fim, _, repete) in janelas if repete and fim <= comum.BASE_FIM}

    r = comum.rng_de("problemas_telemetria")
    gabarito = {"viagens_impossiveis": [], "velocidade_sem_odometro": [], "velocidade_150_confirmada": []}
    plantar_viagens_impossiveis(r, viagens, dias_sobrepostos, gabarito)
    plantar_velocidade_sem_odometro(r, alertas, dias_sobrepostos, gabarito)
    plantar_dias_novos(viagens, alertas, gabarito)
    alertas_por_dia = _indices_por_dia(alertas, lambda a: a["quando"].date())
    viagens_por_dia = _indices_por_dia(viagens, lambda vg: vg["dia"])

    comum.PASTA_TELEMETRIA.mkdir(parents=True, exist_ok=True)
    for antigo in comum.PASTA_TELEMETRIA.glob("Relatorio_Rastreamento_*.xlsx"):
        antigo.unlink()

    cont = {"arquivos_alertas": 0, "arquivos_bdv": 0, "linhas_alertas_nos_arquivos": 0, "linhas_bdv_nos_arquivos": 0,
            "alertas_em_2_arquivos": 0, "viagens_em_2_arquivos": 0, "alertas_em_aberto_depois_fechados": 0,
            "motorista_vazio_depois_preenchido": 0, "linhas_repetidas_no_mesmo_arquivo": 0,
            "linhas_de_rodape": 0}
    em_aberto = set()        # índices de alertas exportados em aberto no 1º arquivo
    motorista_tardio = set()  # ids (alerta/viagem) com motorista vazio no 1º arquivo

    abertos_no_ultimo_dia = 0
    for ini, fim, semente, repete_ultimo_dia in janelas:
        rk = comum.rng_de(*semente)
        exportado_em = fim + timedelta(days=1)
        sufixo = exportado_em.strftime("%Y%m%d")

        # ---------- alertas ----------
        linhas_al = []
        for idx in _indices_da_janela(alertas_por_dia, ini, fim):
            a = alertas[idx]
            d = a["quando"].date()
            ln = dict(a["linha"])
            if d == fim and repete_ultimo_dia:
                # dia que vai se repetir no próximo arquivo
                cont["alertas_em_2_arquivos"] += 1
                if rk.random() < P_ALERTA_EM_ABERTO:
                    for col in ("M", "N", "P", "Q"):
                        ln[col] = ""
                    if d == comum.FIM_PERIODO:
                        abertos_no_ultimo_dia += 1     # fecha no arquivo de amanhã
                    else:
                        em_aberto.add(idx)
                if ln["C"] and rk.random() < P_MOTORISTA_VAZIO_DEPOIS:
                    ln["C"] = ""
                    motorista_tardio.add(("a", idx))
            linhas_al.append(ln)
        linhas_al.sort(key=lambda l: (l["K"][6:] + l["K"][3:5] + l["K"][:2], l["L"], l["B"]))
        linhas_al, dup = _repetir_linhas(rk, linhas_al)
        cont["linhas_repetidas_no_mesmo_arquivo"] += dup
        for i, ln in enumerate(linhas_al, start=1):
            ln["D"] = str(i)
        linhas_al.append({"B": "TOTAL", "D": str(len(linhas_al))})
        cont["linhas_de_rodape"] += 1
        escrever_alertas(comum.PASTA_TELEMETRIA / f"Relatorio_Rastreamento_Alertasenotificacoes_{sufixo}.xlsx", linhas_al)
        cont["arquivos_alertas"] += 1
        cont["linhas_alertas_nos_arquivos"] += len(linhas_al)

        # ---------- BDV ----------
        linhas_bdv = []
        for idx in _indices_da_janela(viagens_por_dia, ini, fim):
            vg = viagens[idx]
            ln = dict(vg["linha"])
            if vg["dia"] == fim and repete_ultimo_dia:
                cont["viagens_em_2_arquivos"] += 1
                if ln["Motorista"] and rk.random() < P_MOTORISTA_VAZIO_DEPOIS:
                    ln["Motorista"] = ""
                    motorista_tardio.add(("v", idx))
            linhas_bdv.append(ln)
        linhas_bdv.sort(key=lambda l: (l["Unidade rastreada"], l["Data inicial"][6:10] + l["Data inicial"][3:5] + l["Data inicial"][:2] + l["Data inicial"][11:]))
        linhas_bdv, dup = _repetir_linhas(rk, linhas_bdv)
        cont["linhas_repetidas_no_mesmo_arquivo"] += dup
        linhas_bdv.extend(rodape_bdv(linhas_bdv))
        cont["linhas_de_rodape"] += 2
        escrever_bdv(comum.PASTA_TELEMETRIA / f"Relatorio_Rastreamento_PeriodosDeUtilizacao_{sufixo}.xlsx", linhas_bdv)
        cont["arquivos_bdv"] += 1
        cont["linhas_bdv_nos_arquivos"] += len(linhas_bdv)

    cont["alertas_em_aberto_depois_fechados"] = len(em_aberto)
    cont["alertas_em_aberto_no_ultimo_dia (fecham amanha)"] = abertos_no_ultimo_dia
    cont["motorista_vazio_depois_preenchido"] = len(motorista_tardio)

    alertas_motor_ocioso = sum(1 for a in alertas if a["regra"] == "Motor ocioso")
    ociosos_5min = sum(1 for a in alertas if a["regra"] == "Motor ocioso" and comum_minutos(a["linha"]["N"]) >= 5)
    resumo = {
        "periodo": [comum.INICIO_PERIODO.isoformat(), comum.FIM_PERIODO.isoformat()],
        "veiculos_com_telemetria": len(rastreados),
        "viagens_unicas": len(viagens),
        "alertas_unicos": len(alertas),
        "alertas_por_regra": {rg: sum(1 for a in alertas if a["regra"] == rg)
                              for rg in list(TAXA_ALERTA_100KM) + ["Motor ocioso"]},
        "alertas_motor_ocioso_5min_ou_mais": ociosos_5min,
        "motorista_sempre_vazio_viagens": sum(1 for vg in viagens if vg["linha"]["Motorista"] == ""),
        "problemas": {**cont,
                      "viagens_impossiveis": len(gabarito["viagens_impossiveis"]),
                      "velocidade_150_sem_odometro": len(gabarito["velocidade_sem_odometro"]),
                      "velocidade_150_confirmada": len(gabarito["velocidade_150_confirmada"])},
        "detalhe": gabarito,
    }
    comum.PASTA_GABARITO.mkdir(parents=True, exist_ok=True)
    with open(comum.PASTA_GABARITO / "telemetria.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)

    def mil(n):
        return f"{n:,}".replace(",", ".")

    print(f"  Viagens únicas: {mil(len(viagens))} | Alertas únicos: {mil(len(alertas))} "
          f"(motor ocioso: {mil(alertas_motor_ocioso)}; desses, >= 5 min: {mil(ociosos_5min)})")
    print(f"  Arquivos: {cont['arquivos_alertas']} de alertas + {cont['arquivos_bdv']} de BDV em {comum.PASTA_TELEMETRIA}")
    print("  Problemas plantados:")
    for chave, valor in resumo["problemas"].items():
        if not chave.startswith(("arquivos", "linhas_alertas", "linhas_bdv")):
            print(f"    {chave}: {valor}")


def comum_minutos(hhmmss):
    h, m, s = (int(p) for p in hhmmss.split(":"))
    return h * 60 + m + s / 60


def _repetir_linhas(r, linhas):
    """Repete algumas linhas logo abaixo delas mesmas (export com linha duplicada)."""
    saida, dup = [], 0
    for ln in linhas:
        saida.append(ln)
        if r.random() < P_DUPLICADA_NO_ARQUIVO:
            saida.append(dict(ln))
            dup += 1
    return saida, dup


if __name__ == "__main__":
    main()
