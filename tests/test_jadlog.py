"""Testes Jadlog. Os de mapeamento são puros; o de integração sobe o mock
localmente e faz HTTP de verdade — nada sai para a internet."""

from __future__ import annotations

import socket
import threading
import time
from decimal import Decimal

import pytest

from carriers.base import Severidade
from carriers.jadlog import mapping as j
from carriers.jadlog.adapter import JadlogAdapter, TokenAusente
from core.models import (
    TipoFrete,
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, StatusCotacao, Volume,
)

CNPJ_A = "11.222.333/0001-81"
CNPJ_B = "45.723.174/0001-10"
CNPJ_C = "61.139.432/0001-72"


def montar(*, cep_ori="29010000", cep_des="01310100", volumes=None, **over):
    base = dict(
        solicitante=Solicitante(nome="Enzo", email="e@ex.com", whatsapp="27999887766"),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf="ES", cidade="Vitória", cep=cep_ori),
        destino=Local(uf="SP", cidade="São Paulo", cep=cep_des),
        remetente=Parte(cnpj=CNPJ_A),
        destinatario=Parte(cnpj=CNPJ_B),
        tipo_frete=TipoFrete.CIF,
        volumes=volumes or [Volume(qtd=1, comprimento_cm=Decimal(40),
                                   largura_cm=Decimal(30), altura_cm=Decimal(20),
                                   peso_kg=Decimal(5))],
        mercadoria=Mercadoria(tipo_material="Eletrônicos"),
        nota_fiscal=NotaFiscal(valor_total=Decimal(1_500)),
    )
    base.update(over)
    return CotacaoRequest(**base)


# ------------------------------------------------------- regra do peso cubado
def test_peso_real_vence_quando_carga_e_densa():
    # 40x30x20 = 24.000 cm³ = 0,024 m³ -> cubado 7,2 kg vs real 5 kg
    req = montar()
    assert req.cubagem_m3 == Decimal("0.024")
    assert j.peso_para_api(req) == Decimal("7.200")  # cubado vence aqui


