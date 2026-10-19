-- GDF V2 (SQL-16) - Folha de pagamento lida dos RECIBOS (PDF): um registro por recibo (colaborador) + de-para departamento -> obra.
-- Cada PDF importado vira uma linha em pnl_importacao (tipo 'FOLHA', escopo CONSTRUTORA/ENERGIA); a anterior do mesmo mes/escopo fica ativo=false.
-- Guarda dados de pessoas (nome, salario): a tabela fica no banco (nao no repositorio publico). Seguro rodar de novo. So acrescenta.
ALTER TABLE gdf.pnl_folha_evento ADD COLUMN IF NOT EXISTS informativo boolean NOT NULL DEFAULT false;   -- linha so' informativa (vale alimentacao, auxilio doenca)

CREATE TABLE IF NOT EXISTS gdf.pnl_folha_recibo (
    id              bigserial PRIMARY KEY,
    importacao_id   bigint NOT NULL REFERENCES gdf.pnl_importacao(id),
    empresa         text NOT NULL,                        -- 468 = Construtora, 469 = Energia (codigo da empresa no recibo)
    cadastro        text NOT NULL,
    nome            text,
    cargo           text,
    local_obra      text,
    departamento    text,                                 -- 001.NNN = subnivel do canteiro
    subnivel_texto  text,
    admissao        date,
    salario         numeric(18,2),                        -- evento 1 (Horas Normais)
    hora_extra      numeric(18,2),                        -- eventos de HE (50/60/80/100/110%)
    dsr_he          numeric(18,2),                        -- DSR s/ horas extras
    total_proventos numeric(18,2),
    total_descontos numeric(18,2),
    liquido         numeric(18,2),
    fgts_mes        numeric(18,2)
);
CREATE INDEX IF NOT EXISTS ix_pnl_folha_recibo_imp ON gdf.pnl_folha_recibo (importacao_id);

-- De-para: departamento da folha (empresa + 001.NNN) -> codigo da obra do painel. Os dados entram por SQL-17 (so' no vault).
CREATE TABLE IF NOT EXISTS gdf.pnl_folha_depto_obra (
    empresa         text NOT NULL,
    departamento    text NOT NULL,
    subnivel_texto  text,
    codigo_obra     text NOT NULL,                        -- codigo da obra do DRE (103, 104...; 99 = administracao central)
    obra_nome       text,
    PRIMARY KEY (empresa, departamento)
);

ALTER TABLE gdf.pnl_importacao DROP CONSTRAINT IF EXISTS pnl_importacao_tipo_check;
ALTER TABLE gdf.pnl_importacao ADD CONSTRAINT pnl_importacao_tipo_check CHECK (tipo IN ('PROJECAO','FOLHA','HISTORICO','DRE','ORCAMENTO'));

GRANT SELECT, INSERT ON gdf.pnl_folha_recibo TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.pnl_folha_recibo_id_seq TO gdf_app;
GRANT SELECT, INSERT, UPDATE ON gdf.pnl_folha_depto_obra TO gdf_app;
ALTER TABLE gdf.pnl_folha_recibo ENABLE ROW LEVEL SECURITY;
ALTER TABLE gdf.pnl_folha_depto_obra ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_folha_recibo;
CREATE POLICY gdf_app_full_access ON gdf.pnl_folha_recibo FOR ALL TO gdf_app USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_folha_depto_obra;
CREATE POLICY gdf_app_full_access ON gdf.pnl_folha_depto_obra FOR ALL TO gdf_app USING (true) WITH CHECK (true);
