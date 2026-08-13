"""Camada pura da calculadora do painel da Jadlog.

O que dá para travar offline: o payload (peso de UM volume, não do lote) e a
leitura da tabela de resultado, com as modalidades que só aparecem depois do
cálculo.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from carriers.jadlog.painel import (
    ROTULO_ALTURA, ROTULO_COMPRIMENTO, ROTULO_LARGURA, JadlogPainelAdapter,
    ler_opcoes,
)
from core.models import StatusCotacao, Volume
from tests.test_jadlog import montar


@pytest.fixture
def adapter():
    return JadlogPainelAdapter()


# Tela real, medida em 13/08/2026 (o print que o Enzo mandou).
RESULTADO = """Calculadora
Limite de Envios Atual: 50
Dados do Envio
Endereço de Origem: 09895-003
Endereço de Destino: 29105-770
Valor do Produto: R$ 586,77
Peso: 1kg
Altura (cm): 30 cm
Comprimento (cm): 30 cm
Largura (cm): 30 cm
Custo de Envio
Transportadora Modalidade Balcão Prazo Valor Opções
jadlog Express 2-3 dias R$ 55,12 Comprar
jadlog Standard 3-4 dias R$ 33,56 Comprar
"""


# ----------------------------------------------------- peso de UM volume
def test_payload_manda_o_peso_de_um_volume_nao_o_do_lote(adapter):
    """A calculadora cota um pacote por vez.

    Com 3 volumes de 12 kg, mandar 36 kg junto das medidas de UMA caixa
    cotaria uma caixa de 30x30x30 pesando 36 kg — carga que não existe. A
    regra combinada com o Enzo é fazer 3 cálculos separados."""
    req = montar(volumes=[Volume(qtd=3, comprimento_cm=Decimal(30),
                                 largura_cm=Decimal(30), altura_cm=Decimal(30),
                                 peso_kg=Decimal(12))])
    p = adapter.preparar_payload(req)

    assert p["peso"] == "12,00"        # não 36; e com 2 casas, pela máscara
    assert req.peso_total_kg == Decimal(36)


def test_medidas_vao_para_o_rotulo_certo(adapter):
    """A ordem da tela é Altura, Largura, Comprimento — invertida em relação
    ao simulador antigo. Casar por posição trocaria altura com largura."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(80),
                                 largura_cm=Decimal(60), altura_cm=Decimal(50),
                                 peso_kg=Decimal(4))])
    p = adapter.preparar_payload(req)

    assert p[ROTULO_ALTURA] == "50"
    assert p[ROTULO_LARGURA] == "60"
    assert p[ROTULO_COMPRIMENTO] == "80"


@pytest.mark.parametrize("kg, esperado", [
    (Decimal(1), "1,00"),
    (Decimal(12), "12,00"),
    (Decimal("0.5"), "0,50"),
    (Decimal(25), "25,00"),
    (Decimal("1.5"), "1,50"),
])
def test_peso_vai_com_duas_casas_por_causa_da_mascara(adapter, kg, esperado):
    """Máscara medida no site em 13/08/2026: o campo é de 2 casas, preenchido
    da direita para a esquerda.

        "1"    -> 0,01
        "0,5"  -> 0,05
        "1,00" -> 1,00

    Mandar "1" cotava 0,01 kg — um centésimo da carga. O print do resultado
    mostrava "Peso: 0.1kg" e o frete saía barato, sem erro nenhum na tela.
    """
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(30),
                                 largura_cm=Decimal(30), altura_cm=Decimal(30),
                                 peso_kg=kg)])
    assert adapter.preparar_payload(req)["peso"] == esperado


def test_medida_vai_sem_casa_decimal(adapter):
    """O campo de medida NÃO tem máscara: "30" fica "30", e "30,0" vira
    "30.0". Regra oposta à da Della Volpe, onde a medida precisa de uma casa.
    Mesmo dado, dois formatos — é o adapter que resolve, não a ficha."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(30),
                                 largura_cm=Decimal(30), altura_cm=Decimal(30),
                                 peso_kg=Decimal(1))])
    p = adapter.preparar_payload(req)
    assert p[ROTULO_ALTURA] == "30"
    assert "," not in p[ROTULO_ALTURA] and "." not in p[ROTULO_ALTURA]


def test_cep_sem_mascara_e_valor_em_virgula(adapter):
    p = adapter.preparar_payload(montar(cep_ori="29.010-000"))
    assert p["cep_origem"] == "29010000"
    assert p["valor"] == "1500,00"


# --------------------------------------------------- leitura do resultado
def test_le_as_duas_modalidades_da_tela_real():
    opcoes = ler_opcoes(RESULTADO)
    por_nome = {o.modalidade: o for o in opcoes}

    assert por_nome["Express"].valor == Decimal("55.12")
    assert por_nome["Express"].prazo == "2-3 dias"
    assert por_nome["Standard"].valor == Decimal("33.56")
    assert por_nome["Standard"].prazo == "3-4 dias"


def test_valor_do_produto_no_cabecalho_nao_vira_opcao():
    """'Valor do Produto: R$ 586,77' aparece antes da tabela. Contá-lo como
    frete daria uma cotação de R$ 586,77 — o valor da mercadoria."""
    modalidades = {o.modalidade for o in ler_opcoes(RESULTADO)}
    assert modalidades == {"Express", "Standard"}


def test_cotacao_usa_a_opcao_mais_barata(adapter):
    res = adapter.normalizar_resposta(RESULTADO)
    assert res.status is StatusCotacao.COTADO
    assert res.valor_frete == Decimal("33.56")


def test_prazo_em_faixa_nao_vira_numero(adapter):
    """O painel dá '2-3 dias'. Escolher 2 ou 3 seria inventar."""
    assert adapter.normalizar_resposta(RESULTADO).prazo_dias is None


def test_tela_sem_opcao_vira_erro(adapter):
    res = adapter.normalizar_resposta("Calculadora\nNenhum resultado")
    assert res.status is StatusCotacao.ERRO
    assert "nenhuma opção" in res.erro
