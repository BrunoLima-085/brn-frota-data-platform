-- =====================================================================
-- 07_views.sql  |  Camada GOLD - views de consumo do dashboard
-- ---------------------------------------------------------------------
-- As views leem só a gold (e a silver, nos pontos de atenção, que
-- precisam do endereço). O dashboard nunca lê tabela: lê estas views
-- pelo pipeline/exportar_dashboard.py.
--
-- Data de referência: o último dia com telemetria carregada. Usar essa
-- data (e não current_date) deixa os números reproduzíveis: rodar de
-- novo amanhã sem dado novo dá o mesmo resultado.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Data de referência do painel
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_data_referencia AS
SELECT COALESCE(MAX(data), CURRENT_DATE) AS data_ref
FROM gold.fato_utilizacao;

-- ---------------------------------------------------------------------
-- Veículo com o centro de custo vigente na data de referência
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_veiculo_atual AS
SELECT v.id_veiculo,
       v.placa,
       v.marca,
       v.modelo,
       v.tipo,
       v.ano_fabricacao,
       v.possui_rastreador,
       v.status_veiculo,
       v.valor_fipe,
       v.ano_modelo,
       v.cor,
       v.chassi,
       v.filial,
       v.blindagem,
       a.id_centro_custo,
       cc.centro_custo,
       cc.cidade,
       cc.regional,
       a.contrato,
       a.operacao
FROM gold.dim_veiculo v
CROSS JOIN gold.vw_data_referencia r
LEFT JOIN LATERAL (
    -- alocação vigente; se não houver (veículo devolvido), a última
    SELECT al.*
    FROM gold.dim_alocacao al
    WHERE al.id_veiculo = v.id_veiculo
      AND al.data_inicio <= r.data_ref
    ORDER BY (al.data_fim IS NULL OR al.data_fim >= r.data_ref) DESC,
             al.data_inicio DESC
    LIMIT 1
) a ON TRUE
LEFT JOIN gold.dim_centro_custo cc ON cc.id_centro_custo = a.id_centro_custo;

-- ---------------------------------------------------------------------
-- Utilização: veículo x dia
-- O centro de custo é o da viagem (alocação vigente no dia), então a
-- troca de centro de custo no meio do período fica no lugar certo.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_utilizacao_diaria AS
SELECT u.id_veiculo,
       u.data,
       u.id_centro_custo,
       COUNT(*)                                   AS viagens,
       SUM(u.distancia_km)                        AS km,
       ROUND(SUM(u.duracao_min) / 60.0, 2)        AS horas_uso,
       ROUND(SUM(u.motor_ocioso_min) / 60.0, 2)   AS horas_ocioso,
       SUM(u.consumo_l)                           AS consumo_l,
       MAX(u.vel_maxima)                          AS vel_maxima,
       SUM(u.qtd_frenagem)                        AS frenagens
FROM gold.fato_utilizacao u
GROUP BY u.id_veiculo, u.data, u.id_centro_custo;

-- ---------------------------------------------------------------------
-- Ociosidade da frota: dias sem nenhuma viagem por veículo com
-- rastreador, dentro do período em que estava alocado.
-- generate_series monta o calendário; o LEFT JOIN acha os buracos.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_dias_sem_uso AS
WITH periodo AS (
    SELECT MIN(data) AS ini, MAX(data) AS fim FROM gold.fato_utilizacao
),
calendario AS (
    SELECT v.id_veiculo, d::date AS data
    FROM gold.dim_veiculo v
    CROSS JOIN periodo p
    CROSS JOIN generate_series(p.ini, p.fim, interval '1 day') d
    WHERE v.possui_rastreador
),
uso AS (
    SELECT DISTINCT id_veiculo, data FROM gold.fato_utilizacao
)
SELECT c.id_veiculo,
       c.data,
       a.id_centro_custo
FROM calendario c
JOIN gold.dim_alocacao a
  ON a.id_veiculo = c.id_veiculo
 AND c.data >= a.data_inicio
 AND (a.data_fim IS NULL OR c.data <= a.data_fim)
LEFT JOIN uso u ON u.id_veiculo = c.id_veiculo AND u.data = c.data
WHERE u.id_veiculo IS NULL;

