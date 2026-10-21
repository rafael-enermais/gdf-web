-- GDF V2 (SQL-31) - Memoria da Dexie (assistente de IA): guarda so' o TEXTO das mensagens de cada usuario (pergunta e resposta), para a conversa
-- continuar quando a pessoa volta ou atualiza a pagina. Nao guarda resultado de ferramenta, dado de credor nem chave. A janela lida pelo app e' curta (24 mensagens).
-- "Nova conversa" NAO apaga: so' marca arquivado (o papel gdf_app nao tem DELETE). Fica no schema gdf (banco compartilhado com EGC e Radar). Seguro rodar de novo.
CREATE TABLE IF NOT EXISTS gdf.dexie_mensagem (
    id          bigserial PRIMARY KEY,
    usuario     text        NOT NULL,                       -- e-mail de quem conversou
    papel       text        NOT NULL CHECK (papel IN ('user', 'assistant')),
    conteudo    text        NOT NULL,
    arquivado   boolean     NOT NULL DEFAULT false,         -- true = conversa encerrada ("Nova conversa"); continua guardada
    criado_em   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dexie_mensagem_usuario_idx ON gdf.dexie_mensagem (usuario, arquivado, id);
GRANT SELECT, INSERT, UPDATE ON gdf.dexie_mensagem TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.dexie_mensagem_id_seq TO gdf_app;
ALTER TABLE gdf.dexie_mensagem ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.dexie_mensagem;
CREATE POLICY gdf_app_full_access ON gdf.dexie_mensagem FOR ALL TO gdf_app USING (true) WITH CHECK (true);
