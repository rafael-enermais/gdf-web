# -*- coding: utf-8 -*-
"""GDF - Guia do app para a Dexie: mapa do menu, o que cada pagina faz, quem ve o que e "onde eu faco X".

Texto ESTATICO escrito pela equipe (nao vem do banco; sem nome de pessoa, credor ou cliente). A Dexie le pela ferramenta `guia_do_app` para ajudar quem edita o app
a achar a tela certa e seguir um fluxo; ela NAO opera as telas (so' explica). Quando uma pagina nova entrar no menu (app.py), acrescente aqui: o teste
`test_guia_cobre_todas_as_paginas_do_menu` falha se alguma pagina do menu nao estiver descrita. Os passos detalhados dos fluxos vem da pagina Ajuda (modulo `ajuda`).
"""
from __future__ import annotations

import unicodedata

import ajuda as AJ

ATUALIZADO_EM = "23/10/2026"

PAPEIS = ("Dois papeis de acesso: EDITOR ve e faz tudo; VISUALIZADOR (diretoria) so' ve o Painel da Diretoria (as outras paginas nem existem para ele). "
          "A Dexie e' so' para EDITOR. O acesso e' cadastrado em Central de dados > Regras > Acessos (o usuario antes e' criado no Supabase > Authentication).")

# secao do menu, titulo (igual ao do menu), quem ve, resumo, abas / blocos
PAGINAS = [
    {"secao": "(topo)", "pagina": "Início", "quem": "editor", "resumo": "Quadro 'Situação do ano': para cada mês, se há balancete importado, status e conferências com falha; atalhos para os passos do mês.",
     "abas": []},
    {"secao": "Painéis", "pagina": "Painel da Diretoria", "quem": "editor e visualizador (única página do visualizador)",
     "resumo": ("Painel só de leitura para a diretoria, no formato do painel da contabilidade, com tudo calculado pela API do Sienge e pelos uploads. Filtro de PERÍODO no topo (mês, 3 ou 6 meses, ano até o mês, "
                "12 meses ou personalizado De→Até) vale para cartões, tabelas e somas; os gráficos mostram sempre os últimos 12 meses. Tabelas com caixinha: marque uma ou mais linhas para detalhar "
                "(várias somam; sem marcação vale o total). Botão 'Atualizar agora' limpa o cache."),
     "abas": ["Resultado (Receita − Custos = BDI, com Custos = DRE 04+06+08+09+10+12; BDI − Administração = Resultado, realizado x previsto)", "Obras (resultado por obra e Custos por categoria no nível do relatório de custos do Sienge; marcar categorias ou subcategorias filtra os credores abaixo; o KPI Custos e o Custo Total por categoria seguem o mesmo padrão (DRE 04+06+08+09+10+12))",
              "Administração (orçado x realizado por grupo, unidade e credor; contas do grupo)", "Despesas (contas pagas por conta, credor, obra)", "Pessoas (despesas com pessoas: colaboradores ativos e custos prioritários por credor e obra)", "Folha PJ (custo PJ do mês por empresa, obra e centro de custo: honorários, premiações, multa, Flash e descontos; pago x a pagar; colaboradores e documentos lançados, em cascata)", "Folha CLT (folha pelos recibos: cards, obras com mais horas extras, filtro obra → canteiro, lista CLT do mês, horas extras × receita)", "Gerar relatório em PDF (quadro acima das abas: modelos prontos ou caixinha por informação de cada aba, filtros de obra, empresa e situação PJ, capa e sumário no layout Enermais; caixa de observação opcional no rodapé de cada aba; só para o editor)",
              "Indicadores financeiros (prazos médios, ciclo, capital de giro, inadimplência)", "Financiamentos (posição de hoje; Investimentos só aparece se o editor liberar)"]},
    {"secao": "Painéis", "pagina": "Obras e contratos", "quem": "só editor",
     "resumo": ("Contratos de SUPRIMENTOS do Sienge (API, somente leitura; a EnerMais não usa contratos de venda no GDF), em um fluxo que desce na mesma tela: 1 Obras → 2 Credores → 3 Contratos → 4 Detalhe "
                "(medições e botão que lista os nomes dos anexos; não baixa arquivo). Marcar obras filtra credores e contratos; marcar credores filtra contratos. Contratos PENDENTES e CANCELADOS ficam fora dos totais "
                "por padrão (muitos são modelos, sem credor); a caixa 'Incluir pendentes e cancelados' os traz de volta. Dados guardados 1 hora; botão 'Atualizar do Sienge'. A Dexie consulta a mesma base pela ferramenta contratos."),
     "abas": []},
    {"secao": "Painéis", "pagina": "Métricas do mês", "quem": "só editor",
     "resumo": ("Calcula os indicadores de metas (I03, I22, I27) de um mês e grava o registro mensal (o histórico de mudanças só cresce; valor digitado à mão não é sobrescrito). Uma rotina diária às 7h30 "
                "(Brasília) também grava o mês atual. Esses registros alimentam o schema 'diretoria' lido por outros apps."),
     "abas": ["Calcular sem gravar", "Gravar", "Ver registro e histórico"]},
    {"secao": "Assistente", "pagina": "Dexie (assistente IA)", "quem": "só editor",
     "resumo": ("A assistente de IA: conversa em português, consulta os dados do app por ferramentas de LEITURA (resultado, despesas, pagamentos, contratos, pessoas, indicadores, financiamentos, logs...), "
                "a base de conhecimento (contabilidade, tributos, reforma tributária) e este guia; monta gráfico e relatório (PDF/Excel) da última consulta. Pode PROPOR ações (sincronizar o Sienge, "
                "atualizar cadastros) que só rodam depois do clique em 'Confirmar e executar'. Aprende com anotações aprovadas por clique."),
     "abas": ["Tabela", "Gráfico", "Relatório", "Anotações (regras da casa, editáveis em tabela)"]},
    {"secao": "Dados e regras", "pagina": "Central de dados", "quem": "só editor",
     "resumo": ("Onde os dados entram e as regras vivem (antiga 'Painel EnerMais'). O que vem do Sienge o app busca sozinho todo dia (últimos 365 dias); aqui se força uma busca, se enviam os arquivos "
                "(PDF do DRE, folha, projeção, orçamento ADM, histórico da contabilidade), se confirma o DRE do mês e se mantêm regras e acessos."),
     "abas": ["Sincronizar com o Sienge (busca contas a pagar/receber e atualiza cadastros de obras, centros e credores)",
              "Importações (V2) (todos os uploads, o que está em uso por mês, desfazer/reativar, editar valores importados, cadastro de credores)",
              "Despesas (prévia)", "Resultado (prévia) (compara PDF x API e confirma o DRE do mês: API, PDF ou MANUAL por linha)", "Obras (prévia)", "Administração (prévia)", "Pessoas (prévia)",
              "Regras (contas excluídas, de-para centro de custo → obra, acessos, opção Investimentos)", "Histórico e logs", "Relatório PDF (rascunho) do painel"]},
    {"secao": "Balancete (contabilidade)", "pagina": "Importar balancete", "quem": "só editor",
     "resumo": "Envia o balancete do mês (CSV ou PDF do sistema contábil), mostra as conferências (✅/❌), permite revisar e confirmar. Nada é apagado.", "abas": []},
    {"secao": "Balancete (contabilidade)", "pagina": "Demonstrativos", "quem": "só editor",
     "resumo": "Demonstrativos calculados dos balancetes ativos: Balanço, DRE, Indicadores, Composição de Saldos (apelidos editáveis) e Conferências.",
     "abas": ["Balanço Patrimonial", "DRE", "Indicadores", "Composição de Saldos", "Conferências"]},
    {"secao": "Balancete (contabilidade)", "pagina": "Painel do balancete", "quem": "só editor",
     "resumo": "KPIs e evolução mensal dos balancetes (mesmos números dos Demonstrativos) para estudo e histórico.", "abas": ["Evolução", "Indicadores", "Tabela mensal", "Qualidade dos dados"]},
    {"secao": "Balancete (contabilidade)", "pagina": "Relatório PDF", "quem": "só editor",
     "resumo": "Gera o relatório do mês no padrão EnerMais (rascunho e versão final), com textos de leitura editáveis, assinantes, histórico de versões e registro da assinatura feita no Autentique.", "abas": []},
    {"secao": "Balancete (contabilidade)", "pagina": "Histórico", "quem": "só editor",
     "resumo": "Importações de balancete (status, desfazer/reativar) e log de eventos (quem fez o quê). Nada é apagado.", "abas": ["Importações", "Log de eventos"]},
    {"secao": "Balancete (contabilidade)", "pagina": "Mapa de contas", "quem": "só editor",
     "resumo": "Como cada conta do balancete vira uma linha do demonstrativo. Editar cria uma linha nova e a anterior fica inativa (com motivo).", "abas": []},
    {"secao": "Ajuda", "pagina": "Ajuda", "quem": "só editor", "resumo": "Fluxo do mês, o que fazer quando uma conferência falha, glossário e o fluxo do Painel EnerMais (V2).",
     "abas": ["Fluxo do mês", "Quando algo não bate", "Glossário", "Painel EnerMais (V2)"]},
]

