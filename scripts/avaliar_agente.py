"""Avalia o agente de diagnóstico do DAV contra envios reais (dados FORA do git).

python scripts/avaliar_agente.py <pasta_dados> [--ia arquivo|api] [--max-usd 1.00]

<pasta_dados>: envios.json, gabarito.json, pedidos.jsonl, vm/<id>.xlsx.
--ia arquivo: respostas pré-gravadas em <pasta_dados>/aval/ia/<id>.json.
--ia api: chama orcamento.agente.diagnosticar; cache em aval/cache_ia/<sha256 das provas>.json.
Sai com 1 se culpa (confiança alta) < 90% ou se houver caso perigoso (criado no HSE, provas dizem []).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orcamento.provas import MARGEM, Achados, coletar, faixa_de_busca  # noqa: E402

LIMITE_ALTA = 0.90


def _iso(s):
    s = (s or "").strip()
    return s.replace(" ", "T") if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$", s) else None


def _numero(e):
    m = re.search(r"Orçamento (\d+)", e["caixa"])
    return int(m.group(1)) if m else None


def _estado(e):
    s, t = e["selo"], e["texto"]
    if "Confira no HSE" in s or "Confira no HSE" in e["caixa"]:
        return "incerto", None
    for ini, est in (("× Erro", "erro"), ("! Planilha", "rejeitado"), ("· Simula", "simulado")):
        if s.startswith(ini):
            return est, None
    if s.startswith("× Com erros"):
        return "rascunho", "erros"
    if s.startswith("· Conferindo"):
        return "rascunho", "ok" if re.search(r"Estado:\s*ok", t) else "conferindo"
    return "pronto", None


def _conf_rel(e):
    t = e["texto"]
    if "Conferência com o HSE" not in t:
        return None
    L = [x.strip() for x in t.split("Conferência com o HSE", 1)[1].split("\n")]
    estado = next((L[k + 1] for k, x in enumerate(L) if x == "Estado:" and k + 1 < len(L)), "")

    def secao(nome):
        if nome not in L:
            return []
        fim = ("Avisos", "Erros", "Cliente no HSE", "Endereço no HSE", "Vendedor no HSE")
        out = []
        for x in L[L.index(nome) + 1:]:
            if x in fim or x.startswith("Robô de Orçamentos"):
                break
            if x:
                out.append(x)
        return out
    rel = next((p for p in e["pres"] if "DRY_RUN" in p), "")
    return json.dumps({"estado": estado, "relatorio": rel, "erros": secao("Erros"), "avisos": secao("Avisos")},
                      ensure_ascii=False)


def montar_dav(e):
    """Reconstrói a linha `dav` a partir do texto extraído das páginas do admin."""
    est, conf = _estado(e)
    pres, d = e["pres"], e["dados"]
    rel = next((p for p in pres if "Modo: REAL" in p), pres[-1] if pres else "")
    texto, erro = e["caixa"] + "\n" + e["texto"], None
    if est in ("erro", "incerto"):
        m = re.search(r"^ERRO:\s*(.*)$", texto, re.M)
        erro = m.group(1) if m else None
    elif est == "rejeitado":
        m = re.search(r"Erro registrado:\s*(.*)", e["texto"])
        erro = m.group(1).strip() if m else None
    return {"id": e["id"], "usuario": d.get("Vendedor"), "arquivo": f"{e['id']}.xlsx", "estado": est, "erro": erro,
            "relatorio": rel, "conferencia": conf, "conferencia_relatorio": _conf_rel(e), "numero": _numero(e),
            "criado_em": _iso(d.get("Envio")), "iniciado_em": _iso(d.get("Início")),
            "terminado_em": _iso(d.get("Conclusão"))}


def fazer_buscador(envios, pedidos_jsonl):
    """Simula o HSE só leitura: mesma faixa (com teto de 60 páginas) que o buscador real."""
    por_num = {p["numero"]: {"numero": p["numero"], "cliente": str(p["cliente"]),
                             "data": p["campos"].get("dtEmissao", ""),
                             "itens": [{"codigo": r[3], "qtd": r[10], "valor": r[12]}
                                       for r in p["itens"] if len(r) > 12]}
               for p in pedidos_jsonl}
    numeros = []
    for e in envios.values():
        hora = next((_iso(e["dados"].get(k)) for k in ("Conclusão", "Início", "Envio") if _iso(e["dados"].get(k))), None)
        if _numero(e) and hora:
            numeros.append((hora, _numero(e)))

    def buscar(cliente, data, perto_de, quando):
        ach = Achados()
        if perto_de is not None:
            faixa = range(perto_de - MARGEM, perto_de + MARGEM + 1)
        else:
            quando = quando or datetime.strptime(data, "%d/%m/%Y").replace(hour=12).isoformat()
            faixa, inteira = faixa_de_busca(numeros, quando), faixa_de_busca(numeros, quando, teto=None)
            if not inteira:
                ach.aviso = "sem referência de número"
            elif len(faixa) < len(inteira):
                ach.aviso = f"faixa cortada: li {faixa.start}..{faixa.stop - 1} de {inteira.start}..{inteira.stop - 1}"
        ach += [por_num[n] for n in faixa
                if n in por_num and por_num[n]["cliente"] == cliente and por_num[n]["data"] == data]
        return ach
    return buscar


def pontuar(linhas):
    """Métricas da spec. Linha: culpa_esp, culpa_obt, conf, criados_esp (bool|None), criados_obt (lista|str)."""
    m = dict.fromkeys(("culpa_ok", "culpa_tot", "alta_ok", "alta_tot", "criados_ok", "criados_tot",
                       "perigosos", "nao_verificado"), 0)
    for r in linhas:
        if r["culpa_esp"] != "teste":   # teste de dev: qualquer culpa coerente serve
            ok = r["culpa_obt"] == r["culpa_esp"]
            m["culpa_tot"] += 1
            m["culpa_ok"] += ok
            if r["conf"] == "alta":
                m["alta_tot"] += 1
                m["alta_ok"] += ok
        esp, obt = r["criados_esp"], r["criados_obt"]
        if isinstance(obt, str):
            m["nao_verificado"] += 1
        elif esp is not None:
            criou = bool(obt) or bool(r.get("outro"))   # pedido, produto ou rascunho
            m["criados_tot"] += 1
            m["criados_ok"] += criou == esp
            m["perigosos"] += bool(esp and not criou)
    return m


def _ia_arquivo(base):
    def obter(i, provas):
        f = base / "aval" / "ia" / f"{i}.json"
        return (json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}), 0.0
    return obter


def _ia_api(base, max_usd):
    from orcamento.agente import diagnosticar
    from dataclasses import replace

    from orcamento.config import config_do_ambiente
    cfg = config_do_ambiente()
    if cfg.ia != "api" or not cfg.ia_chave:
        sys.exit("--ia api exige IA=api e ANTHROPIC_API_KEY no .env")
    # uso vai para a pasta da avaliação, não para o ia_uso.csv de produção
    cfg = replace(cfg, pasta_programa=base / "aval" / "programa", ia_limite_dia=max_usd)
    cfg.pasta_programa.mkdir(parents=True, exist_ok=True)
    cache, gasto = base / "aval" / "cache_ia", [0.0]
    cache.mkdir(parents=True, exist_ok=True)

    def obter(i, provas):
        chave = hashlib.sha256(json.dumps(provas, sort_keys=True, default=str).encode()).hexdigest()
        f = cache / f"{chave}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8")), 0.0
        if gasto[0] >= max_usd:
            return None, 0.0
        res = diagnosticar(provas, cfg)
        gasto[0] += res["custo"]
        f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        return res, res["custo"]
    return obter


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta_dados", type=Path)
    ap.add_argument("--ia", choices=("arquivo", "api"), default="arquivo")
    ap.add_argument("--max-usd", type=float, default=1.00)
    a = ap.parse_args(argv)
    base = a.pasta_dados

    def carregar(nome):
        return json.loads((base / nome).read_text(encoding="utf-8"))
    envios = {e["id"]: e for e in carregar("envios.json")}
    gab = carregar("gabarito.json")
    linhas_ped = (base / "pedidos.jsonl").read_text(encoding="utf-8").splitlines()
    buscar = fazer_buscador(envios, [json.loads(x) for x in linhas_ped if x.strip()])
    obter = _ia_arquivo(base) if a.ia == "arquivo" else _ia_api(base, a.max_usd)
    conhecidos = {i: _numero(e) for i, e in envios.items() if _numero(e)}
    linhas, custos, tempos, pulados = [], [], [], []
    print("| id | estado | culpa esperada | culpa obtida | criados esperado | criados obtido |")
    print("|---|---|---|---|---|---|")
    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)
        (pasta / "entrada").mkdir()
        for g in gab:
            i, e = g["id"], envios[g["id"]]
            dav = montar_dav(e)
            if (base / "vm" / f"{i}.xlsx").exists():
                shutil.copy(base / "vm" / f"{i}.xlsx", pasta / "entrada" / f"{i}.xlsx")
            m = re.search(r"Correção do envio\s*#(\d+)", e["texto"])
            ant = montar_dav(envios[int(m.group(1))]) if m and int(m.group(1)) in envios else None
            provas = coletar(dav, pasta, buscar, {n for k, n in conhecidos.items() if k != i}, ant)
            t0 = time.time()
            ia, custo = obter(i, provas)
            if ia is None:
                pulados.append(i)
                print(f"| {i} | {dav['estado']} | {g['culpa']} | PULADO (limite --max-usd atingido) | | |")
                continue
            if custo:
                custos.append(custo)
                tempos.append(time.time() - t0)
            r = {"culpa_esp": g["culpa"], "culpa_obt": ia.get("culpa"), "conf": g["confianca"],
                 "criados_esp": g.get("suspeita_criado_no_hse"), "criados_obt": provas["criados_no_hse"],
                 "outro": bool(provas.get("produtos_criados") or provas.get("rascunhos"))}
            linhas.append(r)
            print(f"| {i} | {dav['estado']} | {r['culpa_esp']} | {r['culpa_obt']} | "
                  f"{r['criados_esp']} | {r['criados_obt']} |")
    m = pontuar(linhas)

    def pct(x, y):
        return f"{x}/{y} = {x / max(y, 1):.0%}"
    print(f"\nculpa geral: {pct(m['culpa_ok'], m['culpa_tot'])}")
    print(f"culpa confiança alta: {pct(m['alta_ok'], m['alta_tot'])}")
    print(f"criados corretos: {pct(m['criados_ok'], m['criados_tot'])}")
    print(f"perigosos (criado esperado, obtido []): {m['perigosos']}")
    print(f"nao_verificado: {m['nao_verificado']}")
    if pulados:
        print(f"limite --max-usd atingido: {len(pulados)} envios pulados (fora das métricas): {pulados}")
    if custos:
        print(f"custo médio: US$ {sum(custos) / len(custos):.4f} | tempo médio: {sum(tempos) / len(tempos):.1f}s")
    falhas = []
    if m["alta_ok"] < LIMITE_ALTA * m["alta_tot"]:
        falhas.append("culpa alta < 90%")
    if m["perigosos"]:
        falhas.append("perigosos > 0")
    print("LIMIARES:", "FALHOU: " + ", ".join(falhas) if falhas else "ok")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
