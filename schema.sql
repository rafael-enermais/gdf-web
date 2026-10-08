-- =====================================================================
-- GDF - Gestao de Demonstrativo Financeiro  |  schema.sql v0.1
-- Projeto Supabase: radar-comercial (compartilhado com RADAR e EGC)  |  schema NOVO: gdf  |  role: gdf_app
-- NAO toca nenhum schema existente (public, egc...). Idempotente: pode rodar mais de uma vez.
--
-- Como aplicar (so' com o OK do Rafael): Supabase > SQL Editor > colar este arquivo e executar.
-- Depois: ALTER ROLE gdf_app WITH PASSWORD '<senha forte>';  (NAO commitar a senha)
-- e usar a connection string da role gdf_app em st.secrets["DATABASE_URL"].
--
-- Regras de ouro: nada e' apagado de verdade (ativo=false, "Desfazer" reativa); a role do app NAO tem DELETE.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS gdf;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gdf_app') THEN
    CREATE ROLE gdf_app LOGIN;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA gdf TO gdf_app;
ALTER ROLE gdf_app SET search_path = gdf;
REVOKE ALL ON SCHEMA public FROM gdf_app;

-- 1. Empresas (multiempresa: Anastacio agora, Enermais depois) ----------------------------
CREATE TABLE IF NOT EXISTS gdf.empresa (
    id            bigserial PRIMARY KEY,
    codigo        text NOT NULL UNIQUE,                 -- ex.: ANASTACIO
    razao_social  text NOT NULL,
    cnpj          text NOT NULL UNIQUE,
    config        jsonb NOT NULL DEFAULT '{}'::jsonb,   -- assinantes, paginas aplicaveis (Fase 2)
    ativo         boolean NOT NULL DEFAULT true,
    criado_em     timestamptz NOT NULL DEFAULT now()
);

-- 2. Importacoes de balancete (1 arquivo = 1 periodo) -------------------------------------
CREATE TABLE IF NOT EXISTS gdf.importacao (
    id              bigserial PRIMARY KEY,
    empresa_id      bigint NOT NULL REFERENCES gdf.empresa(id),
    tipo            text NOT NULL CHECK (tipo IN ('MENSAL','ACUMULADO')),
    periodo_ini     date NOT NULL,
    periodo_fim     date NOT NULL,
    arquivo_nome    text NOT NULL,
    arquivo_sha256  text NOT NULL,                      -- mesmo arquivo nao entra duas vezes
    status          text NOT NULL DEFAULT 'RASCUNHO' CHECK (status IN ('RASCUNHO','REVISADA')),
    ativo           boolean NOT NULL DEFAULT true,      -- so' as ativas alimentam os demonstrativos
    importado_por   text,
    importado_em    timestamptz NOT NULL DEFAULT now(),
    n_contas        integer NOT NULL DEFAULT 0,
    UNIQUE (empresa_id, arquivo_sha256)
);
-- no maximo 1 importacao ATIVA por empresa + tipo + periodo
CREATE UNIQUE INDEX IF NOT EXISTS ux_importacao_ativa
    ON gdf.importacao (empresa_id, tipo, periodo_ini, periodo_fim) WHERE ativo;

