"""
Testes unitários das regras de tratamento (não precisam de banco).

Uso (na raiz do projeto):  py -m pytest
"""

from collections import defaultdict
from datetime import date, datetime

import pytest

from pipeline import utils
from pipeline.manutencao.tratar_manutencao import DOMINIOS, grafia_mais_comum, padronizar, padronizar_requisicao
from pipeline.telemetria import outliers
from pipeline.telemetria.tratar_telemetria import consolidar, extrair_telemetria, separar_veiculo


# ---------------------------------------------------------
# Conversões do padrão brasileiro
# ---------------------------------------------------------
@pytest.mark.parametrize("entrada, esperado", [
    ("1.250,00", 1250.0), ("R$ 1.977,05", 1977.05), ("1193.73", 1193.73), (1250, 1250.0),
    ("-12,50", -12.5), ("300.005,12", 300005.12), ("", None), (None, None), ("abc", None),
])
def test_numero(entrada, esperado):
    assert utils.numero(entrada) == esperado


@pytest.mark.parametrize("entrada, esperado", [
    (85320, 85320), ("85.320", 85320), ("85320 km", 85320), ("163.788", 163788), (85320.0, 85320), (None, None),
])
def test_km_misturado(entrada, esperado):
    assert utils.so_digitos(entrada) == esperado


@pytest.mark.parametrize("entrada, esperado", [
    ("01:15:30", 75.5), ("00:00:03", 0.05), ("03:00:00", 180.0), ("", None), (None, None),
])
def test_minutos(entrada, esperado):
    assert utils.minutos(entrada) == esperado


@pytest.mark.parametrize("entrada, esperado", [
    ("15/08/2026", datetime(2026, 8, 15)),
    ("15/08/2026 07:26:09", datetime(2026, 8, 15, 7, 26, 9)),
    ("2026-08-15 00:00:00", datetime(2026, 8, 15)),
    (datetime(2026, 8, 15), datetime(2026, 8, 15)),
    (date(2026, 8, 15), datetime(2026, 8, 15)),
    ("46249", datetime(2026, 8, 15)),            # serial do Excel gravado como texto
    ("32/13/2026", None),
])
def test_data_hora(entrada, esperado):
    assert utils.data_hora(entrada) == esperado


def test_texto_tira_espacos_extras():
    assert utils.texto("  CC  Oeste   02 ") == "CC Oeste 02"
    assert utils.texto("   ") is None


# ---------------------------------------------------------
# Chave natural
# ---------------------------------------------------------
def test_id_depende_so_da_chave_natural():
    """O bug real: o hash de todas as colunas mudava quando o alerta era fechado."""
    chave = ("ABC1D23", "Excesso de velocidade", "2026-05-01 08:15:30")
    assert utils.gerar_id(*chave) == utils.gerar_id(*chave)
    assert len(utils.gerar_id(*chave)) == 32
    assert utils.gerar_id(*chave) != utils.gerar_id("ABC1D23", "Freada brusca", "2026-05-01 08:15:30")


def test_separar_veiculo():
    assert separar_veiculo("ABC1D23 - VW Gol 1.0 Branco 22/23") == ("ABC1D23", "VW Gol 1.0 Branco 22/23")
    assert separar_veiculo("TOTAL")[0] == "TOTAL"


def test_extrair_telemetria():
    assert extrair_telemetria("[Velocidade: 82,0 | 118,5 | 101,2]") == (101.2, "velocidade", 118.5)
    assert extrair_telemetria("sem métrica") == (None, None, None)


# ---------------------------------------------------------
# Consolidação de versões do mesmo registro
# ---------------------------------------------------------
def test_alerta_em_aberto_fica_com_a_versao_completa():
    aberto = {"id_evento": "x", "id_lote": 1, "motorista": None, "duracao_min": None, "odometro_final": None}
    fechado = {"id_evento": "x", "id_lote": 2, "motorista": "Motorista 001", "duracao_min": 1.5, "odometro_final": 10.0}
    cont = defaultdict(int)
    [final] = consolidar([aberto, fechado], "id_evento", cont, campo_aberto="duracao_min")
    assert final["duracao_min"] == 1.5 and final["motorista"] == "Motorista 001"
    assert cont["em_mais_de_um_arquivo"] == 1
    assert cont["em_aberto_depois_completado"] == 1
    assert cont["motorista_vazio_depois_preenchido"] == 1


def test_linha_repetida_no_mesmo_arquivo_vira_uma():
    linha = {"id_viagem": "y", "id_lote": 7, "motorista": "Motorista 002"}
    cont = defaultdict(int)
    assert len(consolidar([linha, dict(linha)], "id_viagem", cont)) == 1
    assert cont["repetida_no_mesmo_arquivo"] == 1


# ---------------------------------------------------------
# Outliers
# ---------------------------------------------------------
def _viagem(**kw):
    base = {"distancia_km": 20.0, "duracao_min": 30.0, "consumo_l": 2.0, "eficiencia_km_l": 10.0}
    return {**base, **kw}


