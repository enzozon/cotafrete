"""Abrir a cotação do ME já na conta certa — a extensão do Chrome e as rotas dela.

O problema (29/09/2026): o "Abrir no ME" abria a cotação na conta que
estivesse logada no navegador, e o ME ignora a tela de login de quem já está
logado. A saída, escolhida pelo Enzo, é a "opção 2": o servidor faz um login
novo e a extensão põe SÓ a sessão no Chrome do vendedor — a senha nunca sai
do servidor (mercado_eletronico/sessao_me.py).

- `GET /me-extensao`: como instalar (modo desenvolvedor + "Carregar sem
  compactação", decisão do Enzo).
- `GET /me-extensao/cotafrete-me.zip`: o pacote, gerado com o ENDEREÇO de
  quem baixou — o Chrome só aceita endereços fixos no manifesto, e cada
  máquina acessa o CotaFrete pelo endereço da VM.
- `POST /me/{cid}/sessao-me`: a sessão da conta daquela cotação, só para
  vendedor logado no CotaFrete (todos podem abrir as 14 contas — Enzo,
  29/09/2026). Fica no histórico da cotação quem abriu e quando.

Fora de `/me/...` de propósito no que é GET: `/me/{cid}` pegaria
"/me/extensao" e responderia 422.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from mercado_eletronico import logins as L
from mercado_eletronico import sessao_me
from web.layout import cabecalho, e, pagina

router = APIRouter(include_in_schema=False)
PASTA = Path(__file__).parent / "extensao_me"
NOME_ZIP = "cotafrete-me.zip"
SEM_CACHE = {"Cache-Control": "no-store"}

# Os testes trocam por um falso: nada de login de verdade no ME.
SESSAO_ME: Callable[[str], list[dict]] = sessao_me.sessao_nova


def padrao_do_endereco(request: Request) -> str:
    """"http://192.168.0.10/*": o endereço do CotaFrete como o Chrome aceita
    no manifesto (sem porta — o padrão vale para todas)."""
    return f"{request.url.scheme}://{request.url.hostname}/*"


def manifesto(padrao: str) -> dict:
    return {
        "manifest_version": 3,
        "name": "CotaFrete - Abrir no ME",
        "version": "1.0",
        "description": "Abre a cotação do Mercado Eletrônico já na conta certa. "
                       "A senha não passa pelo navegador: o CotaFrete entrega só a sessão.",
        "key": sessao_me.CHAVE_PUBLICA,
        "permissions": ["cookies", "tabs"],
        "host_permissions": ["https://www.me.com.br/*", padrao],
        "background": {"service_worker": "background.js"},
        "externally_connectable": {"matches": [padrao]},
    }


def pacote(padrao: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("cotafrete-me/manifest.json", json.dumps(manifesto(padrao), ensure_ascii=False, indent=2))
        z.writestr("cotafrete-me/background.js", (PASTA / "background.js").read_text(encoding="utf-8"))
    return buf.getvalue()


def _me_ui():
    from web import me_ui   # tardio: me_ui recebe banco/vendedor do web/app.py
    return me_ui


@router.get("/me-extensao/cotafrete-me.zip")
def baixar(request: Request):
    if not _me_ui()._usuario(request):
        return RedirectResponse("/login", status_code=303)
    return Response(pacote(padrao_do_endereco(request)), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{NOME_ZIP}"', **SEM_CACHE})


@router.get("/me-extensao", response_class=HTMLResponse)
def instalar(request: Request):
    usuario = _me_ui()._usuario(request)
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    corpo = f"""{cabecalho("Abrir no ME na conta certa", tarja="Mercado Eletrônico · extensão do Chrome",
                          sub='Instala uma vez em cada Chrome. Depois, o botão "Abrir no ME" da cotação '
                              'abre o ME já logado na conta dela, sem digitar senha.')}
<div class="cartao" style="padding:16px 20px">
<ol class="passos">
<li><a class="botao" href="/me-extensao/{NOME_ZIP}">Baixar a extensão</a> e <b>descompactar</b> o arquivo
 numa pasta que não vai ser apagada (por exemplo, Documentos\\cotafrete-me).</li>
<li>No Chrome, abrir <code>chrome://extensions</code> (copie e cole na barra de endereço).</li>
<li>Ligar o <b>Modo do desenvolvedor</b>, no canto de cima à direita.</li>
<li>Clicar em <b>Carregar sem compactação</b> e escolher a pasta <b>cotafrete-me</b> que foi descompactada.</li>
<li>Pronto: volte ao CotaFrete, abra uma cotação do ME e clique em <b>Abrir no ME</b>.</li>
</ol>
<p class="sub">A extensão só atende páginas deste endereço ({e(padrao_do_endereco(request))}) e só funciona
 com você logado no CotaFrete. A senha das contas do ME nunca vai para o navegador.
 Se o endereço do CotaFrete mudar, baixe e carregue de novo.</p>
</div>"""
    return HTMLResponse(pagina("Extensão do ME", corpo, usuario))


@router.post("/me/{cid}/sessao-me")
def sessao(cid: int, request: Request):
    ui = _me_ui()
    usuario = ui._usuario(request)
    if not usuario:
        return JSONResponse({"erro": "entre no CotaFrete primeiro"}, status_code=401, headers=SEM_CACHE)
    c = ui.banco.me_cotacao(cid)
    if not c:
        return JSONResponse({"erro": "cotação não encontrada"}, status_code=404, headers=SEM_CACHE)
    rotulo = L.de(c["conta"]).rotulo
    try:
        cookies = SESSAO_ME(c["conta"])
    except Exception as exc:  # ME fora, login recusado: o vendedor vê o motivo
        ui.banco.me_registrar(cid, "abrir no ME falhou", f"{rotulo}: {type(exc).__name__}", usuario)
        return JSONResponse({"erro": f"não consegui entrar na conta {rotulo} do ME agora: {exc}"[:300]},
                            status_code=502, headers=SEM_CACHE)
    ui.banco.me_registrar(cid, "aberta no ME na conta certa", rotulo, usuario)
    return JSONResponse({"url": sessao_me.url_da_cotacao(c["numero"]), "cookies": cookies},
                        headers=SEM_CACHE)
