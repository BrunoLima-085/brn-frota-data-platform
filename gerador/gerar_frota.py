"""
=========================================================
GERAR_FROTA.PY — dimensões da frota fictícia
=========================================================
Projeto: brn-frota-data-platform (dados 100% fictícios)

Cria a "verdade" das dimensões, lida pelos outros dois geradores
(as mesmas placas aparecem na telemetria e na manutenção):

  entrada/frota/veiculos.csv       123 veículos (placas Mercosul geradas)
  entrada/frota/centros_custo.csv  12 centros de custo em 12 capitais das 5 regiões do país
  entrada/frota/alocacao.csv       período de alocação de cada veículo;
                                   ~10% trocam de centro de custo no período
  entrada/frota/motoristas.csv     "Motorista 001" a "Motorista 150"
  entrada/_gabarito/perfis_veiculos.csv
                                   perfil de condução (normal / agressivo / ocioso)
                                   e motorista principal. É gabarito para conferência:
                                   o pipeline NÃO lê esta pasta.

Uso (na raiz do projeto):  py gerador/gerar_frota.py
=========================================================
"""

import random
import string
from datetime import date, timedelta

import comum

# Distribuição da frota (soma 123)
QTD_POR_TIPO = {"Leve": 55, "Pick-up": 25, "Van": 12, "Caminhão": 12, "Ônibus": 6, "Moto": 13}

# (marca, modelo, faixa de valor FIPE em R$)
MODELOS = {
    "Leve": [("VW", "Gol 1.0", (45000, 70000)), ("Fiat", "Mobi 1.0", (48000, 68000)),
             ("Renault", "Kwid 1.0", (50000, 70000)), ("Chevrolet", "Onix 1.0", (60000, 90000)),
             ("Hyundai", "HB20 1.0", (60000, 88000)), ("Fiat", "Argo 1.3", (65000, 92000))],
    "Pick-up": [("Fiat", "Strada 1.3", (85000, 120000)), ("VW", "Saveiro 1.6", (75000, 105000)),
                ("Toyota", "Hilux 2.8", (190000, 290000)), ("Chevrolet", "S10 2.8", (170000, 260000)),
                ("Mitsubishi", "L200 2.4", (160000, 240000))],
    "Van": [("Renault", "Master 2.3", (150000, 220000)), ("Fiat", "Ducato 2.2", (150000, 230000)),
            ("Mercedes-Benz", "Sprinter 2.2", (190000, 290000))],
    "Caminhão": [("VW", "Delivery 11.180", (230000, 330000)), ("Mercedes-Benz", "Accelo 1016", (240000, 340000)),
                 ("Ford", "Cargo 1119", (220000, 310000)), ("Volvo", "VM 270", (420000, 560000))],
    "Ônibus": [("Mercedes-Benz", "OF 1721", (380000, 520000)), ("VW", "15.190 OD", (360000, 500000))],
    "Moto": [("Honda", "CG 160", (14000, 20000)), ("Yamaha", "Factor 150", (13000, 18000)),
             ("Honda", "Bros 160", (17000, 23000))],
}
CORES = ["Branco", "Branco", "Branco", "Prata", "Preto", "Cinza", "Vermelho"]
# Empresas do grupo (fictícias) que são donas dos veículos
FILIAIS = ["BRN Locações", "BRN Serviços", "BRN Transportes", "BRN Logística"]
PESOS_FILIAIS = [50, 25, 15, 10]
LETRAS_CHASSI = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"   # chassi não usa I, O e Q

# Cidades reais (só elas): placa, chassi, motorista e oficina continuam fictícios.
# Um centro de custo por cidade; a regional é a região do IBGE.
CENTROS = [("Norte", "Belém"), ("Norte", "Manaus"),
           ("Nordeste", "Fortaleza"), ("Nordeste", "Recife"), ("Nordeste", "Salvador"),
           ("Centro-Oeste", "Brasília"), ("Centro-Oeste", "Goiânia"),
           ("Sudeste", "São Paulo"), ("Sudeste", "Rio de Janeiro"), ("Sudeste", "Belo Horizonte"),
           ("Sul", "Curitiba"), ("Sul", "Porto Alegre")]
