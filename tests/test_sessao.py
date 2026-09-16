"""A sessão do vendedor — e o buraco que ela existe para fechar.

Até 16/09/2026 o cookie do vendedor guardava o nome digitado, puro. Quem
abrisse o inspetor do navegador e trocasse `cotafrete_usuario=joao` por
`cotafrete_usuario=enzo` virava o Enzo — e via o histórico dele, com CNPJ de
cliente, endereço de entrega e valor de nota.

O teste central deste arquivo é o `test_cookie_forjado_na_mao_nao_vale`: ele
prova que inventar o valor do cookie não dá mais acesso. Sem essa prova, o
teste do caminho feliz passaria mesmo que `dono_do_cookie` fosse
`lambda valor, _: valor`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core import sessao

SEGREDO = "segredo-de-teste-nao-usar-em-producao"


# ------------------------------------------------------------------- senha
def test_a_senha_nunca_fica_guardada_em_texto():
    guardado = sessao.hash_senha("cavalo-bateria-grampo")

    assert "cavalo-bateria-grampo" not in guardado


def test_a_mesma_senha_gera_hashes_diferentes():
    """Sem sal, senhas iguais viram hashes iguais — e aí o banco entrega de
    graça quem usa a mesma senha que outra pessoa."""
    a = sessao.hash_senha("mesma-senha-nos-dois")
    b = sessao.hash_senha("mesma-senha-nos-dois")

    assert a != b
    assert sessao.senha_confere("mesma-senha-nos-dois", a)
    assert sessao.senha_confere("mesma-senha-nos-dois", b)


def test_senha_errada_nao_passa():
    guardado = sessao.hash_senha("a-certa")

    assert not sessao.senha_confere("a-errada", guardado)
    assert not sessao.senha_confere("", guardado)


def test_hash_estragado_recusa_em_vez_de_explodir():
    """Linha corrompida no banco não pode virar 500 na tela de login — nem,
    pior, um `True` por acidente."""
    for lixo in ("", "sem-cifrao", "scrypt$nao$sao$numeros$x$y", "a$b$c"):
        assert not sessao.senha_confere("qualquer", lixo)


def test_senha_curta_e_recusada_com_motivo():
    assert sessao.recusa_da_senha("1234567") is not None
    assert sessao.recusa_da_senha("12345678") is None


# ------------------------------------------------------------------ cookie
def test_cookie_forjado_na_mao_nao_vale():
    """O buraco antigo, fechado.

    Antes, `cotafrete_usuario=enzo` era o bastante. Agora o valor precisa da
    assinatura, que só sai de quem tem o segredo do servidor."""
    assert sessao.dono_do_cookie("enzo", SEGREDO) is None
    assert sessao.dono_do_cookie("656e7a6f|99999999999|0000", SEGREDO) is None
    assert sessao.dono_do_cookie(None, SEGREDO) is None
    assert sessao.dono_do_cookie("", SEGREDO) is None


def test_cookie_assinado_pelo_servidor_vale():
    valor = sessao.assinar("enzo", SEGREDO)

    assert sessao.dono_do_cookie(valor, SEGREDO) == "enzo"


def test_cookie_de_outro_servidor_nao_vale():
    """Trocar o segredo derruba todas as sessões. É assim que se expulsa
    todo mundo sem manter lista de sessão para administrar."""
    valor = sessao.assinar("enzo", SEGREDO)

    assert sessao.dono_do_cookie(valor, "outro-segredo") is None


def test_trocar_o_nome_dentro_do_cookie_invalida_a_assinatura():
    valor = sessao.assinar("joao", SEGREDO)
    corpo, _, assinatura = valor.rpartition("|")
    _, _, prazo = corpo.partition("|")
    adulterado = f"{'enzo'.encode().hex()}|{prazo}|{assinatura}"

    assert sessao.dono_do_cookie(adulterado, SEGREDO) is None


def test_cookie_vencido_nao_vale():
    ontem = datetime.now() - timedelta(days=sessao.DIAS_DE_SESSAO + 1)
    velho = sessao.assinar("enzo", SEGREDO, agora=ontem)

    assert sessao.dono_do_cookie(velho, SEGREDO) is None


def test_cookie_vence_no_prazo_e_nao_antes():
    valor = sessao.assinar("enzo", SEGREDO)
    quase = datetime.now() + timedelta(days=sessao.DIAS_DE_SESSAO, hours=-1)
    passou = datetime.now() + timedelta(days=sessao.DIAS_DE_SESSAO, hours=1)

    assert sessao.dono_do_cookie(valor, SEGREDO, agora=quase) == "enzo"
    assert sessao.dono_do_cookie(valor, SEGREDO, agora=passou) is None


def test_nome_com_acento_e_espaco_sobrevive_a_ida_e_volta():
    """O nome vai codificado no cookie justamente para não quebrar no
    separador nem no cabeçalho HTTP."""
    valor = sessao.assinar("José da Silva", SEGREDO)

    assert sessao.dono_do_cookie(valor, SEGREDO) == "José da Silva"


@pytest.mark.parametrize("estragado", [
    "sem-separador",
    "so|duas",
    "|||",
    "zz|123|abc",           # nome que não é hex
    "656e7a6f|amanha|abc",  # prazo que não é número
])
def test_cookie_estragado_recusa_em_vez_de_explodir(estragado):
    assert sessao.dono_do_cookie(estragado, SEGREDO) is None
