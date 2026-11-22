-- =========================================================
-- 01_BRONZE.SQL — camada bruta (como o dado chega da fonte)
-- =========================================================
-- Projeto: brn-frota-data-platform (dados 100% fictícios)
--
-- Regras da camada:
--   * tudo TEXT: a fonte não garante tipo ("1.250,00", "15/08/2026", "85320 km");
--   * só acrescenta, nunca altera: cada arquivo carregado vira um lote;
--   * o mesmo arquivo (mesmo hash) não entra duas vezes -> carga idempotente;
--   * duplicatas, rodapés TOTAL/MÉDIA e alertas em aberto ficam aqui como vieram.
--
-- Pode rodar quantas vezes quiser: só cria o que ainda não existe.
-- =========================================================

CREATE SCHEMA IF NOT EXISTS bronze;
COMMENT ON SCHEMA bronze IS 'Camada bruta: cópia fiel das fontes, tudo texto, só inserção.';

-- ---------------------------------------------------------
-- Controle de lotes (1 linha = 1 arquivo carregado)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.lote_carga (
    id_lote       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte         TEXT        NOT NULL,
    arquivo       TEXT        NOT NULL,
    hash_arquivo  CHAR(64)    NOT NULL,
    linhas        INTEGER     NOT NULL CHECK (linhas >= 0),
    carregado_em  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_lote_fonte CHECK (fonte IN (
        'telemetria_alertas', 'telemetria_bdv', 'manutencao_os',
        'frota_veiculos', 'frota_alocacao', 'frota_centros_custo', 'frota_motoristas'
    )),
    CONSTRAINT uq_lote_arquivo UNIQUE (fonte, hash_arquivo)
);
COMMENT ON TABLE bronze.lote_carga IS 'Um registro por arquivo carregado. O hash impede carregar o mesmo arquivo duas vezes.';

-- ---------------------------------------------------------
-- Telemetria: Alertas e notificações (35 colunas do export;
-- a coluna A do relatório vem sempre vazia e não é guardada)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.telemetria_alertas (
    id_bruto                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_lote                  BIGINT  NOT NULL REFERENCES bronze.lote_carga (id_lote) ON DELETE CASCADE,
    linha_arquivo            INTEGER NOT NULL,
    unidade_rastreada        TEXT,
    motorista                TEXT,
    n_ordem_rastreador       TEXT,
    telemetrias              TEXT,
    areas_rotas_geograficas  TEXT,
    entradas                 TEXT,
    saidas                   TEXT,
    eventos_controle         TEXT,
    nome_regra               TEXT,
    data_ocorrencia          TEXT,
    hora_ocorrencia          TEXT,
    finalizacao_ocorrencia   TEXT,
    duracao                  TEXT,
    odometro_inicial         TEXT,
    odometro_final           TEXT,
    distancia                TEXT,
    grupo_regras             TEXT,
    requer_tratamento        TEXT,
    situacao_chamado         TEXT,
    status_chamado           TEXT,
    nivel                    TEXT,
    categoria_chamado        TEXT,
    ticket                   TEXT,
    data_criacao             TEXT,
    duracao_chamado          TEXT,
    limite_fechar            TEXT,
    usuario_responsavel      TEXT,
    tempo_abrir              TEXT,
    limite_abrir             TEXT,
    grupo_unidades           TEXT,
    unidade_organizacional   TEXT,
    local_inicio             TEXT,
    local_fim                TEXT,
    modo_violacao            TEXT,
    CONSTRAINT uq_bronze_alertas_linha UNIQUE (id_lote, linha_arquivo)
);

-- ---------------------------------------------------------
-- Telemetria: Períodos de utilização (BDV) — 22 colunas
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.telemetria_bdv (
    id_bruto                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_lote                      BIGINT  NOT NULL REFERENCES bronze.lote_carga (id_lote) ON DELETE CASCADE,
    linha_arquivo                INTEGER NOT NULL,
    unidade_rastreada            TEXT,
    motorista                    TEXT,
    data_inicial                 TEXT,
    data_final                   TEXT,
    distancia_odo                TEXT,
    duracao_dt                   TEXT,
    motor_ocioso                 TEXT,
    consumo_l                    TEXT,
    eficiencia_km_l              TEXT,
    meta_consumo_pct             TEXT,
    economia_rs                  TEXT,
    gasto_combustivel_movimento  TEXT,
    gasto_combustivel_ocioso     TEXT,
    gasto_combustivel_total      TEXT,
    vel_maxima                   TEXT,
    vel_media_movimento          TEXT,
    grupo_unidades               TEXT,
    unidade_organizacional       TEXT,
    endereco_inicial             TEXT,
    endereco_final               TEXT,
    quantidade_frenagem          TEXT,
    tempo_frenagem               TEXT,
    CONSTRAINT uq_bronze_bdv_linha UNIQUE (id_lote, linha_arquivo)
);

