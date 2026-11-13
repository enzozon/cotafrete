"""API do DAV para o Maestro (/api/dav): token, conferência automática, Gerar, NCM."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from orcamento.conferencia import FilaConferencia
from orcamento.fila import FilaDav
from orcamento.fila_diagnostico import FilaDiagnostico
from orcamento.processador import Conferencia, ItemConferido
from tests.orcamento.planilhas.gerar import NOVO, criar

TOKEN = "segredo-de-teste"
CAB = {"Authorization": f"Bearer {TOKEN}"}
DISPARADOS: list = []
CONFERENCIA: dict = {}


def _conferencia(**campos):
    base = dict(estado="ok", relatorio="", cliente="18373 - CLIENTE", endereco="Rua Tal, 10",
                vendedor="ELIZIANE", itens=(ItemConferido(1, "13370", "Descricao HSE", Decimal("10.00"),
                                                          Decimal("145.00"), "codigo"),),
                avisos=(), erros=())
    return Conferencia(**{**base, **campos})


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    from web import adm, api_dav, dav_ui
    monkeypatch.setenv("DAV_API_TOKEN", TOKEN)
    banco = Banco(tmp_path / "teste.db")
    fila = FilaDav(banco, tmp_path / "davs", disparar=lambda t: DISPARADOS.append(t))
    DISPARADOS.clear()
    CONFERENCIA["resultado"] = _conferencia()
    conferencia = FilaConferencia(banco, tmp_path / "davs", executar=lambda _p: CONFERENCIA["resultado"],
                                  disparar=lambda t: t(), ao_terminar=api_dav.seguir)
    diagnostico = FilaDiagnostico(banco, tmp_path / "davs", executar=lambda i: {"culpa": "teste"},
                                  disparar=lambda t: t())
    for mod in (dav_ui, api_dav):
        monkeypatch.setattr(mod, "banco", banco)
        monkeypatch.setattr(mod, "FILA", fila)
        monkeypatch.setattr(mod, "FILA_CONFERENCIA", conferencia, raising=False)
        monkeypatch.setattr(mod, "FILA_DIAGNOSTICO", diagnostico, raising=False)
    monkeypatch.setattr(modulo, "banco", banco)
    monkeypatch.setattr(modulo, "FILA_DAV", fila)
    monkeypatch.setattr(adm, "banco", banco)
    return modulo


@pytest.fixture
def cli(app_web):
    return TestClient(app_web.app, follow_redirects=False)


def enviar(cli, caminho, vendedor="allan", cotacao="301015", cab=CAB, nome=None):
    return cli.post("/api/dav", headers=cab, data={"vendedor": vendedor, "cotacao": cotacao},
                    files={"planilha": (nome or caminho.name, caminho.read_bytes())})


def test_sem_token_no_servidor_a_api_fica_desligada(cli, tmp_path, monkeypatch):
    monkeypatch.delenv("DAV_API_TOKEN")
    r = enviar(cli, criar(tmp_path))
    assert r.status_code == 503 and "DAV_API_TOKEN" in r.json()["detail"]


@pytest.mark.parametrize("cab", [{}, {"Authorization": "Bearer errado"}, {"Authorization": "Bearer çã".encode("latin-1")}])
def test_token_errado_ou_ausente_e_recusado(cli, app_web, tmp_path, cab):
    assert enviar(cli, criar(tmp_path), cab=cab).status_code == 401
    assert cli.get("/api/dav/1", headers=cab).status_code == 401
    assert app_web.banco.dav(1, None) is None


def test_planilha_boa_confere_e_vai_sozinha_para_o_gerar(cli, app_web, tmp_path):
    r = enviar(cli, criar(tmp_path))
    assert r.status_code == 201
    corpo = r.json()
    assert corpo["id"] == 1 and corpo["cotacao"] == "301015" and corpo["ja_existia"] is False
    d = app_web.banco.dav(1, None)
    assert (d["usuario"], d["estado"], d["conferencia"], d["api_cotacao"]) == ("maestro:allan", "fila", "ok", "301015")
    assert len(DISPARADOS) == 1   # entrou na fila do Gerar sem ninguém clicar
    assert cli.get("/api/dav/1", headers=CAB).json()["estado"] == "gerando"


def test_conferencia_com_avisos_gera_e_devolve_os_avisos(cli, app_web, tmp_path):
    CONFERENCIA["resultado"] = _conferencia(avisos=("Item 1: confira o preço",))
    enviar(cli, criar(tmp_path))
    corpo = cli.get("/api/dav/1", headers=CAB).json()
    assert corpo["estado"] == "gerando" and corpo["avisos"] == ["Item 1: confira o preço"]
    assert len(DISPARADOS) == 1


def test_conferencia_com_erros_para_e_devolve_os_motivos(cli, app_web, tmp_path):
    CONFERENCIA["resultado"] = _conferencia(estado="erros", erros=("Item 1: código 13370 inativo no HSE",))
    enviar(cli, criar(tmp_path))
    corpo = cli.get("/api/dav/1", headers=CAB).json()
    assert corpo["estado"] == "erros" and corpo["erros"] == ["Item 1: código 13370 inativo no HSE"]
    assert DISPARADOS == [] and app_web.banco.dav(1, None)["estado"] == "rascunho"


def test_sem_hse_para_conferir_segue_para_o_gerar_como_na_tela(cli, app_web, tmp_path):
    CONFERENCIA["resultado"] = _conferencia(estado="nao_conferido")
    enviar(cli, criar(tmp_path))
    assert app_web.banco.dav(1, None)["estado"] == "fila" and len(DISPARADOS) == 1


def test_erro_financeiro_vira_aviso_unico_para_o_vendedor(cli, app_web, tmp_path):
    CONFERENCIA["resultado"] = _conferencia(estado="erros", erros=("Cliente bloqueado: pendência financeira R$ 900",))
    enviar(cli, criar(tmp_path))
    assert cli.get("/api/dav/1", headers=CAB).json()["erros"] == ["Aviso financeiro: consulte o financeiro."]


def test_planilha_invalida_responde_422_com_os_motivos(cli, app_web, tmp_path):
    r = enviar(cli, criar(tmp_path, {"A30": "Local de entrega", "B30": "CENTRO"}))
    assert r.status_code == 422
    corpo = r.json()
    assert corpo["estado"] == "erros" and corpo["erros"][0].startswith("Planilha antiga")
    assert app_web.banco.dav(1, None)["estado"] == "rejeitado" and DISPARADOS == []


def test_arquivo_que_nao_e_xlsx_e_recusado(cli, tmp_path):
    caminho = tmp_path / "x.pdf"
    caminho.write_bytes(b"%PDF")
    r = enviar(cli, caminho)
    assert r.status_code == 422 and ".xlsx" in r.json()["erros"][0]


@pytest.mark.parametrize("campos", [{"vendedor": "", "cotacao": "1"}, {"vendedor": "a", "cotacao": "<x>"}])
def test_vendedor_e_cotacao_obrigatorios(cli, tmp_path, campos):
    r = cli.post("/api/dav", headers=CAB, data=campos,
                 files={"planilha": ("p.xlsx", criar(tmp_path).read_bytes())})
    assert r.status_code in (400, 422)


def test_mesma_planilha_de_novo_devolve_o_dav_que_ja_existe(cli, app_web, tmp_path):
    caminho = criar(tmp_path)
    enviar(cli, caminho)
    r = enviar(cli, caminho)
    assert r.status_code == 200 and r.json()["id"] == 1 and r.json()["ja_existia"] is True
    assert len(DISPARADOS) == 1   # não gera duas vezes


def test_outro_vendedor_com_a_mesma_planilha_e_outro_dav(cli, app_web, tmp_path):
    caminho = criar(tmp_path)
    enviar(cli, caminho, vendedor="allan")
    assert enviar(cli, caminho, vendedor="bia").json()["id"] == 2


def test_pronto_devolve_numero_ncm_e_pdf(cli, app_web, tmp_path):
    caminho = criar(tmp_path, NOVO)
    enviar(cli, caminho)
    pdf = tmp_path / "davs" / "pdf" / "DAV_16700_CLIENTE.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 teste")
    app_web.banco.dav_atualizar(1, estado="pronto", numero="16700", pdf=str(pdf), relatorio=(
        "Itens:\nItem 1: usou produto existente 13370 - MOUSE (pelo código informado)\n"
        "Item 2: CADASTROU produto novo 20001 - PRODUTO TESTE | NCM 84716053 | Origem 0 | ICMS 17% | "
        "custo R$ 45,00 | grupo INFORMATICA | marca DELL\n"))
    corpo = cli.get("/api/dav/1", headers=CAB).json()
    assert (corpo["estado"], corpo["numero"], corpo["pdf"], corpo["erros"]) == ("pronto", "16700", True, [])
    assert corpo["itens"] == [
        {"item": 1, "codigo": "13370", "ncm": None, "origem": "cadastro HSE"},
        {"item": 2, "codigo": None, "ncm": "84716053", "origem": "planilha"}]
    r = cli.get("/api/dav/1/pdf", headers=CAB)
    assert r.status_code == 200 and r.content == b"%PDF-1.4 teste"


def test_ncm_preenchido_pela_ia_vem_com_origem_ia(cli, app_web, tmp_path):
    enviar(cli, criar(tmp_path, {**NOVO, "L3": None}))
    app_web.banco.dav_atualizar(1, estado="pronto", numero="16701", relatorio=(
        "Item 2: CADASTROU produto novo 20002 - PRODUTO TESTE | NCM 84716052 | Origem 0 | ICMS 17% | "
        "custo R$ 45,00 | grupo INFORMATICA | marca DELL\n"
        "Detalhes:\nItem 2: NCM sugerido por IA: 84716052 (confira antes de faturar)\n"))
    itens = cli.get("/api/dav/1", headers=CAB).json()["itens"]
    assert itens[1] == {"item": 2, "codigo": None, "ncm": "84716052", "origem": "IA"}


def test_pdf_antes_de_pronto_e_409(cli, tmp_path):
    enviar(cli, criar(tmp_path))
    assert cli.get("/api/dav/1/pdf", headers=CAB).status_code == 409


def test_pdf_fora_da_pasta_de_pdfs_nao_sai(cli, app_web, tmp_path):
    enviar(cli, criar(tmp_path))
    fora = tmp_path / "segredo.pdf"
    fora.write_bytes(b"x")
    app_web.banco.dav_atualizar(1, estado="pronto", numero="1", pdf=str(fora))
    assert cli.get("/api/dav/1/pdf", headers=CAB).status_code == 404


def test_incerto_avisa_e_nunca_volta_para_a_fila(cli, app_web, tmp_path):
    from web import api_dav
    caminho = criar(tmp_path)
    enviar(cli, caminho)
    DISPARADOS.clear()
    app_web.banco.dav_atualizar(1, estado="incerto", numero="16702", erro="O servidor reiniciou durante o DAV.")
    api_dav.seguir(1)
    api_dav.retomar()
    corpo = cli.get("/api/dav/1", headers=CAB).json()
    assert corpo["estado"] == "incerto" and api_dav.INCERTO in corpo["erros"] and DISPARADOS == []
    # reenviar a mesma planilha não gera outro: devolve o incerto
    assert enviar(cli, caminho).json()["estado"] == "incerto" and DISPARADOS == []


def test_simulado_vira_erro_explicado(cli, app_web, tmp_path):
    from web import api_dav
    enviar(cli, criar(tmp_path))
    app_web.banco.dav_atualizar(1, estado="simulado")
    corpo = cli.get("/api/dav/1", headers=CAB).json()
    assert corpo["estado"] == "erro" and corpo["erros"] == [api_dav.SIMULADO]


def test_dav_da_tela_nao_aparece_na_api(cli, app_web):
    app_web.banco.dav_criar("ana", "x.xlsx", "h", "C")
    assert cli.get("/api/dav/1", headers=CAB).status_code == 404


def test_retomar_leva_para_a_fila_o_que_a_queda_deixou_conferido(cli, app_web, tmp_path):
    from web import api_dav
    CONFERENCIA["resultado"] = _conferencia(estado="erros", erros=("x",))
    enviar(cli, criar(tmp_path))
    app_web.banco.dav_atualizar(1, conferencia="nao_conferido")   # como o retomar da conferência deixa
    api_dav.retomar()
    assert app_web.banco.dav(1, None)["estado"] == "fila" and len(DISPARADOS) == 1


def test_token_nao_vaza_em_texto_limpo(monkeypatch):
    from orcamento.processador import _sem_segredo
    monkeypatch.setenv("DAV_API_TOKEN", TOKEN)
    assert _sem_segredo(f"erro com {TOKEN}") == "erro com ***"