# "onde eu faco X" (a Dexie explica; quem clica e' a pessoa)
ONDE = [
    ("buscar dados novos do Sienge", "Central de dados > Sincronizar com o Sienge (a busca diária já roda sozinha). A Dexie pode propor a sincronização; você confirma no cartão."),
    ("atualizar nomes de obras, centros de custo e credores (nome fantasia)", "Botão 'Atualizar cadastros' na Central de dados (ou peça à Dexie para propor)."),
    ("enviar PDF do DRE, folha, projeção, orçamento ADM ou histórico da contabilidade", "Central de dados > Importações (V2). Desfazer = marcar a importação como 'fora de uso' lá mesmo."),
    ("confirmar o DRE do mês (escolher API, PDF ou MANUAL por linha)", "Central de dados > Resultado (prévia) > Confirmar o DRE do mês. O padrão é a API; o PDF só entra se a contabilidade escolher."),
    ("dar ou tirar acesso de um diretor", "Criar o usuário no Supabase > Authentication e, em Central de dados > Regras > Acessos, cadastrar o e-mail como VISUALIZADOR (tirar = desativar em Acessos)."),
    ("ver contratos, medições e anexos de uma obra ou credor", "Painéis > Obras e contratos (ou pergunte à Dexie, que usa a mesma base)."),
    ("gravar as métricas do mês (I03, I22, I27)", "Painéis > Métricas do mês."),
    ("gerar o relatório do balancete em PDF", "Balancete (contabilidade) > Relatório PDF (importar o balancete antes, em Importar balancete)."),
    ("gerar PDF ou Excel do que a Dexie mostrou", "Dexie > aba Relatório do painel ao lado (sai da última consulta)."),
    ("corrigir como uma conta do balancete entra no demonstrativo", "Balancete (contabilidade) > Mapa de contas (editar cria versão nova)."),
    ("ver o que foi feito e por quem", "Balancete: Histórico > Log de eventos; painel V2: Central de dados > Histórico e logs."),
    ("registrar uma regra da casa para a Dexie lembrar", "Diga a regra à Dexie: ela propõe a anotação e você confirma no cartão; edição em Dexie > Anotações."),
]

