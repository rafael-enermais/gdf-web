# -*- coding: utf-8 -*-
"""GDF - Dexie: BASE DE CONHECIMENTO (contabilidade, tributos, reforma tributaria, glossario do app).

Texto ESTATICO, escrito e revisado pela equipe (nao vem do banco). A Dexie consulta pela ferramenta `conhecimento` e deve citar a data de atualizacao
e mandar conferir com a contabilidade/assessoria tributaria: lei e regulamento mudam. Para aprimorar a base: edite os temas abaixo (um por chave),
atualize ATUALIZADO_EM e rode os testes. Fontes consultadas na ultima revisao (13/10/2026): texto da EC 132/2023, LC 214/2025 e LC 227/2026 segundo
resumos de Barbieri Advogados, Machado Meyer, Sienge e Senado/Fazenda; conferir sempre o texto oficial antes de decidir.
Nada aqui e' dado da EnerMais: sao regras gerais publicas. Nenhum nome de pessoa, credor ou cliente.
"""
from __future__ import annotations

ATUALIZADO_EM = "13/10/2026"

TEMAS = {
    "reforma_visao_geral": {
        "titulo": "Reforma tributária do consumo: o que é",
        "texto": (
            "Base legal: Emenda Constitucional 132/2023; Lei Complementar 214/2025 (regulamenta IBS, CBS e Imposto Seletivo); Lei Complementar 227/2026 (originada do PLP 108/24: "
            "cria o Comitê Gestor do IBS, ajusta a LC 214 e trata de contencioso administrativo). "
            "Tributos que somem: PIS, Cofins, IPI (zerado, exceto itens da Zona Franca de Manaus), ICMS e ISS. "
            "Tributos novos: CBS (federal, substitui PIS/Cofins), IBS (estados e municípios, substitui ICMS e ISS, administrado pelo Comitê Gestor) e Imposto Seletivo (IS, sobre bens e serviços "
            "prejudiciais à saúde e ao meio ambiente). IRPJ, CSLL e tributos sobre a folha NÃO fazem parte desta reforma. "
            "Ideias centrais: cobrança no destino; não cumulatividade ampla (crédito sobre quase tudo que a empresa compra para a atividade, desde que o fornecedor tenha pago o tributo); "
            "base ampla com poucas exceções; alíquotas reduzidas (60%, 50%, 30%) ou zero para setores específicos; split payment (o tributo é separado no pagamento); "
            "trava de 26,5% para a soma das alíquotas de referência de IBS e CBS (a alíquota de referência da CBS ainda dependia de fixação pelo Senado em out/2026). "
            "Imposto 'por fora': o IBS/CBS não integra a própria base de cálculo, o que muda a forma de formar preço."),
        "vigencia": "Resumo; confirmar alíquotas de referência e regulamentos infralegais antes de decidir.",
    },
    "reforma_cronograma": {
        "titulo": "Reforma tributária: cronograma 2026 a 2033",
        "texto": (
            "2026 (ano de teste): CBS 0,9% e IBS 0,1% só para teste; o recolhimento fica dispensado de quem cumpre as obrigações acessórias (destaque dos novos campos nas notas). "
            "Optantes do Simples não se sujeitam à alíquota de teste. PIS, Cofins, IPI, ICMS e ISS continuam valendo normalmente. "
            "2027: CBS passa a ser cobrada pela alíquota de referência (reduzida em 0,1 ponto percentual em 2027 e 2028); PIS e Cofins são extintos; Imposto Seletivo entra em vigor; IPI com alíquota zero (exceto ZFM); "
            "IBS segue em teste (0,05% estadual + 0,05% municipal). Crédito presumido de IBS/CBS passa a valer em 2027 (LC 227/26). "
            "2028: IBS ainda em teste; CBS com a redução de 0,1 p.p. "
            "2029 a 2032: substituição escalonada de ICMS e ISS: as alíquotas antigas caem para 90% (2029), 80% (2030), 70% (2031) e 60% (2032) enquanto o IBS sobe na mesma proporção. "
            "2033: ICMS e ISS extintos; IBS e CBS em alíquota plena. Saldos credores de ICMS homologados podem ser compensados com IBS em parcelas. "
            "Fundo de compensação de benefícios fiscais (União): cerca de R$ 160 bilhões a valores de 2023, corrigidos pelo IPCA, no período. "
            "Documentos fiscais eletrônicos (Ato Conjunto RFB/CGIBS 4/2026, de 30/07/2026): NF-e, NFC-e, CT-e e outros em 03/08/2026; NFS-e e NFCom em 01/10/2026; 15/11/2026 DeRE 2ª fase; "
            "01/12/2026 NF-e ABI, NFAg, NFGas e outros; 01/01/2027 optantes do Simples, Duimp e NF-e de importação. "
            "Split payment: acompanha a cobrança efetiva dos novos tributos (prevista a partir de 2027); a LC 227/26 fala em repasse ao fornecedor em até 3 dias úteis."),
        "vigencia": "Datas do ato conjunto e do Simples podem ser prorrogadas; conferir no Portal da Reforma Tributária.",
    },
    "reforma_construcao_incorporacao": {
        "titulo": "Reforma tributária na construção civil e incorporação",
        "texto": (
            "Operações com bens imóveis têm regime específico na LC 214/2025. Pontos mais citados: "
            "(1) Alíquota reduzida em 50% para incorporação/venda de imóveis (art. 261) e em 70% para locação, arrendamento e cessão onerosa; com referência de 26,5% isso dá cerca de 13,25% e 7,95%. "
            "(2) Redutor de ajuste: deduz da base valores como o terreno, contrapartidas urbanísticas/ambientais e outorga onerosa (art. 258); a LC 227/26 passou a referi-lo ao imóvel em que a construção é feita. "
            "(3) Redutor social: R$ 100 mil por unidade residencial e R$ 30 mil por lote; na locação residencial, R$ 600 por mês. "
            "(4) Créditos: materiais e serviços de obra aplicados na incorporação são tratados dentro da base (deduzidos), sem geração de crédito monetário separado, segundo os resumos consultados; vale revisar contrato a contrato. "
            "(5) Obras públicas: o ente contratante arca com o novo tributo e há previsão de reequilíbrio econômico-financeiro dos contratos. "
            "(6) RET (Regime Especial de Tributação, 4% da receita mensal; 1% no MCMV faixa 1): incorporações com patrimônio de afetação e opção pelo RET até 31/12/2028 podem seguir no regime atual com CBS de cerca de 2,08% sobre a receita no resto da vigência; "
            "novas incorporações a partir de 01/01/2029 entram no regime regular de IBS/CBS com redução de 50%. "
            "(7) Locação de até 90 dias por contribuinte do regime regular segue as regras de hotelaria (LC 227/26). Permuta com torna: a base muda conforme quem paga a torna. "
            "Atenção: a forma de recolhimento (momento do fato gerador, regime de caixa x competência na incorporação) e as regras de crédito têm nuances; confirmar com a assessoria tributária."),
        "vigencia": "Resumo de fontes secundárias; os artigos citados devem ser conferidos no texto oficial.",
    },
    "reforma_impacto_gestao": {
        "titulo": "Reforma tributária: o que a gestão financeira deve acompanhar",
        "texto": (
            "Para a gestão da EnerMais (construção, energia e administração do grupo): "
            "1) Preço e contratos: separar preço e tributo na negociação; incluir cláusulas objetivas de revisão por mudança de carga tributária; revisar contratos longos de obra assinados antes de 2027. "
            "2) Fornecedores: crédito só existe se o fornecedor recolheu; fornecedor do Simples ou MEI gera menos crédito; cadastro e documento fiscal correto passam a valer dinheiro. "
            "3) Sistemas: ERP e emissão de NF-e/NFS-e com os novos campos de IBS/CBS (2026); apuração paralela (regime atual + novo) de 2027 a 2032. "
            "4) Caixa: o split payment retira o tributo na liquidação, então o fluxo de caixa e o capital de giro mudam; vale simular com o ciclo financeiro (PMR, PMP, necessidade de capital de giro). "
            "5) Resultado: receita e custo passam a ser avaliados líquidos de IBS/CBS; margens e BDI devem ser comparados com a mesma base antes e depois da transição. "
            "6) Controle: acompanhar mês a mês a carga tributária sobre o faturamento (hoje a DRE do app reconstrói impostos sobre a receita pela conta 02.02) e documentar créditos de PIS/Cofins remanescentes. "
            "7) Governança: decidir por empreendimento se mantém o RET ou migra, com a contabilidade, antes dos prazos. "
            "Posso ajudar a levantar nos dados do app: prazos de recebimento/pagamento, concentração de fornecedores, saldo devedor de financiamentos e evolução da receita para as simulações; "
            "alíquotas e enquadramentos são da assessoria tributária."),
        "vigencia": "Orientação geral de gestão; não substitui parecer tributário.",
    },
    "contabilidade_demonstrativos": {
        "titulo": "Demonstrações contábeis: BP, DRE, DFC e conceitos-base",
        "texto": (
            "Balanço Patrimonial (BP): Ativo = Passivo + Patrimônio Líquido. Circulante = até 12 meses ou ciclo operacional; não circulante = depois. "
            "DRE: Receita bruta − deduções (impostos sobre a receita, devoluções) = receita líquida; − custos = lucro bruto; − despesas operacionais = resultado operacional; ± resultado financeiro; − IRPJ/CSLL = lucro líquido. "
            "DFC (fluxo de caixa): atividades operacionais, de investimento e de financiamento; método direto ou indireto. "
            "Regime de competência: receita e despesa entram quando ocorrem, independentemente do caixa; regime de caixa: quando pago/recebido. O Painel da Diretoria mistura propositalmente fontes de competência (DRE) e de caixa (contas pagas). "
            "Conciliação: a DRE gerencial por obra deve fechar com a DRE contábil; diferenças típicas são previsão, NF desfeita, distrato e reapropriação de custos. "
            "Provisões e contingências (CPC 25): provável = provisiona; possível = divulga; remoto = nada. Ajuste a valor presente (CPC 12) para prazos longos relevantes. "
            "Resultado gerencial x contábil: o gerencial costuma tirar efeitos não recorrentes e agrupar por obra; sempre explicar a diferença ao comparar."),
        "vigencia": "Conceitos estáveis (CPCs/NBC).",
    },
    "contabilidade_construcao_cpcs": {
        "titulo": "CPCs que mais pesam em construção, incorporação e energia",
        "texto": (
            "CPC 47 (IFRS 15, receita de contrato com cliente): receita reconhecida conforme o cumprimento das obrigações de desempenho; em obras longas, ao longo do tempo (método de custos incorridos / percentual de evolução, POC). "
            "ICPC 02 e OCPC 04: aplicação do CPC 47 a incorporação imobiliária (custo do terreno e custos incorridos, distratos, encargos financeiros). "
            "CPC 20 (custos de empréstimos): juros de financiamentos que financiam ativo qualificável (obra em andamento) são capitalizados. "
            "CPC 06 (arrendamentos): direito de uso e passivo de arrendamento para locações relevantes. "
            "CPC 27 (imobilizado) e CPC 28 (propriedade para investimento): imóveis mantidos para renda ou valorização. "
            "CPC 25 (provisões e contingências) e CPC 24 (eventos subsequentes). "
            "CPC 32 (tributos sobre o lucro): impostos diferidos. "
            "CPC 48 (instrumentos financeiros): classificação e perdas de crédito esperadas em contas a receber. "
            "CPC 26 (apresentação das demonstrações) e CPC 03 (fluxo de caixa). "
            "Transmissão e geração de energia usam também ICPC 01 / CPC 47 (contratos de concessão): ativo contratual e receita de construção; consultar a contabilidade da concessão para o tratamento do caso."),
        "vigencia": "Pronunciamentos vigentes; conferir revisões do CPC.",
    },
    "indicadores_formulas": {
        "titulo": "Indicadores financeiros: fórmulas e como ler",
        "texto": (
            "Liquidez corrente = Ativo circulante ÷ Passivo circulante. Liquidez seca = (AC − estoques) ÷ PC. Liquidez geral = (AC + realizável a longo prazo) ÷ (PC + exigível a longo prazo). "
            "Endividamento = (Passivo circulante + não circulante) ÷ Ativo; composição do endividamento = PC ÷ (PC + PNC). "
            "Margem bruta = lucro bruto ÷ receita líquida; margem líquida = lucro líquido ÷ receita líquida; EBITDA = resultado antes de juros, impostos sobre o lucro, depreciação e amortização. "
            "ROA = lucro líquido ÷ ativo; ROE = lucro líquido ÷ patrimônio líquido. Alavancagem = dívida líquida ÷ EBITDA. "
            "BDI (benefícios e despesas indiretas): no painel da Diretoria, BDI = Receita − Custos de obra no padrão da contabilidade (DRE 04+06+08+10+12; resultado antes da administração). "
            "Prazo médio de recebimento (PMR) = média de dias entre emissão e vencimento dos títulos a receber; prazo médio de pagamento (PMP), idem para a pagar; "
            "ciclo financeiro = PMR − PMP; necessidade de capital de giro (NCG) = gasto diário × ciclo (quando positivo), como o app calcula. Ciclo positivo = a empresa paga antes de receber. "
            "Inadimplência = vencidos e não pagos na data de posição, por faixa de atraso. Desvio de orçamento = realizado − orçado (positivo = gastou mais). "
            "Hora extra ÷ base: no app, (HE + DSR s/ HE) ÷ remuneração líquida (proventos sem HE/DSR menos descontos)."),
        "vigencia": "Fórmulas usuais de análise; o app documenta as suas na tela Ajuda.",
    },
    "tributos_atuais": {
        "titulo": "Tributos vigentes (até a transição) e retenções comuns",
        "texto": (
            "Lucro real: IRPJ 15% + adicional de 10% sobre o lucro que excede R$ 20 mil por mês (R$ 240 mil por ano) e CSLL 9%; PIS/Cofins não cumulativo 1,65% + 7,6% com créditos. "
            "Lucro presumido: base de presunção sobre a receita (comércio/indústria 8% IRPJ e 12% CSLL; serviços em geral 32%; incorporação e construção com regras próprias); PIS/Cofins cumulativo 0,65% + 3%. "
            "ISS: municipal, em regra de 2% a 5% sobre serviços; construção civil tem regras específicas de local e de base (subempreitada/materiais). "
            "RET da incorporação: 4% da receita mensal recebida (inclui IRPJ, CSLL, PIS e Cofins); 1% no MCMV faixa 1; exige patrimônio de afetação. "
            "Retenções comuns na fonte: INSS 11% sobre cessão de mão de obra/empreitada (nota fiscal de serviço); ISS retido conforme o município; IRRF 1,5% sobre serviços profissionais; "
            "CSRF (CSLL 1% + PIS 0,65% + Cofins 3% = 4,65%) em pagamentos de PJ a PJ de serviços sujeitos. Há muitas exceções por município, porte e regime do prestador. "
            "Folha: INSS patronal, RAT/FAP, terceiros, FGTS 8%. Tudo isso continua valendo até a extinção gradual prevista em 2027–2033 (PIS/Cofins em 2027; ICMS/ISS até 2033)."),
        "vigencia": "Regras gerais; limites e alíquotas podem mudar por lei. Conferir com a contabilidade.",
    },
    "glossario_gdf": {
        "titulo": "Glossário e regras do GDF (como o app calcula)",
        "texto": (
            "Painel da Diretoria: Receita − Custos (DRE 04+06+08+10+12) = BDI; BDI − Administração = Resultado; mostra realizado x previsto (projeção) por mês e somado no período. "
            "Origem do DRE do mês: 1) DRE confirmado pela contabilidade; 2) DRE oficial importado (PDF do Sienge); 3) reconstruído pela API do Sienge (a conferir; não é número oficial). "
            "Despesas: contas pagas (baixas) com as regras da aba Regras (contas excluídas como pessoal CLT, encargos e transferências; previsão fora). "
            "Previsão: título marcado como previsão no Sienge; fica fora de despesas e indicadores por padrão. "
            "Distrato e NF desfeita: títulos a receber cujas baixas de distrato somam o valor todo, e notas desfeitas, ficam fora da receita reconstruída. "
            "Grupo ENERMAIS: as 6 empresas do grupo; operações entre elas são retiradas dos indicadores por padrão (intragrupo), com opção de incluir tudo para comparar. "
            "Pessoas: CLT pela folha importada (recibos) e PJ pelas contas pagas de salários PJ (nome fantasia do cadastro de credores do Sienge quando houver). "
            "Financiamentos/Investimentos: posição de hoje (parcelas não pagas), independente do período escolhido. "
            "Fontes de dado: Sienge (API, só leitura), PDFs/planilhas importados em Importações (V2), histórico do painel importado (HTML da diretoria) e regras/cadastros do próprio GDF. "
            "Papéis: EDITOR vê tudo; VISUALIZADOR vê só o Painel da Diretoria."),
        "vigencia": "Descreve a versão atual do app.",
    },
}


