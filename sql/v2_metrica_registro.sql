-- GDF V2 (SQL-34) - Registro mensal das metricas do painel de metas (contrato do ENERDATA, metricas.md secao 4): 3 tabelas NOVAS no schema gdf.
--   metrica_registro      1 linha por item (I01.., E01..) por mes (e por empresa/obra/UN quando houver);
--   metrica_ocorrencia    so' para entregas diarias/semanais/por evento (data prevista x feita);
--   metrica_registro_hist rastro de correcao manual (quem, quando, valor anterior, motivo).
-- So' CRIA tabelas novas (nao altera nem apaga nada que existe; o banco radar-comercial e' compartilhado e sem backup ate a migracao).
-- O papel gdf_app NAO tem DELETE. Dimensoes vazias ficam como '' (texto vazio) para a chave unica funcionar no "upsert". Seguro rodar de novo.
CREATE TABLE IF NOT EXISTS gdf.metrica_registro (
    id              bigserial PRIMARY KEY,
    item_id         text        NOT NULL,                       -- I01..I54 (indicador) ou E01..E44 (entrega)
    periodo         text        NOT NULL CHECK (periodo ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    pessoa          text        NOT NULL,                       -- dono do item
    empresa         text        NOT NULL DEFAULT '',
    obra            text        NOT NULL DEFAULT '',
    un              text        NOT NULL DEFAULT '',
    app_origem      text        NOT NULL DEFAULT 'GDF',
    meta            text,                                       -- meta numerica ou texto do slide
    previsto        numeric,
    realizado       numeric,
    numerador       numeric,                                    -- razoes: permite somar periodos e depois dividir
    denominador     numeric,
    pct_atingimento numeric,                                    -- regra 3.2; vazio para indicador sem %
    status          text        NOT NULL DEFAULT 'Sem lançamento' CHECK (status IN ('No alvo', 'Atenção', 'Fora da meta', 'Sem lançamento')),
    origem          text        NOT NULL DEFAULT 'medido' CHECK (origem IN ('medido', 'checklist', 'manual')),
    detalhe         text,                                       -- texto curto + tela/lancamentos que explicam o numero (sem nome de pessoa/credor)
    atualizado_em   timestamptz NOT NULL DEFAULT now(),
    atualizado_por  text        NOT NULL DEFAULT 'sistema',
    UNIQUE (item_id, periodo, empresa, obra, un, app_origem)
);
CREATE INDEX IF NOT EXISTS metrica_registro_periodo_idx ON gdf.metrica_registro (periodo, item_id);

CREATE TABLE IF NOT EXISTS gdf.metrica_ocorrencia (
    id            bigserial PRIMARY KEY,
    item_id       text        NOT NULL,
    data_prevista date        NOT NULL,
    data_feita    date,
    no_prazo      boolean,                                      -- vazio = ainda sem lancamento
    observacao    text,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    criado_por    text        NOT NULL DEFAULT 'sistema',
    UNIQUE (item_id, data_prevista)
);

CREATE TABLE IF NOT EXISTS gdf.metrica_registro_hist (
    id              bigserial PRIMARY KEY,
    registro_id     bigint      NOT NULL REFERENCES gdf.metrica_registro(id),
    campo           text        NOT NULL,                       -- qual campo foi corrigido
    valor_anterior  text,
    valor_novo      text,
    motivo          text        NOT NULL,
    alterado_por    text        NOT NULL,
    alterado_em     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS metrica_registro_hist_reg_idx ON gdf.metrica_registro_hist (registro_id, id);

GRANT SELECT, INSERT, UPDATE ON gdf.metrica_registro, gdf.metrica_ocorrencia TO gdf_app;
GRANT SELECT, INSERT ON gdf.metrica_registro_hist TO gdf_app;          -- historico so' cresce
GRANT USAGE, SELECT ON SEQUENCE gdf.metrica_registro_id_seq, gdf.metrica_ocorrencia_id_seq, gdf.metrica_registro_hist_id_seq TO gdf_app;
ALTER TABLE gdf.metrica_registro      ENABLE ROW LEVEL SECURITY;
ALTER TABLE gdf.metrica_ocorrencia    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gdf.metrica_registro_hist ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.metrica_registro;
CREATE POLICY gdf_app_full_access ON gdf.metrica_registro      FOR ALL TO gdf_app USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.metrica_ocorrencia;
CREATE POLICY gdf_app_full_access ON gdf.metrica_ocorrencia    FOR ALL TO gdf_app USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.metrica_registro_hist;
CREATE POLICY gdf_app_full_access ON gdf.metrica_registro_hist FOR ALL TO gdf_app USING (true) WITH CHECK (true);
