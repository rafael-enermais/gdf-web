-- GDF V2 (SQL-27): VENCIMENTO ORIGINAL do titulo. O Sienge NAO entrega o vencimento original por API (so' o atual), entao o app guarda o PRIMEIRO
-- vencimento que viu de cada titulo e nunca o sobrescreve: se o titulo for prorrogado depois, a inadimplencia continua contando pelo original.
-- Titulos ja gravados recebem o vencimento atual como "primeiro visto" (limite: prorrogacoes anteriores a primeira carga nao sao recuperaveis).
-- Aditivo: cria 1 coluna e preenche; nada e' apagado. Seguro rodar de novo.
ALTER TABLE gdf.pnl_titulo ADD COLUMN IF NOT EXISTS data_vencimento_original date;
COMMENT ON COLUMN gdf.pnl_titulo.data_vencimento_original IS 'primeiro data_vencimento visto pelo app (nunca sobrescrito); NULL = ainda nao gravado';
UPDATE gdf.pnl_titulo SET data_vencimento_original = data_vencimento WHERE data_vencimento_original IS NULL;
