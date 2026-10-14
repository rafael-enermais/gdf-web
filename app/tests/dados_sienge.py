# -*- coding: utf-8 -*-
"""Dados SINTETICOS no formato da API do Sienge (bulk-data/outcome e income), para os testes. Nenhum dado real."""


def _c(plano, nome, rate, cc=1, cc_nome="CC TESTE"):
    return {"financialCategoryId": plano, "financialCategoryName": nome, "financialCategoryRate": rate, "costCenterId": cc,
            "costCenterName": cc_nome, "projectId": 5, "projectName": "CONSTRUTORA"}


def _pg(seq, data, liq, oper=1, nome="Pagamento"):
    return {"sequencialNumber": seq, "paymentDate": data, "netAmount": liq, "grossAmount": liq, "operationTypeId": oper, "operationTypeName": nome}


def outcome():
    """4 titulos: material (rateio 60/40), salario PJ (conta de pessoas), transferencia entre empresas e um pago em agosto."""
    return [
        {"billId": 1, "installmentId": 1, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "CP", "documentIdentificationId": "NFS ",
         "documentIdentificationName": "NOTA FISCAL DE SERVICOS", "forecastDocument": "N", "documentNumber": "10", "creditorId": 77, "creditorName": "FORNECEDOR TESTE",
         "issueDate": "2026-08-20", "dueDate": "2026-09-10", "originalAmount": 1000.0, "businessTypeId": 10, "businessTypeName": "CONSTRUTORA - OBRAS",
         "projectId": 5, "projectName": "CONSTRUTORA", "payments": [_pg(1, "2026-09-10", 1000.0)],
         "paymentsCategories": [_c("2010104", "Material de Consumo | Obra", 60, 1049, "CON - ANASTACIO - LOTE 11"), _c("2010404", "Combustível | Obra", 40, 1023, "CON - OPGW II")]},
        {"billId": 2, "installmentId": 1, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "CP", "documentIdentificationId": "HOL ",
         "documentIdentificationName": "HOLERITE", "creditorId": 78, "creditorName": "COLABORADOR TESTE", "issueDate": "2026-09-05", "dueDate": "2026-09-05",
         "originalAmount": 500.0, "payments": [_pg(1, "2026-09-12", 500.0)], "paymentsCategories": [_c("2010201", "Salários PJ | Obra", 100)]},
        {"billId": 3, "installmentId": 2, "companyId": 1, "companyName": "ENERGIA", "originId": "CP", "documentIdentificationId": "FAT ", "creditorId": 79,
         "creditorName": "OUTRA EMPRESA DO GRUPO", "issueDate": "2026-09-01", "dueDate": "2026-09-20", "originalAmount": 300.0,
         "payments": [_pg(1, "2026-09-20", 300.0), _pg(2, "2026-09-21", 50.0, 3, "Cancelamento")],
         "paymentsCategories": [_c("1030202", "(-) Transferências Entre Empresas", 100)]},
        {"billId": 4, "installmentId": 1, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "ME", "documentIdentificationId": "PCT ", "creditorId": 80,
         "creditorName": "FORNECEDOR 2", "issueDate": "2026-08-01", "dueDate": "2026-08-30", "originalAmount": 700.0,
         "payments": [_pg(1, "2026-08-30", 700.0)], "paymentsCategories": [_c("2010104", "Material de Consumo | Obra", 100)]},
    ]


def income():
    return [{"billId": 50, "installmentId": 1, "companyId": 5, "companyName": "CONSTRUTORA", "originId": "NS", "documentIdentificationId": "NFS ",
             "clientId": 900, "clientName": "CLIENTE TESTE", "issueDate": "2026-09-15", "dueDate": "2026-09-30", "originalAmount": 2000.0,
             "receipts": [{"sequencialNumber": 1, "paymentDate": "2026-09-30", "netAmount": 1800.0, "grossAmount": 2000.0, "taxAmount": 200.0,
                           "operationTypeId": 1, "operationTypeName": "Recebimento"}],
             "receiptsCategories": [{"financialCategoryId": "1010101", "financialCategoryName": "Receitas de Serviços", "financialCategoryRate": 100,
                                     "costCenterId": 1049, "costCenterName": "CON - ANASTACIO - LOTE 11", "projectId": 5, "projectName": "CONSTRUTORA"}]}]


def movimentos_banco():
    """Movimentos bancarios sinteticos: 2 avisos de saida sem titulo (um com 2 rateios), 1 entrada, 1 saida com titulo, 1 saida sem plano."""
    cat = lambda cod, nome, taxa: {"financialCategoryId": cod, "financialCategoryName": nome, "financialCategoryRate": taxa, "costCenterId": 1, "costCenterName": "SEDE"}  # noqa: E731
    return [
        {"bankMovementId": 9001, "billId": None, "companyId": 1, "companyName": "ENERGIA", "bankMovementOriginId": "BC", "bankMovementOperationType": "S",
         "bankMovementOperationId": 2, "bankMovementOperationName": "Pagamento", "bankMovementDate": "2026-09-01", "bankMovementAmount": 100.0,
         "documentIdentificationId": "AV  ", "documentIdentificationName": "AVISO DE LANÇAMENTO", "financialCategories": [cat("2030102", "Tarifas Diversas | ADM", 100)]},
        {"bankMovementId": 9002, "billId": 0, "companyId": 1, "companyName": "ENERGIA", "bankMovementOriginId": "BC", "bankMovementOperationType": "S",
         "bankMovementOperationId": 2, "bankMovementOperationName": "Pagamento", "bankMovementDate": "2026-09-15", "bankMovementAmount": 1000.0,
         "financialCategories": [cat("2030104", "Juros sobre Empréstimos | ADM", 60), cat("2030409", "Cresol | Juros", 40)]},
        {"bankMovementId": 9003, "billId": None, "bankMovementOriginId": "BC", "bankMovementOperationType": "E", "bankMovementOperationId": 1,
         "bankMovementDate": "2026-09-02", "bankMovementAmount": 55.0, "financialCategories": [cat("1030402", "Valores indevidos", 100)]},
        {"bankMovementId": 9004, "billId": 10, "bankMovementOriginId": "CP", "bankMovementOperationType": "S", "bankMovementOperationId": 2,
         "bankMovementDate": "2026-09-10", "bankMovementAmount": 1000.0, "financialCategories": [cat("2010104", "Material", 100)]},
        {"bankMovementId": 9005, "billId": None, "bankMovementOriginId": "CX", "bankMovementOperationType": "S", "bankMovementOperationId": 14,
         "bankMovementDate": "2026-09-03", "bankMovementAmount": 30.0, "financialCategories": []},
        {"bankMovementId": 9001, "billId": None, "bankMovementOriginId": "BC", "bankMovementOperationType": "S", "bankMovementOperationId": 2,
         "bankMovementDate": "2026-09-01", "bankMovementAmount": 100.0, "financialCategories": [cat("2030102", "Tarifas Diversas | ADM", 100)]},   # repetido: ignora
    ]
