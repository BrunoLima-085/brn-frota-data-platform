-- =========================================================
-- 03_GOLD.SQL — modelo dimensional (esquema estrela)
-- =========================================================
-- Projeto: brn-frota-data-platform (dados 100% fictícios)
--
-- A gold é montada em SQL a partir da silver (scripts de carga nas
-- próximas fases). Aqui ficam as regras que o BANCO garante sozinho:
--   * chaves primárias e estrangeiras de verdade;
--   * CHECKs de domínio (distância e consumo >= 0, tipo de manutenção...);
--   * um veículo não pode ter duas alocações ao mesmo tempo (EXCLUDE);
--   * colunas calculadas (GENERATED) na fato de manutenção:
--     % de variação, etapa atual e dias gastos em cada etapa do fluxo.
--
-- Pode rodar quantas vezes quiser: só cria o que ainda não existe.
-- =========================================================

CREATE SCHEMA IF NOT EXISTS gold;
COMMENT ON SCHEMA gold IS 'Modelo estrela consumido pelo dashboard (dimensões + fatos + views).';

-- btree_gist: permite a restrição EXCLUDE (período de alocação sem sobreposição)
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA extensions;

-- =========================================================
-- DIMENSÕES
-- =========================================================
CREATE TABLE IF NOT EXISTS gold.dim_data (
    data           DATE PRIMARY KEY,
    ano            SMALLINT NOT NULL,
    mes            SMALLINT NOT NULL,
    nome_mes       TEXT     NOT NULL,
    ano_mes        CHAR(7)  NOT NULL,          -- '2026-05'
    trimestre      SMALLINT NOT NULL,
    semana_iso     SMALLINT NOT NULL,
    dia_semana     SMALLINT NOT NULL,          -- 1 = segunda ... 7 = domingo (ISO)
    nome_dia       TEXT     NOT NULL,
    fim_de_semana  BOOLEAN  NOT NULL,
    feriado        BOOLEAN  NOT NULL
);

-- Calendário 2024–2027 gerado no próprio banco (feriados nacionais de data fixa)
INSERT INTO gold.dim_data
SELECT
    d::date,
    EXTRACT(YEAR FROM d)::smallint,
    EXTRACT(MONTH FROM d)::smallint,
    (ARRAY['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho',
           'Agosto','Setembro','Outubro','Novembro','Dezembro'])[EXTRACT(MONTH FROM d)::int],
    to_char(d, 'YYYY-MM'),
    EXTRACT(QUARTER FROM d)::smallint,
    EXTRACT(WEEK FROM d)::smallint,
    EXTRACT(ISODOW FROM d)::smallint,
    (ARRAY['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo'])[EXTRACT(ISODOW FROM d)::int],
    EXTRACT(ISODOW FROM d) IN (6, 7),
    to_char(d, 'MM-DD') IN ('01-01','04-21','05-01','09-07','10-12','11-02','11-15','11-20','12-25')
FROM generate_series(DATE '2024-01-01', DATE '2027-12-31', INTERVAL '1 day') AS g(d)
ON CONFLICT (data) DO NOTHING;

