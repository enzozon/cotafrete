"""Tela Gerar DAV: /dav (enviar, conferir, gerar, acompanhar, baixar o PDF).

O robô e a fila moram em orcamento/ (fila.py); aqui só a porta do vendedor.
`banco`, `vendedor` e `FILA` são injetados por web/app.py (importar web.app
daqui seria circular), como em web/me_ui.py.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from core.banco import Banco
from orcamento.fila import FilaDav
from orcamento.planilha import ErroPlanilha, ler_planilha
from web import adm
from web.layout import e, pagina

banco: Banco | None = None
vendedor: Callable[[str | None], str | None] | None = None
FILA: FilaDav | None = None
COOKIE = "cotafrete_usuario"

MAX_BYTES = 5 * 1024 * 1024
MODELO = Path(__file__).resolve().parent.parent / "orcamento" / "modelo" / "PLANILHA-BASE-v3.xlsx"
ESTADOS = {"rascunho": "Conferindo", "fila": "Na fila", "gerando": "Gerando no HSE",
           "pronto": "Pronto", "erro": "Erro", "incerto": "Confira no HSE",
           "simulado": "Simulação (nada salvo)"}
# ponytail: uma trava global; basta para uma VM com poucos vendedores.
_TRAVA = threading.Lock()

router = APIRouter(prefix="/dav", include_in_schema=False)


def _quem(usuario: str | None = Cookie(None, alias=COOKIE)):
    return vendedor(usuario)


def _login():
    return RedirectResponse("/login", status_code=303)


def _html(titulo: str, corpo: str, usuario: str | None) -> HTMLResponse:
    return HTMLResponse(pagina(titulo, corpo, usuario))


def pdf_link(d: dict) -> str:
    return f'<a href="/dav/{d["id"]}/pdf">PDF</a>' if d["pdf"] else ""


def tabela_davs(linhas: list[dict], com_vendedor: bool = False) -> str:
    if not linhas:
        return '<p class="sub">Nenhum DAV ainda.</p>'
    cab = ("<th>Data</th>" + ("<th>Vendedor</th>" if com_vendedor else "")
           + "<th>Arquivo</th><th>Cliente</th><th>Número</th><th>Estado</th><th>PDF</th><th></th>")
    corpo = "".join(
        f"<tr><td>{e((d['criado_em'] or '')[:16].replace('T', ' '))}</td>"
        + (f"<td>{e(d['usuario'])}</td>" if com_vendedor else "")
        + f"<td>{e(d['arquivo'])}</td><td>{e(d['cliente'] or '')}</td>"
        f"<td>{e(d['numero'] or '')}</td><td>{e(ESTADOS.get(d['estado'], d['estado']))}</td>"
        f'<td>{pdf_link(d)}</td>'
        f'<td><a href="/dav/{d["id"]}">abrir</a></td></tr>' for d in linhas)
    return f"<table><thead><tr>{cab}</tr></thead><tbody>{corpo}</tbody></table>"


def _tela_envio(usuario: str, aviso: str = "") -> HTMLResponse:
    corpo = f"""<h1>Gerar DAV</h1>
{aviso}
<form method="post" action="/dav/conferir" enctype="multipart/form-data" class="cartao">
  <p>Envie a PLANILHA-BASE v3 (.xlsx, até 5 MB). <a href="/dav/modelo">Baixar o modelo v3</a></p>
  <input type="file" name="planilha" accept=".xlsx" required>
  <button type="submit">Conferir</button>
</form>
<h2>Seus DAVs</h2>{tabela_davs(banco.davs(usuario))}"""
    return _html("Gerar DAV", corpo, usuario)


def _erro(usuario: str, *msgs: str) -> HTMLResponse:
    itens = "".join(f"<li>{e(m)}</li>" for m in msgs)
    return _tela_envio(usuario, f'<div class="alerta"><ul>{itens}</ul></div>')


def _ja_gerou(usuario: str, antigo: dict) -> HTMLResponse:
    n = antigo["numero"] or f"(DAV {antigo['id']})"
    aviso = (f'<div class="alerta">Esta planilha já gerou o orçamento {e(n)}. '
             f'<a href="/dav/{antigo["id"]}">Ver</a></div>')
    return _tela_envio(usuario, aviso)


@router.get("", response_class=HTMLResponse)
def inicio(usuario: str | None = Depends(_quem)):
    if not usuario:
        return _login()
    return _tela_envio(usuario)


@router.get("/modelo")
def modelo(usuario: str | None = Depends(_quem)):
    if not usuario:
        return _login()
    return FileResponse(MODELO, filename=MODELO.name)


def _resumo(o, dav_id: int) -> str:
    itens = "".join(
        f"<tr><td>{i.numero}</td><td>{e(i.produto)}</td><td>{e(i.quantidade)}</td>"
        f"<td>{e(i.valor_unit)}</td><td>"
        f"{e(i.codigo) if i.codigo else 'procurar pela descrição / cadastrar se não existir'}"
        "</td></tr>" for i in o.itens)
    avisos = "".join(f'<div class="aviso">{e(a)}</div>' for a in o.avisos)
    prazo = o.prazo_dias if o.prazo_dias is not None else ""
    return f"""<h1>Conferir</h1>{avisos}
