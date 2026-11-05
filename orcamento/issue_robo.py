"""Erro do robô vira issue no GitHub, sozinho.

O repositório é PÚBLICO: a issue leva só texto técnico. Cliente, produto,
preço, CNPJ e números saem; os detalhes ficam no ADM, que pede login.
O mesmo erro (mesma assinatura) vira uma issue só; quando volta, comentário.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable


REPO = "enzozon/cotafrete"
ROTULO = "robo-dav"
MAX_NOVAS_DIA = 5
ADM = "https://cotafrete.ventura.inf.br/adm/dav/"


def _post(*a, **k):
    import httpx   # só na hora: o job de CI cruzar-nf-py38 não instala httpx e o conftest importa este módulo
    return httpx.post(*a, **k)

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


_TRAVA = threading.Lock()   # cotações rodam em várias threads; o registro é um arquivo só


def codigo_de(sig: str) -> str:
    return hashlib.sha1(sig.encode()).hexdigest()[:10]


def publicar(pasta: Path, sig: str, titulo: str, corpo: Callable[[str], str], ref, comentario: str,
             token: str, post: Callable = _post, agora: datetime | None = None,
             rotulo: str = ROTULO) -> str | None:
    """Abre a issue da assinatura `sig` (ou comenta na que já existe) e devolve a URL.

    `ref` identifica a ocorrência (envio, cotação): a mesma ref não comenta duas vezes.
    None quando o limite de issues novas do dia barrou."""
    agora = agora or datetime.now()
    arquivo = Path(pasta) / "issues_robo.json"
    codigo = codigo_de(sig)
    cab = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    with _TRAVA:
        reg = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}
        item = reg.get(codigo)
        if item:
            if ref in item["envios"]:
                return item["url"]
            r = post(f"https://api.github.com/repos/{REPO}/issues/{item['numero']}/comments", headers=cab,
                     timeout=20, json={"body": f"Aconteceu de novo em {comentario} ({agora:%d/%m/%Y %H:%M})."})
            r.raise_for_status()
            item["envios"].append(ref)
        else:
            dia = agora.date().isoformat()
            novas = reg.setdefault("_novas", {})
            if novas.get(dia, 0) >= MAX_NOVAS_DIA:
                return None
            r = post(f"https://api.github.com/repos/{REPO}/issues", headers=cab, timeout=20,
                     json={"title": titulo[:120], "body": corpo(codigo), "labels": [rotulo]})
            r.raise_for_status()
            j = r.json()
            item = reg[codigo] = {"numero": j["number"], "url": j["html_url"], "envios": [ref]}
            novas[dia] = novas.get(dia, 0) + 1
        Path(pasta).mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return item["url"]


def registrar_issue(dav: dict, diag: dict, pasta: Path, token: str,
                    post: Callable = _post, agora: datetime | None = None) -> str | None:
    """Erro do robô do DAV: abre a issue (ou comenta) e devolve a URL; None se o limite do dia barrou."""
    sig = assinatura(dav.get("erro") or diag.get("causa"), dav.get("cliente") or "")
    i = int(dav["id"])   # "Diagnosticar de novo" no mesmo envio não comenta duas vezes
    return publicar(pasta, sig, f"[robô DAV] {sig[:100]}", lambda codigo: _corpo(dav, diag, sig, codigo), i,
                    f"o envio #{i}: {ADM}{i}", token, post, agora)


if __name__ == "__main__":   # confere que nada de cliente/produto/preço passa
    erro = ("falha durante a criação no HSE: Item 1: o HSE recusou o produto 76817 a 8300,94 "
            "(Margem atualizada) MAQUINA FONTE PLASMA 12/16MM cliente VALE S/A 33.592.510/0220-42 R$ 1.234,56")
    s = assinatura(erro, "1061 - VALE S/A/VALE S.A.")
    for proibido in ("76817", "8300", "MAQUINA", "VALE", "33.592", "1.234"):
        assert proibido not in s, (proibido, s)
    print(s)
