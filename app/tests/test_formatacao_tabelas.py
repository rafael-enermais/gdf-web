# -*- coding: utf-8 -*-
import formatacao as F
import motor
import tabelas
from dados_sinteticos import gerar_meses


def test_formatacao_br():
    assert F.num_br(1234.5) == "1.234,50"
    assert F.num_br(-1234.5) == "−1.234,50"
    assert F.num_br(0) == "0,00" and F.num_br(-0.001) == "0,00"
    assert F.num_br(None) == "–"
    assert F.moeda_br(-10) == "−R$ 10,00"
    assert F.pct_br(0.949) == "94,9%" and F.razao_br(1.348) == "1,35x"
    assert F.var_pct(50, 100) == "−50,0%" and F.var_pct(5, 0) == "–" and F.var_pct(-10, -100) == "90,0%"
    assert F.mes_br("2026-08") == "08/2026"


def test_tabelas_montam():
    b = motor.Balancetes(gerar_meses([(100_000, 5_000, 200), (80_000, 4_000, 100)]))
    bp, d = motor.balanco(b, "2026-02"), motor.dre(b, "2026-02")
    (df_a, est_a), (df_p, est_p) = tabelas.tabela_balanco(bp, "2026-02", "2026-01")
    assert list(df_a.columns)[1:4] == ["31/12/2025", "31/01/2026", "28/02/2026"]
    assert len(df_a) == len(est_a) and len(df_p) == len(est_p)
    tot = df_a[df_a.iloc[:, 0] == "TOTAL DO ATIVO"].iloc[0]
    assert tot["31/12/2025"] == "6.000.000,00"
    df_d, est_d = tabelas.tabela_dre(d, "2026-02")
    liq = df_d[df_d.iloc[:, 0] == "RESULTADO LÍQUIDO DO PERÍODO"].iloc[0]
    assert liq.iloc[2] == "−175.300,00" or liq.iloc[2].startswith("−")
    df_i, est_i = tabelas.tabela_indicadores(bp, d, "2026-02", "2026-01")
    assert len(df_i) == len(est_i) and df_i.iloc[:, 0].tolist().count("Liquidez corrente") == 1
    assert df_i[df_i.iloc[:, 0] == "Resultado líquido (R$)"].iloc[0, 1] == "–"        # abertura nao tem resultado
    tabelas.estilizar(df_d, est_d).to_html()                                              # Styler nao quebra