-- ---------------------------------------------------------------------
-- Alertas: veículo x dia x hora x regra
-- Base do mapa de calor (dia da semana x hora) e das séries diárias.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_alertas_hora AS
SELECT a.id_veiculo,
       a.data,
       EXTRACT(HOUR FROM a.data_hora_evento)::smallint            AS hora,
       a.id_centro_custo,
       a.nome_regra,
       COUNT(*)                                                    AS qtd,
       MAX(a.valor_metrica) FILTER (WHERE a.nome_regra = 'Excesso de velocidade')
                                                                   AS vel_maxima,
       ROUND(SUM(a.duracao_min) FILTER (WHERE a.nome_regra = 'Motor ocioso'), 1)
                                                                   AS ocioso_min
FROM gold.fato_alertas a
GROUP BY a.id_veiculo, a.data, 3, a.id_centro_custo, a.nome_regra;

-- ---------------------------------------------------------------------
-- Pontos de atenção: trechos (rua + bairro + cidade, sem o número)
-- que mais concentram excesso de velocidade e motor ocioso.
-- O endereço só existe na silver; o regex tira o número da via.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_pontos_atencao AS
WITH base AS (
    SELECT s.nome_regra,
           regexp_replace(s.local_inicio, ',\s*\d+\s*,', ',')   AS trecho,
           s.valor_metrica,
           s.duracao_min,
           s.placa,
           s.data_hora_evento::date                              AS data
    FROM silver.alertas s
    WHERE s.nome_regra IN ('Excesso de velocidade', 'Motor ocioso')
      AND s.local_inicio IS NOT NULL
)
SELECT nome_regra,
       trecho,
       split_part(trecho, ', ', 3)                    AS cidade,
       COUNT(*)                                       AS ocorrencias,
       COUNT(DISTINCT placa)                          AS veiculos,
       MAX(valor_metrica) FILTER (WHERE nome_regra = 'Excesso de velocidade')
                                                      AS vel_maxima,
       ROUND(SUM(duracao_min) FILTER (WHERE nome_regra = 'Motor ocioso'), 0)
                                                      AS ocioso_min,
       MIN(data)                                      AS primeira,
       MAX(data)                                      AS ultima
FROM base
GROUP BY nome_regra, trecho;

-- ---------------------------------------------------------------------
-- Ordens de serviço com situação e custo do veículo parado
--   dias_parado        : da entrada na oficina até a saída (ou até hoje)
--   atrasada           : passou da previsão de saída e não saiu
--   reincidente        : mesmo veículo e mesmo sistema em até 90 dias (LAG)
--   dias_locacao       : dias com veículo substituto (= dias parado)
--   custo_locacao      : diária x dias, ou o valor fixo do período
--   custo_total_parado : negociado + peças + locação
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_os_situacao AS
WITH os AS (
    SELECT m.*,
           LAG(m.data_os) OVER (PARTITION BY m.id_veiculo, m.tipo_sistema
                                ORDER BY m.data_os, m.numero_os) AS os_anterior_data
    FROM gold.fato_manutencao m
),
calc AS (
    SELECT os.*,
           r.data_ref,
           (COALESCE(os.data_real_saida, r.data_ref) - os.data_entrada_oficina) AS dias_parado
    FROM os
    CROSS JOIN gold.vw_data_referencia r
),
locacao AS (
    SELECT c.*,
           CASE WHEN c.veiculo_substituto THEN c.dias_parado END AS dias_locacao,
           CASE WHEN NOT c.veiculo_substituto THEN 0
                WHEN c.tipo_aluguel = 'Período' THEN c.valor_aluguel
                ELSE c.valor_aluguel * COALESCE(c.dias_parado, 0) END AS custo_locacao
    FROM calc c
)
SELECT l.numero_os,
       l.id_veiculo,
       v.placa,
       v.modelo,
       v.tipo,
       l.id_centro_custo,
       l.contrato,
       l.data_os,
       l.oficina,
       l.tipo_manutencao,
       l.criticidade,
       l.tipo_sistema,
       l.descricao_problema,
       l.status_manutencao,
       l.status_operacional,
       l.etapa_atual,
       l.data_entrada_oficina,
       l.data_prevista_saida,
       l.data_real_saida,
       l.valor_orcamento,
       l.valor_negociado,
       l.pct_variacao,
       l.desconto_obtido,
       l.n_requisicao_pecas,
       l.valor_pecas,
       l.veiculo_substituto,
       l.placa_substituto,
       l.tipo_aluguel,
       l.valor_aluguel,
       l.dias_os_entrada,
       l.dias_entrada_orcamento,
       l.dias_orcamento_solicitacao,
       l.dias_solicitacao_aprovacao,
       l.dias_aprovacao_pedido,
       l.dias_pedido_compra,
       l.dias_compra_entrega,
       l.dias_entrada_saida,
       l.dias_parado,
       l.dias_locacao,
       ROUND(l.custo_locacao, 2)                                              AS custo_locacao,
       ROUND(COALESCE(l.valor_negociado, 0) + COALESCE(l.valor_pecas, 0)
             + COALESCE(l.custo_locacao, 0), 2)                               AS custo_total_parado,
       (l.data_real_saida IS NULL AND l.data_prevista_saida < l.data_ref)     AS atrasada,
       (l.os_anterior_data IS NOT NULL
        AND l.data_os - l.os_anterior_data <= 90
        AND l.tipo_manutencao <> 'Preventiva')                                AS reincidente
