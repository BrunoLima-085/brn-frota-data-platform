"""
=========================================================
TRATAR_TELEMETRIA.PY — alertas e viagens (BDV): bronze -> silver
=========================================================
O coração do ETL da telemetria (evolução do construir_fato v5 do
pipeline real). Para cada lote novo da bronze:

  1. descarta rodapés (TOTAL, SOMATÓRIO, MÉDIA, RESULTADOS);
  2. separa "PLACA - MODELO", converte números BR e hh:mm:ss;
  3. extrai a métrica de "[Velocidade: 80,0 | 120,5 | 100,2]";
  4. gera o id pela CHAVE NATURAL
        alerta = placa + regra + data/hora
        viagem = placa + início + fim
     — o bug real: o hash de TODAS as colunas mudava quando um alerta
       aberto era fechado no export seguinte, e o mesmo evento entrava
       de novo (+13,7% de linhas na fato real);
  5. junta as versões do mesmo registro (repetido no arquivo ou em
     arquivos com período sobreposto) ficando com a mais completa;
  6. separa os suspeitos (outliers) para revisão manual;
  7. faz upsert na silver: o que veio vazio antes é completado
     (COALESCE), nada duplica.

Uso (na raiz do projeto):  py -m pipeline.telemetria.tratar_telemetria
=========================================================
"""

import re
from collections import defaultdict

from pipeline import config, utils
from pipeline.telemetria import outliers

REGEX_RODAPE = re.compile(r"TOTAL|SOMAT[ÓO]RIO|M[ÉE]DIA|RESULTADOS", re.IGNORECASE)
REGEX_TELEMETRIA = re.compile(
    r"\[([A-Za-zÀ-ú ]+):\s*([-\d,\.]+)\s*\|\s*([-\d,\.]+)\s*\|\s*([-\d,\.]+)\s*\]")

COLUNAS_ALERTAS = [
    "id_evento", "placa", "modelo", "motorista", "nome_regra", "data_hora_evento", "duracao_min",
    "valor_metrica", "unidade_metrica", "odometro_inicial", "odometro_final", "distancia_km",
    "local_inicio", "local_fim", "modo_violacao", "grupo_unidades", "arquivo_origem", "id_lote",
]
COLUNAS_VIAGENS = [
    "id_viagem", "placa", "modelo", "motorista", "data_inicial", "data_final", "distancia_km",
    "duracao_min", "motor_ocioso_min", "consumo_l", "eficiencia_km_l", "vel_maxima", "vel_media_movimento",
    "qtd_frenagem", "tempo_frenagem_min", "endereco_inicial", "endereco_final", "grupo_unidades",
    "arquivo_origem", "id_lote",
]
FORMATO_DH = "%Y-%m-%d %H:%M:%S"


def separar_veiculo(valor):
    """'ABC1D23 - VW Gol 1.0 Branco 22/23' -> ('ABC1D23', 'VW Gol 1.0 Branco 22/23')"""
    t = utils.texto(valor) or ""
    placa, _, modelo = t.partition(" - ")
    return placa.strip().upper().replace("-", ""), (modelo.strip() or None)


def extrair_telemetria(valor):
    m = REGEX_TELEMETRIA.search(valor or "")
    if not m:
        return None, None, None
    metrica, _minimo, maximo, media = m.groups()
    return utils.numero(media), metrica.strip().lower(), utils.numero(maximo)


