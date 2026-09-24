"""Máscara do valor da nota fiscal no formulário de cotação.

Reclamação dos vendedores (24/09/2026): "1000" no campo não deixava claro se
era mil reais ou dez. Ao sair do campo ele vira "1.000,00". O teste digita
tecla a tecla num Chromium, como o vendedor, e confere o que ficou escrito —
e que o servidor lê o valor formatado como o número certo.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from tests.apoio import entrar
from web import app as app_web


@pytest.fixture(scope="module")
def navegador():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def pagina(monkeypatch, tmp_path, navegador):
    monkeypatch.setattr(app_web, "banco", Banco(tmp_path / "t.db"))
    cliente = entrar(TestClient(app_web.app), app_web)
    pg = navegador.new_page()
    pg.route("**/*", lambda r: r.abort())
    pg.set_content(cliente.get("/").text)
    yield pg
    pg.close()


def _digitar_e_sair(pg, texto):
    pg.click("#valor_nf")
    pg.keyboard.press("Control+A")
    pg.keyboard.press("Backspace")
    pg.keyboard.type(texto)
    pg.click("#material")                     # sai do campo
    return pg.input_value("#valor_nf")


@pytest.mark.parametrize("digitado, fica", [
    ("1000", "1.000,00"),
    ("32890", "32.890,00"),
    ("1234567", "1.234.567,00"),
    ("0,5", "0,50"),
    ("1234,5", "1.234,50"),
    ("1234,56", "1.234,56"),
    ("1.500", "1.500,00"),            # ponto de milhar, como o vendedor escreve
    ("1.500,75", "1.500,75"),
    ("12.5", "12,50"),                # ponto decimal (colado de planilha)
    ("R$ 2.000,00", "2.000,00"),
    ("99,999", "100,00"),             # arredonda os centavos
    ("", ""),
])
def test_ao_sair_do_campo_fica_claro_quanto_e(pagina, digitado, fica):
    assert _digitar_e_sair(pagina, digitado) == fica


def test_enquanto_digita_o_campo_e_do_usuario(pagina):
    pagina.click("#valor_nf")
    pagina.keyboard.type("1234")
    assert pagina.input_value("#valor_nf") == "1234"      # nada de 12,34 no meio


def test_da_para_trocar_tudo_e_mexer_nos_centavos(pagina):
    assert _digitar_e_sair(pagina, "1000") == "1.000,00"
    # ao voltar, o valor inteiro fica selecionado: digitar substitui tudo
    pagina.click("#valor_nf")
    assert pagina.evaluate("() => { const e = document.getElementById('valor_nf');"
                           " return [e.selectionStart, e.selectionEnd]; }") == [0, 8]
    pagina.keyboard.type("2500")
    pagina.click("#material")
    assert pagina.input_value("#valor_nf") == "2.500,00"
    # e editar só os centavos: fim do campo, apaga 2, digita
    pagina.click("#valor_nf")
    pagina.keyboard.press("End")
    pagina.keyboard.press("Backspace")
    pagina.keyboard.press("Backspace")
    pagina.keyboard.type("90")
    pagina.click("#material")
    assert pagina.input_value("#valor_nf") == "2.500,90"


def test_repetir_cotacao_chega_formatado(monkeypatch, tmp_path, navegador):
    monkeypatch.setattr(app_web, "banco", Banco(tmp_path / "t.db"))
    cliente = entrar(TestClient(app_web.app), app_web)
    from tests.test_web_cotacao import CARGA
    cid = app_web.banco.salvar_cotacao("enzo", {**CARGA, "valor_nf": "32890.00"})
    pg = navegador.new_page()
    pg.route("**/*", lambda r: r.abort())
    pg.set_content(cliente.get(f"/?repetir={cid}").text)
    assert pg.input_value("#valor_nf") == "32.890,00"
    pg.close()


def test_o_servidor_le_o_valor_formatado():
    for texto, valor in (("1.000,00", "1000.00"), ("32.890,00", "32890.00"),
                         ("1.234.567,89", "1234567.89")):
        assert app_web._num(texto) == Decimal(valor)


def test_enter_sem_sair_do_campo_tambem_formata(pagina):
    """Sem isto "1.500" + Enter chegava cru e o servidor lia 1,5."""
    pagina.evaluate("""() => document.querySelector('form[action="/cotar"]').addEventListener(
        'submit', ev => { window.__enviado = document.getElementById('valor_nf').value;
                          ev.preventDefault(); })""")
    pagina.evaluate("() => document.querySelectorAll('input[required]').forEach(i => i.required = false)")
    pagina.click("#valor_nf")
    pagina.keyboard.type("1.500")
    pagina.keyboard.press("Enter")
    pagina.wait_for_function("window.__enviado !== undefined")
    assert pagina.evaluate("window.__enviado") == "1.500,00"
