# -*- coding: utf-8 -*-
"""GDF - textos da pagina Ajuda (fluxo do mes, o que fazer quando uma conferencia falha, glossario). Modulo puro."""
from __future__ import annotations

FLUXO = [
    ("Receber o balancete", "O contador envia o balancete de cada mês em CSV ou PDF (pode ser o PDF assinado; o GDF só lê, nunca altera). CSV e PDF dão os **mesmos números**; a única diferença é que no PDF alguns nomes muito longos (fornecedores) saem cortados, então, tendo os dois, prefira o CSV. Não importe os dois do mesmo período: o app avisa e mantém só um ativo."),
    ("Importar balancete", "Menu **Importar balancete**: envie o arquivo do mês. Veja a lista de conferências (✅/❌) antes de confirmar. Se houver ❌, consulte o guia abaixo."),
    ("Revisar", "Na própria tela de **Importar**: veja as conferências e, se os números batem com a contabilidade, marque **\"Revisei os números e confirmo\"** — o balancete entra já como **REVISADA**. Quem já entrou como rascunho é confirmado em **Histórico**."),
    ("Conferir os demonstrativos", "Menu **Demonstrativos**: Balanço, DRE, Indicadores, Composição de Saldos (aqui dá para digitar apelidos para os nomes cortados) e Conferências."),
    ("Gerar o relatório", "Menu **Relatório PDF**: gere o rascunho, ajuste os textos de leitura, e quando tudo estiver revisado gere a **versão final**. Se ainda houver pendência (balancete em rascunho, conferência com falha, assinante sem nome), dá para gerar mesmo assim: o app pede uma marcação e deixa o aviso no log. A ordem em que os balancetes são enviados não importa."),
    ("Se faltar algum mês", "O app **nunca trava** por falta de balancete. O ideal é importar todos os meses (relatório completo). Se faltar algum, ele usa o **balancete acumulado** (01/01 até o mês) para completar o que der e marca **n/d** só no que não dá para calcular, sempre explicando o motivo e o que importar. Nenhum número é estimado."),
    ("Assinar (opcional)", "Assine a versão final no Autentique (fora do GDF). Se quiser deixar o registro no GDF, use **Relatório PDF → Registrar assinatura** e envie o PDF assinado; dá para substituir ou desfazer quando quiser (nada trava)."),
    ("Acompanhar", "Menu **Painel**: KPIs e evolução mês a mês. Na página **Início** fica o quadro de situação do ano."),
]

# detalhes (em topicos) de passos do fluxo: mostrados logo abaixo do passo
FLUXO_DETALHES = {
    "Se faltar algum mês": [
        "O quadro **Cobertura do ano** (em **Importar**) mostra como sairia o relatório de cada mês.",
        "Nos **Demonstrativos** e no **Relatório PDF**, o aviso **O que falta e o que acontece se gerar assim** lista cada item n/d e o que importar para resolver.",
        "Quando falta um mês no meio do ano, **você escolhe como gerar** (opções acima dos números): **ano completo com n/d**; **só o período depois da lacuna** (ex.: abril a agosto, com abertura em 31/03 e DRE somando só esses meses); ou **até o último mês completo antes da lacuna** (ex.: janeiro a fevereiro). Se só existir um caminho, o app apenas explica qual é.",
        "Em qualquer caminho o relatório diz qual período cobre e o que ficou de fora; o PDF mostra n/d e ganha a página **Dados incompletos**.",
        "O app só recusa gerar quando não há nenhum balancete do mês escolhido.",
    ],
}

