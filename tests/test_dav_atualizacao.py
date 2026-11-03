from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.test_dav_tela import app_web, cli  # noqa: F401
from tests.test_adm_dav import admin  # noqa: F401


def registro(banco, usuario="ana", **campos):
    i = banco.dav_criar(usuario, "a.xlsx", "hash", "Cliente")
    banco.dav_atualizar(i, estado="erro", **campos)
    return i


@pytest.mark.parametrize("url", ["/dav/agora", "/dav/1/agora", "/adm/dav/agora", "/adm/dav/1/agora"])
def test_api_sessao_expirada_401(app_web, monkeypatch, url):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "s3nha")
    assert TestClient(app_web.app).get(url).status_code == 401


def test_mesma_contagem_com_novo_erro_muda_versao(cli, app_web):
    i = registro(app_web.banco, erro="Local de entrega inválido")
    a = cli.get("/dav/agora").json()
    assert cli.get("/dav/agora", params={"v": a["v"]}).status_code == 204
    app_web.banco.dav_atualizar(i, erro="O HSE recusou o login")
    b = cli.get("/dav/agora", params={"v": a["v"]})
    assert b.status_code == 200 and b.json()["v"] != a["v"]
    assert cli.get("/dav/agora", params={"estado": "pronto", "v": b.json()["v"]}).status_code == 200


def test_api_perfis_e_no_store(cli, admin, app_web):
    i = registro(app_web.banco, relatorio="Pendência financeira DF15653 valor 1234,56 Venc: 27/09/2026")
    outro = registro(app_web.banco, "bia", erro="Segredo da Bia")
    for url in ("/dav/agora", f"/dav/{i}/agora"):
        r = cli.get(url)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        for segredo in ("DF15653", "1234,56", "27/09/2026", "Segredo da Bia"):
            assert segredo not in r.text
    assert cli.get(f"/dav/{outro}/agora").status_code == 404
    assert "DF15653" in admin.get(f"/adm/dav/{i}/agora").text


def test_versao_inclui_janela_do_periodo(cli, app_web, monkeypatch):
    from web import dav_ui
    monkeypatch.setattr(dav_ui, "agora", lambda: datetime(2026, 10, 29, 23, 59))
    a = cli.get("/dav/agora").json()
    monkeypatch.setattr(dav_ui, "agora", lambda: datetime(2026, 10, 30, 0, 1))
    b = cli.get("/dav/agora", params={"v": a["v"]})
    assert b.status_code == 200 and b.json()["v"] != a["v"]


def test_adm_principal_muda_sem_cotacao_de_frete(admin, app_web):
    a = admin.get("/adm/agora").json()
    registro(app_web.banco)
    b = admin.get("/adm/agora", params={"v": a["v"]})
    assert b.status_code == 200 and "dav" in b.json()


def test_detalhe_terminal_e_fila(cli, app_web):
    i = registro(app_web.banco)
    assert cli.get(f"/dav/{i}/agora").json()["ativo"] is False
    app_web.banco.dav_atualizar(i, estado="fila")
    assert cli.get(f"/dav/{i}/agora").json()["ativo"] is True
