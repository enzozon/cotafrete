"""Camada pura do adapter do simulador público da Jadlog.

A mecânica de browser (JSF apagando campo, painel trocado no partial update) foi
verificada contra o site real; aqui ficam as regras que dá para travar offline.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from carriers.jadlog.simulador import JadlogSimuladorAdapter, _num_br_para_decimal
from core.models import StatusCotacao, Volume
from tests.test_jadlog import montar


@pytest.fixture
def adapter():
    return JadlogSimuladorAdapter(modalidade="expresso")


# ------------------------------------------------- peso REAL, não cubado
def test_simulador_manda_peso_real_nao_cubado(adapter):
    """Diferença crítica para o adapter da API REST.

    A API não recebe medidas, então o peso precisa ir já cubado. O simulador
    RECEBE largura/altura/comprimento e cuba por conta própria — mandar o peso
    cubado junto contaria cubagem duas vezes e inflaria o frete."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(80),
                                 largura_cm=Decimal(60), altura_cm=Decimal(50),
                                 peso_kg=Decimal(4))])
    p = adapter.preparar_payload(req)

    assert p["peso"] == "4"          # real; o cubado seria 72
    assert p["valComprimento"] == "80"
    assert p["valLargura"] == "60"
    assert p["valAltura"] == "50"


def test_cep_vai_sem_mascara(adapter):
    p = adapter.preparar_payload(montar(cep_ori="29.010-000"))
    assert p["origem"] == "29010000"
    assert p["destino"] == "01310100"


def test_valor_da_mercadoria_em_formato_brasileiro(adapter):
    p = adapter.preparar_payload(montar())
    assert p["valor_mercadoria"] == "1500,00"


# ------------------------------------------------------ leitura do resultado
@pytest.mark.parametrize("texto, esperado", [
    ("Resultado\nR$ 118.09\nDica", Decimal("118.09")),
    ("Resultado\nR$ 61,27\nDica", Decimal("61.27")),
    ("Resultado\nR$ 1.234,56\nDica", Decimal("1234.56")),
])
def test_le_valor_nos_dois_formatos_de_numero(adapter, texto, esperado):
    """O painel alterna entre '118.09' e '61,27' conforme a rota."""
    res = adapter.normalizar_resposta(texto)
    assert res.status is StatusCotacao.COTADO
    assert res.valor_frete == esperado


def test_painel_sem_valor_vira_erro(adapter):
    res = adapter.normalizar_resposta("Resultado\nNenhum valor disponível")
    assert res.status is StatusCotacao.ERRO
    assert "não devolveu valor" in res.erro


@pytest.mark.parametrize("texto", [
    "Resultado\nCEP nao atendido\nDica",
    "Resultado\nCEP não atendido\nDica",
    "Resultado\nCEP NAO ATENDIDO",
    "Resultado\nLocalidade não atendida",
])
def test_cep_fora_de_cobertura_e_recusa_nao_erro(adapter, texto):
    """Visto em produção 13/08/2026: Vitória/ES -> Cachoeiro/ES no Expresso.

    'CEP não atendido' é a Jadlog dizendo que não roda aquela rota — é
    RECUSADO, igual a um vendedor dizendo não. Tratar como ERRO faz o operador
    caçar bug de código onde não tem bug, e some com o motivo real."""
    res = adapter.normalizar_resposta(texto)
    assert res.status is StatusCotacao.RECUSADO
    assert res.valor_frete is None
    assert res.erro is None
    assert "atendid" in (res.motivo_recusa or "").lower()


def test_simulador_nao_informa_prazo(adapter):
    """Regressão: o simulador só dá valor. Inventar prazo aqui seria mentira."""
    assert adapter.normalizar_resposta("R$ 99,90").prazo_dias is None


def test_conversor_de_numero():
    assert _num_br_para_decimal("1.234,56") == Decimal("1234.56")
    assert _num_br_para_decimal("118.09") == Decimal("118.09")
    assert _num_br_para_decimal("61,27") == Decimal("61.27")
    assert _num_br_para_decimal("lixo") is None
