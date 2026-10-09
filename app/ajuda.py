# -*- coding: utf-8 -*-
"""GDF - textos da pagina Ajuda (fluxo do mes, o que fazer quando uma conferencia falha, glossario). Modulo puro."""
from __future__ import annotations

FLUXO = [
    ("Receber o balancete", "O contador envia o balancete de cada mês em CSV ou PDF (pode ser o PDF assinado; o GDF só lê, nunca altera)."),
    ("Importar balancete", "Menu **Importar balancete**: envie o arquivo do mês. Veja a lista de conferências (✅/❌) antes de confirmar. Se houver ❌, consulte o guia abaixo."),
    ("Revisar", "Na própria tela de **Importar**: veja as conferências e, se os números batem com a contabilidade, marque **\"Revisei os números e confirmo\"** — o balancete entra já como **REVISADA**. Quem já entrou como rascunho é confirmado em **Histórico**."),
    ("Conferir os demonstrativos", "Menu **Demonstrativos**: Balanço, DRE, Indicadores, Composição de Saldos (aqui dá para digitar apelidos para os nomes cortados) e Conferências."),
    ("Gerar o relatório", "Menu **Relatório PDF**: gere o rascunho, ajuste os textos de leitura, e quando tudo estiver revisado gere a **versão final**. Se ainda houver pendência (balancete em rascunho, conferência com falha, assinante sem nome), dá para gerar mesmo assim: o app pede uma marcação e deixa o aviso no log. A ordem em que os balancetes são enviados não importa."),
    ("Se faltar algum mês", "O app **nunca trava** por falta de balancete. O ideal é importar todos os meses (relatório completo). Se faltar algum, ele usa o **balancete acumulado** (01/01 até o mês) para completar o que der e marca **n/d** só no que não dá para calcular, sempre explicando o motivo e o que importar. "
     "O quadro **Cobertura do ano** (em **Importar**) mostra como sairia o relatório de cada mês; nos **Demonstrativos** e no **Relatório PDF**, o aviso **O que falta e o que acontece se gerar assim** lista cada item n/d. "
     "Quando falta um mês no meio do ano, **você escolhe como gerar** (botões de opção acima dos números): **ano completo com n/d**; **só o período depois da lacuna** (ex.: abril a agosto, com abertura em 31/03 e a DRE somando só esses meses); ou **até o último mês completo antes da lacuna** (ex.: janeiro a fevereiro). Em qualquer caminho o relatório diz qual período cobre e o que ficou de fora. "
     "O PDF mostra n/d e ganha a página **Dados incompletos**; nenhum número é estimado. O app só recusa gerar quando não há nenhum balancete do mês escolhido."),
    ("Assinar (opcional)", "Assine a versão final no Autentique (fora do GDF). Se quiser deixar o registro no GDF, use **Relatório PDF → Registrar assinatura** e envie o PDF assinado; dá para substituir ou desfazer quando quiser (nada trava)."),
    ("Acompanhar", "Menu **Painel**: KPIs e evolução mês a mês. Na página **Início** fica o quadro de situação do ano."),
]

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
