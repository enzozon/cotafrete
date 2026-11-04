"""Coleta de provas do diagnóstico do DAV (sem HSE)."""

from pathlib import Path

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


_PRONTOS = [("2026-11-04T09:28:00", 16504), ("2026-11-04T16:15:00", 16541)]


def test_faixa_pelo_pronto_mais_proximo():
    from orcamento.provas import faixa_de_busca
    f = faixa_de_busca(_PRONTOS, "2026-11-04T14:55:00")
    assert len(f) == 51 and all(n in f for n in range(16533, 16537))


def test_faixa_sem_prontos_vazia():
    from orcamento.provas import faixa_de_busca
    assert len(faixa_de_busca([], "2026-11-04T14:55:00")) == 0


def test_buscador_filtra_cliente_data_e_pula_inexistentes():
    from orcamento.provas import buscador_hse

    class Hse:
        lidos = []

        def ler_pedido(self, n):
            self.lidos.append(n)
            if n == 16535:
                return None
            return {"numero": n, "cliente": "1061" if n % 2 else "9", "data": "04/11/2026", "itens": []}
    h = Hse()
    achados = buscador_hse(h, _PRONTOS)("1061", "04/11/2026", 16540)
    assert h.lidos[0] == 16515 and h.lidos[-1] == 16565  # centrado no número do próprio envio
    assert 16535 not in [p["numero"] for p in achados] and 16537 in [p["numero"] for p in achados]
    assert all(p["cliente"] == "1061" for p in achados)


def test_celula_numerica_inteira_vira_texto_sem_ponto_zero():
    from orcamento.provas import _texto
    assert _texto(76817.0) == "76817" and _texto(2.5) == "2.5" and _texto(None) is None


def test_data_do_envio_ilegivel_nao_derruba():
    r = coletar(_dav(iniciado_em="04/11/2026 10:00"), Path("."), lambda *a: [])
    assert r["criados_no_hse"] == NAO_VERIFICADO and r["motivo_nao_verificado"]


def test_conferencia_corrompida_vira_none():
    assert coletar(_dav(conferencia_relatorio="{quebrado"), Path("."), None)["conferencia"] is None
