"""Sincronização de NF: HSE -> base de vendas -> NF nos pedidos do Maestro.

Uma rodada:
1. `exportar(de, ate, progresso)` baixa o Excel de Venda (pedido) do HSE
   (o robô, ou um Excel já baixado);
2. lê o Excel e junta na base acumulada (`vendas_hse.json`);
3. cruza a BASE INTEIRA com os pedidos e grava a NF onde está vazia
   (`maestro.aplicar_nfs`, dentro da trava do planilha_manager);
4. registra o estado (`sync_nf.json`): última sincronização, cobertura e
   histórico — é o que o portal mostra.

Rodar à mão (só com o gerenciador DESLIGADO, porque grava direto no arquivo):

    python -m cruzar_nf.sincronizar --dados <pasta Banco-de-dados> --pedidos <PEDIDOS.json>
        --excel planilha.xlsx --de 01/01/2025 --ate 29/09/2026 [--gravar]

Sem --gravar é só prévia. Compatível com Python 3.8.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from cruzar_nf.base_vendas import FORMATO_DATA, BaseVendas, data_br
from cruzar_nf.cruzar import gravar_json, ler_json_com_chave
from cruzar_nf.maestro import aplicar_nfs
from cruzar_nf.vendas_excel import ler_excel_vendas, resumo_excel

ARQ_BASE = "vendas_hse.json"
ARQ_ESTADO = "sync_nf.json"
PASTA_HISTORICO = "cruzamento_nf"
SOBREPOSICAO_DIAS = 10        # NF emitida depois / OC corrigida depois
JANELA_SEM_HISTORICO_DIAS = 30
MANTER_EXCEL = 30             # quantos Excel baixados guardar para auditoria
MANTER_HISTORICO = 60


def _fmt(d: Optional[_dt.date]) -> Optional[str]:
    return d.strftime(FORMATO_DATA) if d else None


def _ler_data(texto: Any) -> Optional[_dt.date]:
    """Aceita dd/mm/aaaa (portal/HSE) e aaaa-mm-dd (input type=date)."""
    if texto in (None, ""):
        return None
    d = data_br(texto)
    if d:
        return d
    try:
        return _dt.datetime.strptime(str(texto).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Data inválida: {texto!r} (use dd/mm/aaaa).")


# -- estado -------------------------------------------------------------------

def carregar_estado(pasta: "str | Path") -> Dict[str, Any]:
    arq = Path(pasta) / ARQ_ESTADO
    if not arq.is_file():
        return {"ultima": None, "cobertura": [], "historico": []}
    return json.loads(arq.read_text(encoding="utf-8"))


def _salvar_estado(pasta: "str | Path", estado: Dict[str, Any]) -> None:
    estado["historico"] = estado.get("historico", [])[:MANTER_HISTORICO]
    gravar_json(Path(pasta) / ARQ_ESTADO, estado)


def _ultima_data(estado: Dict[str, Any]) -> Optional[_dt.date]:
    cob = estado.get("cobertura") or []
    return data_br(cob[-1][1]) if cob else None


def janela(pasta: "str | Path", de: Any = None, ate: Any = None,
           hoje: Optional[_dt.date] = None) -> Tuple[_dt.date, _dt.date]:
    """Período da próxima exportação. Sem datas: última sincronizada - 10 dias até hoje."""
    hoje = hoje or _dt.date.today()
    fim = _ler_data(ate) or hoje
    inicio = _ler_data(de)
    if inicio is None:
        ultima = _ultima_data(carregar_estado(pasta))
        inicio = (ultima - _dt.timedelta(days=SOBREPOSICAO_DIAS)) if ultima \
            else hoje - _dt.timedelta(days=JANELA_SEM_HISTORICO_DIAS)
    if inicio > fim:
        raise ValueError(f"A data inicial ({_fmt(inicio)}) é depois da final ({_fmt(fim)}).")
    return inicio, fim


def estado_para_tela(pasta: "str | Path") -> Dict[str, Any]:
    estado = carregar_estado(pasta)
    de, ate = janela(pasta)
    return {"ultima": estado.get("ultima"), "cobertura": estado.get("cobertura", []),
            "proxima_janela": {"de": _fmt(de), "ate": _fmt(ate)},
            "historico": estado.get("historico", [])[:10]}


def registrar_falha(pasta: "str | Path", de: _dt.date, ate: _dt.date, erro: str, origem: str) -> None:
    try:
        estado = carregar_estado(pasta)
        estado.setdefault("historico", []).insert(0, {
            "rodou_em": _dt.datetime.now().isoformat(timespec="seconds"), "origem": origem,
            "de": _fmt(de), "ate": _fmt(ate), "sucesso": False, "erro": erro})
        _salvar_estado(pasta, estado)
    except Exception:
        pass   # registrar a falha não pode gerar outra


# -- rodada -------------------------------------------------------------------

def _guardar_excel(arquivo: Path, pasta_hist: Path, de: _dt.date, ate: _dt.date) -> Path:
    pasta_hist.mkdir(parents=True, exist_ok=True)
    carimbo = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destino = pasta_hist / f"vendas_hse {de:%Y-%m-%d} a {ate:%Y-%m-%d} ({carimbo}){arquivo.suffix}"
    n = 2
    while destino.exists():   # duas rodadas no mesmo segundo não apagam a auditoria uma da outra
        destino = destino.with_name(f"vendas_hse {de:%Y-%m-%d} a {ate:%Y-%m-%d} ({carimbo} {n}){arquivo.suffix}")
        n += 1
    if arquivo.resolve() != destino.resolve():
        shutil.copy2(str(arquivo), str(destino))
    guardados = sorted(pasta_hist.glob("vendas_hse *"), key=lambda p: p.stat().st_mtime, reverse=True)
    for velho in guardados[MANTER_EXCEL:]:
        velho.unlink()
    return destino


def sincronizar(pasta: "str | Path", manager: Any, de: _dt.date, ate: _dt.date,
                exportar: Callable[..., Dict[str, Any]], gravar: bool = True,
                dir_backup: Optional[str] = None, progresso: Callable[[str], None] = print,
                origem: str = "manual") -> Dict[str, Any]:
    pasta = Path(pasta)
    progresso(f"Exportando as vendas do HSE de {_fmt(de)} a {_fmt(ate)}...")
    exportado = exportar(de, ate, progresso)
    arquivo = Path(exportado["arquivo"])
    vendas = ler_excel_vendas(arquivo)
    resumo_xls = resumo_excel(vendas)
    progresso(f"Excel lido: {len(vendas)} vendas.")

    aviso = None
    linhas_tela = exportado.get("linhas_tela")
    if linhas_tela is not None and linhas_tela != len(vendas):
        aviso = (f"A tela do HSE mostrou {linhas_tela} vendas e o Excel trouxe {len(vendas)}. "
                 "Confira se faltou alguma venda no Excel.")
        progresso("ATENÇÃO: " + aviso)

    guardado = _guardar_excel(arquivo, pasta / PASTA_HISTORICO, de, ate)
    base = BaseVendas.carregar(pasta / ARQ_BASE)
    mescla = base.mesclar(vendas, de, ate)
    base.salvar(pasta / ARQ_BASE)
    progresso(f"Base de vendas: {mescla['novas']} novas, {mescla['alteradas']} alteradas, "
              f"{mescla['removidas']} removidas ({mescla['total_na_base']} no total).")

    progresso("Cruzando com os pedidos do Maestro...")
    if hasattr(manager, "aplicar_nfs"):     # serviço separado: grava com controle de concorrência
        relatorio, gravadas = manager.aplicar_nfs(base.lista(), gravar=gravar, so_vazias=True,
                                                  dir_backup=dir_backup)
    else:                                   # dentro do gerenciador: trava do planilha_manager
        relatorio, gravadas = aplicar_nfs(manager, base.lista(), gravar=gravar, so_vazias=True,
                                          dir_backup=dir_backup)
    r = relatorio["resumo"]
    progresso(f"{gravadas} NF(s) {'gravada(s)' if gravar else 'a gravar (prévia)'}.")

    resultado = {
        "rodou_em": _dt.datetime.now().isoformat(timespec="seconds"), "origem": origem,
        "de": _fmt(de), "ate": _fmt(ate), "sucesso": True, "gravou": gravar,
        "nfs_gravadas": gravadas if gravar else 0, "nfs_a_gravar": gravadas,
        "excel": resumo_xls, "excel_guardado": guardado.name, "linhas_tela": linhas_tela,
        "aviso": aviso, "base": mescla,
        "pedidos": r["pedidos_na_planilha"], "pedidos_com_nf": r["bateram_1_nf"] + r["mais_de_uma_nf"],
        "sem_nf": r["nao_encontrados_no_erp"], "mais_de_uma_nf": r["mais_de_uma_nf"],
        "divergencias": r["divergencia_de_valor"], "percentual_com_nf": r["percentual_com_nf"],
        "divergencia_valor": [{k: d[k] for k in ("oc", "nf_gravada", "valor_planilha", "valor_erp",
                                                 "diferenca_valor")} for d in relatorio["divergencia_valor"]],
    }
    gravar_json(pasta / PASTA_HISTORICO / "RELATORIO_NF_ultimo.json", relatorio)

    estado = carregar_estado(pasta)
    estado["cobertura"] = [[_fmt(a), _fmt(b)] for a, b in base.cobertura]
    if gravar:
        estado["ultima"] = {k: resultado[k] for k in ("rodou_em", "origem", "de", "ate", "nfs_gravadas",
                                                      "pedidos", "pedidos_com_nf", "sem_nf",
                                                      "divergencias", "aviso")}
    estado.setdefault("historico", []).insert(0, {k: resultado[k] for k in (
        "rodou_em", "origem", "de", "ate", "sucesso", "gravou", "nfs_gravadas", "nfs_a_gravar",
        "pedidos_com_nf", "sem_nf", "divergencias", "aviso")})
    _salvar_estado(pasta, estado)
    progresso("Sincronização concluída.")
    return resultado


# -- uso à mão (gerenciador desligado) -----------------------------------------

class ArquivoPedidos:
    """Faz o papel do planilha_manager quando a sincronização roda fora do gerenciador."""

    def __init__(self, caminho: "str | Path"):
        self.caminho_pedidos = str(caminho)
        self.lock = threading.RLock()
        self.pedidos: Dict[str, List[dict]] = {}
        self._chave: Optional[str] = None
        self._lido = False

    def iniciar(self, *_: Any) -> None:
        if not self._lido:
            lista, self._chave = ler_json_com_chave(self.caminho_pedidos)
            self.pedidos = {"PEDIDOS": lista}
            self._lido = True

    def salvar(self) -> bool:
        lista = self.pedidos.get("PEDIDOS", [])
        gravar_json(self.caminho_pedidos, {self._chave: lista} if self._chave else lista)
        return True


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="cruzar_nf.sincronizar", description=__doc__.splitlines()[0])
    ap.add_argument("--dados", required=True, help="pasta da base (vendas_hse.json, sync_nf.json)")
    ap.add_argument("--pedidos", required=True, help="PEDIDOS.json (gerenciador desligado!)")
    origem = ap.add_mutually_exclusive_group(required=True)
    origem.add_argument("--excel", help="Excel de Venda (pedido) já baixado do HSE")
    origem.add_argument("--robo", action="store_true", help="baixar do HSE com o robô")
    ap.add_argument("--de")
    ap.add_argument("--ate")
    ap.add_argument("--gravar", action="store_true", help="grava a NF (sem isso é só prévia)")
    ap.add_argument("--backup", help="pasta do backup do PEDIDOS.json antes de gravar")
    a = ap.parse_args(argv)

    de, ate = janela(a.dados, a.de, a.ate)
    if a.excel:
        def exportar(_de, _ate, _progresso):
            return {"arquivo": a.excel, "linhas_tela": None}
    else:
        from cruzar_nf.hse_robo import exportador_do_config
        exportar = exportador_do_config({})
    res = sincronizar(a.dados, ArquivoPedidos(a.pedidos), de, ate, exportar,
                      gravar=a.gravar, dir_backup=a.backup, origem="linha de comando")
    print(json.dumps({k: res[k] for k in ("de", "ate", "gravou", "nfs_a_gravar", "nfs_gravadas",
                                          "pedidos_com_nf", "sem_nf", "divergencias", "base", "aviso")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
