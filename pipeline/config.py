"""
=========================================================
CONFIG.PY — caminhos, regras de negócio e conexão com o banco
=========================================================
A conexão vem do arquivo .env na raiz do projeto (nunca vai para o git):

    SUPABASE_DB_URL=postgresql://usuario:senha@host:5432/postgres

Nada de caminho fixo: tudo é relativo à raiz do projeto.
=========================================================
"""

import os
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = RAIZ / "entrada"
SAIDA = RAIZ / "saida"
PASTA_LOGS = SAIDA / "logs"
ARQUIVO_REVISAO_OUTLIERS = SAIDA / "outliers_para_revisao.xlsx"
PASTA_DOCS = RAIZ / "docs"                    # vai para o git: resumos e status da última execução
PASTA_RESUMOS = PASTA_DOCS / "resumos"
ARQUIVO_STATUS = PASTA_DOCS / "status_pipeline.md"

load_dotenv(RAIZ / ".env")

# ---------------------------------------------------------
# Regras de negócio (vindas do pipeline real)
# ---------------------------------------------------------
OCIOSO_MINIMO_MIN = 5            # motor ocioso só conta a partir de 5 minutos
VELOCIDADE_CONFIAVEL_KMH = 150   # >= 150 km/h só vale se o odômetro confirmar
VELOCIDADE_IMPLICITA_MAX = 200   # viagem com média acima disso é fisicamente impossível
EFICIENCIA_MAX_KM_L = 100        # nenhum veículo da frota faz mais que isso
RETENCAO_BRONZE_DIAS = 90        # linhas brutas de lotes tratados mais antigos que isso são apagadas

PADRAO_PLACA = r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$"   # antigo AAA9999 ou Mercosul AAA9A99


TENTATIVAS_CONEXAO = 4               # o Supabase gratuito às vezes recusa ou derruba a conexão
ESPERA_ENTRE_TENTATIVAS_S = (0, 15, 45, 90)


def conectar() -> psycopg.Connection:
    """Conecta no banco, tentando de novo se a conexão falhar (até 4 vezes, com espera crescente)."""
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        raise SystemExit(
            "SUPABASE_DB_URL não encontrada. Copie o .env.exemplo para .env "
            "e preencha a connection string do Supabase (Session pooler)."
        )
    ultimo_erro = None
    for tentativa, espera in enumerate(ESPERA_ENTRE_TENTATIVAS_S[:TENTATIVAS_CONEXAO], start=1):
        if espera:
            time.sleep(espera)
        try:
            # keepalives: evita que consultas longas percam a conexão por inatividade no pooler
            return psycopg.connect(url, connect_timeout=20, application_name="brn-frota-pipeline",
                                   keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5)
        except psycopg.OperationalError as e:
            ultimo_erro = e
            print(f"[conexão] tentativa {tentativa} de {TENTATIVAS_CONEXAO} falhou: {str(e).splitlines()[0]}")
    raise SystemExit(f"Não foi possível conectar ao banco depois de {TENTATIVAS_CONEXAO} tentativas: {ultimo_erro}\n"
                     "Se o projeto do Supabase estiver pausado, reative em Project > Resume project.")
