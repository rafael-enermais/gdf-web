-- SQL-41 (executado em producao em 29/10/2026 pelo Rafael) - fase 3 do Caixa x Referencia: cada arquivo enviado passa a guardar a base ('REF' = mes de referencia/competencia, 'CAIXA' = mes de caixa).
-- Pedido do Rafael (29/10/2026): "ja verifica tb no upload, pois teremos q configurar tb, e setar como mes referencia ou mes caixa".
-- So mexe no schema gdf. Nada e apagado: so' entram 2 colunas novas e as regras de unicidade passam a incluir a base
-- (o MESMO arquivo/mes pode existir uma vez como Referencia e uma vez como Caixa, cada um com o seu 'ativo').
-- Valores que ja existem ficam assim (conferir com a Suellen): importacoes antigas (DRE, projecao, orcamento, recibos, historico) = 'REF'; Flash antigo = 'CAIXA'.
-- ATENCAO: o app (v0.57.0 em diante) precisa destas colunas: o envio do Flash e dos recibos/projecao/orcamento grava a base. Rodar ANTES de subir o codigo.

-- 1) pnl_importacao: coluna base
ALTER TABLE gdf.pnl_importacao ADD COLUMN IF NOT EXISTS base text NOT NULL DEFAULT 'REF';
ALTER TABLE gdf.pnl_importacao DROP CONSTRAINT IF EXISTS pnl_importacao_base_check;
ALTER TABLE gdf.pnl_importacao ADD CONSTRAINT pnl_importacao_base_check CHECK (base IN ('REF','CAIXA'));

-- 2) pnl_importacao: unicidade por (tipo, arquivo, base) e uma ativa por (tipo, mes, escopo, base)
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT c.conname FROM pg_constraint c
            WHERE c.conrelid = 'gdf.pnl_importacao'::regclass AND c.contype = 'u'
              AND (SELECT array_agg(a.attname::text ORDER BY a.attname::text) FROM unnest(c.conkey) k JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k)
                  = ARRAY['arquivo_sha256','tipo']
  LOOP
    EXECUTE format('ALTER TABLE gdf.pnl_importacao DROP CONSTRAINT %I', r.conname);
  END LOOP;
END $$;
ALTER TABLE gdf.pnl_importacao DROP CONSTRAINT IF EXISTS pnl_importacao_tipo_sha_base_key;
ALTER TABLE gdf.pnl_importacao ADD CONSTRAINT pnl_importacao_tipo_sha_base_key UNIQUE (tipo, arquivo_sha256, base);
DROP INDEX IF EXISTS gdf.ux_pnl_importacao_ativa;
CREATE UNIQUE INDEX IF NOT EXISTS ux_pnl_importacao_ativa ON gdf.pnl_importacao (tipo, mes, escopo, base) WHERE ativo;

-- 3) pj_flash: coluna base e chave primaria com a base
ALTER TABLE gdf.pj_flash ADD COLUMN IF NOT EXISTS base text NOT NULL DEFAULT 'CAIXA';
ALTER TABLE gdf.pj_flash DROP CONSTRAINT IF EXISTS pj_flash_base_check;
ALTER TABLE gdf.pj_flash ADD CONSTRAINT pj_flash_base_check CHECK (base IN ('REF','CAIXA'));
ALTER TABLE gdf.pj_flash DROP CONSTRAINT IF EXISTS pj_flash_pkey;
ALTER TABLE gdf.pj_flash ADD PRIMARY KEY (mes, empresa, credor_id, base);

-- CONFERENCIA depois (so' SELECT):
--   select tipo, base, count(*) from gdf.pnl_importacao group by 1,2 order by 1,2;      -- tudo 'REF' (igual ao backup)
--   select mes, empresa, base, count(*) from gdf.pj_flash where ativo group by 1,2,3;    -- tudo 'CAIXA'
--   select count(*) from gdf.pnl_importacao; select count(*) from gdf.pnl_importacao_bak_20261029;   -- iguais
-- VOLTAR ATRAS (se precisar; so' possivel enquanto nao houver linhas CAIXA/REF duplicadas do mesmo arquivo/mes):
--   ALTER TABLE gdf.pnl_importacao DROP CONSTRAINT pnl_importacao_tipo_sha_base_key;
--   ALTER TABLE gdf.pnl_importacao ADD UNIQUE (tipo, arquivo_sha256);
--   DROP INDEX gdf.ux_pnl_importacao_ativa; CREATE UNIQUE INDEX ux_pnl_importacao_ativa ON gdf.pnl_importacao (tipo, mes, escopo) WHERE ativo;
--   ALTER TABLE gdf.pj_flash DROP CONSTRAINT pj_flash_pkey; ALTER TABLE gdf.pj_flash ADD PRIMARY KEY (mes, empresa, credor_id);
--   (as colunas 'base' podem ficar; nao atrapalham)
