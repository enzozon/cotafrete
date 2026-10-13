"""Planilha dos estagiários x portal: quem é par de quem, e a conferência diária.

Pareia cada linha da aba PEDIDOS com o(s) pedido(s) do PEDIDOS.json pela mesma
regra do cadastro automático (cadastro_pedidos.correspondentes). A conferência
lista o que só está de um lado e as NFs diferentes entre planilha e portal.
Roda uma vez por dia junto com o CadastrarPedidos.bat (--diario) e o resultado
vai para o painel do portal.

Linhas canceladas de propósito ficam em <SYNC_NF_DADOS>/conferencia_ignorar.json:
[{"chave": "<PEDIDO>|<RFQ>|<começo do PRODUTO>", "motivo": "..."}].

    python -m cruzar_nf.planilha_portal [--diario]

Compatível com Python 3.8.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from cruzar_nf.cadastro_pedidos import _campo, chave, correspondentes, ler_planilha_com_linhas

ARQ_RELATORIO = "conferencia_planilha.json"
ARQ_IGNORAR = "conferencia_ignorar.json"
MAX_NA_TELA = 30
IDENTIDADE = ("PEDIDO", "NMR DA RFQ", "PRODUTO")
EDITAVEIS = ("CIDADE", "FRETE", "VALOR", "DATA DE ENTREGA", "FATURAMENTO", "STATUS",
             "DAV", "REQUISITANTE", "EMAIL REQUSITAN")


def normalizar(nome: str, valor: Any, formato_data: str = "dmy") -> Any:
    if valor is None or str(valor).strip() == "":
        return None
    if nome == "VALOR":
        texto = str(valor).strip()
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        try:
            numero = Decimal(texto)
            if not numero.is_finite():
                raise ValueError("Valor não finito")
            return str(numero.quantize(Decimal("0.01")))
        except InvalidOperation as e:
            raise ValueError("Valor inválido: %s" % valor) from e
    if isinstance(valor, (_dt.date, _dt.datetime)):
        return valor.strftime("%Y-%m-%d")
    if nome == "DATA DE ENTREGA":
        formatos = ("%m/%d/%Y", "%d/%m/%Y") if formato_data == "mdy" else ("%d/%m/%Y", "%m/%d/%Y")
        for formato in formatos + ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return _dt.datetime.strptime(str(valor).strip(), formato).strftime("%Y-%m-%d")
            except ValueError:
                pass
        raise ValueError("Data inválida: %s" % valor)
    if nome == "Nº NOTA FISCAL":
        return sorted(nfs(valor))
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = unicodedata.normalize("NFKD", str(valor))
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).casefold().split())


def formato_data_portal(excel, portal):
    """O JSON antigo veio de exportação americana; o cadastro atual escreve dd/mm/aaaa."""
    try:
        a = normalizar('DATA DE ENTREGA', _campo(excel or {}, 'DATA DE ENTREGA'))
        valor = _campo(portal or {}, 'DATA DE ENTREGA')
        if a is not None and normalizar('DATA DE ENTREGA', valor, 'mdy') == a:
            if normalizar('DATA DE ENTREGA', valor, 'dmy') != a:
                return 'mdy'
    except ValueError:
        pass
    return 'dmy'


def nf_de(p: Dict[str, Any]) -> str:
    """A NF fica em "Nº NOTA FISCAL" (às vezes com espaço sobrando)."""
    v = next((v for k, v in p.items() if "NOTA FISCAL" in k.upper()), None)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return "" if v is None else str(v).strip()


def nfs(v: Any) -> Set[str]:
    """"15020 / 15031" -> {"15020", "15031"}; zeros à esquerda não contam."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+", str(v or ""))}


def parear(linhas: List[Tuple[int, Dict[str, Any]]], pedidos: List[Dict[str, Any]]) -> Dict[int, List[int]]:
    """linha do Excel -> posições dos pedidos correspondentes no PEDIDOS.json."""
    return {n: correspondentes(l, pedidos) for n, l in linhas}


def _desc(l: Dict[str, Any]) -> Dict[str, Any]:
    return {"pedido": str(_campo(l, "PEDIDO") or ""), "produto": str(_campo(l, "PRODUTO") or "")[:60]}


