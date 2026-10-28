-- GDF V2 (SQL-40) - Painel "Folha PJ" (Painel da Diretoria, ao lado de Pessoas). So a ESTRUTURA (sem nomes, sem CPF, sem valores):
--  1) pnl_titulo.desconto_titulo: desconto lancado no TITULO (discountAmount da API do Sienge) - e' o "desconto dos abertos" do relatorio a pagar.
--     A coleta tambem passa a guardar o imposto retido do titulo a pagar (taxAmount) em pnl_titulo.imposto_titulo (antes so' do lado receber).
--  2) pj_diretoria_credor: credores da diretoria por CODIGO do Sienge (somados numa linha so' no painel). Editavel na tela de importacoes.
--  3) pj_colaborador: mapa credor -> colaborador PJ (funcao, centro de origem, CPF so' como hash, "novo"). Vem da planilha da folha.
--  4) pj_flash: Flash do mes (premiacao no cartao e alimentacao/refeicao) so' de quem casa com um PJ; sem CPF em claro.
-- Seguro rodar de novo. Nada e apagado ("remover" = ativo = false). Depois de rodar: Actions > Ingest Sienge GDF (ou esperar a rotina das 04:30) para preencher o desconto dos titulos.
ALTER TABLE gdf.pnl_titulo ADD COLUMN IF NOT EXISTS desconto_titulo numeric(18,2);
COMMENT ON COLUMN gdf.pnl_titulo.desconto_titulo IS 'discountAmount do titulo a pagar (desconto lancado antes do pagamento); NULL = ainda nao sincronizado';
COMMENT ON COLUMN gdf.pnl_titulo.imposto_titulo IS 'taxAmount do titulo (receber: impostos da NF; pagar: imposto retido do titulo); NULL = ainda nao sincronizado';

CREATE TABLE IF NOT EXISTS gdf.pj_diretoria_credor (
    credor_id      integer PRIMARY KEY,                   -- codigo do credor no Sienge
    nome_exibicao  text,
    ativo          boolean NOT NULL DEFAULT true,
    alterado_por   text,
    alterado_em    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gdf.pj_colaborador (
    credor_id      integer PRIMARY KEY,                   -- codigo do credor no Sienge (um colaborador PJ = um credor)
    nome_exibicao  text NOT NULL,
    nome_chave     text,                                  -- nome em minusculas, sem acento (cruzamento com o Flash quando falta CPF)
    funcao         text,
    centro_origem  text,                                  -- centro de custo que ja estava na planilha (usado so' para quem tem Flash e nenhuma nota no mes)
    empresa_origem text,
    cpf_hash       text,                                  -- HMAC-SHA256 do CPF (so' digitos) com segredo do app; NUNCA o CPF
    novo_desde     date,                                  -- 1o dia do mes em que entrou na lista (marca "novo" naquele mes)
    ativo          boolean NOT NULL DEFAULT true,
    alterado_por   text,
    alterado_em    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pj_colaborador_cpf ON gdf.pj_colaborador (cpf_hash);

CREATE TABLE IF NOT EXISTS gdf.pj_flash (
    mes            date NOT NULL,                         -- 1o dia da competencia
    empresa        text NOT NULL,                         -- empresa do arquivo Flash (quem paga o beneficio)
    credor_id      integer NOT NULL,                      -- so' entra quem casou com um PJ de pj_colaborador
    premiacao      numeric(14,2) NOT NULL DEFAULT 0,      -- "premiacao no cartao" = Ajuda de custo
    alimentacao    numeric(14,2) NOT NULL DEFAULT 0,      -- refeicao e alimentacao = Vale alimentacao
    ativo          boolean NOT NULL DEFAULT true,         -- reimportar o Flash do mes/empresa desativa as linhas antigas e grava as novas (nada e apagado)
    importado_por  text,
    importado_em   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (mes, empresa, credor_id)
);

GRANT SELECT, INSERT, UPDATE ON gdf.pj_diretoria_credor, gdf.pj_colaborador, gdf.pj_flash TO gdf_app;
ALTER TABLE gdf.pj_diretoria_credor ENABLE ROW LEVEL SECURITY;
ALTER TABLE gdf.pj_colaborador ENABLE ROW LEVEL SECURITY;
ALTER TABLE gdf.pj_flash ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pj_diretoria_credor;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pj_colaborador;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pj_flash;
CREATE POLICY gdf_app_full_access ON gdf.pj_diretoria_credor FOR ALL TO gdf_app USING (true) WITH CHECK (true);
CREATE POLICY gdf_app_full_access ON gdf.pj_colaborador FOR ALL TO gdf_app USING (true) WITH CHECK (true);
CREATE POLICY gdf_app_full_access ON gdf.pj_flash FOR ALL TO gdf_app USING (true) WITH CHECK (true);
