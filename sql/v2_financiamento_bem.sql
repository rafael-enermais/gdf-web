-- GDF V2 (SQL-26) - De-para dos FINANCIAMENTOS: o que cada contrato financia (maquina, veiculo, imovel, capital de giro...).
-- O painel sugere sozinho (pelo nome do plano de contas); aqui a contabilidade/Rafael corrigem. So' a ESTRUTURA (sem nomes/valores).
-- Seguro rodar de novo. Nada e' apagado: "limpar" = ativo = false (a linha fica no historico).
CREATE TABLE IF NOT EXISTS gdf.pnl_financiamento_bem (
    chave         text PRIMARY KEY,                  -- numero do contrato (como o painel mostra na tabela de contratos)
    categoria     text,                              -- NULL = usa a sugestao automatica
    objeto        text,                              -- texto livre: ex. "Retroescavadeira", "Frota de caminhonetes"
    observacao    text,
    taxa_mensal   numeric(7,4),                      -- taxa de juros do contrato em % ao mes (ex.: 1,85); NULL = usa a taxa implicita
    ativo         boolean NOT NULL DEFAULT true,
    alterado_por  text,
    alterado_em   timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE gdf.pnl_financiamento_bem ADD COLUMN IF NOT EXISTS taxa_mensal numeric(7,4);
GRANT SELECT, INSERT, UPDATE ON gdf.pnl_financiamento_bem TO gdf_app;
ALTER TABLE gdf.pnl_financiamento_bem ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_financiamento_bem;
CREATE POLICY gdf_app_full_access ON gdf.pnl_financiamento_bem FOR ALL TO gdf_app USING (true) WITH CHECK (true);
