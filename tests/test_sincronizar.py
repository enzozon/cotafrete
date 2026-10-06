"""Sincronização de NF e ligação com o gerenciador (cruzar_nf/sincronizar.py, maestro.py)."""

from __future__ import annotations

import datetime as dt
import json
import threading

import pytest

from cruzar_nf import sincronizar as sync
from cruzar_nf.maestro import CAMPO_NF as CAMPO, aplicar_nfs, registrar

D = dt.date


class Manager:
    """Imita o planilha_manager do gerenciador (mesma interface)."""

    def __init__(self, pedidos, caminho, salvar_ok=True):
        self.lock = threading.RLock()
        self.pedidos = {"PEDIDOS": pedidos}
        self.caminho_pedidos = str(caminho)
        self.salvos = 0
        self.salvar_ok = salvar_ok
        caminho.write_text(json.dumps(self.pedidos), encoding="utf-8")

    def iniciar(self, *_):
        pass

    def salvar(self):
        self.salvos += 1
        return self.salvar_ok


class Sio:
    def __init__(self):
        self.handlers, self.emitidos = {}, []

    def on(self, evento, handler):
        self.handlers[evento] = handler

    def emit(self, evento, dados=None):
        self.emitidos.append((evento, dados))

    def ultimo(self, evento):
        return [d for e, d in self.emitidos if e == evento][-1]


class Log:
    def info(self, *_):
        pass

    error = info


class Agenda:
    def __init__(self):
        self.tarefas = []

    def every(self):
        return self

    @property
    def day(self):
        return self

    def at(self, horario):
        self.horario = horario
        return self

    def do(self, f):
        self.tarefas.append(f)


def ped(oc, valor=100, **extra):
    return {"PEDIDO": oc, "VALOR ": valor, **extra}


def venda(codigo, oc, nf, valor=100, emissao="15/09/2026", filial="VENTURA MATRIZ"):
    return {"Tipo": "VEN", "Código": codigo, "Emissão": emissao, "Ordem Compra": oc, "NF": nf,
            "Total Líq.": valor, "Filial": filial}


def excel_de(tmp_path, vendas, nome="hse.xlsx"):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    cab = ["Tipo", "Código", "Emissão", "Ordem Compra", "Total Líq.", "Filial", "NF"]
    ws.append([])
    ws.append([])
    ws.append([None] + cab)
    for v in vendas:
        ws.append([None] + [dt.datetime.strptime(v[c], "%d/%m/%Y") if c == "Emissão" else v[c] for c in cab])
    caminho = tmp_path / nome
    wb.save(caminho)
    return caminho


# -- aplicar_nfs ----------------------------------------------------------------

def test_aplicar_grava_so_nf_vazia_por_posicao_com_backup(tmp_path):
    pedidos = [ped(1), ped(2, **{CAMPO: "999"}), ped(1), ped(3)]
    m = Manager(pedidos, tmp_path / "PEDIDOS.json")
    rel, n = aplicar_nfs(m, [venda(10, 1, 15), venda(20, 2, 25)], gravar=True, dir_backup=str(tmp_path / "bk"))
    assert n == 2                                               # as duas linhas do pedido repetido
    assert [p.get(CAMPO) for p in pedidos] == ["15", "999", "15", None]
    assert m.salvos == 1
    assert len(list((tmp_path / "bk").glob("PEDIDOS antes da NF *.json"))) == 1


def test_aplicar_previa_nao_grava(tmp_path):
    pedidos = [ped(1)]
    m = Manager(pedidos, tmp_path / "PEDIDOS.json")
    _, n = aplicar_nfs(m, [venda(10, 1, 15)], gravar=False)
    assert n == 1 and CAMPO not in pedidos[0] and m.salvos == 0


def test_aplicar_sem_mudanca_nao_regrava(tmp_path):
    m = Manager([ped(1, **{CAMPO: "15"})], tmp_path / "PEDIDOS.json")
    _, n = aplicar_nfs(m, [venda(10, 1, 15)], gravar=True)
    assert n == 0 and m.salvos == 0


