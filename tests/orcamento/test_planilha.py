from decimal import Decimal

import pytest

from orcamento.planilha import ErroPlanilha, ler_planilha, normalizar, observacoes_hse
from tests.orcamento.planilhas.gerar import VARIANTES, criar


def ler(tmp_path, variante: str, extra: dict | None = None):
    return ler_planilha(criar(tmp_path, {**VARIANTES[variante], **(extra or {})}))


def erros(tmp_path, variante: str, extra: dict | None = None) -> str:
    with pytest.raises(ErroPlanilha) as e:
        ler(tmp_path, variante, extra)
    return "\n".join(e.value.erros)


def test_normalizar():
    assert normalizar("  Mouse   Óptico ") == "MOUSE OPTICO"
    assert normalizar(None) == ""


def test_valida(tmp_path):
    orc = ler(tmp_path, "valida")
    assert len(orc.itens) == 1
    it = orc.itens[0]
    assert it.numero == 1
    assert it.codigo == "13370"
    assert it.quantidade == Decimal("1")
    assert it.valor_unit == Decimal("145.00")
    assert orc.cliente == "18373"
    assert orc.vendedor == "ELIZIANE AMORIM ROSA BARROS"
    assert orc.filial == 1
    assert orc.forma_pg is None
    assert orc.prazo_dias is None
    assert any("recalculado" in a for a in orc.avisos)


def test_completa(tmp_path):
    orc = ler(tmp_path, "completa")
    novo = orc.itens[1]
    assert novo.numero == 2
    assert novo.codigo is None
    assert novo.ncm == "84716053"
    assert novo.origem == 0
    assert novo.icms == Decimal("17")
    assert novo.descricao_cadastro == "PRODUTO TESTE ROBO"
    assert novo.grupo == "INFORMATICA" and novo.marca == "DELL"
    assert novo.valor_unit == Decimal("65.25")
    assert orc.forma_pg == "PX"
    assert orc.parcelamento == "30 DIAS"
    assert orc.prazo_dias == 10
    assert orc.filial == 2
    assert orc.local_entrega == "CENTRO"
    assert orc.ordem_compra == "OC-1"
    assert orc.observacoes == "Obs teste"


def test_valor_cacheado_usado(tmp_path):
    # J numérico (como se o Excel tivesse calculado) é usado sem aviso
    orc = ler(tmp_path, "valida", {"H2": 100, "I2": 145, "J2": 145.004})
    assert orc.itens[0].valor_unit == Decimal("145.00")
    assert orc.avisos == ()


def test_quantidade_e_frete_no_calculo(tmp_path):
    # H = 10*3 + 5+0+0 = 35 ; I = 35*1.45 = 50.75 ; J = 16.916.. → 16.92
    orc = ler(tmp_path, "valida", {"B2": 3, "C2": 10, "D2": 5})
    assert orc.itens[0].valor_unit == Decimal("16.92")


def test_descricao_cadastro_coluna_o(tmp_path):
    orc = ler(tmp_path, "completa", {"O3": "DESCRICAO CADASTRO"})
    assert orc.itens[1].descricao_cadastro == "DESCRICAO CADASTRO"


def test_icms_percentual_formatado(tmp_path):
    orc = ler(tmp_path, "completa", {"N3": 0.12})
    assert orc.itens[1].icms == Decimal("12")


def test_sem_cliente(tmp_path):
    assert "Cliente" in erros(tmp_path, "sem_cliente")


def test_sem_vendedor(tmp_path):
    assert "VENDEDOR" in erros(tmp_path, "sem_vendedor")


def test_sem_itens(tmp_path):
    assert "nenhum item" in erros(tmp_path, "sem_itens")


def test_valor_zero(tmp_path):
    assert "Item 2: valor unitário" in erros(tmp_path, "valor_zero")


def test_quantidade_invalida(tmp_path):
    assert "Item 2: quantidade" in erros(tmp_path, "quantidade_invalida")


def test_quantidade_zero(tmp_path):
    assert "Item 1: quantidade" in erros(tmp_path, "valida", {"B2": 0})


def test_obs_longa(tmp_path):
    assert "1024" in erros(tmp_path, "obs_longa")


def test_filial_invalida(tmp_path):
    assert "Filial" in erros(tmp_path, "filial_invalida")


def test_pagamento_invalido(tmp_path):
    assert "Forma de pagamento" in erros(tmp_path, "pagamento_invalido")


def test_pagamento_por_codigo(tmp_path):
    assert ler(tmp_path, "valida", {"B34": "bo"}).forma_pg == "BO"


def test_origem_invalida(tmp_path):
    assert "Item 2: ORIGEM" in erros(tmp_path, "completa", {"M3": 9})


