-- GDF V2 (SQL-30) - Credores do cadastro do Sienge: so' o NOME e o NOME FANTASIA (para mostrar o fantasia dos colaboradores PJ no Painel da Diretoria, pedido da contabilidade 21/10/2026).
-- Nao guarda CPF/CNPJ nem o registro bruto (dado pessoal desnecessario). Os dados entram pelo botao "Atualizar cadastros" do Painel EnerMais.
-- Fica no schema gdf (o banco e' compartilhado com EGC e Radar Comercial: nada fora de gdf e' tocado). So' acrescenta; seguro rodar de novo.
CREATE TABLE IF NOT EXISTS gdf.pnl_credor_sienge (
    id              bigint PRIMARY KEY,          -- id do credor no Sienge
    nome            text NOT NULL,               -- razao social (como aparece nos titulos)
    nome_fantasia   text,                        -- nome fantasia do cadastro (pode vir vazio)
    atualizado_em   timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON gdf.pnl_credor_sienge TO gdf_app;
ALTER TABLE gdf.pnl_credor_sienge ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_credor_sienge;
CREATE POLICY gdf_app_full_access ON gdf.pnl_credor_sienge FOR ALL TO gdf_app USING (true) WITH CHECK (true);