def test_aplicar_ignora_none_na_lista(tmp_path):
    m = Manager([None, ped(1)], tmp_path / "PEDIDOS.json")
    _, n = aplicar_nfs(m, [venda(10, 1, 15)], gravar=True)
    assert n == 1 and m.pedidos["PEDIDOS"][1][CAMPO] == "15"


def test_aplicar_reusa_o_campo_que_ja_existe_com_outro_espaco(tmp_path):
    m = Manager([ped(1, **{"Nº NOTA FISCAL ": ""})], tmp_path / "PEDIDOS.json")
    aplicar_nfs(m, [venda(10, 1, 15)], gravar=True)
    assert m.pedidos["PEDIDOS"][0] == {"PEDIDO": 1, "VALOR ": 100, "Nº NOTA FISCAL ": "15"}


def test_aplicar_mais_de_uma_nf_separada_por_barra(tmp_path):
    m = Manager([ped(1)], tmp_path / "PEDIDOS.json")
    aplicar_nfs(m, [venda(10, 1, 15), venda(11, 1, 16)], gravar=True)
    assert m.pedidos["PEDIDOS"][0][CAMPO] == "15 / 16"


def test_aplicar_grava_mesmo_com_valor_diferente(tmp_path):
    m = Manager([ped(1, valor=500)], tmp_path / "PEDIDOS.json")
    rel, n = aplicar_nfs(m, [venda(10, 1, 15, valor=100)], gravar=True)
    assert n == 1 and m.pedidos["PEDIDOS"][0][CAMPO] == "15"
    assert rel["resumo"]["divergencia_de_valor"] == 1


def test_aplicar_guarda_so_os_ultimos_backups(tmp_path):
    bk = tmp_path / "bk"
    bk.mkdir()
    for i in range(35):
        (bk / f"PEDIDOS antes da NF 2026-01-01_00-00-{i:02d}.json").write_text("{}")
    m = Manager([ped(1)], tmp_path / "PEDIDOS.json")
    aplicar_nfs(m, [venda(10, 1, 15)], gravar=True, dir_backup=str(bk))
    backups = sorted(p.name for p in bk.glob("PEDIDOS antes da NF *.json"))
    assert len(backups) == 30 and "2026-01-01_00-00-00" not in backups[0]


def test_aplicar_falha_ao_salvar_levanta(tmp_path):
    m = Manager([ped(1)], tmp_path / "PEDIDOS.json", salvar_ok=False)
    with pytest.raises(RuntimeError):
        aplicar_nfs(m, [venda(10, 1, 15)], gravar=True)


# -- janela ---------------------------------------------------------------------

def test_janela_sem_historico_e_30_dias(tmp_path):
    assert sync.janela(tmp_path, hoje=D(2026, 10, 1)) == (D(2026, 9, 1), D(2026, 10, 1))


def test_janela_padrao_e_ultima_menos_10_dias(tmp_path):
    (tmp_path / sync.ARQ_ESTADO).write_text(json.dumps({"cobertura": [["01/01/2025", "29/09/2026"]]}))
    assert sync.janela(tmp_path, hoje=D(2026, 10, 1)) == (D(2026, 9, 19), D(2026, 10, 1))


def test_janela_escolhida_aceita_dois_formatos(tmp_path):
    assert sync.janela(tmp_path, "2026-09-01", "30/09/2026") == (D(2026, 9, 1), D(2026, 9, 30))


def test_janela_invertida_ou_invalida(tmp_path):
    with pytest.raises(ValueError):
        sync.janela(tmp_path, "30/09/2026", "01/09/2026")
    with pytest.raises(ValueError):
        sync.janela(tmp_path, "ontem", None)


# -- sincronizar ----------------------------------------------------------------

