"""Gravação da NF por fora do gerenciador (cruzar_nf/arquivo_pedidos.py) — caminho B.

O cenário que importa: o gerenciador do Maestro (planilha_manager) e o
serviço de NF mexendo no mesmo PEDIDOS.json ao mesmo tempo.
"""

from __future__ import annotations

import json
import os
import threading
import types
from pathlib import Path

import pytest

from cruzar_nf.arquivo_pedidos import ArquivoPedidosConcorrente, ConflitoGravacao
from cruzar_nf.maestro import CAMPO_NF as CAMPO

FIXTURE_PM = Path(__file__).parent / "fixtures" / "maestro" / "planilha_manager_servidor_2026-10-01.py"


def venda(codigo, oc, nf, valor=100):
    return {"Tipo": "VEN", "Código": codigo, "Emissão": "15/09/2026", "Ordem Compra": oc, "NF": nf,
            "Total Líq.": valor, "Filial": "VENTURA MATRIZ"}


def ped(oc, **extra):
    return {"CIDADE": "SÃO LUÍS - MA", "PEDIDO": oc, "VALOR ": 100, **extra}


def escrever_como_o_gerenciador(arq, pedidos):
    """Igual ao planilha_manager.salvar(): sem temporário, indent=1, acentos."""
    with open(arq, "w", encoding="utf-8") as f:
        json.dump({"PEDIDOS": pedidos}, f, indent=1, ensure_ascii=False)


def ler(arq):
    return json.loads(Path(arq).read_text(encoding="utf-8"))


def gravador(arq, **kw):
    kw.setdefault("espera_verificacao", 0)
    kw.setdefault("dormir", lambda _s: None)
    return ArquivoPedidosConcorrente(str(arq), **kw)


