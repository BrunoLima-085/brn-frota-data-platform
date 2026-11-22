-- =========================================================
-- 06_RETENCAO_BRONZE.SQL — política de retenção da camada bruta
-- =========================================================
-- Projeto: brn-frota-data-platform (dados 100% fictícios)
--
-- Com a simulação rodando todo dia, a bronze cresce sem parar. A bronze
-- serve para auditoria e reprocessamento recente; o histórico tratado
-- mora na silver/gold. Então:
--   * linhas brutas de lotes JÁ TRATADOS e mais antigos que N dias são apagadas;
--   * o registro do lote (bronze.lote_carga, com o hash) FICA: é ele que impede
--     o mesmo arquivo de ser carregado de novo;
--   * lote ainda não tratado nunca é apagado.
--
--     SELECT * FROM bronze.aplicar_retencao(90);
-- Pode rodar este arquivo quantas vezes quiser (CREATE OR REPLACE / IF NOT EXISTS).
-- =========================================================

ALTER TABLE bronze.lote_carga ADD COLUMN IF NOT EXISTS linhas_expurgadas_em TIMESTAMPTZ;
COMMENT ON COLUMN bronze.lote_carga.linhas_expurgadas_em IS
    'Quando as linhas brutas deste lote foram apagadas pela retenção (o lote continua registrado).';

CREATE OR REPLACE FUNCTION bronze.aplicar_retencao(p_dias INTEGER DEFAULT 90)
RETURNS TABLE (tabela TEXT, linhas_apagadas BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
    v_tabela TEXT;
    v_total  BIGINT;
BEGIN
    IF p_dias < 7 THEN
        RAISE EXCEPTION 'Retenção mínima de 7 dias (recebido: %)', p_dias;
    END IF;

    CREATE TEMP TABLE lotes_expirados ON COMMIT DROP AS
    SELECT l.id_lote
    FROM bronze.lote_carga l
    WHERE l.carregado_em < now() - make_interval(days => p_dias)
      AND l.linhas_expurgadas_em IS NULL
      AND EXISTS (SELECT 1 FROM silver.lote_processado p WHERE p.id_lote = l.id_lote);

    FOREACH v_tabela IN ARRAY ARRAY['telemetria_alertas', 'telemetria_bdv', 'manutencao_os', 'frota_veiculos',
                                    'frota_alocacao', 'frota_centros_custo', 'frota_motoristas'] LOOP
        EXECUTE format('DELETE FROM bronze.%I WHERE id_lote IN (SELECT id_lote FROM lotes_expirados)', v_tabela);
        GET DIAGNOSTICS v_total = ROW_COUNT;
        tabela := v_tabela;
        linhas_apagadas := v_total;
        RETURN NEXT;
    END LOOP;

    UPDATE bronze.lote_carga SET linhas_expurgadas_em = now()
    WHERE id_lote IN (SELECT id_lote FROM lotes_expirados);
    DROP TABLE lotes_expirados;
END;
$$;
COMMENT ON FUNCTION bronze.aplicar_retencao(INTEGER) IS
    'Apaga as linhas brutas de lotes já tratados e mais antigos que N dias; mantém o registro do lote (hash).';
