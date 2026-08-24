"""Camada pura da Camilo dos Santos (SSW).

O erro caro deste site é a unidade: a cubagem é em METROS. Uma caixa de 30 cm
vai como 0,300. Mandar 30 cotaria uma caixa de 30 metros — e ao contrário das
outras armadilhas do projeto, esta erra para MAIS: frete absurdo em vez de
frete barato.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from carriers.camilo.adapter import (
    FRETE_CIF, FRETE_FOB, CamiloAdapter, ler_resultado,
)
from core.models import StatusCotacao, Volume
from tests.test_jadlog import montar


@pytest.fixture
def adapter():
    return CamiloAdapter()


# ------------------------------------------------------- metros, não cm
@pytest.mark.parametrize("cm, metros", [
    (Decimal(30), "0,300"),
    (Decimal(100), "1,000"),
    (Decimal(5), "0,050"),
    (Decimal(260), "2,600"),
    (Decimal(1250), "12,500"),
])
def test_medida_vai_em_metros(adapter, cm, metros):
    """"Dimensões em metros", diz o próprio popup do site."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=cm, largura_cm=cm,
                                 altura_cm=cm, peso_kg=Decimal(1))])
    p = adapter.preparar_payload(req)

    assert p["cub_alt_1"] == metros
    assert p["cub_larg_1"] == metros
    assert p["cub_comp_1"] == metros


def test_uma_linha_de_cubagem_por_tamanho(adapter):
    """O popup tem 20 linhas. Dois tamanhos diferentes ocupam duas, cada uma
    com a própria quantidade — resolve os pedidos de 80 volumes em UMA cotação,
    coisa que a Jadlog exigiria em N cálculos separados."""
    req = montar(volumes=[
        Volume(qtd=40, comprimento_cm=Decimal(104), largura_cm=Decimal(44),
               altura_cm=Decimal(19), peso_kg=Decimal(30)),
        Volume(qtd=40, comprimento_cm=Decimal(210), largura_cm=Decimal(10),
               altura_cm=Decimal(10), peso_kg=Decimal(33)),
    ])
    p = adapter.preparar_payload(req)

    assert (p["cub_alt_1"], p["cub_larg_1"], p["cub_comp_1"]) == \
        ("0,190", "0,440", "1,040")
    assert p["cub_nro_vezes_1"] == "40"
    assert (p["cub_alt_2"], p["cub_larg_2"], p["cub_comp_2"]) == \
        ("0,100", "0,100", "2,100")
    assert p["cub_nro_vezes_2"] == "40"
    assert p["qtde_vol"] == "80"


def test_mais_de_vinte_tamanhos_e_recusado(adapter):
    """O popup tem 20 linhas. Silenciosamente ignorar a 21ª cotaria menos
    carga do que existe."""
    volumes = [Volume(qtd=1, comprimento_cm=Decimal(10 + i),
                      largura_cm=Decimal(10), altura_cm=Decimal(10),
                      peso_kg=Decimal(1)) for i in range(21)]
    with pytest.raises(ValueError, match="20"):
        adapter.preparar_payload(montar(volumes=volumes))


# ------------------------------------------------------------- outros campos
def test_cep_so_digitos_e_cnpj_sem_mascara(adapter):
    p = adapter.preparar_payload(montar(cep_ori="29.010-000"))
    assert p["cep_origem"] == "29010000"
    assert p["cep_destino"] == "01310100"
    # CIF: quem paga e o remetente. O CNPJ do pagador deixou de ser
    # digitado a parte — ver core.models.TipoFrete.
    assert p["cgc_pag"] == "11222333000181"      # o pagador, sem pontuação


