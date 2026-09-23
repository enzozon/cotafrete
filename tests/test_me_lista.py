"""Lista de pendências do Mercado Eletrônico, a partir do JSON da busca.

A tela do ME monta a lista com `POST api.web.mercadoe.com/.../transactions/
search`. O robô lê esse JSON em vez de raspar a tabela. Estrutura copiada do
recon de 23/09/2026 (UNIÃO e VENTURA); nomes trocados por sintéticos.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from mercado_eletronico import lista as L


def _registro(**muda):
    base = {
        "id": "7_23039029_4637695", "processType": 7, "processId": 23039029,
        "processName": "Cotação", "customerName": "Comprador Exemplo",
        "company": "Samarco Mineração", "workflow": "Samarco",
        "clientCode": "308-029226_00002", "createDate": "2026-09-21T19:49:18.233Z",
        "statusId": 8, "statusName": "Em andamento", "summary": "308-029226_00002",
        "answerStatus": "Não Respondida", "negotiationStage": "1º Oportunidade",
        "dueDate": "2026-09-24T00:00:00Z", "stageRFX": "RFQ",
    }
    base.update(muda)
    return base


def _resposta(*registros):
    return {"aggregation": [], "hits": len(registros),
            "data": {"count": len(registros), "result": list(registros)}}


def test_le_os_campos_da_cotacao():
    [c] = L.ler_busca(_resposta(_registro()))
    assert c.numero == 23039029
    assert c.empresa == "Samarco Mineração"
    assert c.comprador == "Comprador Exemplo"
    assert c.codigo == "308-029226_00002"
    assert c.status_resposta == "Não Respondida"
    assert c.link == "https://www.me.com.br/RespostaCotaItem.asp?Cotacao=23039029&SuperCleanPage="


def test_data_limite_vem_em_utc_e_vira_21h_de_brasilia_do_dia_anterior():
    # a tela mostrava "Prazo para resposta: 23/09/2026 21:00"
    [c] = L.ler_busca(_resposta(_registro()))
    assert c.data_limite.replace(tzinfo=None) == datetime(2026, 9, 23, 21, 0)
    assert c.data_limite.utcoffset().total_seconds() == -3 * 3600


@pytest.mark.parametrize("status, enviada", [
    ("Não Respondida", False),
    ("Parcialmente Respondida", True),
    ("Totalmente Respondida", True),
    ("Recusada", False),
])
def test_enviada_so_quando_o_me_diz_respondida(status, enviada):
    # rascunho salvo continua "Não Respondida" (teste real de 23/09/2026)
    [c] = L.ler_busca(_resposta(_registro(answerStatus=status)))
    assert c.enviada is enviada
    assert c.recusada is (status == "Recusada")


def test_so_cotacoes_entram_na_lista():
    pedido = _registro(processType=13, processId=999, processName="Pedido")
    cots = L.ler_busca(_resposta(_registro(), pedido))
    assert [c.numero for c in cots] == [23039029]


def test_ordena_pela_data_limite():
    a = _registro(processId=2, dueDate="2026-09-29T00:00:00Z")
    b = _registro(processId=1, dueDate="2026-09-24T00:00:00Z")
    assert [c.numero for c in L.ler_busca(_resposta(a, b))] == [1, 2]


def test_lista_vazia_e_formatos_inesperados():
    assert L.ler_busca(_resposta()) == []
    assert L.ler_busca({}) == []
    assert L.ler_busca({"data": None}) == []


def test_registro_quebrado_vira_erro_claro():
    with pytest.raises(L.RespostaInesperada):
        L.ler_busca(_resposta(_registro(processId=None)))
    with pytest.raises(L.RespostaInesperada):
        L.ler_busca(_resposta(_registro(dueDate="amanhã")))
