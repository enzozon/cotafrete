"""Traduzir o erro técnico da transportadora em frase de vendedor.

Enzo pediu isto em 18/08/2026 e mandou deixar para depois. O motivo é
concreto: o vendedor não sabe o que é "sweet-alert", "timeout" ou
"wait_for_selector". Lendo o texto cru ele não sabe se o problema é o
sistema, a internet dele ou a carga — e liga para o Enzo.

Os erros aqui NÃO foram inventados: são os cinco textos distintos que a
Generoso realmente produziu em produção entre 19 e 28/08/2026, copiados do
banco. Inventar erro para testar tradutor de erro daria um mapa que casa com
frases que nunca aparecem.

A regra, do jeito que ele pediu: erro conhecido vira frase amigável; erro
desconhecido continua mostrando o texto original, para não esconder
informação. A frase NUNCA substitui o texto técnico no cartão — ela entra
antes dele.
"""

from __future__ import annotations

import pytest

from web import app as app_web

# Copiados do banco de produção. Repare que o mesmo arquivo escreve umas
# frases com acento e outras sem ("nao trouxe o endereco"), o que é
# exatamente por que o casamento ignora acento.
ERROS_REAIS = {
    "sem_preco":
        "A tela de resultado não trouxe preço nem confirmação de recebimento.",
    "etapa_destino":
        "RuntimeError: a etapa do destino não avançou. O site diz: "
        "(nenhuma mensagem visível)",
    "etapa_carga":
        "RuntimeError: a etapa da Carga não avançou. O site diz: "
        "(nenhuma mensagem visível)",
    "sem_endereco":
        "RuntimeError: o CNPJ 29.744.778/3505-03 nao trouxe o endereco de "
        "destino; sem isso a cotacao sairia de lugar nenhum. O site diz: "
        "(nenhuma mensagem visível)",
    "login_nao_abriu":
        'TimeoutError: Page.wait_for_selector: Timeout 45000ms exceeded.\n'
        'Call log:\n  - waiting for locator("input[name=\\"email\\"]") '
        'to be visible\n',
}

# O checkpoint da Vercel (28/08/2026). Ainda não chegou a virar linha de
# `erro` no banco porque aparece como o timeout acima, mas o texto está no
# print e pode chegar aqui a qualquer momento.
ERRO_CHECKPOINT = "Falha ao verificar seu navegador Código 21"

JARGAO = ("RuntimeError", "TimeoutError", "wait_for_selector", "locator",
          "Call log", "None", "Traceback", "exceeded")


@pytest.mark.parametrize("chave", sorted(ERROS_REAIS))
def test_todo_erro_real_da_generoso_ganha_frase(chave):
    frase = app_web.mensagem_amigavel("generoso", ERROS_REAIS[chave])

    assert frase, f"erro real sem tradução: {ERROS_REAIS[chave][:60]}"


def test_o_checkpoint_da_vercel_tambem_tem_frase():
    assert app_web.mensagem_amigavel("generoso", ERRO_CHECKPOINT)


@pytest.mark.parametrize("chave", sorted(ERROS_REAIS))
def test_a_frase_nao_carrega_jargao_de_volta(chave):
    """Traduzir e devolver "TimeoutError" no meio não traduz nada."""
    frase = app_web.mensagem_amigavel("generoso", ERROS_REAIS[chave])

    for palavra in JARGAO:
        assert palavra not in frase, f"{palavra!r} sobrou em: {frase}"


def test_erro_desconhecido_nao_ganha_frase_inventada():
    """Sem tradução, o cartão mostra o texto original — nada é escondido."""
    assert app_web.mensagem_amigavel(
        "generoso", "MemoryError: sei lá o que aconteceu") is None


def test_transportadora_sem_mapa_nao_quebra():
    assert app_web.mensagem_amigavel("camilo", ERROS_REAIS["sem_preco"]) is None
    assert app_web.mensagem_amigavel("generoso", "") is None
    assert app_web.mensagem_amigavel("generoso", None) is None


def test_o_acento_nao_decide_se_casa():
    """O mesmo adapter escreve "endereço" e "endereco". Casar só uma das
    formas deixaria metade dos erros reais sem tradução."""
    com = app_web.mensagem_amigavel(
        "generoso", "o CNPJ 1 não trouxe o endereço de origem")
    sem = app_web.mensagem_amigavel(
        "generoso", "o CNPJ 1 nao trouxe o endereco de origem")

    assert com and com == sem
