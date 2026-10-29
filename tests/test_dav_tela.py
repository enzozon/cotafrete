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


def test_conferir_com_erro_registra_rejeicao_sem_gerar(cli, app_web, tmp_path):
    r = enviar(cli, planilha(tmp_path, {"B31": None}))
    assert r.status_code == 200
    assert "/gerar" not in r.text
    assert app_web.banco.dav(1, "ana")["estado"] == "rejeitado"
    assert not list((tmp_path / "davs" / "entrada").glob("*"))


@pytest.mark.parametrize("nome,conteudo", [
    ("a.xls", b"x"), ("a.xlsx", b"x" * (6 * 1024 * 1024)),
    ("a.xlsx", b"isto nao e um xlsx")], ids=["xls", "6mb", "corrompido"])
def test_arquivo_errado_so_registra_rejeicao(cli, app_web, tmp_path, nome, conteudo):
    r = enviar(cli, None, nome, conteudo)
    assert r.status_code == 200
    assert "/gerar" not in r.text
    assert app_web.banco.dav(1, "ana")["estado"] == "rejeitado"
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
    assert "Baixar PDF" in t and "<b>x</b>" not in t
    app_web.banco.dav_atualizar(1, estado="erro", erro="deu ruim", numero=None)
    assert "Motivo não identificado" in cli.get("/dav/1").text


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


