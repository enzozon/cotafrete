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

    def buscar(cliente, data, perto_de, quando):
        chamadas.append((cliente, data, perto_de, quando))
        return [{"numero": 16533, "cliente": "1061", "data": "04/11/2026",
                 "itens": [{"codigo": "76817", "qtd": 3, "valor": 2.5}]}]

    p = coletar(_dav(), tmp_path, buscar)
    assert p["criados_no_hse"] == [16533]
    assert chamadas == [("1061", "04/11/2026", None, "2026-11-04T10:00:00")]
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


_PRONTOS = [("2026-11-04T09:28:53", 16504), ("2026-11-04T16:15:30", 16541)]


def test_faixa_com_numeros_reais_acha_16530_a_16536():
    from orcamento.provas import MAX_PAGINAS, faixa_de_busca
    f = faixa_de_busca(_PRONTOS, "2026-11-04T14:55:09")
    assert all(n in f for n in range(16530, 16537)) and len(f) <= MAX_PAGINAS == 60


def test_faixa_um_lado_so_dois_margens_em_volta():
    from orcamento.provas import MARGEM, faixa_de_busca
    f = faixa_de_busca(_PRONTOS[:1], "2026-11-04T14:55:09", teto=None)
    assert f == range(16504 - 2 * MARGEM, 16504 + 2 * MARGEM + 1)
    f = faixa_de_busca(_PRONTOS[1:], "2026-11-04T08:00:00", teto=None)
    assert f == range(16541 - 2 * MARGEM, 16541 + 2 * MARGEM + 1)


def test_faixa_dos_dois_lados_inteira():
    from orcamento.provas import MARGEM, faixa_de_busca
    f = faixa_de_busca([("2026-11-04T09:00:00", 100), ("2026-11-04T10:00:00", 110),
                        ("2026-11-04T16:00:00", 120)], "2026-11-04T12:00:00")
    assert f == range(110 - 5, 120 + MARGEM + 1)


def test_buscador_usa_hora_do_envio():
    from orcamento.provas import buscador_hse

    class Hse:
        def ler_pedido(self, n):
            return {"numero": n, "cliente": "1061", "data": "04/11/2026", "itens": []} if 16530 <= n <= 16536 else None
    achados = buscador_hse(Hse(), _PRONTOS)("1061", "04/11/2026", None, "2026-11-04T14:55:09")
    assert [p["numero"] for p in achados] == list(range(16530, 16537))


def _so_um_pedido(n, codigo="76817"):
    class Hse:
        def ler_pedido(self, x):
            return ({"numero": x, "cliente": "1061", "data": "04/11/2026",
                     "itens": [{"codigo": codigo, "qtd": "3", "valor": "2,500000"}]} if x == n else None)
    return Hse()


def test_faixa_cortada_sem_achado_fica_nao_verificado(tmp_path):
    from orcamento.provas import buscador_hse
    _planilha(tmp_path)
    numeros = [("2026-11-04T09:00:00", 16000), ("2026-11-04T16:00:00", 16500)]
    p = coletar(_dav(iniciado_em="2026-11-04T12:00:00"), tmp_path, buscador_hse(_so_um_pedido(16400), numeros))
    assert p["criados_no_hse"] == NAO_VERIFICADO and "cortada" in p["motivo_nao_verificado"]


def test_faixa_cortada_com_achado_lista_e_avisa(tmp_path):
    from orcamento.provas import buscador_hse
    _planilha(tmp_path)
    numeros = [("2026-11-04T09:00:00", 16000), ("2026-11-04T16:00:00", 16500)]
    p = coletar(_dav(iniciado_em="2026-11-04T12:00:00"), tmp_path, buscador_hse(_so_um_pedido(16003), numeros))
    assert p["criados_no_hse"] == [16003] and "cortada" in p["motivo_nao_verificado"]


def test_sem_referencia_de_numero_fica_nao_verificado(tmp_path):
    from orcamento.provas import buscador_hse
    _planilha(tmp_path)
    p = coletar(_dav(), tmp_path, buscador_hse(_so_um_pedido(1), []))
    assert p["criados_no_hse"] == NAO_VERIFICADO and p["motivo_nao_verificado"] == "sem referência de número"


def test_numero_do_envio_em_texto_centra_a_busca(tmp_path):
    vistos = []
    coletar(_dav(numero="16540"), tmp_path, lambda c, d, perto, q: vistos.append(perto) or [])
    assert vistos == [16540]


def _ped(numero, codigos, valor="2,500000"):
    return {"numero": numero, "cliente": "1061", "data": "04/11/2026",
            "itens": [{"codigo": c, "qtd": "1", "valor": valor} for c in codigos]}


def test_ignora_numero_de_outro_dav():
    assert pedidos_do_envio([_ped(16402, ["76817"])], "1061", "04/11/2026", {"76817"}, ignorar={16402}) == []


