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


def test_senha_recusada_tem_palavra_propria_no_monitor():
    """"ERRO" mandaria o Enzo caçar defeito; "intervencao_necessaria" cru não
    cabe na coluna. O que ele precisa ler é que alguém tem que mexer no
    .env — é a única falha aqui que não passa sozinha."""
    celula = monitorar._celula({"valor": None,
                                "status": "intervencao_necessaria"})

    assert celula == "SENHA"


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


def test_a_generoso_e_acompanhada_como_as_outras():
    """Ligada em web/app.py mas fora do monitor, ela sumiria da tabela: o
    Enzo nao veria nem que ela rodou."""
    assert "generoso" in monitorar.AUTOMATICAS
    assert "generoso" in monitorar.TITULOS


# --------------------------------------------- colunas derivadas do banco
def test_slugs_do_periodo_pega_quem_apareceu_no_banco():
    """O bug real: a Della Volpe saiu de AUTOMATICAS em 31/08/2026 e sumiu
    da tela inteira, mesmo com erro dela salvo no banco. As colunas agora
    vem do que o banco tem, nao de uma lista fixa copiada a mao."""
    resultados = {1: {"dellavolpe": {"status": "intervencao_necessaria"}}}

    assert monitorar.slugs_do_periodo(resultados) == ("dellavolpe",)


def test_slugs_do_periodo_cai_para_automaticas_com_banco_vazio():
    """Banco novo, sem nenhum resultado ainda: a tela nao pode subir sem
    coluna nenhuma."""
    assert monitorar.slugs_do_periodo({}) == monitorar.AUTOMATICAS


def test_titulo_cai_para_slug_maiusculo_quando_desconhecido():
    """Uma transportadora nova nunca some da tela por faltar em TITULOS —
    aparece com o slug em maiusculo ate alguem cadastrar o nome bonito."""
    assert monitorar._titulo("nova_transportadora") == "NOVA_TRANSPORTADORA"
    assert monitorar._titulo("camilo") == "CAMILO"


def test_desenhar_nao_quebra_com_transportadora_fora_de_automaticas(capsys):
    """A reproducao direta do bug: um resultado de uma transportadora que
    nao esta em AUTOMATICAS (a Della Volpe, hoje) tem que aparecer na tela
    e no historico de falhas, nao ser ignorado silenciosamente."""
    dados = {
        "cotacoes": [{"id": 1, "criado_em": "2026-09-01T10:00:00",
                      "usuario": "enzo", "uf_origem": "SP", "uf_destino": "ES",
                      "quantidade": 1, "peso_kg": "10"}],
        "resultados": {1: {"dellavolpe": {
            "transportadora": "dellavolpe", "valor": None,
            "status": "intervencao_necessaria",
            "erro": "Envio barrado como spam pelo formulário."}}},
        "zaps": {},
    }

    monitorar.desenhar(dados, dias=1)
    saida = capsys.readouterr().out

    assert "DELLA VOLPE" in saida
    assert "Envio barrado como spam" in saida


# --------------------------------------------- linhas sem estourar o terminal
def test_linhas_disponiveis_respeita_o_minimo(monkeypatch):
    """Terminal pequeno nao pode zerar a tabela — cai no minimo, nunca em
    zero ou negativo."""
    import os
    import shutil

    monkeypatch.setattr(shutil, "get_terminal_size",
                        lambda fallback=None: os.terminal_size((80, 10)))

    assert monitorar._linhas_disponiveis() == monitorar.LINHAS_MIN_TABELA


def test_linhas_disponiveis_cresce_com_o_terminal(monkeypatch):
    import os
    import shutil

    monkeypatch.setattr(shutil, "get_terminal_size",
                        lambda fallback=None: os.terminal_size((200, 80)))

    assert monitorar._linhas_disponiveis() == 80 - monitorar.LINHAS_MOLDURA
