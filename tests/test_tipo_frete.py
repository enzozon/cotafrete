"""CIF ou FOB: uma escolha só, que atravessa o sistema inteiro.

Regra do Enzo (20/08/2026):

    CIF  -> quem paga e o REMETENTE
    FOB  -> quem paga e o DESTINATARIO

Nao existe mais "CNPJ de quem paga" digitado a parte. Ele passou a ser
DERIVADO da escolha, e por isso nao tem como discordar dela — que era
exatamente o que acontecia: o formulario mandava um CNPJ da Ventura como
pagador (CIF) enquanto a Camilo recebia tp_frete=2 (FOB), fixo.

Este arquivo e a prova de ponta a ponta: o mesmo pedido, nas duas escolhas,
chegando certo em cada transportadora e na mensagem do WhatsApp.
"""

from __future__ import annotations

from decimal import Decimal

from core.models import StatusCotacao, TipoFrete
from tests.test_jadlog import CNPJ_A, CNPJ_B, montar


# ------------------------------------------------------- o modelo central
def test_cif_faz_o_remetente_pagar():
    req = montar(tipo_frete=TipoFrete.CIF)

    assert req.pagador_frete.cnpj == req.remetente.cnpj


def test_fob_faz_o_destinatario_pagar():
    req = montar(tipo_frete=TipoFrete.FOB)

    assert req.pagador_frete.cnpj == req.destinatario.cnpj


def test_nao_da_para_contrabandear_um_pagador_por_fora():
    """A garantia de que os dois nunca mais discordam: passar pagador_frete
    na mao levanta erro, em vez de ser silenciosamente ignorado."""
    import pytest
    from core.models import Parte

    with pytest.raises(Exception):
        montar(pagador_frete=Parte(cnpj=CNPJ_A))


# ------------------------------------------------------------- transportadoras
def test_camilo_manda_1_no_cif_e_2_no_fob():
    """tp_frete do SSW: 1 = pago pelo remetente, 2 = pelo destinatario."""
    from carriers.camilo.adapter import CamiloAdapter
    a = CamiloAdapter()

    assert a.preparar_payload(montar(tipo_frete=TipoFrete.CIF))["tp_frete"] == "1"
    assert a.preparar_payload(montar(tipo_frete=TipoFrete.FOB))["tp_frete"] == "2"


def test_camilo_manda_o_cnpj_de_quem_realmente_paga():
    from carriers.camilo.adapter import CamiloAdapter
    from core.models import limpa_doc
    a = CamiloAdapter()

    assert a.preparar_payload(
        montar(tipo_frete=TipoFrete.CIF))["cgc_pag"] == limpa_doc(CNPJ_A)
    assert a.preparar_payload(
        montar(tipo_frete=TipoFrete.FOB))["cgc_pag"] == limpa_doc(CNPJ_B)


def test_translovato_marca_remetente_no_cif_e_destinatario_no_fob():
    """Radios medidos no recon: value=1 e o rotulo REMETENTE, value=2 e
    DESTINATARIO."""
    from carriers.translovato import mapping as t

    assert t.preparar_payload(
        montar(tipo_frete=TipoFrete.CIF))["value[payer_type]"] == "1"
    assert t.preparar_payload(
        montar(tipo_frete=TipoFrete.FOB))["value[payer_type]"] == "2"


def test_generoso_escolhe_a_opcao_do_select_conforme_a_escolha():
    from carriers.generoso.adapter import (
        TIPO_PAGADOR_DESTINATARIO, TIPO_PAGADOR_REMETENTE, GenerosoAdapter)
    a = GenerosoAdapter()

    assert a.preparar_payload(
        montar(tipo_frete=TipoFrete.CIF))["tipo_pagador"] == (
            TIPO_PAGADOR_REMETENTE)
    assert a.preparar_payload(
        montar(tipo_frete=TipoFrete.FOB))["tipo_pagador"] == (
            TIPO_PAGADOR_DESTINATARIO)


