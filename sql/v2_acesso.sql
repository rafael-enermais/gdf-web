-- GDF V2 (SQL-20) - Acesso por papel: EDITOR (tudo, como hoje) ou VISUALIZADOR (so' o "Painel da Diretoria").
-- Quem NAO estiver na lista continua EDITOR (nada muda para a contabilidade/Rafael). Quem estiver como VISUALIZADOR ativo so' enxerga o painel.
-- O login continua no Supabase Authentication (voce cria o usuario la); aqui so' se diz o papel do e-mail. gdf_app continua SEM DELETE
-- (para tirar o acesso: ativo = false, ou excluir o usuario no Authentication). Seguro rodar de novo.
CREATE TABLE IF NOT EXISTS gdf.pnl_acesso (
    email        text PRIMARY KEY,                                   -- sempre em minusculas
    papel        text NOT NULL CHECK (papel IN ('EDITOR', 'VISUALIZADOR')),
    ativo        boolean NOT NULL DEFAULT true,
    criado_por   text,
    criado_em    timestamptz NOT NULL DEFAULT now(),
    alterado_por text,
    alterado_em  timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON gdf.pnl_acesso TO gdf_app;
ALTER TABLE gdf.pnl_acesso ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_acesso;
CREATE POLICY gdf_app_full_access ON gdf.pnl_acesso FOR ALL TO gdf_app USING (true) WITH CHECK (true);
