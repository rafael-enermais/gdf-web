-- GDF V2 (SQL-29) - CONFIGURACOES do painel (chave/valor). Hoje: 'investimentos_visualizador' = 'sim' libera a aba Investimentos para o login de
-- visualizacao do Painel da Diretoria (padrao: nao). Quem e' EDITOR sempre ve a aba. So' a ESTRUTURA; nada e' apagado. Seguro rodar de novo.
CREATE TABLE IF NOT EXISTS gdf.pnl_config (
    chave         text PRIMARY KEY,
    valor         text,
    alterado_por  text,
    alterado_em   timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON gdf.pnl_config TO gdf_app;
ALTER TABLE gdf.pnl_config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_config;
CREATE POLICY gdf_app_full_access ON gdf.pnl_config FOR ALL TO gdf_app USING (true) WITH CHECK (true);
