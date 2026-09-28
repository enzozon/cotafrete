"""A sessão do navegador do robô do ME não pode "envenenar" a thread.

28/09/2026: o resumo do dia no /adm mostrou 91 leituras do ME falhando em
cada conta, entre 0h e 10h, todas com "It looks like you are using Playwright
Sync API inside the asyncio loop". O vigia do ME roda numa thread só e abre
uma sessão a cada 7 minutos. Basta UMA sessão falhar no meio da abertura (o
navegador não subir, o estado.json estragado) sem o Playwright receber
stop(): o laço dele fica "rodando" na thread e toda sessão seguinte morre na
hora, até alguém reiniciar o servidor.

Os testes rodam cada cenário numa thread NOVA, como o vigia, para a sujeira
de um não vazar para o outro nem para o resto da suíte.
"""

from __future__ import annotations

import threading

import pytest

from mercado_eletronico import robo as B
from mercado_eletronico.regras import Conta

pytest.importorskip("playwright.sync_api")


def _na_thread(fn):
    """Roda fn numa thread nova e devolve o que ela devolveu ou levantou."""
    saida: dict = {}

    def alvo():
        try:
            saida["ok"] = fn()
        except BaseException as exc:  # noqa: BLE001 — o teste quer ver qualquer uma
            saida["erro"] = exc

    t = threading.Thread(target=alvo)
    t.start()
    t.join(120)
    assert not t.is_alive(), "a sessão travou"
    return saida


def _responder(route, request):
    route.fulfill(status=200, content_type="text/html", body="<p>ok</p>")


def _sessao_que_abre(tmp_path):
    with B.Sessao(Conta.UNIAO, pasta=tmp_path, seguir=_responder, timeout_ms=10_000) as s:
        s.page.goto("https://www.me.com.br/teste")
        return s.page.inner_text("p")


def test_sessao_normal_abre_e_fecha(tmp_path):
    assert _na_thread(lambda: _sessao_que_abre(tmp_path)) == {"ok": "ok"}


def test_falha_ao_abrir_nao_envenena_a_proxima_sessao(tmp_path, monkeypatch):
    from playwright.sync_api import Browser

    original = Browser.new_context
    falhas = {"restam": 1}

    def new_context_que_falha_uma_vez(self, *a, **k):
        if falhas["restam"]:
            falhas["restam"] -= 1
            raise RuntimeError("navegador sem memória")
        return original(self, *a, **k)

    monkeypatch.setattr(Browser, "new_context", new_context_que_falha_uma_vez)

    def duas_sessoes():
        with pytest.raises(RuntimeError, match="navegador sem memória"):
            _sessao_que_abre(tmp_path)
        return _sessao_que_abre(tmp_path)   # a madrugada do vigia: a próxima volta

    saida = _na_thread(duas_sessoes)
    assert "erro" not in saida, f"a segunda sessão morreu: {saida.get('erro')!r}"
    assert saida["ok"] == "ok"


def test_falha_ao_fechar_nao_envenena_a_proxima_sessao(tmp_path, monkeypatch):
    from playwright.sync_api import BrowserContext

    original = BrowserContext.close
    falhas = {"restam": 1}

    def close_que_falha_uma_vez(self, *a, **k):
        original(self, *a, **k)
        if falhas["restam"]:
            falhas["restam"] -= 1
            raise RuntimeError("Target page, context or browser has been closed")

    monkeypatch.setattr(BrowserContext, "close", close_que_falha_uma_vez)
    saida = _na_thread(lambda: (_sessao_que_abre(tmp_path), _sessao_que_abre(tmp_path)))
    assert "erro" not in saida, f"a segunda sessão morreu: {saida.get('erro')!r}"


def test_estado_json_estragado_vira_login_de_novo(tmp_path):
    (tmp_path / "uniao").mkdir()
    (tmp_path / "uniao" / "estado.json").write_text("{cortado no meio", encoding="utf-8")
    assert _na_thread(lambda: _sessao_que_abre(tmp_path)) == {"ok": "ok"}
    assert not (tmp_path / "uniao" / "estado.json").exists()
