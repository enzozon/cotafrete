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
    assert orc.ordem_compra == "OC-1"
    assert orc.observacoes == "Obs teste"


def test_planilha_antiga_com_local_de_entrega_pede_a_nova(tmp_path):
    # 10/11/2026: o Local de entrega saiu do modelo; quem manda a planilha antiga recebe só este aviso
    from orcamento.planilha import PLANILHA_ANTIGA
    assert "Planilha antiga" in PLANILHA_ANTIGA and "Baixar" in PLANILHA_ANTIGA
    for celulas in ({"A30": "Local de entrega"}, {"A30": "Local de entrega", "B30": "CENTRO", "B31": None}):
        assert erros(tmp_path, "valida", celulas) == PLANILHA_ANTIGA
    from orcamento.diagnostico import diagnostico   # não pode cair em "causa não identificada, procure o Enzo"
    d = diagnostico({"estado": "rejeitado", "erro": PLANILHA_ANTIGA}, administrador=False)
    assert d["origem"] == "planilha" and "modelo antigo" in d["motivo"] and "Baixe a planilha nova" in d["orientacao"]


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


def test_modelo_antigo_sem_linha_do_frete_ignora_b38(tmp_path):
    # DAVs 54, 57 e 59 (30/10/2026): no modelo anterior a linha 38 é "ITEM 1" e a B38 traz o produto
    orc = ler(tmp_path, "valida", {"A38": "ITEM 1", "B38": "Mousepad", "B32": None})
    assert orc.frete is None


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


def test_mesma_descricao_com_dados_diferentes_e_recusada(tmp_path):
    # Envio #85: duas peças com a mesma descrição viraram um produto só no HSE
    segunda = {"A4": "PRODUTO TESTE ROBO", "B4": 1, "C4": 0.10, "L4": "85359090", "M4": 0, "N4": 17}
    assert "Item 3: descrição deve ser diferente da do item 2" in erros(tmp_path, "completa", segunda)


def test_mesma_descricao_com_os_mesmos_dados_passa(tmp_path):
    repetida = {"A4": "produto  teste robo", "B4": 2, "C4": 45, "L4": "84716053", "M4": 0, "N4": 17}
    assert len(ler(tmp_path, "completa", repetida).itens) == 3


def test_descricao_igual_cai_na_coluna_o():
    from orcamento.diagnostico import diagnostico
    d = diagnostico({"estado": "rejeitado", "erro": "Item 3: descrição deve ser diferente da do item 2 "
                     "(mesma descrição com NCM, custo diferentes)"}, administrador=False)
    assert d["origem"] == "planilha" and d["campos"] == ["O4"]


def test_mesmo_codigo_em_duas_linhas_e_aceito(tmp_path):
    # O robô marca "Ins. individual" no HSE e cada linha vira um item (pedido 16669, 10/11/2026);
    # antes a planilha era recusada (envios #149 e #153)
    codigo = ler(tmp_path, "valida").itens[0].codigo
    for custo in (99, ler(tmp_path, "valida").itens[0].custo):  # com outro valor e com o mesmo valor
        orc = ler(tmp_path, "valida", {"A3": "outra linha", "B3": 5, "C3": custo, "K3": codigo})
        assert [it.codigo for it in orc.itens] == [codigo, codigo]


def test_codigo_repetido_cai_na_coluna_k():
    from orcamento.diagnostico import diagnostico
    # mensagem de processador._recusar_repetidos: uma linha tem o código e a outra chegou nele pela descrição
    d = diagnostico({"estado": "rejeitado", "erro": "Item 2: mesmo produto do item 1: preencha o CÓDIGO HSE "
                     "13370 nas duas linhas (o robô insere uma por uma) ou junte numa linha só"}, administrador=False)
    assert d["origem"] == "planilha" and d["campos"] == ["K3"]
