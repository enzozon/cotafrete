"""A Generoso recusando por praça fora da malha — e por que isso não era ERRO.

Seis cotações reais entre 24/08 e 31/08/2026 (#5, #20, #40, #43, #78, #79)
viraram:

    RuntimeError: a etapa do destino não avançou. O site diz:
    (nenhuma mensagem visível)

O print de cada uma mostra a mesma coisa: o CEP É resolvido (cidade e rua
vêm preenchidas, ex. "São Sebastião do Passé/BA", "Maceió/AL"), mas um aviso
vermelho aparece embaixo do campo — "Ainda não atendemos essa origem. Veja
nossas unidades e cidades atendidas." — e o botão Próximo trava sem avançar.

`_erros_da_tela` não pega esse aviso: o filtro lá só casa
"obrigat|inválid|erro", e "não atendemos" não tem nenhuma dessas palavras.
Por isso a tela virava "(nenhuma mensagem visível)" mesmo com o aviso
visível na tela — mesma classe de bug de test_generoso_cnpj.py, resolvida
do mesmo jeito: checar o texto real da tela ANTES do Próximo, e virar
RECUSADO com a frase certa em vez de ERRO genérico repetido pela retentativa.
"""

from __future__ import annotations

import pytest

from carriers.generoso import mapping as m
from carriers.generoso.adapter import ForaDeArea, GenerosoAdapter
from core.models import StatusCotacao
from core.retentativa import vale_repetir
from tests.test_jadlog import montar

# Frase real, capturada nos prints de teste_real/generoso/20260826-165411/ e
# .../20260831-102226/ (produção).
AVISO_REAL = ("Ainda não atendemos essa origem. Veja nossas unidades e "
              "cidades atendidas.")


def test_a_frase_do_site_esta_reconhecida_no_mapping():
    assert m.AVISO_CEP_NAO_ATENDIDO in AVISO_REAL.lower()


@pytest.mark.parametrize("lado", ["origem", "destino"])
def test_a_recusa_nomeia_o_lado_e_o_cep(lado):
    """Numa cotação existem DOIS CEPs. Não dizer qual deixa o vendedor
    procurando no escuro — mesma lição de recusa_cliente_nao_cadastrado."""
    frase = m.recusa_cep_nao_atendido("62670000", lado)

    assert "62670000" in frase
    assert lado in frase
    assert "WhatsApp" in frase


def test_a_recusa_nao_fala_em_erro_de_sistema():
    frase = m.recusa_cep_nao_atendido("62670000", "destino")

    for tecnique in ("RuntimeError", "Timeout", "None", "null"):
        assert tecnique not in frase


# ------------------------------------- o que faz a repetição inútil parar
def test_cep_fora_de_area_vira_recusa_e_nao_repete(tmp_path):
    """RECUSADO, não ERRO — o que impede a retentativa de repetir três vezes
    para ouvir o mesmo "não atendemos" que a Generoso já tinha dado na
    primeira. Mesma forma de test_cliente_nao_cadastrado_vira_recusa_e_nao_repete
    em test_generoso_cnpj.py: `_entrar` levanta a exceção no lugar de
    percorrer o site, então nenhuma rede é tocada."""
    def recusar(self, page):
        raise ForaDeArea(m.recusa_cep_nao_atendido("62670000", "destino"))

    adapter = GenerosoAdapter(workdir=str(tmp_path), usuario="teste",
                              senha="teste")
    adapter._entrar = recusar.__get__(adapter)

    res = adapter.cotar(montar())

    assert res.status is StatusCotacao.RECUSADO
    assert res.erro is None, "recusa não é erro; o cartão lê isso"
    assert "62670000" in (res.motivo_recusa or "")
    assert not vale_repetir(res), "repetir daria o mesmo não, custando uma vaga"
