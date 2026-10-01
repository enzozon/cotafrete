"""Busca no HSE Sistemas as NFs que explicam as divergências de valor.

Para cada pedido do DIVERGENCIAS_VALOR.json (gerado a partir do
RELATORIO_NF.json), procura em Fiscal -> Notas fiscais uma NF de saída
autorizada com valor IGUAL ao valor absoluto da diferença (Valor Inicial =
Valor Final), em todas as empresas. Foi assim que a diferença de R$ 28.230,00
do pedido 4500249590 achou a NF 13768.

Rodar:

    python -m cruzar_nf.busca_hse --pasta C:\\...\\planilha_estagiarios

Abre uma janela do navegador. Faça o login no HSE você mesmo e abra
Fiscal -> Notas fiscais; a ferramenta espera e faz o resto. Nenhuma senha
passa pelo programa: a sessão fica guardada no perfil do navegador em
%LOCALAPPDATA%\\cruzar_nf\\perfil_hse (apague a pasta para "deslogar").

Saída, na mesma pasta: BUSCA_HSE_DIVERGENCIAS.json e .md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

URL_HSE = "https://app.hsesistemas.com.br/"
MOTOR_JS = Path(__file__).with_name("busca_hse.js")
ESPERA_LOGIN_S = 15 * 60

# Empresas do próprio grupo: NF entre elas é transferência, não venda ao cliente
GRUPO = ("VENTURA", "UNIAO COMERCIO", "ALIANCA COMERCIO")

EXPLICADA = "EXPLICADA"        # a NF achada já é uma das NFs do ERP daquela OC
CANDIDATA = "CANDIDATA"        # mesmo estado do pedido, cliente de fora do grupo: conferir
COINCIDENCIA = "COINCIDENCIA"  # só o valor bate (outro estado ou transferência do grupo)
NAO_ACHOU = "NAO_ACHOU"

ROTULO = {
    CANDIDATA: "✅ candidata (conferir)",
    EXPLICADA: "🟦 explicada (NF já está no ERP)",
    COINCIDENCIA: "⚪ só coincidência de valor",
    NAO_ACHOU: "❌ não achou",
}


# --------------------------------------------------------------------------
# classificação (sem navegador: testável)
# --------------------------------------------------------------------------

def uf_da_cidade(cidade: Any) -> str | None:
    """'MARIANA - MG' -> 'MG'; 'ANANINDEUA-PA' -> 'PA'."""
    m = re.search(r"([A-Za-z]{2})\s*$", str(cidade or ""))
    return m.group(1).upper() if m else None


def _do_grupo(nome: Any) -> bool:
    texto = str(nome or "").upper()
    return any(g in texto for g in GRUPO)


def classificar(pedido: dict, notas: list[dict]) -> tuple[str, str]:
    """(conclusão, observação) para as NFs que o HSE devolveu para um pedido."""
    if not notas:
        return NAO_ACHOU, "Nenhuma NF de saída autorizada com esse valor exato no período."
    nfs_erp = set(re.findall(r"\d+", str(pedido.get("nfs") or "")))
    ja_no_erp = [n for n in notas if n.get("nota") in nfs_erp]
    if ja_no_erp:
        lista = ", ".join(n["nota"] for n in ja_no_erp)
        return EXPLICADA, (f"A NF {lista} já é uma das NFs do ERP desta OC: a planilha "
                           "não somou essa NF (valor da planilha desatualizado).")
    uf = uf_da_cidade(pedido.get("cidade"))
    candidatas = [n for n in notas if not _do_grupo(n.get("destinatario"))
                  and (uf is None or (n.get("uf") or "").upper() == uf)]
    if candidatas:
        lista = ", ".join(f"{n['nota']} ({n['destinatario']})" for n in candidatas)
        return CANDIDATA, (f"NF(s) {lista} no mesmo estado do pedido e fora do grupo. "
                           "Conferir se o cliente é o do pedido: se for, é a NF que falta "
                           "ligar a esta OC no ERP.")
    return COINCIDENCIA, "Só o valor bate: NF para outro estado ou transferência entre empresas do grupo."


# --------------------------------------------------------------------------
# relatório
# --------------------------------------------------------------------------

def _brl(texto: Any) -> str:
    v = Decimal(str(texto))
    inteiro, cent = f"{abs(v):,.2f}".split(".")
    return f"{'-' if v < 0 else ''}R$ {inteiro.replace(',', '.')},{cent}"


def montar_md(dados: dict) -> str:
    res = dados["resultados"]
    cont = Counter(r["conclusao"] for r in res)
    linhas = [
        "# Busca das diferenças de valor no HSE Sistemas", "",
        f"Gerado em {dados['gerado_em'][:16].replace('T', ' ')}. {len(res)} pedidos.", "",
        "**Filtros** (Fiscal → Notas fiscais): "
        + ", ".join(f"{k}: {v}" for k, v in dados["filtros"].items()) + ".", "",
        "## Resumo", "", "| resultado | pedidos |", "|---|---|",
        *[f"| {ROTULO[k]} | {cont[k]} |" for k in (CANDIDATA, EXPLICADA, COINCIDENCIA, NAO_ACHOU)],
        "", "## Todos os pedidos", "",
        "| # | pedido | cidade | NF(s) no ERP | diferença | NF achada no HSE | resultado |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(res, 1):
        achadas = "; ".join(f"{n['nota']} ({n['empresa'].split()[0]}, {n['emissao']}, {n['destinatario']})"
                            for n in r["notas_hse"]) or "-"
        linhas.append(f"| {i} | {r['oc']} | {r.get('cidade') or '-'} | {r.get('nfs') or '-'} | "
                      f"{_brl(r['diferenca'])} | {achadas} | {ROTULO[r['conclusao']]} |")
    for chave in (CANDIDATA, EXPLICADA, COINCIDENCIA):
        grupo = [r for r in res if r["conclusao"] == chave]
        if not grupo:
            continue
        linhas += ["", f"## {ROTULO[chave]}", ""]
        for r in grupo:
            linhas.append(f"- **{r['oc']}** ({r.get('cidade')}, diferença {_brl(r['diferenca'])}): {r['observacao']}")
            for n in r["notas_hse"]:
                linhas.append(f"  - NF {n['nota']} série {n['serie']} — {n['empresa']} — {n['emissao']} — "
                              f"{n['origem']} — CFOP {n['cfop']} — {n['destinatario']} "
                              f"(CNPJ {n['cnpj']}, {n['uf']}) — R$ {n['valor']}")
    erros = [r for r in res if r.get("erro")]
    if erros:
        linhas += ["", "## Buscas que falharam", ""]
        linhas += [f"- {r['oc']}: {r['erro']}" for r in erros]
    return "\n".join(linhas) + "\n"


# --------------------------------------------------------------------------
# navegador
# --------------------------------------------------------------------------

def _frame_notas(page):
    for frame in page.frames:
        try:
            if frame.query_selector("#formFiltro"):
                return frame
        except Exception:  # frame recarregando
            continue
    return None


def _esperar_tela(page):
    """Espera o login (feito pela pessoa) e a tela de Notas fiscais aberta."""
    print("\n>> Na janela que abriu: faça o login no HSE e abra Fiscal -> Notas fiscais.")
    tentou_menu = False
    fim = time.time() + ESPERA_LOGIN_S
    while time.time() < fim:
        frame = _frame_notas(page)
        if frame:
            return frame
        if not tentou_menu and page.query_selector("text=Notas fiscais") is None \
                and page.query_selector("text=Fiscal"):
            tentou_menu = True   # logado: tenta abrir o menu uma vez, sem insistir
            try:
                page.click("text=Fiscal", timeout=3000)
                page.click("text=Notas fiscais", timeout=3000)
            except Exception:
                pass
        time.sleep(2)
    raise TimeoutError("A tela de Notas fiscais não apareceu em 15 minutos.")


def buscar_no_hse(valores: list[Decimal], desde: str, ate: str, perfil: Path,
                  ao_buscar=None) -> list[dict]:
    from playwright.sync_api import sync_playwright

    perfil.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(perfil), headless=False,
                                                    viewport={"width": 1500, "height": 850})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(URL_HSE)
            frame = _esperar_tela(page)
            motor = frame.evaluate_handle(MOTOR_JS.read_text(encoding="utf-8"))
            motor.evaluate("(m, a) => m.configurar(a[0], a[1])", [desde, ate])
            saida = []
            for i, v in enumerate(valores, 1):
                r = motor.evaluate("(m, a) => m.buscar(a[0], a[1])", [float(v), 30000])
                saida.append(r)
                if ao_buscar:
                    ao_buscar(i, len(valores), v, r)
            return saida
        finally:
            ctx.close()


def rodar(pasta: Path, desde: str, ate: str, perfil: Path) -> dict:
    entrada = pasta / "DIVERGENCIAS_VALOR.json"
    pedidos = json.loads(entrada.read_text(encoding="utf-8"))
    valores = [abs(Decimal(str(p["diferenca"]))) for p in pedidos]

    def progresso(i, total, v, r):
        n = len(r.get("notas") or [])
        print(f"  [{i:>2}/{total}] {pedidos[i-1]['oc']:>12}  {_brl(v):>14}  "
              f"{r.get('erro') or f'{n} NF(s)'}")

    respostas = buscar_no_hse(valores, desde, ate, perfil, progresso)
    resultados = []
    for p, v, r in zip(pedidos, valores, respostas):
        notas = r.get("notas") or []
        conclusao, obs = classificar(p, notas)
        resultados.append({**p, "valor_buscado": f"{v:.2f}", "notas_hse": notas,
                           "conclusao": conclusao, "observacao": obs, "erro": r.get("erro")})
    dados = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "filtros": {"modelo": "55 - NFe", "filiais": "todas", "operação": "Saída",
                    "status": "Autorizadas", "emissão": f"{desde} a {ate}",
                    "valor": "= |diferença| (Valor Inicial = Valor Final)"},
        "resultados": resultados,
    }
    (pasta / "BUSCA_HSE_DIVERGENCIAS.json").write_text(
        json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    (pasta / "BUSCA_HSE_DIVERGENCIAS.md").write_text(montar_md(dados), encoding="utf-8")
    return dados


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cruzar_nf.busca_hse", description=__doc__.splitlines()[0])
    ap.add_argument("--pasta", default=".", help="pasta com o DIVERGENCIAS_VALOR.json")
    ap.add_argument("--desde", default="01/01/2025", help="emissão inicial (dd/mm/aaaa)")
    ap.add_argument("--ate", default=date.today().strftime("%d/%m/%Y"), help="emissão final")
    ap.add_argument("--perfil", default=os.path.join(os.environ.get("LOCALAPPDATA", "."),
                                                     "cruzar_nf", "perfil_hse"))
    args = ap.parse_args(argv)
    pasta = Path(args.pasta)
    if not (pasta / "DIVERGENCIAS_VALOR.json").is_file():
        print(f"[ERRO] não achei {pasta / 'DIVERGENCIAS_VALOR.json'}", file=sys.stderr)
        return 1
    dados = rodar(pasta, args.desde, args.ate, Path(args.perfil))
    cont = Counter(r["conclusao"] for r in dados["resultados"])
    print("\n" + "\n".join(f"  {ROTULO[k]}: {cont[k]}" for k in (CANDIDATA, EXPLICADA, COINCIDENCIA, NAO_ACHOU)))
    print(f"\n  Relatório: {pasta / 'BUSCA_HSE_DIVERGENCIAS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
