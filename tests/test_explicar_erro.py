"""Sugestão 2: a IA explica em uma frase o erro que ninguém traduziu."""

from __future__ import annotations

import json
import sqlite3

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
    with app_web.banco._conectar() as con:
        ex._criar_tabela(con)
        con.execute("INSERT OR REPLACE INTO erro_explicado VALUES (?, ?, NULL, '2026-10-09')",
                    (ex.chave("camilo", TIMEOUT), "Frase da IA."))
    assert app_web._explicacao_ia("camilo", TIMEOUT) == "Frase da IA."
    # sem frase guardada e IA desligada (conftest): None, o cartão mostra só o técnico
    assert app_web._explicacao_ia("camilo", "erro nunca visto") is None