def test_pedido_de_outro_assunto_nao_casa():
    assert pedidos_do_envio([_ped(1, ["76817", "99999"])], "1061", "04/11/2026", {"76817"}) == []


def test_pedido_parcial_do_robo_casa():
    assert pedidos_do_envio([_ped(1, ["1"])], "1061", "04/11/2026", {"1", "2"}) == [1]


def test_valor_diferente_nao_casa():
    from decimal import Decimal
    pedidos = [_ped(1, ["76817"], "8.300,940000")]
    assert pedidos_do_envio(pedidos, "1061", "04/11/2026", {"76817"}, valores={"76817": "8000,00"}) == []
    assert pedidos_do_envio(pedidos, "1061", "04/11/2026", {"76817"}, valores={"76817": "8300,94"}) == [1]
    assert pedidos_do_envio(pedidos, "1061", "04/11/2026", {"76817"}, valores={"76817": Decimal("8300.94")}) == [1]


def test_coletar_repassa_ignorar(tmp_path):
    _planilha(tmp_path)
    p = coletar(_dav(), tmp_path, lambda *a: [_ped(16402, ["76817"])], ignorar={16402})
    assert p["criados_no_hse"] == []


def test_coletar_compara_valor_da_planilha(tmp_path):
    _planilha(tmp_path)  # J2 = 2.5
    assert coletar(_dav(), tmp_path, lambda *a: [_ped(1, ["76817"], "9,000000")])["criados_no_hse"] == NAO_VERIFICADO
    assert coletar(_dav(), tmp_path, lambda *a: [_ped(1, ["76817"], "2,500000")])["criados_no_hse"] == [1]


def test_produto_achado_pela_descricao_conta_como_do_envio(tmp_path):
    # item sem código K na planilha: o robô achou 55555 pela descrição; o pedido parcial é do envio
    _planilha(tmp_path)
    rel = RELATORIO + "\nItem 2: usou produto existente 55555 - cabo (encontrado pela descrição)"
    p = coletar(_dav(relatorio=rel), tmp_path, lambda *a: [_ped(16533, ["76817", "55555"])])
    assert p["criados_no_hse"] == [16533]


def test_rascunho_do_relatorio_entra(tmp_path):
    p = coletar(_dav(erro="falha; o rascunho 16492 pode ter ficado com itens"), tmp_path, lambda *a: [])
    assert 16492 in p["criados_no_hse"] and p["rascunhos"] == [16492]


def test_rascunho_nao_duplica(tmp_path):
    _planilha(tmp_path)
    p = coletar(_dav(erro="rascunho 16533 ficou vazio"), tmp_path, lambda *a: [_ped(16533, ["76817"])])
    assert p["criados_no_hse"] == [16533]


def test_produtos_criados_do_relatorio(tmp_path):
    rel = (RELATORIO + "\nProdutos cadastrados no HSE (continuam lá): "
           "76811 - terminal pin tub compr phoenix /3200991")
    assert coletar(_dav(relatorio=rel), tmp_path, lambda *a: [])["produtos_criados"] == [
        "76811 - terminal pin tub compr phoenix /3200991"]


def test_produtos_criados_da_linha_cadastrou(tmp_path):
    rel = (RELATORIO + "\nItem 1: CADASTROU produto novo 76811 - terminal | NCM 1 | Origem 0"
           "\nItem 2: CADASTROU produto novo 76812 - luva | NCM 2"
           "\nProdutos cadastrados no HSE (continuam lá): 76811 - terminal; 76812 - luva")
    assert coletar(_dav(relatorio=rel), tmp_path, None)["produtos_criados"] == ["76811 - terminal", "76812 - luva"]


def test_nao_verificado_continua_quando_hse_cai(tmp_path):
    def buscar(*a):
        raise HseIndisponivel("fora")
    p = coletar(_dav(erro="o rascunho 16492 pode ter ficado"), tmp_path, buscar)
    assert p["criados_no_hse"] == NAO_VERIFICADO and p["rascunhos"] == [16492]


def _planilha_b31(pasta, b31):
    _planilha(pasta)
    wb = openpyxl.load_workbook(pasta / "entrada" / "7.xlsx")
    wb["ORÇAMENTO"]["B31"] = b31
    wb.save(pasta / "entrada" / "7.xlsx")


@pytest.mark.parametrize("b31, ok", [("11.200.594/0001-45", False), ("39.787.056/0012-26", True),
                                      ("11111111111111", False)])
def test_cnpj_valido_e_invalido(tmp_path, b31, ok):
    _planilha_b31(tmp_path, b31)
    assert coletar(_dav(estado="pronto"), tmp_path, None)["cliente_b31"] == {"valor": b31, "cnpj_valido": ok}


