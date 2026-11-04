"""Tela Gerar DAV (/dav): conferir, gerar, histórico, dono x admin."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from decimal import Decimal

from core.banco import Banco
from orcamento.fila_diagnostico import FilaDiagnostico
from orcamento.conferencia import FilaConferencia
from orcamento.processador import SEM_HSE, Conferencia, ItemConferido
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
    CONFERENCIA["resultado"] = _conferencia_ok()
    conferencia = FilaConferencia(banco, tmp_path / "davs", executar=lambda _p: CONFERENCIA["resultado"],
                                  disparar=lambda t: t())
    monkeypatch.setattr(dav_ui, "FILA_CONFERENCIA", conferencia, raising=False)
    diagnostico = FilaDiagnostico(banco, tmp_path / "davs", executar=lambda i: {"culpa": "teste"},
                                  disparar=lambda t: t())
    monkeypatch.setattr(dav_ui, "FILA_DIAGNOSTICO", diagnostico, raising=False)
    monkeypatch.setattr(modulo, "banco", banco)
    monkeypatch.setattr(modulo, "FILA_DAV", fila)
    monkeypatch.setattr(dav_ui, "banco", banco)
    monkeypatch.setattr(dav_ui, "FILA", fila)
    monkeypatch.setattr(adm, "banco", banco)
    return modulo


DISPARADOS: list = []
CONFERENCIA: dict = {}


def _conferencia_ok(**campos):
    base = dict(estado="ok", relatorio="", cliente="6303 - TANGARA", endereco="Rua Tal, 10",
                vendedor="ANA", itens=(ItemConferido(1, "C1", "Descricao HSE", Decimal("10.00"),
                                                     Decimal("12.50"), "codigo"),),
                avisos=(), erros=())
    return Conferencia(**{**base, **campos})


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
    # a recusada fica guardada: o ADM precisa abrir o Excel que o vendedor mandou (envio #87)
    assert [f.name for f in (tmp_path / "davs" / "entrada").glob("*")] == ["1.xlsx"]


@pytest.mark.parametrize("nome,conteudo,guardada", [
    ("a.xls", b"x", []), ("a.xlsx", b"x" * (6 * 1024 * 1024), []),
    ("a.xlsx", b"isto nao e um xlsx", ["1.xlsx"])], ids=["xls", "6mb", "corrompido"])
def test_arquivo_errado_so_registra_rejeicao(cli, app_web, tmp_path, nome, conteudo, guardada):
    r = enviar(cli, None, nome, conteudo)
    assert r.status_code == 200
    assert "/gerar" not in r.text
    assert app_web.banco.dav(1, "ana")["estado"] == "rejeitado"
    assert [f.name for f in (tmp_path / "davs" / "entrada").glob("*")] == guardada


def test_adm_baixa_a_planilha_enviada_ate_a_recusada(cli, app_web, tmp_path, monkeypatch):
    caminho = planilha(tmp_path, {"B31": None}, nome="recusada.xlsx")
    enviar(cli, caminho)
    from web import adm
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "s3nha")
    cli_adm = TestClient(app_web.app, follow_redirects=False)
    cli_adm.cookies.set(adm.COOKIE_ADM, adm.token_de("s3nha"))
    assert "/adm/dav/1/planilha" in cli_adm.get("/adm/dav/1").text
    r = cli_adm.get("/adm/dav/1/planilha")
    assert r.status_code == 200 and r.content == caminho.read_bytes()
    assert "recusada.xlsx" in r.headers["content-disposition"]
    outro = entrar(TestClient(app_web.app, follow_redirects=False), app_web, "bia")
    assert outro.get("/dav/1/planilha").status_code == 404


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
    assert cli_adm.get("/dav/1").status_code == 303
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
    assert 'data-endpoint="/dav/1/agora"' in cli.get("/dav/1").text
    app_web.banco.dav_atualizar(1, estado="incerto", numero="55")
    t = cli.get("/dav/1").text
    assert "Confira no HSE o orçamento 55 e não gere de novo" in t
    assert "Próximo passo" not in t  # uma caixa só; a orientação por origem já traz o passo
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
    from datetime import datetime
    data = datetime.fromisoformat(app_web.banco.dav(1, "ana")["criado_em"]).strftime("%d/%m/%Y")
    assert f"Confira no HSE os orçamentos deste cliente de {data} antes de gerar de novo." in t
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


def test_rejeicao_enfileira_diagnostico(cli, app_web):
    cli.post("/dav/conferir", files={"planilha": ("a.xls", b"x")})
    d = app_web.banco.dav(1, None)
    assert d["estado"] == "rejeitado" and d["diagnostico_estado"] == "feito"


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
    assert "Aviso financeiro" not in t  # pendência financeira é normal: Pronto sem aviso
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


def test_rejeicao_preserva_correcao_ate_novo_envio_pronto(cli, app_web, tmp_path):
    from contextlib import closing
    from core.painel_dav import resolvidas
    origem = app_web.banco.dav_rejeitar("ana", "antiga.xls", ["formato"])
    r = cli.post("/dav/conferir", data={"origem": origem}, files={"planilha": ("invalida.xls", b"x")})
    assert 'name="origem" value="2"' in r.text
    p = planilha(tmp_path)
    cli.post("/dav/conferir", data={"origem": 2}, files={"planilha": ("corrigida.xlsx", p.read_bytes())})
    cli.post("/dav/3/gerar")
    app_web.banco.dav_atualizar(3, estado="pronto", numero="16410")
    with closing(app_web.banco._conectar()) as con:
        assert resolvidas(con, [1, 2], "ana") == {1: 3, 2: 3}


def test_deduplicacao_na_confirmacao_resolve_origem_do_rascunho(cli, app_web, tmp_path):
    from contextlib import closing
    from core.painel_dav import resolvidas
    origem = app_web.banco.dav_rejeitar("ana", "antiga.xls", ["formato"])
    p = planilha(tmp_path)
    cli.post("/dav/conferir", data={"origem": origem}, files={"planilha": ("corrigida.xlsx", p.read_bytes())})
    enviar(cli, p)
    cli.post("/dav/3/gerar")
    app_web.banco.dav_atualizar(3, estado="pronto", numero="16410")
    r = cli.post("/dav/2/gerar")
    assert "16410" in r.text and len(DISPARADOS) == 1
    with closing(app_web.banco._conectar()) as con:
        assert resolvidas(con, [origem], "ana") == {origem: 3}


def test_resumo_mostra_observacoes_com_frete_e_descricao_dos_itens(cli, tmp_path):
    r = enviar(cli, planilha(tmp_path, {"B26": "Obs <b>", "B32": 30, "B38": "CIF", "R2": "Cor preta"}))
    assert "Obs &lt;b&gt;<br>FRETE CIF, PRAZO DE ENTREGA 30 DIAS" in r.text
    assert "<th>Descrição</th>" in r.text and "<td>Cor preta</td>" in r.text


def test_detalhe_vendedor_mostra_o_erro_do_robo_sem_o_financeiro(cli, app_web):
    # DAV 28 (29/10/2026): o vendedor corrigiu o código do item 8 lendo esse erro
    i = app_web.banco.dav_criar("ana", "a.xlsx", "a", "Cliente")
    app_web.banco.dav_atualizar(i, estado="erro", relatorio=(
        "Robô de Orçamentos HSE\nModo: REAL\nResultado: ERRO na validação com o HSE (nada foi criado)\nItens:\n\n"
        "Detalhes:\nO HSE avisou: Pendência Cliente bloqueado. Consultar o setor financeiro DE15635 Venc: 27/09/2026\n\n"
        "Erros:\nERRO: Item 8: valor unitário R$ 407,19 abaixo do mínimo R$ 16.022,50 "
        "(preço de tabela R$ 18.850,00, desconto máximo 15%)"))
    t = cli.get(f"/dav/{i}").text
    assert "Item 8: valor unitário R$ 407,19 abaixo do mínimo R$ 16.022,50" in t
    for segredo in ("DE15635", "27/09/2026"):
        assert segredo not in t


def test_conferencia_com_erros_esconde_gerar_e_mostra_corrigir(cli, app_web, tmp_path):
    CONFERENCIA["resultado"] = _conferencia_ok(estado="erros", erros=("Item 1: código <x> não existe",))
    r = enviar(cli, planilha(tmp_path))
    assert "/gerar" not in r.text
    assert 'class="alerta"' in r.text and "Item 1: código &lt;x&gt; não existe" in r.text
    assert "/dav?origem=1" in r.text
    assert cli.get("/dav?origem=1").status_code == 200


def test_conferindo_atualiza_sozinho_e_nao_tem_gerar(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    app_web.banco.dav_atualizar(1, conferencia="conferindo")
    t = cli.get("/dav/1/conferir").text
    assert '<meta http-equiv="refresh" content="5;url=/dav/1/conferir">' in t
    assert "Conferindo com o HSE" in t and "/gerar" not in t


def test_nao_conferido_avisa_e_libera_gerar(cli, app_web, tmp_path):
    CONFERENCIA["resultado"] = Conferencia("nao_conferido", "", "", "", "", (), (SEM_HSE,), ())
    r = enviar(cli, planilha(tmp_path))
    assert r.text.count(SEM_HSE) == 1 and "/dav/1/gerar" in r.text


def test_rascunho_nasce_conferindo_sem_janela_nula(cli, app_web, tmp_path, monkeypatch):
    vistos = []
    criar_original = app_web.banco.dav_criar

    def espiar(*a, **kw):
        i = criar_original(*a, **kw)
        vistos.append(app_web.banco.dav(i, None)["conferencia"])
        return i
    monkeypatch.setattr(app_web.banco, "dav_criar", espiar)
    enviar(cli, planilha(tmp_path))
    assert vistos == ["conferindo"]


def test_nao_conferido_sem_relatorio_avisa_e_libera_gerar(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    app_web.banco.dav_atualizar(1, conferencia="nao_conferido", conferencia_relatorio=None)
    t = cli.get("/dav/1/conferir").text
    assert t.count(SEM_HSE) == 1 and "/dav/1/gerar" in t


def test_rascunho_com_erros_aparece_com_erros_no_historico(cli, app_web, tmp_path):
    CONFERENCIA["resultado"] = _conferencia_ok(estado="erros", erros=("Item 1: x",))
    enviar(cli, planilha(tmp_path))
    CONFERENCIA["resultado"] = _conferencia_ok()
    enviar(cli, planilha(tmp_path, {"B36": "OC-2"}, "b.xlsx"))
    app_web.banco.dav_atualizar(2, conferencia="conferindo")
    for linha, esperado, outro in ((1, "Com erros", "Conferindo"), (2, "Conferindo", "Com erros")):
        selo = cli.get("/dav").text.split(f'data-dav="{linha}"')[1].split("</tr>")[0]
        assert esperado in selo and outro not in selo


@pytest.mark.parametrize("estado", ["conferindo", "erros"])
def test_gerar_recusado_com_conferencia_em_andamento_ou_com_erros(cli, app_web, tmp_path, estado):
    enviar(cli, planilha(tmp_path))
    app_web.banco.dav_atualizar(1, conferencia=estado)
    r = cli.post("/dav/1/gerar")
    assert (r.status_code, r.headers["location"]) == (303, "/dav/1/conferir")
    assert app_web.banco.dav(1, "ana")["estado"] == "rascunho" and not DISPARADOS


def test_rascunho_antigo_sem_conferencia_continua_gerando(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    app_web.banco.dav_atualizar(1, conferencia=None)
    t = cli.get("/dav/1/conferir").text
    assert "/dav/1/gerar" in t and "Cliente no HSE" not in t
    assert cli.post("/dav/1/gerar").headers["location"] == "/dav/1"
    assert len(DISPARADOS) == 1


def test_aviso_financeiro_da_conferencia_nao_aparece_ao_vendedor(cli, app_web, tmp_path):
    fin = "Cliente com pendência financeira: título DF15653 vencido"
    CONFERENCIA["resultado"] = _conferencia_ok(avisos=(fin, fin, "Outro aviso <b>"), estado="ok")
    t = enviar(cli, planilha(tmp_path)).text
    assert "DF15653" not in t
    assert t.count("Aviso financeiro: consulte o financeiro.") == 1
    assert "Outro aviso &lt;b&gt;" in t


def test_tabela_mostra_preco_de_tabela_e_da_planilha(cli, tmp_path):
    t = enviar(cli, planilha(tmp_path)).text
    for esperado in ("Código HSE", "Descrição no HSE", "Tabela", "Planilha", "R$ 10,00", "R$ 12,50",
                     "Descricao HSE", "6303 - TANGARA", "Rua Tal, 10"):
        assert esperado in t


def _rascunho_com_erros(cli, app_web, tmp_path):
    CONFERENCIA["resultado"] = _conferencia_ok(estado="erros", erros=("Item 1: ruim",))
    enviar(cli, planilha(tmp_path))
    return 1


def test_corrigir_rascunho_com_erros_vincula_sem_500(cli, app_web, tmp_path):
    origem = _rascunho_com_erros(cli, app_web, tmp_path)
    CONFERENCIA["resultado"] = _conferencia_ok()
    r = cli.post("/dav/conferir", data={"origem": origem},
                 files={"planilha": ("c.xlsx", planilha(tmp_path, {"B26": "outra"}, "c.xlsx").read_bytes())})
    assert r.status_code == 200
    from contextlib import closing
    with closing(app_web.banco._conectar()) as con:
        assert con.execute("SELECT destino_id FROM dav_correcao WHERE origem_id=?", (origem,)).fetchone()[0] == 2


def test_corrigir_rascunho_com_erros_enviando_planilha_invalida_nao_da_500(cli, app_web, tmp_path):
    origem = _rascunho_com_erros(cli, app_web, tmp_path)
    r = cli.post("/dav/conferir", data={"origem": origem}, files={"planilha": ("a.xls", b"x")})
    assert r.status_code == 200
    from contextlib import closing
    with closing(app_web.banco._conectar()) as con:
        assert con.execute("SELECT COUNT(*) FROM dav_correcao WHERE origem_id=?", (origem,)).fetchone()[0] == 1


def test_erros_com_json_ilegivel_explica_por_que_nao_ha_gerar(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    app_web.banco.dav_atualizar(1, conferencia="erros", conferencia_relatorio="{quebrado")
    t = cli.get("/dav/1/conferir").text
    assert "Não consegui ler o resultado da conferência" in t and "/gerar" not in t


def test_pronto_com_pendencia_financeira_fica_verde_sem_aviso(cli, app_web, tmp_path):
    enviar(cli, planilha(tmp_path))
    app_web.banco.dav_atualizar(1, estado="pronto", numero="16504", relatorio=(
        "Robô de Orçamentos HSE\nArquivo: 1.xlsx\nModo: REAL\nResultado: OK - orçamento 16504 salvo\n"
        "Itens:\nDetalhes:\nO HSE avisou: Pendência Cliente bloqueado. Consultar o setor financeiro DE16214"))
    t = cli.get("/dav/1").text
    assert "dav-resultado-box ok" in t and "dav-selo ok" in t
    assert "dav-selo atencao" not in t and "Aviso financeiro" not in t and "class=\"dav-aviso\"" not in t


def test_adm_ve_print_e_resposta_do_hse_do_envio(cli, app_web, tmp_path, monkeypatch):
    enviar(cli, planilha(tmp_path))
    prints, respostas = tmp_path / "davs" / "prints_hse", tmp_path / "davs" / "respostas_hse"
    prints.mkdir(parents=True), respostas.mkdir(parents=True)
    (prints / "1_20261104-145538.png").write_bytes(b"\x89PNG")
    (prints / "11_20261104-145538.png").write_bytes(b"outro envio")
    (respostas / "1_20261104-145538_76817.html").write_text("<script>toastSuccess('Margem atualizada')</script>")
    from web import adm
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "s3nha")
    cli_adm = TestClient(app_web.app, follow_redirects=False)
    cli_adm.cookies.set(adm.COOKIE_ADM, adm.token_de("s3nha"))
    t = cli_adm.get("/adm/dav/1").text
    assert '<img src="/adm/dav/1/hse/1_20261104-145538.png"' in t and "11_2026" not in t
    assert "/adm/dav/1/hse/1_20261104-145538_76817.html" in t
    assert cli_adm.get("/adm/dav/1/hse/1_20261104-145538.png").content == b"\x89PNG"
    r = cli_adm.get("/adm/dav/1/hse/1_20261104-145538_76817.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert cli_adm.get("/adm/dav/1/hse/11_20261104-145538.png").status_code == 404
    assert cli_adm.get("/adm/dav/1/hse/..%2Fteste.db").status_code == 404
    assert "prints_hse" not in cli.get("/dav/1").text and "/hse/" not in cli.get("/dav/1").text


def _adm(app_web, monkeypatch):
    from web import adm
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "s3nha")
    c = TestClient(app_web.app, follow_redirects=False)
    c.cookies.set(adm.COOKIE_ADM, adm.token_de("s3nha"))
    return c


def _diag(**campos):
    import json
    base = dict(culpa="robo", causa="Falhou <b>x</b>", acao="Rodar de novo", evidencia="log", confianca="media",
                criados_no_hse=[16533, 16534], custo=0.0004)
    return json.dumps({**base, **campos})


def test_adm_ve_cartao_diagnostico_vendedor_nao(cli, app_web, tmp_path, monkeypatch):
    enviar(cli, planilha(tmp_path))
    app_web.banco.dav_atualizar(1, estado="erro", diagnostico=_diag(), diagnostico_estado="feito")
    t = _adm(app_web, monkeypatch).get("/adm/dav/1").text
    assert "Robô" in t and "16533, 16534" in t and "Diagnosticar de novo" in t
    assert "US$ 0,0004" in t and "média" in t and "<b>x</b>" not in t
    v = cli.get("/dav/1").text
    assert "Diagnosticar de novo" not in v and "16533" not in v


def test_diagnostico_nao_verificado_nada_e_pendente(cli, app_web, tmp_path, monkeypatch):
    enviar(cli, planilha(tmp_path))
    adm = _adm(app_web, monkeypatch)
    app_web.banco.dav_atualizar(1, estado="erro", diagnostico_estado="feito",
                                diagnostico=_diag(criados_no_hse="nao_verificado", motivo_nao_verificado="HSE indisponível"))
    assert "Não verificado (HSE indisponível)" in adm.get("/adm/dav/1").text
    app_web.banco.dav_atualizar(1, diagnostico=_diag(criados_no_hse=[]))
    assert "Nada criado" in adm.get("/adm/dav/1").text
    app_web.banco.dav_atualizar(1, diagnostico_estado="pendente")
    assert "Diagnosticando" in adm.get("/adm/dav/1").text


def test_post_diagnosticar_exige_adm_e_enfileira(cli, app_web, tmp_path, monkeypatch):
    enviar(cli, planilha(tmp_path))
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "s3nha")
    r = TestClient(app_web.app, follow_redirects=False).post("/adm/dav/1/diagnosticar")
    assert r.status_code == 303 and "/adm/entrar" in r.headers["location"]
    chamadas = []
    from web import dav_ui
    monkeypatch.setattr(dav_ui, "FILA_DIAGNOSTICO", type("F", (), {"enfileirar": lambda s, i: (
        chamadas.append(i), app_web.banco.dav_atualizar(i, diagnostico_estado="pendente"))})())
    r = _adm(app_web, monkeypatch).post("/adm/dav/1/diagnosticar")
    assert r.status_code == 303 and r.headers["location"] == "/adm/dav/1" and chamadas == [1]
    assert app_web.banco.dav(1, None)["diagnostico_estado"] == "pendente"


def test_cartao_mostra_produtos_cadastrados_e_rascunhos(cli, app_web, tmp_path, monkeypatch):
    enviar(cli, planilha(tmp_path))
    app_web.banco.dav_atualizar(1, estado="erro", diagnostico_estado="feito", diagnostico=_diag(
        criados_no_hse="nao_verificado", rascunhos=[16492], produtos_criados=["76811 - terminal <i>pin</i>"]))
    t = _adm(app_web, monkeypatch).get("/adm/dav/1").text
    assert "Produtos cadastrados" in t and "76811 - terminal &lt;i&gt;pin&lt;/i&gt;" in t
    assert "Rascunhos do robô" in t and "16492" in t and "Não verificado" in t