def conferir(linhas: List[Tuple[int, Dict[str, Any]]], pedidos: List[Dict[str, Any]],
             ignorar: Set[str]) -> Dict[str, Any]:
    pares = parear(linhas, pedidos)
    canceladas = {n for n, l in linhas if chave(l) in ignorar}
    usados = {i for v in pares.values() for i in v}
    usados |= {i for i, p in enumerate(pedidos) if chave(p) in ignorar}
    rel: Dict[str, Any] = {
        "gerado_em": _dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "linhas": len(linhas), "pedidos": len(pedidos), "ignoradas": len(canceladas),
        "planilha_sem_portal": [dict(linha=n, **_desc(l)) for n, l in linhas
                                if not pares[n] and n not in canceladas],
        "portal_sem_planilha": [_desc(p) for i, p in enumerate(pedidos) if i not in usados],
        "nf_divergente": [], "nf_so_no_portal": 0, "campos_divergentes": [], "ambiguas": [],
    }
    inverso = {i: [n for n, indices in pares.items() if i in indices] for i in usados}
    for n, l in linhas:
        if not pares[n] or n in canceladas:
            continue
        if len(pares[n]) != 1 or any(len(inverso[i]) != 1 for i in pares[n]):
            rel["ambiguas"].append(dict(linha=n, **_desc(l), candidatos=len(pares[n])))
        for i in pares[n]:
            for nome in IDENTIDADE + EDITAVEIS:
                a, b = _campo(l, nome), _campo(pedidos[i], nome)
                try:
                    diferente = normalizar(nome, a) != normalizar(nome, b, formato_data_portal(l, pedidos[i]))
                except ValueError:
                    diferente = True
                if diferente:
                    rel["campos_divergentes"].append(dict(linha=n, **_desc(l), campo=nome,
                        planilha=a, portal=b, indice_portal=i))
        na_planilha = nf_de(l)
        no_portal = sorted({nf_de(pedidos[i]) for i in pares[n]} - {""})
        if no_portal and not na_planilha:
            rel["nf_so_no_portal"] += 1
        elif nfs(na_planilha) != set().union(*(nfs(x) for x in no_portal)):
            rel["nf_divergente"].append(dict(linha=n, **_desc(l), nf_planilha=na_planilha,
                                             nf_portal=" / ".join(no_portal)))
    return rel


# -- arquivos ------------------------------------------------------------------

def carregar_ignorar(pasta: str) -> Set[str]:
    arq = Path(pasta) / ARQ_IGNORAR
    if not arq.is_file():
        return set()
    return {item["chave"] for item in json.loads(arq.read_text(encoding="utf-8"))}


def _ler_relatorio(pasta: str) -> Optional[Dict[str, Any]]:
    arq = Path(pasta) / ARQ_RELATORIO
    if not arq.is_file():
        return None
    return json.loads(arq.read_text(encoding="utf-8"))


def resumo_para_tela(pasta: str) -> Optional[Dict[str, Any]]:
    rel = _ler_relatorio(pasta)
    if rel is None:
        return None
    listas = ("planilha_sem_portal", "portal_sem_planilha", "nf_divergente", "campos_divergentes", "ambiguas")
    return dict({k: len(rel.get(k, [])) for k in listas},
                gerado_em=rel["gerado_em"], nf_so_no_portal=rel["nf_so_no_portal"],
                ignoradas=rel["ignoradas"], listas={k: rel.get(k, [])[:MAX_NA_TELA] for k in listas})


def gerar(planilha: str, caminho_pedidos: str, pasta: str) -> Dict[str, Any]:
    from cruzar_nf.arquivo_pedidos import ArquivoPedidosConcorrente

    linhas = ler_planilha_com_linhas(planilha)
    manager = ArquivoPedidosConcorrente(caminho_pedidos)
    manager.iniciar()                      # só lê, com a mesma tolerância do gerenciador
    rel = conferir(linhas, manager.pedidos.get("PEDIDOS", []), carregar_ignorar(pasta))
    arq = Path(pasta) / ARQ_RELATORIO
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(arq))
    return rel


def main(argv: Optional[List[str]] = None) -> int:
    from cruzar_nf.cadastro_pedidos import PLANILHA_PADRAO
    from cruzar_nf.sincronizar import DADOS_PADRAO, PEDIDOS_PADRAO

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(prog="cruzar_nf.planilha_portal", description=__doc__.splitlines()[0])
    ap.add_argument("--planilha", default=os.environ.get("CADASTRO_PLANILHA") or PLANILHA_PADRAO)
    ap.add_argument("--dados", default=os.environ.get("SYNC_NF_DADOS") or DADOS_PADRAO)
    ap.add_argument("--pedidos", default=os.environ.get("SYNC_NF_PEDIDOS") or PEDIDOS_PADRAO)
    ap.add_argument("--diario", action="store_true", help="não faz nada se já conferiu hoje")
    a = ap.parse_args(argv)

    hoje = _dt.date.today().strftime("%d/%m/%Y")
    anterior = _ler_relatorio(a.dados)
    if a.diario and anterior and anterior["gerado_em"].startswith(hoje):
        return 0
    try:
        rel = gerar(a.planilha, a.pedidos, a.dados)
    except Exception as e:      # planilha salvando, rede: tenta de novo na próxima rodada
        print(f"[ERRO] conferência planilha x portal: {e}", file=sys.stderr)
        return 1
    print(f"Conferência planilha x portal: {len(rel['planilha_sem_portal'])} só na planilha, "
          f"{len(rel['portal_sem_planilha'])} só no portal, {len(rel['nf_divergente'])} NF diferente(s), "
          f"{rel['nf_so_no_portal']} NF só no portal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