FROM locacao l
JOIN gold.dim_veiculo v ON v.id_veiculo = l.id_veiculo;

-- ---------------------------------------------------------------------
-- SLA por etapa (as 8 etapas da planilha de acompanhamento):
-- média, mediana, p90 e % dentro da meta. As metas ficam num VALUES,
-- à vista de quem lê o SQL. Só entram OS com as duas datas da etapa.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_sla_etapas AS
WITH metas(ordem, etapa, coluna, meta_dias) AS (
    VALUES (1, 'OS → Entrada na oficina',              'dias_os_entrada',            2),
           (2, 'Entrada → Orçamento',                  'dias_entrada_orcamento',     2),
           (3, 'Orçamento → Solicitação de aprovação', 'dias_orcamento_solicitacao', 1),
           (4, 'Solicitação → Aprovação',              'dias_solicitacao_aprovacao', 2),
           (5, 'Aprovação → Pedido de compra',         'dias_aprovacao_pedido',      1),
           (6, 'Pedido → Compra efetivada',            'dias_pedido_compra',         2),
           (7, 'Compra → Entrega da peça',             'dias_compra_entrega',        4),
           (8, 'Entrada → Saída da oficina',           'dias_entrada_saida',         10)
),
valores AS (
    SELECT m.ordem, m.etapa, m.meta_dias,
           CASE m.coluna
               WHEN 'dias_os_entrada'            THEN f.dias_os_entrada
               WHEN 'dias_entrada_orcamento'     THEN f.dias_entrada_orcamento
               WHEN 'dias_orcamento_solicitacao' THEN f.dias_orcamento_solicitacao
               WHEN 'dias_solicitacao_aprovacao' THEN f.dias_solicitacao_aprovacao
               WHEN 'dias_aprovacao_pedido'      THEN f.dias_aprovacao_pedido
               WHEN 'dias_pedido_compra'         THEN f.dias_pedido_compra
               WHEN 'dias_compra_entrega'        THEN f.dias_compra_entrega
               WHEN 'dias_entrada_saida'         THEN f.dias_entrada_saida
           END AS dias
    FROM metas m
    CROSS JOIN gold.fato_manutencao f
)
SELECT ordem,
       etapa,
       meta_dias,
       COUNT(dias)                                                     AS os_medidas,
       ROUND(AVG(dias), 1)                                             AS media_dias,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dias)               AS mediana_dias,
       PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY dias)               AS p90_dias,
       ROUND(100.0 * COUNT(*) FILTER (WHERE dias <= meta_dias)
             / NULLIF(COUNT(dias), 0), 1)                              AS pct_na_meta
FROM valores
GROUP BY ordem, etapa, meta_dias;

