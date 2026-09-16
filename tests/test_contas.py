"""Contas de vendedor: quem pode entrar, e como a senha é escolhida.

O admin abre o convite (conta sem senha); a pessoa escolhe a senha no
primeiro acesso. O teste que carrega este arquivo é o
`test_o_convite_so_pode_ser_usado_uma_vez`: sem essa trava, qualquer um que
chegasse depois reescreveria a senha de um vendedor que já usa o sistema —
e o login viraria enfeite.
"""

from __future__ import annotations

import pytest

from core import sessao
from core.banco import Banco


@pytest.fixture
def db(tmp_path):
    return Banco(tmp_path / "cotafrete.db")


# ------------------------------------------------------------------ convite
def test_conta_nova_nasce_sem_senha(db):
    assert db.criar_conta("joao")

    conta = db.conta("joao")
    assert conta["senha_hash"] is None, "NULL é o convite ainda aberto"
    assert conta["definida_em"] is None


def test_nome_repetido_nao_reabre_convite(db):
    """Sem isto, criar de novo uma conta existente apagaria a senha de quem
    já usa o sistema — um jeito silencioso de sequestrar a conta."""
    db.criar_conta("joao")
    db.definir_senha("joao", sessao.hash_senha("senha-do-joao"))

    assert db.criar_conta("joao") is False
    assert db.conta("joao")["senha_hash"] is not None


def test_o_convite_so_pode_ser_usado_uma_vez(db):
    """A trava central. A segunda tentativa de definir senha é recusada."""
    db.criar_conta("joao")

    assert db.definir_senha("joao", sessao.hash_senha("a-do-joao"))
    assert db.definir_senha("joao", sessao.hash_senha("a-do-invasor")) is False

    guardado = db.conta("joao")["senha_hash"]
    assert sessao.senha_confere("a-do-joao", guardado)
    assert not sessao.senha_confere("a-do-invasor", guardado)


def test_definir_senha_de_conta_que_nao_existe_nao_cria_conta(db):
    """Um nome digitado na tela de login não pode virar conta sozinho —
    senão qualquer pessoa da internet se cadastra."""
    assert db.definir_senha("ninguem", sessao.hash_senha("oito-caracteres")) is False
    assert db.conta("ninguem") is None


def test_admin_reabre_o_convite_quando_alguem_esquece(db):
    db.criar_conta("joao")
    db.definir_senha("joao", sessao.hash_senha("a-esquecida"))

    assert db.esquecer_senha("joao")

    assert db.conta("joao")["senha_hash"] is None
    assert db.definir_senha("joao", sessao.hash_senha("a-nova"))


def test_remover_conta_tira_o_acesso_e_preserva_o_historico(db):
    from tests.test_banco import _carga
    db.criar_conta("joao")
    db.salvar_cotacao("joao", _carga())

    assert db.remover_conta("joao")

    assert db.conta("joao") is None
    assert len(db.listar_cotacoes("joao")) == 1, (
        "cotação é histórico da empresa, não da pessoa")


def test_contas_lista_em_ordem(db):
    db.criar_conta("zulmira")
    db.criar_conta("ana")

    assert [c["nome"] for c in db.contas()] == ["ana", "zulmira"]


# ------------------------------------------------------------- segredo
def test_o_segredo_nasce_uma_vez_e_nao_muda(db):
    """Se mudasse a cada chamada, todo reinício do servidor derrubaria a
    equipe inteira."""
    primeiro = db.segredo_sessao()

    assert db.segredo_sessao() == primeiro
    assert len(primeiro) >= 32


def test_o_segredo_sobrevive_a_reabrir_o_banco(db, tmp_path):
    primeiro = db.segredo_sessao()

    outro = Banco(tmp_path / "cotafrete.db")

    assert outro.segredo_sessao() == primeiro


def test_bancos_diferentes_tem_segredos_diferentes(db, tmp_path):
    outro = Banco(tmp_path / "outro.db")

    assert db.segredo_sessao() != outro.segredo_sessao()
