"""A porta da frente: quem entra, quem não entra, e o primeiro acesso.

Estes testes batem na rota de verdade, com HTTP, porque o buraco que eles
fecham era de rota: até 16/09/2026 qualquer pessoa digitava um nome e
entrava. O `test_nome_inventado_nao_entra` é o que mais importa — se um dia
ele passar a falhar, o sistema voltou a ser uma porta aberta.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from core import sessao
from core.banco import Banco


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    import web.app as modulo
    importlib.reload(modulo)
    banco = Banco(tmp_path / "cotafrete.db")
    monkeypatch.setattr(modulo, "banco", banco)
    monkeypatch.setattr(modulo.adm, "banco", banco)
    # Sem o atraso: ele existe para atrapalhar quem tenta mil senhas, e aqui
    # só atrasaria a suíte.
    monkeypatch.setattr(modulo, "PAUSA_SENHA_ERRADA_S", 0)
    return modulo


@pytest.fixture
def c(app_web):
    return TestClient(app_web.app, follow_redirects=False)


def _com_conta(app_web, nome="joao", senha="senha-do-joao"):
    app_web.banco.criar_conta(nome)
    if senha:
        app_web.banco.definir_senha(nome, sessao.hash_senha(senha))
    return nome


# --------------------------------------------------------- a porta fechada
def test_nome_inventado_nao_entra(c, app_web):
    """O buraco antigo. Antes isto criava sessão e abria o sistema."""
    r = c.post("/login", data={"usuario": "invasor", "senha": "qualquer"})

    assert r.status_code == 401
    assert app_web.COOKIE not in r.cookies


def test_senha_errada_nao_entra(c, app_web):
    _com_conta(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "chute"})

    assert r.status_code == 401
    assert app_web.COOKIE not in r.cookies


def test_a_tela_nao_repete_a_senha_digitada(c, app_web):
    """Senha errada não pode voltar escrita na tela: fica no histórico do
    navegador e na tela de quem estiver olhando por cima do ombro."""
    _com_conta(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "MinhaSenhaSecreta"})

    assert "MinhaSenhaSecreta" not in r.text


def test_sem_sessao_o_sistema_manda_para_o_login(c):
    for rota in ("/", "/historico"):
        r = c.get(rota)
        assert r.status_code == 303, rota
        assert r.headers["location"] == "/login", rota


def test_cookie_forjado_nao_abre_o_sistema(c, app_web):
    """O mesmo ataque do test_sessao, agora pela porta HTTP."""
    _com_conta(app_web)
    c.cookies.set(app_web.COOKIE, "joao")

    r = c.get("/")

    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_conta_removida_perde_o_acesso_na_hora(c, app_web):
    """Sem isto, tirar alguém do sistema só faria efeito quando o cookie dela
    vencesse — até uma semana depois."""
    _com_conta(app_web)
    c.cookies.set(app_web.COOKIE,
                  sessao.assinar("joao", app_web.banco.segredo_sessao()))
    assert c.get("/").status_code == 200

    app_web.banco.remover_conta("joao")

    assert c.get("/").status_code == 303


# --------------------------------------------------------- a porta abrindo
def test_senha_certa_entra(c, app_web):
    _com_conta(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "senha-do-joao"})

    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert sessao.dono_do_cookie(r.cookies[app_web.COOKIE],
                                 app_web.banco.segredo_sessao()) == "joao"


def test_o_cookie_entregue_nao_contem_o_nome_legivel(c, app_web):
    _com_conta(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "senha-do-joao"})

    assert "joao" not in r.cookies[app_web.COOKIE]


# ------------------------------------------------------- primeiro acesso
def test_primeiro_acesso_pede_para_escolher_a_senha(c, app_web):
    _com_conta(app_web, senha=None)

    r = c.post("/login", data={"usuario": "joao", "senha": "tanto-faz"})

    assert "Primeiro acesso" in r.text
    assert app_web.COOKIE not in r.cookies, "ainda não entrou"


def test_toda_resposta_do_login_sai_como_html(c, app_web):
    """17/09/2026: o ramo do primeiro acesso devolvia str numa rota sem
    `response_class`, e o FastAPI mandava a página como JSON — a pessoa via
    o código-fonte escapado, com \\n literal, em vez da tela.

    O teste anterior não pegou porque conferia só se o texto aparecia, e em
    JSON ele aparece (escapado). Quem decide se a tela funciona é o tipo de
    mídia, então é ele que precisa ser conferido — em TODOS os caminhos, que
    é onde o defeito se escondeu: só um dos cinco estava errado."""
    _com_conta(app_web, nome="maria", senha=None)          # convite aberto
    _com_conta(app_web, nome="joao")                       # já tem senha

    respostas = {
        "conta inexistente":
            c.post("/login", data={"usuario": "ninguem", "senha": "x"}),
        "primeiro acesso":
            c.post("/login", data={"usuario": "maria", "senha": "tanto-faz"}),
        "senha curta":
            c.post("/login", data={"usuario": "maria", "senha": "123",
                                   "confirmacao": "123"}),
        "senhas diferentes":
            c.post("/login", data={"usuario": "maria", "senha": "uma-senha-boa",
                                   "confirmacao": "outra-senha-boa"}),
        "senha errada":
            c.post("/login", data={"usuario": "joao", "senha": "chute"}),
        "tela inicial": c.get("/login"),
    }

    for caminho, r in respostas.items():
        assert r.headers["content-type"].startswith("text/html"), caminho
        assert not r.text.lstrip().startswith('"'), (
            f"{caminho}: saiu como string JSON, não como página")


def test_a_senha_digitada_antes_nao_vira_a_senha_da_conta(c, app_web):
    """Quem chega no primeiro acesso digitou algo no campo "sua senha" sem
    saber. Esse valor não pode virar a senha definitiva por acidente."""
    _com_conta(app_web, senha=None)

    c.post("/login", data={"usuario": "joao", "senha": "digitei-sem-querer"})

    assert app_web.banco.conta("joao")["senha_hash"] is None


def test_escolher_a_senha_entra_de_uma_vez(c, app_web):
    _com_conta(app_web, senha=None)

    r = c.post("/login", data={"usuario": "joao", "senha": "frase-boa-aqui",
                               "confirmacao": "frase-boa-aqui"})

    assert r.status_code == 303
    assert sessao.senha_confere("frase-boa-aqui",
                                app_web.banco.conta("joao")["senha_hash"])


def test_senhas_diferentes_nao_definem_nada(c, app_web):
    _com_conta(app_web, senha=None)

    r = c.post("/login", data={"usuario": "joao", "senha": "frase-boa-aqui",
                               "confirmacao": "frase-boa-daqui"})

    assert r.status_code == 401
    assert app_web.banco.conta("joao")["senha_hash"] is None


def test_senha_curta_e_recusada_com_o_motivo_na_tela(c, app_web):
    _com_conta(app_web, senha=None)

    r = c.post("/login", data={"usuario": "joao", "senha": "1234",
                               "confirmacao": "1234"})

    assert r.status_code == 401
    assert str(sessao.MINIMO_DA_SENHA) in r.text
    assert app_web.banco.conta("joao")["senha_hash"] is None


def test_o_convite_nao_pode_ser_usado_por_quem_chegar_depois(c, app_web):
    """O invasor que descobre o nome de um vendedor não pode escolher a
    senha dele depois que a pessoa já escolheu a sua."""
    _com_conta(app_web, senha=None)
    c.post("/login", data={"usuario": "joao", "senha": "a-do-joao-mesmo",
                           "confirmacao": "a-do-joao-mesmo"})

    r = c.post("/login", data={"usuario": "joao", "senha": "a-do-invasor",
                               "confirmacao": "a-do-invasor"})

    assert r.status_code == 401
    assert sessao.senha_confere("a-do-joao-mesmo",
                                app_web.banco.conta("joao")["senha_hash"])


def test_sair_derruba_a_sessao(c, app_web):
    _com_conta(app_web)
    c.cookies.set(app_web.COOKIE,
                  sessao.assinar("joao", app_web.banco.segredo_sessao()))

    c.get("/sair")
    c.cookies.clear()

    assert c.get("/").status_code == 303
