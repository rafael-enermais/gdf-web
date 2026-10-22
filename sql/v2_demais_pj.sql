-- GDF V2 (SQL-37) - Novo grupo "Demais colaboradores-PJ" no de-para de credores (aba Pessoas, lista "PJ do mes").
-- So a ESTRUTURA (sem nomes): amplia o CHECK de gdf.pnl_credor_grupo.grupo para aceitar 'DEMAIS_PJ' alem de 'OUTROS_DIR'.
-- Os nomes entram pela propria tela (Importacoes V2 > credores) ou pelo SQL-38 (arquivo do vault, fora do repositorio publico).
-- Seguro rodar de novo. Nada e apagado.
ALTER TABLE gdf.pnl_credor_grupo DROP CONSTRAINT IF EXISTS pnl_credor_grupo_grupo_check;
ALTER TABLE gdf.pnl_credor_grupo ADD CONSTRAINT pnl_credor_grupo_grupo_check CHECK (grupo IN ('OUTROS_DIR', 'DEMAIS_PJ'));