# grupo da conferencia (motor) -> (o que significa, causas provaveis, o que fazer)
GUIA_CONFERENCIAS = {
    "arquivo": ("O leitor não conseguiu entender alguma linha de conta do arquivo.",
                "Arquivo de outro relatório, exportação cortada ou layout diferente do habitual.",
                "Exporte de novo o relatório Balancete (Débito/Crédito em CSV ou Societário em PDF), completo e sem filtros. Se continuar, envie o arquivo ao suporte."),
    "Fechamento": ("O Ativo não é igual ao Passivo + resultado em aberto (conta 8).",
                   "Arquivo incompleto ou com filtro (por exemplo, sem contas zeradas ou sem as contas sintéticas 1 e 2).",
                   "Exporte novamente o balancete inteiro. Se o arquivo estiver correto no sistema contábil, confirme com o contador antes de importar."),
    "Soma das contas": ("Uma conta sintética (com filhas) não bate com a soma das analíticas dela.",
                        "Página faltando no PDF, linha cortada ou filtro aplicado na exportação.",
                        "Reenvie o arquivo completo. As contas citadas no detalhe mostram onde está a diferença."),
    "Movimento": ("Saldo anterior + movimento do mês não dá o saldo final em alguma conta.",
                  "Coluna lida errada, arquivo editado à mão ou exportação parcial.",
                  "Não edite o arquivo. Reexporte do sistema contábil e importe de novo."),
    "Mapa de contas": ("Existe conta com saldo ou movimento que não está ligada a nenhuma linha dos demonstrativos.",
                       "Conta nova no plano de contas (novo banco, novo tipo de despesa) ou mudança de código.",
                       "Menu **Mapa de contas**: veja a lista das contas sem chave. Conta nova de uma linha que já existe entra com o prefixo dela; "
                       "se for um tipo novo de linha, peça ao suporte para incluir."),
    "Continuidade": ("O saldo anterior de uma conta neste mês não é o saldo final do mês anterior.",
                     "Falta um mês, ou o mês anterior importado é outro arquivo (retificado ou de outra versão).",
                     "No **Histórico**, confira qual importação do mês anterior está ativa; importe a versão correta (a antiga fica guardada, nada se perde)."),
    "Encerramento": ("O saldo anterior de Prejuízos Acumulados não é a soma dos resultados dos meses anteriores.",
                     "Algum mês anterior foi retificado, ou houve lançamento direto na conta de Prejuízos Acumulados.",
                     "Confirme com o contador se houve ajuste ou retificação. Se foi legítimo, importe a versão correta dos meses afetados."),
    "Balanço calculado": ("O balanço calculado pelo app não fecha (Ativo ≠ Passivo + PL) ou não bate com a conta 1.",
                          "Quase sempre uma conta sem chave no mapa.",
                          "Veja **Mapa de contas → Contas sem chave** e a conferência 'Mapa de contas' do mesmo mês."),
    "Acumulado x mensal": ("O saldo final do balancete acumulado não bate com o saldo anterior do mensal do mês seguinte.",
                           "O acumulado ou o mensal é de outra versão (retificado) ou de outro período.",
                           "Confira os arquivos no **Histórico**. Enquanto não bater, o acumulado **não é usado** nas contas (aparece em “O que falta”) e nada é calculado com dado incoerente."),
    "Mensal x acumulado": ("A soma dos meses não bate com o balancete acumulado do mesmo período.",
                           "Um mês foi retificado depois de o acumulado ser emitido (ou vice-versa).",
                           "Compare o mês indicado com o do acumulado; importe a versão atual do mês correto. Diferenças só de centavos entram em 'Outros ajustes líquidos'."),
}

QUANDO_PEDIR_AJUDA = ("Antes de pedir ajuda, anote: o **mês**, a **tela** em que aconteceu e a **mensagem** que apareceu (pode tirar um print). "
                      "Não envie senhas. O **Histórico → Log de eventos** mostra o que foi feito e por quem.")