FLUXOS = [
    "Fechamento do mês pelo Sienge (Painel EnerMais V2): sincronizar → enviar arquivos que não vêm do Sienge (folha, projeção, orçamento) → conferir o quadro 'em uso' → confirmar o DRE → ver no Painel da Diretoria. Detalhes na Ajuda > Painel EnerMais (V2).",
    "Fechamento do balancete (contabilidade): receber o balancete → Importar balancete → revisar/confirmar → Demonstrativos → Relatório PDF → assinar (Autentique) → acompanhar no Painel do balancete. Detalhes na Ajuda > Fluxo do mês.",
    "Contratos: Obras e contratos filtra em cascata (obras → credores → contratos → detalhe); pendentes e cancelados ficam fora dos totais por padrão.",
]


def _norm(s) -> str:
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return t


def mapa_curto() -> str:
    """Resumo do menu (uma linha por pagina) para o prompt da Dexie."""
    return "\n".join(f"- {p['pagina']} ({p['secao']}; {p['quem'].split(' (')[0]}): {p['resumo'].split('. ')[0].rstrip('.')[:170]}." for p in PAGINAS)


def _entradas_ajuda() -> list:
    """(titulo, texto, origem) de tudo que a pagina Ajuda explica (fluxos e guias de problema)."""
    out = [(t, x, "Ajuda > Fluxo do mês") for t, x in AJ.FLUXO] + [(t, x, "Ajuda > Painel EnerMais (V2)") for t, x in AJ.FLUXO_V2]
    for nome, tup in AJ.GUIA_V2.items():
        out.append((nome, " | ".join(str(v) for v in (tup if isinstance(tup, (tuple, list)) else [tup])), "Ajuda > Painel EnerMais (V2) > o que aconteceu"))
    for nome, tup in AJ.GUIA_CONFERENCIAS.items():
        out.append((f"Conferência: {nome}", " | ".join(str(v) for v in tup), "Ajuda > Quando algo não bate"))
    return out


