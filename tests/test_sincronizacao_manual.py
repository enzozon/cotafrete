"""Botões do dashboard do admin pelo serviço de NF (maestro.py): "NF completo" (HSE -> portal -> planilha)
e "Sync planilha ⇄ portal" na hora, mesmo depois da rodada do dia. Arquivos sintéticos, nunca produção."""

from __future__ import annotations

import datetime as dt
import json

import openpyxl

from cruzar_nf import sync_planilha_portal as SP
from cruzar_nf.arquivo_pedidos import ArquivoPedidosConcorrente
from cruzar_nf.maestro import registrar
from cruzar_nf.sincronizar import trava
from tests.test_nf_planilha import Cenario, lin, ped
from tests.test_sincronizar import Log, Sio, excel_de, venda
from tests.test_sync_planilha_portal import Cenario as CenarioSync, pedido

HOJE = dt.date.today().strftime("%d/%m/%Y")


def retorno(sio):
    return sio.ultimo("retorno_sincronizacao")


# -- NF completo ------------------------------------------------------------------------

def montar_nf(tmp_path, vendas, falhar=False):
    """Pedido 3 (MOUSE) sem NF no portal e com a venda no HSE; 1 e 2 já têm NF no portal."""
    cen = Cenario(tmp_path, [lin(1, "MONITOR"), lin(2, "TECLADO"), lin(3, "MOUSE")],
                  [ped(1, "MONITOR 24", nf="15730"), ped(2, "TECLADO", nf="15020 / 15031"), ped(3, "MOUSE")])
    arq = excel_de(tmp_path, vendas)

    def exportar(de, ate, progresso):
        if falhar:
            raise RuntimeError("HSE fora do ar")
        progresso("baixando do HSE")
        return {"arquivo": arq, "linhas_tela": len(vendas)}

    sio = Sio()
    h = registrar(sio, {"caminho_banco_dados": str(cen.dados), "caminho_pedidos": str(cen.pedidos),
                        "caminho_planilha": str(cen.xlsx), "caminho_backups": str(tmp_path / "bk")},
                  Log(), manager=ArquivoPedidosConcorrente(str(cen.pedidos)), exportar=exportar, em_thread=False)
    return cen, sio, h


def test_nf_completo_grava_no_portal_e_depois_na_planilha(tmp_path):
    cen, sio, h = montar_nf(tmp_path, [venda(10, 3, 16001, emissao=HOJE)])
    h["sincronizacao"]({"servico": "nf_completo", "clientId": "c1", "audit_id": "a1"})
    r = retorno(sio)
    assert r["sucesso"], r
    assert (r["servico"], r["clientId"], r["audit_id"]) == ("nf_completo", "c1", "a1")
    portal = json.loads(cen.pedidos.read_text(encoding="utf-8"))["PEDIDOS"]
    assert portal[2]["Nº NOTA FISCAL"] == "16001"                                # HSE -> portal
    assert cen.valores(14) == ["NF (MAESTRO)", 15730, "15020 / 15031", 16001]    # portal -> planilha
    assert "1 NF" in r["mensagem"] and "3 NF" in r["mensagem"]
    assert ("planilha_atualizada", None) in sio.emitidos
    assert any(e == "progresso_sincronizacao" and d["servico"] == "nf_completo" for e, d in sio.emitidos)


def test_nf_completo_hse_fora_do_ar_nao_mexe_na_planilha(tmp_path):
    cen, sio, h = montar_nf(tmp_path, [venda(10, 3, 16001)], falhar=True)
    h["sincronizacao"]({"servico": "nf_completo"})
    r = retorno(sio)
    assert r["sucesso"] is False and "HSE fora do ar" in r["erro"]
    assert cen.xlsx.read_bytes() == cen.original
    h["sincronizacao"]({"servico": "nf_completo"})                    # a trava foi liberada
    assert "rodando" not in retorno(sio)["erro"]


def test_nf_completo_planilha_recusada_diz_que_o_portal_ja_foi(tmp_path, monkeypatch):
    from cruzar_nf import nf_planilha as NP

    def recusar(*a, **k):
        raise NP.GravacaoRecusada("A planilha está aberta no Excel (ANA).")
    monkeypatch.setattr(NP, "gravar_nf_na_planilha", recusar)
    cen, sio, h = montar_nf(tmp_path, [venda(10, 3, 16001, emissao=HOJE)])
    h["sincronizacao"]({"servico": "nf_completo"})
    r = retorno(sio)
    assert r["sucesso"] is False
    assert "1 NF" in r["erro"] and "aberta no Excel (ANA)" in r["erro"]


