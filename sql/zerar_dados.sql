-- =====================================================================
-- GDF - ZERAR DADOS  |  sql/zerar_dados.sql  v1.0
-- Apaga TODOS os dados do schema gdf: importacoes, linhas e conferencias, mapa de contas editado, apelidos,
-- relatorios gerados (e o registro de assinaturas), log de eventos e a empresa (assinantes padrao inclusos).
--
-- NAO apaga: o schema/tabelas, a role gdf_app, RLS/policies, nem os usuarios do Authentication (logins).
-- No proximo acesso o app recria sozinho a empresa Anastacio e o mapa de contas padrao (v1.0).
--
-- COMO RODAR (so' o Rafael): Supabase > SQL Editor > colar tudo > Run.  A role do app nao tem DELETE/TRUNCATE:
-- este script precisa rodar como postgres (e' o que o SQL Editor usa).  Tudo roda numa transacao so':
-- se qualquer passo falhar, nada e' apagado.
--
-- TRAVA: se existir relatorio com status ASSINADO o script PARA e nao apaga nada.  Para zerar mesmo assim,
-- tire os dois tracos da linha "SET LOCAL gdf.permitir_zerar_assinados" logo abaixo.
-- =====================================================================
BEGIN;

-- SET LOCAL gdf.permitir_zerar_assinados = 'sim';

-- 1. Foto de ANTES (conferir o que vai embora; aparece na aba Results se rodar so' esta parte)
SELECT 'ANTES' AS momento,
       (SELECT count(*) FROM gdf.empresa)          AS empresa,
       (SELECT count(*) FROM gdf.importacao)       AS importacao,
       (SELECT count(*) FROM gdf.balancete_linha)  AS balancete_linha,
       (SELECT count(*) FROM gdf.conferencia)      AS conferencia,
       (SELECT count(*) FROM gdf.mapa_conta)       AS mapa_conta,
       (SELECT count(*) FROM gdf.apelido)          AS apelido,
       (SELECT count(*) FROM gdf.relatorio)        AS relatorio,
       (SELECT count(*) FROM gdf.relatorio WHERE status = 'ASSINADO') AS relatorio_assinado,
       (SELECT count(*) FROM gdf.evento)           AS evento;

-- 2. Trava dos relatorios assinados
DO $$
DECLARE n integer;
BEGIN
  SELECT count(*) INTO n FROM gdf.relatorio WHERE status = 'ASSINADO';
  IF n > 0 AND coalesce(current_setting('gdf.permitir_zerar_assinados', true), '') <> 'sim' THEN
    RAISE EXCEPTION 'Ha % relatorio(s) ASSINADO. Nada foi apagado. Para zerar mesmo assim, ative a linha SET LOCAL gdf.permitir_zerar_assinados no topo do script.', n;
  END IF;
END
$$;

-- 3. Zerar (ordem irrelevante com CASCADE; RESTART IDENTITY recomeca os numeros em 1)
TRUNCATE TABLE gdf.conferencia, gdf.balancete_linha, gdf.importacao, gdf.mapa_conta, gdf.apelido,
               gdf.relatorio, gdf.evento, gdf.empresa
    RESTART IDENTITY CASCADE;

-- 4. Foto de DEPOIS (tudo deve estar 0)
SELECT 'DEPOIS' AS momento,
       (SELECT count(*) FROM gdf.empresa)          AS empresa,
       (SELECT count(*) FROM gdf.importacao)       AS importacao,
       (SELECT count(*) FROM gdf.balancete_linha)  AS balancete_linha,
       (SELECT count(*) FROM gdf.conferencia)      AS conferencia,
       (SELECT count(*) FROM gdf.mapa_conta)       AS mapa_conta,
       (SELECT count(*) FROM gdf.apelido)          AS apelido,
       (SELECT count(*) FROM gdf.relatorio)        AS relatorio,
       (SELECT count(*) FROM gdf.evento)           AS evento;

COMMIT;
