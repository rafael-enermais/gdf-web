-- SQL-25 (GDF): data-base da parcela (installmentBaseDate do Sienge) em cada titulo. Candidata a "vencimento original" para a inadimplencia.
-- Aditivo e seguro: so' cria uma coluna vazia no schema gdf (nada e' apagado ou alterado). O app funciona com ou sem ela.
ALTER TABLE gdf.pnl_titulo ADD COLUMN IF NOT EXISTS data_base_parcela date;
COMMENT ON COLUMN gdf.pnl_titulo.data_base_parcela IS 'installmentBaseDate do Sienge (data-base da parcela); NULL = ainda nao sincronizado';