# ------------------------------------------------------------------ Painel EnerMais (V2): fluxo, o que fazer quando algo nao bate
FLUXO_V2 = [
    ("Para que serve", "O **Painel EnerMais** (menu à esquerda) monta o resultado do Grupo EnerMais: o que vem do Sienge o app busca sozinho; o que não vem do Sienge (PDFs e planilha) você envia na aba **Importações (V2)**. É separado do balancete (V1): uma coisa não mexe na outra."),
    ("Sincronizar com o Sienge", "Aba **Sincronizar com o Sienge**: o app já busca sozinho todo dia os últimos 365 dias de contas a pagar e a receber. O botão **Buscar no Sienge** serve para atualizar na hora. O app só **lê** o Sienge, nunca grava lá."),
    ("Enviar os arquivos", "Aba **Importações (V2)**: envie o **DRE gerencial** (PDF por obra), a **folha** (PDF de recibos da Construtora e da Energia), a **projeção de receita** (xlsx) e o **Orçamento ADM** (PDF). Depois de ler, o app mostra o que entendeu; confira e clique em **Salvar**. Depois de salvo aparece **Já salvo no banco** com número, mês, linhas, quem e quando."),
    ("Conferir o que está em uso", "No topo de **Importações (V2)** o quadro mostra, mês a mês, o que está em uso (DRE, folha de cada empresa, projeção e orçamento). Enviar de novo o **mesmo arquivo** não duplica nada; enviar um **novo do mesmo mês** substitui o anterior (o antigo fica guardado)."),
    ("Corrigir ou desfazer", "Ainda em **Importações (V2)**: no **histórico** dá para marcar uma importação como **fora de uso** e depois **reativar** (nada é apagado). Se a leitura errou um valor, edite na grade: escolha a importação, corrija, escreva o motivo e salve; o **antes e o depois** ficam no histórico de edições. Dá para **adicionar linhas** que a leitura perdeu. Os dados que vêm direto da API do Sienge **não** são editados."),
    ("Histórico do ano (painel da contabilidade)", "Em **Importações (V2)** envie o **HTML do painel da contabilidade** (ex.: “Painel EnerMais Setembro_2026.html”). O app guarda só os números do ano (acumulado jan–set, desvio mensal, recomposição out–dez, horas extras e custos com pessoas), sem nomes de colaboradores ou credores, e eles passam a aparecer na aba **Resultado** (período “Ano até o mês”, desvio mensal e recomposição) e na aba **Pessoas** do Painel da Diretoria, e no PDF. Para atualizar, envie o HTML do mês seguinte."),
    ("Painel da Diretoria e acessos", "**Painel da Diretoria** é uma página só de leitura, no mesmo formato do painel da contabilidade: abas **Resultado, Obras, Administração, Despesas, Pessoas, Indicadores financeiros e Financiamentos**, com busca e clique para detalhar (conta → credor → obra). Cada aba só carrega quando é aberta. No topo, o filtro **Período** vale para todas as abas: Mês, Últimos 3 ou 6 meses, **Ano até o mês** (padrão), Últimos 12 meses ou Personalizado (de – até). Resultado e Obras somam os meses com DRE (confirmado / oficial) e avisam quais meses ficaram de fora. Nos Indicadores, prazos médios e gasto ignoram o que não é fornecedor/cliente de verdade (lançamentos sem credor, banco/caixa, financiamentos e as empresas do grupo ENERMAIS); a caixa “Incluir tudo” volta ao cálculo completo. Em Pessoas, as listas de credores não mostram as empresas do grupo e a tabela por obra usa o mesmo nome da aba Obras. O PJ por colaborador vem das contas pagas “Salários PJ” e aparece pelo **nome fantasia** do cadastro do credor (a razão social fica ao lado); para carregar o nome fantasia, execute o SQL-30 e clique em “Atualizar cadastros” no Painel EnerMais. O Painel se adapta ao tamanho da tela (cartões e gráficos quebram em linhas conforme a largura). Em “Personalizado” escolha primeiro o mês inicial (De) e depois o final (Até). As abas **Financiamentos** e **Investimentos** mostram a posição de hoje (o que falta pagar) e por isso não mudam com o período; “Recomposição out–dez” também é fixa. Para dar acesso a um diretor: crie o usuário em **Supabase → Authentication** e, em **Regras → Acessos**, cadastre o e-mail como **VISUALIZADOR**; ele só enxerga essa página. Para tirar o acesso, desative em Acessos (não exclua o usuário no Authentication sem checar: o login é compartilhado com os outros apps)."),
    ("Dexie, a assistente de IA", "Menu **Dexie (assistente IA)** (só para quem edita; o login de visualização não vê). Converse em português: ela **lê** os dados do app (resultado, DRE, obras, despesas, administração, pessoas, indicadores, financiamentos, sincronizações, logs) e responde só com o que está no banco; consulta uma **base de conhecimento** (contabilidade, CPCs, fórmulas de indicadores, tributos e a **reforma tributária**: IBS, CBS, cronograma 2026–2033, construção e incorporação) e sempre manda confirmar com a contabilidade o que depender de lei; pede **gráfico** da última consulta, baixa a tabela em **Excel** e gera um **relatório em PDF** (título, resumo, gráfico e tabela) pelo painel ao lado. Ela também pode **propor** buscar o Sienge ou atualizar cadastros: aparece um cartão e só executa depois do seu clique em **Confirmar e executar** (fica em Histórico e logs). **Conferência:** peça \"confira o ano com o painel da contabilidade\" e ela monta a tabela app × painel (mês de referência, jan até o mês anterior e acumulado), com a diferença e a origem do dado. **Anotações (o que ela aprende):** quando você ensina uma regra ou definição, ela sugere guardar num cartão e só vale depois do seu clique em **Guardar anotação** (SQL-33); a aba **Anotações** do painel ao lado lista, edita (versão nova) e desativa; ela não guarda valores, dados pessoais nem links. O relatório também sai em **PDF da conversa inteira**. Não grava, não apaga e não importa arquivos (as anotações e as ações confirmadas por você são as únicas gravações). **Memória:** com o SQL-31 rodado, a conversa continua quando você volta (últimas 24 mensagens); **Nova conversa** arquiva e começa limpa (nada é apagado). Precisa do secret **ANTHROPIC_API_KEY** no Streamlit."),
    ("Cadastros", "No fim de **Importações (V2)**: **departamento da folha → obra** e **credores em “Outros credores/Dir”**. Pode corrigir ou acrescentar; nada é apagado."),
    ("Resultado: confirmar o DRE do mês", "Aba **Resultado**: compara o DRE do PDF com o recalculado pela API. Em **Confirmar o DRE do mês** escolha, linha a linha, a fonte: **API**, **PDF** ou **MANUAL** (você digita o valor, útil se a leitura do PDF falhou). Ajuste manual exige uma **observação** e fica registrado com o valor da API e do PDF. Confirmar de novo não apaga a anterior."),
    ("Despesas, Obras, Administração e Pessoas", "**Despesas**: pago por conta, com as regras da aba **Regras**. **Obras**: resultado por obra e projeção × realizado. **Administração**: despesas das unidades ADM, credores, orçado × realizado e desvio mês a mês. **Pessoas**: série de receita, colaboradores e folha por obra, horas extras ÷ salários."),
    ("Regras e Histórico e logs", "**Regras**: o que entra e o que sai de cada aba; proposta vira confirmada quando a contabilidade confirma. **Histórico e logs**: tudo que foi sincronizado, importado, editado ou deu erro."),
]

