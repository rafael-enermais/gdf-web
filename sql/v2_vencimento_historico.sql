-- GDF V2 (SQL-28) - HISTORICO de alteracoes de vencimento. Toda vez que a carga muda o data_vencimento de um titulo ja gravado, o banco registra
-- (antes -> depois, quando). O vencimento ATUAL continua em pnl_titulo.data_vencimento (usado por todos os fluxos); o ORIGINAL (SQL-27) fica a parte.
-- Gravacao feita por TRIGGER: vale para qualquer carga (diaria, semanal, manual). Nada e' apagado nem alterado nos titulos. Seguro rodar de novo.
CREATE TABLE IF NOT EXISTS gdf.pnl_vencimento_alteracao (
    id                  bigserial PRIMARY KEY,
    lado                char(1) NOT NULL,
    bill_id             bigint NOT NULL,
    installment_id      bigint NOT NULL,
    vencimento_anterior date,
    vencimento_novo     date,
    alterado_em         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pnl_vencimento_alteracao_titulo ON gdf.pnl_vencimento_alteracao (lado, bill_id, installment_id);
GRANT SELECT, INSERT ON gdf.pnl_vencimento_alteracao TO gdf_app;
GRANT USAGE, SELECT ON SEQUENCE gdf.pnl_vencimento_alteracao_id_seq TO gdf_app;
ALTER TABLE gdf.pnl_vencimento_alteracao ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gdf_app_full_access ON gdf.pnl_vencimento_alteracao;
CREATE POLICY gdf_app_full_access ON gdf.pnl_vencimento_alteracao FOR ALL TO gdf_app USING (true) WITH CHECK (true);

CREATE OR REPLACE FUNCTION gdf.pnl_titulo_registra_vencimento() RETURNS trigger AS $$
BEGIN
    IF OLD.data_vencimento IS DISTINCT FROM NEW.data_vencimento THEN
        INSERT INTO gdf.pnl_vencimento_alteracao (lado, bill_id, installment_id, vencimento_anterior, vencimento_novo)
        VALUES (NEW.lado, NEW.bill_id, NEW.installment_id, OLD.data_vencimento, NEW.data_vencimento);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS pnl_titulo_vencimento_hist ON gdf.pnl_titulo;
CREATE TRIGGER pnl_titulo_vencimento_hist AFTER UPDATE OF data_vencimento ON gdf.pnl_titulo
    FOR EACH ROW EXECUTE FUNCTION gdf.pnl_titulo_registra_vencimento();