def consultar(pagina: str | None = None, busca: str | None = None) -> dict:
    """Sem argumentos: o menu e os fluxos. Com `pagina`: a descricao completa. Com `busca`: paginas, 'onde faco X' e trechos da Ajuda que contem as palavras."""
    base = {"guia_atualizado_em": ATUALIZADO_EM, "fonte": "guia interno do GDF (texto da equipe, não é dado do banco). Você explica; quem clica na tela é a pessoa."}
    if pagina:
        t = _norm(pagina)
        achadas = [p for p in PAGINAS if t in _norm(p["pagina"]) or _norm(p["pagina"]) in t]
        if not achadas:
            return {**base, "erro": "Página não encontrada no menu.", "paginas": [p["pagina"] for p in PAGINAS]}
        return {**base, "papeis": PAPEIS, "paginas": [dict(p) for p in achadas[:2]]}
    if busca:
        pal = [w for w in _norm(busca).split() if len(w) >= 3][:6]
        if not pal:
            return {**base, "erro": "Diga ao menos uma palavra com 3 letras ou mais."}

        def pontos(txt: str) -> int:
            n = _norm(txt)
            return sum(1 for w in pal if w in n)
        pgs = sorted(((pontos(p["pagina"] + " " + p["resumo"] + " " + " ".join(p["abas"])), p) for p in PAGINAS), key=lambda x: -x[0])
        onde = sorted(((pontos(a + " " + b), a, b) for a, b in ONDE), key=lambda x: -x[0])
        aj = sorted(((pontos(t + " " + x), t, x, o) for t, x, o in _entradas_ajuda()), key=lambda x: -x[0])
        return {**base, "busca": busca,
                "paginas": [{"pagina": p["pagina"], "secao": p["secao"], "quem": p["quem"], "resumo": p["resumo"], "abas": p["abas"]} for n, p in pgs if n][:3],
                "onde_faco": [{"tarefa": a, "como": b} for n, a, b in onde if n][:4],
                "trechos_da_ajuda": [{"titulo": t, "onde_na_ajuda": o, "texto": x[:1400]} for n, t, x, o in aj if n][:3]}
    return {**base, "papeis": PAPEIS, "menu": [{"secao": p["secao"], "pagina": p["pagina"], "quem": p["quem"], "resumo": p["resumo"].split(". ")[0].rstrip(".") + "."} for p in PAGINAS],
            "fluxos": FLUXOS, "onde_faco": [{"tarefa": a, "como": b} for a, b in ONDE],
            "dica": "Chame de novo com pagina=<nome> para o detalhe de uma tela, ou busca=<palavras> para achar tela, passo e texto da Ajuda."}
