"""Conferência completa da planilha de pedidos contra o ERP, num comando só.

Roda o cruzamento (cruzar), as pistas no ERP (investigar) e verificações de
qualidade dos dados da planilha, e gera uma LISTA DE CORREÇÕES exata:
linha, pedido, campo, valor atual, valor sugerido e por quê.

    python -m cruzar_nf.conferir --pedidos <PEDIDOS.json> --comparar <comparar.json> --saida <pasta>

Não altera o PEDIDOS.json. Por que não corrige sozinho: o gerenciador do
Maestro (planilha_manager) carrega o PEDIDOS.json uma vez e regrava o arquivo
inteiro a cada mudança; uma edição feita por fora seria sobrescrita na próxima
gravação do robô ou do portal. As correções entram pelo portal ("Editar") ou
por um comando do gerenciador que use o CORRECOES.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from cruzar_nf.cruzar import (
    _chave_campo, campo, cruzar, ler_json_com_chave, ler_json, normalizar_nf, normalizar_oc,
    valor_decimal,
)
from cruzar_nf.investigar import investigar

ARREDONDAMENTO = Decimal("1.00")   # diferença menor que isso não vira correção


def _nome_campo(pedido: dict, nome: str) -> str:
    """Nome do campo como está no pedido ("VALOR " com espaço), ou o nome dado."""
    return next((k for k in pedido if _chave_campo(k) == _chave_campo(nome)), nome)


def _numero(v: Decimal) -> float | int:
    return int(v) if v == v.to_integral_value() else float(v)


def verificar_qualidade(pedidos: list[dict], comparar: list[dict]) -> list[dict]:
    """Problemas de formato/conteúdo, cada um já com a correção sugerida."""
    nf_para_ocs: dict[str, set[str]] = defaultdict(set)
    for r in comparar:
        nf, oc = normalizar_nf(campo(r, "NF")), normalizar_oc(campo(r, "Ordem Compra"))
        if nf and oc:
            nf_para_ocs[nf].add(oc)

    achados = []

    def achado(i, p, nome, sugerido, motivo, certeza):
        achados.append({"linha": i, "pedido": campo(p, "PEDIDO"), "campo": _nome_campo(p, nome),
                        "atual": campo(p, nome), "sugerido": sugerido, "motivo": motivo, "certeza": certeza})

    for i, p in enumerate(pedidos, 1):
        valor = campo(p, "VALOR")
        if isinstance(valor, str) and valor_decimal(valor) is not None:
            achado(i, p, "VALOR", _numero(valor_decimal(valor)),
                   "VALOR gravado como texto (os outros pedidos são número)", "alta")
        if not valor or valor_decimal(valor) in (None, Decimal(0)):
            achado(i, p, "VALOR", None, "VALOR vazio ou zero", "verificar")

        bruto = campo(p, "PEDIDO")
        if isinstance(bruto, str) and bruto != bruto.strip():
            achado(i, p, "PEDIDO", bruto.strip(), "número do pedido com espaço invisível no fim", "alta")

        nf = normalizar_nf(campo(p, "NF"))
        oc = normalizar_oc(bruto)
        if nf and nf_para_ocs.get(nf) and oc not in nf_para_ocs[nf]:
            achado(i, p, "NF", "", f"no ERP a NF {nf} é da(s) OC(s) {', '.join(sorted(nf_para_ocs[nf]))}", "alta")

        email, status = campo(p, "EMAIL REQUSITAN"), campo(p, "STATUS")
        if not email and isinstance(status, str) and "@" in status:
            achado(i, p, "EMAIL REQUSITAN", status, "e-mail do requisitante está no campo STATUS", "alta")
    return achados


def correcoes_de_cruzamento(rel: dict, pedidos: list[dict]) -> list[dict]:
    """Divergência em que a NF do ERP é a referência (ERP maior que a planilha)."""
    saida = []
    for d in rel["divergencia_valor"]:
        dif = Decimal(d["diferenca_valor"])
        if abs(dif) < ARREDONDAMENTO or dif < 0:
            continue    # negativa = falta NF: não se corrige o valor, investiga-se
        p = pedidos[d["posicao"] - 1]
        saida.append({"linha": d["posicao"], "pedido": d["pedido"], "campo": _nome_campo(p, "VALOR"),
                      "atual": campo(p, "VALOR"), "sugerido": _numero(Decimal(d["valor_erp"])),
                      "motivo": f"VALOR menor que a soma das NFs do ERP ({d['nf_gravada']})",
                      "certeza": "verificar"})
    return saida


def conferir(pedidos: list[dict], comparar: list[dict]) -> dict:
    _, rel = cruzar(pedidos, comparar)
    inv = investigar(comparar, rel)
    correcoes = verificar_qualidade(pedidos, comparar) + correcoes_de_cruzamento(rel, pedidos)
    pendencias = [d for d in rel["divergencia_valor"]
                  if Decimal(d["diferenca_valor"]) <= -ARREDONDAMENTO]
    pistas = [b for b in inv["sem_nf"] + inv["divergencias"] if b["oc_parecida"] or b["mesmo_valor"]]
    return {"gerado_em": datetime.now().isoformat(timespec="seconds"), "resumo": rel["resumo"],
            "correcoes": sorted(correcoes, key=lambda c: c["linha"]),
            "falta_nf": pendencias, "pistas_erp": pistas, "repetidos": rel["pedidos_duplicados"]}


def _brl(t: Any) -> str:
    v = Decimal(str(t))
    i, c = f"{abs(v):,.2f}".split(".")
    return f"{'-' if v < 0 else ''}R$ {i.replace(',', '.')},{c}"


def montar_md(res: dict) -> str:
    r = res["resumo"]
    L = ["# Conferência da planilha de pedidos", "",
         f"Gerado em {res['gerado_em'][:16].replace('T', ' ')}.", "",
         f"- Pedidos: **{r['pedidos_na_planilha']}**, com NF no ERP: **{r['bateram_1_nf'] + r['mais_de_uma_nf']}** "
         f"({str(r['percentual_com_nf']).replace('.', ',')}%), sem NF: **{r['nao_encontrados_no_erp']}**.",
         f"- Divergências de valor: **{r['divergencia_de_valor']}**.",
         f"- Correções sugeridas: **{len(res['correcoes'])}** (lista abaixo e em `CORRECOES.json`).", "",
         "## Correções sugeridas", "",
         "| linha | pedido | campo | atual | sugerido | por quê | certeza |", "|---|---|---|---|---|---|---|"]
    for c in res["correcoes"]:
        L.append(f"| {c['linha']} | {c['pedido']} | `{c['campo']}` | `{c['atual']!r}` | "
                 f"`{c['sugerido']!r}` | {c['motivo']} | {c['certeza']} |")
    L += ["", "## Falta NF (planilha maior que o ERP)", "",
          "| pedido | planilha | ERP | diferença | NF(s) |", "|---|---|---|---|---|"]
    L += [f"| {d['oc']} | {_brl(d['valor_planilha'])} | {_brl(d['valor_erp'])} | {_brl(d['diferenca_valor'])} | {d['nf_gravada']} |"
          for d in res["falta_nf"]]
    L += ["", "## Pistas no ERP (OC parecida ou mesmo valor)", ""]
    for b in res["pistas_erp"]:
        partes = [f"OC {o['oc_no_erp']} ({_brl(o['total'])})" for o in b["oc_parecida"]]
        partes += [f"NF {v['nf']} {str(v['cliente'])[:25]} ({_brl(v['valor'])})" for v in b["mesmo_valor"][:3]]
        L.append(f"- **{b['oc']}** ({_brl(b['alvo']) if b['alvo'] else '-'}): " + "; ".join(partes))
    if res["repetidos"]:
        L += ["", "## Pedido repetido", ""]
        L += [f"- {d['oc']}: linhas {', '.join(map(str, d['posicoes']))}" for d in res["repetidos"]]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cruzar_nf.conferir", description=__doc__.splitlines()[0])
    ap.add_argument("--pedidos", required=True)
    ap.add_argument("--comparar", required=True)
    ap.add_argument("--saida", default=".")
    a = ap.parse_args(argv)
    for arq in (a.pedidos, a.comparar):
        if not Path(arq).is_file():
            print(f"[ERRO] não achei {arq}", file=sys.stderr)
            return 1
    res = conferir(ler_json_com_chave(a.pedidos)[0], ler_json(a.comparar))
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "CONFERENCIA.md").write_text(montar_md(res), encoding="utf-8")
    (saida / "CORRECOES.json").write_text(json.dumps(res["correcoes"], ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    tipos = Counter(c["motivo"].split(" (")[0].split(":")[0] for c in res["correcoes"])
    print(f"{len(res['correcoes'])} correções sugeridas -> {saida / 'CONFERENCIA.md'}")
    for motivo, n in tipos.most_common():
        print(f"  {n:>3}  {motivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