def rodar(tmp_path, manager, vendas, de, ate, gravar=True, linhas_tela=None):
    arq = excel_de(tmp_path, vendas, nome=f"hse_{de:%Y%m%d}_{ate:%Y%m%d}.xlsx")
    msgs = []
    res = sync.sincronizar(tmp_path / "dados", manager, de, ate,
                           lambda _d, _a, _p: {"arquivo": arq, "linhas_tela": linhas_tela},
                           gravar=gravar, progresso=msgs.append)
    return res, msgs


def test_primeira_carga_e_incremental_usa_a_base_inteira(tmp_path):
    (tmp_path / "dados").mkdir()
    pedidos = [ped(1)]
    m = Manager(pedidos, tmp_path / "PEDIDOS.json")
    res, _ = rodar(tmp_path, m, [venda(10, 1, 15, emissao="10/01/2025")], D(2025, 1, 1), D(2026, 9, 29))
    assert res["nfs_gravadas"] == 1 and pedidos[0][CAMPO] == "15"

    # pedido novo na planilha, com venda ANTIGA (fora da janela incremental): tem que achar
    pedidos.append(ped(2))
    res, _ = rodar(tmp_path, m, [venda(30, 3, 35, emissao="25/09/2026")], D(2026, 9, 19), D(2026, 10, 1))
    assert res["nfs_gravadas"] == 0                               # o 2 não tem venda em lugar nenhum
    pedidos.append(ped(3))
    res, _ = rodar(tmp_path, m, [venda(30, 3, 35, emissao="25/09/2026")], D(2026, 9, 19), D(2026, 10, 1))
    assert res["nfs_gravadas"] == 1 and pedidos[2][CAMPO] == "35"

    estado = sync.carregar_estado(tmp_path / "dados")
    assert estado["cobertura"] == [["01/01/2025", "01/10/2026"]]
    assert estado["ultima"]["ate"] == "01/10/2026"
    assert len(estado["historico"]) == 3
    assert len(list((tmp_path / "dados" / sync.PASTA_HISTORICO).glob("vendas_hse *.xlsx"))) == 3


def test_pedido_novo_com_venda_antiga_da_base(tmp_path):
    (tmp_path / "dados").mkdir()
    pedidos = [ped(1)]
    m = Manager(pedidos, tmp_path / "PEDIDOS.json")
    rodar(tmp_path, m, [venda(10, 1, 15, emissao="10/01/2025"), venda(20, 2, 25, emissao="11/01/2025")],
          D(2025, 1, 1), D(2026, 9, 29))
    pedidos.append(ped(2))                                       # entrou na planilha depois
    res, _ = rodar(tmp_path, m, [], D(2026, 9, 19), D(2026, 10, 1))
    assert res["nfs_gravadas"] == 1 and pedidos[1][CAMPO] == "25"


def test_previa_nao_muda_a_ultima_sincronizacao(tmp_path):
    (tmp_path / "dados").mkdir()
    m = Manager([ped(1)], tmp_path / "PEDIDOS.json")
    res, _ = rodar(tmp_path, m, [venda(10, 1, 15)], D(2026, 9, 1), D(2026, 9, 30), gravar=False)
    assert res["nfs_a_gravar"] == 1 and res["nfs_gravadas"] == 0
    estado = sync.carregar_estado(tmp_path / "dados")
    assert estado["ultima"] is None and estado["historico"][0]["gravou"] is False


def test_aviso_quando_excel_e_tela_divergem(tmp_path):
    (tmp_path / "dados").mkdir()
    m = Manager([ped(1)], tmp_path / "PEDIDOS.json")
    res, msgs = rodar(tmp_path, m, [venda(10, 1, 15)], D(2026, 9, 1), D(2026, 9, 30), linhas_tela=3)
    assert "mostrou 3" in res["aviso"] and any("ATENÇÃO" in x for x in msgs)