# situacao do Painel EnerMais -> (o que significa, causas provaveis, o que fazer)
GUIA_V2 = {
    "A receita da API não bate com o PDF": ("O DRE recalculado pela API tem receita diferente da do PDF do Sienge.",
                                            "NF desfeita por distrato (o Sienge ainda lista na API mas o DRE não conta) ou documento de previsão.",
                                            "Na aba **Resultado**, deixe marcados **Tirar NFs desfeitas (distrato)** e **Tirar documentos de previsão**. Se ainda houver diferença, a tabela de conferência mostra a conta e a obra."),
    "O custo da API é maior que o do PDF": ("Em Mão de obra, Materiais ou Frota a API soma mais que o PDF.",
                                           "(1) INSS e FGTS pagos em guia entram na API e o PDF só leva a parte já apropriada (regra aguardando a contabilidade); (2) títulos desfeitos (cancelados, substituídos ou abatidos com adiantamento) e multas (tipo AEJ), que o Sienge não conta no DRE; (3) diferenças pequenas e redondas de lançamento.",
                                           "Na aba **Resultado** use **Tirar títulos a pagar desfeitos e multas** (proposta, aguarda a contabilidade) para ver o efeito. Enquanto a regra não for confirmada, escolha a fonte **PDF** na linha ao confirmar o DRE."),
    "A leitura de um PDF errou um valor": ("O app leu um número diferente do que está no PDF, ou perdeu uma linha.",
                                          "Layout diferente do habitual, página cortada ou texto ilegível.",
                                          "Em **Importações (V2)**, edite o valor na grade (com motivo) ou adicione a linha. No DRE do mês use **MANUAL** na linha. Nada é apagado e o antes/depois fica no histórico."),
    "Subi o arquivo errado": ("Foi salvo um arquivo que não era o certo.",
                              "Arquivo do mês errado ou versão antiga.",
                              "Em **Importações (V2) → histórico**, marque a importação como **fora de uso** (e reative a anterior, se quiser). Depois envie o arquivo certo."),
    "A projeção não casa com as obras": ("Alguma obra da planilha de projeção aparece em “sem correspondência”.",
                                        "O nome da obra na planilha é diferente do nome no DRE ou no cadastro de obras.",
                                        "Ajuste o nome em **Cadastros** (departamento → obra) ou corrija a planilha e envie de novo."),
    "Um credor não aparece em Outros credores/Dir": ("O credor foi cadastrado mas o valor continua no ranking.",
                                                    "O nome no Sienge é diferente do que foi cadastrado (o app reconhece o credor pelo **começo** do nome).",
                                                    "Em **Importações (V2) → credores**, ajuste o texto para o começo exato do nome no Sienge."),
}