def test_tipo_de_frete_vem_do_pedido_e_nao_do_adapter(adapter):
    """Era fixo em FOB no construtor, enquanto o formulario mandava um CNPJ da
    Ventura como pagador — que e CIF. Os dois se contradiziam e o SSW recebia
    a combinacao errada, sem ninguem ver.

    Agora tp_frete e cgc_pag saem da MESMA escolha, entao nao tem como
    discordarem. A prova completa esta em tests/test_tipo_frete.py."""
    from core.models import TipoFrete

    cif = adapter.preparar_payload(montar(tipo_frete=TipoFrete.CIF))
    fob = adapter.preparar_payload(montar(tipo_frete=TipoFrete.FOB))

    assert (cif["tp_frete"], fob["tp_frete"]) == (FRETE_CIF, FRETE_FOB)
    assert cif["cgc_pag"] != fob["cgc_pag"]


def test_padroes_confirmados_pelo_enzo(adapter):
    p = adapter.preparar_payload(montar())
    assert p["coletar"] == "S"
    assert p["contribuinte"] == "S"
    assert p["ent_dif"] == "N"


def test_campos_opcionais_ficam_de_fora(adapter):
    """Enzo cota só com o CNPJ pagador, como faz à mão."""
    p = adapter.preparar_payload(montar())
    for opcional in ("cgc_rem", "cgc_dest", "tp_merc", "qtde_pares",
                     "chave_nfe"):
        assert p.get(opcional, "") == ""


def test_peso_e_valor_em_formato_brasileiro(adapter):
    p = adapter.preparar_payload(montar())
    assert p["peso"] == "5,000"           # a fixture tem 1 volume de 5 kg
    assert p["vlr_merc"] == "1500,00"


# ------------------------------------------------------ leitura do resultado
def test_le_valor_e_numero_da_cotacao():
    achado = ler_resultado({"vlr_frete": "69,91", "nro_cotacao": "2799331"})
    assert achado == (Decimal("69.91"), "2799331")


def test_resultado_vazio_nao_vira_cotacao(adapter):
    """Sem valor não houve cálculo. Dar COTADO aqui repetiria o erro da
    Della Volpe, onde status otimista escondeu envio que nunca saiu."""
    res = adapter.normalizar_resposta({"vlr_frete": "", "nro_cotacao": ""})
    assert res.status is StatusCotacao.ERRO


def test_resultado_com_valor_vira_cotado(adapter):
    res = adapter.normalizar_resposta(
        {"vlr_frete": "69,91", "nro_cotacao": "2799331"})
    assert res.status is StatusCotacao.COTADO
    assert res.valor_frete == Decimal("69.91")
    assert res.protocolo == "2799331"


# --------------------------- quando o SSW diz nao, quem fala e o SSW
def test_popup_do_site_vira_recusa_com_as_palavras_dele(adapter):
    """A cotacao #10 de producao (24/08/2026), destino Sao Goncalo/RJ.

    O SSW abriu um "Aviso" dizendo "Cliente nao possui tabela de frete
    negociada. Cotacao nao permitida." — e o adapter FECHAVA o popup para
    tirar ele da frente do print, jogando a frase fora. Sobrava
    "A tela nao devolveu valor de frete": cara de defeito do programa, e
    ainda repetido tres vezes pela retentativa.
    """
    res = adapter.normalizar_resposta(
        {"vlr_frete": "", "nro_cotacao": "",
         "aviso": "Cliente não possui tabela de frete negociada. "
                  "Cotação não permitida."})

    assert res.status is StatusCotacao.RECUSADO
    assert res.erro is None
    assert "tabela de frete negociada" in res.motivo_recusa


def test_cep_nao_atendido_vira_recusa(adapter):
    """O rotulo vermelho ao lado do campo de CEP. Ninguem lia essa regiao da
    tela, entao virava o mesmo generico."""
    res = adapter.normalizar_resposta(
        {"vlr_frete": "", "nro_cotacao": "",
         "aviso": "CEP INVÁLIDO/NÃO ATENDIDO"})

    assert res.status is StatusCotacao.RECUSADO
    assert "CEP" in res.motivo_recusa


def test_sem_aviso_e_sem_preco_continua_sendo_erro(adapter):
    """Tela muda que ninguem entendeu continua erro — e continua sendo
    repetida, que e o certo para o que nao se sabe explicar."""
    res = adapter.normalizar_resposta({"vlr_frete": "", "nro_cotacao": ""})

    assert res.status is StatusCotacao.ERRO
