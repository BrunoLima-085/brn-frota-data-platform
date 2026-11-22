-- =========================================================
-- 04_CARGA_GOLD.SQL — funções que montam a gold a partir da silver
-- =========================================================
-- Projeto: brn-frota-data-platform (dados 100% fictícios)
--
-- A modelagem dimensional é feita em SQL, dentro do banco:
--   * upsert com INSERT ... ON CONFLICT DO UPDATE;
--   * só atualiza o que mudou (WHERE ... IS DISTINCT FROM ...);
--   * conta novos x atualizados com o truque do (xmax = 0) no RETURNING;
--   * centro de custo resolvido pela alocação vigente NA DATA do evento;
--   * regra de negócio: motor ocioso só conta a partir de N minutos;
--   * sincronia: o que saiu da silver (ex.: outlier rejeitado) sai da gold.
--
-- O pipeline chama:  SELECT * FROM gold.carregar_dimensoes();
--                    SELECT * FROM gold.carregar_fatos_telemetria();
-- Pode rodar este arquivo quantas vezes quiser (CREATE OR REPLACE).
-- =========================================================

-- =========================================================
-- DIMENSÕES
-- =========================================================
CREATE OR REPLACE FUNCTION gold.carregar_dimensoes()
RETURNS TABLE (tabela TEXT, inseridos BIGINT, atualizados BIGINT)
LANGUAGE plpgsql
AS $$
#variable_conflict use_column
BEGIN
    -- centros de custo
    RETURN QUERY
    WITH up AS (
        INSERT INTO gold.dim_centro_custo AS d (id_centro_custo, centro_custo, cidade, regional)
        SELECT id_centro_custo, centro_custo, cidade, regional
        FROM silver.centros_custo
        ON CONFLICT (id_centro_custo) DO UPDATE
           SET centro_custo = EXCLUDED.centro_custo, cidade = EXCLUDED.cidade, regional = EXCLUDED.regional
         WHERE (d.centro_custo, d.cidade, d.regional)
               IS DISTINCT FROM (EXCLUDED.centro_custo, EXCLUDED.cidade, EXCLUDED.regional)
        RETURNING (xmax = 0) AS novo
    )
    SELECT 'dim_centro_custo', count(*) FILTER (WHERE novo), count(*) FILTER (WHERE NOT novo) FROM up;

    -- veículos
    RETURN QUERY
    WITH up AS (
        INSERT INTO gold.dim_veiculo AS d (id_veiculo, placa, marca, modelo, tipo, ano_fabricacao, ano_modelo,
                                           blindagem, possui_rastreador, status_veiculo, valor_fipe,
                                           cor, chassi, filial)
        SELECT id_veiculo, placa, marca, modelo, tipo, ano_fabricacao, ano_modelo,
               blindagem, possui_rastreador, status_veiculo, valor_fipe, cor, chassi, filial
        FROM silver.veiculos
        ON CONFLICT (id_veiculo) DO UPDATE
           SET placa = EXCLUDED.placa, marca = EXCLUDED.marca, modelo = EXCLUDED.modelo, tipo = EXCLUDED.tipo,
               ano_fabricacao = EXCLUDED.ano_fabricacao, ano_modelo = EXCLUDED.ano_modelo,
               blindagem = EXCLUDED.blindagem, possui_rastreador = EXCLUDED.possui_rastreador,
               status_veiculo = EXCLUDED.status_veiculo, valor_fipe = EXCLUDED.valor_fipe,
               cor = EXCLUDED.cor, chassi = EXCLUDED.chassi, filial = EXCLUDED.filial
         WHERE (d.placa, d.marca, d.modelo, d.tipo, d.ano_fabricacao, d.ano_modelo, d.blindagem,
                d.possui_rastreador, d.status_veiculo, d.valor_fipe, d.cor, d.chassi, d.filial)
               IS DISTINCT FROM
               (EXCLUDED.placa, EXCLUDED.marca, EXCLUDED.modelo, EXCLUDED.tipo, EXCLUDED.ano_fabricacao,
                EXCLUDED.ano_modelo, EXCLUDED.blindagem, EXCLUDED.possui_rastreador, EXCLUDED.status_veiculo,
                EXCLUDED.valor_fipe, EXCLUDED.cor, EXCLUDED.chassi, EXCLUDED.filial)
        RETURNING (xmax = 0) AS novo
    )
    SELECT 'dim_veiculo', count(*) FILTER (WHERE novo), count(*) FILTER (WHERE NOT novo) FROM up;

    -- motoristas (o id 0 "Indefinido" já existe)
    RETURN QUERY
    WITH up AS (
        INSERT INTO gold.dim_motorista AS d (id_motorista, motorista)
        SELECT id_motorista, motorista FROM silver.motoristas
        ON CONFLICT (id_motorista) DO UPDATE SET motorista = EXCLUDED.motorista
         WHERE d.motorista IS DISTINCT FROM EXCLUDED.motorista
        RETURNING (xmax = 0) AS novo
    )
    SELECT 'dim_motorista', count(*) FILTER (WHERE novo), count(*) FILTER (WHERE NOT novo) FROM up;

    -- alocações (a restrição EXCLUDE recusa períodos sobrepostos do mesmo veículo)
    RETURN QUERY
    WITH up AS (
        INSERT INTO gold.dim_alocacao AS d (id_alocacao, id_veiculo, id_centro_custo, contrato, operacao,
                                            data_inicio, data_fim)
        SELECT id_alocacao, id_veiculo, id_centro_custo, contrato, operacao, data_inicio, data_fim
        FROM silver.alocacao
        ON CONFLICT (id_alocacao) DO UPDATE
           SET id_veiculo = EXCLUDED.id_veiculo, id_centro_custo = EXCLUDED.id_centro_custo,
               contrato = EXCLUDED.contrato, operacao = EXCLUDED.operacao,
               data_inicio = EXCLUDED.data_inicio, data_fim = EXCLUDED.data_fim
         WHERE (d.id_veiculo, d.id_centro_custo, d.contrato, d.operacao, d.data_inicio, d.data_fim)
               IS DISTINCT FROM
               (EXCLUDED.id_veiculo, EXCLUDED.id_centro_custo, EXCLUDED.contrato, EXCLUDED.operacao,
                EXCLUDED.data_inicio, EXCLUDED.data_fim)
        RETURNING (xmax = 0) AS novo
    )
    SELECT 'dim_alocacao', count(*) FILTER (WHERE novo), count(*) FILTER (WHERE NOT novo) FROM up;