-- ---------------------------------------------------------------------
-- Condução x manutenção, por veículo
-- Alertas de condução brusca a cada 100 km contra corretivas e custo.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_conducao_x_manutencao AS
WITH km AS (
    SELECT id_veiculo, SUM(distancia_km) AS km
    FROM gold.fato_utilizacao GROUP BY id_veiculo
),
alertas AS (
    SELECT id_veiculo, COUNT(*) AS bruscos
    FROM gold.fato_alertas
    WHERE nome_regra IN ('Freada brusca', 'Aceleração brusca', 'Curva brusca')
    GROUP BY id_veiculo
),
manut AS (
    SELECT id_veiculo,
           COUNT(*) FILTER (WHERE tipo_manutencao = 'Corretiva')                  AS corretivas,
           COALESCE(SUM(valor_negociado) FILTER (WHERE tipo_manutencao = 'Corretiva'), 0)
                                                                                  AS custo_corretivo,
           COALESCE(SUM(valor_negociado), 0)                                      AS custo_total
    FROM gold.fato_manutencao GROUP BY id_veiculo
)
SELECT v.id_veiculo,
       v.placa,
       v.tipo,
       ROUND(k.km, 0)                                         AS km,
       COALESCE(a.bruscos, 0)                                 AS alertas_bruscos,
       ROUND(100.0 * COALESCE(a.bruscos, 0) / NULLIF(k.km, 0), 2) AS bruscos_100km,
       COALESCE(m.corretivas, 0)                              AS corretivas,
       COALESCE(m.custo_corretivo, 0)                         AS custo_corretivo,
       COALESCE(m.custo_total, 0)                             AS custo_total
FROM gold.dim_veiculo v
JOIN km k ON k.id_veiculo = v.id_veiculo
LEFT JOIN alertas a ON a.id_veiculo = v.id_veiculo
LEFT JOIN manut m   ON m.id_veiculo = v.id_veiculo
WHERE k.km >= 500;          -- sem rodagem mínima a taxa por km não diz nada

-- Correlação de Pearson entre a taxa de alertas e a manutenção
CREATE OR REPLACE VIEW gold.vw_correlacao AS
SELECT COUNT(*)                                                   AS veiculos,
       ROUND(CORR(bruscos_100km, corretivas)::numeric, 3)         AS corr_alertas_corretivas,
       ROUND(CORR(bruscos_100km, custo_corretivo)::numeric, 3)    AS corr_alertas_custo
FROM gold.vw_conducao_x_manutencao;

-- ---------------------------------------------------------------------
-- Faixas de condução: cada veículo numa faixa pela taxa de alertas bruscos
-- a cada 100 km. O dashboard compara o custo corretivo médio das faixas.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_conducao_faixas AS
SELECT c.*,
       CASE WHEN c.bruscos_100km < 1.5 THEN 1
            WHEN c.bruscos_100km < 2.5 THEN 2
            WHEN c.bruscos_100km < 4.0 THEN 3
            ELSE 4 END                                          AS ordem_faixa,
       CASE WHEN c.bruscos_100km < 1.5 THEN 'Suave'
            WHEN c.bruscos_100km < 2.5 THEN 'Moderada'
            WHEN c.bruscos_100km < 4.0 THEN 'Brusca'
            ELSE 'Agressiva' END                                AS faixa
FROM gold.vw_conducao_x_manutencao c;

-- ---------------------------------------------------------------------
-- Última manutenção concluída de cada veículo e há quantos dias foi.
-- DISTINCT ON pega a mais recente sem subconsulta correlacionada.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_ultima_manutencao AS
SELECT DISTINCT ON (v.id_veiculo)
       v.id_veiculo,
       v.placa,
       m.numero_os,
       m.tipo_manutencao,
       m.tipo_sistema,
       m.data_real_saida                       AS data_ultima,
       r.data_ref - m.data_real_saida          AS dias_desde
FROM gold.dim_veiculo v
CROSS JOIN gold.vw_data_referencia r
LEFT JOIN gold.fato_manutencao m
       ON m.id_veiculo = v.id_veiculo AND m.data_real_saida IS NOT NULL
ORDER BY v.id_veiculo, m.data_real_saida DESC NULLS LAST, m.numero_os DESC;

-- ---------------------------------------------------------------------
-- Leitura: as views herdam o RLS das tabelas quando chamadas por um
-- papel sem bypass. O pipeline conecta como dono do banco, então não
-- precisa de policy. security_invoker deixa isso explícito.
-- ---------------------------------------------------------------------
DO $$
DECLARE v text;
BEGIN
    FOR v IN SELECT viewname FROM pg_views WHERE schemaname = 'gold' AND viewname LIKE 'vw\_%'
    LOOP
        EXECUTE format('ALTER VIEW gold.%I SET (security_invoker = true)', v);
    END LOOP;
END $$;
