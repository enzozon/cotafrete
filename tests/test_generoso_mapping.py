"""As empresas do grupo, e o CIF/FOB que a Generoso nao perdoa.

A Generoso PRENDE uma das pontas no CNPJ cadastrado — no CIF a origem, no
FOB o destino — e nao deixa mexer no CEP dela. Se o vendedor marca CIF mas
poe uma empresa DO GRUPO no destino, as duas pontas viram a mesma casa: o
site trava, e a reclamacao ("CEP de coleta nao pode ser o mesmo de destino")
mora so no `aria-invalid`, invisivel para quem le a tela.

Resultado ate hoje: "a etapa do destino nao avancou. O site diz: (nenhuma
mensagem visivel)". Aconteceu nas cotacoes #5 e #20 de producao e na #53 de
desenvolvimento — as tres com a MESMA forma, CIF com empresa do grupo no
destino. Nenhuma outra falha da Generoso no historico tem essa forma.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from carriers.generoso.mapping import (
    EMPRESAS, conflito_cif_fob, empresa_de, lado_do_grupo,
)
from core.models import Parte, TipoFrete
from tests.test_jadlog import montar

HERCULES = "60.042.686/0001-05"          # cliente, nao e do grupo
ALIANCA = "05.954.058/0001-98"
VENTURA = "08.310.365/0001-24"
UNIAO = "20.837.281/0001-49"


def cotacao(*, tipo, rem, dest):
    return montar(tipo_frete=tipo, remetente=Parte(cnpj=rem),
                  destinatario=Parte(cnpj=dest))


# ------------------------------------------------------ o cadastro
def test_as_tres_empresas_do_grupo():
    assert {e.cnpj for e in EMPRESAS} == {VENTURA, ALIANCA, UNIAO}


@pytest.mark.parametrize("escrito", [
    "05.954.058/0001-98", "05954058000198", " 05.954.058/0001-98 ",
])
def test_reconhece_o_cnpj_em_qualquer_formato(escrito):
    """O formulario aceita com e sem mascara; a busca nao pode depender disso."""
    assert empresa_de(escrito).cnpj == ALIANCA


def test_cnpj_de_fora_do_grupo_nao_e_empresa():
    assert empresa_de(HERCULES) is None
    assert empresa_de("") is None


# --------------------------------------------- de que lado esta o grupo
def test_grupo_na_origem_e_frete_saindo():
    assert lado_do_grupo(cotacao(tipo=TipoFrete.CIF, rem=UNIAO,
                                 dest=HERCULES)) == "origem"


def test_grupo_no_destino_e_frete_chegando():
    assert lado_do_grupo(cotacao(tipo=TipoFrete.FOB, rem=HERCULES,
                                 dest=VENTURA)) == "destino"


def test_grupo_dos_dois_lados():
    assert lado_do_grupo(cotacao(tipo=TipoFrete.CIF, rem=VENTURA,
                                 dest=ALIANCA)) == "ambos"


def test_sem_o_grupo_em_nenhuma_ponta():
    assert lado_do_grupo(cotacao(tipo=TipoFrete.CIF, rem=HERCULES,
                                 dest="45.723.174/0001-10")) is None


# ------------------------------------------------- o conflito, e a frase
def test_a_forma_exata_das_cotacoes_5_20_e_53(tmp_path=None):
    """CIF com empresa do grupo no destino. As tres falhas reais."""
    conflito = conflito_cif_fob(
        cotacao(tipo=TipoFrete.CIF, rem=HERCULES, dest=ALIANCA))

    assert conflito is not None
    assert "FOB" in conflito
    assert "CIF" in conflito


def test_o_contrario_tambem_e_conflito():
    """FOB com o grupo despachando: a carga esta SAINDO, entao e CIF."""
    conflito = conflito_cif_fob(
        cotacao(tipo=TipoFrete.FOB, rem=UNIAO, dest=HERCULES))

    assert conflito is not None
    assert "CIF" in conflito


@pytest.mark.parametrize("tipo, rem, dest", [
    (TipoFrete.CIF, UNIAO, HERCULES),      # grupo despacha, marcado CIF
    (TipoFrete.FOB, HERCULES, VENTURA),    # grupo recebe, marcado FOB
    (TipoFrete.CIF, HERCULES, "45.723.174/0001-10"),   # grupo fora das pontas
])
def test_cotacao_coerente_nao_e_barrada(tipo, rem, dest):
    """A trava so pode pegar o caso comprovado. Barrar cotacao boa e pior
    que o bug: o vendedor fica sem preco e sem saber o que fazer."""
    assert conflito_cif_fob(cotacao(tipo=tipo, rem=rem, dest=dest)) is None


def test_a_frase_diz_o_que_fazer_e_nao_so_o_que_esta_errado():
    """O vendedor precisa sair da tela sabendo o proximo clique."""
    conflito = conflito_cif_fob(
        cotacao(tipo=TipoFrete.CIF, rem=HERCULES, dest=ALIANCA))

    assert "CEP" in conflito          # explica por que nao da para "so corrigir"
    assert conflito.rstrip().endswith(".")
    assert len(conflito) < 400


# ------------------------------- qual empresa o site tem que ficar mostrando
def test_no_cif_a_empresa_e_a_do_remetente():
    """CIF: o grupo despacha, entao a ponta travada e a ORIGEM."""
    from carriers.generoso.mapping import empresa_alvo
    alvo = empresa_alvo(cotacao(tipo=TipoFrete.CIF, rem=UNIAO, dest=HERCULES))
    assert alvo.cnpj == UNIAO


def test_no_fob_a_empresa_e_a_do_destinatario():
    """FOB: o grupo recebe, entao a ponta travada e o DESTINO."""
    from carriers.generoso.mapping import empresa_alvo
    alvo = empresa_alvo(cotacao(tipo=TipoFrete.FOB, rem=HERCULES, dest=ALIANCA))
    assert alvo.cnpj == ALIANCA


def test_sem_empresa_do_grupo_na_ponta_travada_nao_ha_alvo():
    """Nada a trocar: fica o que a conta ja mostra, como sempre foi."""
    from carriers.generoso.mapping import empresa_alvo
    assert empresa_alvo(
        cotacao(tipo=TipoFrete.CIF, rem=HERCULES, dest=ALIANCA)) is None
