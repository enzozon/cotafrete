"""A Generoso só cota com a Ventura na ponta que o portal TRAVA.

O portal dela cota LOGADO, e preenche cada ponta pelo CNPJ — nunca pelo CEP
que o vendedor digitou. Uma das pontas fica travada no CNPJ da conta: no CIF
a origem, no FOB o destino. Se a Ventura não estiver ali, o site escreve o
endereço DELA naquela ponta, e o preço volta de outra rota.

Cotação #154 (10/09/2026), rodada em dry-run contra o site real:

    ficha:  São Paulo/SP 05117-002  ->  Linhares/ES 29911-080
            FOB, ADECIL COMERCIAL -> INSTITUTO AMBIENTAL
            (a Ventura não é nenhuma das duas pontas)

    tela:   origem   ADECIL,  13.211-377, Jundiaí/SP
            destino  VENTURA, 29.105-770, Vila Velha/ES

O preço que sairia dali é de Jundiaí -> Vila Velha. Quando a busca da ponta
travada nem responde, o mesmo caso vira `RuntimeError: a conta da Generoso
nao trouxe o endereco de destino` — ERRO, repetido três vezes pela
retentativa. Era esse o "flag de falha" que o Enzo via.

Barrar não tira preço de ninguém: nos 143 resultados da Generoso em produção
(19/08 a 09/09/2026), as 83 COM preço tinham todas o grupo na ponta travada.
Sem ele ali, nunca saiu preço — só 2 erros e 7 recusas.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from carriers.generoso import mapping as m
from carriers.generoso.adapter import GenerosoAdapter
from core.models import (Local, Mercadoria, NotaFiscal, Parte, StatusCotacao,
                         TipoFrete, Volume)
from core.retentativa import vale_repetir
from tests.test_jadlog import montar

VENTURA = "08.310.365/0001-24"
ALIANCA = "05.954.058/0001-98"
ADECIL = "05.074.931/0001-58"          # remetente da #154
INSTITUTO = "04.151.690/0001-30"       # destinatário da #154


def cotacao_154():
    """A #154 como o vendedor preencheu — FOB, Ventura em ponta nenhuma."""
    return montar(
        origem=Local(uf="SP", cidade="São Paulo", cep="05117-002"),
        destino=Local(uf="ES", cidade="Linhares", cep="29911-080"),
        remetente=Parte(cnpj=ADECIL, nome="ADECIL COMERCIAL LTDA"),
        destinatario=Parte(cnpj=INSTITUTO, nome="INSTITUTO AMBIENTAL"),
        tipo_frete=TipoFrete.FOB,
        volumes=[Volume(qtd=1, comprimento_cm=Decimal(70),
                        largura_cm=Decimal(26), altura_cm=Decimal(33),
                        peso_kg=Decimal(3))],
        mercadoria=Mercadoria(tipo_material="localizador cabo"),
        nota_fiscal=NotaFiscal(valor_total=Decimal("38718.75")),
    )


# ------------------------------------------------------------ a camada pura
def test_a_154_e_pega_pela_regra():
    """O caso real. Sem esta regra ele passava direto e virava preço errado."""
    frase = m.ponta_travada_sem_o_grupo(cotacao_154())

    assert frase is not None
    assert "destino" in frase, "no FOB quem trava é o destino"
    assert "Ventura" in frase


@pytest.mark.parametrize("tipo,ponta,cnpj_bom", [
    (TipoFrete.CIF, "remetente", VENTURA),
    (TipoFrete.FOB, "destinatario", VENTURA),
    (TipoFrete.CIF, "remetente", ALIANCA),
])
def test_com_o_grupo_na_ponta_travada_nao_reclama(tipo, ponta, cnpj_bom):
    """As 83 cotações que voltaram com preço em produção são deste formato —
    nenhuma delas pode passar a ser recusada."""
    req = montar(tipo_frete=tipo, **{ponta: Parte(cnpj=cnpj_bom)})

    assert m.ponta_travada_sem_o_grupo(req) is None


def test_a_ponta_LIVRE_pode_ser_de_quem_for():
    """Só a travada precisa ser do grupo. Exigir as duas recusaria toda
    cotação de verdade — o cliente nunca é do grupo."""
    req = montar(tipo_frete=TipoFrete.CIF,
                 remetente=Parte(cnpj=VENTURA),
                 destinatario=Parte(cnpj=INSTITUTO))

    assert m.ponta_travada_sem_o_grupo(req) is None


def test_a_frase_diz_ao_vendedor_o_que_fazer():
    """Recusa que não diz o próximo passo vira ligação para o Enzo."""
    frase = m.ponta_travada_sem_o_grupo(cotacao_154())

    assert "outra transportadora" in frase
    assert "CIF/FOB" in frase
    for tecniques in ("RuntimeError", "None", "Timeout", "null"):
        assert tecniques not in frase


# --------------------------------------- o que economiza navegador e retentativa
def test_vira_recusa_sem_abrir_navegador_e_sem_repetir():
    """RECUSADO, não ERRO — é isso que impede as três rodadas de navegador
    atrás do mesmo endereço que nunca vem.

    Sem credencial de propósito: se a validação não pegasse, `cotar` seguiria
    e pararia no "Faltam GENEROSO_USUARIO..." — status ERRO. O RECUSADO aqui
    prova que a recusa veio ANTES, da validação, sem tocar em navegador nem
    em rede."""
    res = GenerosoAdapter(usuario="", senha="").cotar(cotacao_154())

    assert res.status is StatusCotacao.RECUSADO
    assert res.erro is None, "recusa não é erro; o cartão do vendedor lê isso"
    assert "Ventura" in (res.motivo_recusa or "")
    assert not vale_repetir(res), \
        "repetir daria o mesmo endereço errado, custando 3 vagas de navegador"