END;
$$;
COMMENT ON FUNCTION gold.carregar_dimensoes() IS 'Upsert das dimensões a partir da silver. Retorna novos x atualizados por tabela.';


-- =========================================================
-- FATOS DE TELEMETRIA
-- =========================================================
CREATE OR REPLACE FUNCTION gold.carregar_fatos_telemetria(p_ocioso_minimo_min NUMERIC DEFAULT 5)
RETURNS TABLE (tabela TEXT, inseridos BIGINT, atualizados BIGINT)
LANGUAGE plpgsql
AS $$
#variable_conflict use_column
BEGIN
    -- ---------------- alertas ----------------
    RETURN QUERY
    WITH origem AS (
        SELECT a.id_evento,
               v.id_veiculo,
               COALESCE(m.id_motorista, 0)        AS id_motorista,      -- vazio -> "Indefinido"
               al.id_centro_custo,                                       -- alocação vigente na data
               a.data_hora_evento::date           AS data,
               a.data_hora_evento, a.nome_regra, a.duracao_min, a.valor_metrica, a.unidade_metrica,
               a.odometro_inicial, a.odometro_final, a.distancia_km
        FROM silver.alertas a
        JOIN gold.dim_veiculo v        ON v.placa = a.placa
        LEFT JOIN gold.dim_motorista m ON m.motorista = a.motorista
        LEFT JOIN gold.dim_alocacao al ON al.id_veiculo = v.id_veiculo
                                      AND a.data_hora_evento::date BETWEEN al.data_inicio
                                                                       AND COALESCE(al.data_fim, 'infinity'::date)
        -- regra de negócio: motor ocioso abaixo do mínimo não é alerta
        WHERE NOT (a.nome_regra = 'Motor ocioso' AND COALESCE(a.duracao_min, 0) < p_ocioso_minimo_min)
    ),
    up AS (
        INSERT INTO gold.fato_alertas AS f (id_evento, id_veiculo, id_motorista, id_centro_custo, data,
                                            data_hora_evento, nome_regra, duracao_min, valor_metrica,
                                            unidade_metrica, odometro_inicial, odometro_final, distancia_km)
        SELECT id_evento, id_veiculo, id_motorista, id_centro_custo, data, data_hora_evento, nome_regra,
               duracao_min, valor_metrica, unidade_metrica, odometro_inicial, odometro_final, distancia_km
        FROM origem
        ON CONFLICT (id_evento) DO UPDATE
           SET id_veiculo = EXCLUDED.id_veiculo, id_motorista = EXCLUDED.id_motorista,
               id_centro_custo = EXCLUDED.id_centro_custo, data = EXCLUDED.data,
               data_hora_evento = EXCLUDED.data_hora_evento, nome_regra = EXCLUDED.nome_regra,
               duracao_min = EXCLUDED.duracao_min, valor_metrica = EXCLUDED.valor_metrica,
               unidade_metrica = EXCLUDED.unidade_metrica, odometro_inicial = EXCLUDED.odometro_inicial,
               odometro_final = EXCLUDED.odometro_final, distancia_km = EXCLUDED.distancia_km
         WHERE (f.id_veiculo, f.id_motorista, f.id_centro_custo, f.data, f.data_hora_evento, f.nome_regra,
                f.duracao_min, f.valor_metrica, f.unidade_metrica, f.odometro_inicial, f.odometro_final,
                f.distancia_km)
               IS DISTINCT FROM
               (EXCLUDED.id_veiculo, EXCLUDED.id_motorista, EXCLUDED.id_centro_custo, EXCLUDED.data,
                EXCLUDED.data_hora_evento, EXCLUDED.nome_regra, EXCLUDED.duracao_min, EXCLUDED.valor_metrica,
                EXCLUDED.unidade_metrica, EXCLUDED.odometro_inicial, EXCLUDED.odometro_final,
                EXCLUDED.distancia_km)
        RETURNING (xmax = 0) AS novo
    )
    SELECT 'fato_alertas', count(*) FILTER (WHERE novo), count(*) FILTER (WHERE NOT novo) FROM up;

    -- sincronia: alerta que saiu da silver (ou virou ocioso < mínimo) sai da gold
    RETURN QUERY
    WITH removidos AS (
        DELETE FROM gold.fato_alertas f
        WHERE NOT EXISTS (
            SELECT 1 FROM silver.alertas a
            WHERE a.id_evento = f.id_evento
              AND NOT (a.nome_regra = 'Motor ocioso' AND COALESCE(a.duracao_min, 0) < p_ocioso_minimo_min))
        RETURNING 1
    )
    SELECT 'fato_alertas (removidos)', 0::bigint, count(*) FROM removidos;

    -- informativo: quantos alertas a regra do motor ocioso deixou de fora
    RETURN QUERY
    SELECT 'regra: motor ocioso < ' || p_ocioso_minimo_min || ' min (fora da fato)', count(*), 0::bigint
    FROM silver.alertas
    WHERE nome_regra = 'Motor ocioso' AND COALESCE(duracao_min, 0) < p_ocioso_minimo_min;

    -- ---------------- utilização (viagens) ----------------
    RETURN QUERY
    WITH origem AS (
        SELECT u.id_viagem,
               v.id_veiculo,
               COALESCE(m.id_motorista, 0) AS id_motorista,
               al.id_centro_custo,
               u.data_inicial::date        AS data,
               u.data_inicial, u.data_final, u.distancia_km, u.duracao_min, u.motor_ocioso_min,
               u.consumo_l, u.eficiencia_km_l, u.vel_maxima, u.vel_media_movimento,
               u.qtd_frenagem, u.tempo_frenagem_min
        FROM silver.viagens u
        JOIN gold.dim_veiculo v        ON v.placa = u.placa
        LEFT JOIN gold.dim_motorista m ON m.motorista = u.motorista
        LEFT JOIN gold.dim_alocacao al ON al.id_veiculo = v.id_veiculo
                                      AND u.data_inicial::date BETWEEN al.data_inicio
                                                                   AND COALESCE(al.data_fim, 'infinity'::date)
    ),
    up AS (
        INSERT INTO gold.fato_utilizacao AS f (id_viagem, id_veiculo, id_motorista, id_centro_custo, data,
                                               data_inicial, data_final, distancia_km, duracao_min,
                                               motor_ocioso_min, consumo_l, eficiencia_km_l, vel_maxima,
                                               vel_media_movimento, qtd_frenagem, tempo_frenagem_min)
        SELECT id_viagem, id_veiculo, id_motorista, id_centro_custo, data, data_inicial, data_final,
               distancia_km, duracao_min, motor_ocioso_min, consumo_l, eficiencia_km_l, vel_maxima,
               vel_media_movimento, qtd_frenagem, tempo_frenagem_min
        FROM origem
        ON CONFLICT (id_viagem) DO UPDATE
           SET id_veiculo = EXCLUDED.id_veiculo, id_motorista = EXCLUDED.id_motorista,
               id_centro_custo = EXCLUDED.id_centro_custo, data = EXCLUDED.data,
               data_inicial = EXCLUDED.data_inicial, data_final = EXCLUDED.data_final,
               distancia_km = EXCLUDED.distancia_km, duracao_min = EXCLUDED.duracao_min,
               motor_ocioso_min = EXCLUDED.motor_ocioso_min, consumo_l = EXCLUDED.consumo_l,
               eficiencia_km_l = EXCLUDED.eficiencia_km_l, vel_maxima = EXCLUDED.vel_maxima,
               vel_media_movimento = EXCLUDED.vel_media_movimento, qtd_frenagem = EXCLUDED.qtd_frenagem,
               tempo_frenagem_min = EXCLUDED.tempo_frenagem_min
         WHERE (f.id_veiculo, f.id_motorista, f.id_centro_custo, f.data, f.data_inicial, f.data_final,
                f.distancia_km, f.duracao_min, f.motor_ocioso_min, f.consumo_l, f.eficiencia_km_l,
                f.vel_maxima, f.vel_media_movimento, f.qtd_frenagem, f.tempo_frenagem_min)
               IS DISTINCT FROM
               (EXCLUDED.id_veiculo, EXCLUDED.id_motorista, EXCLUDED.id_centro_custo, EXCLUDED.data,
                EXCLUDED.data_inicial, EXCLUDED.data_final, EXCLUDED.distancia_km, EXCLUDED.duracao_min,
                EXCLUDED.motor_ocioso_min, EXCLUDED.consumo_l, EXCLUDED.eficiencia_km_l, EXCLUDED.vel_maxima,
                EXCLUDED.vel_media_movimento, EXCLUDED.qtd_frenagem, EXCLUDED.tempo_frenagem_min)
        RETURNING (xmax = 0) AS novo
    )
    SELECT 'fato_utilizacao', count(*) FILTER (WHERE novo), count(*) FILTER (WHERE NOT novo) FROM up;

    RETURN QUERY
    WITH removidos AS (
        DELETE FROM gold.fato_utilizacao f
        WHERE NOT EXISTS (SELECT 1 FROM silver.viagens u WHERE u.id_viagem = f.id_viagem)
        RETURNING 1
    )
    SELECT 'fato_utilizacao (removidos)', 0::bigint, count(*) FROM removidos;
