"""Testes Jadlog. Os de mapeamento são puros; o de integração sobe o mock
localmente e faz HTTP de verdade — nada sai para a internet."""

from __future__ import annotations

import socket
import threading
import time
from decimal import Decimal

import pytest

from carriers.jadlog import mapping as j
from carriers.jadlog.adapter import JadlogAdapter, TokenAusente
from core.models import (
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
        pagador_frete=Parte(cnpj=CNPJ_C),
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


def test_modalidade_invalida():
    assert any(e.campo == "modalidade"
               for e in j.bloqueantes(j.validar(montar(), modalidade="foguete")))


# -------------------------------------------------------------------- payload
def test_payload_usa_cnpj_do_pagador_como_tomador():
    p = j.preparar_payload(montar())["frete"][0]
    assert p["cnpj"] == "61139432000172"     # pagador, não remetente
    assert p["cepori"] == "29010000"
    assert p["cepdes"] == "01310100"
    assert p["vldeclarado"] == 1500.0
    assert p["tpentrega"] == "D"


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