def test_jadlog_nao_muda_com_o_tipo_de_frete():
    """Decisao do Enzo: a Jadlog fica de fora da mudanca.

    E o que ja acontece por construcao — o adapter que roda em producao e o
    do PAINEL, e o payload dele nao tem CNPJ nenhum: so CEPs e medidas. A
    etiqueta e pre-paga, quem paga e sempre quem compra a etiqueta.

    Se este teste quebrar, alguem mexeu onde nao devia."""
    from carriers.jadlog.painel import JadlogPainelAdapter
    a = JadlogPainelAdapter()

    assert (a.preparar_payload(montar(tipo_frete=TipoFrete.CIF))
            == a.preparar_payload(montar(tipo_frete=TipoFrete.FOB)))


# ------------------------------------------ a Jadlog so faz frete CIF de verdade
def test_jadlog_recusa_fob_sem_abrir_navegador():
    """Decisao do Enzo (03/09/2026): a Jadlog cota FOB sem reclamar no site,
    mas na pratica ela nao coleta no fornecedor/cliente -- so entrega, saindo
    sempre da base da Ventura. Cotar FOB e regra comercial que ja se sabe de
    antemao, e barra ANTES do navegador abrir: e o adapter que roda em
    producao (JadlogPainelAdapter), com Playwright de verdade."""
    from carriers.jadlog.painel import JadlogPainelAdapter

    res = JadlogPainelAdapter().cotar(montar(tipo_frete=TipoFrete.FOB))

    assert res.status is StatusCotacao.RECUSADO
    assert res.erro is None, "recusa nao e erro; o cartao le isso"
    assert "CIF" in (res.motivo_recusa or "")
    assert "FOB" in (res.motivo_recusa or "")


def test_jadlog_continua_cotando_cif():
    """Guarda contra o conserto virar uma trava nova: CIF (o caso normal,
    carga saindo da Ventura) nao pode ganhar a recusa por engano."""
    from carriers.jadlog import mapping as m

    erros = m.bloqueantes(m.validar(montar(tipo_frete=TipoFrete.CIF)))

    assert not erros, f"CIF nao devia recusar: {erros}"


def test_jadlog_adapter_de_api_tambem_recusa_fob():
    """O outro adapter (API pura, sem navegador) compartilha o mesmo
    m.validar — a regra vale nos dois lugares, nao so no do painel."""
    from carriers.jadlog.adapter import JadlogAdapter

    res = JadlogAdapter(token="fake").cotar(montar(tipo_frete=TipoFrete.FOB))

    assert res.status is StatusCotacao.RECUSADO
    assert "CIF" in (res.motivo_recusa or "")


# ------------------------------------------------------------------ a tela
import pytest
from fastapi.testclient import TestClient

from core.banco import Banco

CARGA = {
    "cep_origem": "29010-000", "cep_destino": "01310-100",
    "cidade_origem": "Vitória", "uf_origem": "ES",
    "cidade_destino": "São Paulo", "uf_destino": "SP",
    # Decimal, e nao string: e assim que buscar_cotacao devolve.
    "peso_kg": Decimal("12"), "quantidade": 3,
    "comprimento_cm": 80, "largura_cm": 60, "altura_cm": 50,
    "valor_nf": Decimal("1500.00"), "material": "Bomba",
    "cnpj_remetente": "05.954.058/0001-98",
    "cnpj_destinatario": "60.042.686/0001-05",
    "nome_remetente": "VENTURA INF LTDA ME",
    "nome_destinatario": "HERCULES EQUIPAMENTOS",
    "email": "vendas@ventura.com.br",
}


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    return modulo


@pytest.fixture
def cliente(app_web):
    c = TestClient(app_web.app)
    c.cookies.set(app_web.COOKIE, "enzo")
    return c


