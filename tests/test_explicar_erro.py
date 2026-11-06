"""Sugestão 2: a IA explica em uma frase o erro que ninguém traduziu."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest

from core import explicar_erro as ex
from core import ia
from tests.test_ia import Provedor, Resp

TIMEOUT = "TimeoutError: Locator.click: Timeout 30000ms exceeded (CEP 29230000)"


@pytest.fixture
def prov(monkeypatch):
    p = Provedor()
    monkeypatch.setattr(ia, "POST", p)
    monkeypatch.setattr(ia, "_castigo", {})
    monkeypatch.setattr(ia, "REGISTRO", None)
    monkeypatch.setenv("IA_MODELOS", "groq:melhor,openrouter:reserva:free")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "y")
    return p


@pytest.fixture
def conectar(tmp_path):
    caminho = tmp_path / "t.db"
    return lambda: sqlite3.connect(caminho)


def _frase(t):
    return Resp(conteudo=json.dumps({"frase": t}))


def test_frase_guardada_vale_para_o_mesmo_erro_com_outros_numeros(prov, conectar):
    prov.roteiro["melhor"] = [_frase("O site demorou a responder. Repita a cotação.")]

    assert ex.explicar(conectar, "camilo", "Camilo", TIMEOUT)

    with conectar() as con:
        outro = TIMEOUT.replace("29230000", "01001000").replace("30000", "45000")
        assert ex.guardada(con, "camilo", outro) == "O site demorou a responder. Repita a cotação."
        assert ex.guardada(con, "jadlog", TIMEOUT) is None    # outra transportadora


def test_frase_com_numero_vai_para_o_proximo_modelo(prov, conectar):
    """A frase vale para o TIPO de erro: um número dela seria de um caso só."""
    prov.roteiro["melhor"] = [_frase("Demorou mais de 30 segundos.")]
    prov.roteiro["reserva:free"] = [_frase("O site demorou. Repita.")]

    assert ex.explicar(conectar, "camilo", "Camilo", TIMEOUT) == "O site demorou. Repita."


def test_ia_fora_do_ar_nao_guarda_nada(prov, conectar):
    prov.roteiro["melhor"] = [_frase("")]
    prov.roteiro["reserva:free"] = [_frase("x" * 400)]

    assert ex.explicar(conectar, "camilo", "Camilo", TIMEOUT) is None
    with conectar() as con:
        assert ex.guardada(con, "camilo", TIMEOUT) is None


def test_desligada_nao_dispara(monkeypatch, conectar):
    monkeypatch.setattr(ex, "LIGADA", False)
    assert ex.explicar_em_fundo(conectar, "camilo", "Camilo", TIMEOUT) is False


def test_cartao_mostra_a_frase_guardada_antes_do_texto_tecnico(monkeypatch, tmp_path):
    from core.banco import Banco
    from web import app as app_web
    monkeypatch.setattr(app_web, "banco", Banco(tmp_path / "t.db"))
    with closing(app_web.banco._conectar()) as con, con:
        ex._criar_tabela(con)
        con.execute("INSERT OR REPLACE INTO erro_explicado VALUES (?, ?, NULL, '2026-10-09')",
                    (ex.chave("camilo", TIMEOUT), "Frase da IA."))
    assert app_web._explicacao_ia("camilo", TIMEOUT) == "Frase da IA."
    # sem frase guardada e IA desligada (conftest): None, o cartão mostra só o técnico
    assert app_web._explicacao_ia("camilo", "erro nunca visto") is None


def test_falha_nao_e_pedida_de_novo_a_cada_abertura(monkeypatch, conectar):
    """A cotação se recarrega sozinha: sem a espera, cada recarga gastaria cota."""
    chamadas = []
    monkeypatch.setattr(ex, "LIGADA", True)
    monkeypatch.setattr(ex, "_pedidos", {})
    monkeypatch.setattr(ia, "configurada", lambda: True)
    monkeypatch.setattr(ex, "explicar", lambda *a: chamadas.append(a))

    assert ex.explicar_em_fundo(conectar, "camilo", "Camilo", TIMEOUT) is True
    assert ex.explicar_em_fundo(conectar, "camilo", "Camilo", TIMEOUT) is False
    monkeypatch.setattr(ex, "ESPERA_FALHA_S", 0)
    assert ex.explicar_em_fundo(conectar, "camilo", "Camilo", TIMEOUT) is True


def test_explicacao_fica_pendente_so_enquanto_a_thread_roda(monkeypatch, conectar):
    import threading
    solta = threading.Event()
    monkeypatch.setattr(ex, "LIGADA", True)
    monkeypatch.setattr(ex, "_pedidos", {})
    monkeypatch.setattr(ia, "configurada", lambda: True)
    monkeypatch.setattr(ex, "explicar", lambda *a: solta.wait(5))

    ex.explicar_em_fundo(conectar, "camilo", "Camilo", TIMEOUT)
    assert ex.pendente("camilo", TIMEOUT)

    solta.set()
    for t in threading.enumerate():
        if t.name == "explicar-erro":
            t.join(5)
    assert not ex.pendente("camilo", TIMEOUT)


def test_tela_recarrega_em_10_s_enquanto_a_explicacao_esta_pendente(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from core.banco import Banco
    from tests.apoio import entrar
    from tests.test_web_cotacao import CARGA
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "t.db"))
    monkeypatch.setattr(modulo, "TENTATIVAS_EM_CURSO", {})
    monkeypatch.setattr(modulo, "AUTOMATICAS", ("camilo",))
    cli = TestClient(modulo.app)
    entrar(cli, modulo)
    cid = modulo.banco.salvar_cotacao("enzo", CARGA)
    modulo.banco.salvar_resultado(cid, "camilo", status="erro", erro="erro nunca visto")
    recarga = '<meta http-equiv="refresh" content="10">'

    assert recarga not in cli.get(f"/cotacao/{cid}").text

    monkeypatch.setattr(ex, "_em_curso", {ex.chave("camilo", "erro nunca visto")})
    assert recarga in cli.get(f"/cotacao/{cid}").text