def test_peso_cubado_vence_em_carga_volumosa():
    """Regressão do erro silencioso: mandar peso real aqui subcota o frete."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(100),
                                 largura_cm=Decimal(100), altura_cm=Decimal(100),
                                 peso_kg=Decimal(3))])
    assert req.peso_total_kg == Decimal(3)
    assert j.peso_para_api(req) == Decimal(300)      # 1 m³ x 300
    assert j.preparar_payload(req)["frete"][0]["peso"] == 300.0


def test_peso_real_vence_em_carga_pesada_e_compacta():
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(30),
                                 largura_cm=Decimal(30), altura_cm=Decimal(30),
                                 peso_kg=Decimal(25))])
    assert j.peso_para_api(req) == Decimal(25)


# ----------------------------------------------------------------- validação
def test_cep_obrigatorio():
    req = montar(origem=Local(uf="ES", cidade="Vitória"))  # sem CEP
    erros = j.bloqueantes(j.validar(req))
    assert any(e.campo == "origem.cep" for e in erros)


def test_cep_com_mascara_e_aceito():
    req = montar(cep_ori="29.010-000")
    assert j.bloqueantes(j.validar(req)) == []
    assert j.preparar_payload(req)["frete"][0]["cepori"] == "29010000"


def test_carga_pesada_demais_para_jadlog():
    req = montar(volumes=[Volume(qtd=10, comprimento_cm=Decimal(50),
                                 largura_cm=Decimal(50), altura_cm=Decimal(50),
                                 peso_kg=Decimal(35))])
    erros = j.bloqueantes(j.validar(req))
    assert any(e.campo == "peso" for e in erros)


def test_caixa_acima_de_30kg_e_reprovada_antes_de_abrir_o_navegador():
    """Regressão da cotação #46 (24/08/2026).

    80 kg em 2 volumes PASSA no limite de franquia (120 kg) e a calculadora
    recusa assim mesmo: ela cota UM pacote por vez, recebe 40 kg, e o site
    bloqueia o botão com "Para caixas, o peso máximo permitido é 30kg".

    Sem esta validação a cotação abre o Chromium, preenche, clica num botão
    desabilitado e gasta os 45s inteiros do timeout para devolver
    `TimeoutError` — que ainda por cima tem cara de erro passageiro e seria
    repetido três vezes, com o mesmo resultado.
    """
    def com_peso(kg):
        return montar(volumes=[Volume(qtd=2, comprimento_cm=Decimal(40),
                                      largura_cm=Decimal(40),
                                      altura_cm=Decimal(80),
                                      peso_kg=Decimal(kg))])

    req = com_peso(40)
    assert req.peso_total_kg == Decimal(80)   # passa nos 120 kg da franquia
    assert any(e.campo == "peso" and "30" in e.mensagem
               for e in j.bloqueantes(j.validar(req)))

    # 30 kg cravados é o limite do site, não o primeiro valor recusado.
    assert j.bloqueantes(j.validar(com_peso(30))) == []


def _so_peso(kg, medida=Decimal(40)):
    return montar(volumes=[Volume(qtd=1, comprimento_cm=medida,
                                  largura_cm=medida, altura_cm=medida,
                                  peso_kg=Decimal(kg))])


# ------------------------- as três recusas do painel, com o texto do site
def test_valor_acima_da_cobertura_e_recusado():
    """Limite de cobertura da Jadlog. Acima disso ela não aceita a carga —
    e é melhor o vendedor ler isso na hora do que esperar o navegador."""
    caro = montar(nota_fiscal=NotaFiscal(valor_total=Decimal("30000.01")))

    assert any("Cobertura máxima de R$30.000 excedida." in e.mensagem
               for e in j.bloqueantes(j.validar(caro)))

    no_limite = montar(nota_fiscal=NotaFiscal(valor_total=Decimal(30_000)))
    assert j.bloqueantes(j.validar(no_limite)) == []


def test_caixa_acima_de_30kg_usa_o_texto_do_site():
    """A frase é a que a própria calculadora escreve ao lado do campo."""
    assert any("Para caixas, o peso máximo permitido é 30kg" in e.mensagem
               for e in j.bloqueantes(j.validar(_so_peso("30.5"))))

    assert j.bloqueantes(j.validar(_so_peso(30))) == []


def test_medida_acima_de_80cm_e_recusada():
    """Vale para as TRÊS medidas, uma de cada vez: 81 de altura reprova
    mesmo com largura e comprimento pequenos."""
    frase = "Aceitamos pacotes com até 80cm x 80cm x 80cm"
    for lado in ("comprimento_cm", "largura_cm", "altura_cm"):
        medidas = {"comprimento_cm": Decimal(40), "largura_cm": Decimal(40),
                   "altura_cm": Decimal(40), lado: Decimal(81)}
        grande = montar(volumes=[Volume(qtd=1, peso_kg=Decimal(5), **medidas)])

        assert any(frase in e.mensagem
                   for e in j.bloqueantes(j.validar(grande))), lado

    # 80 cravados é o limite, não o primeiro valor recusado.
    no_limite = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(80),
                                       largura_cm=Decimal(40),
                                       altura_cm=Decimal(40),
                                       peso_kg=Decimal(5))])
    assert j.bloqueantes(j.validar(no_limite)) == []


@pytest.mark.xfail(reason="DECIDIDO em 24/08/2026: o limite de 120 kg fica, "
                          "mesmo contradizendo o pacote de 80x80x80",
                   strict=True)
def test_caixa_de_80x80x80_deveria_passar():
    """A contradicao conhecida, registrada de proposito.

    O Enzo passou em 24/08/2026 a regra da Jadlog: "Aceitamos pacotes com
    ate 80cm x 80cm x 80cm". Mas uma caixa assim tem 0,512 m3, que a 300 de
    fator da 153,6 kg cubados — acima dos 120 kg de PESO_MAX_FRANQUIA_KG, e
    a validacao recusa. As duas regras nao podem estar certas ao mesmo
    tempo.

    A hipotese e que os 120 kg sejam do frete de FRANQUIA (o adapter de
    API, que manda a carga inteira) e nao do Jadlog Entregas (o painel, que
    cota um pacote por vez). NAO foi confirmado com a franquia.

    Decisao do Enzo no mesmo dia: manter os 120 kg valendo para os dois,
    "assim evita confusao". O preco disso e conhecido e aceito — a Jadlog
    recusa carga volumosa que talvez cotasse, como as tres caixas de
    80x60x50 da cotacao #51.

    Este teste fica como o registro dessa escolha. `strict=True` de
    proposito: se alguem mexer no limite, ele passa a dar erro de "xpass" e
    a decisao volta a ser discutida em vez de sumir sem ninguem notar.
    """
    caixa = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(80),
                                   largura_cm=Decimal(80),
                                   altura_cm=Decimal(80),
                                   peso_kg=Decimal(5))])

    assert j.bloqueantes(j.validar(caixa)) == []


def test_modalidades_batem_com_o_select_da_jadlog():
    """Códigos medidos no simulador público (simulacao.jad) em 12/08/2026.

    Os presumidos erravam 3 de 7: 6 é Doc (não 'corporate'), 12 é Cargo (não
    'standard'), 9 (.Com) faltava, e 14/'pickup' não existe — retirada em ponto
    é tpentrega='R', não uma modalidade."""
    assert j.MODALIDADES == {
        "expresso": 0, "package": 3, "rodoviario": 4,
        "economico": 5, "doc": 6, "com": 9, "cargo": 12,
    }


def test_limite_de_ponto_de_postagem_usa_tpentrega_nao_modalidade():
    """O aviso de peso PUDO dependia de modalidade=='pickup', que não existe.
    Quem define retirada em ponto é tpentrega."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(30),
                                 largura_cm=Decimal(30), altura_cm=Decimal(30),
                                 peso_kg=Decimal(50))])
    avisos = j.validar(req, tpentrega=j.TP_ENTREGA_REDE)
    assert any(e.campo == "peso" and e.severidade is Severidade.AVISO
               for e in avisos)
    assert not any(e.campo == "peso" and e.severidade is Severidade.AVISO
                   for e in j.validar(req, tpentrega=j.TP_ENTREGA_DOMICILIO))


