"""Tela Gerar DAV (/dav): conferir, gerar, histórico, dono x admin."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from orcamento.fila import FilaDav
from tests.apoio import entrar
from tests.orcamento.planilhas.gerar import criar


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    from web import adm, dav_ui
    banco = Banco(tmp_path / "teste.db")
    fila = FilaDav(banco, tmp_path / "davs", disparar=lambda t: DISPARADOS.append(t))
    DISPARADOS.clear()
    monkeypatch.setattr(modulo, "banco", banco)
    monkeypatch.setattr(modulo, "FILA_DAV", fila)
    monkeypatch.setattr(dav_ui, "banco", banco)
    monkeypatch.setattr(dav_ui, "FILA", fila)
    monkeypatch.setattr(adm, "banco", banco)
    return modulo


DISPARADOS: list = []


@pytest.fixture
def cli(app_web):
    return entrar(TestClient(app_web.app, follow_redirects=False), app_web, "ana")


def planilha(tmp_path, celulas=None, nome="orc.xlsx"):
    return criar(tmp_path, celulas, nome)


def enviar(c, caminho, nome=None, conteudo=None):
    dados = conteudo if conteudo is not None else caminho.read_bytes()
    return c.post("/dav/conferir",
                  files={"planilha": (nome or caminho.name, dados)})


def test_sem_login_vai_para_login(app_web):
    r = TestClient(app_web.app, follow_redirects=False).get("/dav")
    assert (r.status_code, r.headers["location"]) == (303, "/login")


def test_conferir_boa_mostra_resumo_e_botao_gerar(cli, app_web, tmp_path):
    r = enviar(cli, planilha(tmp_path))
    assert r.status_code == 200
    assert "Gerar" in r.text and "/gerar" in r.text
    d = app_web.banco.dav(1, "ana")
    assert d["estado"] == "rascunho"
    assert (tmp_path / "davs" / "entrada" / "1.xlsx").exists()


def test_conferir_com_erro_lista_erros_sem_botao_nem_linha(cli, app_web, tmp_path):
    r = enviar(cli, planilha(tmp_path, {"B31": None}))
    assert r.status_code == 200
    assert "/gerar" not in r.text
    assert app_web.banco.dav(1, None) is None
    assert not list((tmp_path / "davs" / "entrada").glob("*"))


@pytest.mark.parametrize("nome,conteudo", [
    ("a.xls", b"x"), ("a.xlsx", b"x" * (6 * 1024 * 1024)),
    ("a.xlsx", b"isto nao e um xlsx")], ids=["xls", "6mb", "corrompido"])
def test_arquivo_errado_nada_criado(cli, app_web, tmp_path, nome, conteudo):
    r = enviar(cli, None, nome, conteudo)
    assert r.status_code == 200
    assert "/gerar" not in r.text
    assert app_web.banco.dav(1, None) is None
    assert not list((tmp_path / "davs" / "entrada").glob("*"))


def test_gerar_enfileira_uma_vez(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    r = cli.post("/dav/1/gerar")
    assert (r.status_code, r.headers["location"]) == (303, "/dav/1")
    assert app_web.banco.dav(1, "ana")["estado"] == "fila"
    cli.post("/dav/1/gerar")
    assert len(DISPARADOS) == 1


def test_mesma_planilha_depois_de_gerar_ja_gerou(cli, app_web, tmp_path):
    p = planilha(tmp_path)
    enviar(cli, p)
    cli.post("/dav/1/gerar")
    app_web.banco.dav_atualizar(1, estado="pronto", numero="777")
    r = enviar(cli, p)
    assert "já gerou o orçamento 777" in r.text
    assert "/gerar" not in r.text
    assert len(DISPARADOS) == 1


def test_rascunho_duplicado_nao_gera_de_novo(cli, app_web, tmp_path):
    p = planilha(tmp_path)
    enviar(cli, p)
    enviar(cli, p)           # dois rascunhos do mesmo arquivo
    cli.post("/dav/1/gerar")
    r = cli.post("/dav/2/gerar")
    assert r.status_code == 200 and "já gerou" in r.text
    assert app_web.banco.dav(2, "ana")["estado"] == "rascunho"
    assert len(DISPARADOS) == 1


def test_outro_vendedor_recebe_404_admin_200(cli, app_web, tmp_path, monkeypatch):
    enviar(cli, planilha(tmp_path))
    cli.post("/dav/1/gerar")
    pdf = tmp_path / "davs" / "pdf" / "x.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    app_web.banco.dav_atualizar(1, estado="pronto", numero="9", pdf=str(pdf))
    outro = entrar(TestClient(app_web.app, follow_redirects=False), app_web, "bia")
    assert outro.get("/dav/1").status_code == 404
    assert outro.get("/dav/1/pdf").status_code == 404
    assert outro.post("/dav/1/gerar").status_code == 404
    assert cli.get("/dav/1/pdf").status_code == 200
    from web import adm
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "s3nha")
    cli_adm = TestClient(app_web.app, follow_redirects=False)
    cli_adm.cookies.set(adm.COOKIE_ADM, adm.token_de("s3nha"))
    assert cli_adm.get("/dav/1").status_code == 200
    assert cli_adm.get("/dav/1/pdf").status_code == 200
    assert "ana" in cli_adm.get("/adm/dav").text


def test_pdf_fora_da_pasta_davs_pdf_404(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    fora = tmp_path / "segredo.pdf"
    fora.write_bytes(b"x")
    app_web.banco.dav_atualizar(1, estado="pronto", numero="9", pdf=str(fora))
    assert cli.get("/dav/1/pdf").status_code == 404


def test_estados_da_pagina(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    cli.post("/dav/1/gerar")
    assert 'http-equiv="refresh"' in cli.get("/dav/1").text
    app_web.banco.dav_atualizar(1, estado="incerto", numero="55")
    t = cli.get("/dav/1").text
    assert "confira no HSE o orçamento 55 e não gere de novo" in t
    assert 'http-equiv="refresh"' not in t
    app_web.banco.dav_atualizar(1, estado="pronto", relatorio="LINHA <b>x</b>", pdf="x.pdf")
    t = cli.get("/dav/1").text
    assert "Baixar PDF" in t and "&lt;b&gt;" in t
    app_web.banco.dav_atualizar(1, estado="erro", erro="deu ruim")
    assert "deu ruim" in cli.get("/dav/1").text


def test_historico_so_do_vendedor(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    cli.post("/dav/1/gerar")
    outro = entrar(TestClient(app_web.app, follow_redirects=False), app_web, "bia")
    enviar(outro, planilha(tmp_path, {"A2": None, "B2": 3}, "outra.xlsx"))
    outro.post("/dav/2/gerar")
    t = cli.get("/dav").text
    assert "orc.xlsx" in t and "outra.xlsx" not in t


def test_adm_dav_sem_admin_redireciona(app_web, monkeypatch):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "s3nha")
    r = TestClient(app_web.app, follow_redirects=False).get("/adm/dav")
    assert r.status_code == 303 and r.headers["location"] == "/adm/entrar"


def test_nome_do_arquivo_escapado(cli, app_web, tmp_path):
    p = planilha(tmp_path)
    enviar(cli, p, nome="<b onload=x>.xlsx")
    cli.post("/dav/1/gerar")
    t = cli.get("/dav").text
    assert "<b onload" not in t and "&lt;b onload" in t


def test_modelo_baixa(cli):
    assert cli.get("/dav/modelo").status_code == 200
