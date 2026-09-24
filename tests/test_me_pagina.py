"""Leitura da página de resposta do ME, contra as cópias reais de 23/09/2026."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from mercado_eletronico import pagina as P

FIX = Path(__file__).resolve().parent / "fixtures" / "me_real"


def _ler(nome):
    return P.ler((FIX / f"{nome}.html").read_text(encoding="utf-8"))


def test_cabecalho_da_cotacao():
    p = _ler("23039029_p1")
    assert p.numero == 23039029
    assert p.titulo == "308-029226_00002"
    assert p.comprador == "Mayanna Cristina Goncalves de Aguirre"
    assert p.fornecedor == "VENTURA INFORMATICA LTDA"
    assert p.data_limite == datetime(2026, 9, 23, 21, 0)
    assert p.obs_comprador.startswith("Prezado Fornecedor")
    assert (p.pagina, p.paginas) == (1, [1, 2])


def test_item_com_tudo_que_a_tela_mostra():
    item = _ler("23039029_p1").itens[0]
    assert (item.indice, item.numero, item.produto_id) == (1, 10, "65342757")
    assert item.descricao == "POSTO DUPLO"
    assert (item.quantidade, item.unidade) == ("2,00", "UND")
    assert item.obs_comprador.startswith("Mesa 120x120x73cm")
    assert item.obs_comprador.endswith("ENTREGAR EM BSB")
    assert item.pedido.uf_destino == "ES"
    assert item.pedido.origem == 0
    assert item.pedido.data_remessa == date(2026, 11, 2)


def test_pagina_2_continua_a_numeracao():
    p = _ler("23039029_p2")
    assert p.pagina == 2
    assert [i.numero for i in p.itens] == list(range(110, 181, 10))
    assert [i.indice for i in p.itens] == list(range(1, 9))  # N recomeça na página


def test_juntar_as_paginas():
    tudo = P.juntar([_ler("23039029_p2"), _ler("23039029_p1")])
    assert [i.numero for i in tudo.itens] == list(range(10, 181, 10))
    assert tudo.pagina == 1


def test_ventura_entregando_em_mg():
    """A bateria de drone: VENTURA, mas entrega em MG — ICMS 12%, não 17%."""
    (item,) = _ler("23049227_p1").itens
    assert item.descricao.startswith("000000000000263252 - BATERIA")
    assert item.pedido.uf_destino == "MG"
    assert item.quantidade == "5,00"


def test_uniao():
    p = _ler("23052403_p1")
    assert p.fornecedor.startswith("UNIAO")
    assert p.data_limite == datetime(2026, 9, 28, 21, 0)
    assert [i.numero for i in p.itens] == [10, 20, 30]
    assert p.itens[0].quantidade == "1.000,00"
    assert {i.pedido.uf_destino for i in p.itens} == {"MG"}


def test_pagina_que_nao_e_de_resposta():
    with pytest.raises(ValueError):
        P.ler("<html><body>Ocorreu uma falha no sistema.</body></html>")
