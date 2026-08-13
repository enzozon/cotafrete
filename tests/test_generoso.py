"""Camada pura do Generoso.

O formulário é em etapas e quase tudo do endereço vem do CNPJ, então o que
sobra para a camada pura é pequeno — mas é onde mora o erro caro: a máscara
do peso e o formato do valor da nota.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from carriers.generoso.adapter import (
    TIPO_PAGADOR_DESTINATARIO, GenerosoAdapter, ler_resultado,
)
from core.models import StatusCotacao, Volume
from tests.test_jadlog import montar


@pytest.fixture
def adapter():
    return GenerosoAdapter()


# --------------------------------------------------------- máscara do peso
@pytest.mark.parametrize("kg, digitado", [
    (Decimal(1), "1,00"),
    (Decimal(12), "12,00"),
    (Decimal("0.5"), "0,50"),
    (Decimal(25), "25,00"),
    (Decimal("1.5"), "1,50"),
])
def test_peso_vai_com_duas_casas(adapter, kg, digitado):
    """Máscara medida no site em 13/08/2026, de 2 casas e da direita para a
    esquerda — o Enzo já tinha avisado e o recon confirmou:

        type("1")    -> 0.01
        type("100")  -> 1.00
        type("1200") -> 12.00

    Mandar "1" cotaria 10 gramas. A forma com vírgula e 2 casas produz o
    mesmo resultado que a de dígitos e é legível no código."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(30),
                                 largura_cm=Decimal(30), altura_cm=Decimal(30),
                                 peso_kg=kg)])
    assert adapter.preparar_payload(req)["peso"] == digitado


def test_medida_vai_inteira_em_cm(adapter):
    """As medidas não têm máscara: vão como inteiro, em centímetros."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(80),
                                 largura_cm=Decimal(60), altura_cm=Decimal(50),
                                 peso_kg=Decimal(4))])
    p = adapter.preparar_payload(req)

    assert p["altura"] == "50"
    assert p["largura"] == "60"
    assert p["comprimento"] == "80"


def test_peso_e_de_um_volume_e_quantidade_vai_separada(adapter):
    """O site tem 'Peso unitário' e 'Quantidade' e calcula o total sozinho.
    Mandar o peso do lote no campo unitário multiplicaria a carga."""
    req = montar(volumes=[Volume(qtd=3, comprimento_cm=Decimal(30),
                                 largura_cm=Decimal(30), altura_cm=Decimal(30),
                                 peso_kg=Decimal(12))])
    p = adapter.preparar_payload(req)

    assert p["peso"] == "12,00"        # unitário, não 36
    assert p["quantidade"] == "3"


def test_valor_da_nota_em_formato_brasileiro(adapter):
    assert adapter.preparar_payload(montar())["valor_nf"] == "1500,00"


def test_documentos_vao_para_os_papeis_certos(adapter):
    """Três CNPJs, três papéis. Trocar remetente com destinatário inverteria
    a rota e o frete sairia de outra praça."""
    p = adapter.preparar_payload(montar())

    assert p["cnpj_remetente"] == "11.222.333/0001-81"
    assert p["cnpj_solicitante"] == "61.139.432/0001-72"   # o pagador
    assert p["tipo_pagador"] == TIPO_PAGADOR_DESTINATARIO


# ------------------------------------------------------ leitura do resultado
def test_confirmacao_do_site_e_reconhecida(adapter):
    """Tela final medida: 'Recebemos seu pedido de cotação. Entraremos em
    contato em breve!' — não há preço nenhum, igual à Della Volpe."""
    res = adapter.normalizar_resposta(
        "Resultado\nRecebemos seu pedido de cotação. "
        "Entraremos em contato em breve!\nNova cotação")

    assert res.status is StatusCotacao.AGUARDANDO_RETORNO
    assert res.valor_frete is None
    assert res.erro is None


def test_tela_sem_confirmacao_vira_erro(adapter):
    """Sem a frase, não houve envio. Dar aguardando_retorno aqui repetiria o
    erro da Della Volpe, onde cinco cotações 'enviadas' nunca saíram."""
    res = adapter.normalizar_resposta("Carga\nPróximo\nConfirmar e ver resultado")
    assert res.status is StatusCotacao.ERRO


@pytest.mark.parametrize("texto, esperado", [
    ("Recebemos seu pedido de cotação", True),
    ("RECEBEMOS SEU PEDIDO DE COTAÇÃO. Entraremos em contato", True),
    ("Entraremos em contato em breve!", True),
    ("Preencha os campos para receber sua cotação", False),
    ("", False),
])
def test_frases_de_confirmacao(texto, esperado):
    assert ler_resultado(texto) is esperado
