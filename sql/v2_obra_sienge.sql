-- GDF V2 (SQL-24) - Obras (empreendimentos) do cadastro do Sienge, para completar o NOME das obras no painel. So a ESTRUTURA (sem dados; os dados vem pelo botao
-- "Atualizar cadastros" do Painel EnerMais). Fica no schema gdf (o banco e' compartilhado com EGC e Radar Comercial: nada fora de gdf e' tocado). So acrescenta; seguro rodar de novo.
CREATE TABLE IF NOT EXISTS gdf.pnl_obra_sienge (
    id              bigint PRIMARY KEY,          -- id da obra (enterprise) no Sienge
    nome            text,
    nome_comercial  text,
    empresa_id      bigint,
    codigo          text,                        -- codigo/sigla da obra no Sienge, se o cadastro trouxer
    bruto           jsonb,                       -- registro como o Sienge devolveu (para conferir o de-para sem chamar a API de novo)
    atualizado_em   timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON gdf.pnl_obra_sienge TO gdf_app;
ALTER TABLE gdf.pnl_obra_sienge ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_obra_sienge;
CREATE POLICY gdf_app_full_access ON gdf.pnl_obra_sienge FOR ALL TO gdf_app USING (true) WITH CHECK (true);