def test_grava_no_formato_do_planilha_manager(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    escrever_como_o_gerenciador(arq, [ped(1), None, ped(2, **{CAMPO: "999"})])
    _, n = gravador(arq).aplicar_nfs([venda(10, 1, 15)], gravar=True)
    assert n == 1
    texto = arq.read_text(encoding="utf-8")
    assert texto.startswith('{\n "PEDIDOS": [\n  {')          # indent=1, como o planilha_manager
    assert "SÃO LUÍS" in texto                                # acentos preservados
    assert ler(arq)["PEDIDOS"] == [ped(1, **{CAMPO: "15"}), None, ped(2, **{CAMPO: "999"})]
    assert not list(tmp_path.glob("*.tmp"))                   # o temporário não sobra


def test_previa_nao_grava(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    escrever_como_o_gerenciador(arq, [ped(1)])
    antes = arq.read_bytes()
    _, n = gravador(arq).aplicar_nfs([venda(10, 1, 15)], gravar=False)
    assert n == 1 and arq.read_bytes() == antes


def test_salvar_recusa_se_o_arquivo_mudou_depois_da_leitura(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    escrever_como_o_gerenciador(arq, [ped(1)])
    g = gravador(arq)
    g.iniciar()
    escrever_como_o_gerenciador(arq, [ped(1), ped(2)])         # o robô salvou um pedido novo
    with pytest.raises(ConflitoGravacao):
        g.salvar()
    assert len(ler(arq)["PEDIDOS"]) == 2                        # nada foi perdido


def test_gerenciador_grava_no_meio_e_o_pedido_novo_nao_some(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    escrever_como_o_gerenciador(arq, [ped(1)])
    g = gravador(arq)
    original_salvar = g.salvar
    chamadas = {"n": 0}

    def salvar_com_robo_no_meio():
        chamadas["n"] += 1
        if chamadas["n"] == 1:   # entre nossa leitura e nossa gravação, o robô salvou um pedido
            escrever_como_o_gerenciador(arq, [ped(1), ped(2)])
        return original_salvar()

    g.salvar = salvar_com_robo_no_meio
    _, n = g.aplicar_nfs([venda(10, 1, 15), venda(20, 2, 25)], gravar=True)
    assert [p.get(CAMPO) for p in ler(arq)["PEDIDOS"]] == ["15", "25"]
    assert n == 2 and chamadas["n"] == 2


def test_gerenciador_salva_por_cima_depois_e_a_nf_volta(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    escrever_como_o_gerenciador(arq, [ped(1)])
    vezes = {"n": 0}

    def dormir(_s):
        vezes["n"] += 1
        if vezes["n"] == 1:      # durante a verificação, o robô salva a memória velha por cima
            escrever_como_o_gerenciador(arq, [ped(1), ped(3)])

    mensagens = []
    _, n = gravador(arq, dormir=dormir, progresso=mensagens.append).aplicar_nfs([venda(10, 1, 15)], gravar=True)
    assert ler(arq)["PEDIDOS"] == [ped(1, **{CAMPO: "15"}), ped(3)]
    assert n == 1 and any("não ficaram gravadas" in m for m in mensagens)


def test_le_de_novo_quando_pega_o_json_cortado(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    arq.write_text('{\n "PEDIDOS": [\n  {"PEDIDO": 1,', encoding="utf-8")   # gravação pela metade
    leituras = {"n": 0}

    def dormir(_s):
        leituras["n"] += 1
        escrever_como_o_gerenciador(arq, [ped(1)])

    g = gravador(arq, dormir=dormir)
    g.iniciar()
    assert g.pedidos["PEDIDOS"] == [ped(1)] and leituras["n"] == 1


def test_le_com_a_tolerancia_do_planilha_manager(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    arq.write_text('{"PEDIDOS": [{"PEDIDO": 1,}, ]}', encoding="utf-8")
    g = gravador(arq)
    g.iniciar()
    assert g.pedidos == {"PEDIDOS": [{"PEDIDO": 1}]}


def test_desiste_depois_das_tentativas(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    escrever_como_o_gerenciador(arq, [ped(1)])
    g = gravador(arq, tentativas=3)

    def sempre_conflito():
        raise ConflitoGravacao("teste")

    g.salvar = sempre_conflito
    with pytest.raises(RuntimeError, match="todas as tentativas"):
        g.aplicar_nfs([venda(10, 1, 15)], gravar=True)


def test_backup_uma_vez_so(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    escrever_como_o_gerenciador(arq, [ped(1)])
    vezes = {"n": 0}

    def dormir(_s):
        vezes["n"] += 1
        if vezes["n"] == 1:
            escrever_como_o_gerenciador(arq, [ped(1)])           # força uma segunda volta

    gravador(arq, dormir=dormir).aplicar_nfs([venda(10, 1, 15)], gravar=True, dir_backup=str(tmp_path / "bk"))
    assert len(list((tmp_path / "bk").glob("*.json"))) == 1


def carregar_planilha_manager_do_servidor(pasta):
    """O planilha_manager real do servidor, apontado para uma pasta de teste."""
    fonte = FIXTURE_PM.read_text(encoding="utf-8")
    fonte = fonte.replace(r'r"\\SERVIDOR2\Publico\ALLAN\database\Banco-de-dados"', repr(str(pasta)))
    assert "SERVIDOR2" not in fonte
    mod = types.ModuleType("planilha_manager_teste")
    exec(compile(fonte, "planilha_manager_servidor", "exec"), mod.__dict__)
    return mod.planilha_manager


def test_o_planilha_manager_do_servidor_enxerga_a_nf_sem_reiniciar(tmp_path):
    escrever_como_o_gerenciador(tmp_path / "PEDIDOS.json", [ped(1)])
    (tmp_path / "COTAÇÕES.json").write_text('{"COTAÇÃO": []}', encoding="utf-8")
    pm = carregar_planilha_manager_do_servidor(tmp_path)
    pm.iniciar()
    assert CAMPO not in pm.pedidos["PEDIDOS"][0]

    gravador(tmp_path / "PEDIDOS.json").aplicar_nfs([venda(10, 1, 15)], gravar=True)

    pm.iniciar()                                         # o que toda operação do gerenciador faz
    assert pm.pedidos["PEDIDOS"][0][CAMPO] == "15"
    # e quando o gerenciador salvar de novo (ex.: robô do Coupa adiciona pedido), a NF continua
    pm.adicionar_linhas_pedidos("PEDIDO", [{"pedido": 2, "itens": []}])
    assert ler(tmp_path / "PEDIDOS.json")["PEDIDOS"][0][CAMPO] == "15"
    assert len(ler(tmp_path / "PEDIDOS.json")["PEDIDOS"]) == 2


def test_a_data_do_arquivo_sempre_avanca_para_o_gerenciador_reler(tmp_path):
    # o planilha_manager só relê se a data de modificação AUMENTAR; no Windows ela anda
    # em passos de milissegundos e a nossa gravação pode cair no mesmo passo da dele
    arq = tmp_path / "PEDIDOS.json"
    escrever_como_o_gerenciador(arq, [ped(1)])
    futuro = arq.stat().st_mtime_ns + 5 * 10**9
    os.utime(arq, ns=(futuro, futuro))
    gravador(arq).aplicar_nfs([venda(10, 1, 15)], gravar=True)
    assert arq.stat().st_mtime_ns > futuro


def test_gravacoes_simultaneas_do_gerenciador_nao_perdem_pedido(tmp_path):
    """Robô do gerenciador adicionando pedidos em paralelo com a sincronização."""
    escrever_como_o_gerenciador(tmp_path / "PEDIDOS.json", [ped(i) for i in range(1, 51)])
    (tmp_path / "COTAÇÕES.json").write_text('{"COTAÇÃO": []}', encoding="utf-8")
    pm = carregar_planilha_manager_do_servidor(tmp_path)
    pm.iniciar()
    vendas = [venda(i, i, 1000 + i) for i in range(1, 51)]
    do_robo = list(range(100, 130))

    def robo():
        for k in do_robo:
            pm.adicionar_linhas_pedidos("PEDIDO", [{"pedido": k, "itens": []}])

    t = threading.Thread(target=robo)
    t.start()
    try:
        ArquivoPedidosConcorrente(str(tmp_path / "PEDIDOS.json"), espera_verificacao=0.05).aplicar_nfs(vendas, gravar=True)
    finally:
        t.join()
    final = ler(tmp_path / "PEDIDOS.json")["PEDIDOS"]
    pedidos = [p["PEDIDO"] for p in final]
    assert set(pedidos) >= set(range(1, 51))                 # os pedidos antigos estão todos lá
    assert sorted(p for p in pedidos if p >= 100) == do_robo  # nenhum pedido do robô se perdeu
