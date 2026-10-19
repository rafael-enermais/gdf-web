-- GDF V2 (SQL-11) - De-para credor -> grupo "Outros credores/Dir" da aba Administracao. So a ESTRUTURA (sem nomes).
-- Os nomes (credores que a contabilidade manda tirar do ranking) NAO ficam no repositorio publico: entram pela propria tela
-- (Administracao > de-para de credores) ou pelo SQL-12 (arquivo do vault). Seguro rodar de novo. Nada e apagado: "remover" = ativo = false.
CREATE TABLE IF NOT EXISTS gdf.pnl_credor_grupo (
    id             bigserial PRIMARY KEY,
    chave          text NOT NULL,                    -- nome do credor em MAIUSCULAS, sem acento e com espacos simples (o credor casa se o nome dele COMECA com isto)
    nome_exibicao  text,                             -- como a contabilidade escreveu
    grupo          text NOT NULL DEFAULT 'OUTROS_DIR' CHECK (grupo IN ('OUTROS_DIR')),
    ativo          boolean NOT NULL DEFAULT true,
    alterado_por   text,
    alterado_em    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pnl_credor_grupo_ativo ON gdf.pnl_credor_grupo (chave, grupo) WHERE ativo;
GRANT SELECT, INSERT, UPDATE ON gdf.pnl_credor_grupo TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.pnl_credor_grupo_id_seq TO gdf_app;
ALTER TABLE gdf.pnl_credor_grupo ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_credor_grupo;
CREATE POLICY gdf_app_full_access ON gdf.pnl_credor_grupo FOR ALL TO gdf_app USING (true) WITH CHECK (true);
