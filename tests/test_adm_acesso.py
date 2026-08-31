"""Quem entra no /adm, e quem não entra.

A tela junta CNPJ, nome e valor de nota de todos os clientes num lugar só. O
Servidor.bat avisa que 0.0.0.0 inclui o Wi-Fi: numa rede com visitantes, esta
senha é a única barreira entre eles e o histórico comercial da Ventura.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from web import adm, app as app_web

SENHA = "senha-de-teste-123"


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))
    return TestClient(app_web.app)


def test_sem_senha_no_ambiente_a_rota_nem_existe(monkeypatch, tmp_path):
    """404, não 401. Sem a variável configurada a tela não deve existir —
    ninguém abre um painel por engano numa pasta onde nada foi montado."""
    monkeypatch.delenv("COTAFRETE_ADM_SENHA", raising=False)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))

    resposta = TestClient(app_web.app).get("/adm", follow_redirects=False)

    assert resposta.status_code == 404


def test_sem_cookie_cai_na_tela_de_senha(cliente):
    resposta = cliente.get("/adm", follow_redirects=False)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/adm/entrar"


def test_senha_certa_entra(cliente):
    resposta = cliente.post("/adm/entrar", data={"senha": SENHA},
                            follow_redirects=False)

    assert resposta.status_code == 303
    assert adm.COOKIE_ADM in resposta.cookies


def test_senha_errada_nao_entra(cliente):
    resposta = cliente.post("/adm/entrar", data={"senha": "chutando"},
                            follow_redirects=False)

    assert adm.COOKIE_ADM not in resposta.cookies


def test_cookie_forjado_nao_entra(cliente):
    """O cookie não pode ser "adm=sim": qualquer um que soubesse o nome
    entraria digitando no navegador."""
    cliente.cookies.set(adm.COOKIE_ADM, "sim")

    assert cliente.get("/adm", follow_redirects=False).status_code == 303


def test_trocar_a_senha_invalida_as_sessoes(cliente, monkeypatch):
    """O token sai da própria senha, então trocá-la derruba todo mundo — sem
    precisar de uma lista de sessões para administrar."""
    antigo = adm.token_de(SENHA)
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "outra-senha")

    assert not adm.autorizado(antigo)


def test_a_senha_nunca_aparece_na_resposta(cliente):
    """Nem em campo escondido, nem em URL, nem em mensagem de erro."""
    resposta = cliente.post("/adm/entrar", data={"senha": "chutando"})

    assert SENHA not in resposta.text
    assert "chutando" not in resposta.text