def test_nf_completo_recusa_com_outra_sincronizacao_de_nf_rodando(tmp_path):
    cen, sio, h = montar_nf(tmp_path, [venda(10, 3, 16001, emissao=HOJE)])
    with trava(cen.dados, "SincronizarNF.bat"):
        h["sincronizacao"]({"servico": "nf_completo"})
    r = retorno(sio)
    assert r["sucesso"] is False and "rodando" in r["erro"]
    assert cen.xlsx.read_bytes() == cen.original


# -- Sync planilha ⇄ portal ----------------------------------------------------------------

def montar_sync(tmp_path):
    c = CenarioSync(tmp_path)
    sio = Sio()
    h = registrar(sio, {"caminho_banco_dados": str(c.dados), "caminho_pedidos": str(c.json),
                        "caminho_planilha": str(c.xlsx)}, Log(), manager=object(), em_thread=False)
    return c, sio, h


def test_sync_planilha_roda_mesmo_depois_da_rodada_do_dia(tmp_path):
    c, sio, h = montar_sync(tmp_path)
    c.rodar()                                                          # foto inicial
    SP._salvar(c.dados, SP.ARQ_RELATORIO, dict(SP._ler(c.dados, SP.ARQ_RELATORIO),
                                                concluido_em=dt.datetime.now().strftime(SP.FMT_HORA)))
    w = openpyxl.load_workbook(c.xlsx)
    w["PEDIDOS"].append(list(pedido(2).values()))
    w.save(c.xlsx)
    h["sincronizacao"]({"servico": "sync_planilha", "clientId": "c2"})
    r = retorno(sio)
    assert r["sucesso"], r
    assert len(c.portal()) == 2                                        # a linha nova do Excel entrou
    assert "1 alteração" in r["mensagem"]
    assert ("planilha_atualizada", None) in sio.emitidos


def test_sync_planilha_com_rodada_do_agendador_em_andamento(tmp_path):
    c, sio, h = montar_sync(tmp_path)
    with trava(c.dados, "Sincronização planilha/portal"):
        h["sincronizacao"]({"servico": "sync_planilha"})
    r = retorno(sio)
    assert r["sucesso"] is False and "rodando" in r["erro"]


def test_sync_planilha_adiada_por_excel_aberto_e_erro(tmp_path, monkeypatch):
    c, sio, h = montar_sync(tmp_path)
    monkeypatch.setattr(SP, "sincronizar", lambda *a, **k: {"adiado": True, "aviso": "aberta por ANA"})
    h["sincronizacao"]({"servico": "sync_planilha"})
    r = retorno(sio)
    assert r["sucesso"] is False and "aberta por ANA" in r["erro"]


def test_sync_planilha_que_falha_fica_no_relatorio_do_painel(tmp_path, monkeypatch):
    c, sio, h = montar_sync(tmp_path)

    def quebrar(*a, **k):
        raise OSError("rede caiu")
    monkeypatch.setattr(SP, "sincronizar", quebrar)
    h["sincronizacao"]({"servico": "sync_planilha"})
    assert "rede caiu" in retorno(sio)["erro"]
    assert SP._ler(c.dados, SP.ARQ_RELATORIO)["erro"] == "rede caiu"


# -- comum ---------------------------------------------------------------------------------

def test_servico_desconhecido_e_estado_para_os_cartoes(tmp_path):
    cen, sio, h = montar_nf(tmp_path, [venda(10, 3, 16001, emissao=HOJE)])
    h["sincronizacao"]({"servico": "ciclo_coupa"})                    # é do gerenciador, não daqui
    assert retorno(sio)["sucesso"] is False
    h["sincronizacao"]({"servico": "nf_completo"})
    h["sincronizacao_estado"]({"clientId": "c3"})
    r = sio.ultimo("retorno_sincronizacao_estado")
    assert r["sucesso"] and r["clientId"] == "c3" and r["estado"]["rodando"] == []
    ultima = r["estado"]["ultimas"]["nf_completo"]
    assert ultima["nivel"] == "ok" and "1 NF" in ultima["resumo"] and ultima["em"]
    assert "sync_planilha" not in r["estado"]["ultimas"]             # nunca rodou nesta pasta


def test_registra_os_comandos_novos(tmp_path):
    _, sio, _ = montar_sync(tmp_path)
    assert {"comando_sincronizacao", "comando_sincronizacao_estado"} <= set(sio.handlers)