# ---------------------------------------------------------
# Leitura e conversão
# ---------------------------------------------------------
def ler_alertas(cur, lotes: list, cont: dict) -> list:
    cur.execute("""
        SELECT b.id_lote, b.linha_arquivo, l.arquivo, b.unidade_rastreada, b.motorista, b.telemetrias,
               b.nome_regra, b.data_ocorrencia, b.hora_ocorrencia, b.duracao, b.odometro_inicial,
               b.odometro_final, b.distancia, b.local_inicio, b.local_fim, b.modo_violacao, b.grupo_unidades
        FROM bronze.telemetria_alertas b JOIN bronze.lote_carga l USING (id_lote)
        WHERE b.id_lote = ANY(%s)
        ORDER BY b.id_lote, b.linha_arquivo
    """, (lotes,))
    registros = []
    for (lote, linha, arquivo, unidade, motorista, telem, regra, dia, hora, dur, odo_i, odo_f,
         dist, loc_i, loc_f, modo, grupo) in cur:
        cont["linhas_bronze"] += 1
        placa, modelo = separar_veiculo(unidade)
        if REGEX_RODAPE.search(placa or ""):
            cont["rodape_descartado"] += 1
            continue
        quando = utils.data_hora(f"{utils.texto(dia) or ''} {utils.texto(hora) or ''}")
        if not re.fullmatch(config.PADRAO_PLACA, placa) or not quando or not utils.texto(regra):
            cont["invalidas_descartadas"] += 1
            continue
        valor, unidade_metrica, vel_max = extrair_telemetria(telem)
        regra = utils.texto(regra)
        registros.append({
            "id_evento": utils.gerar_id(placa, regra, quando.strftime(FORMATO_DH)),
            "placa": placa, "modelo": modelo, "motorista": utils.texto(motorista), "nome_regra": regra,
            "data_hora_evento": quando, "duracao_min": utils.minutos(dur), "valor_metrica": valor,
            "unidade_metrica": unidade_metrica, "odometro_inicial": utils.numero(odo_i),
            "odometro_final": utils.numero(odo_f), "distancia_km": utils.numero(dist),
            "local_inicio": utils.texto(loc_i), "local_fim": utils.texto(loc_f),
            "modo_violacao": utils.texto(modo), "grupo_unidades": utils.texto(grupo),
            "arquivo_origem": arquivo, "id_lote": lote, "_vel_max": vel_max,
        })
    return registros


def ler_viagens(cur, lotes: list, cont: dict) -> list:
    cur.execute("""
        SELECT b.id_lote, b.linha_arquivo, l.arquivo, b.unidade_rastreada, b.motorista, b.data_inicial,
               b.data_final, b.distancia_odo, b.duracao_dt, b.motor_ocioso, b.consumo_l, b.eficiencia_km_l,
               b.vel_maxima, b.vel_media_movimento, b.quantidade_frenagem, b.tempo_frenagem,
               b.endereco_inicial, b.endereco_final, b.grupo_unidades
        FROM bronze.telemetria_bdv b JOIN bronze.lote_carga l USING (id_lote)
        WHERE b.id_lote = ANY(%s)
        ORDER BY b.id_lote, b.linha_arquivo
    """, (lotes,))
    registros = []
    for (lote, linha, arquivo, unidade, motorista, ini, fim, dist, dur, ocioso, cons, efic,
         vmax, vmed, qfren, tfren, end_i, end_f, grupo) in cur:
        cont["linhas_bronze"] += 1
        placa, modelo = separar_veiculo(unidade)
        if REGEX_RODAPE.search(placa or ""):
            cont["rodape_descartado"] += 1
            continue
        inicio, final = utils.data_hora(ini), utils.data_hora(fim)
        if not re.fullmatch(config.PADRAO_PLACA, placa) or not inicio or not final:
            cont["invalidas_descartadas"] += 1
            continue
        registros.append({
            "id_viagem": utils.gerar_id(placa, inicio.strftime(FORMATO_DH), final.strftime(FORMATO_DH)),
            "placa": placa, "modelo": modelo, "motorista": utils.texto(motorista),
            "data_inicial": inicio, "data_final": final, "distancia_km": utils.numero(dist),
            "duracao_min": utils.minutos(dur), "motor_ocioso_min": utils.minutos(ocioso),
            "consumo_l": utils.numero(cons), "eficiencia_km_l": utils.numero(efic),
            "vel_maxima": utils.numero(vmax), "vel_media_movimento": utils.numero(vmed),
            "qtd_frenagem": utils.inteiro(qfren), "tempo_frenagem_min": utils.minutos(tfren),
            "endereco_inicial": utils.texto(end_i), "endereco_final": utils.texto(end_f),
            "grupo_unidades": utils.texto(grupo), "arquivo_origem": arquivo, "id_lote": lote,
        })
    return registros


# ---------------------------------------------------------
# Consolidação das versões de um mesmo registro
# ---------------------------------------------------------
def consolidar(registros: list, chave: str, cont: dict, campo_aberto: str = None) -> list:
    """
    Junta as versões do mesmo id (já em ordem de chegada):
    a mais recente vale, e o que ela trouxer vazio é completado pelas anteriores.
    """
    grupos = defaultdict(list)
    for r in registros:
        grupos[r[chave]].append(r)

    consolidados = []
    for versoes in grupos.values():
        lotes = [v["id_lote"] for v in versoes]
        repetidas_no_arquivo = len(lotes) - len(set(lotes))
        cont["repetida_no_mesmo_arquivo"] += repetidas_no_arquivo
        if len(set(lotes)) > 1:
            cont["em_mais_de_um_arquivo"] += 1

        final = dict(versoes[-1])
        for anterior in reversed(versoes[:-1]):
            for campo, valor in anterior.items():
                if final.get(campo) is None and valor is not None:
                    final[campo] = valor

        if campo_aberto and any(v[campo_aberto] is None for v in versoes) and final[campo_aberto] is not None:
            cont["em_aberto_depois_completado"] += 1
        if any(v["motorista"] is None for v in versoes) and final["motorista"] is not None:
            cont["motorista_vazio_depois_preenchido"] += 1
        consolidados.append(final)
    return consolidados


