"""A tela que decide quem entra no Cotafrete.

Duas garantias aqui. A primeira é óbvia e mesmo assim é a que mais importa:
criar conta exige a senha do painel. Se
`test_sem_a_senha_do_painel_ninguem_mexe_em_conta` falhar, qualquer pessoa da
internet cria a própria conta e o login inteiro vira enfeite.

A segunda é que o administrador não tem como ver nem escolher a senha de
ninguém — só reabrir o convite.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from core import sessao
from core.banco import Banco

SENHA_DO_PAINEL = "senha-do-painel-de-teste"


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA_DO_PAINEL)
    import web.app as modulo
    importlib.reload(modulo)
    banco = Banco(tmp_path / "cotafrete.db")
    monkeypatch.setattr(modulo, "banco", banco)
    monkeypatch.setattr(modulo.adm, "banco", banco)
    return modulo


@pytest.fixture
def anonimo(app_web):
    return TestClient(app_web.app, follow_redirects=False)


@pytest.fixture
def chefe(app_web):
    """Cliente já logado no painel."""
    c = TestClient(app_web.app, follow_redirects=False)
    c.cookies.set(app_web.adm.COOKIE_ADM,
                  app_web.adm.token_de(SENHA_DO_PAINEL))
    return c


# ------------------------------------------------------------- a barreira
def test_sem_a_senha_do_painel_ninguem_mexe_em_conta(anonimo, app_web):
    """Todas as portas desta tela, não só a de leitura."""
    app_web.banco.criar_conta("joao")

    tentativas = [
        anonimo.get("/adm/contas"),
        anonimo.post("/adm/contas/criar", data={"nome": "invasor"}),
        anonimo.post("/adm/contas/esquecer", data={"nome": "joao"}),
        anonimo.post("/adm/contas/remover", data={"nome": "joao"}),
    ]

    for r in tentativas:
        assert r.status_code == 303
        assert r.headers["location"] == "/adm/entrar"
    assert [c["nome"] for c in app_web.banco.contas()] == ["joao"], (
        "nada foi criado nem removido")


# --------------------------------------------------------------- criar
def test_criar_conta_abre_convite_sem_senha(chefe, app_web):
    r = chefe.post("/adm/contas/criar", data={"nome": "maria"})

    assert r.status_code == 303
    conta = app_web.banco.conta("maria")
    assert conta is not None
    assert conta["senha_hash"] is None, "quem escolhe a senha é a Maria"


def test_nome_repetido_avisa_e_nao_apaga_a_senha_de_quem_ja_usa(chefe, app_web):
    app_web.banco.criar_conta("maria")
    app_web.banco.definir_senha("maria", sessao.hash_senha("a-da-maria"))

    chefe.post("/adm/contas/criar", data={"nome": "maria"})

    assert sessao.senha_confere("a-da-maria",
                                app_web.banco.conta("maria")["senha_hash"])


def test_nome_em_branco_nao_cria_conta(chefe, app_web):
    chefe.post("/adm/contas/criar", data={"nome": "   "})

    assert app_web.banco.contas() == []


# -------------------------------------------------------------- esquecer
def test_esquecer_reabre_o_convite(chefe, app_web):
    app_web.banco.criar_conta("maria")
    app_web.banco.definir_senha("maria", sessao.hash_senha("a-esquecida"))

    chefe.post("/adm/contas/esquecer", data={"nome": "maria"})

    assert app_web.banco.conta("maria")["senha_hash"] is None


def test_a_tela_nunca_mostra_o_hash_da_senha(chefe, app_web):
    """O hash não é a senha, mas também não tem por que aparecer na tela —
    é material para quem quiser atacá-lo offline."""
    app_web.banco.criar_conta("maria")
    guardado = sessao.hash_senha("a-da-maria")
    app_web.banco.definir_senha("maria", guardado)

    corpo = chefe.get("/adm/contas").text

    assert guardado not in corpo
    assert "scrypt$" not in corpo


# --------------------------------------------------------------- remover
def test_remover_tira_o_acesso_e_guarda_o_historico(chefe, app_web):
    from tests.test_banco import _carga
    app_web.banco.criar_conta("maria")
    app_web.banco.salvar_cotacao("maria", _carga())

    chefe.post("/adm/contas/remover", data={"nome": "maria"})

    assert app_web.banco.conta("maria") is None
    assert len(app_web.banco.listar_cotacoes("maria")) == 1


def test_quem_ja_cotou_aparece_como_sugestao_mas_nao_ganha_conta(chefe, app_web):
    """A virada de 16/09/2026 deixou nomes no histórico que nunca foram
    conta. Eles são sugeridos — e só. Criar sozinho seria abrir um convite
    para cada erro de digitação do passado, e convite aberto é reivindicável
    por quem adivinhar o nome."""
    from tests.test_banco import _carga
    app_web.banco.salvar_cotacao("leandro", _carga())

    corpo = chefe.get("/adm/contas").text

    assert "leandro" in corpo
    assert "ainda não têm conta" in corpo
    assert app_web.banco.conta("leandro") is None, "ninguém ganhou conta sozinho"


def test_quem_ja_tem_conta_sai_das_sugestoes(chefe, app_web):
    from tests.test_banco import _carga
    app_web.banco.salvar_cotacao("leandro", _carga())
    app_web.banco.criar_conta("leandro")

    corpo = chefe.get("/adm/contas").text

    assert "ainda não têm conta" not in corpo


def test_a_tela_lista_quem_tem_conta(chefe, app_web):
    app_web.banco.criar_conta("maria")
    app_web.banco.criar_conta("joao")

    corpo = chefe.get("/adm/contas").text

    assert "maria" in corpo and "joao" in corpo
    assert "convite aberto" in corpo