CONTRATOS = [f"Contrato {i:02d}" for i in range(1, 7)]
OPERACOES = ["Distribuição", "Transporte de pessoal", "Manutenção de redes",
             "Apoio administrativo", "Coleta", "Obras"]
QTD_MOTORISTAS = 150


def gerar_placa(r: random.Random, usadas: set) -> str:
    """Padrão Mercosul AAA9A99."""
    while True:
        p = (
            "".join(r.choice(string.ascii_uppercase) for _ in range(3))
            + r.choice(string.digits)
            + r.choice(string.ascii_uppercase)
            + "".join(r.choice(string.digits) for _ in range(2))
        )
        if p not in usadas:
            usadas.add(p)
            return p


def gerar_ano_fabricacao(r: random.Random) -> int:
    """Poucos antigos, maioria recente (2008 a 2026)."""
    if r.random() < 0.12:
        return r.randint(2008, 2015)
    return r.randint(2016, 2026)


def main():
    comum.argumentos("Gera os cadastros da frota fictícia (iguais em qualquer --ate).")
    r = random.Random(comum.SEMENTE)
    print("Gerando frota fictícia...")

    # ---- centros de custo ----
    centros = []
    for regional, cidade in CENTROS:
        centros.append({
            "ID_Centro_Custo": len(centros) + 1,
            "Centro_Custo": f"CC {cidade}",
            "Cidade": cidade,
            "Regional": regional,
        })

    # ---- veículos ----
    tipos = [t for t, q in QTD_POR_TIPO.items() for _ in range(q)]
    r.shuffle(tipos)
    usadas = set()
    veiculos = []
    for i, tipo in enumerate(tipos, start=1):
        marca, modelo, (fipe_min, fipe_max) = r.choice(MODELOS[tipo])
        fab = gerar_ano_fabricacao(r)
        mod = min(fab + (1 if r.random() < 0.6 else 0), 2027)
        depreciacao = max(0.45, 1 - 0.06 * (2026 - fab))
        veiculos.append({
            "ID_Veiculo": i,
            "Placa": gerar_placa(r, usadas),
            "Marca": marca,
            "Modelo": modelo,
            "Cor": r.choice(CORES),
            "Tipo": tipo,
            "Ano_Fabricacao": fab,
            "Ano_Modelo": mod,
            "Blindagem": "Sim" if (tipo in ("Leve", "Pick-up") and r.random() < 0.06) else "Não",
            "Rastreador": "Sim",
            "Status_Veiculo": "Ativo",
            "Valor_FIPE": round(r.uniform(fipe_min, fipe_max) * depreciacao, 2),
        })

    # chassi e filial: semente própria por placa, para não mexer no resto do sorteio
    for v in veiculos:
        rc = comum.rng_de("cadastro_extra", v["Placa"])
        v["Chassi"] = "9" + "".join(rc.choice(LETRAS_CHASSI) for _ in range(16))
        v["Filial"] = rc.choices(FILIAIS, weights=PESOS_FILIAIS)[0]

    # ~5% sem rastreador (não aparecem na telemetria, de propósito)
    sem_rastreador = r.sample(veiculos, 6)
    for v in sem_rastreador:
        v["Rastreador"] = "Não"

    # ---- alocação (com troca de centro de custo para ~10%) ----
    alocacao = []
    trocam = set(v["Placa"] for v in r.sample(veiculos, 12))
    for v in veiculos:
        cc = r.choice(centros)
        contrato = r.choice(CONTRATOS) if r.random() < 0.75 else ""
        inicio = date(2024, 1, 1) + timedelta(days=r.randint(0, 820))  # até mar/2026
        base = {"ID_Veiculo": v["ID_Veiculo"], "Placa": v["Placa"], "Operacao": r.choice(OPERACOES)}
        if v["Placa"] in trocam:
            troca = date(2026, 6, 1) + timedelta(days=r.randint(0, 120))
            novo_cc = r.choice([c for c in centros if c["ID_Centro_Custo"] != cc["ID_Centro_Custo"]])
            alocacao.append({**base, "ID_Centro_Custo": cc["ID_Centro_Custo"], "Centro_Custo": cc["Centro_Custo"],
                             "Contrato": contrato, "Data_Inicio": inicio.isoformat(),
                             "Data_Fim": (troca - timedelta(days=1)).isoformat(), "Status_Alocacao": "Encerrada"})
            alocacao.append({**base, "ID_Centro_Custo": novo_cc["ID_Centro_Custo"], "Centro_Custo": novo_cc["Centro_Custo"],
                             "Contrato": r.choice(CONTRATOS), "Data_Inicio": troca.isoformat(),
                             "Data_Fim": "", "Status_Alocacao": "Vigente"})
        else:
            alocacao.append({**base, "ID_Centro_Custo": cc["ID_Centro_Custo"], "Centro_Custo": cc["Centro_Custo"],
                             "Contrato": contrato, "Data_Inicio": inicio.isoformat(),
                             "Data_Fim": "", "Status_Alocacao": "Vigente"})
    for i, a in enumerate(alocacao, start=1):
        a["ID_Alocacao"] = i

    # ---- motoristas ----
    motoristas = [{"ID_Motorista": i, "Motorista": f"Motorista {i:03d}"} for i in range(1, QTD_MOTORISTAS + 1)]

    # ---- perfis (gabarito) ----
    rastreados = [v for v in veiculos if v["Rastreador"] == "Sim"]
    agressivos = set(v["Placa"] for v in r.sample(rastreados, round(len(rastreados) * 0.15)))
    candidatos_ociosos = [v for v in rastreados if v["Placa"] not in agressivos and v["Tipo"] != "Moto"]
    ociosos = set(v["Placa"] for v in r.sample(candidatos_ociosos, 12))
    nomes = [m["Motorista"] for m in motoristas]
    perfis = []
    for v in veiculos:
        perfil = "agressivo" if v["Placa"] in agressivos else "ocioso" if v["Placa"] in ociosos else "normal"
        perfis.append({"Placa": v["Placa"], "Perfil": perfil, "Motorista_Principal": r.choice(nomes),
                       "Troca_Alocacao": "Sim" if v["Placa"] in trocam else "Não"})

    # ---- gravação ----
    comum.gravar_csv(comum.PASTA_FROTA / "veiculos.csv", veiculos, list(veiculos[0].keys()))
    comum.gravar_csv(comum.PASTA_FROTA / "centros_custo.csv", centros, list(centros[0].keys()))
    col_aloc = ["ID_Alocacao", "ID_Veiculo", "Placa", "ID_Centro_Custo", "Centro_Custo", "Contrato",
                "Operacao", "Data_Inicio", "Data_Fim", "Status_Alocacao"]
    comum.gravar_csv(comum.PASTA_FROTA / "alocacao.csv", alocacao, col_aloc)
    comum.gravar_csv(comum.PASTA_FROTA / "motoristas.csv", motoristas, list(motoristas[0].keys()))
    comum.gravar_csv(comum.PASTA_GABARITO / "perfis_veiculos.csv", perfis, list(perfis[0].keys()))

    print(f"  Veículos: {len(veiculos)} ({', '.join(f'{t}: {q}' for t, q in QTD_POR_TIPO.items())})")
    print(f"  Sem rastreador: {len(sem_rastreador)}")
    print(f"  Centros de custo: {len(centros)} | Alocações: {len(alocacao)} ({len(trocam)} veículos trocam de CC)")
    print(f"  Motoristas: {len(motoristas)}")
    print(f"  Perfis: {len(agressivos)} agressivos, {len(ociosos)} com motor muito ocioso")
    print(f"  Arquivos em: {comum.PASTA_FROTA}")


if __name__ == "__main__":
    main()
