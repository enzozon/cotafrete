"""Coleta de provas do diagnóstico do DAV (sem HSE)."""

import openpyxl
import pytest

from orcamento.processador import HseIndisponivel
from orcamento.provas import NAO_VERIFICADO, coletar, pedidos_do_envio

RELATORIO = "Cliente: 1061 - VALE S/A/VALE S.A. (33592510022042)\nItens: 1"


def _dav(**kw):
    d = {"id": 7, "usuario": "ana", "arquivo": "p.xlsx", "estado": "erro", "erro": "boom",
         "relatorio": RELATORIO, "conferencia": None, "conferencia_relatorio": None,
         "numero": None, "criado_em": "2026-11-03T09:00:00",
         "iniciado_em": "2026-11-04T10:00:00", "terminado_em": None}
    d.update(kw)
    return d


def _planilha(pasta, i=7):
    (pasta / "entrada").mkdir(exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ORÇAMENTO"
    ws["A2"], ws["B2"], ws["C2"], ws["J2"], ws["K2"] = "Parafuso", 3, 1, 2.5, 76817
    ws["B31"], ws["B33"] = "VALE", "ana"
    wb.save(pasta / "entrada" / f"{i}.xlsx")


def test_pedidos_do_envio_casa_cliente_data_e_codigo():
    pedidos = [
        {"numero": 1, "cliente": "1061", "data": "04/11/2026", "itens": [{"codigo": "76817"}]},
        {"numero": 2, "cliente": "999", "data": "04/11/2026", "itens": [{"codigo": "76817"}]},
        {"numero": 3, "cliente": "1061", "data": "04/11/2026", "itens": [{"codigo": "1"}]},
    ]
    assert pedidos_do_envio(pedidos, "1061", "04/11/2026", {"76817"}) == [1]


def test_coletar_erro_com_pedido_criado(tmp_path):
    _planilha(tmp_path)
    chamadas = []

    def buscar(cliente, data, perto_de):
        chamadas.append((cliente, data, perto_de))
        return [{"numero": 16533, "cliente": "1061", "data": "04/11/2026",
                 "itens": [{"codigo": "76817", "qtd": 3, "valor": 2.5}]}]

    p = coletar(_dav(), tmp_path, buscar)
    assert p["criados_no_hse"] == [16533]
    assert chamadas == [("1061", "04/11/2026", None)]
    assert p["planilha"]["itens"][0]["codigo"] == "76817"
    assert p["envio"]["vendedor"] == "ana"


def test_hse_fora_fica_nao_verificado(tmp_path):
    def buscar(*a):
        raise HseIndisponivel("fora")
    p = coletar(_dav(), tmp_path, buscar)
    assert p["criados_no_hse"] == NAO_VERIFICADO
    assert "HSE" in p["motivo_nao_verificado"]


def test_recusa_nao_busca_no_hse(tmp_path):
    def buscar(*a):
        raise AssertionError("não devia buscar")
    assert coletar(_dav(estado="rejeitado"), tmp_path, buscar)["criados_no_hse"] == []


def test_sem_planilha_guardada(tmp_path):
    assert coletar(_dav(estado="pronto"), tmp_path, None)["planilha"] is None


def test_mensagens_e_print_do_envio(tmp_path):
    (tmp_path / "respostas_hse").mkdir()
    (tmp_path / "prints_hse").mkdir()
    (tmp_path / "respostas_hse" / "7_x_1.html").write_text(
        "<script>toastSuccess('Margem atualizada')</script>", encoding="utf-8")
    (tmp_path / "respostas_hse" / "17_x_1.html").write_text(
        "<script>alert('outro')</script>", encoding="utf-8")
    for n in ("7_a.png", "7_b.png", "17_c.png"):
        (tmp_path / "prints_hse" / n).write_bytes(b"x")
    p = coletar(_dav(estado="pronto"), tmp_path, None)
    assert p["mensagens_hse"] == ["Margem atualizada"]
    assert p["print"].endswith("7_b.png")
