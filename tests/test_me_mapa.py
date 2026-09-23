"""Tradução das regras para os campos do formulário do ME — sem navegador.

Nomes e códigos vêm do recon e do teste real de Salvar (23/09/2026): o que
está aqui foi o que o ME aceitou e devolveu igual depois de salvar.
"""

from __future__ import annotations

from datetime import date

import pytest

from mercado_eletronico import mapa as M
from mercado_eletronico.regras import Conta, EntradaItem, PedidoDoComprador

HOJE = date(2026, 9, 23)
MG = PedidoDoComprador(uf_destino="MG", origem=0)
ES = PedidoDoComprador(uf_destino="ES", origem=0)


def _item(**muda):
    base = dict(numero=10, preco="1,00", ncm="48219000", prazo_dias=30, marca="TESTE",
                obs="obs", origem=0, pedido=MG)
    base.update(muda)
    return EntradaItem(**base)


def test_item_da_uniao_igual_ao_que_o_me_aceitou_no_teste_real():
    campos = M.campos_item(Conta.UNIAO, _item(), 1, HOJE)
    assert campos == {
        "Preco1": "1,00", "UnidadeResp1": "UN", "TipoImposto1": "1",
        "IPI1": "0,00", "IPIIncluso1": "I", "ICMS1": "12,00", "ICMSIncluso1": "S",
        "PIS1": "0,00", "PISIncluso1": "I", "COFINS1": "0,00", "COFINSIncluso1": "I",
        "NCM1": "4821.90.00", "Prazo1": "30", "DataEntregaItemAux1": "23/10/2026",
        "Fabricante1": "TESTE", "Observacao1": "obs", "OrigMat1": "992",
        "SubstituicaoTributaria1": "N", "AliquotaSubstituicaoTributaria1": "0,00",
        "ValorSubstituicaoTributaria1": "0,00", "BaseCalculo1": "100,00",
        "BaseCalculoImposto1": "S",
    }


def test_ventura_cobra_pis_e_cofins_e_icms_17_no_es():
    c = M.campos_item(Conta.VENTURA, _item(pedido=ES), 3, HOJE)
    assert (c["PIS3"], c["PISIncluso3"], c["COFINS3"], c["COFINSIncluso3"]) == ("0,65", "S", "3,00", "S")
    assert c["ICMS3"] == "17,00"


@pytest.mark.parametrize("origem, codigo", [(0, "992"), (2, "994")])
def test_origem_vira_codigo_do_select(origem, codigo):
    assert M.campos_item(Conta.UNIAO, _item(origem=origem), 1, HOJE)["OrigMat1"] == codigo


def test_indice_do_campo_e_o_da_pagina_nao_o_numero_do_item():
    c = M.campos_item(Conta.UNIAO, _item(numero=110), 1, HOJE)
    assert "Preco1" in c and "Preco110" not in c


def test_cabecalho_fixo_e_validade():
    cab = M.campos_cabecalho(validade_dias=30, hoje=HOJE, obs="")
    assert cab == {
        "IcoTerms": "FOB", "atrib_CidadeEstado_1_1_0_0": "Frete FOB",
        "CondicaoPagamento": "F060", "NumFoneCota": "2732991664", "MoedaCot": "BRL",
        "ValidadePropostaAux": "23/10/2026", "ObsForn": "",
    }


def test_plano_limpa_a_base_dos_itens_sem_resposta():
    # sem isso o ME recusa: "Base de cálculo preenchida... informe o Preço"
    plano = M.plano_pagina(Conta.UNIAO, {1: _item(), 2: None, 3: None}, 30, HOJE)
    assert plano.campos["BaseCalculo2"] == "" and plano.campos["BaseCalculo3"] == ""
    assert plano.marcar == [1]
    assert plano.campos["Preco1"] == "1,00"


def test_item_sem_preco_fica_vazio_e_a_justificativa_vai_para_a_obs_geral():
    sem = _item(numero=20, preco="", obs="fora de linha")
    plano = M.plano_pagina(Conta.UNIAO, {1: _item(), 2: sem}, 30, HOJE)
    assert plano.campos["BaseCalculo2"] == "" and "Preco2" not in plano.campos
    assert plano.marcar == [1]
    assert "Item 20: fora de linha" in plano.campos["ObsForn"]


def test_plano_recusa_item_invalido():
    with pytest.raises(M.PlanoInvalido) as exc:
        M.plano_pagina(Conta.UNIAO, {1: _item(ncm="123")}, 30, HOJE)
    assert "NCM" in str(exc.value)


def test_plano_sem_validade_recusado():
    with pytest.raises(M.PlanoInvalido):
        M.plano_pagina(Conta.UNIAO, {1: _item()}, None, HOJE)


def test_avisos_seguem_no_plano_sem_bloquear():
    plano = M.plano_pagina(Conta.UNIAO, {1: _item(marca="")}, 30, HOJE)
    assert any("marca" in a for a in plano.avisos)