-- 3. Linhas do balancete ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gdf.balancete_linha (
    id              bigserial PRIMARY KEY,
    importacao_id   bigint NOT NULL REFERENCES gdf.importacao(id),
    conta_id        text NOT NULL,                      -- codigo interno do sistema contabil
    classificacao   text NOT NULL,                      -- ex.: 1.1.01.002.001
    nome            text NOT NULL,
    sintetica       boolean NOT NULL,
    saldo_anterior  numeric(18,2) NOT NULL,
    debito          numeric(18,2) NOT NULL,
    credito         numeric(18,2) NOT NULL,
    saldo_final     numeric(18,2) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_balancete_imp ON gdf.balancete_linha (importacao_id);

-- 4. Mapa de contas (por empresa; edicao = nova linha, a anterior fica inativa) ---------------
CREATE TABLE IF NOT EXISTS gdf.mapa_conta (
    id            bigserial PRIMARY KEY,
    empresa_id    bigint NOT NULL REFERENCES gdf.empresa(id),
    chave         text NOT NULL,                        -- ex.: dep_vista, juros, prej
    rotulo        text NOT NULL,
    secao         text NOT NULL CHECK (secao IN ('BP','DRE')),
    prefixos      text[] NOT NULL,                      -- classificacoes que alimentam a chave
    natureza      text CHECK (natureza IN ('D','C')),   -- so' contas de resultado
    ativo         boolean NOT NULL DEFAULT true,
    alterado_por  text,
    alterado_em   timestamptz NOT NULL DEFAULT now(),
    motivo        text
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mapa_ativo ON gdf.mapa_conta (empresa_id, chave) WHERE ativo;

-- 4b. Apelidos de nomes para a Composicao de Saldos (a contadora edita; o sistema reaproveita todo mes) ----
CREATE TABLE IF NOT EXISTS gdf.apelido (
    id             bigserial PRIMARY KEY,
    empresa_id     bigint NOT NULL REFERENCES gdf.empresa(id),
    nome_original  text NOT NULL,                       -- nome da conta no balancete (abreviado/cortado)
    apelido        text NOT NULL,                       -- nome limpo que aparece no relatorio
    ativo          boolean NOT NULL DEFAULT true,
    alterado_por   text,
    alterado_em    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_apelido_ativo ON gdf.apelido (empresa_id, lower(nome_original)) WHERE ativo;

-- 5. Conferencias e log de eventos ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS gdf.conferencia (
    id             bigserial PRIMARY KEY,
    importacao_id  bigint NOT NULL REFERENCES gdf.importacao(id),
    grupo          text NOT NULL,
    descricao      text NOT NULL,
    ok             boolean NOT NULL,
    detalhe        text,
    criado_em      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conferencia_imp ON gdf.conferencia (importacao_id);

CREATE TABLE IF NOT EXISTS gdf.evento (
    id          bigserial PRIMARY KEY,
    empresa_id  bigint REFERENCES gdf.empresa(id),
    origem      text NOT NULL,                          -- importar, historico, mapa, demonstrativos...
    nivel       text NOT NULL CHECK (nivel IN ('info','aviso','erro')),
    mensagem    text NOT NULL,
    detalhe     jsonb NOT NULL DEFAULT '{}'::jsonb,
    usuario     text,
    criado_em   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_evento_data ON gdf.evento (criado_em DESC);

-- 6. Relatorios gerados (Fase 2: PDF no layout novo) ----------------------------------------
CREATE TABLE IF NOT EXISTS gdf.relatorio (
    id          bigserial PRIMARY KEY,
    empresa_id  bigint NOT NULL REFERENCES gdf.empresa(id),
    periodo     date NOT NULL,
    versao      integer NOT NULL DEFAULT 1,
    status      text NOT NULL DEFAULT 'RASCUNHO' CHECK (status IN ('RASCUNHO','REVISADO','ASSINADO')),
    pdf_sha256  text,
    textos      jsonb NOT NULL DEFAULT '{}'::jsonb,     -- leitura editavel pela contadora
    assinantes  jsonb NOT NULL DEFAULT '[]'::jsonb,
    gerado_por  text,
    gerado_em   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (empresa_id, periodo, versao)
);
-- relatorio ASSINADO nunca e' regravado: nova versao = nova linha.

-- 7. Acesso da role do app (sem DELETE de proposito) + RLS -----------------------------------
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA gdf TO gdf_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA gdf TO gdf_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA gdf GRANT SELECT, INSERT, UPDATE ON TABLES TO gdf_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA gdf GRANT USAGE, SELECT ON SEQUENCES TO gdf_app;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['empresa','importacao','balancete_linha','mapa_conta','apelido','conferencia','evento','relatorio']
  LOOP
    EXECUTE format('ALTER TABLE gdf.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS gdf_app_full_access ON gdf.%I', t);
    EXECUTE format('CREATE POLICY gdf_app_full_access ON gdf.%I FOR ALL TO gdf_app USING (true) WITH CHECK (true)', t);
  END LOOP;
END
$$;
