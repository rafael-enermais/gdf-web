-- GDF V2 - Historico e logs (conferencias, erros, acoes). Rodar UMA vez no Supabase (SQL Editor). Seguro rodar de novo.
-- Guarda so contagens, totais, nomes de arquivo e codigos de verificacao (hash). Nenhum dado de pessoa. Ninguem apaga (sem DELETE).
CREATE TABLE IF NOT EXISTS gdf.pnl_log (
    id       bigserial PRIMARY KEY,
    quando   timestamptz NOT NULL DEFAULT now(),
    usuario  text,
    nivel    text NOT NULL DEFAULT 'INFO' CHECK (nivel IN ('INFO','AVISO','ERRO')),
    acao     text NOT NULL,            -- CONFERENCIA_DESPESAS, SYNC_OK, SYNC_ERRO, REGRA_CONFIRMADA, ROTINA_ERRO ...
    mes      date,                     -- mes de competencia ligado ao evento (1o dia)
    detalhe  jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_pnl_log_quando ON gdf.pnl_log (quando DESC);
CREATE INDEX IF NOT EXISTS ix_pnl_log_acao ON gdf.pnl_log (acao, quando DESC);

GRANT SELECT, INSERT ON gdf.pnl_log TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.pnl_log_id_seq TO gdf_app;
ALTER TABLE gdf.pnl_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_log;
CREATE POLICY gdf_app_full_access ON gdf.pnl_log FOR ALL TO gdf_app USING (true) WITH CHECK (true);
