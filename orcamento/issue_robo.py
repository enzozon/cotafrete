"""Erro do robô vira issue no GitHub, sozinho.

O repositório é PÚBLICO: a issue leva só texto técnico. Cliente, produto,
preço, CNPJ e números saem; os detalhes ficam no ADM, que pede login.
O mesmo erro (mesma assinatura) vira uma issue só; quando volta, comentário.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx

REPO = "enzozon/cotafrete"
ROTULO = "robo-dav"
MAX_NOVAS_DIA = 5
ADM = "https://cotafrete.ventura.inf.br/adm/dav/"

_ASPAS = re.compile(r"""'[^']*'|"[^"]*"|“[^”]*”""")
_DINHEIRO = re.compile(r"R\$\s*[\d.,]+")
_NUMERO = re.compile(r"\d[\d.,/-]*")
_MAIUSCULAS = re.compile(r"\b[A-ZÀ-Ý0-9/-]{3,}(?:\s+[A-ZÀ-Ý0-9/-]{3,}){2,}\b")  # descrição de produto
_ESPACOS = re.compile(r"\s+")


def limpar(texto, cliente: str = "") -> str:
    t = str(texto or "")
    for palavra in {w for w in re.split(r"\W+", cliente or "") if len(w) >= 4}:
        t = re.sub(re.escape(palavra), "<cliente>", t, flags=re.IGNORECASE)
    t = _ASPAS.sub("'<texto>'", t)
    t = _MAIUSCULAS.sub("<texto>", t)
    t = _DINHEIRO.sub("<valor>", t)
    t = _NUMERO.sub("<n>", t)
    return _ESPACOS.sub(" ", t).strip()


def assinatura(erro, cliente: str = "") -> str:
    """Primeira linha do erro sem dados: o mesmo defeito dá a mesma assinatura."""
    primeira = next((l for l in str(erro or "").splitlines() if l.strip()), "")
    return limpar(primeira, cliente)[:160]


def _corpo(dav: dict, diag: dict, sig: str, codigo: str) -> str:
    cliente = dav.get("cliente") or ""
    return "\n".join([
        f"Aberta sozinha pelo agente de diagnóstico do DAV. Assinatura `{codigo}`.",
        "", "## O que aconteceu", limpar(diag.get("causa"), cliente) or "—",
        "", "## Como possivelmente consertar", limpar(diag.get("conserto"), cliente) or "—",
        "", "## Erro (sem dados)", f"`{sig}`",
        "", "## Onde ver", f"Envio #{int(dav['id'])}: {ADM}{int(dav['id'])} (pede login: print, resposta do HSE e planilha).",
        "", "_Cliente, produto, preço e números foram tirados porque este repositório é público._"])


def registrar_issue(dav: dict, diag: dict, pasta: Path, token: str,
                    post: Callable = httpx.post, agora: datetime | None = None) -> str | None:
    """Abre a issue (ou comenta na que já existe) e devolve a URL; None se o limite do dia barrou."""
    agora = agora or datetime.now()
    arquivo = Path(pasta) / "issues_robo.json"
    reg = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}
    sig = assinatura(dav.get("erro") or diag.get("causa"), dav.get("cliente") or "")
    codigo = hashlib.sha1(sig.encode()).hexdigest()[:10]
    cab = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    item = reg.get(codigo)
    if item:
        if int(dav["id"]) not in item["envios"]:   # "Diagnosticar de novo" não comenta duas vezes
            r = post(f"https://api.github.com/repos/{REPO}/issues/{item['numero']}/comments", headers=cab, timeout=20,
                     json={"body": f"Aconteceu de novo no envio #{int(dav['id'])} ({agora:%d/%m/%Y %H:%M}): "
                                   f"{ADM}{int(dav['id'])}"})
            r.raise_for_status()
            item["envios"].append(int(dav["id"]))
    else:
        dia = agora.date().isoformat()
        novas = reg.setdefault("_novas", {})
        if novas.get(dia, 0) >= MAX_NOVAS_DIA:
            return None
        r = post(f"https://api.github.com/repos/{REPO}/issues", headers=cab, timeout=20,
                 json={"title": f"[robô DAV] {sig[:100]}", "body": _corpo(dav, diag, sig, codigo), "labels": [ROTULO]})
        r.raise_for_status()
        j = r.json()
        item = reg[codigo] = {"numero": j["number"], "url": j["html_url"], "envios": [int(dav["id"])]}
        novas[dia] = novas.get(dia, 0) + 1
    arquivo.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return item["url"]


if __name__ == "__main__":   # confere que nada de cliente/produto/preço passa
    erro = ("falha durante a criação no HSE: Item 1: o HSE recusou o produto 76817 a 8300,94 "
            "(Margem atualizada) MAQUINA FONTE PLASMA 12/16MM cliente VALE S/A 33.592.510/0220-42 R$ 1.234,56")
    s = assinatura(erro, "1061 - VALE S/A/VALE S.A.")
    for proibido in ("76817", "8300", "MAQUINA", "VALE", "33.592", "1.234"):
        assert proibido not in s, (proibido, s)
    print(s)
