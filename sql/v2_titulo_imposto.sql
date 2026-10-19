-- GDF V2 (SQL-13) - Imposto do TITULO de receita (campo taxAmount do titulo na API do Sienge): base da linha 02.02 "Impostos sobre o Faturamento" do DRE.
-- Descoberto pelo diagnostico dos impostos (19/10/2026): o titulo de NFS traz taxAmount = ISS/PIS/COFINS da nota (~7,9% do valor); as baixas e o rateio nao trazem.
-- So adiciona uma coluna (nullable); nada e apagado. Seguro rodar de novo. Depois de rodar, a rotina diaria preenche a coluna; para preencher os meses antigos,
-- rodar Actions > Ingest Sienge GDF com o campo "meses" (ex.: 2026-09).
ALTER TABLE gdf.pnl_titulo ADD COLUMN IF NOT EXISTS imposto_titulo numeric(18,2);
COMMENT ON COLUMN gdf.pnl_titulo.imposto_titulo IS 'taxAmount do titulo de receita (impostos da NF); NULL = ainda nao sincronizado ou lado pagar';