def test_rodada_com_varios_excel(tmp_path):
    (tmp_path / "dados").mkdir()
    pedidos = [ped(1), ped(2)]
    m = Manager(pedidos, tmp_path / "PEDIDOS.json")
    jan = excel_de(tmp_path, [venda(10, 1, 15, emissao="10/01/2025")], nome="jan.xlsx")
    fev = excel_de(tmp_path, [venda(20, 2, 25, emissao="10/02/2025")], nome="fev.xlsx")
    res = sync.sincronizar(tmp_path / "dados", m, D(2025, 1, 1), D(2025, 2, 28),
                           lambda _d, _a, _p: {"arquivos": [jan, fev], "linhas_tela": 2}, progresso=lambda _m: None)
    assert res["nfs_gravadas"] == 2 and res["aviso"] is None
    assert [p[CAMPO] for p in pedidos] == ["15", "25"]
    assert len(list((tmp_path / "dados" / sync.PASTA_HISTORICO).glob("vendas_hse *.xlsx"))) == 2


def test_cli_le_as_pastas_do_ambiente_e_grava_com_seguranca(tmp_path, monkeypatch, capsys):
    arq = tmp_path / "PEDIDOS.json"
    arq.write_text(json.dumps({"PEDIDOS": [ped(1)]}), encoding="utf-8")
    xls = excel_de(tmp_path, [venda(10, 1, 15)])
    monkeypatch.setenv("SYNC_NF_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("SYNC_NF_PEDIDOS", str(arq))
    assert sync.main(["--excel", str(xls), "--de", "01/09/2026", "--gravar"]) == 0
    assert json.loads(arq.read_text(encoding="utf-8")) == {"PEDIDOS": [{"PEDIDO": 1, "VALOR ": 100, CAMPO: "15"}]}
    assert len(list((tmp_path / "dados" / "backups").glob("PEDIDOS antes da NF *.json"))) == 1


def test_arquivo_pedidos_le_e_grava_no_formato_do_maestro(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    arq.write_text(json.dumps({"PEDIDOS": [ped(1)]}), encoding="utf-8")
    m = sync.ArquivoPedidos(arq)
    _, n = aplicar_nfs(m, [venda(10, 1, 15)], gravar=True)
    assert n == 1
    assert json.loads(arq.read_text(encoding="utf-8")) == {"PEDIDOS": [{"PEDIDO": 1, "VALOR ": 100, CAMPO: "15"}]}


def test_cli_previa_com_excel(tmp_path, capsys):
    arq = tmp_path / "PEDIDOS.json"
    arq.write_text(json.dumps({"PEDIDOS": [ped(1)]}), encoding="utf-8")
    xls = excel_de(tmp_path, [venda(10, 1, 15)])
    (tmp_path / "dados").mkdir()
    assert sync.main(["--dados", str(tmp_path / "dados"), "--pedidos", str(arq), "--excel", str(xls),
                      "--de", "01/09/2026", "--ate", "30/09/2026"]) == 0
    assert '"nfs_a_gravar": 1' in capsys.readouterr().out
    assert CAMPO not in json.loads(arq.read_text(encoding="utf-8"))["PEDIDOS"][0]   # prévia


# -- registrar (gerenciador) ------------------------------------------------------

def montar(tmp_path, pedidos, vendas, falhar=False):
    (tmp_path / "dados").mkdir(exist_ok=True)
    arq = excel_de(tmp_path, vendas)

    def exportar(de, ate, progresso):
        if falhar:
            raise RuntimeError("HSE fora do ar")
        progresso("baixando")
        return {"arquivo": arq, "linhas_tela": len(vendas)}

    sio, agenda = Sio(), Agenda()
    m = Manager(pedidos, tmp_path / "PEDIDOS.json")
    h = registrar(sio, {"caminho_banco_dados": str(tmp_path / "dados"), "caminho_backups": str(tmp_path / "bk")},
                  Log(), manager=m, exportar=exportar, schedule=agenda, em_thread=False)
    return sio, agenda, m, h


def test_registra_os_comandos_e_o_agendamento(tmp_path):
    sio, agenda, _, _ = montar(tmp_path, [ped(1)], [venda(10, 1, 15)])
    assert set(sio.handlers) == {"comando_sync_nf_estado", "comando_sync_nf"}
    assert agenda.horario == "07:30" and len(agenda.tarefas) == 1


def test_comando_sincroniza_e_avisa_as_telas(tmp_path):
    pedidos = [ped(1)]
    sio, _, _, _ = montar(tmp_path, pedidos, [venda(10, 1, 15)])
    sio.handlers["comando_sync_nf"]({"clientId": "abc", "de": "01/09/2026", "ate": "30/09/2026"})
    r = sio.ultimo("retorno_sync_nf")
    assert r["sucesso"] and r["clientId"] == "abc" and r["resultado"]["nfs_gravadas"] == 1
    assert pedidos[0][CAMPO] == "15"
    assert ("planilha_atualizada", None) in sio.emitidos
    assert any(e == "progresso_sync_nf" and d["mensagem"] == "baixando" for e, d in sio.emitidos)


def test_comando_previa_nao_grava(tmp_path):
    pedidos = [ped(1)]
    sio, _, _, _ = montar(tmp_path, pedidos, [venda(10, 1, 15)])
    sio.handlers["comando_sync_nf"]({"clientId": "x", "de": "01/09/2026", "ate": "30/09/2026", "gravar": False})
    assert sio.ultimo("retorno_sync_nf")["resultado"]["nfs_a_gravar"] == 1 and CAMPO not in pedidos[0]
    assert ("planilha_atualizada", None) not in sio.emitidos


def test_falha_do_robo_vira_erro_e_fica_no_historico(tmp_path):
    sio, _, _, _ = montar(tmp_path, [ped(1)], [venda(10, 1, 15)], falhar=True)
    sio.handlers["comando_sync_nf"]({"clientId": "x", "de": "01/09/2026", "ate": "30/09/2026"})
    r = sio.ultimo("retorno_sync_nf")
    assert r["sucesso"] is False and "HSE fora do ar" in r["erro"]
    assert sync.carregar_estado(tmp_path / "dados")["historico"][0]["sucesso"] is False
    # e o próximo pode rodar (a trava foi liberada)
    sio.handlers["comando_sync_nf"]({"clientId": "x", "de": "01/09/2026", "ate": "30/09/2026"})
    assert "já existe" not in sio.ultimo("retorno_sync_nf").get("erro", "").lower()


def test_data_invalida_responde_erro(tmp_path):
    sio, _, _, _ = montar(tmp_path, [ped(1)], [venda(10, 1, 15)])
    sio.handlers["comando_sync_nf"]({"clientId": "x", "de": "30/09/2026", "ate": "01/09/2026"})
    assert "depois da final" in sio.ultimo("retorno_sync_nf")["erro"]


def test_estado_para_a_tela(tmp_path):
    sio, _, _, h = montar(tmp_path, [ped(1)], [venda(10, 1, 15)])
    sio.handlers["comando_sync_nf"]({"clientId": "x", "de": "01/09/2026", "ate": "30/09/2026"})
    h["estado"]({"clientId": "y"})
    r = sio.ultimo("retorno_sync_nf_estado")
    assert r["sucesso"] and r["clientId"] == "y"
    assert r["estado"]["ultima"]["ate"] == "30/09/2026" and r["estado"]["rodando"] is False
    assert r["estado"]["proxima_janela"]["de"] == "20/09/2026"


def test_agendado_usa_a_janela_padrao(tmp_path):
    pedidos = [ped(1)]
    sio, agenda, _, _ = montar(tmp_path, pedidos, [venda(10, 1, 15)])
    agenda.tarefas[0]()
    assert sio.ultimo("retorno_sync_nf")["resultado"]["origem"] == "agendado" and pedidos[0][CAMPO] == "15"
