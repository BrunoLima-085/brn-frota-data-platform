-- =========================================================
-- 05_TESTES_QUALIDADE.SQL — testes de qualidade de dados no banco
-- =========================================================
-- Projeto: brn-frota-data-platform (dados 100% fictícios)
--
-- Uma função que roda todos os testes e devolve uma linha por teste:
--     SELECT * FROM gold.testes_qualidade();
--
-- critico = true  -> falha para o pipeline (código de saída <> 0)
-- critico = false -> aviso (aparece no relatório, não para nada)
--
-- O que já é garantido por restrição (PK, FK, CHECK, EXCLUDE) não é
-- testado de novo aqui: os testes cobrem o que o banco não impede sozinho,
-- principalmente a CONSERVAÇÃO entre camadas (nada some no caminho).
-- Pode rodar este arquivo quantas vezes quiser (CREATE OR REPLACE).
-- =========================================================

CREATE OR REPLACE FUNCTION gold.testes_qualidade(p_ocioso_minimo_min NUMERIC DEFAULT 5)
RETURNS TABLE (camada TEXT, teste TEXT, critico BOOLEAN, falhas BIGINT, resultado TEXT)
LANGUAGE sql
STABLE
AS $$
WITH testes (camada, teste, critico, falhas) AS (

    -- ---------- conservação: silver -> gold (nada pode sumir sem regra) ----------
    SELECT 'gold', 'fato_alertas = silver.alertas menos a regra do motor ocioso', true,
           abs((SELECT count(*) FROM silver.alertas
                WHERE NOT (nome_regra = 'Motor ocioso' AND COALESCE(duracao_min, 0) < p_ocioso_minimo_min))
               - (SELECT count(*) FROM gold.fato_alertas))
    UNION ALL
    SELECT 'gold', 'fato_utilizacao = silver.viagens', true,
           abs((SELECT count(*) FROM silver.viagens) - (SELECT count(*) FROM gold.fato_utilizacao))
    UNION ALL
    SELECT 'gold', 'fato_manutencao = silver.os_manutencao', true,
           abs((SELECT count(*) FROM silver.os_manutencao) - (SELECT count(*) FROM gold.fato_manutencao))

    -- ---------- integridade: placa da silver precisa existir na frota ----------
    UNION ALL
    SELECT 'silver', 'alertas/viagens com placa fora da dim_veiculo', true,
           (SELECT count(*) FROM silver.alertas a WHERE NOT EXISTS (SELECT 1 FROM gold.dim_veiculo v WHERE v.placa = a.placa))
         + (SELECT count(*) FROM silver.viagens u WHERE NOT EXISTS (SELECT 1 FROM gold.dim_veiculo v WHERE v.placa = u.placa))
    UNION ALL
    SELECT 'silver', 'OS com placa fora da dim_veiculo (deveriam estar na quarentena)', true,
           (SELECT count(*) FROM silver.os_manutencao o WHERE NOT EXISTS (SELECT 1 FROM gold.dim_veiculo v WHERE v.placa = o.placa))

    -- ---------- pipeline em dia ----------
    UNION ALL
    SELECT 'bronze', 'lotes carregados e ainda não tratados', true,
           (SELECT count(*) FROM bronze.lote_carga l
            WHERE NOT EXISTS (SELECT 1 FROM silver.lote_processado p WHERE p.id_lote = l.id_lote))

    -- ---------- valores fisicamente possíveis na gold ----------
    UNION ALL
    SELECT 'gold', 'viagem com velocidade média implícita > 200 km/h', true,
           (SELECT count(*) FROM gold.fato_utilizacao
            WHERE duracao_min > 0 AND distancia_km / (duracao_min / 60) > 200)

    -- ---------- avisos (não param o pipeline) ----------
    UNION ALL
    SELECT 'gold', 'fato sem centro de custo (veículo sem alocação na data)', false,
           (SELECT count(*) FROM gold.fato_alertas WHERE id_centro_custo IS NULL)
         + (SELECT count(*) FROM gold.fato_utilizacao WHERE id_centro_custo IS NULL)
         + (SELECT count(*) FROM gold.fato_manutencao WHERE id_centro_custo IS NULL)
    UNION ALL
    SELECT 'gold', 'OS com datas do fluxo fora de ordem', false,
           (SELECT count(*) FROM gold.fato_manutencao
            WHERE dias_os_entrada < 0 OR dias_entrada_orcamento < 0 OR dias_orcamento_solicitacao < 0
               OR dias_solicitacao_aprovacao < 0 OR dias_aprovacao_pedido < 0 OR dias_pedido_compra < 0
               OR dias_compra_entrega < 0 OR data_pagamento_oficina < data_real_saida)
    UNION ALL
    SELECT 'gold', 'OS com valor negociado acima do orçamento', false,
           (SELECT count(*) FROM gold.fato_manutencao WHERE valor_negociado > valor_orcamento)
    UNION ALL
    SELECT 'gold', 'OS com veículo substituto sem placa do substituto', false,
           (SELECT count(*) FROM gold.fato_manutencao WHERE veiculo_substituto AND placa_substituto IS NULL)
    UNION ALL
    SELECT 'gold', 'OS com status digitado diferente da etapa pelas datas', false,
           (SELECT count(*) FROM gold.fato_manutencao WHERE status_manutencao <> etapa_atual)
    UNION ALL
    SELECT 'gold', 'veículo ativo sem alocação vigente', false,
           (SELECT count(*) FROM gold.dim_veiculo v
            WHERE v.status_veiculo = 'Ativo'
              AND NOT EXISTS (SELECT 1 FROM gold.dim_alocacao a WHERE a.id_veiculo = v.id_veiculo AND a.data_fim IS NULL))
    UNION ALL
    SELECT 'silver', 'outliers aguardando revisão (Pendente)', false,
           (SELECT count(*) FROM silver.outliers_telemetria WHERE status = 'Pendente')
    UNION ALL
    SELECT 'silver', 'OS em quarentena', false,
           (SELECT count(DISTINCT numero_os) FROM silver.quarentena_manutencao)
)
SELECT camada, teste, critico, falhas,
       CASE WHEN falhas = 0 THEN 'OK' WHEN critico THEN 'FALHOU' ELSE 'AVISO' END
FROM testes;
$$;
COMMENT ON FUNCTION gold.testes_qualidade(NUMERIC) IS
    'Testes de qualidade entre camadas. critico=true derruba o pipeline; false é aviso.';
