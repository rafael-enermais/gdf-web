-- GDF V2 (SQL-21) - Historico do ano vindo do painel da contabilidade (artifact/HTML): acumulado jan-set, desvio mensal, recomposicao out-dez,
-- horas extras mes a mes e custos com pessoas. Cada upload vira uma linha em pnl_importacao (tipo 'HISTORICO'; a anterior do mesmo mes fica ativo=false)
-- e UMA linha aqui com os numeros (jsonb). O repositorio e' publico: os dados ficam so' no banco. Seguro rodar de novo. So acrescenta.
CREATE TABLE IF NOT EXISTS gdf.pnl_historico_painel (
    id            bigserial PRIMARY KEY,
    importacao_id bigint NOT NULL REFERENCES gdf.pnl_importacao(id),
    dados         jsonb NOT NULL,
    criado_em     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pnl_historico_painel_imp ON gdf.pnl_historico_painel (importacao_id);
GRANT SELECT, INSERT ON gdf.pnl_historico_painel TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.pnl_historico_painel_id_seq TO gdf_app;
ALTER TABLE gdf.pnl_historico_painel ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_historico_painel;
CREATE POLICY gdf_app_full_access ON gdf.pnl_historico_painel FOR ALL TO gdf_app USING (true) WITH CHECK (true);