def test_modalidade_invalida():
    assert any(e.campo == "modalidade"
               for e in j.bloqueantes(j.validar(montar(), modalidade="foguete")))


# -------------------------------------------------------------------- payload
def test_payload_usa_cnpj_do_pagador_como_tomador():
    p = j.preparar_payload(montar())["frete"][0]
    # O tomador e quem paga. Com CIF isso e o remetente.
    assert p["cnpj"] == "11222333000181"
    assert p["cepori"] == "29010000"
    assert p["cepdes"] == "01310100"
    assert p["vldeclarado"] == 1500.0
    assert p["tpentrega"] == "D"


def test_peso_e_valor_vao_quantizados_para_a_api():
    """FATOR_CUBAGEM fracionário (1000/6 = 166,666..., usado por parte do
    mercado) gera Decimal de 28 dígitos. Sem quantização explícita o float()
    manda para a API um número cuja última casa sai do binário, não da regra
    comercial — e é sobre esse número que a franquia fatura."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(33),
                                 largura_cm=Decimal(33), altura_cm=Decimal(33),
                                 peso_kg=Decimal(1))],
                 nota_fiscal=NotaFiscal(valor_total=Decimal("1234.565")))
    p = j.preparar_payload(req, fator=Decimal(1000) / Decimal(6))["frete"][0]

    assert p["peso"] == 5.99      # 0,035937 m³ x 166,666... = 5,9895 -> 5,990
    assert p["vldeclarado"] == 1234.57   # dinheiro: 2 casas, ROUND_HALF_UP


def test_payload_omite_conta_e_contrato_quando_nao_informados():
    p = j.preparar_payload(montar())["frete"][0]
    assert "conta" not in p and "contrato" not in p


# ------------------------------------------------------------------- resposta
def test_resposta_com_valor_vira_cotado():
    res = j.normalizar_resposta(
        {"frete": [{"vlfrete": 42.5, "vltotal": 47.6, "prazo": 5}]})
    assert res.status is StatusCotacao.COTADO
    assert res.valor_frete == Decimal("47.6")
    assert res.prazo_dias == 5


def test_resposta_com_erro_vira_recusado():
    res = j.normalizar_resposta(
        {"frete": [{"erro": {"id": "1", "descricao": "CEP inválido"}}]})
    assert res.status is StatusCotacao.RECUSADO
    assert "CEP inválido" in res.erro


def test_resposta_vazia_vira_erro():
    assert j.normalizar_resposta({"frete": []}).status is StatusCotacao.ERRO


def test_frete_zero_e_resposta_legitima_nao_erro():
    """_num() trata 0 como ausente. Frete grátis (promoção, rota bonificada,
    contrato com franquia de valor) vira 'Resposta sem valor de frete' e a
    cotação some do comparativo — o cliente perde a opção mais barata."""
    res = j.normalizar_resposta({"frete": [{"vltotal": 0, "vlfrete": 0, "prazo": 3}]})
    assert res.status is StatusCotacao.COTADO
    assert res.valor_frete == Decimal(0)
    assert res.prazo_dias == 3


def test_vltotal_zero_nao_cai_para_vlfrete():
    """O encadeamento `_num(vltotal) or _num(vlfrete)` também erra: com vltotal
    legítimo igual a 0, o `or` escorrega para vlfrete e reporta outro número."""
    res = j.normalizar_resposta({"frete": [{"vltotal": 0, "vlfrete": 71.4}]})
    assert res.valor_frete == Decimal(0)


def test_prazo_zero_e_mesmo_dia_nao_ausente():
    """prazo=0 é entrega no mesmo dia, não 'sem prazo'."""
    res = j.normalizar_resposta({"frete": [{"vltotal": 50.0, "prazo": 0}]})
    assert res.prazo_dias == 0


def test_sem_token_levanta_erro_claro():
    with pytest.raises(TokenAusente):
        JadlogAdapter(token=None).cotar(montar())


# ------------------------------------------------- integração HTTP com o mock
def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mock_url():
    import uvicorn
    from mock.jadlog_server import app

    porta = _porta_livre()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="error")
    servidor = uvicorn.Server(cfg)
    t = threading.Thread(target=servidor.run, daemon=True)
    t.start()
    for _ in range(80):
        if servidor.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{porta}/embarcador/api/frete/valor"
    servidor.should_exit = True
    t.join(timeout=5)


def test_e2e_cotacao_com_sucesso(mock_url):
    adapter = JadlogAdapter(token="TOKEN-DE-TESTE", base_url=mock_url)
    res = adapter.cotar(montar())
    assert res.status is StatusCotacao.COTADO
    assert res.valor_frete and res.valor_frete > 0
    assert res.prazo_dias == 5
    assert res.enviado_em and res.respondido_em


def test_e2e_token_errado(mock_url):
    res = JadlogAdapter(token="LIXO", base_url=mock_url).cotar(montar())
    assert res.status is StatusCotacao.ERRO
    assert "401" in res.erro


def test_e2e_peso_cubado_chega_na_api(mock_url):
    """Ponta a ponta: carga leve e volumosa precisa chegar cubada."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(80),
                                 largura_cm=Decimal(60), altura_cm=Decimal(50),
                                 peso_kg=Decimal(4))])
    adapter = JadlogAdapter(token="TOKEN-DE-TESTE", base_url=mock_url)
    res = adapter.cotar(req)
    assert res.status is StatusCotacao.COTADO

    import httpx
    base = mock_url.rsplit("/embarcador", 1)[0]
    recebido = httpx.get(f"{base}/ultimo-payload").json()
    assert recebido["frete"][0]["peso"] == 72.0   # 0,24 m³ x 300, não 4 kg
