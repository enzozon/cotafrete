import pytest
from fastapi.testclient import TestClient

from tests.test_dav_tela import app_web, cli  # noqa: F401


@pytest.fixture
def admin(app_web, monkeypatch):
    from web import adm
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "s3nha")
    c = TestClient(app_web.app, follow_redirects=False)
    c.cookies.set(adm.COOKIE_ADM, adm.token_de("s3nha"))
    return c


@pytest.mark.parametrize("url", ["/adm/dav", "/adm/dav/1", "/adm/dav/1/pdf"])
def test_porta_admin_em_todas_rotas(app_web, monkeypatch, url):
    c = TestClient(app_web.app, follow_redirects=False)
    monkeypatch.delenv("COTAFRETE_ADM_SENHA", raising=False)
    assert c.get(url).status_code == 404
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "s3nha")
    assert c.get(url).status_code == 303


def test_adm_dav_sidebar_e_links(admin, app_web):
    i = app_web.banco.dav_criar("bia", "a.xlsx", "a", "Cliente A")
    app_web.banco.dav_atualizar(i, estado="erro", erro="Local de entrega não encontrado")
    t = admin.get("/adm/dav").text
    assert 'aria-current="page"' in t and 'href="/adm/dav"' in t
    assert 'href="/adm#movimento"' in t and "bia" in t
    assert "local de entrega" in t.lower() and "Falhas de criação" in t
    assert admin.get(f"/adm/dav/{i}").status_code == 200


def test_admin_ve_relatorio_completo_sem_html_executavel(admin, app_web):
    i = app_web.banco.dav_criar("bia", "a.xlsx", "a", "Cliente A")
    app_web.banco.dav_atualizar(i, estado="erro", relatorio="Pendência financeira DF15653 <b>x</b>")
    t = admin.get(f"/adm/dav/{i}").text
    assert "DF15653" in t and "&lt;b&gt;x&lt;/b&gt;" in t
    assert "Enviar planilha corrigida" not in t


def test_retorno_preserva_recorte_sem_open_redirect(admin, app_web):
    i = app_web.banco.dav_criar("ana", "a.xlsx", "a", "Cliente A")
    app_web.banco.dav_atualizar(i, estado="erro")
    t = admin.get(f"/adm/dav/{i}?dias=7&estado=erro&vendedor=ana&busca=Cliente&pagina=2&retorno=https://evil.invalid").text
    assert "dias=7" in t and "pagina=2" in t and "vendedor=ana" in t
    assert "evil.invalid" not in t


def test_resumo_dav_nao_altera_totais_frete(admin, app_web):
    i = app_web.banco.dav_criar("ana", "a.xlsx", "a", "A")
    app_web.banco.dav_atualizar(i, estado="incerto")
    t = admin.get("/adm").text
    assert "Orçamentos DAV" in t and "Hoje" in t
    assert "estado=incerto" in t and "dias=1" in t
    from contextlib import closing
    with closing(app_web.banco._conectar()) as con:
        assert con.execute("SELECT COUNT(*) FROM cotacao").fetchone()[0] == 0


def test_duas_sessoes_nao_elevam_rota_vendedor(cli, admin, app_web):
    from web import adm
    i = app_web.banco.dav_criar("bia", "privado.xlsx", "p", "Cliente B")
    cli.cookies.set(adm.COOKIE_ADM, adm.token_de("s3nha"))
    assert cli.get(f"/dav/{i}").status_code == 404
    assert admin.get(f"/dav/{i}").status_code == 303
