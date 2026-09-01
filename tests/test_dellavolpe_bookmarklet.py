"""O bookmarklet da Della Volpe: preenche o formulário OFICIAL deles no
navegador de verdade do vendedor, sem Playwright e sem CDP no meio.

Existe porque pelo formulário oficial a resposta chega em 2 a 5 minutos —
contra 10 a 12 horas do e-mail avulso (`/email/{id}/dellavolpe`). O Turnstile
("confirme que é humano") continua ativo e continua exigindo humano de
verdade: isto aqui só poupa a digitação, quem resolve o captcha e clica em
enviar é sempre a pessoa. Ver carriers/dellavolpe/bookmarklet.py para o
porquê completo.

Duas camadas testadas separadamente:
1. `campos_por_name`/`url_formulario` — puro Python, sem browser.
2. `SCRIPT_JS` contra um fixture DOM (tests/fixtures/dellavolpe_formulario.html)
   que simula o AJAX estado->cidade do site real — a mesma corrida que
   carriers/dellavolpe/adapter.py::_esperar_opcoes resolve do lado Playwright.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from carriers.dellavolpe import bookmarklet as dv
from core.banco import Banco

FIXTURE = (Path(__file__).parent / "fixtures" / "dellavolpe_formulario.html").resolve()

# Uma cotação completa, com os dois campos novos (nome_solicitante,
# whatsapp_solicitante) que este bookmarklet foi o motivo de existirem.
COTACAO = {
    "cidade_origem": "Vila Velha", "uf_origem": "ES",
    "cep_origem": "29102-030", "cep_destino": "01310-100",
    "cidade_destino": "São Paulo", "uf_destino": "SP",
    "peso_kg": "12.5", "quantidade": 3,
    "comprimento_cm": "80", "largura_cm": "60", "altura_cm": "50",
    "valor_nf": "1500.00", "material": "Bomba d'água",
    "cnpj_remetente": "12.345.678/0001-90",
    "cnpj_destinatario": "98.765.432/0001-10",
    "cnpj_pagador": "12.345.678/0001-90",
    "email": "vendas@ventura.com.br",
    "nome_solicitante": "Enzo Zon",
    "whatsapp_solicitante": "(27) 99988-7766",
}


# --------------------------------------------------------- campos_por_name
def test_campos_por_name_usa_os_atributos_reais_do_site():
    campos = dv.campos_por_name(COTACAO)

    assert campos["nome"] == "Enzo Zon"
    assert campos["email"] == "vendas@ventura.com.br"
    assert campos["whatsapp"] == "(27) 99988-7766"
    assert campos["estado_origem"] == "ES"
    assert campos["cidade_origem"] == "Vila Velha"
    assert campos["cnpj_origem"] == "12.345.678/0001-90"
    assert campos["cnpj"] == "12.345.678/0001-90"
    assert campos["servico"] == "Fracionado -LTL"


def test_campos_por_name_formata_numeros_como_o_site_exige():
    campos = dv.campos_por_name(COTACAO)

    # Peso arredondado pra cima e sem vírgula: 12,5 -> 13. O campo da Della
    # Volpe concatena os dígitos em vez de recusar decimal — ver mapping.py.
    assert campos["peso"] == "13"
    assert campos["comprimento"] == "80,0"   # uma casa decimal, é o que a
    assert campos["largura"] == "60,0"       # máscara do site reserva —
    assert campos["altura"] == "50,0"        # ver medida_br em mapping.py
    assert campos["valor"] == "1.500,00"


def test_campo_vazio_ou_ausente_nao_entra_no_resultado():
    """Cotação sem nome/whatsapp guardado (anterior a esta mudança). O
    bookmarklet tem que deixar o campo do site como está, não sobrescrever
    com string vazia."""
    sem_solicitante = {k: v for k, v in COTACAO.items()
                       if k not in ("nome_solicitante", "whatsapp_solicitante")}

    campos = dv.campos_por_name(sem_solicitante)

    assert "nome" not in campos
    assert "whatsapp" not in campos
    assert campos["email"] == "vendas@ventura.com.br"  # o resto continua


def test_sem_medidas_numericas_nao_quebra():
    """Peso/medida corrompido no banco não pode derrubar a tela inteira —
    só aquele campo fica de fora, como se não tivesse valor nenhum."""
    quebrado = {**COTACAO, "peso_kg": "não é número"}

    campos = dv.campos_por_name(quebrado)

    assert "peso" not in campos
    assert campos["email"] == "vendas@ventura.com.br"


def test_anexo_nao_faz_parte_do_resultado():
    """input[type=file] não aceita valor por JavaScript — nem tenta."""
    campos = dv.campos_por_name(COTACAO)

    assert "anexo-vol" not in campos
    assert "anexo-fispq" not in campos


# ------------------------------------------------------------ url_formulario
def test_url_formulario_aponta_para_o_site_real():
    url = dv.url_formulario(COTACAO)

    assert url.startswith("https://dellavolpe.com.br/?cf=")
    assert url.endswith("#cotacao")


def test_url_formulario_carrega_exatamente_os_campos_de_campos_por_name():
    """O parâmetro `cf` é a única ponte entre o Cotafrete e a aba da Della
    Volpe — sem fetch, sem CORS (ver o docstring do módulo). Se o que vai no
    parâmetro divergir de campos_por_name, o bookmarklet preenche errado
    sem ninguém perceber, porque não existe teste de integração possível
    contra o site real."""
    url = dv.url_formulario(COTACAO)
    query = parse_qs(urlparse(url).query)
    decodificado = json.loads(base64.b64decode(query["cf"][0]))

    assert decodificado == dv.campos_por_name(COTACAO)


# --------------------------------------------------------- href_bookmarklet
def test_href_bookmarklet_e_uma_url_javascript():
    href = dv.href_bookmarklet()

    assert href.startswith("javascript:")
    assert "URLSearchParams" in href  # confirma que é o SCRIPT_JS mesmo,
    assert "atob" in href             # não um placeholder vazio


# ------------------------------------------------------------------- rota
@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    monkeypatch.setattr(modulo, "TENTATIVAS_EM_CURSO", {})
    return modulo


@pytest.fixture
def cliente(app_web):
    c = TestClient(app_web.app)
    c.cookies.set(app_web.COOKIE, "enzo")
    return c


def test_rota_exige_login(app_web):
    sem_login = TestClient(app_web.app)

    resposta = sem_login.get("/dellavolpe/1", follow_redirects=False)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/login"


def test_rota_nao_vaza_cotacao_de_outro_usuario(app_web, cliente):
    cotacao_id = app_web.banco.salvar_cotacao("outra_pessoa", COTACAO)

    resposta = cliente.get(f"/dellavolpe/{cotacao_id}")

    assert resposta.status_code == 404


def test_rota_traz_o_link_do_formulario_e_do_favorito(app_web, cliente):
    cotacao_id = app_web.banco.salvar_cotacao("enzo", COTACAO)

    resposta = cliente.get(f"/dellavolpe/{cotacao_id}")
    texto = resposta.text

    assert resposta.status_code == 200
    assert "https://dellavolpe.com.br/?cf=" in texto
    assert "javascript:" in texto
    assert "2 a 5" in texto  # a promessa que justifica a tela existir


def test_rota_ainda_oferece_o_email_como_alternativa(app_web, cliente):
    """Quem não instalou o favorito ainda não pode ficar sem opção nenhuma."""
    cotacao_id = app_web.banco.salvar_cotacao("enzo", COTACAO)

    resposta = cliente.get(f"/dellavolpe/{cotacao_id}")

    assert f"/email/{cotacao_id}/dellavolpe" in resposta.text


def test_abrir_a_tela_marca_como_aberta(app_web, cliente):
    """Mesma tabela do WhatsApp/e-mail — o contador da cotação usa isto."""
    cotacao_id = app_web.banco.salvar_cotacao("enzo", COTACAO)

    cliente.get(f"/dellavolpe/{cotacao_id}")

    assert "dellavolpe" in app_web.banco.whatsapp_abertos(cotacao_id)


def test_o_card_da_cotacao_usa_a_rota_rapida_como_padrao(app_web, cliente):
    """O card de "Precisa de você" tem que apontar para o formulário rápido,
    não para o e-mail de 10 a 12 horas — senão a via rápida existe mas
    ninguém a encontra."""
    cotacao_id = app_web.banco.salvar_cotacao("enzo", COTACAO)

    resposta = cliente.get(f"/cotacao/{cotacao_id}")
    texto = resposta.text

    assert f'href="/dellavolpe/{cotacao_id}"' in texto
    assert "Preencher formulário" in texto


# --------------------------------------------------- o script, contra o DOM
@pytest.fixture
def page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_context(locale="pt-BR").new_page()
        pg.set_default_timeout(6_000)
        pg.on("dialog", lambda d: d.accept())  # o script termina com alert()
        yield pg
        browser.close()


def _abrir_com_dados(page, campos: dict[str, str]) -> None:
    b64 = base64.b64encode(
        json.dumps(campos, ensure_ascii=False).encode("utf-8")).decode("ascii")
    page.goto(f"{FIXTURE.as_uri()}?cf={b64}", wait_until="load")


CAMPOS_COMPLETOS = dv.campos_por_name(COTACAO)


def test_preenche_os_campos_de_texto(page):
    _abrir_com_dados(page, CAMPOS_COMPLETOS)

    page.evaluate(dv.SCRIPT_JS)
    page.wait_for_timeout(3_000)

    assert page.locator('[name="nome"]').input_value() == "Enzo Zon"
    assert page.locator('[name="email"]').input_value() == "vendas@ventura.com.br"
    assert page.locator('[name="peso"]').input_value() == "13"
    assert page.locator('[name="valor"]').input_value() == "1.500,00"


def test_seleciona_o_servico_por_texto(page):
    _abrir_com_dados(page, CAMPOS_COMPLETOS)

    page.evaluate(dv.SCRIPT_JS)
    page.wait_for_timeout(3_000)

    assert page.locator('[name="servico"]').input_value() == "Fracionado -LTL"


def test_espera_o_ajax_de_cidade_antes_de_selecionar(page):
    """A corrida real: o select de cidade fica vazio ("Carregando...") por
    250ms depois do estado mudar. Sem esperar, a cidade nunca é selecionada
    — foi exatamente o bug que _esperar_opcoes existe para evitar do lado
    Playwright (ver carriers/dellavolpe/adapter.py)."""
    _abrir_com_dados(page, CAMPOS_COMPLETOS)

    page.evaluate(dv.SCRIPT_JS)
    page.wait_for_timeout(3_000)

    assert page.locator('[name="estado_origem"]').input_value() == "ES"
    assert page.locator('[name="cidade_origem"]').input_value() == "Vila Velha"
    assert page.locator('[name="estado_destino"]').input_value() == "SP"
    assert page.locator('[name="cidade_destino"]').input_value() == "São Paulo"


def test_sem_parametro_cf_avisa_e_nao_mexe_em_nada(page):
    """Aba errada — o vendedor clicou no favorito numa aba antiga da Della
    Volpe, sem ter passado pelo nosso link primeiro."""
    page.goto(FIXTURE.as_uri(), wait_until="load")

    page.evaluate(dv.SCRIPT_JS)
    page.wait_for_timeout(500)

    assert page.locator('[name="nome"]').input_value() == ""


def test_dado_corrompido_nao_quebra_a_pagina(page):
    """`cf` presente mas ilegível não pode travar a aba do vendedor."""
    page.goto(f"{FIXTURE.as_uri()}?cf=isso-nao-e-base64-valido", wait_until="load")

    page.evaluate(dv.SCRIPT_JS)  # não pode levantar
    page.wait_for_timeout(500)

    assert page.locator('[name="nome"]').input_value() == ""