def test_viagem_normal_nao_e_outlier():
    assert outliers.motivo_viagem(_viagem()) is None


@pytest.mark.parametrize("campos, motivo", [
    ({"distancia_km": -5.0}, "Distância negativa"),
    ({"distancia_km": 300000.0, "duracao_min": 180.0}, "Velocidade implícita"),
    ({"eficiencia_km_l": 150.0}, "Eficiência acima"),
])
def test_viagem_impossivel(campos, motivo):
    assert outliers.motivo_viagem(_viagem(**campos)).startswith(motivo)


def test_velocidade_150_so_vale_com_odometro():
    base = {"nome_regra": "Excesso de velocidade", "_vel_max": 160.0, "odometro_inicial": 100.0}
    assert outliers.motivo_alerta({**base, "odometro_final": 100.0}) is not None   # sem variação: erro
    assert outliers.motivo_alerta({**base, "odometro_final": 101.2}) is None       # confirmado: mantém


# ---------------------------------------------------------
# Padronização de texto da manutenção
# ---------------------------------------------------------
def test_padronizar_contra_a_lista():
    validos = ["Preventiva", "Corretiva", "Preditiva"]
    assert padronizar("  CORRETIVA ", validos) == ("Corretiva", True)
    assert padronizar("corretiva", validos) == ("Corretiva", True)
    assert padronizar("Emergencial", validos) == ("Emergencial", False)


def test_grafia_mais_comum():
    mapa = grafia_mais_comum(["Oficina Alfa", "Oficina Alfa", "oficina alfa ", "OFICINA  ALFA"])
    assert mapa["oficina alfa"] == "Oficina Alfa"


# ---------------------------------------------------------
# Planilha de manutenção: listas sem acento e nº da requisição
# ---------------------------------------------------------

@pytest.mark.parametrize("bruto, campo, esperado", [
    ("Aguardando pecas", "status_manutencao", "Aguardando peças"),
    (" Em diagnostico ", "status_manutencao", "Em diagnóstico"),
    ("Concluida", "status_manutencao", "Concluída"),
    ("Media", "criticidade", "Média"),
    ("Restricao", "status_operacional", "Restrição"),
    ("ELETRICA", "tipo_sistema", "Elétrica"),
    ("suspencao  ", "tipo_sistema", "Suspensão"),
    ("Diaria", "tipo_aluguel", "Diária"),
])
def test_padroniza_lista_sem_acento(bruto, campo, esperado):
    assert padronizar(bruto, DOMINIOS[campo]) == (esperado, True)


def test_valor_fora_da_lista_e_sinalizado():
    assert padronizar("Funilaria", DOMINIOS["tipo_sistema"]) == ("Funilaria", False)


@pytest.mark.parametrize("bruto, esperado", [
    ("REQ-26-0031", "REQ-26-0031"),
    ("req 26 0031", "REQ-26-0031"),
    ("REQ260031", "REQ-26-0031"),
    (" Req-26-31", "REQ-26-0031"),
    ("REQ 26/0031", "REQ-26-0031"),
    (None, None),
    ("sem requisição", "sem requisição"),
])
def test_padroniza_requisicao(bruto, esperado):
    assert padronizar_requisicao(bruto) == esperado


# ---------------------------------------------------------
# Hash do conteúdo: mesmo dado, bytes diferentes -> mesmo hash
# ---------------------------------------------------------
def test_hash_xlsx_ignora_metadados_e_bytes(tmp_path):
    from openpyxl import Workbook
    def salvar(nome, autor):
        wb = Workbook()
        wb.properties.creator = autor
        wb.active.append(["Placa", "Km", "Data"])
        wb.active.append(["ABC1D23", 10.5, datetime(2026, 11, 1, 8, 30)])
        caminho = tmp_path / nome
        wb.save(caminho)
        return caminho
    a, b = salvar("a.xlsx", "Windows"), salvar("b.xlsx", "Linux")
    assert a.read_bytes() != b.read_bytes()
    assert utils.hash_arquivo(a) == utils.hash_arquivo(b)


def test_hash_xlsx_muda_quando_o_dado_muda(tmp_path):
    from openpyxl import Workbook
    caminhos = []
    for km in (10.5, 10.6):
        wb = Workbook()
        wb.active.append(["ABC1D23", km])
        caminhos.append(tmp_path / f"{km}.xlsx")
        wb.save(caminhos[-1])
    assert utils.hash_arquivo(caminhos[0]) != utils.hash_arquivo(caminhos[1])


def test_hash_csv_ignora_quebra_de_linha_e_bom(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_bytes("﻿Placa,Km\nABC1D23,10\n".encode("utf-8"))
    b.write_bytes("Placa,Km\r\nABC1D23,10\r\n".encode("utf-8"))
    assert utils.hash_arquivo(a) == utils.hash_arquivo(b)