def test_codigo_curto_sem_validacao(tmp_path):
    _planilha_b31(tmp_path, "1061")
    assert coletar(_dav(estado="pronto"), tmp_path, None)["cliente_b31"] == {"valor": "1061", "cnpj_valido": None}


def test_envio_anterior_traz_linhas_do_robo(tmp_path):
    origem = {"id": 5, "estado": "erro", "erro": "recusado",
              "relatorio": "Cliente: 1061\nItem 1: CADASTROU produto novo 76811 - terminal | NCM 1"
                           "\nItem 2: usou produto existente 76811 - terminal (cadastrado no item 1)\nfim"}
    p = coletar(_dav(estado="pronto"), tmp_path, None, anterior=origem)
    assert p["envio_anterior"] == {"id": 5, "estado": "erro", "erro": "recusado", "linhas": [
        "Item 1: CADASTROU produto novo 76811 - terminal | NCM 1",
        "Item 2: usou produto existente 76811 - terminal (cadastrado no item 1)"]}
    assert coletar(_dav(estado="pronto"), tmp_path, None)["envio_anterior"] is None


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
    achados = buscador_hse(h, _PRONTOS)("1061", "04/11/2026", 16540, "2026-11-04T14:55:09")
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


def test_sem_codigos_com_pedidos_do_cliente_fica_nao_verificado(tmp_path):
    p = coletar(_dav(), tmp_path, lambda *a: [_ped(16533, ["76817"])])  # sem planilha guardada
    assert p["criados_no_hse"] == NAO_VERIFICADO and "códigos" in p["motivo_nao_verificado"]


# --- rodada de correção 1 ---

def test_valor_com_tolerancia_de_um_centavo():
    pedidos = [_ped(1, ["76817"], "2,350000")]
    assert pedidos_do_envio(pedidos, "1061", "04/11/2026", {"76817"}, valores={"76817": "2.345"}) == [1]


def test_preco_diferente_vira_nao_verificado_nunca_vazio(tmp_path):
    _planilha(tmp_path)  # J2 = 2.5
    p = coletar(_dav(), tmp_path, lambda *a: [_ped(16533, ["76817"], "9,000000")])
    assert p["criados_no_hse"] == NAO_VERIFICADO
    assert p["motivo_nao_verificado"] == "pedido 16533 do cliente com preço diferente; confira no HSE"


def test_mesmo_codigo_com_dois_precos_casa_qualquer_um(tmp_path):
    _planilha(tmp_path)
    wb = openpyxl.load_workbook(tmp_path / "entrada" / "7.xlsx")
    ws = wb["ORÇAMENTO"]
    ws["A3"], ws["B3"], ws["C3"], ws["J3"], ws["K3"] = "Parafuso", 1, 1, 7.0, 76817
    wb.save(tmp_path / "entrada" / "7.xlsx")
    assert coletar(_dav(), tmp_path, lambda *a: [_ped(1, ["76817"], "2,500000")])["criados_no_hse"] == [1]
    assert pedidos_do_envio([_ped(1, ["76817"], "2,500000")], "1061", "04/11/2026", {"76817"},
                            valores={"76817": {"7", "2.5"}}) == [1]


def test_pedido_sem_itens_do_cliente_vira_nao_verificado(tmp_path):
    _planilha(tmp_path)
    p = coletar(_dav(), tmp_path, lambda *a: [_ped(16533, [])])
    assert p["criados_no_hse"] == NAO_VERIFICADO
    assert p["motivo_nao_verificado"] == "pedido 16533 sem itens do cliente no dia"


def test_pedido_sem_itens_ignorado_continua_vazio(tmp_path):
    _planilha(tmp_path)
    assert coletar(_dav(), tmp_path, lambda *a: [_ped(16533, [])], ignorar={16533})["criados_no_hse"] == []


def test_faixa_aceita_hora_com_espaco():
    from orcamento.provas import faixa_de_busca
    f = faixa_de_busca([("2026-11-04 09:28:53", 16504), ("2026-11-04 16:15:30", 16541)], "2026-11-04T14:55:09")
    assert f == faixa_de_busca(_PRONTOS, "2026-11-04 14:55:09") == range(16499, 16559)


def test_busca_para_no_prazo_e_avisa():
    from orcamento.provas import buscador_hse

    class Relogio:
        t = 0.0

        def __call__(self):
            return self.t

    relogio, lidos = Relogio(), []

    class Hse:
        def ler_pedido(self, n):
            lidos.append(n)
            relogio.t += 10
            return {"numero": n, "cliente": "1061", "data": "04/11/2026", "itens": []} if n == 16505 else None
    achados = buscador_hse(Hse(), _PRONTOS, limite_s=35, relogio=relogio)("1061", "04/11/2026", 16530, None)
    assert len(lidos) == 4 and [p["numero"] for p in achados] == [16505]
    assert "busca cortada por tempo" in achados.aviso
