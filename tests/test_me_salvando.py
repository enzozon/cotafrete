"""Cotação do ME nunca fica presa em "salvando".

O robô roda numa thread. Se o processo fecha no meio (o atualizar.py
reinicia a cada merge) ou se uma exceção escapa antes da troca de status, a
cotação ficava "Salvando no ME…" para sempre: a edição fechada e os botões
recusando, até ela sumir do ME.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.banco import Banco
from web import me_ui


@pytest.fixture
def banco(tmp_path, monkeypatch):
    b = Banco(tmp_path / "t.db")
    monkeypatch.setattr(me_ui, "banco", b)
    return b


def test_subida_solta_o_que_ficou_salvando(banco):
    presa = banco.me_criar("ventura", 1, status="salvando")
    livre = banco.me_criar("ventura", 2, status="salva")

    assert banco.me_soltar_salvando("fechou no meio") == [presa]
    assert banco.me_cotacao(presa)["status"] == "erro"
    assert banco.me_cotacao(presa)["erro"] == "fechou no meio"
    assert banco.me_cotacao(livre)["status"] == "salva"
    assert banco.me_historico(presa)[-1]["evento"] == "erro do robô"


def test_excecao_fora_do_previsto_vira_erro_e_nao_trava(banco, monkeypatch):
    cid = banco.me_criar("ventura", 3, status="salvando")
    resultado = SimpleNamespace(ok=True, divergencias=[], prints=[], erro=None, avisos=["um aviso"])
    monkeypatch.setattr(me_ui, "ROBO", lambda *a, **k: resultado)
    monkeypatch.setattr(me_ui, "entradas", lambda c: {})
    monkeypatch.setattr(me_ui, "anexos_locais", lambda c: {})
    monkeypatch.setattr(me_ui, "frete_de", lambda c: ("FOB", ""))
    real = banco.me_registrar

    def registrar(cotacao_id, evento, detalhe="", usuario=None):
        if evento == "aviso do robô":
            raise RuntimeError("database is locked")
        return real(cotacao_id, evento, detalhe, usuario)

    monkeypatch.setattr(banco, "me_registrar", registrar)
    me_ui._contar_robo(+1)
    me_ui._rodar_robo(cid, "enzo", False, "pendente")

    c = banco.me_cotacao(cid)
    assert c["status"] == "erro" and "database is locked" in c["erro"]
    assert me_ui.robos_em_curso() == 0


def test_ocupado_conta_o_robo_do_me(monkeypatch):
    from fastapi.testclient import TestClient
    from web import app as app_web
    monkeypatch.setattr(me_ui, "_robos_em_curso", 1)
    assert TestClient(app_web.app).get("/_ocupado").json()["em_curso"] >= 1
