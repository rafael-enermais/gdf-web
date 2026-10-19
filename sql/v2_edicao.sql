-- GDF V2 (SQL-19) - Edicao dos dados importados + historico de edicoes (aba "Importacoes (V2)").
-- Nada e' apagado: editar troca o valor e guarda o ANTES e o DEPOIS em pnl_edicao (quem, quando, motivo). Reverter uma importacao = marcar ativo=false.
-- O papel gdf_app continua SEM DELETE. Seguro rodar de novo. So acrescenta.
CREATE TABLE IF NOT EXISTS gdf.pnl_edicao (
    id              bigserial PRIMARY KEY,
    importacao_id   bigint REFERENCES gdf.pnl_importacao(id),   -- NULL = edicao de cadastro (ex.: de-para departamento -> obra)
    tabela          text NOT NULL,
    linha_id        bigint,
    campo           text NOT NULL,                              -- '*' = linha nova (valores em valor_depois)
    valor_antes     text,
    valor_depois    text,
    acao            text NOT NULL DEFAULT 'EDITOU' CHECK (acao IN ('EDITOU','ADICIONOU','DESATIVOU','REATIVOU','CADASTRO')),
    motivo          text,
    quem            text,
    quando          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pnl_edicao_imp ON gdf.pnl_edicao (importacao_id, quando DESC);

GRANT SELECT, INSERT ON gdf.pnl_edicao TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.pnl_edicao_id_seq TO gdf_app;
GRANT UPDATE ON gdf.pnl_folha_recibo, gdf.pnl_projecao_linha, gdf.pnl_orcamento_linha, gdf.pnl_dre_valor TO gdf_app;
GRANT UPDATE ON gdf.pnl_importacao TO gdf_app;
ALTER TABLE gdf.pnl_edicao ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_edicao;
CREATE POLICY gdf_app_full_access ON gdf.pnl_edicao FOR ALL TO gdf_app USING (true) WITH CHECK (true);
