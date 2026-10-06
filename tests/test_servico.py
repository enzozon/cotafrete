"""Serviço de NF separado do gerenciador (cruzar_nf/servico.py) — caminho B."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from cruzar_nf import servico
from cruzar_nf.maestro import CAMPO_NF as CAMPO
from cruzar_nf import sincronizar as sync


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
    def __init__(self):
        self.linhas = []

    def info(self, m):
        self.linhas.append(m)

    warning = error = info


class Agenda:
    def __init__(self):
        self.tarefas, self.horario = [], None

    def every(self):
        return self

    @property
    def day(self):
        return self

    def at(self, h):
        self.horario = h
        return self

    def do(self, f):
        self.tarefas.append(f)


def test_config_exige_o_token():
    with pytest.raises(servico.ConfigInvalida):
        servico.config_do_ambiente({})


def test_config_padrao_e_do_ambiente():
    c = servico.config_do_ambiente({"SYNC_NF_TOKEN": " abc "})
    assert c["token"] == "abc" and c["url"] == servico.URL_PADRAO
    assert c["caminho_pedidos"].endswith("PEDIDOS.json") and c["horario"] == "07:30"
    c = servico.config_do_ambiente({"SYNC_NF_TOKEN": "x", "SYNC_NF_DADOS": "C:/dados",
                                    "URL_SERVIDOR": "http://localhost:8000", "SYNC_NF_HORARIO": ""})
    assert c["caminho_banco_dados"] == "C:/dados" and c["url"] == "http://localhost:8000" and c["horario"] == ""


def montar(tmp_path, horario="07:30", vendas=None):
    dados = tmp_path / "dados"
    dados.mkdir()
    (dados / "PEDIDOS.json").write_text(json.dumps({"PEDIDOS": [{"PEDIDO": 1, "VALOR ": 100}]}), encoding="utf-8")
    config = servico.config_do_ambiente({"SYNC_NF_TOKEN": "segredo", "SYNC_NF_DADOS": str(dados),
                                         "SYNC_NF_BACKUPS": str(tmp_path / "bk"), "SYNC_NF_HORARIO": horario})
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([])
    ws.append([])
    ws.append([None, "Tipo", "Código", "Emissão", "Ordem Compra", "Total Líq.", "Filial", "NF"])
    for v in (vendas or [("VEN", 10, dt.datetime(2026, 9, 15), 1, 100, "VENTURA MATRIZ", 15)]):
        ws.append([None, *v])
    xls = tmp_path / "hse.xlsx"
    wb.save(xls)
    sio, agenda, log = Sio(), Agenda(), Log()
    h = servico.montar(sio, config, log, schedule=agenda,
                       exportar=lambda de, ate, p: {"arquivo": str(xls), "linhas_tela": 1}, em_thread=False)
    return sio, agenda, log, h, dados


def test_identifica_com_o_token_ao_conectar(tmp_path):
    sio, _, _, h, _ = montar(tmp_path)
    h["connect"]()
    assert sio.ultimo("sou_o_sync_nf") == {"token": "segredo"}


def test_registra_os_comandos_e_a_rodada_diaria(tmp_path):
    sio, agenda, _, _, _ = montar(tmp_path)
    assert {"connect", "disconnect", "sync_nf_recusado", "comando_sync_nf", "comando_sync_nf_estado"} <= set(sio.handlers)
    assert agenda.horario == "07:30" and len(agenda.tarefas) == 1


def test_sem_horario_nao_agenda(tmp_path):
    _, agenda, _, _, _ = montar(tmp_path, horario="")
    assert agenda.tarefas == []


def test_recusa_vai_para_o_log(tmp_path):
    sio, _, log, _, _ = montar(tmp_path)
    sio.handlers["sync_nf_recusado"]({})
    assert any("SYNC_NF_TOKEN" in l for l in log.linhas)


def test_comando_do_portal_grava_a_nf_no_arquivo(tmp_path):
    sio, _, _, _, dados = montar(tmp_path)
    sio.handlers["comando_sync_nf"]({"clientId": "tela1", "de": "01/09/2026", "ate": "30/09/2026"})
    r = sio.ultimo("retorno_sync_nf")
    assert r["sucesso"] and r["resultado"]["nfs_gravadas"] == 1, r
    assert json.loads((dados / "PEDIDOS.json").read_text(encoding="utf-8"))["PEDIDOS"][0][CAMPO] == "15"
    assert ("planilha_atualizada", None) in sio.emitidos
    assert sync.carregar_estado(dados)["ultima"]["nfs_gravadas"] == 1
    assert len(list((tmp_path / "bk").glob("PEDIDOS antes da NF *.json"))) == 1