def separar_suspeitos(registros: list, tipo: str, chave: str, regra, status: dict, cont: dict):
    """Limpos + aprovados seguem; suspeitos novos/pendentes vão para revisão; rejeitados saem."""
    seguem, suspeitos = [], []
    for r in registros:
        motivo = regra(r)
        if not motivo:
            seguem.append(r)
            continue
        cont[f"outlier: {motivo.split(' (')[0]}"] += 1
        situacao = status.get(r[chave], "Pendente")
        if situacao == "Aprovado":
            seguem.append(r)
        elif situacao == "Pendente":
            dados = {k: v for k, v in r.items() if not k.startswith("_")}
            suspeitos.append((tipo, r[chave], r["placa"], motivo, dados))
    return seguem, suspeitos


def _linhas(registros: list, colunas: list) -> list:
    return [[r.get(c) for c in colunas] for r in registros]


# ---------------------------------------------------------
# Execução
# ---------------------------------------------------------
def tratar() -> dict:
    utils.titulo("SILVER — telemetria (alertas e viagens)")
    resumo = {}
    with config.conectar() as con, con.transaction(), con.cursor() as cur:
        decisoes = outliers.aplicar_decisoes_da_planilha(cur)
        if any(decisoes.values()):
            utils.log().info(f"Decisões da planilha de revisão aplicadas: {decisoes}")
        removidos = outliers.remover_rejeitados_da_silver(cur)
        if removidos:
            utils.log().info(f"Registros rejeitados retirados da silver: {removidos}")
        status = outliers.status_atuais(cur)

        etapas = [
            ("alertas", "telemetria_alertas", ler_alertas, "id_evento", "duracao_min", "alerta",
             outliers.motivo_alerta, "silver.alertas", COLUNAS_ALERTAS),
            ("viagens", "telemetria_bdv", ler_viagens, "id_viagem", None, "viagem",
             outliers.motivo_viagem, "silver.viagens", COLUNAS_VIAGENS),
        ]
        for nome, fonte, leitor, chave, campo_aberto, tipo, regra, tabela, colunas in etapas:
            cont = defaultdict(int)
            lotes = [l[0] for l in utils.lotes_pendentes(cur, fonte)]
            if lotes:
                registros = leitor(cur, lotes, cont)
                consolidados = consolidar(registros, chave, cont, campo_aberto)
                cont["registros_unicos"] = len(consolidados)
                if nome == "alertas":
                    cont["velocidade_150_confirmada_pelo_odometro"] = sum(
                        1 for r in consolidados if r["nome_regra"] == "Excesso de velocidade"
                        and (r["_vel_max"] or 0) >= config.VELOCIDADE_CONFIAVEL_KMH and not regra(r))
                seguem, suspeitos = separar_suspeitos(consolidados, tipo, chave, regra, status, cont)
                cont["outliers_novos_para_revisao"] = outliers.registrar(cur, suspeitos)
            else:
                seguem = []
            # aprovados em revisões anteriores que ainda não estão na silver
            reinjetar = outliers.aprovados_fora_da_silver(cur, tipo)
            if reinjetar:
                cont["aprovados_reinjetados"] = len(reinjetar)
                ids = {r[chave] for r in seguem}
                seguem += [d for d in reinjetar if d[chave] not in ids]
            novos, atualizados = utils.upsert(cur, tabela, colunas, _linhas(seguem, colunas), [chave],
                                              modo="completar")
            cont["silver_novos"], cont["silver_atualizados"] = novos, atualizados
            utils.marcar_processados(cur, lotes)
            resumo[nome] = dict(cont)
            utils.log().info(f"[{nome}] {len(lotes)} lote(s) novo(s)")
            for k, v in cont.items():
                utils.log().info(f"    {k}: {utils.mil(v)}")

        total, salvou = outliers.exportar_planilha(cur)
        if salvou:
            utils.log().info(f"Planilha de revisão: {config.ARQUIVO_REVISAO_OUTLIERS.name} ({total} registro(s))")
    return resumo


if __name__ == "__main__":
    tratar()
