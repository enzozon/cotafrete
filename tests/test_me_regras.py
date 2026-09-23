"""Regras da resposta no Mercado Eletrônico: impostos, datas, validação.

O caso-âncora é real: a cotação 23039029 (Ventura), item 10, bateria de
drone. O ME mostrou 45 dias → 09/11/2026 no dia 23/09/2026 — que só bate com
dias CORRIDOS empurrados para o próximo dia útil (07/11 é sábado).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from mercado_eletronico import feriados as F
from mercado_eletronico import regras as R
from mercado_eletronico.regras import Conta, EntradaItem, PedidoDoComprador

HOJE = date(2026, 9, 23)

CAMPOS_ADICIONAIS_REAL = (
    "NCM: Data de Remessa: 02.11.2026 CNPJ: 16628281000676End. entrega: "
    "Rodovia do Sol, S/N - Ponta Ubu - Anchieta - ES - 29230-000 Categoria do "
    "Material: 00 - Material Utilização do Material: 2 - Consumo Origem do "
    "Material: 0 - Nacional - exceto indicado para códigos 3, 4, 5 ou 8"
)


# ---------------------------------------------------------------- feriados
@pytest.mark.parametrize(
    "ano, pascoa", [(2026, date(2026, 4, 5)), (2027, date(2027, 3, 28))]
)
def test_pascoa(ano, pascoa):
    assert F.pascoa(ano) == pascoa


@pytest.mark.parametrize(
    "dia",
    [
        date(2026, 2, 16), date(2026, 2, 17),  # Carnaval
        date(2026, 4, 3),                      # Sexta-feira Santa
        date(2026, 6, 4),                      # Corpus Christi
        date(2026, 11, 2), date(2026, 11, 20), date(2026, 12, 25),
        date(2027, 2, 8), date(2027, 2, 9), date(2027, 3, 26), date(2027, 5, 27),
        date(2027, 1, 1), date(2027, 4, 21), date(2027, 9, 7), date(2027, 10, 12),
    ],
)
def test_feriados_nacionais_e_moveis(dia):
    assert not F.eh_dia_util(dia)


def test_dia_comum_e_util():
    assert F.eh_dia_util(date(2026, 9, 23))


# -------------------------------------------------------------------- datas
def test_caso_real_do_me_45_dias_cai_no_sabado_e_vai_para_segunda():
    assert R.data_entrega(45, HOJE) == date(2026, 11, 9)


def test_data_que_cai_em_feriado_pula_para_o_proximo_util():
    # 23/09 + 40 = 02/11 (Finados, segunda) → 03/11
    assert R.data_entrega(40, HOJE) == date(2026, 11, 3)


def test_feriado_emendado_com_fim_de_semana():
    # 20/11/2026 é sexta (Consciência Negra) → segunda 23/11
    assert R.data_entrega(58, HOJE) == date(2026, 11, 23)


def test_data_de_entrega_e_sempre_dia_util():
    for prazo in range(1, 400):
        assert F.eh_dia_util(R.data_entrega(prazo, HOJE))


def test_prazo_zero_nao_existe():
    with pytest.raises(ValueError):
        R.data_entrega(0, HOJE)


def test_validade_e_hoje_mais_dias_corridos():
    assert R.validade_proposta(10, HOJE) == date(2026, 10, 3)


# ----------------------------------------------------------------- impostos
@pytest.mark.parametrize("origem", [0, 2])
@pytest.mark.parametrize("uf, esperado", [("ES", "17"), ("es", "17"), ("SP", "12"), ("MG", "12")])
def test_icms_por_origem_e_destino(origem, uf, esperado):
    assert R.aliquota_icms(origem, uf) == Decimal(esperado)


@pytest.mark.parametrize("origem", [1, 3, 4, 5, 6, 7, 8])
def test_origem_sem_regra_bloqueia(origem):
    with pytest.raises(R.RegraDesconhecida):
        R.aliquota_icms(origem, "ES")


def test_uf_desconhecida_bloqueia():
    with pytest.raises(R.RegraDesconhecida):
        R.aliquota_icms(0, "XX")


def test_ventura_cobra_tudo_menos_ipi():
    c = R.impostos(Conta.VENTURA, 0, "ES").como_campos()
    assert c == {
        "icms": "17,00", "icms_incluso": "sim",
        "pis": "0,65", "pis_incluso": "sim",
        "cofins": "3,00", "cofins_incluso": "sim",
    }


def test_uniao_cobra_so_icms():
    c = R.impostos(Conta.UNIAO, 2, "RJ").como_campos()
    assert c == {
        "icms": "12,00", "icms_incluso": "sim",
        "pis": "0,00", "pis_incluso": "Isento",
        "cofins": "0,00", "cofins_incluso": "Isento",
    }


def test_ipi_e_sempre_isento_nas_duas_contas():
    assert R.CAMPOS_FIXOS_ITEM["ipi"] == "0"
    assert R.CAMPOS_FIXOS_ITEM["ipi_incluso"] == "Isento"


# ------------------------------------------------------------------ formato
@pytest.mark.parametrize(
    "texto, valor",
    [("17", "17"), ("17,00", "17"), ("1.234,50", "1234.50"), ("0,65", "0.65"), ("", None), ("abc", None)],
)
def test_ler_decimal(texto, valor):
    assert R.ler_decimal(texto) == (Decimal(valor) if valor else None)


def test_ncm_aceita_com_ou_sem_pontos():
    assert R.formatar_ncm("84672992") == "8467.29.92"
    assert R.formatar_ncm("8467.29.92") == "8467.29.92"
    with pytest.raises(ValueError):
        R.formatar_ncm("8467.29")


# ------------------------------------------------ campos adicionais do item
def test_le_uf_origem_e_remessa_do_texto_real():
    p = R.ler_campos_adicionais(CAMPOS_ADICIONAIS_REAL)
    assert p == PedidoDoComprador("ES", 0, date(2026, 11, 2))


def test_texto_sem_endereco_nao_inventa_uf():
    assert R.ler_campos_adicionais("Origem do Material: 2").uf_destino is None


# ---------------------------------------------------------------- validação
def _item(**kw):
    base = dict(
        numero=10, preco="1500,00", ncm="8467.29.92", prazo_dias=30,
        marca="DJI", origem=0,
        pedido=R.ler_campos_adicionais(CAMPOS_ADICIONAIS_REAL),
    )
    base.update(kw)
    return EntradaItem(**base)


def test_item_completo_passa_sem_aviso():
    r = R.validar_item(_item(), HOJE)
    assert r.pode_salvar and r.avisos == []


def test_caso_real_45_dias_avisa_que_passa_da_remessa():
    r = R.validar_item(_item(prazo_dias=45), HOJE)
    assert r.pode_salvar
    assert any("09/11/2026" in a and "02/11/2026" in a for a in r.avisos)


@pytest.mark.parametrize(
    "mudanca, trecho",
    [
        (dict(preco="0"), "preço"),
        (dict(preco="abc"), "preço"),
        (dict(ncm="8467"), "NCM"),
        (dict(prazo_dias=None), "prazo"),
        (dict(origem=None), "origem"),
        (dict(origem=1), "origem 1"),
        (dict(pedido=PedidoDoComprador()), "UF"),
    ],
)
def test_erros_bloqueiam(mudanca, trecho):
    r = R.validar_item(_item(**mudanca), HOJE)
    assert not r.pode_salvar
    assert any(trecho in e for e in r.erros)


def test_origem_diferente_da_pedida_avisa():
    r = R.validar_item(_item(origem=2), HOJE)
    assert r.pode_salvar and any("pediu origem 0" in a for a in r.avisos)


def test_marca_acima_de_20_caracteres_bloqueia():
    # o campo Fabricante{N} do ME tem maxlength=20: cortaria calado
    r = R.validar_item(_item(marca="X" * 21), HOJE)
    assert not r.pode_salvar and any("20" in e for e in r.erros)
    assert R.validar_item(_item(marca="X" * 20), HOJE).pode_salvar


def test_ie_e_contato_nao_sao_fixos():
    # UNIÃO tem outra IE (083049428) e o ME já traz o contato de cada conta
    assert "inscricao_estadual" not in R.CAMPOS_FIXOS_COTACAO
    assert "nome_contato" not in R.CAMPOS_FIXOS_COTACAO


def test_tipo_de_imposto_do_item_e_ipi():
    # sem ele o ME recusa salvar: "Escolha um dos tipos de imposto IPI ou ISS"
    assert R.CAMPOS_FIXOS_ITEM["tipo_imposto"] == "IPI"


def test_marca_em_branco_so_avisa():
    r = R.validar_item(_item(marca=""), HOJE)
    assert r.pode_salvar and any("marca" in a for a in r.avisos)


def test_item_sem_preco_precisa_de_observacao():
    assert not R.validar_item(_item(preco="", obs=""), HOJE).pode_salvar
    assert R.validar_item(_item(preco="", obs="Não fornecemos este item"), HOJE).pode_salvar


def test_cotacao_precisa_de_validade_e_de_um_item_com_preco():
    sem_validade = R.validar_cotacao([_item()], None, HOJE)
    assert any("Validade" in e for e in sem_validade.erros)
    so_obs = R.validar_cotacao([_item(preco="", obs="não temos")], 10, HOJE)
    assert any("Nenhum item" in e for e in so_obs.erros)
    assert R.validar_cotacao([_item()], 10, HOJE).pode_salvar


def test_campos_do_item_juntam_fixos_impostos_e_usuario():
    c = R.campos_do_item(Conta.VENTURA, _item(prazo_dias=45), HOJE)
    assert c["icms"] == "17,00" and c["pis"] == "0,65"
    assert c["ipi_incluso"] == "Isento" and c["substituicao_tributaria"] == "NÃO"
    assert c["ncm"] == "8467.29.92" and c["preco"] == "1500,00"
    assert c["data_entrega"] == "09/11/2026"


# ------------------------------------------------- conferência pós-salvar
def test_conferencia_aceita_mesmo_numero_escrito_diferente():
    assert R.conferir({"icms": "17,00", "ncm": "8467.29.92"}, {"icms": "17", "ncm": "8467.29.92"}) == []


def test_conferencia_acusa_divergencia_e_campo_sumido():
    d = R.conferir(
        {"icms": "17,00", "marca": "DJI", "data_entrega": "09/11/2026"},
        {"icms": "12,00", "data_entrega": "10/11/2026"},
    )
    assert len(d) == 3
    assert any("icms" in x for x in d) and any("marca" in x for x in d)
