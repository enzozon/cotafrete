"""Colar o pedido e preencher a cotação (core/extrair_carga + POST /extrair).

A IA é o provedor falso de tests/test_ia.py: ele devolve o JSON que o teste
mandar, como um modelo devolveria. O que se testa é o que vem DEPOIS — a
camada de código que decide o que chega à tela — e a tela preenchendo o
formulário de verdade num Chromium.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core import extrair_carga as ex
from core import ia
from core.banco import Banco
from tests.apoio import entrar
from tests.test_ia import Provedor, Resp
from web import app as app_web

VAZIO = {k: None for k in ex.ESQUEMA["required"]} | {"observacoes": []}
PEDIDO = """Bom dia Enzo, segue pedido 4471.
Entregar na Samarco - Rodovia do Sol s/n, Ubu, Anchieta/ES CEP 29230-000
CNPJ 33.000.167/0001-01. Frete FOB.
São 3 caixas de 60x40x30 cm, 45 kg no total. Valor da NF R$ 12.345,60.
Material: notebooks Dell."""


def _resposta(**campos) -> dict:
    return VAZIO | campos


# --------------------------------------------------- a camada que manda
def test_pedido_tipico_vira_campos_do_formulario():
    x = ex.limpar(_resposta(
        cep_destino="29230-000", cnpj_destinatario="33.000.167/0001-01", tipo_frete="fob",
        quantidade_volumes=3, peso_total_kg=45, comprimento_cm=60, largura_cm=40,
        altura_cm=30, valor_nf_reais=12345.6, material="notebooks Dell"))
    assert x.campos == {
        "cep_destino": "29230-000", "cnpj_destinatario": "33.000.167/0001-01",
        "tipo_frete": "fob", "quantidade": "3", "peso": "15", "comprimento": "60",
        "largura": "40", "altura": "30", "valor_nf": "12345,6", "material": "notebooks Dell"}
    # o formulário pede o peso de UM volume: a conta é dita, não escondida
    assert any("45 kg ÷ 3 volumes = 15 kg" in a for a in x.avisos)
    assert x.faltando == ["CEP de origem", "CNPJ do remetente"]


def test_cnpj_inventado_nao_passa_do_digito_verificador():
    x = ex.limpar(_resposta(cnpj_remetente="12.345.678/0001-00", cnpj_destinatario="11222333000181"))
    assert "cnpj_remetente" not in x.campos
    assert x.campos["cnpj_destinatario"] == "11.222.333/0001-81"
    assert any("CNPJ do remetente" in a and "não é um CNPJ válido" in a for a in x.avisos)


def test_cep_incompleto_vira_aviso():
    x = ex.limpar(_resposta(cep_origem="29100", cep_destino="01310100"))
    assert x.campos == {"cep_destino": "01310-100"}
    assert any("CEP de origem" in a and "8 dígitos" in a for a in x.avisos)


def test_peso_por_volume_que_nao_bate_com_o_total():
    x = ex.limpar(_resposta(quantidade_volumes=2, peso_por_volume_kg=10, peso_total_kg=35))
    assert x.campos["peso"] == "10"
    assert any("2 × 10 kg = 20 kg" in a and "35 kg" in a for a in x.avisos)


def test_peso_total_sem_quantidade_nao_chuta():
    x = ex.limpar(_resposta(peso_total_kg=80))
    assert "peso" not in x.campos
    assert any("peso total (80 kg)" in a for a in x.avisos)


def test_numeros_em_texto_e_decimais_brasileiros():
    x = ex.limpar(_resposta(quantidade_volumes="2", peso_por_volume_kg="12,5",
                            comprimento_cm="120.0", largura_cm=0.5, altura_cm=-3,
                            valor_nf_reais="R$ 1.234,56"))
    assert x.campos["quantidade"] == "2" and x.campos["peso"] == "12,5"
    assert x.campos["comprimento"] == "120" and x.campos["largura"] == "0,5"
    assert "altura" not in x.campos and x.campos["valor_nf"] == "1234,56"


def test_quantidade_quebrada_e_tipo_inventado_ficam_de_fora():
    x = ex.limpar(_resposta(quantidade_volumes=2.5, tipo_frete="a combinar"))
    assert "quantidade" not in x.campos and "tipo_frete" not in x.campos
    assert any("Quantidade de volumes estranha" in a for a in x.avisos)


def test_observacoes_da_ia_viram_avisos():
    x = ex.limpar(_resposta(observacoes=["Há 2 tamanhos de caixa: 60x40x30 e 30x30x30.", "  "]))
    assert x.avisos == ["Há 2 tamanhos de caixa: 60x40x30 e 30x30x30."]


def test_contato_nunca_e_preenchido():
    """Nome, e-mail e WhatsApp são do VENDEDOR, não do cliente do texto."""
    assert not {"nome", "email", "whatsapp"} & set(ex.ESQUEMA["properties"])


def test_esquema_vale_no_modo_estrito():
    e = ex.ESQUEMA
    assert e["additionalProperties"] is False and set(e["required"]) == set(e["properties"])


# ---------------------------------------------------- pela cadeia de IA
@pytest.fixture
def prov(monkeypatch):
    p = Provedor()
    monkeypatch.setattr(ia, "POST", p)
    monkeypatch.setattr(ia, "_castigo", {})
    monkeypatch.setattr(ia, "REGISTRO", None)
    monkeypatch.setenv("IA_MODELOS", "groq:melhor,openrouter:reserva:free")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "y")
    return p


def test_extrair_manda_o_texto_e_limpa_a_resposta(prov):
    prov.roteiro["melhor"] = [Resp(conteudo=json.dumps(_resposta(cep_destino="29230000", quantidade_volumes=3)))]
    x = ex.extrair(PEDIDO)
    assert x.modelo == "groq:melhor" and x.campos == {"cep_destino": "29230-000", "quantidade": "3"}
    ((_, _, corpo),) = prov.pedidos
    assert "Samarco" in corpo["messages"][1]["content"] and corpo["messages"][0]["content"].startswith(ex.SISTEMA)


def test_resposta_sem_nenhum_campo_passa_para_o_proximo_modelo(prov):
    prov.roteiro["melhor"] = [Resp(conteudo='{"pedido": "ok"}')]
    prov.roteiro["reserva:free"] = [Resp(conteudo=json.dumps({"cep_destino": "01310-100"}))]
    x = ex.extrair(PEDIDO)   # o 2º omitiu os nulos: vale como nulo
    assert x.modelo == "openrouter:reserva:free" and x.campos == {"cep_destino": "01310-100"}


@pytest.mark.parametrize("texto, trecho", [("", "Cole o texto"), ("x" * 9000, "grande demais")])
def test_texto_vazio_ou_enorme_nem_vai_para_a_ia(prov, texto, trecho):
    with pytest.raises(ex.TextoInvalido, match=trecho):
        ex.extrair(texto)
    assert prov.pedidos == []


# ----------------------------------------------------------- rota e tela
@pytest.fixture
def cliente(monkeypatch, tmp_path, prov):
    monkeypatch.setattr(app_web, "banco", Banco(tmp_path / "t.db"))
    return entrar(TestClient(app_web.app), app_web)


def test_rota_devolve_campos_avisos_e_rotulos(cliente, prov):
    prov.roteiro["melhor"] = [Resp(conteudo=json.dumps(_resposta(
        cep_destino="29230-000", quantidade_volumes=3, peso_total_kg=45)))]
    d = cliente.post("/extrair", json={"texto": PEDIDO}).json()
    assert d["campos"] == {"cep_destino": "29230-000", "quantidade": "3", "peso": "15"}
    assert d["modelo"] == "groq:melhor" and d["rotulos"]["peso"] == "Peso de UM volume"
    assert "CEP de origem" in d["faltando"]


def test_rota_com_ia_fora_do_ar_da_mensagem_e_nao_quebra(cliente, prov):
    prov.roteiro["melhor"] = prov.roteiro["reserva:free"] = [Resp(503)]
    d = cliente.post("/extrair", json={"texto": PEDIDO}).json()
    assert "indisponível" in d["erro"] and "Preencha à mão" in d["erro"]


def test_rota_precisa_de_login(monkeypatch, tmp_path, prov):
    monkeypatch.setattr(app_web, "banco", Banco(tmp_path / "t.db"))
    r = TestClient(app_web.app).post("/extrair", json={"texto": PEDIDO})
    assert r.status_code == 401 and prov.pedidos == []


def test_caixa_so_aparece_com_a_ia_configurada(cliente, monkeypatch):
    assert 'id="ia-texto"' in cliente.get("/").text
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert 'id="ia-texto"' not in cliente.get("/").text


def test_a_tela_preenche_o_formulario_de_verdade(cliente, prov):
    """Chromium: cola, clica, e os inputs recebem os valores — com as máscaras
    de CEP/CNPJ aplicadas, o FOB marcado e o aviso na tela. Nada é cotado."""
    sync = pytest.importorskip("playwright.sync_api")
    prov.roteiro["melhor"] = [Resp(conteudo=json.dumps(_resposta(
        cep_destino="29230000", cnpj_destinatario="33000167000101", tipo_frete="fob",
        quantidade_volumes=3, peso_total_kg=45, comprimento_cm=60, largura_cm=40, altura_cm=30,
        valor_nf_reais=12345.6, material="notebooks Dell")))]
    html = cliente.get("/").text
    cotou = []

    def servir(route, request):
        if request.url.endswith("/extrair"):
            r = cliente.post("/extrair", content=request.post_data,
                             headers={"Content-Type": "application/json"})
            return route.fulfill(status=r.status_code, body=r.content, content_type="application/json")
        if "/cotar" in request.url:
            cotou.append(request.url)
        if request.url.rstrip("/") == "http://cotafrete.teste":
            return route.fulfill(status=200, body=html, content_type="text/html; charset=utf-8")
        return route.abort()

    with sync.sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.route("**/*", servir)
        pg.goto("http://cotafrete.teste/")
        pg.fill("#ia-texto", PEDIDO)
        pg.click("#ia-preencher")
        pg.wait_for_function("document.getElementById('ia-status').textContent.includes('campos')")
        v = pg.evaluate("""() => Object.fromEntries(['cep_destino','cnpj_destinatario','quantidade',
            'peso','comprimento','largura','altura','valor_nf','material','cep_origem']
            .map(id => [id, document.getElementById(id).value]))""")
        fob = pg.is_checked('input[name="tipo_frete"][value="fob"]')
        destaque = pg.evaluate("() => document.querySelectorAll('input.ia-preenchido').length")
        aviso = pg.inner_text("#ia-resultado")
        b.close()
    assert v == {"cep_destino": "29230-000", "cnpj_destinatario": "33.000.167/0001-01",
                 "quantidade": "3", "peso": "15", "comprimento": "60", "largura": "40",
                 "altura": "30", "valor_nf": "12.345,60", "material": "notebooks Dell",
                 "cep_origem": ""}
    assert fob and destaque == 9
    assert "45 kg ÷ 3 volumes = 15 kg" in aviso and "CEP de origem" in aviso
    assert cotou == []   # preencher nunca cota