-- ---------------------------------------------------------
-- Manutenção: planilha de OS (aba FATO_Manutencao, 36 colunas)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.manutencao_os (
    id_bruto                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_lote                     BIGINT  NOT NULL REFERENCES bronze.lote_carga (id_lote) ON DELETE CASCADE,
    linha_arquivo               INTEGER NOT NULL,
    controle_pedido_interno     TEXT,
    placa                       TEXT,
    modelo                      TEXT,
    centro_custo                TEXT,
    contrato                    TEXT,
    oficina                     TEXT,
    data_os                     TEXT,
    data_entrada_oficina        TEXT,
    data_prevista_saida         TEXT,
    data_real_saida             TEXT,
    data_orcamento              TEXT,
    data_solicitacao_aprovacao  TEXT,
    data_aprovacao              TEXT,
    data_pedido_compra          TEXT,
    data_compra_efetivada       TEXT,
    data_entrega_peca           TEXT,
    data_pagamento_oficina      TEXT,
    tipo_manutencao             TEXT,
    criticidade                 TEXT,
    valor_orcamento             TEXT,
    valor_negociado             TEXT,
    pct_variacao                TEXT,
    n_requisicao_pecas          TEXT,
    valor_pecas                 TEXT,
    km_atual                    TEXT,
    status_operacional          TEXT,
    veiculo_substituto          TEXT,
    placa_substituto            TEXT,
    tipo_aluguel                TEXT,
    valor_aluguel               TEXT,
    solicitante                 TEXT,
    tipo_sistema                TEXT,
    descricao_problema          TEXT,
    status_manutencao           TEXT,
    responsavel_aprovacao       TEXT,
    observacoes_gerais          TEXT,
    CONSTRAINT uq_bronze_os_linha UNIQUE (id_lote, linha_arquivo)
);

-- ---------------------------------------------------------
-- Frota (cadastros)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.frota_veiculos (
    id_bruto        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_lote         BIGINT  NOT NULL REFERENCES bronze.lote_carga (id_lote) ON DELETE CASCADE,
    linha_arquivo   INTEGER NOT NULL,
    id_veiculo      TEXT,
    placa           TEXT,
    marca           TEXT,
    modelo          TEXT,
    cor             TEXT,
    tipo            TEXT,
    ano_fabricacao  TEXT,
    ano_modelo      TEXT,
    blindagem       TEXT,
    rastreador      TEXT,
    status_veiculo  TEXT,
    valor_fipe      TEXT,
    chassi          TEXT,
    filial          TEXT,
    CONSTRAINT uq_bronze_veiculos_linha UNIQUE (id_lote, linha_arquivo)
);

CREATE TABLE IF NOT EXISTS bronze.frota_alocacao (
    id_bruto         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_lote          BIGINT  NOT NULL REFERENCES bronze.lote_carga (id_lote) ON DELETE CASCADE,
    linha_arquivo    INTEGER NOT NULL,
    id_alocacao      TEXT,
    id_veiculo       TEXT,
    placa            TEXT,
    id_centro_custo  TEXT,
    centro_custo     TEXT,
    contrato         TEXT,
    operacao         TEXT,
    data_inicio      TEXT,
    data_fim         TEXT,
    status_alocacao  TEXT,
    CONSTRAINT uq_bronze_alocacao_linha UNIQUE (id_lote, linha_arquivo)
);

CREATE TABLE IF NOT EXISTS bronze.frota_centros_custo (
    id_bruto         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_lote          BIGINT  NOT NULL REFERENCES bronze.lote_carga (id_lote) ON DELETE CASCADE,
    linha_arquivo    INTEGER NOT NULL,
    id_centro_custo  TEXT,
    centro_custo     TEXT,
    cidade           TEXT,
    regional         TEXT,
    CONSTRAINT uq_bronze_cc_linha UNIQUE (id_lote, linha_arquivo)
);

CREATE TABLE IF NOT EXISTS bronze.frota_motoristas (
    id_bruto       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_lote        BIGINT  NOT NULL REFERENCES bronze.lote_carga (id_lote) ON DELETE CASCADE,
    linha_arquivo  INTEGER NOT NULL,
    id_motorista   TEXT,
    motorista      TEXT,
    CONSTRAINT uq_bronze_motoristas_linha UNIQUE (id_lote, linha_arquivo)
);

-- ---------------------------------------------------------
-- Segurança: RLS ligado em todas as tabelas da camada.
-- Sem política, nada é lido pela API pública; o pipeline conecta
-- como dono das tabelas e não é afetado. (Idempotente.)
-- ---------------------------------------------------------
DO $$
DECLARE t RECORD;
BEGIN
    FOR t IN SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'bronze' LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.schemaname, t.tablename);
    END LOOP;
END $$;
