-- GDF V2 - De-para centro de custo -> grupo (OBRA / ADM / DEMAIS) e codigo da obra do painel. So a ESTRUTURA (sem dados).
-- Os dados (217 centros, validados pela Suellen) ficam no vault e sao colados no Supabase depois deste bloco. Seguro rodar de novo.
CREATE TABLE IF NOT EXISTS gdf.pnl_centro_grupo (
    centro_custo_id  bigint PRIMARY KEY,
    centro_nome      text,
    empresa_nome     text,
    grupo            text NOT NULL CHECK (grupo IN ('OBRA','ADM','DEMAIS_MES','DEMAIS_FIXA')),
    codigo_obra      text,                      -- codigo do painel (100, 103, 126...; DEM, ADM)
    obra_nome        text,
    alterado_por     text,
    alterado_em      timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON gdf.pnl_centro_grupo TO gdf_app;
ALTER TABLE gdf.pnl_centro_grupo ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_centro_grupo;
CREATE POLICY gdf_app_full_access ON gdf.pnl_centro_grupo FOR ALL TO gdf_app USING (true) WITH CHECK (true);