def test_ncm_invalido(tmp_path):
    assert "Item 2: NCM" in erros(tmp_path, "completa", {"L3": "8471"})


def test_com_codigo_ignora_l_a_q(tmp_path):
    it = ler(tmp_path, "valida", {"L2": "123", "M2": 99, "N2": "x", "P2": "G"}).itens[0]
    assert it.ncm is None and it.grupo is None


def test_ncm_com_pontos(tmp_path):
    assert ler(tmp_path, "completa", {"L3": "8471.60.53"}).itens[1].ncm == "84716053"


def test_prazo_invalido(tmp_path):
    assert "Prazo" in erros(tmp_path, "valida", {"B32": "amanhã"})


def test_erros_acumulados(tmp_path):
    texto = erros(tmp_path, "valida", {"B31": None, "B33": None, "B2": 0})
    assert "Cliente" in texto and "VENDEDOR" in texto and "Item 1: quantidade" in texto


def test_cliente_cnpj_texto(tmp_path):
    assert ler(tmp_path, "valida", {"B31": " 12.345.678/0001-90 "}).cliente == "12.345.678/0001-90"


def test_texto_com_ponto_de_milhar(tmp_path):
    # "1.500" digitado como texto é mil e quinhentos, não 1,5
    orc = ler(tmp_path, "valida", {"C2": "1.500"})
    assert orc.itens[0].custo == Decimal("1500")
    assert orc.itens[0].valor_unit == Decimal("2175.00")
    assert ler(tmp_path, "valida", {"C2": "12.5"}).itens[0].custo == Decimal("12.5")


def test_codigo_float_vira_inteiro(tmp_path):
    assert ler(tmp_path, "valida", {"K2": 13370.0}).itens[0].codigo == "13370"


# --- frete (B38) e descrição por item (coluna R) ---

def test_sem_frete_observacoes_ficam_iguais(tmp_path):
    orc = ler(tmp_path, "valida", {"B26": "Obs do vendedor"})
    assert orc.frete is None
    assert observacoes_hse(orc) == "Obs do vendedor"


def test_frete_vai_numa_linha_depois_das_observacoes(tmp_path):
    orc = ler(tmp_path, "valida", {"B26": "Obs do vendedor", "B32": 30, "B38": "CIF"})
    assert orc.frete == "CIF"
    assert observacoes_hse(orc) == "Obs do vendedor\nFRETE CIF, PRAZO DE ENTREGA 30 DIAS"


def test_frete_sem_observacoes_e_um_dia(tmp_path):
    orc = ler(tmp_path, "valida", {"B32": 1, "B38": " fob "})
    assert observacoes_hse(orc) == "FRETE FOB, PRAZO DE ENTREGA 1 DIA"


@pytest.mark.parametrize("prazo", [None, 0])
def test_frete_exige_prazo(tmp_path, prazo):
    assert "Prazo de entrega (B32) é obrigatório quando o FRETE" in erros(
        tmp_path, "valida", {"B32": prazo, "B38": "CIF"})


def test_frete_invalido(tmp_path):
    assert "FRETE (B38)" in erros(tmp_path, "valida", {"B32": 5, "B38": "CFI"})


def test_prazo_zero_sem_frete_continua_valido(tmp_path):
    assert ler(tmp_path, "valida", {"B32": 0}).prazo_dias == 0


def test_observacoes_com_frete_respeitam_1024(tmp_path):
    linha = "\nFRETE CIF, PRAZO DE ENTREGA 30 DIAS"
    assert ler(tmp_path, "valida", {"B26": "x" * (1024 - len(linha)), "B32": 30, "B38": "CIF"})
    texto = erros(tmp_path, "valida", {"B26": "x" * (1025 - len(linha)), "B32": 30, "B38": "CIF"})
    assert "OBSERVAÇÕES" in texto and "1025" in texto


def test_descricao_do_item(tmp_path):
    orc = ler(tmp_path, "completa", {"R2": "  Cor preta  ", "R3": "220V\n  Inox\r\nGarantia"})
    assert [i.descricao for i in orc.itens] == ["Cor preta", "220V Inox Garantia"]


def test_descricao_vazia(tmp_path):
    assert ler(tmp_path, "valida").itens[0].descricao == ""


def test_descricao_maximo_512(tmp_path):
    assert len(ler(tmp_path, "valida", {"R2": "x" * 512}).itens[0].descricao) == 512
    assert "Item 1: DESCRIÇÃO NO DAV com 513 caracteres (máximo 512)" in erros(
        tmp_path, "valida", {"R2": "x" * 513})
