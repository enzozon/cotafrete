"""Investigação dos pedidos que o cruzamento não fechou, só com o ERP.

Duas buscas, sem precisar do HSE:

1. **Ordem de compra parecida.** A OC do pedido não está no ERP, mas tem
   uma OC no ERP (ainda não ligada a pedido nenhum) que difere em UM dígito:
   sobrando, faltando, trocado ou dois vizinhos invertidos. Na rodada de
   30/09/2026 foi assim que apareceram as NFs que faltavam: 4500249590 virou
   "45002495990" no ERP (NF 13768) e 4101211034 virou "41014211034" (NF 15677).

2. **Mesmo valor.** Venda do ERP ainda não ligada a pedido, com valor igual
   (ao centavo) ao que falta: o VALOR do pedido sem NF, ou o módulo da
   diferença de um pedido em que falta NF. Valor redondo para outro cliente
   é coincidência — por isso o resultado diz se o cliente é o mesmo.

Rodar (na pasta com comparar.json e RELATORIO_NF.json):

    python -m cruzar_nf.investigar --pasta C:\\...\\planilha_estagiarios
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from cruzar_nf.cruzar import (
    campo, exportacao_com_texto_6_casas, ler_json, normalizar_nf, normalizar_oc,
    valor_decimal, valor_erp,
)

TOLERANCIA = Decimal("0.02")
MINIMO_DIGITOS_OC = 6        # OC curta ("15120") casa com tudo: não compara
CAMPOS_VALOR = ("Total Líq.", "Total Liq", "Total Bruto")


def um_digito_de_diferenca(a: str, b: str) -> bool:
    """Distância de Damerau-Levenshtein igual a 1 (e não 0)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        dif = [i for i in range(len(a)) if a[i] != b[i]]
        return len(dif) == 1 or (
            len(dif) == 2 and dif[1] == dif[0] + 1
            and a[dif[0]] == b[dif[1]] and a[dif[1]] == b[dif[0]])
    curta, longa = (a, b) if len(a) < len(b) else (b, a)
    return any(longa[:i] + longa[i + 1:] == curta for i in range(len(longa)))


def _raiz_cnpj(valor: Any) -> str | None:
    """8 primeiros dígitos do CNPJ (a empresa, sem a filial). O ERP perde o 0 da frente."""
    digitos = "".join(ch for ch in str(valor or "") if ch.isdigit())
    return digitos.zfill(14)[:8] if len(digitos) >= 11 else None


def _venda(r: dict, texto_6_casas: bool) -> dict:
    return {
        "nf": normalizar_nf(campo(r, "NF")),
        "empresa": campo(r, "Filial"),
        "venda": campo(r, "Código"),
        "oc_no_erp": campo(r, "Ordem Compra"),
        "cliente": campo(r, "Cliente"),
        "cnpj_raiz": _raiz_cnpj(campo(r, "CNPJ/CPF")),
        "emissao": campo(r, "Emissão"),
        "valor": valor_erp(campo(r, *CAMPOS_VALOR), texto_6_casas),
    }


def investigar(comparar: list[dict], relatorio: dict) -> dict:
    texto_6 = exportacao_com_texto_6_casas([campo(r, *CAMPOS_VALOR) for r in comparar])
    ocs_planilha = {p["oc"] for k in ("bateram", "mais_de_uma_nf", "nao_encontrados", "sem_nf")
                    for p in relatorio.get(k, []) if p.get("oc")}
    por_oc: dict[str, list[dict]] = defaultdict(list)   # OCs do ERP sem pedido na planilha
    livres: list[dict] = []                              # vendas com NF e sem pedido
    clientes_da_oc: dict[str, set[str]] = defaultdict(set)
    for r in comparar:
        venda = _venda(r, texto_6)
        oc = normalizar_oc(campo(r, "Ordem Compra"))
        if oc and venda["cnpj_raiz"]:
            clientes_da_oc[oc].add(venda["cnpj_raiz"])
        if oc in ocs_planilha or not venda["nf"]:
            continue
        livres.append(venda)
        if oc:
            por_oc[oc].append(venda)

    def oc_parecida(oc: str) -> list[dict]:
        if len(oc) < MINIMO_DIGITOS_OC:
            return []
        saida = []
        for outra, vendas in por_oc.items():
            if len(outra) >= MINIMO_DIGITOS_OC and um_digito_de_diferenca(oc, outra):
                total = sum((v["valor"] or Decimal(0)) for v in vendas)
                comuns = clientes_da_oc[oc] & clientes_da_oc[outra]
                saida.append({"oc_no_erp": outra, "total": f"{total:.2f}",
                              "mesmo_cliente": bool(comuns) if clientes_da_oc[oc] else None,
                              "vendas": vendas})
        return saida

    def mesmo_valor(alvo: Decimal | None, clientes: set[str]) -> list[dict]:
        if not alvo:
            return []
        return [{**v, "mesmo_cliente": (v["cnpj_raiz"] in clientes) if clientes else None}
                for v in livres if v["valor"] is not None and abs(v["valor"] - alvo) <= TOLERANCIA]

    def bloco(p: dict, alvo: Decimal | None) -> dict:
        clientes = clientes_da_oc.get(p["oc"], set())
        return {"oc": p["oc"], "cidade": p.get("cidade"), "alvo": f"{alvo:.2f}" if alvo else None,
                "oc_parecida": oc_parecida(p["oc"]), "mesmo_valor": mesmo_valor(alvo, clientes)}

    sem_nf = [bloco(p, valor_decimal(p.get("valor_planilha")))
              for p in relatorio.get("nao_encontrados", []) if p.get("oc")]
    divergencias = [bloco(p, abs(Decimal(p["diferenca_valor"])))
                    for p in relatorio.get("divergencia_valor", [])]
    return {"sem_nf": sem_nf, "divergencias": divergencias}


def _json_padrao(o: Any) -> Any:
    if isinstance(o, Decimal):
        return f"{o:.2f}"
    raise TypeError(type(o))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cruzar_nf.investigar", description=__doc__.splitlines()[0])
    ap.add_argument("--pasta", default=".")
    args = ap.parse_args(argv)
    pasta = Path(args.pasta)
    for nome in ("comparar.json", "RELATORIO_NF.json"):
        if not (pasta / nome).is_file():
            print(f"[ERRO] não achei {pasta / nome}", file=sys.stderr)
            return 1
    rel = json.loads((pasta / "RELATORIO_NF.json").read_text(encoding="utf-8"))
    res = investigar(ler_json(pasta / "comparar.json"), rel)
    (pasta / "INVESTIGACAO_ERP.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=_json_padrao), encoding="utf-8")
    n_oc = sum(1 for b in res["sem_nf"] + res["divergencias"] if b["oc_parecida"])
    n_val = sum(1 for b in res["sem_nf"] + res["divergencias"] if b["mesmo_valor"])
    print(f"OC parecida: {n_oc} pedidos | mesmo valor: {n_val} pedidos -> {pasta / 'INVESTIGACAO_ERP.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