def indice() -> list:
    return [{"tema": k, "titulo": v["titulo"]} for k, v in TEMAS.items()]


def consultar(tema: str | None = None, busca: str | None = None) -> dict:
    """Devolve um tema (pela chave), os temas que contem as palavras de `busca`, ou o indice se nada for pedido. Sempre inclui a data de atualizacao da base."""
    base = {"base_atualizada_em": ATUALIZADO_EM, "fonte": "base de conhecimento interna do GDF (regras gerais públicas, revisada pela equipe; não é dado do banco)"}
    if tema:
        t = TEMAS.get(str(tema))
        if not t:
            return {**base, "erro": f"Tema inexistente. Temas: {', '.join(TEMAS)}."}
        return {**base, "tema": tema, "titulo": t["titulo"], "texto": t["texto"], "vigencia": t["vigencia"]}
    if busca:
        palavras = [p for p in str(busca).lower().split() if len(p) >= 3][:6]
        achados = [k for k, v in TEMAS.items() if palavras and any(p in (v["titulo"] + " " + v["texto"]).lower() for p in palavras)]
        return {**base, "busca": busca, "temas_encontrados": [{"tema": k, "titulo": TEMAS[k]["titulo"]} for k in achados] or "nenhum; veja o índice",
                "dica": "Chame de novo com tema=<chave> para ler o texto."}
    return {**base, "indice": indice()}
