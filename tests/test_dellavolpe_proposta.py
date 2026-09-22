"""O PDF de proposta da Della Volpe, lido.

A fixture é o texto extraído do PDF REAL da proposta 15626/26, recebida em
22/09/2026. Texto e não o PDF: o arquivo tem 1,7 MB de papel timbrado, e o
que este módulo precisa provar é a leitura, não o pypdf.

O ERRO CARO deste arquivo tem nome e sobrenome. O PDF traz DOIS valores:

    FRETE: R$167,63
    ...
    VALOR TOTAL DO FRETE: R$196,40

O primeiro é o frete sem as taxas; o segundo é o que a Ventura paga. Ler o
primeiro mostraria a Della Volpe 17% mais barata do que ela é — e como a tela
dá o selo de MAIS BARATO ao menor número, ela ganharia a comparação com um
preço que não existe. As outras transportadoras já mostram preço com taxas e
ICMS (ver NOTAS em web/app.py), então o total é o único número comparável.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from carriers.dellavolpe.proposta import ler_proposta

TEXTO = (Path(__file__).parent / "fixtures"
         / "dellavolpe_proposta.txt").read_text(encoding="utf-8")


@pytest.fixture
def proposta():
    return ler_proposta(TEXTO)


# ------------------------------------------------------------ o dinheiro
def test_le_o_valor_total_e_nao_o_frete_sem_taxas(proposta):
    """O teste que este arquivo existe para ter."""
    assert proposta.valor == Decimal("196.40")


def test_nao_confunde_com_o_frete_puro(proposta):
    """167,63 é o frete antes de ad-valorem, taxa de CTe e ICMS. Ele está no
    PDF, logo acima, e casar com ele é o jeito mais fácil de errar aqui."""
    assert proposta.valor != Decimal("167.63")


def test_pdf_sem_valor_total_nao_inventa_numero():
    """Se a Della Volpe mudar o rótulo, o certo é devolver None e deixar a
    tela dizer que não deu para ler — nunca cair no primeiro R$ que aparecer,
    que seria justamente o valor errado."""
    sem_total = TEXTO.replace("VALOR TOTAL DO FRETE", "XXX")

    assert ler_proposta(sem_total).valor is None


# --------------------------------------------------------------- o resto
def test_le_o_numero_da_proposta(proposta):
    """É por ele que se fala com a Della Volpe sobre esta cotação."""
    assert proposta.numero == "15626/26"


def test_le_o_prazo_de_entrega_em_dias(proposta):
    """"PREVISÂO DE ENTREGA: 6 Dias úteis" — o resto do sistema compara
    prazo em dias, como nas outras transportadoras."""
    assert proposta.prazo_dias == 6


def test_le_a_data_do_documento(proposta):
    """"São Paulo, 22 de setembro de 2026" — por extenso, no cabeçalho."""
    assert proposta.emitida_em == date(2026, 9, 22)


def test_le_ate_quando_a_proposta_vale(proposta):
    """"Validade da proposta: 7 dias", contados da data do documento. Entra
    na mesma coluna de validade das outras transportadoras."""
    assert proposta.validade == date(2026, 9, 29)


# ---------------------------------------------------------- o casamento
def test_le_o_destinatario(proposta):
    """"A/C: ENZO ZON" vem do campo "Nome completo" do formulário. É onde o
    Cotafrete carimba o número da cotação para saber, depois, de qual
    cotação é este PDF."""
    assert "ENZO ZON" in proposta.destinatario


def test_extrai_o_numero_da_cotacao_carimbado():
    """O formato que o envio usa: "Enzo Zon (cot. 208)" volta no PDF como
    "A/C: ENZO ZON (COT. 208)" — em maiúsculas, que é como o PDF escreve."""
    com_carimbo = TEXTO.replace("A/C: ENZO ZON", "A/C: ENZO ZON (COT. 208)")

    assert ler_proposta(com_carimbo).cotacao_id == 208


def test_sem_carimbo_nao_chuta_cotacao(proposta):
    """PDF de uma cotação feita à mão, fora do sistema, não pode ser colado
    em cotação nenhuma — mostrar o preço de uma carga em outra é o erro que
    chega na mesa do cliente."""
    assert proposta.cotacao_id is None


# ------------------------------------------------------------ robustez
def test_texto_vazio_nao_levanta():
    """O ingestor roda em segundo plano: uma exceção aqui mata a thread e o
    PDF seguinte nunca é lido."""
    vazio = ler_proposta("")

    assert vazio.valor is None
    assert vazio.numero is None


def test_texto_que_nao_e_proposta_nao_levanta():
    assert ler_proposta("Olá, segue em anexo o catálogo.").valor is None