def test_incerto_sem_numero_nao_tem_buraco_no_aviso(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    cli.post("/dav/1/gerar")
    app_web.banco.dav_atualizar(1, estado="incerto")
    t = cli.get("/dav/1").text
    assert "Confira no HSE os orçamentos deste cliente de hoje antes de gerar de novo." in t
    assert "orçamento  e" not in t


def test_historico_tem_coluna_pdf_com_link_so_quando_ha_pdf(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    cli.post("/dav/1/gerar")
    t = cli.get("/dav").text
    assert "<th>PDF</th>" in t and "/dav/1/pdf" not in t
    app_web.banco.dav_atualizar(1, estado="pronto", numero="9", pdf="x.pdf")
    assert '<a href="/dav/1/pdf">PDF</a>' in cli.get("/dav").text


def test_conferir_roda_na_threadpool_nao_no_loop():
    import inspect
    from web import dav_ui
    assert not inspect.iscoroutinefunction(dav_ui.conferir)


def test_retomar_que_falha_nao_impede_o_servidor_de_subir(app_web, monkeypatch):
    def quebra():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(app_web.FILA_DAV, "retomar", quebra)
    monkeypatch.setattr(app_web.dv_ingestor, "iniciar", lambda b: None)
    monkeypatch.setattr(app_web.me_ui, "iniciar_vigia", lambda: None)
    monkeypatch.setattr(app_web, "INGESTOR", None)
    with TestClient(app_web.app) as c:
        assert c.get("/login").status_code == 200


def test_corrigir_referencia_origem_e_preserva_dono(cli, app_web, tmp_path):
    origem = app_web.banco.dav_rejeitar("ana", "antiga.xls", ["formato"])
    assert f'value="{origem}"' in cli.get(f"/dav?origem={origem}").text
    r = cli.post("/dav/conferir", data={"origem": origem},
                 files={"planilha": ("nova.xlsx", planilha(tmp_path).read_bytes())})
    assert r.status_code == 200 and "/gerar" in r.text
    from contextlib import closing
    with closing(app_web.banco._conectar()) as con:
        assert tuple(con.execute("SELECT origem_id, destino_id FROM dav_correcao").fetchone()) == (origem, 2)
    assert DISPARADOS == []


@pytest.mark.parametrize("estado,usuario,numero,esperado", [
    ("erro", "bia", None, 404), ("incerto", "ana", None, 409),
    ("erro", "ana", "16410", 409), ("pronto", "ana", None, 409)])
def test_origem_forjada_e_incerta_nao_permite_correcao(cli, app_web, tmp_path, estado, usuario, numero, esperado):
    i = app_web.banco.dav_criar(usuario, "antes.xlsx", "x", "A")
    app_web.banco.dav_atualizar(i, estado=estado, numero=numero)
    r = cli.post("/dav/conferir", data={"origem": i}, files={"planilha": ("a.xlsx", b"x")})
    assert r.status_code == esperado
    assert app_web.banco.dav(2, None) is None and not DISPARADOS


def test_correcao_deduplicada_vincula_resultado_existente(cli, app_web, tmp_path):
    p = planilha(tmp_path)
    enviar(cli, p)
    cli.post("/dav/1/gerar")
    app_web.banco.dav_atualizar(1, estado="pronto", numero="777")
    origem = app_web.banco.dav_rejeitar("ana", "invalida.xls", ["formato"])
    r = cli.post("/dav/conferir", data={"origem": origem}, files={"planilha": ("a.xlsx", p.read_bytes())})
    assert r.status_code == 200 and "777" in r.text
    from contextlib import closing
    with closing(app_web.banco._conectar()) as con:
        assert tuple(con.execute("SELECT origem_id, destino_id FROM dav_correcao").fetchone()) == (origem, 1)
    assert app_web.banco.dav(3, None) is None and len(DISPARADOS) == 1


def test_rejeicao_de_reenvio_tem_vinculo_e_sem_login_nao_grava(cli, app_web):
    origem = app_web.banco.dav_rejeitar("ana", "a.xls", ["formato"])
    cli.post("/dav/conferir", data={"origem": origem}, files={"planilha": ("a.xls", b"x")})
    from contextlib import closing
    with closing(app_web.banco._conectar()) as con:
        assert tuple(con.execute("SELECT origem_id, destino_id FROM dav_correcao").fetchone()) == (origem, 2)
    sem_login = TestClient(app_web.app, follow_redirects=False)
    assert sem_login.post("/dav/conferir", files={"planilha": ("a.xls", b"x")}).status_code == 303
    assert app_web.banco.dav(3, None) is None


def test_detalhe_vendedor_nao_embute_relatorio_privado(cli, app_web):
    i = app_web.banco.dav_criar("ana", "a.xlsx", "a", "Cliente")
    app_web.banco.dav_atualizar(i, estado="pronto", numero="16410", relatorio=(
        "Robô de Orçamentos HSE\nResultado: OK\nItens:\n\nDetalhes:\n"
        "O HSE avisou: Pendência financeira DF15653 valor 1234,56 Venc: 27/09/2026"))
    t = cli.get(f"/dav/{i}").text
    assert "financeiro" in t
    for segredo in ("DF15653", "1234,56", "27/09/2026"):
        assert segredo not in t


def test_reabrir_rascunho_preserva_confirmacao(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    t = cli.get("/dav/1/conferir")
    assert t.status_code == 200 and "/dav/1/gerar" in t.text
    assert "Local de entrega" in t.text and "Pagamento" in t.text and "Observações" in t.text
    assert app_web.banco.dav(2, None) is None and not DISPARADOS
    outro = entrar(TestClient(app_web.app, follow_redirects=False), app_web, "bia")
    assert outro.get("/dav/1/conferir").status_code == 404
    (tmp_path / "davs" / "entrada" / "1.xlsx").unlink()
    assert "/gerar" not in cli.get("/dav/1/conferir").text


def test_incerto_nao_oferece_reenvio_mesmo_quando_estado_e_erro(cli, app_web):
    i = app_web.banco.dav_criar("ana", "a.xlsx", "x", "Cliente")
    app_web.banco.dav_atualizar(i, estado="erro", numero="16410")
    t = cli.get(f"/dav/{i}").text
    assert "Confira no HSE" in t
    assert "Enviar planilha corrigida" not in t and "/gerar" not in t


def test_historico_filtra_no_servidor_e_mostra_motivo(cli, app_web):
    i = app_web.banco.dav_criar("ana", "erro.xlsx", "e", "Cliente")
    app_web.banco.dav_atualizar(i, estado="erro", erro="Local de entrega não encontrado")
    p = app_web.banco.dav_criar("ana", "pronto.xlsx", "p", "Cliente")
    app_web.banco.dav_atualizar(p, estado="pronto")
    t = cli.get("/dav?estado=erro").text
    assert "erro.xlsx" in t and "pronto.xlsx" not in t
    assert "local de entrega" in t.lower()


def test_envios_concorrentes_nao_duplicam_geracao(cli, app_web, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    p = planilha(tmp_path)
    enviar(cli, p)
    enviar(cli, p)
    with ThreadPoolExecutor(max_workers=2) as pool:
        respostas = list(pool.map(lambda i: cli.post(f"/dav/{i}/gerar").status_code, [1, 2]))
    assert set(respostas) <= {200, 303}
    assert len(DISPARADOS) == 1
