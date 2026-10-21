-- GDF V2 (SQL-33) - Anotacoes da Dexie ("o que ela aprendeu"): regras da casa, definicoes e notas de conhecimento que a equipe aprova.
-- A Dexie so' SUGERE (cartao na tela); a anotacao so' vale depois do clique de um editor. Nada e' apagado: editar cria uma versao nova e a anterior fica
-- 'desativado'. Guarda so' texto de regra/definicao (sem valores de periodo, sem dado pessoal). O papel gdf_app nao tem DELETE. Seguro rodar de novo.
CREATE TABLE IF NOT EXISTS gdf.dexie_aprendizado (
    id           bigserial PRIMARY KEY,
    tipo         text        NOT NULL CHECK (tipo IN ('regra', 'definicao', 'conhecimento')),
    titulo       text        NOT NULL,
    texto        text        NOT NULL,
    fonte        text,                                          -- de onde vem (ex.: "dito pela contabilidade em 21/10/2026", "LC 214/2025 art. 261")
    status       text        NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'desativado')),
    origem       text        NOT NULL CHECK (origem IN ('dexie', 'pessoa')),   -- 'dexie' = sugerida por ela e aprovada no cartao; 'pessoa' = digitada na tela
    criado_por   text        NOT NULL,
    criado_em    timestamptz NOT NULL DEFAULT now(),
    revisado_por text,
    revisado_em  timestamptz,
    motivo       text,                                          -- por que foi desativada/substituida
    substitui_id bigint REFERENCES gdf.dexie_aprendizado(id)
);
CREATE INDEX IF NOT EXISTS dexie_aprendizado_status_idx ON gdf.dexie_aprendizado (status, id);
GRANT SELECT, INSERT, UPDATE ON gdf.dexie_aprendizado TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.dexie_aprendizado_id_seq TO gdf_app;
ALTER TABLE gdf.dexie_aprendizado ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.dexie_aprendizado;
CREATE POLICY gdf_app_full_access ON gdf.dexie_aprendizado FOR ALL TO gdf_app USING (true) WITH CHECK (true);
