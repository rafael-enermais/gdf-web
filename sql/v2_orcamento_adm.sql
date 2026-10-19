-- GDF V2 (SQL-18) - Orcamento ADM (Sienge, "Comparativo Orcado X Realizado Agrupado") lido do PDF: orcado, realizado e saldo por conta e por mes.
-- Cada PDF importado vira uma linha em pnl_importacao (tipo 'ORCAMENTO', mes = 1o mes do periodo); o antigo do mesmo inicio fica ativo=false.
-- Guarda valores de dinheiro: a tabela fica no banco (nao no repositorio publico). Seguro rodar de novo. So acrescenta.
ALTER TABLE gdf.pnl_importacao DROP CONSTRAINT IF EXISTS pnl_importacao_tipo_check;
ALTER TABLE gdf.pnl_importacao ADD CONSTRAINT pnl_importacao_tipo_check CHECK (tipo IN ('PROJECAO','FOLHA','HISTORICO','DRE','ORCAMENTO'));

CREATE TABLE IF NOT EXISTS gdf.pnl_orcamento_linha (
    id              bigserial PRIMARY KEY,
    importacao_id   bigint NOT NULL REFERENCES gdf.pnl_importacao(id),
    codigo          text NOT NULL,                        -- 2.02.01.01
    conta           text,
    tipo            text,                                 -- T total, R conta, M conta (canteiros)
    mes             date NOT NULL,                        -- 1o dia da competencia
    orcado          numeric(18,2),
    realizado       numeric(18,2),
    saldo           numeric(18,2)
);
CREATE INDEX IF NOT EXISTS ix_pnl_orcamento_imp ON gdf.pnl_orcamento_linha (importacao_id, mes);

GRANT SELECT, INSERT ON gdf.pnl_orcamento_linha TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.pnl_orcamento_linha_id_seq TO gdf_app;
ALTER TABLE gdf.pnl_orcamento_linha ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_orcamento_linha;
CREATE POLICY gdf_app_full_access ON gdf.pnl_orcamento_linha FOR ALL TO gdf_app USING (true) WITH CHECK (true);
