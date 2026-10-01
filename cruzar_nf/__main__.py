"""Rodar à mão:

    python -m cruzar_nf                       # arquivos na pasta atual
    python -m cruzar_nf --pasta C:\\planilhas
    python -m cruzar_nf --pedidos A.json --comparar B.json --saida C.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cruzar_nf.cruzar import resumo_console, rodar


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="cruzar_nf",
        description="Cruza PEDIDOS.json com comparar.json pela ordem de compra e grava a NF.",
    )
    ap.add_argument("--pasta", default=".", help="pasta dos arquivos (padrão: a atual)")
    ap.add_argument("--pedidos", default="PEDIDOS.json")
    ap.add_argument("--comparar", default="comparar.json")
    ap.add_argument("--saida", default="PEDIDOS_ATUALIZADO.json")
    ap.add_argument("--relatorio", default="RELATORIO_NF.md", help="relatório em Markdown")
    ap.add_argument("--relatorio-json", default="RELATORIO_NF.json",
                    help="relatório em JSON (o que o portal lê)")
    args = ap.parse_args(argv)

    pasta = Path(args.pasta)
    caminhos = {k: pasta / getattr(args, k) for k in
                ("pedidos", "comparar", "saida", "relatorio", "relatorio_json")}
    for k in ("pedidos", "comparar"):
        if not caminhos[k].is_file():
            print(f"[ERRO] não achei {caminhos[k]}", file=sys.stderr)
            return 1

    try:
        rel = rodar(caminhos["pedidos"], caminhos["comparar"], caminhos["saida"],
                    caminhos["relatorio"], caminhos["relatorio_json"])
    except (ValueError, OSError) as e:  # JSON quebrado, arquivo aberto no Excel...
        print(f"[ERRO] {e}", file=sys.stderr)
        return 1

    print(f"\nCruzamento concluído.\n\n{resumo_console(rel)}\n")
    print(f"  Arquivo novo: {caminhos['saida']}")
    print(f"  Relatório:    {caminhos['relatorio']}")
    print(f"                {caminhos['relatorio_json']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
