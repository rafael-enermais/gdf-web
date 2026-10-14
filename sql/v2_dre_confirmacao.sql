-- SQL-10 | GDF V2 - confirmacao do DRE do mes: para cada linha do DRE, qual FONTE (API do Sienge ou PDF do Sienge) a Suellen/Rafael adotou.
-- Cada confirmacao nova do mesmo mes desativa a anterior (ativo=false); nada e' apagado. Seguro rodar de novo.
CREATE TABLE IF NOT EXISTS gdf.pnl_dre_confirmacao (
    id                 bigserial PRIMARY KEY,
    mes                date NOT NULL,                         -- 1o dia da competencia
    ativo              boolean NOT NULL DEFAULT true,
    confirmado_por     text,
    confirmado_em      timestamptz NOT NULL DEFAULT now(),
    observacao         text,
    fontes             jsonb NOT NULL,                        -- {"01.01": "PDF", "04.01": "API", ...}
    valores            jsonb NOT NULL,                        -- {"01.01": 9291981.70, ...} valor adotado por linha
    resumo             jsonb NOT NULL DEFAULT '{}'::jsonb,    -- lucro liquido na API, no PDF e o adotado
    dre_importacao_id  bigint REFERENCES gdf.pnl_importacao(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pnl_dre_confirmacao_ativa ON gdf.pnl_dre_confirmacao (mes) WHERE ativo;

GRANT SELECT, INSERT, UPDATE ON gdf.pnl_dre_confirmacao TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.pnl_dre_confirmacao_id_seq TO gdf_app;
ALTER TABLE gdf.pnl_dre_confirmacao ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_dre_confirmacao;
CREATE POLICY gdf_app_full_access ON gdf.pnl_dre_confirmacao FOR ALL TO gdf_app USING (true) WITH CHECK (true);
