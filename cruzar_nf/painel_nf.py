"""Dados dos dashboards de NFs e de Atividade do portal. Só LÊ: nada aqui grava.

- `painel_para_tela(pasta)`: indicadores da NF, pedidos sem NF (mais antigos
  primeiro), divergências, NF no portal com a coluna vazia na planilha, rodadas
  de NF e o cadastro automático. Cada parte que falha vem como {"erro": ...},
  nunca como zero.
- `eventos(pasta, limite, desde)`: linha do tempo dos últimos 7 dias no
  contrato dos dashboards ({"em", "servico", "tipo", "nivel", "resumo", "ref",
  "detalhe"}).

Os eventos NÃO têm arquivo próprio: são montados na leitura a partir dos
históricos que cada rotina já grava sozinha (sync_nf.json, cadastro_pedidos.json,
sync_planilha_portal_historico.json). Quem roda são processos diferentes
(serviço de NF, SincronizarNF.bat, CadastrarPedidos.bat e a tarefa da sync);
um eventos_nf.jsonl comum teria vários gravadores no mesmo arquivo.

Compatível com Python 3.8.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

DIAS_EVENTOS = 7
MAX_EVENTOS = 500
MAX_ITENS = 300
TAM_RESUMO = 140
ARQ_RELATORIO_NF = os.path.join("cruzamento_nf", "RELATORIO_NF_ultimo.json")
ARQ_HIST_SYNC = "sync_planilha_portal_historico.json"
FMT_BR = "%d/%m/%Y %H:%M:%S"
STATUS_SEM_NF = {"nao_encontrados": "Pedido não achado no HSE", "sem_nf": "No HSE, mas sem NF emitida",
                 "pedido_invalido": "Número do pedido inválido"}

_cache: Dict[str, Any] = {}


def _ler_json(arq: Path) -> Any:
    """Lê com cache pela data do arquivo: o relatório da NF tem ~1 MB e o portal pede a cada 60 s."""
    st = arq.stat()
    marca = (st.st_mtime_ns, st.st_size)
    if _cache.get(str(arq), (None,))[0] != marca:
        _cache[str(arq)] = (marca, json.loads(arq.read_text(encoding="utf-8")))
    return _cache[str(arq)][1]


def _parte(ler: Callable[[], Any]) -> Any:
    try:
        return ler()
    except FileNotFoundError:
        return {"erro": "Ainda não gerado."}
    except Exception as e:      # uma fonte quebrada não esconde as outras
        return {"erro": f"Erro ao ler: {e}"}


def _texto(v: Any, tam: int = 80) -> Optional[str]:
    return None if v is None else str(v).strip()[:tam]


def _data_entrega(v: Any) -> Optional[_dt.date]:
    # ponytail: datas legadas do portal ("24-Jun", m/d/aaaa) ficam sem dias; a lista mostra o texto cru
    from cruzar_nf.planilha_portal import normalizar
    try:
        iso = normalizar("DATA DE ENTREGA", v)
    except ValueError:
        return None
    return _dt.datetime.strptime(iso, "%Y-%m-%d").date() if iso else None


def _sem_nf(rel: Dict[str, Any], hoje: _dt.date) -> List[Dict[str, Any]]:
    itens = []
    for chave, motivo in STATUS_SEM_NF.items():
        for r in rel.get(chave, []):
            entrega = _data_entrega(r.get("entrega"))
            itens.append({"pedido": _texto(r.get("pedido"), 40), "rfq": _texto(r.get("rfq"), 40),
                          "produto": _texto(r.get("produto")), "cidade": _texto(r.get("cidade"), 40),
                          "entrega": _texto(r.get("entrega"), 20),
                          "dias_desde_entrega": (hoje - entrega).days if entrega else None,
                          "motivo": motivo})
    # mais antigos primeiro; sem data no fim
    itens.sort(key=lambda i: (i["dias_desde_entrega"] is None, -(i["dias_desde_entrega"] or 0)))
    return itens


def _divergencias(rel: Dict[str, Any]) -> List[Dict[str, Any]]:
    itens = []
    for r in rel.get("divergencia_valor", []):
        itens.append({"pedido": _texto(r.get("pedido"), 40), "produto": _texto(r.get("produto")),
                      "nf_portal": r.get("nf_anterior") or r.get("nf_gravada"),
                      "nf_hse": " / ".join(r.get("nfs") or []),
                      "motivo": f"Valor diferente: planilha {r.get('valor_planilha')} × HSE {r.get('valor_erp')}"
                                f" (diferença {r.get('diferenca_valor')})"})
    for r in rel.get("nf_alterada", []):
        itens.append({"pedido": _texto(r.get("pedido"), 40), "produto": _texto(r.get("produto")),
                      "nf_portal": r.get("nf_anterior"), "nf_hse": " / ".join(r.get("nfs") or []),
                      "motivo": "A NF do portal não é a que o HSE mostra para o pedido"})
    return itens


def _relatorio_nf(pasta: Path, hoje: _dt.date) -> Dict[str, Any]:
    rel = _ler_json(pasta / ARQ_RELATORIO_NF)
    sem_nf, divergencias = _sem_nf(rel, hoje), _divergencias(rel)
    return {"gerado_em": rel.get("gerado_em"), "total_sem_nf": len(sem_nf), "sem_nf": sem_nf[:MAX_ITENS],
            "total_divergencias": len(divergencias), "divergencias": divergencias[:MAX_ITENS]}


def _conferencia(pasta: Path) -> Dict[str, Any]:
    from cruzar_nf.planilha_portal import ARQ_RELATORIO
    conf = _ler_json(pasta / ARQ_RELATORIO)
    lista = conf.get("nf_so_no_portal_lista")
    return {"gerado_em": conf.get("gerado_em"), "total": conf.get("nf_so_no_portal"),
            # None = conferência de antes da lista existir; aparece na próxima rodada diária
            "itens": lista[:MAX_ITENS] if isinstance(lista, list) else None}


def _indicadores(pasta: Path) -> Dict[str, Any]:
    from cruzar_nf import sincronizar as sync
    estado = sync.estado_para_tela(pasta)
    ultima = estado.get("ultima")
    if not ultima:
        return {"erro": "Nenhuma sincronização gravada ainda."}
    cob = estado.get("cobertura") or []
    return {"com_nf": ultima.get("pedidos_com_nf"), "total": ultima.get("pedidos"),
            "sem_nf": ultima.get("sem_nf"), "divergencias": ultima.get("divergencias"),
            "ultima_sincronizacao": ultima.get("rodou_em"), "origem": ultima.get("origem"),
            "aviso": ultima.get("aviso"),
            "periodo": {"de": cob[0][0], "ate": cob[-1][1]} if cob else None,
            "proxima_janela": estado.get("proxima_janela")}


def _rodadas_nf(pasta: Path) -> List[Dict[str, Any]]:
    from cruzar_nf.sincronizar import carregar_estado
    return [{k: h.get(k) for k in ("inicio", "rodou_em", "origem", "de", "ate", "sucesso", "gravou",
                                    "nfs_gravadas", "sem_nf", "divergencias", "erro", "aviso")}
            for h in carregar_estado(pasta).get("historico", [])]


def _cadastro(pasta: Path) -> Dict[str, Any]:
    from cruzar_nf.cadastro_pedidos import estado_para_tela
    return estado_para_tela(str(pasta))


def painel_para_tela(pasta: "str | Path", hoje: Optional[_dt.date] = None) -> Dict[str, Any]:
    pasta, hoje = Path(pasta), hoje or _dt.date.today()
    return {"gerado_em": _dt.datetime.now().isoformat(timespec="seconds"),
            "indicadores": _parte(lambda: _indicadores(pasta)),
            "relatorio": _parte(lambda: _relatorio_nf(pasta, hoje)),
            "nf_so_no_portal": _parte(lambda: _conferencia(pasta)),
            "rodadas": _parte(lambda: _rodadas_nf(pasta)),
            "cadastro": _parte(lambda: _cadastro(pasta))}


# -- eventos -------------------------------------------------------------------

def _hora(texto: Any) -> Optional[_dt.datetime]:
    """'2026-10-15T12:30:21' ou '15/10/2026 12:30:21' -> datetime com o fuso local."""
    for ler in (_dt.datetime.fromisoformat, lambda t: _dt.datetime.strptime(t, FMT_BR)):
        try:
            d = ler(str(texto).strip())
        except (TypeError, ValueError):
            continue
        return d if d.tzinfo else d.astimezone()
    return None


def _evento(em: _dt.datetime, servico: str, tipo: str, nivel: str, resumo: str,
            ref: Any = None, detalhe: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if len(resumo) > TAM_RESUMO:
        resumo = resumo[:TAM_RESUMO - 1] + "…"
    return {"em": em.isoformat(timespec="seconds"), "servico": servico, "tipo": tipo, "nivel": nivel,
            "resumo": resumo, "ref": ref, "detalhe": detalhe or {}}


def _eventos_nf(pasta: Path) -> List[Dict[str, Any]]:
    from cruzar_nf.sincronizar import carregar_estado
    saida = []
    for h in carregar_estado(pasta).get("historico", []):
        em = _hora(h.get("rodou_em"))
        if em is None:
            continue
        detalhe = {k: h.get(k) for k in ("origem", "de", "ate", "sem_nf", "divergencias") if h.get(k) is not None}
        if not h.get("sucesso"):
            nivel, resumo = "erro", f"Sincronização de NF falhou: {h.get('erro')}"
        elif not h.get("gravou"):
            nivel, resumo = "info", f"Prévia da NF: {h.get('nfs_a_gravar', 0)} NF(s) a gravar"
        elif h.get("aviso"):
            nivel, resumo = "aviso", f"Gravou {h.get('nfs_gravadas', 0)} NF(s), com aviso: {h['aviso']}"
        elif h.get("nfs_gravadas"):
            nivel, resumo = "ok", f"Gravou {h['nfs_gravadas']} NF(s) do HSE; {h.get('sem_nf')} pedido(s) ainda sem NF"
        else:
            nivel, resumo = "info", f"Nenhuma NF nova no HSE; {h.get('sem_nf')} pedido(s) sem NF"
        saida.append(_evento(em, "nf", "rodada", nivel, resumo, detalhe=detalhe))
    return saida


def _eventos_cadastro(pasta: Path) -> List[Dict[str, Any]]:
    from cruzar_nf.cadastro_pedidos import carregar_estado
    estado = carregar_estado(str(pasta))
    saida = []
    for h in estado.get("historico", []):
        em = _hora(h.get("rodou_em"))
        if em is None or h.get("primeira_vez"):
            continue
        pedidos, repetidas = h.get("pedidos") or [], h.get("repetidas") or []
        if h.get("gravados"):
            saida.append(_evento(em, "cadastro", "cadastro", "ok",
                                 f"Cadastrou {h['gravados']} pedido(s) da planilha no portal",
                                 ref=str(pedidos[0]).split(" - ")[0] if pedidos else None,
                                 detalhe={"pedidos": pedidos[:10]}))
        if repetidas:
            saida.append(_evento(em, "cadastro", "cadastro", "aviso",
                                 f"{len(repetidas)} linha(s) repetida(s) na planilha não foram cadastradas",
                                 detalhe={"repetidas": repetidas[:10]}))
        if not h.get("gravados") and not repetidas and h.get("ja_no_portal"):
            saida.append(_evento(em, "cadastro", "cadastro", "info",
                                 f"{h['ja_no_portal']} linha(s) nova(s) da planilha já estavam no portal"))
    erro = estado.get("erro") or {}
    em = _hora(erro.get("em"))
    if em is not None:
        saida.append(_evento(em, "cadastro", "erro", "erro", f"Cadastro automático com erro: {erro.get('mensagem')}"))
    return saida


NIVEL_SYNC = {"gravou": "ok", "adiado": "aviso", "erro": "erro", "sem_acoes": "info", "inicializou": "info"}


def _eventos_sync(pasta: Path) -> List[Dict[str, Any]]:
    arq = pasta / ARQ_HIST_SYNC
    if not arq.is_file():
        return []
    saida = []
    for x in json.loads(arq.read_text(encoding="utf-8")).get("rodadas", []):
        em, resultado = _hora(x.get("em")), x.get("resultado")
        if em is None:
            continue
        cont = x.get("contagens") or {}
        resumo = {"gravou": f"Gravou {cont.get('acoes', 0)} mudança(s) entre planilha e portal",
                  "adiado": f"Sincronização adiada: {x.get('aviso')}",
                  "erro": f"Sincronização com erro: {x.get('aviso')}",
                  "inicializou": "Primeira rodada: foto da planilha e do portal guardada",
                  }.get(resultado, "Nada a sincronizar entre planilha e portal")
        saida.append(_evento(em, "sync_planilha", "rodada", NIVEL_SYNC.get(resultado, "info"), resumo,
                             detalhe={k: v for k, v in cont.items() if v}))
    return saida


FONTES = (("nf", _eventos_nf), ("cadastro", _eventos_cadastro), ("sync_planilha", _eventos_sync))


def eventos(pasta: "str | Path", limite: Any = 200, desde: Any = None,
            agora: Optional[_dt.datetime] = None) -> Dict[str, Any]:
    """Eventos dos últimos 7 dias (ou só os depois de `desde`), mais novos primeiro.
    Uma fonte com erro vai em `erros` e não esconde as outras."""
    pasta = Path(pasta)
    agora = (agora or _dt.datetime.now()).astimezone()
    corte = agora - _dt.timedelta(days=DIAS_EVENTOS)
    depois = _hora(desde) if desde else None
    try:
        limite = max(1, min(int(limite), MAX_EVENTOS))
    except (TypeError, ValueError):
        limite = 200
    todos, erros = [], {}
    for nome, ler in FONTES:
        try:
            todos.extend(ler(pasta))
        except Exception as e:
            erros[nome] = str(e)
    todos = [e for e in todos if _hora(e["em"]) >= corte and (depois is None or _hora(e["em"]) > depois)]
    todos.sort(key=lambda e: _hora(e["em"]), reverse=True)
    return {"eventos": todos[:limite], "total": len(todos), "erros": erros}