CREATE TABLE IF NOT EXISTS gold.dim_centro_custo (
    id_centro_custo  INTEGER PRIMARY KEY,
    centro_custo     TEXT NOT NULL UNIQUE,
    cidade           TEXT NOT NULL,
    regional         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.dim_veiculo (
    id_veiculo         INTEGER PRIMARY KEY,
    placa              VARCHAR(7) NOT NULL UNIQUE,
    marca              TEXT NOT NULL,
    modelo             TEXT NOT NULL,
    tipo               TEXT NOT NULL,
    ano_fabricacao     SMALLINT,
    ano_modelo         SMALLINT,
    blindagem          BOOLEAN NOT NULL,
    possui_rastreador  BOOLEAN NOT NULL,
    status_veiculo     TEXT NOT NULL,
    valor_fipe         NUMERIC(12, 2),
    cor                TEXT,
    chassi             VARCHAR(17),
    filial             TEXT,
    CONSTRAINT ck_dim_veiculo_placa CHECK (placa ~ '^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$'),
    CONSTRAINT ck_dim_veiculo_tipo CHECK (tipo IN ('Leve', 'Pick-up', 'Van', 'Caminhão', 'Ônibus', 'Moto')),
    CONSTRAINT ck_dim_veiculo_anos CHECK (ano_modelo IS NULL OR ano_fabricacao IS NULL OR ano_modelo BETWEEN ano_fabricacao AND ano_fabricacao + 1)
);

CREATE TABLE IF NOT EXISTS gold.dim_alocacao (
    id_alocacao      INTEGER PRIMARY KEY,
    id_veiculo       INTEGER NOT NULL REFERENCES gold.dim_veiculo (id_veiculo),
    id_centro_custo  INTEGER NOT NULL REFERENCES gold.dim_centro_custo (id_centro_custo),
    contrato         TEXT,                       -- vazio = frota própria
    operacao         TEXT,
    data_inicio      DATE NOT NULL,
    data_fim         DATE,                       -- NULL = alocação vigente
    CONSTRAINT ck_dim_alocacao_periodo CHECK (data_fim IS NULL OR data_fim >= data_inicio),
    -- um veículo não pode estar em dois centros de custo no mesmo dia
    CONSTRAINT ex_dim_alocacao_sem_sobreposicao EXCLUDE USING gist (
        id_veiculo WITH =,
        daterange(data_inicio, data_fim, '[]') WITH &&
    )
);
COMMENT ON TABLE gold.dim_alocacao IS
    'Período de alocação de cada veículo (SCD tipo 2 simplificada). Responde "a qual centro de custo o veículo pertencia na data".';

CREATE TABLE IF NOT EXISTS gold.dim_motorista (
    id_motorista  INTEGER PRIMARY KEY,
    motorista     TEXT NOT NULL UNIQUE
);
-- Membro "desconhecido": motorista vazio na telemetria aponta para cá
INSERT INTO gold.dim_motorista (id_motorista, motorista)
VALUES (0, 'Indefinido')
ON CONFLICT (id_motorista) DO NOTHING;

-- =========================================================
-- FATOS
-- =========================================================
CREATE TABLE IF NOT EXISTS gold.fato_alertas (
    id_evento         CHAR(32) PRIMARY KEY,
    id_veiculo        INTEGER NOT NULL REFERENCES gold.dim_veiculo (id_veiculo),
    id_motorista      INTEGER NOT NULL REFERENCES gold.dim_motorista (id_motorista),
    id_centro_custo   INTEGER REFERENCES gold.dim_centro_custo (id_centro_custo),
    data              DATE NOT NULL REFERENCES gold.dim_data (data),
    data_hora_evento  TIMESTAMP NOT NULL,
    nome_regra        TEXT NOT NULL,
    duracao_min       NUMERIC(10, 2),
    valor_metrica     NUMERIC(10, 2),
    unidade_metrica   TEXT,
    odometro_inicial  NUMERIC(12, 2),
    odometro_final    NUMERIC(12, 2),
    distancia_km      NUMERIC(12, 2),
    CONSTRAINT ck_fato_alertas_distancia CHECK (distancia_km IS NULL OR distancia_km >= 0),
    CONSTRAINT ck_fato_alertas_duracao CHECK (duracao_min IS NULL OR duracao_min >= 0)
);

CREATE TABLE IF NOT EXISTS gold.fato_utilizacao (
    id_viagem            CHAR(32) PRIMARY KEY,
    id_veiculo           INTEGER NOT NULL REFERENCES gold.dim_veiculo (id_veiculo),
    id_motorista         INTEGER NOT NULL REFERENCES gold.dim_motorista (id_motorista),
    id_centro_custo      INTEGER REFERENCES gold.dim_centro_custo (id_centro_custo),
    data                 DATE NOT NULL REFERENCES gold.dim_data (data),
    data_inicial         TIMESTAMP NOT NULL,
    data_final           TIMESTAMP NOT NULL,
    distancia_km         NUMERIC(12, 2) NOT NULL,
    duracao_min          NUMERIC(10, 2),
    motor_ocioso_min     NUMERIC(10, 2),
    consumo_l            NUMERIC(10, 2),
    eficiencia_km_l      NUMERIC(10, 2),
    vel_maxima           NUMERIC(6, 1),
    vel_media_movimento  NUMERIC(6, 1),
    qtd_frenagem         INTEGER,
    tempo_frenagem_min   NUMERIC(10, 2),
    CONSTRAINT ck_fato_utilizacao_distancia CHECK (distancia_km >= 0),
    CONSTRAINT ck_fato_utilizacao_consumo CHECK (consumo_l IS NULL OR consumo_l >= 0),
    CONSTRAINT ck_fato_utilizacao_periodo CHECK (data_final >= data_inicial)
);

CREATE TABLE IF NOT EXISTS gold.fato_manutencao (
    numero_os                   TEXT PRIMARY KEY,   -- Controle de Pedido Interno (BRN-26-0001)
    id_veiculo                  INTEGER NOT NULL REFERENCES gold.dim_veiculo (id_veiculo),
    id_centro_custo             INTEGER REFERENCES gold.dim_centro_custo (id_centro_custo),
    data                        DATE NOT NULL REFERENCES gold.dim_data (data),   -- data de abertura da OS
    contrato                    TEXT,
    oficina                     TEXT NOT NULL,
    tipo_manutencao             TEXT NOT NULL,
    criticidade                 TEXT,
    tipo_sistema                TEXT NOT NULL,
    descricao_problema          TEXT,
    status_manutencao           TEXT NOT NULL,
    status_operacional          TEXT,
    km_atual                    INTEGER,
    data_os                     DATE NOT NULL,
    data_entrada_oficina        DATE,
    data_prevista_saida         DATE,
    data_orcamento              DATE,
    data_solicitacao_aprovacao  DATE,
    data_aprovacao              DATE,
    data_pedido_compra          DATE,
    data_compra_efetivada       DATE,
    data_entrega_peca           DATE,
    data_real_saida             DATE,
    data_pagamento_oficina      DATE,
    valor_orcamento             NUMERIC(12, 2),
    valor_negociado             NUMERIC(12, 2),
    n_requisicao_pecas          TEXT,
    valor_pecas                 NUMERIC(12, 2),
    veiculo_substituto          BOOLEAN,
    placa_substituto            VARCHAR(7),
    tipo_aluguel                TEXT,
    valor_aluguel               NUMERIC(12, 2),

    -- ---- colunas calculadas pelo próprio banco ----
    pct_variacao NUMERIC(8, 4) GENERATED ALWAYS AS (
        CASE WHEN valor_orcamento > 0 AND valor_negociado IS NOT NULL
             THEN ROUND((valor_negociado - valor_orcamento) / valor_orcamento, 4) END
    ) STORED,
    desconto_obtido NUMERIC(12, 2) GENERATED ALWAYS AS (valor_orcamento - valor_negociado) STORED,
    -- etapa pela última data preenchida (a "verdade" das datas; o status digitado pode divergir)
    etapa_atual TEXT GENERATED ALWAYS AS (
        CASE
            WHEN data_real_saida      IS NOT NULL THEN 'Concluída'
            WHEN data_entrega_peca    IS NOT NULL THEN 'Em manutenção'
            WHEN data_aprovacao       IS NOT NULL THEN 'Aguardando peças'
            WHEN data_orcamento       IS NOT NULL THEN 'Aguardando aprovação'
            WHEN data_entrada_oficina IS NOT NULL THEN 'Em diagnóstico'
            ELSE 'Em agendamento'
        END
    ) STORED,
    -- dias em cada etapa do SLA (date - date = inteiro; vazio enquanto a etapa não fecha)
    dias_os_entrada            INTEGER GENERATED ALWAYS AS (data_entrada_oficina - data_os) STORED,
    dias_entrada_orcamento     INTEGER GENERATED ALWAYS AS (data_orcamento - data_entrada_oficina) STORED,
    dias_orcamento_solicitacao INTEGER GENERATED ALWAYS AS (data_solicitacao_aprovacao - data_orcamento) STORED,
    dias_solicitacao_aprovacao INTEGER GENERATED ALWAYS AS (data_aprovacao - data_solicitacao_aprovacao) STORED,
    dias_aprovacao_pedido      INTEGER GENERATED ALWAYS AS (data_pedido_compra - data_aprovacao) STORED,
    dias_pedido_compra         INTEGER GENERATED ALWAYS AS (data_compra_efetivada - data_pedido_compra) STORED,
    dias_compra_entrega        INTEGER GENERATED ALWAYS AS (data_entrega_peca - data_compra_efetivada) STORED,
    dias_entrada_saida         INTEGER GENERATED ALWAYS AS (data_real_saida - data_entrada_oficina) STORED,

    CONSTRAINT ck_fato_manutencao_tipo CHECK (tipo_manutencao IN ('Preventiva', 'Corretiva', 'Preditiva')),
    CONSTRAINT ck_fato_manutencao_criticidade CHECK (criticidade IS NULL OR criticidade IN ('Baixa', 'Média', 'Alta')),
    CONSTRAINT ck_fato_manutencao_status CHECK (status_manutencao IN
        ('Em agendamento', 'Em diagnóstico', 'Aguardando aprovação', 'Aguardando peças', 'Em manutenção', 'Concluída')),
    CONSTRAINT ck_fato_manutencao_operacional CHECK (status_operacional IS NULL OR status_operacional IN
        ('Operando', 'Parado', 'Restrição')),
    CONSTRAINT ck_fato_manutencao_aluguel CHECK (tipo_aluguel IS NULL OR tipo_aluguel IN ('Diária', 'Período')),
    CONSTRAINT ck_fato_manutencao_valores CHECK (valor_orcamento IS NULL OR valor_orcamento >= 0),
    CONSTRAINT ck_fato_manutencao_entrada CHECK (data_entrada_oficina IS NULL OR data_entrada_oficina >= data_os),
    CONSTRAINT ck_fato_manutencao_saida CHECK (data_real_saida IS NULL OR data_real_saida >= data_entrada_oficina)
);
COMMENT ON TABLE gold.fato_manutencao IS
    '1 linha = 1 OS. pct_variacao, desconto_obtido, etapa_atual e dias_* são calculados pelo banco (GENERATED). Dias parado, locação e custo do veículo parado dependem da data de referência e ficam na view gold.vw_os_situacao.';

-- =========================================================
-- ÍNDICES para os filtros do dashboard (período, veículo, centro de custo)
-- =========================================================
CREATE INDEX IF NOT EXISTS ix_fato_alertas_data         ON gold.fato_alertas (data);
CREATE INDEX IF NOT EXISTS ix_fato_alertas_veiculo      ON gold.fato_alertas (id_veiculo, data);
CREATE INDEX IF NOT EXISTS ix_fato_alertas_regra        ON gold.fato_alertas (nome_regra);
CREATE INDEX IF NOT EXISTS ix_fato_utilizacao_data      ON gold.fato_utilizacao (data);
CREATE INDEX IF NOT EXISTS ix_fato_utilizacao_veiculo   ON gold.fato_utilizacao (id_veiculo, data);
CREATE INDEX IF NOT EXISTS ix_fato_manutencao_veiculo   ON gold.fato_manutencao (id_veiculo, data);
CREATE INDEX IF NOT EXISTS ix_fato_manutencao_cc        ON gold.fato_manutencao (id_centro_custo);
CREATE INDEX IF NOT EXISTS ix_dim_alocacao_veiculo      ON gold.dim_alocacao (id_veiculo, data_inicio);

-- ---------------------------------------------------------
-- Segurança: RLS ligado em todas as tabelas da camada.
-- Sem política, nada é lido pela API pública; o pipeline conecta
-- como dono das tabelas e não é afetado. (Idempotente.)
-- ---------------------------------------------------------
DO $$
DECLARE t RECORD;
BEGIN
    FOR t IN SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'gold' LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.schemaname, t.tablename);
    END LOOP;
END $$;
