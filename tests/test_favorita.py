"""Favorita: o portal da Generoso com outra conta (carriers/favorita).

O que pode quebrar não é a mecânica — essa é a da Generoso e tem os testes
dela — e sim o que muda de uma conta para a outra: endereço, credencial,
empresas do "Alterar empresa", trava e o nome nas frases para o vendedor.

tests/fixtures/favorita_carga.html é o DOM real da etapa da Carga, capturado
logado em 13/10/2026 por recon/recon_favorita.py --ate-carga.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carriers.favorita.adapter import FavoritaAdapter
from carriers.generoso.adapter import EMBALAGENS, GenerosoAdapter
from core.models import Parte, StatusCotacao, TipoFrete
from tests.test_jadlog import montar

VENTURA = Parte(cnpj="08.310.365/0001-24")
ALIANCA = Parte(cnpj="05.954.058/0001-98")
FIXTURE = (Path(__file__).parent / "fixtures" / "favorita_carga.html").resolve()


def test_aponta_para_o_portal_e_a_credencial_da_favorita(monkeypatch):
    monkeypatch.setenv("FAVORITA_USUARIO", "u@favorita")
    monkeypatch.setenv("FAVORITA_SENHA", "s")
    monkeypatch.setenv("GENEROSO_USUARIO", "u@generoso")
    a = FavoritaAdapter()
    assert a.url_base == "https://cliente.favorita.com.br"
    assert a.usuario == "u@favorita"
    assert a.workdir == Path("teste_real/favorita")


def test_trava_propria_nao_espera_pela_generoso():
    assert FavoritaAdapter.trava_conta is not GenerosoAdapter.trava_conta


def test_sem_credencial_nao_abre_navegador(monkeypatch):
    monkeypatch.delenv("FAVORITA_USUARIO", raising=False)
    monkeypatch.delenv("FAVORITA_SENHA", raising=False)
    res = FavoritaAdapter().cotar(montar(remetente=VENTURA))
    assert res.status is StatusCotacao.ERRO
    assert "FAVORITA_USUARIO" in res.erro and "Generoso" not in res.erro


def test_cif_com_a_ventura_na_origem_passa():
    assert FavoritaAdapter().validar(montar(remetente=VENTURA)) == []


def test_alianca_nao_e_empresa_da_conta_da_favorita():
    """Na Generoso a Aliança está no menu; na Favorita não. CIF com ela na
    origem sairia com o endereço da Ventura — então barra, e com o nome
    certo da transportadora."""
    erros = FavoritaAdapter().validar(montar(remetente=ALIANCA))
    assert erros and erros[0].campo == "CIF/FOB"
    assert "Favorita" in erros[0].mensagem
    assert "Generoso" not in erros[0].mensagem
    # e a Generoso continua aceitando, porque lá a Aliança existe
    assert GenerosoAdapter().validar(montar(remetente=ALIANCA)) == []


def test_cif_fob_trocado_fala_em_favorita():
    req = montar(destinatario=VENTURA, tipo_frete=TipoFrete.CIF)
    msgs = " ".join(e.mensagem for e in FavoritaAdapter().validar(req))
    assert "Marque FOB" in msgs and "Generoso" not in msgs


def test_recusas_da_tela_falam_em_favorita():
    a = FavoritaAdapter()
    limite = a.normalizar_resposta(
        "A carga ultrapassou os limites permitidos para o site. "
        "Peso máximo: 500 kg")
    assert limite.status is StatusCotacao.RECUSADO
    assert "Favorita" in limite.motivo_recusa
    parceira = a.normalizar_resposta(
        "Aguardando validação. Atendida por unidades parceiras.")
    assert "Favorita" in parceira.motivo_recusa
    assert "rodonaves" not in parceira.motivo_recusa


def test_le_a_tela_de_resultado_real():
    """Texto da cotação 371121, o envio real de 13/10/2026."""
    res = FavoritaAdapter().normalizar_resposta(
        "Resultado da cotação\n\nNova cotação\nLista de cotações\n"
        "Cotação: 371121\nFrete\nR$ 260,42\nPrevisão de entrega\n21/10/26\n"
        "Cotado em\n13/10/26\nCotação válida até\n23/10/26\n"
        "O valor de R$ 260,42 é válido para contratação até dia 23/10/26, "
        "considerando os dados iguais ao da NFe\nAgendar coleta")
    assert res.status is StatusCotacao.COTADO
    assert res.protocolo == "371121"
    assert str(res.valor_frete) == "260.42"
    assert res.prazo_dias == 8
    assert str(res.validade) == "2026-10-23"


def test_agendamento_nao_cai_no_portal_da_generoso():
    with pytest.raises(NotImplementedError):
        FavoritaAdapter().agendar_coleta("123", None)


@pytest.fixture
def page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_context(locale="pt-BR").new_page()
        pg.goto(FIXTURE.as_uri(), wait_until="load")
        yield pg
        browser.close()


@pytest.mark.parametrize("name", [
    "totalMerchandiseValue", "cubageValues.0.height", "cubageValues.0.width",
    "cubageValues.0.length", "cubageValues.0.weight",
    "cubageValues.0.quantity", "observation"])
def test_campos_da_carga_existem_no_dom_real(page, name):
    """Os mesmos seletores que GenerosoAdapter.cotar digita."""
    assert page.locator(f'input[name="{name}"]:visible').count() == 1


def test_cards_de_embalagem_existem_no_dom_real(page):
    for rotulo in EMBALAGENS:
        assert page.get_by_text(rotulo, exact=True).count() >= 1


def test_botao_proximo_existe_no_dom_real(page):
    assert page.get_by_role("button", name="Próximo").count() >= 1


def test_ligada_no_app():
    import web.app as app_web

    assert "favorita" in app_web.AUTOMATICAS
    assert app_web.FABRICAS["favorita"] is app_web._cotar_favorita
    assert app_web.NOMES["favorita"] == "Favorita Transportes"
    assert "favorita" in app_web.NOTAS
    assert "favorita" in app_web.AUTOMATICA_DESDE
    assert all("Generoso" not in f
               for _, f in app_web.MENSAGENS_DE_ERRO["favorita"])
