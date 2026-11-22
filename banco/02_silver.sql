-- =========================================================
-- 02_SILVER.SQL — camada tratada (limpa, tipada, sem duplicata)
-- =========================================================
-- Projeto: brn-frota-data-platform (dados 100% fictícios)
--
-- Quem escreve aqui é o pipeline Python, a partir da bronze:
--   * números e datas no padrão BR viram NUMERIC / DATE / TIMESTAMP;
--   * cada registro tem a CHAVE NATURAL como chave primária
--     (alerta = placa + regra + data/hora; viagem = placa + início + fim;
--      OS = Controle Interno) -> upsert com ON CONFLICT DO UPDATE;
--   * o que não passa nas regras vai para outliers (revisão manual)
--     ou quarentena, nunca é descartado em silêncio.
--
-- Pode rodar quantas vezes quiser: só cria o que ainda não existe.
-- =========================================================

CREATE SCHEMA IF NOT EXISTS silver;
COMMENT ON SCHEMA silver IS 'Camada tratada: tipos corretos, chave natural, sem duplicatas.';

-- ---------------------------------------------------------
-- Controle de processamento: quais lotes da bronze já viraram silver
-- (permite processar só o que chegou de novo)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.lote_processado (
    id_lote        BIGINT PRIMARY KEY REFERENCES bronze.lote_carga (id_lote) ON DELETE CASCADE,
    processado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------
-- Cadastros
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.centros_custo (
    id_centro_custo  INTEGER PRIMARY KEY,
    centro_custo     TEXT NOT NULL UNIQUE,
    cidade           TEXT NOT NULL,
    regional         TEXT NOT NULL,
    id_lote          BIGINT REFERENCES bronze.lote_carga (id_lote),
    atualizado_em    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS silver.veiculos (
    id_veiculo         INTEGER PRIMARY KEY,
    placa              VARCHAR(7) NOT NULL UNIQUE,
    marca              TEXT NOT NULL,
    modelo             TEXT NOT NULL,
    cor                TEXT,
    tipo               TEXT NOT NULL,
    ano_fabricacao     SMALLINT,
    ano_modelo         SMALLINT,
    blindagem          BOOLEAN NOT NULL,
    possui_rastreador  BOOLEAN NOT NULL,
    status_veiculo     TEXT NOT NULL,
    valor_fipe         NUMERIC(12, 2),
    chassi             VARCHAR(17),
    filial             TEXT,
    id_lote            BIGINT REFERENCES bronze.lote_carga (id_lote),
    atualizado_em      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS silver.alocacao (
    id_alocacao      INTEGER PRIMARY KEY,
    id_veiculo       INTEGER NOT NULL,
    placa            VARCHAR(7) NOT NULL,
    id_centro_custo  INTEGER NOT NULL,
    contrato         TEXT,
    operacao         TEXT,
    data_inicio      DATE NOT NULL,
    data_fim         DATE,
    status_alocacao  TEXT,
    id_lote          BIGINT REFERENCES bronze.lote_carga (id_lote),
    atualizado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_silver_alocacao_periodo CHECK (data_fim IS NULL OR data_fim >= data_inicio)
);

CREATE TABLE IF NOT EXISTS silver.motoristas (
    id_motorista   INTEGER PRIMARY KEY,
    motorista      TEXT NOT NULL UNIQUE,
    id_lote        BIGINT REFERENCES bronze.lote_carga (id_lote),
    atualizado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------
-- Telemetria
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.alertas (
    id_evento         CHAR(32) PRIMARY KEY,          -- hash de placa|regra|data_hora (chave natural)
    placa             VARCHAR(7) NOT NULL,
    modelo            TEXT,
    motorista         TEXT,                          -- vazio vira NULL ("Indefinido" na gold)
    nome_regra        TEXT NOT NULL,
    data_hora_evento  TIMESTAMP NOT NULL,
    duracao_min       NUMERIC(10, 2),
    valor_metrica     NUMERIC(10, 2),
    unidade_metrica   TEXT,
    odometro_inicial  NUMERIC(12, 2),
    odometro_final    NUMERIC(12, 2),
    distancia_km      NUMERIC(12, 2),
    local_inicio      TEXT,
    local_fim         TEXT,
    modo_violacao     TEXT,
    grupo_unidades    TEXT,
    arquivo_origem    TEXT,
    id_lote           BIGINT REFERENCES bronze.lote_carga (id_lote),
    atualizado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_silver_alertas_chave UNIQUE (placa, nome_regra, data_hora_evento)
);

CREATE TABLE IF NOT EXISTS silver.viagens (
    id_viagem            CHAR(32) PRIMARY KEY,       -- hash de placa|data_inicial|data_final
    placa                VARCHAR(7) NOT NULL,
    modelo               TEXT,
    motorista            TEXT,
    data_inicial         TIMESTAMP NOT NULL,
    data_final           TIMESTAMP NOT NULL,
    distancia_km         NUMERIC(12, 2),
    duracao_min          NUMERIC(10, 2),
    motor_ocioso_min     NUMERIC(10, 2),
    consumo_l            NUMERIC(10, 2),
    eficiencia_km_l      NUMERIC(10, 2),
    vel_maxima           NUMERIC(6, 1),
    vel_media_movimento  NUMERIC(6, 1),
    qtd_frenagem         INTEGER,
    tempo_frenagem_min   NUMERIC(10, 2),
    endereco_inicial     TEXT,
    endereco_final       TEXT,
    grupo_unidades       TEXT,
    arquivo_origem       TEXT,
    id_lote              BIGINT REFERENCES bronze.lote_carga (id_lote),
    atualizado_em        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_silver_viagens_chave UNIQUE (placa, data_inicial, data_final)
);

-- Suspeitos da telemetria: ficam fora da gold até alguém revisar
CREATE TABLE IF NOT EXISTS silver.outliers_telemetria (
    id_registro    CHAR(32) PRIMARY KEY,             -- id_viagem ou id_evento
    tipo_registro  TEXT NOT NULL CHECK (tipo_registro IN ('viagem', 'alerta')),
    placa          VARCHAR(7) NOT NULL,
    motivo         TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'Pendente' CHECK (status IN ('Pendente', 'Aprovado', 'Rejeitado')),
    dados          JSONB NOT NULL,                    -- registro completo, para reinjetar se for aprovado
    detectado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    revisado_em    TIMESTAMPTZ
);
COMMENT ON TABLE silver.outliers_telemetria IS
    'Viagens e alertas fisicamente impossíveis. Aprovado entra na gold; Rejeitado fica fora para sempre; Pendente aguarda revisão.';

-- ---------------------------------------------------------
-- Manutenção
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.os_manutencao (
    numero_os                   TEXT PRIMARY KEY,    -- Controle de Pedido Interno (BRN-26-0001)
    placa                       VARCHAR(7) NOT NULL,
    modelo                      TEXT,
    centro_custo                TEXT,
    contrato                    TEXT,
    oficina                     TEXT,
    data_os                     DATE NOT NULL,       -- abertura da OS
    data_entrada_oficina        DATE,                -- vazia = ainda em agendamento
    data_prevista_saida         DATE,
    data_real_saida             DATE,
    data_orcamento              DATE,
    data_solicitacao_aprovacao  DATE,
    data_aprovacao              DATE,
    data_pedido_compra          DATE,
    data_compra_efetivada       DATE,
    data_entrega_peca           DATE,
    data_pagamento_oficina      DATE,
    tipo_manutencao             TEXT,
    criticidade                 TEXT,
    valor_orcamento             NUMERIC(12, 2),
    valor_negociado             NUMERIC(12, 2),
    n_requisicao_pecas          TEXT,                -- padronizado: REQ-26-0031
    valor_pecas                 NUMERIC(12, 2),
    km_atual                    INTEGER,
    status_operacional          TEXT,
    veiculo_substituto          BOOLEAN,
    placa_substituto            VARCHAR(7),
    tipo_aluguel                TEXT,
    valor_aluguel               NUMERIC(12, 2),
    solicitante                 TEXT,
    tipo_sistema                TEXT,
    descricao_problema          TEXT,
    status_manutencao           TEXT,
    responsavel_aprovacao       TEXT,
    observacoes_gerais          TEXT,
    id_lote                     BIGINT REFERENCES bronze.lote_carga (id_lote),
    atualizado_em               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- OS que não podem entrar no modelo (ex.: placa que não existe na frota)
CREATE TABLE IF NOT EXISTS silver.quarentena_manutencao (
    numero_os     TEXT   NOT NULL,
    id_lote       BIGINT NOT NULL REFERENCES bronze.lote_carga (id_lote),
    placa         TEXT,
    motivo        TEXT   NOT NULL,
    dados         JSONB  NOT NULL,
    detectado_em  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (numero_os, id_lote)
);
COMMENT ON TABLE silver.quarentena_manutencao IS 'OS barradas na carga, com o motivo. Conferência manual.';

-- ---------------------------------------------------------
-- Segurança: RLS ligado em todas as tabelas da camada.
-- Sem política, nada é lido pela API pública; o pipeline conecta
-- como dono das tabelas e não é afetado. (Idempotente.)
-- ---------------------------------------------------------
DO $$
DECLARE t RECORD;
BEGIN
    FOR t IN SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'silver' LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.schemaname, t.tablename);
    END LOOP;
END $$;
