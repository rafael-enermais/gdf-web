# -*- coding: utf-8 -*-
"""Guia do app para a Dexie: cobre todas as paginas do menu, responde por ferramenta e entra no prompt. Sem banco e sem rede."""
import re
from datetime import date
from pathlib import Path

import ajuda as AJ
import dexie_chat as DC
import dexie_ferramentas as FERR
import guia_app as G

APP = Path(__file__).resolve().parent.parent


def test_guia_cobre_todas_as_paginas_do_menu():
    """Pagina nova no menu (app.py) sem texto no guia = teste falha: a Dexie nunca fica para tras do app."""
    codigo = (APP / "app.py").read_text(encoding="utf-8")
    titulos = set(re.findall(r'st\.Page\([^)]*?title="([^"]+)"', codigo))
    assert len(titulos) >= 12
    assert titulos == {p["pagina"] for p in G.PAGINAS}, titulos ^ {p["pagina"] for p in G.PAGINAS}
    secoes = set(re.findall(r'^    "([^"]*)": \[', codigo, re.M))
    assert {p["secao"] for p in G.PAGINAS if p["secao"] != "(topo)"} <= secoes


def test_tela_nova_do_menu_tem_arquivo_e_ajuda():
    codigo = (APP / "app.py").read_text(encoding="utf-8")
    for arq in re.findall(r'st\.Page\("(telas/[^"]+)"', codigo):
        assert (APP / arq).exists(), arq
    assert "Obras e contratos" in " ".join(t + x for t, x in AJ.FLUXO_V2)         # a Ajuda fala da pagina de contratos


def test_ferramenta_guia_do_app_menu_pagina_e_busca():
    r, t = FERR.executar(None, "guia_do_app", {})
    assert t is None and len(r["menu"]) == len(G.PAGINAS) and r["fluxos"] and r["onde_faco"] and "EDITOR" in r["papeis"]
    r, _ = FERR.executar(None, "guia_do_app", {"pagina": "contratos"})
    assert r["paginas"][0]["pagina"] == "Obras e contratos" and "Pendentes" in r["paginas"][0]["resumo"].title().replace("PENDENTES", "Pendentes")
    assert "erro" in FERR.executar(None, "guia_do_app", {"pagina": "tela que nao existe"})[0]
    r, _ = FERR.executar(None, "guia_do_app", {"busca": "dar acesso a um diretor visualizador"})
    assert any("Acessos" in x["como"] for x in r["onde_faco"])
    r, _ = FERR.executar(None, "guia_do_app", {"busca": "o custo da API é maior que o PDF"})
    assert r["trechos_da_ajuda"] and "erro" not in r
    assert "erro" in FERR.executar(None, "guia_do_app", {"busca": "a b"})[0]
    assert "guia_do_app" in [x["name"] for x in FERR.TOOLS]


def test_prompt_da_dexie_leva_o_mapa_das_telas_e_a_regra_de_contratos():
    s = DC.montar_system("ana@x", date(2026, 10, 23))
    for p in G.PAGINAS:
        assert p["pagina"] in s, p["pagina"]
    assert "guia_do_app" in s and "incluir_pendentes" in s and "quem clica na tela é a pessoa" in s
    assert s.index("SEGURANÇA") > s.index("guia_do_app")


def test_guia_sem_dado_pessoal():
    corpo = " ".join(p["resumo"] + " ".join(p["abas"]) for p in G.PAGINAS) + " ".join(a + b for a, b in G.ONDE) + " ".join(G.FLUXOS) + G.PAPEIS
    assert "@" not in corpo and not re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", corpo)
    nomes = ("Su" + "ellen", "Raf" + "ael", "Al" + "ex", "Yu" + "di")
    assert not any(n in corpo for n in nomes)
