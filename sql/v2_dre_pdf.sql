-- GDF V2 - DRE oficial do Sienge lido do PDF ("DRE gerencial - composicao das contas"): valor por obra x linha do DRE x conta do plano.
-- Cada PDF importado vira uma linha em pnl_importacao (tipo 'DRE'); o antigo do mesmo mes fica ativo=false (nada e' apagado).
-- Guarda valores de dinheiro: a tabela fica no banco (nao no repositorio publico). Seguro rodar de novo.
ALTER TABLE gdf.pnl_importacao DROP CONSTRAINT IF EXISTS pnl_importacao_tipo_check;
ALTER TABLE gdf.pnl_importacao ADD CONSTRAINT pnl_importacao_tipo_check CHECK (tipo IN ('PROJECAO','FOLHA','HISTORICO','DRE'));

CREATE TABLE IF NOT EXISTS gdf.pnl_dre_valor (
    id             bigserial PRIMARY KEY,
    importacao_id  bigint NOT NULL REFERENCES gdf.pnl_importacao(id),
    obra_cod       text NOT NULL,               -- codigo da obra no painel (100, 103, 6003, 99986...)
    obra_nome      text,
    linha          text NOT NULL,               -- linha do DRE: 01, 01.01, 04.01 ...
    conta          text,                        -- conta do plano (NULL = linha de total do DRE)
    conta_nome     text,
    valor          numeric(18,2) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pnl_dre_valor_imp ON gdf.pnl_dre_valor (importacao_id, obra_cod);

GRANT SELECT, INSERT ON gdf.pnl_dre_valor TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.pnl_dre_valor_id_seq TO gdf_app;
ALTER TABLE gdf.pnl_dre_valor ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_dre_valor;
CREATE POLICY gdf_app_full_access ON gdf.pnl_dre_valor FOR ALL TO gdf_app USING (true) WITH CHECK (true);
