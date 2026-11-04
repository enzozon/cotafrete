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
    assert 'data-tema-troca\n' in t or 'data-tema-troca ' in t
    assert 'href="/adm#movimento"' in t and "bia" in t
    assert "local de entrega" in t.lower() and "Pendentes agora" in t and "falhas de criação" in t
    assert admin.get(f"/adm/dav/{i}").status_code == 200


def test_admin_ve_o_gasto_da_ia(admin, app_web, tmp_path, monkeypatch):
    from datetime import datetime
    from orcamento import ia
    from web import adm_dav
    uso = tmp_path / "ia_uso.csv"
    uso.write_text(";".join(ia.COLUNAS) + "\n" + datetime.now().strftime("%Y-%m-%d 10:00:00")
                   + ";api:ncm_web;claude-haiku-5-5;1;1;0.031200;sim;\n", encoding="utf-8-sig")
    monkeypatch.setattr(adm_dav, "IA_USO", uso)
    t = admin.get("/adm/dav").text
    assert "Gasto da IA" in t and "US$ 0,0312 hoje" in t and "US$ 0,0312 no mês" in t
    monkeypatch.setattr(adm_dav, "IA_USO", tmp_path / "nao_existe.csv")
    assert "US$ 0,0000 hoje" in admin.get("/adm/dav").text


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


def _conf(**kw):
    from orcamento.processador import Conferencia
    base = dict(estado="erros", relatorio="REL <i>x</i> completo", cliente="", endereco="", vendedor="",
                itens=(), avisos=("Cliente com pendência financeira DF15653",), erros=("Preço <b>errado</b>",))
    return Conferencia(**{**base, **kw})


def test_admin_ve_conferencia_completa_com_financeiro(admin, app_web):
    i = app_web.banco.dav_criar("bia", "a.xlsx", "a", "Cliente A")
    app_web.banco.dav_atualizar(i, conferencia="erros", conferencia_relatorio=_conf().para_json())
    t = admin.get(f"/adm/dav/{i}").text
    assert "Conferência com o HSE" in t and "DF15653" in t
    assert "Preço &lt;b&gt;errado&lt;/b&gt;" in t and "REL &lt;i&gt;x&lt;/i&gt; completo" in t
    assert "<b>errado</b>" not in t


def test_admin_conferencia_json_quebrado_nao_derruba(admin, app_web):
    i = app_web.banco.dav_criar("bia", "a.xlsx", "a", "Cliente A")
    app_web.banco.dav_atualizar(i, conferencia="erros", conferencia_relatorio="{quebrado")
    r = admin.get(f"/adm/dav/{i}")
    assert r.status_code == 200 and "Conferência com o HSE" in r.text


def test_rascunho_com_erros_na_conferencia_aparece_em_atencao(admin, app_web):
    i = app_web.banco.dav_criar("bia", "a.xlsx", "a", "Cliente Rasc")
    app_web.banco.dav_atualizar(i, conferencia="erros", conferencia_relatorio=_conf().para_json())
    ok = app_web.banco.dav_criar("bia", "b.xlsx", "b", "Cliente Ok")
    app_web.banco.dav_atualizar(ok, conferencia="ok")
    t = admin.get("/adm/dav").text
    quadro = t.split('id="dav-quadro"')[1].split('id="historico"')[0]
    assert f"<b>#{i}</b>" in quadro and f"<b>#{ok}</b>" not in quadro
    linha = t.split(f'data-dav="{i}"')[1].split("</tr>")[0]
    assert "Com erros" in linha and "Conferindo" not in linha


@pytest.mark.parametrize("url", ["/adm/dav/erros", "/adm/dav/erros/agora"])
def test_resumo_erros_exige_administrador(app_web, monkeypatch, url):
    c = TestClient(app_web.app, follow_redirects=False)
    monkeypatch.delenv("COTAFRETE_ADM_SENHA", raising=False)
    assert c.get(url).status_code == 404
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "s3nha")
    assert c.get(url).status_code == (401 if url.endswith("/agora") else 303)


def test_resumo_erros_completo_escape_e_filtros(admin, app_web):
    for n in range(30):
        i = app_web.banco.dav_criar("bia", f"a{n}.xlsx", str(n), "Cliente <img src=x>")
        app_web.banco.dav_atualizar(i, estado="erro", erro="Local de entrega não encontrado <script>x</script>")
    outro = app_web.banco.dav_criar("ana", "outro.xlsx", "outro", "Cliente privado")
    app_web.banco.dav_atualizar(outro, estado="erro", erro="HSE fora do ar")
    url = "/adm/dav/erros?dias=7&vendedor=bia&busca=Cliente&estado=erro&categoria=endereco"
    r = admin.get(url)
    assert r.status_code == 200
    assert "30 envios" in r.text and f"/adm/dav/{i}?" in r.text
    assert "Origem" in r.text and "Onde conferir" in r.text and "Como corrigir" in r.text
    assert "&lt;script&gt;x&lt;/script&gt;" in r.text and "<script>x</script>" not in r.text
    assert "&lt;img src=x&gt;" in r.text and "Cliente privado" not in r.text
    assert "dias=7" in r.text and "vendedor=bia" in r.text and "categoria=endereco" in r.text
    painel = admin.get("/adm/dav").text
    assert 'id="dav-quadro"' in painel and 'href="/adm/dav/erros?' in painel
    pulso = admin.get(url.replace("/erros?", "/erros/agora?"))
    assert pulso.status_code == 200 and "dav-ocorrencias" in pulso.json()["fragmentos"]
    v = pulso.json()["v"]
    assert admin.get(url.replace("/erros?", "/erros/agora?") + "&v=" + v).status_code == 204


def test_resumo_conferencia_tem_detalhes_escapados(admin, app_web):
    i = app_web.banco.dav_criar("bia", "a.xlsx", "a", "Cliente A")
    app_web.banco.dav_atualizar(i, conferencia="erros", conferencia_relatorio=_conf().para_json())
    t = admin.get("/adm/dav/erros").text
    assert "Conferência inválida" in t
    assert "DF15653" in t and "&lt;i&gt;x&lt;/i&gt;" in t and "<i>x</i>" not in t