END;
$$;
COMMENT ON FUNCTION gold.carregar_fatos_telemetria(NUMERIC) IS
    'Upsert de fato_alertas e fato_utilizacao a partir da silver, com centro de custo pela data e regra do motor ocioso.';


-- =========================================================
-- FATO DE MANUTENÇÃO
-- =========================================================
-- pct_variacao, etapa_atual e dias_* são colunas GENERATED: o banco calcula.
-- O centro de custo vem da alocação vigente na data de entrada na oficina
-- (o texto digitado na planilha fica só na silver, para conferência).
CREATE OR REPLACE FUNCTION gold.carregar_fato_manutencao()
RETURNS TABLE (tabela TEXT, inseridos BIGINT, atualizados BIGINT)
LANGUAGE plpgsql
AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    WITH origem AS (
        SELECT o.numero_os, v.id_veiculo, al.id_centro_custo, o.data_os AS data, o.contrato, o.oficina,
               o.tipo_manutencao, o.criticidade, o.tipo_sistema, o.descricao_problema,
               o.status_manutencao, o.status_operacional, o.km_atual, o.data_os,
               o.data_entrada_oficina, o.data_prevista_saida, o.data_orcamento,
               o.data_solicitacao_aprovacao, o.data_aprovacao, o.data_pedido_compra,
               o.data_compra_efetivada, o.data_entrega_peca, o.data_real_saida,
               o.data_pagamento_oficina, o.valor_orcamento, o.valor_negociado, o.n_requisicao_pecas,
               o.valor_pecas, o.veiculo_substituto, o.placa_substituto, o.tipo_aluguel, o.valor_aluguel
        FROM silver.os_manutencao o
        JOIN gold.dim_veiculo v        ON v.placa = o.placa
        LEFT JOIN gold.dim_alocacao al ON al.id_veiculo = v.id_veiculo
                                      AND o.data_os BETWEEN al.data_inicio AND COALESCE(al.data_fim, 'infinity'::date)
    ),
    up AS (
        INSERT INTO gold.fato_manutencao AS f (
            numero_os, id_veiculo, id_centro_custo, data, contrato, oficina, tipo_manutencao,
            criticidade, tipo_sistema, descricao_problema, status_manutencao, status_operacional,
            km_atual, data_os, data_entrada_oficina, data_prevista_saida, data_orcamento,
            data_solicitacao_aprovacao, data_aprovacao, data_pedido_compra, data_compra_efetivada,
            data_entrega_peca, data_real_saida, data_pagamento_oficina, valor_orcamento,
            valor_negociado, n_requisicao_pecas, valor_pecas, veiculo_substituto, placa_substituto,
            tipo_aluguel, valor_aluguel)
        SELECT numero_os, id_veiculo, id_centro_custo, data, contrato, oficina, tipo_manutencao,
               criticidade, tipo_sistema, descricao_problema, status_manutencao, status_operacional,
               km_atual, data_os, data_entrada_oficina, data_prevista_saida, data_orcamento,
               data_solicitacao_aprovacao, data_aprovacao, data_pedido_compra, data_compra_efetivada,
               data_entrega_peca, data_real_saida, data_pagamento_oficina, valor_orcamento,
               valor_negociado, n_requisicao_pecas, valor_pecas, veiculo_substituto, placa_substituto,
               tipo_aluguel, valor_aluguel
        FROM origem
        ON CONFLICT (numero_os) DO UPDATE
           SET id_veiculo = EXCLUDED.id_veiculo, id_centro_custo = EXCLUDED.id_centro_custo,
               data = EXCLUDED.data, contrato = EXCLUDED.contrato, oficina = EXCLUDED.oficina,
               tipo_manutencao = EXCLUDED.tipo_manutencao, criticidade = EXCLUDED.criticidade,
               tipo_sistema = EXCLUDED.tipo_sistema, descricao_problema = EXCLUDED.descricao_problema,
               status_manutencao = EXCLUDED.status_manutencao,
               status_operacional = EXCLUDED.status_operacional, km_atual = EXCLUDED.km_atual,
               data_os = EXCLUDED.data_os, data_entrada_oficina = EXCLUDED.data_entrada_oficina,
               data_prevista_saida = EXCLUDED.data_prevista_saida,
               data_orcamento = EXCLUDED.data_orcamento,
               data_solicitacao_aprovacao = EXCLUDED.data_solicitacao_aprovacao,
               data_aprovacao = EXCLUDED.data_aprovacao,
               data_pedido_compra = EXCLUDED.data_pedido_compra,
               data_compra_efetivada = EXCLUDED.data_compra_efetivada,
               data_entrega_peca = EXCLUDED.data_entrega_peca,
               data_real_saida = EXCLUDED.data_real_saida,
               data_pagamento_oficina = EXCLUDED.data_pagamento_oficina,
               valor_orcamento = EXCLUDED.valor_orcamento, valor_negociado = EXCLUDED.valor_negociado,
               n_requisicao_pecas = EXCLUDED.n_requisicao_pecas, valor_pecas = EXCLUDED.valor_pecas,
               veiculo_substituto = EXCLUDED.veiculo_substituto,
               placa_substituto = EXCLUDED.placa_substituto, tipo_aluguel = EXCLUDED.tipo_aluguel,
               valor_aluguel = EXCLUDED.valor_aluguel
         WHERE (f.id_veiculo, f.id_centro_custo, f.data, f.contrato, f.oficina, f.tipo_manutencao,
                f.criticidade, f.tipo_sistema, f.descricao_problema, f.status_manutencao,
                f.status_operacional, f.km_atual, f.data_os, f.data_entrada_oficina,
                f.data_prevista_saida, f.data_orcamento, f.data_solicitacao_aprovacao,
                f.data_aprovacao, f.data_pedido_compra, f.data_compra_efetivada, f.data_entrega_peca,
                f.data_real_saida, f.data_pagamento_oficina, f.valor_orcamento, f.valor_negociado,
                f.n_requisicao_pecas, f.valor_pecas, f.veiculo_substituto, f.placa_substituto,
                f.tipo_aluguel, f.valor_aluguel)
               IS DISTINCT FROM
               (EXCLUDED.id_veiculo, EXCLUDED.id_centro_custo, EXCLUDED.data, EXCLUDED.contrato,
                EXCLUDED.oficina, EXCLUDED.tipo_manutencao, EXCLUDED.criticidade,
                EXCLUDED.tipo_sistema, EXCLUDED.descricao_problema, EXCLUDED.status_manutencao,
                EXCLUDED.status_operacional, EXCLUDED.km_atual, EXCLUDED.data_os,
                EXCLUDED.data_entrada_oficina, EXCLUDED.data_prevista_saida, EXCLUDED.data_orcamento,
                EXCLUDED.data_solicitacao_aprovacao, EXCLUDED.data_aprovacao,
                EXCLUDED.data_pedido_compra, EXCLUDED.data_compra_efetivada,
                EXCLUDED.data_entrega_peca, EXCLUDED.data_real_saida, EXCLUDED.data_pagamento_oficina,
                EXCLUDED.valor_orcamento, EXCLUDED.valor_negociado, EXCLUDED.n_requisicao_pecas,
                EXCLUDED.valor_pecas, EXCLUDED.veiculo_substituto, EXCLUDED.placa_substituto,
                EXCLUDED.tipo_aluguel, EXCLUDED.valor_aluguel)
        RETURNING (xmax = 0) AS novo
    )
    SELECT 'fato_manutencao', count(*) FILTER (WHERE novo), count(*) FILTER (WHERE NOT novo) FROM up;

    -- sincronia: OS que saiu da silver sai da gold
    RETURN QUERY
    WITH removidos AS (
        DELETE FROM gold.fato_manutencao f
        WHERE NOT EXISTS (SELECT 1 FROM silver.os_manutencao o WHERE o.numero_os = f.numero_os)
        RETURNING 1
    )
    SELECT 'fato_manutencao (removidos)', 0::bigint, count(*) FROM removidos;

    -- informativo: OS em quarentena (não entram na fato)
    RETURN QUERY
    SELECT 'quarentena_manutencao (fora da fato)', count(DISTINCT numero_os), 0::bigint
    FROM silver.quarentena_manutencao;
END;
$$;
COMMENT ON FUNCTION gold.carregar_fato_manutencao() IS
    'Upsert da fato_manutencao a partir da silver; centro de custo pela alocação na data de abertura da OS.';