<dl><dt>Cliente</dt><dd>{e(o.cliente)}</dd><dt>Vendedor</dt><dd>{e(o.vendedor)}</dd>
<dt>Filial</dt><dd>{e(o.filial)}</dd>
<dt>Pagamento</dt><dd>{e(o.forma_pg or '')} {e(o.parcelamento or '')}</dd>
<dt>Prazo (dias)</dt><dd>{e(prazo)}</dd>
<dt>OC</dt><dd>{e(o.ordem_compra or '')}</dd><dt>Observações</dt><dd>{e(o.observacoes)}</dd></dl>
<table><thead><tr><th>#</th><th>Produto</th><th>Qtd</th><th>Valor unit.</th><th>Código HSE</th></tr></thead>
<tbody>{itens}</tbody></table>
<form method="post" action="/dav/{dav_id}/gerar"><button type="submit">Gerar</button></form>"""


@router.post("/conferir", response_class=HTMLResponse)
def conferir(planilha: UploadFile = File(...),
                   usuario: str | None = Depends(_quem)):
    if not usuario:
        return _login()
    nome = Path(planilha.filename or "planilha.xlsx").name
    if not nome.lower().endswith(".xlsx"):
        return _erro(usuario, "Envie um arquivo .xlsx (a PLANILHA-BASE v3).")
    dados = planilha.file.read(MAX_BYTES + 1)
    if len(dados) > MAX_BYTES:
        return _erro(usuario, "O arquivo passa de 5 MB.")
    hash_ = hashlib.sha256(dados).hexdigest()
    pasta = FILA.pasta / "entrada"
    pasta.mkdir(parents=True, exist_ok=True)
    temp = pasta / f"{uuid.uuid4().hex}.xlsx"
    temp.write_bytes(dados)
    try:
        try:
            o = ler_planilha(temp)
        except ErroPlanilha as exc:
            return _erro(usuario, *exc.erros)
        except Exception:
            return _erro(usuario, "Não consegui abrir o arquivo. "
                                  "É a PLANILHA-BASE v3 em .xlsx?")
        with _TRAVA:
            antigo = banco.dav_ja_gerado(usuario, hash_)
            if antigo:
                return _ja_gerou(usuario, antigo)
            dav_id = banco.dav_criar(usuario, nome, hash_, o.cliente)
            temp.replace(FILA.planilha(dav_id))
        return _html("Conferir DAV", _resumo(o, dav_id), usuario)
    finally:
        temp.unlink(missing_ok=True)


@router.post("/{dav_id}/gerar", response_class=HTMLResponse)
def gerar(dav_id: int, usuario: str | None = Depends(_quem)):
    if not usuario:
        return _login()
    with _TRAVA:
        d = banco.dav(dav_id, usuario)
        if d is None:
            raise HTTPException(404)
        if d["estado"] != "rascunho":
            return RedirectResponse(f"/dav/{dav_id}", status_code=303)
        antigo = banco.dav_ja_gerado(usuario, d["hash_planilha"])
        if antigo:
            return _ja_gerou(usuario, antigo)
        banco.dav_atualizar(dav_id, estado="fila")   # antes: o robô só pega "fila"
        FILA.enfileirar(dav_id)
    return RedirectResponse(f"/dav/{dav_id}", status_code=303)


def _acesso(dav_id: int, usuario: str | None, cookie_adm: str | None):
    """(dav, redirecionamento): o admin vê qualquer um, o vendedor só os seus."""
    admin = adm.autorizado(cookie_adm)
    if not usuario and not admin:
        return None, _login()
    d = banco.dav(dav_id, None if admin else usuario)
    if d is None:
        raise HTTPException(404)
    return d, None


@router.get("/{dav_id}", response_class=HTMLResponse)
def ver(dav_id: int, usuario: str | None = Depends(_quem),
        cookie_adm: str | None = Cookie(None, alias=adm.COOKIE_ADM)):
    d, ir = _acesso(dav_id, usuario, cookie_adm)
    if ir:
        return ir
    est = d["estado"]
    meta = '<meta http-equiv="refresh" content="5">' if est in ("fila", "gerando") else ""
    corpo = (f"{meta}<h1>DAV {d['id']} — {e(ESTADOS.get(est, est))}</h1>"
             f"<p>{e(d['arquivo'])} · {e(d['cliente'] or '')}</p>")
    if est == "fila":
        pos = 1 + sum(1 for x in banco.davs(None)
                      if x["estado"] == "fila" and x["id"] < dav_id)
        corpo += f"<p>Posição na fila: {pos}</p>"
    if est == "incerto":
        quando = (f'confira no HSE o orçamento {e(d["numero"])} e não gere de novo.'
                  if d["numero"] else
                  "Confira no HSE os orçamentos deste cliente de hoje antes de gerar de novo.")
        corpo += f'<div class="alerta"><b>Não sei se este DAV foi salvo: {quando}</b></div>'

    if est == "pronto":
        corpo += f'<p>Orçamento <b>{e(d["numero"] or "")}</b></p>'
        if d["pdf"]:
            corpo += f'<p><a class="botao2" href="/dav/{d["id"]}/pdf">Baixar PDF</a></p>'
    if est in ("erro", "incerto") and d["erro"]:
        corpo += f'<div class="alerta">{e(d["erro"])}</div>'
    if d["relatorio"]:
        corpo += f"<pre>{e(d['relatorio'])}</pre>"
    return _html("DAV", corpo + '<p><a href="/dav">Voltar</a></p>', usuario)


@router.get("/{dav_id}/pdf")
def pdf(dav_id: int, usuario: str | None = Depends(_quem),
        cookie_adm: str | None = Cookie(None, alias=adm.COOKIE_ADM)):
    d, ir = _acesso(dav_id, usuario, cookie_adm)
    if ir:
        return ir
    if not d["pdf"]:
        raise HTTPException(404)
    caminho = Path(d["pdf"]).resolve()
    if not caminho.is_relative_to((FILA.pasta / "pdf").resolve()) or not caminho.is_file():
        raise HTTPException(404)
    return FileResponse(caminho, media_type="application/pdf", filename=caminho.name)
