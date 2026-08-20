"""O monitor de terminal, na parte que decide o que cada coluna diz.

Existe porque o monitor é o único lugar onde o Enzo olha o dia inteiro. Uma
transportadora que respondeu certo aparecendo como ERRO faz ele caçar um
defeito que não existe — e, pior, ensina a ignorar a coluna de erro.
"""

from __future__ import annotations

import monitorar


def test_cotacao_que_responde_por_email_nao_e_erro_na_coluna():
    """A Generoso confirma o recebimento e manda o preço por e-mail. Sem preço
    e sem falha: a coluna precisa de uma terceira palavra."""
    celula = monitorar._celula({"valor": None, "status": "aguardando_retorno"})

    assert celula == "e-mail"
    assert "ERRO" not in celula


def test_resposta_por_email_conta_separada_dos_erros():
    """A regra e do STATUS, nao da transportadora: qualquer uma que confirme
    o recebimento sem preco conta aqui. Por isso o slug vem de AUTOMATICAS —
    o teste continua valendo quando a Generoso entrar na lista."""
    cotacoes = [{"id": 1}]
    resultados = {1: {monitorar.AUTOMATICAS[0]: {
        "valor": None, "status": "aguardando_retorno"}}}

    contas = monitorar.contar(cotacoes, resultados)

    assert contas["por_email"] == 1
    assert contas["erros"] == 0
    assert contas["recusadas"] == 0