def _sem_tags(html: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_formulario_troca_o_cnpj_do_pagador_pelo_botao(app_web, cliente):
    """O campo "CNPJ de quem paga" sai; entra a escolha do tipo de frete."""
    texto = _sem_tags(cliente.get("/").text)

    assert "Tipo de frete" in texto
    assert "CIF" in texto and "Remetente que paga" in texto
    assert "FOB" in texto and "Destinatário que paga" in texto
    assert "CNPJ de quem paga" not in texto


def test_mensagem_do_whatsapp_no_cif_cobra_do_remetente(app_web):
    carga = {**CARGA, "tipo_frete": "cif",
             "cnpj_pagador": CARGA["cnpj_remetente"],
             "nome_pagador": CARGA["nome_remetente"]}

    msg = app_web.mensagem_whatsapp(carga)

    assert "TIPO DE FRETE: CIF" in msg
    assert "REMETENTE" in msg.split("TIPO DE FRETE")[1]
    assert "VENTURA INF LTDA ME" in msg.split("TIPO DE FRETE")[1]
    assert "05.954.058/0001-98" in msg.split("TIPO DE FRETE")[1]


def test_mensagem_do_whatsapp_no_fob_cobra_do_destinatario(app_web):
    carga = {**CARGA, "tipo_frete": "fob",
             "cnpj_pagador": CARGA["cnpj_destinatario"],
             "nome_pagador": CARGA["nome_destinatario"]}

    msg = app_web.mensagem_whatsapp(carga)

    assert "TIPO DE FRETE: FOB" in msg
    depois = msg.split("TIPO DE FRETE")[1]
    assert "DESTINAT" in depois
    assert "HERCULES EQUIPAMENTOS" in depois
    assert "60.042.686/0001-05" in depois


def test_repetir_cotacao_lembra_o_tipo_de_frete(app_web, cliente):
    """Repetir uma cotação FOB que volta como CIF cobraria da empresa
    errada, e a diferença não aparece em nenhum lugar da tela."""
    cid = app_web.banco.salvar_cotacao("enzo", {**CARGA, "tipo_frete": "fob"})

    html = cliente.get(f"/?repetir={cid}").text

    assert 'value="fob" checked' in html or "fob\" checked" in html


# ------------------------------------------------ Generoso e o CNPJ da conta
def test_generoso_digita_o_destinatario_no_cif_e_o_remetente_no_fob():
    """O site trava a ponta da CONTA e deixa a outra editavel:

        CIF  a Ventura e a remetente    -> origem travada, digita o destino
        FOB  a Ventura e a destinataria -> destino travado, digita a origem

    Digitar na ponta travada nao adianta, e deixar a livre em branco faz a
    cotacao nao ter de onde ou para onde ir."""
    from carriers.generoso.adapter import pontas_a_digitar

    cif = pontas_a_digitar(montar(tipo_frete=TipoFrete.CIF))
    fob = pontas_a_digitar(montar(tipo_frete=TipoFrete.FOB))

    assert cif == (None, "45.723.174/0001-10")     # so o destino
    assert fob == ("11.222.333/0001-81", None)     # so a origem


def test_a_empresa_do_portal_sai_do_cnpj_do_formulario(app_web, cliente):
    """Substitui o aviso que morava aqui ate 25/08/2026.

    Ate aquele dia o cartao dizia "Cotada com o CNPJ 08.310.365/0001-24 — nao
    da para trocar", porque o robo nunca mexia no "Alterar empresa" do portal
    e toda cotacao saia com a empresa da conta. O aviso estava CERTO e era
    necessario: sem ele o vendedor passava a um cliente de uma empresa um
    preco cotado por outra.

    Agora o robo troca a empresa, entao o aviso virou mentira — e aviso falso
    e pior que nenhum, porque ensina a desconfiar de um numero que passou a
    estar certo. O que sobra para provar e a escolha em si.
    """
    from carriers.base import ResultadoCotacao
    from carriers.generoso.mapping import empresa_alvo
    from core.models import Parte, StatusCotacao

    # CIF: quem despacha e a UNIAO, que nao e a empresa da conta.
    req = montar(tipo_frete=TipoFrete.CIF,
                 remetente=Parte(cnpj="20.837.281/0001-49"),
                 destinatario=Parte(cnpj=CNPJ_B))
    assert empresa_alvo(req).cnpj == "20.837.281/0001-49"

    cid = app_web.banco.salvar_cotacao("enzo", {
        **CARGA, "tipo_frete": "cif",
        "cnpj_remetente": "20.837.281/0001-49"})
    app_web._rodar(cid, "generoso",
                   lambda _: ResultadoCotacao("generoso", StatusCotacao.COTADO,
                                              valor_frete=Decimal("421.94")),
                   None)

    texto = _sem_tags(cliente.get(f"/cotacao/{cid}").text)

    assert "não dá para trocar" not in texto
    assert "08.310.365/0001-24" not in texto
