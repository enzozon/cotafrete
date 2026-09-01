"""A Della Volpe deixou de ser automática — e por quê.

Em 31/08/2026 eles puseram **Cloudflare Turnstile** no formulário público.
Não é o reCAPTCHA v3 invisível de antes: é uma caixa "Confirme que é humano".
Sem ela marcada, o Contact Form 7 recusa o envio como spam e **nenhum e-mail
é gerado** — as cotações #78 a #84 falharam todas assim.

Medido com um envio real autorizado pelo Enzo, em 31/08/2026: o token
`_wpcf7_turnstile_response` fica vazio antes do clique, continua vazio 30
segundos depois da recusa, e o segundo clique é recusado igual. O widget
escala para a caixa interativa. Não é espera que resolve.

Marcar essa caixa por código seria derrubar um controle que o dono do site
instalou de propósito. Então ela sai das automáticas e entra em "Precisa de
você", junto das que o vendedor aciona à mão — o mesmo padrão do WhatsApp: o
sistema prepara, a pessoa envia.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from web import app as app_web, transportadoras

CARGA = {"cep_origem": "29105770", "cep_destino": "01310100",
         "cidade_origem": "Vila Velha", "uf_origem": "ES",
         "cidade_destino": "São Paulo", "uf_destino": "SP",
         "peso_kg": "10", "quantidade": 2, "comprimento_cm": 30,
         "largura_cm": 40, "altura_cm": 50, "valor_nf": "1500",
         "material": "PLACA DE VIDEO", "tipo_frete": "cif",
         "cnpj_remetente": "05.954.058/0001-98",
         "nome_remetente": "VENTURA COMERCIO",
         "cnpj_destinatario": "60.042.686/0001-05",
         "nome_destinatario": "CLIENTE EXEMPLO"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(app_web, "banco", Banco(tmp_path / "t.db"))
    return app_web


@pytest.fixture
def cliente(app):
    c = TestClient(app.app)
    c.cookies.set(app_web.COOKIE, "enzo")
    return c


def _criar(app) -> int:
    return app.banco.salvar_cotacao("enzo", CARGA)


# ------------------------------------------------------ saiu das automáticas
def test_dellavolpe_saiu_das_automaticas():
    """Enquanto ela estivesse aqui, toda cotação gastaria uma vaga de
    navegador para terminar em "barrado como spam" — um cartão vermelho que
    ninguém consegue resolver."""
    assert "dellavolpe" not in app_web.AUTOMATICAS


def test_nao_sobrou_fabrica_tentando_enviar_sozinho():
    """Fábrica órfã não roda, mas fica de isca para quem reativar sem ler."""
    assert "dellavolpe" not in app_web.FABRICAS


# ------------------------------------------------- entrou em "Precisa de você"
def test_dellavolpe_esta_entre_as_que_o_vendedor_aciona():
    slugs = {t.slug for t in transportadoras.com_email()}

    assert "dellavolpe" in slugs


def test_o_endereco_e_o_que_esta_impresso_no_formulario_deles():
    """Não inventado: é o e-mail que aparece no rodapé do próprio formulário,
    e é para onde o formulário mandaria a cotação se funcionasse."""
    dv = transportadoras.por_slug_email("dellavolpe")

    assert dv is not None
    assert dv.email == "comercial@dellavolpe.com.br"


def test_ela_nao_aparece_na_lista_do_whatsapp():
    """Sem número não pode virar botão de WhatsApp — o cadastro já avisa que
    botão que não abre conversa é pior que transportadora nenhuma."""
    assert "dellavolpe" not in {t.slug for t in transportadoras.com_whatsapp()}


# ------------------------------------------------------------- a tela pronta
def test_a_pagina_traz_o_endereco_e_a_carga(app, cliente):
    cotacao_id = _criar(app)

    html = cliente.get(f"/email/{cotacao_id}/dellavolpe").text

    assert "comercial@dellavolpe.com.br" in html
    assert "PLACA DE VIDEO" in html          # o material
    assert "05.954.058/0001-98" in html      # o CNPJ do remetente


def test_o_texto_e_o_mesmo_do_whatsapp(app, cliente):
    """Um segundo texto seria mais um para divergir do primeiro."""
    cotacao_id = _criar(app)
    esperado = app_web.mensagem_whatsapp(
        app.banco.buscar_cotacao(cotacao_id, "enzo"))

    html = cliente.get(f"/email/{cotacao_id}/dellavolpe").text

    for linha in esperado.splitlines():
        if linha.strip():
            assert app_web.e(linha) in html, f"faltou no texto: {linha}"


def test_a_pagina_diz_que_quem_envia_e_o_vendedor(app, cliente):
    """A mesma honestidade do WhatsApp: depois que ele copia, o sistema não
    tem como saber se saiu — e a tela precisa DIZER isso, não presumir.

    A primeira versão deste teste proibia a palavra "enviada" na página. Era
    uma asserção preguiçosa: ela baniria justamente a frase que faz o ponto
    ("o contador diz abertas, e nunca enviadas"). O que importa não é a
    palavra ausente, é a promessa presente."""
    html = cliente.get(f"/email/{_criar(app)}/dellavolpe").text
    # Espaço normalizado: o HTML quebra a frase em duas linhas, e quebra de
    # linha em HTML não é significativa — assertar o texto cru amarraria o
    # teste à largura do código-fonte.
    corrido = " ".join(html.split())

    assert "abertas" in corrido
    assert "não tem como saber se a mensagem saiu" in corrido
    assert "enviada com sucesso" not in corrido.lower()


# -------------------------------------------------------------- quem entra
def test_sem_login_nao_abre(app):
    resposta = TestClient(app.app).get(f"/email/{_criar(app)}/dellavolpe",
                                       follow_redirects=False)

    assert resposta.status_code == 303


def test_cotacao_de_outro_usuario_nao_abre(app):
    """A mesma garantia da tela da cotação: o histórico é separado por
    vendedor, e esta rota não pode ser a porta dos fundos."""
    de_outro = app.banco.salvar_cotacao("outra_pessoa", CARGA)
    c = TestClient(app.app)
    c.cookies.set(app_web.COOKIE, "enzo")

    assert c.get(f"/email/{de_outro}/dellavolpe").status_code == 404


def test_transportadora_desconhecida_nao_abre(app, cliente):
    assert cliente.get(f"/email/{_criar(app)}/inventada").status_code == 404


# ---------------------------------------------------------- a documentação
def test_a_documentacao_parou_de_dizer_que_ela_cota_sozinha(cliente):
    """A ajuda dizia "a resposta costuma chegar em 2 a 5 minutos". Hoje nada
    é enviado sozinho: manter a frase mandaria o vendedor esperar um e-mail
    que nunca vem."""
    html = cliente.get("/documentacao").text

    assert "2 a 5 minutos" not in html


# ------------------------------------------- o painel "Escolher", no formulário
def test_a_dellavolpe_tem_caixa_no_painel_de_escolha(cliente):
    """O bug que o Enzo viu na tela em 31/08/2026: ela sumiu inteira.

    Sem caixa no painel, o formulário nunca a envia como escolhida. Aí
    `selecao.para_guardar` grava uma lista SEM ela — e como a lista não é
    NULL, `selecao.entra` responde False para sempre. Ela desaparecia do
    resultado sem nenhuma mensagem, que é o pior jeito de sumir."""
    html = cliente.get("/").text

    assert 'value="dellavolpe"' in html


def test_toda_transportadora_da_conta_tem_caixa_no_painel(cliente):
    """A generalização do bug acima, e a razão de este teste existir.

    O painel anuncia "todas as N transportadoras", com N vindo de
    TODAS_AS_SLUGS. Se alguém acrescentar uma transportadora numa lista e
    esquecer do painel, o número continua certo e a caixa não existe — e a
    transportadora some das cotações novas, calada."""
    html = cliente.get("/").text
    faltando = [s for s in app_web.TODAS_AS_SLUGS
                if f'value="{s}"' not in html]

    assert not faltando, f"sem caixa no painel Escolher: {faltando}"
