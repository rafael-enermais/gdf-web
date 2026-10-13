-- =====================================================================
-- GDF V2 - Painel de Resultados EnerMais  |  v2_painel_schema.sql v0.1  (13/10/2026)
-- Projeto Supabase: radar-comercial  |  schema: gdf (ja existe)  |  role do app: gdf_app (ja existe)
-- SO CRIA TABELAS/VIEWS NOVAS com prefixo pnl_. NAO altera nem apaga nada que ja existe (empresa, importacao, balancete_linha...).
-- Idempotente (pode rodar mais de uma vez). Sem DELETE para a role do app (mesma regra do GDF): nada e' apagado, usa-se ativo=false / sync_id.
-- Ideia: guardar o dado "cru" que vem do Sienge e dos uploads; as REGRAS (o que entra em cada aba) ficam em pnl_regra e
-- podem mudar sem reimportar.
-- =====================================================================

-- 1. Cadastros que vem do Sienge ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gdf.pnl_empresa_sienge (
    id            bigint PRIMARY KEY,                    -- companyId do Sienge
    nome          text NOT NULL,
    cnpj          text,
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

-- Obra como aparece no painel/DRE (ex.: 103 - ANASTACIO - LOTE 11). Preenchida/validada pela Suellen.
CREATE TABLE IF NOT EXISTS gdf.pnl_obra (
    codigo        text PRIMARY KEY,                      -- codigo da obra no Sienge/DRE (ex.: 103)
    nome_sienge   text,
    nome_painel   text NOT NULL,                         -- nome curto que aparece no painel
    cliente       text,
    grupo         text NOT NULL DEFAULT 'OBRA' CHECK (grupo IN ('OBRA','DEMAIS','ADM')),
    ativo         boolean NOT NULL DEFAULT true,
    alterado_por  text,
    alterado_em   timestamptz NOT NULL DEFAULT now(),
    motivo        text
);

-- Centro de custo do Sienge -> obra (a DRE por obra agrupa varios centros de custo numa obra)
CREATE TABLE IF NOT EXISTS gdf.pnl_centro_custo (
    id            bigint PRIMARY KEY,                    -- costCenterId
    nome          text NOT NULL,
    empresa_id    bigint,
    obra_codigo   text REFERENCES gdf.pnl_obra(codigo),  -- de-para (sugestao automatica + validacao manual)
    obra_origem   text CHECK (obra_origem IN ('AUTO','MANUAL')),
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    alterado_por  text
);

CREATE TABLE IF NOT EXISTS gdf.pnl_plano_conta (
    codigo        text PRIMARY KEY,                      -- com pontos (2.01.02.01)
    codigo_sienge text,                                  -- como o Sienge devolve (2010201)
    nome          text NOT NULL,
    tipo          text,
    redutora      boolean,
    ativa         boolean,
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gdf.pnl_tipo_negocio (
    id            bigint PRIMARY KEY,
    nome          text NOT NULL,
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

-- 2. Sincronizacoes com o Sienge (log; 1 linha por mes/lado/tipo de data) -----------------------
CREATE TABLE IF NOT EXISTS gdf.pnl_sync (
    id              bigserial PRIMARY KEY,
    mes             date NOT NULL,                       -- 1o dia do mes
    lado            char(1) NOT NULL CHECK (lado IN ('P','R')),   -- P = a pagar, R = a receber
    tipo_data       text NOT NULL,                       -- I emissao, D vencimento, P pagamento (R: tambem B, C)
    status          text NOT NULL DEFAULT 'EM_ANDAMENTO' CHECK (status IN ('EM_ANDAMENTO','OK','ERRO')),
    n_titulos       integer NOT NULL DEFAULT 0,
    n_baixas        integer NOT NULL DEFAULT 0,
    n_rateios       integer NOT NULL DEFAULT 0,
    valor_liquido   numeric(18,2),
    usuario         text,
    erro            text,
    iniciado_em     timestamptz NOT NULL DEFAULT now(),
    finalizado_em   timestamptz
);
CREATE INDEX IF NOT EXISTS ix_pnl_sync_mes ON gdf.pnl_sync (mes, lado, tipo_data, id DESC);

-- 3. Titulos, baixas e rateios (dado cru do Sienge) ------------------------------------------------
CREATE TABLE IF NOT EXISTS gdf.pnl_titulo (
    lado              char(1) NOT NULL CHECK (lado IN ('P','R')),
    bill_id           bigint NOT NULL,
    installment_id    bigint NOT NULL,
    sync_id           bigint NOT NULL REFERENCES gdf.pnl_sync(id),   -- ultima sync que trouxe este titulo
    empresa_id        bigint,
    empresa_nome      text,
    origem            text,                              -- originId (CP, ME, AC, RF, FP...)
    doc_id            text,                              -- tipo de documento (NFS, HOL, PRV, FOPA, GUIA...)
    doc_nome          text,
    previsao          text,                              -- forecastDocument / documentForecast
    numero_doc        text,
    contraparte_id    bigint,                            -- credor (P) ou cliente (R)
    contraparte_nome  text,
    data_emissao      date,
    data_vencimento   date,
    valor_original    numeric(18,2),
    tipo_negocio_id   bigint,
    tipo_negocio_nome text,
    area_id           bigint,
    area_nome         text,
    projeto_id        bigint,                            -- no EnerMais o "projeto" do Sienge = empresa do grupo
    projeto_nome      text,
    atualizado_em     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (lado, bill_id, installment_id)
);
CREATE INDEX IF NOT EXISTS ix_pnl_titulo_emissao ON gdf.pnl_titulo (data_emissao);
CREATE INDEX IF NOT EXISTS ix_pnl_titulo_venc ON gdf.pnl_titulo (data_vencimento);

CREATE TABLE IF NOT EXISTS gdf.pnl_baixa (
    lado              char(1) NOT NULL,
    bill_id           bigint NOT NULL,
    installment_id    bigint NOT NULL,
    seq               integer NOT NULL,                  -- sequencialNumber da baixa
    sync_id           bigint NOT NULL REFERENCES gdf.pnl_sync(id),
    data_pagamento    date,
    tipo_oper_id      integer,                           -- 1 Pagamento, 3 Cancelamento, 5 Substituicao, 8 Abatimento de adiantamento, 10 Adiantamento
    tipo_oper_nome    text,
    bruto             numeric(18,2),
    liquido           numeric(18,2),
    juros             numeric(18,2),
    multa             numeric(18,2),
    desconto          numeric(18,2),
    imposto           numeric(18,2),
    correcao          numeric(18,2),
    PRIMARY KEY (lado, bill_id, installment_id, seq),
    FOREIGN KEY (lado, bill_id, installment_id) REFERENCES gdf.pnl_titulo (lado, bill_id, installment_id)
);
CREATE INDEX IF NOT EXISTS ix_pnl_baixa_data ON gdf.pnl_baixa (data_pagamento);

CREATE TABLE IF NOT EXISTS gdf.pnl_rateio (
    lado              char(1) NOT NULL,
    bill_id           bigint NOT NULL,
    installment_id    bigint NOT NULL,
    linha             integer NOT NULL,                  -- posicao na lista de rateio do titulo
    sync_id           bigint NOT NULL REFERENCES gdf.pnl_sync(id),
    plano_cod         text NOT NULL,                     -- conta do plano financeiro, com pontos
    plano_nome        text,
    centro_custo_id   bigint,
    centro_custo_nome text,
    percentual        numeric(12,6) NOT NULL,            -- % do titulo/baixa que cai nesta conta + centro de custo
    PRIMARY KEY (lado, bill_id, installment_id, linha),
    FOREIGN KEY (lado, bill_id, installment_id) REFERENCES gdf.pnl_titulo (lado, bill_id, installment_id)
);
CREATE INDEX IF NOT EXISTS ix_pnl_rateio_plano ON gdf.pnl_rateio (plano_cod);
CREATE INDEX IF NOT EXISTS ix_pnl_rateio_cc ON gdf.pnl_rateio (centro_custo_id);

-- Views: so enxergam baixas/rateios da ULTIMA sincronizacao de cada titulo (se um rateio mudar no Sienge, o antigo some da leitura)
CREATE OR REPLACE VIEW gdf.pnl_v_baixa WITH (security_invoker = true) AS
SELECT b.* FROM gdf.pnl_baixa b
JOIN gdf.pnl_titulo t ON t.lado=b.lado AND t.bill_id=b.bill_id AND t.installment_id=b.installment_id AND t.sync_id=b.sync_id;

CREATE OR REPLACE VIEW gdf.pnl_v_rateio WITH (security_invoker = true) AS
SELECT r.* FROM gdf.pnl_rateio r
JOIN gdf.pnl_titulo t ON t.lado=r.lado AND t.bill_id=r.bill_id AND t.installment_id=r.installment_id AND t.sync_id=r.sync_id;

-- 4. Regras (o que entra em cada aba) - editaveis, com historico em alterado_por/em ----------------
CREATE TABLE IF NOT EXISTS gdf.pnl_regra (
    id            bigserial PRIMARY KEY,
    area          text NOT NULL,                         -- DESPESAS, RESULTADO, OBRAS, ADM, PESSOAS, GERAL
    tipo          text NOT NULL,                         -- EXCLUI_PLANO_PREFIXO, EXCLUI_DOC, EXCLUI_OPERACAO, PERCENTUAL_PREVISTO...
    valor         text NOT NULL,
    descricao     text,
    status        text NOT NULL DEFAULT 'PROPOSTA' CHECK (status IN ('PROPOSTA','CONFIRMADA')),
    ativo         boolean NOT NULL DEFAULT true,
    alterado_por  text,
    alterado_em   timestamptz NOT NULL DEFAULT now(),
    motivo        text
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pnl_regra_ativa ON gdf.pnl_regra (area, tipo, valor) WHERE ativo;

-- Regras iniciais (PROPOSTA = deduzidas do CSV de setembro e da nota do painel; a Suellen confirma)
INSERT INTO gdf.pnl_regra (area, tipo, valor, descricao, status, alterado_por, motivo)
SELECT * FROM (VALUES
  ('DESPESAS','EXCLUI_PLANO_PREFIXO','2.01.02','Pessoal de obra (fica na aba Pessoas)','PROPOSTA','sistema','deducao do CSV set/2026 e nota do painel'),
  ('DESPESAS','EXCLUI_PLANO_PREFIXO','2.02.01','Pessoal ADM (fica na aba Pessoas)','PROPOSTA','sistema','deducao do CSV set/2026 e nota do painel'),
  ('DESPESAS','EXCLUI_PLANO_PREFIXO','2.04.02','Encargos INSS/FGTS (ficam na aba Pessoas)','PROPOSTA','sistema','deducao do CSV set/2026 e nota do painel'),
  ('DESPESAS','EXCLUI_PLANO_PREFIXO','1.03.02.02','Transferencias entre empresas','PROPOSTA','sistema','deducao do CSV set/2026 (R$ 5,52 Mi)')
) AS v(area,tipo,valor,descricao,status,alterado_por,motivo)
WHERE NOT EXISTS (SELECT 1 FROM gdf.pnl_regra r WHERE r.area=v.area AND r.tipo=v.tipo AND r.valor=v.valor AND r.ativo);

-- 5. Uploads feitos pela Suellen (projecao, recibos da folha) e historico importado do painel ------------
CREATE TABLE IF NOT EXISTS gdf.pnl_importacao (
    id              bigserial PRIMARY KEY,
    tipo            text NOT NULL CHECK (tipo IN ('PROJECAO','FOLHA','HISTORICO')),
    mes             date NOT NULL,                       -- 1o dia da competencia
    escopo          text NOT NULL DEFAULT '',            -- FOLHA: CONSTRUTORA / ENERGIA
    arquivo_nome    text NOT NULL,
    arquivo_sha256  text NOT NULL,
    status          text NOT NULL DEFAULT 'RASCUNHO' CHECK (status IN ('RASCUNHO','REVISADA')),
    ativo           boolean NOT NULL DEFAULT true,
    importado_por   text,
    importado_em    timestamptz NOT NULL DEFAULT now(),
    n_linhas        integer NOT NULL DEFAULT 0,
    detalhe         jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (tipo, arquivo_sha256)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pnl_importacao_ativa ON gdf.pnl_importacao (tipo, mes, escopo) WHERE ativo;

CREATE TABLE IF NOT EXISTS gdf.pnl_projecao_linha (
    id              bigserial PRIMARY KEY,
    importacao_id   bigint NOT NULL REFERENCES gdf.pnl_importacao(id),
    linha           integer NOT NULL,
    contrato        text, cliente text, obra text, categoria text, natureza text, empresa text,
    valor_mes       numeric(18,2),
    custos          numeric(18,2),
    bdi             numeric(18,2)
);
CREATE INDEX IF NOT EXISTS ix_pnl_projecao_imp ON gdf.pnl_projecao_linha (importacao_id);

CREATE TABLE IF NOT EXISTS gdf.pnl_folha_evento (
    id              bigserial PRIMARY KEY,
    importacao_id   bigint NOT NULL REFERENCES gdf.pnl_importacao(id),
    empresa         text,
    cadastro        text,
    nome            text,
    cbo             text,
    cargo           text,
    local_obra      text,                                -- campo "Local" do recibo (obra)
    departamento    text,
    admissao        date,
    ev              integer,                             -- codigo do evento (1, 35, 49, 59...)
    descricao       text,
    referencia      text,
    provento        numeric(18,2),
    desconto        numeric(18,2)
);
CREATE INDEX IF NOT EXISTS ix_pnl_folha_imp ON gdf.pnl_folha_evento (importacao_id);

-- Historico "importado do painel" (blocos do artifact: res, dev, obras, adm_m, desp...) por competencia
CREATE TABLE IF NOT EXISTS gdf.pnl_historico_bloco (
    id            bigserial PRIMARY KEY,
    importacao_id bigint REFERENCES gdf.pnl_importacao(id),
    periodo       date NOT NULL,                         -- competencia do painel (2026-09-01)
    bloco         text NOT NULL,                         -- res, dev, recomp, obras, adm_m, adm_u, desp, hc, he, pess, pdet, admdet, hcob
    dados         jsonb NOT NULL,
    origem        text NOT NULL DEFAULT 'IMPORTADO_DO_PAINEL',
    ativo         boolean NOT NULL DEFAULT true,
    importado_em  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pnl_hist_ativo ON gdf.pnl_historico_bloco (periodo, bloco) WHERE ativo;

-- 6. Acesso da role do app (sem DELETE) + RLS ------------------------------------------------------
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA gdf TO gdf_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA gdf TO gdf_app;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['pnl_empresa_sienge','pnl_obra','pnl_centro_custo','pnl_plano_conta','pnl_tipo_negocio','pnl_sync',
                           'pnl_titulo','pnl_baixa','pnl_rateio','pnl_regra','pnl_importacao','pnl_projecao_linha',
                           'pnl_folha_evento','pnl_historico_bloco']
  LOOP
    EXECUTE format('ALTER TABLE gdf.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS gdf_app_full_access ON gdf.%I', t);
    EXECUTE format('CREATE POLICY gdf_app_full_access ON gdf.%I FOR ALL TO gdf_app USING (true) WITH CHECK (true)', t);
  END LOOP;
END
$$;
