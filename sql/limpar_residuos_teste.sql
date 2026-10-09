-- =====================================================================
-- GDF - LIMPAR RESIDUOS DO TESTE AO VIVO (09/10/2026)  |  sql/limpar_residuos_teste.sql  v1.0
-- Apaga SO' o que sobrou do teste ao vivo:
--   * relatorios 08/2026 versoes v3 e v4 (RASCUNHO)                       -> 2 linhas
--   * importacoes #10 (balancete_08_2026_TESTE.csv) e #11 (PDF acumulado) -> 2 importacoes + suas linhas e conferencias
-- E devolve a #1 (CSV original acumulado) ao estado de antes do teste: ATIVA e REVISADA.
-- NAO mexe: nas importacoes mensais (#2 a #9), nos relatorios v1 e v2 (REVISADO), no mapa, nos apelidos, no log de eventos
-- (o log guarda uma linha dizendo que a limpeza foi feita).
--
-- COMO RODAR (so' o Rafael): Supabase > SQL Editor > colar tudo > Run.  A role do app nao tem DELETE; o SQL Editor roda como postgres.
-- Numa transacao so': se qualquer conferencia abaixo nao bater, para com erro e NAO apaga nada.
-- Se o sistema tiver mudado e os numeros (#10, #11, v3, v4) nao forem mais os mesmos, o script recusa em vez de apagar o errado.
-- =====================================================================
BEGIN;

SELECT 'ANTES' AS momento,
       (SELECT count(*) FROM gdf.importacao)      AS importacao,
       (SELECT count(*) FROM gdf.balancete_linha) AS balancete_linha,
       (SELECT count(*) FROM gdf.conferencia)     AS conferencia,
       (SELECT count(*) FROM gdf.relatorio)       AS relatorio;

DO $$
DECLARE
  n_imp integer; n_rel integer; n_um integer;
BEGIN
  -- so' apaga se for exatamente o que esperamos
  SELECT count(*) INTO n_imp FROM gdf.importacao
   WHERE id IN (10, 11) AND tipo = 'ACUMULADO' AND periodo_fim = DATE '2026-08-31'
     AND (arquivo_nome = 'balancete_08_2026_TESTE.csv' OR arquivo_nome LIKE '01 a 08.2026%');
  SELECT count(*) INTO n_rel FROM gdf.relatorio
   WHERE periodo = DATE '2026-08-01' AND versao IN (3, 4) AND status = 'RASCUNHO';
  SELECT count(*) INTO n_um FROM gdf.importacao
   WHERE id = 1 AND tipo = 'ACUMULADO' AND periodo_fim = DATE '2026-08-31' AND arquivo_nome LIKE 'Relatorios_Contabeis%';
  IF n_imp <> 2 THEN RAISE EXCEPTION 'Esperava as importacoes #10 e #11 (acumulados de teste de 08/2026), achei %. Nada foi apagado.', n_imp; END IF;
  IF n_rel <> 2 THEN RAISE EXCEPTION 'Esperava os relatorios v3 e v4 de 08/2026 como RASCUNHO, achei %. Nada foi apagado.', n_rel; END IF;
  IF n_um <> 1 THEN RAISE EXCEPTION 'A importacao #1 (CSV original) nao esta como esperado. Nada foi apagado.'; END IF;
END
$$;

-- 1. relatorios de teste
DELETE FROM gdf.relatorio
 WHERE periodo = DATE '2026-08-01' AND versao IN (3, 4) AND status = 'RASCUNHO';

-- 2. importacoes de teste (filhos primeiro)
DELETE FROM gdf.conferencia     WHERE importacao_id IN (10, 11);
DELETE FROM gdf.balancete_linha WHERE importacao_id IN (10, 11);
DELETE FROM gdf.importacao      WHERE id IN (10, 11);

-- 3. devolve a #1 ao estado de antes do teste (so' se nao houver outro acumulado ativo no periodo)
UPDATE gdf.importacao SET ativo = true, status = 'REVISADA'
 WHERE id = 1
   AND NOT EXISTS (SELECT 1 FROM gdf.importacao o
                    WHERE o.empresa_id = gdf.importacao.empresa_id AND o.tipo = 'ACUMULADO'
                      AND o.periodo_ini = gdf.importacao.periodo_ini AND o.periodo_fim = gdf.importacao.periodo_fim AND o.ativo AND o.id <> 1);

-- 4. rastro no log
INSERT INTO gdf.evento (empresa_id, origem, nivel, mensagem, usuario)
SELECT empresa_id, 'historico', 'info',
       'Residuos do teste ao vivo removidos por SQL: importacoes #10 e #11, relatorios v3 e v4 de 08/2026; importacao #1 reativada', 'rafael (SQL Editor)'
  FROM gdf.importacao WHERE id = 1;

SELECT 'DEPOIS' AS momento,
       (SELECT count(*) FROM gdf.importacao)      AS importacao,
       (SELECT count(*) FROM gdf.balancete_linha) AS balancete_linha,
       (SELECT count(*) FROM gdf.conferencia)     AS conferencia,
       (SELECT count(*) FROM gdf.relatorio)       AS relatorio,
       (SELECT ativo FROM gdf.importacao WHERE id = 1)  AS importacao_1_ativa,
       (SELECT status FROM gdf.importacao WHERE id = 1) AS importacao_1_status;

COMMIT;
