"""Tela Gerar DAV: /dav (enviar, conferir, gerar, acompanhar, baixar o PDF).

O robô e a fila moram em orcamento/ (fila.py); aqui só a porta do vendedor.
`banco`, `vendedor` e `FILA` são injetados por web/app.py (importar web.app
daqui seria circular), como em web/me_ui.py.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from core.banco import Banco
from core import painel_dav
from orcamento.fila import FilaDav
from orcamento.diagnostico import diagnostico
from orcamento.planilha import ErroPlanilha, ler_planilha
from web import adm
from web.layout import CSS_DAV, cabecalho, e, pagina

banco: Banco | None = None
vendedor: Callable[[str | None], str | None] | None = None
FILA: FilaDav | None = None
COOKIE = "cotafrete_usuario"

MAX_BYTES = 5 * 1024 * 1024
MODELO = Path(__file__).resolve().parent.parent / "orcamento" / "modelo" / "PLANILHA-BASE-v3.xlsx"
ESTADOS = {"rascunho": "Conferindo", "fila": "Na fila", "gerando": "Gerando no HSE",
           "pronto": "Pronto", "erro": "Erro", "incerto": "Confira no HSE",
           "simulado": "Simulação (nada salvo)", "rejeitado": "Planilha não aceita"}
# ponytail: uma trava global; basta para uma VM com poucos vendedores.
_TRAVA = threading.Lock()

router = APIRouter(prefix="/dav", include_in_schema=False)

SCRIPT_ACOES = """<script>
document.addEventListener('submit', ev => {
  const form = ev.target.closest('[data-dav-envio]');
  if (!form) return;
  if (form.dataset.enviando) { ev.preventDefault(); return; }
  form.dataset.enviando = '1';
  form.querySelectorAll('button[type="submit"]').forEach(b => { b.disabled = true; b.textContent = 'Aguarde…'; });
});
document.addEventListener('click', async ev => {
  if (!ev.target.closest('[data-dav-copiar]')) return;
  const texto = document.getElementById('dav-diagnostico');
  const status = document.getElementById('dav-copiado');
  try { await navigator.clipboard.writeText(texto.textContent); status.textContent = 'Diagnóstico copiado.'; }
  catch (erro) { status.textContent = 'Selecione e copie o diagnóstico acima.'; }
});
</script>"""


def _quem(usuario: str | None = Cookie(None, alias=COOKIE)):
    return vendedor(usuario)


def _login():
    return RedirectResponse("/login", status_code=303)


def _html(titulo: str, corpo: str, usuario: str | None) -> HTMLResponse:
    return HTMLResponse(pagina(titulo, f'<style>{CSS_DAV}</style><div class="dav">{corpo}</div>{SCRIPT_ACOES}', usuario),
                        headers={"Cache-Control": "no-store"})


def pdf_link(d: dict) -> str:
    return f'<a href="/dav/{d["id"]}/pdf">PDF</a>' if d["pdf"] else ""


def _selo(d: dict) -> str:
    diag = diagnostico(d, administrador=False)
    estado = d["estado"]
    incerto = diag["salvamento"] == "incerto"
    tom = "atencao" if incerto else {"pronto": "ok", "erro": "erro", "rejeitado": "atencao",
                                    "fila": "marca", "gerando": "marca"}.get(estado, "")
    texto = "Confira no HSE" if incerto else ESTADOS.get(estado, estado)
    if estado == "pronto" and diag["tem_aviso"]:
        tom, texto = "atencao", "Criado com aviso"
    simbolo = {"ok": "✓", "erro": "×", "atencao": "!", "marca": "◷"}.get(tom, "·")
    return f'<span class="dav-selo {tom}">{simbolo} {e(texto)}</span>'


def url_dav(base: str, filtros: dict | None = None, **alteracoes) -> str:
    q = dict(filtros or {})
    q.update(alteracoes)
    query = urlencode({k: v for k, v in q.items() if v not in ("", None)})
    return base + ("?" + query if query else "")


def tabela_davs(linhas: list[dict], com_vendedor: bool = False, *, administrador: bool = False,
                filtros: dict | None = None) -> str:
    if not linhas:
        return '<p class="dav-vazio">Nenhum DAV neste recorte. Ajuste os filtros ou envie sua primeira planilha.</p>'
    corpo = ""
    base = "/adm/dav" if administrador else "/dav"
    for d in linhas:
        diag = diagnostico(d, administrador=administrador)
        destino = f"{base}/{d['id']}"
        if d["estado"] == "rascunho" and not administrador:
            destino += "/conferir"
        motivo = (f'<small class="dav-motivo">{e(diag["motivo"])}</small>'
                  if d["estado"] in ("erro", "incerto", "rejeitado") else "")
        aviso = '<small>HSE sinalizou pendência financeira.</small>' if diag["aviso_financeiro"] else ""
        resolvida = (f'<small>Resolvida por <a href="{base}/{d["resolvida_por"]}">novo envio #{d["resolvida_por"]}</a></small>'
                     if d.get("resolvida_por") else "")
        pdf = f'<a href="{base}/{d["id"]}/pdf">PDF</a>' if d.get("pdf") else "—"
        corpo += (f'<tr data-dav="{d["id"]}"><td><b>#{d["id"]}</b><small>{e(d["criado_em"].replace("T", " ")[:16])}</small></td>'
                  + (f'<td>{e(d["usuario"])}</td>' if com_vendedor else "")
                  + f'<td><b>{e(d.get("cliente") or "Cliente não identificado")}</b><small>{e(d["arquivo"])}</small></td>'
                  + f'<td class="dav-resultado">{_selo(d)}{motivo}{aviso}{resolvida}'
                  + (f'<small>Orçamento {e(d["numero"])}</small>' if d.get("numero") else "")
                  + f'</td><td>{pdf}</td><td><a href="{e(url_dav(destino, filtros))}">Abrir →</a></td></tr>')
    return ('<div class="dav-table"><table><thead><tr><th>Envio / data</th>'
            + ('<th>Vendedor</th>' if com_vendedor else '')
            + '<th>Cliente / arquivo</th><th>Resultado e motivo</th><th>PDF</th><th>Ação</th>'
            + f'</tr></thead><tbody>{corpo}</tbody></table></div>')


def filtros_dav(dados: dict, filtros: dict, *, administrador: bool = False) -> str:
    def opcoes(itens, atual):
        return "".join(f'<option value="{e(v)}"{" selected" if str(v) == str(atual) else ""}>{e(t)}</option>' for v, t in itens)
    estados = [("", "Todos os resultados"), ("com_aviso", "Criado com aviso")]
    estados += list(ESTADOS.items())
    if filtros.get("estado") and filtros["estado"] not in dict(estados):
        estados.append((filtros["estado"], filtros["estado"]))
    vendedor = (f'<label>Vendedor<select name="vendedor">{opcoes([("", "Todos os vendedores")] + [(v,v) for v in dados["vendedores"]], filtros.get("vendedor", ""))}</select></label>'
                if administrador else "")
    categoria = (f'<input type="hidden" name="categoria" value="{e(filtros["categoria"])}">'
                 if filtros.get("categoria") else "")
    return (f'<form class="dav-filtros" method="get">{categoria}<label>Período<select name="dias">'
            + opcoes([(1, "Hoje"), (7, "Últimos 7 dias"), (30, "Últimos 30 dias")], dados["periodo"]["dias"])
            + '</select></label><label>Resultado<select name="estado">'
            + opcoes(estados, filtros.get("estado", "")) + '</select></label>' + vendedor
            + f'<label class="dav-busca">Buscar cliente, arquivo ou orçamento<input type="search" name="busca" value="{e(filtros.get("busca", ""))}" maxlength="160"></label>'
            + '<button type="submit">Filtrar</button><a href="'+ ('/adm/dav' if administrador else '/dav') +'">Limpar</a></form>')


def historico_dav(dados: dict, filtros: dict, *, administrador: bool = False) -> str:
    base = "/adm/dav" if administrador else "/dav"
    anterior = (f'<a href="{e(url_dav(base, filtros, pagina=dados["pagina"]-1))}">← Anterior</a>' if dados["pagina"] > 1 else '<span>Início</span>')
    proxima = (f'<a href="{e(url_dav(base, filtros, pagina=dados["pagina"]+1))}">Próxima →</a>' if dados["pagina"] < dados["paginas"] else '<span>Fim</span>')
    return (tabela_davs(dados["linhas"], administrador, administrador=administrador, filtros=filtros)
            + f'<nav class="dav-paginacao" aria-label="Páginas do histórico DAV">{anterior}<span>{dados["total"]} registros · Página {dados["pagina"]} de {dados["paginas"]}</span>{proxima}</nav>')


def _tela_envio(usuario: str, aviso: str = "", origem: int | None = None, **filtros) -> HTMLResponse:
    referencia = f'<input type="hidden" name="origem" value="{origem}">' if origem else ""
    with closing(banco._conectar()) as con:
        dados = painel_dav.consultar(con, usuario=usuario, agora=datetime.now(), **({"dias": 1} | filtros))
    corpo = cabecalho("Da planilha ao DAV, com clareza.", tarja="Orçamentos · Área do vendedor",
                      sub="Envie, confira e acompanhe o resultado dos seus orçamentos.") + f"""
{aviso}
<div class="dav-grid dav-entrada"><section class="cartao dav-card"><h2>{'Corrigir envio #' + str(origem) if origem else 'Novo orçamento DAV'}</h2>
<div class="dav-steps"><span class="atual">1 · Enviar planilha</span><span>2 · Conferir</span><span>3 · Gerar DAV</span></div>
<form method="post" action="/dav/conferir" enctype="multipart/form-data" data-dav-envio>
{referencia}
  <div class="dav-upload"><label for="dav-planilha">Escolha sua PLANILHA-BASE v3</label>
  <input id="dav-planilha" type="file" name="planilha" accept=".xlsx" required aria-describedby="dav-limites">
  <p id="dav-limites">Formato .xlsx · até 5 MB</p><a href="/dav/modelo">Baixar o modelo v3 ↓</a></div>
  <div class="dav-acoes"><button type="submit">Conferir planilha →</button></div>
</form>
</section><aside class="cartao dav-card"><p class="tarja">Sem surpresas</p><h2>Você acompanha cada resultado</h2>
<ul class="dav-lista"><li><b>✓ Confira antes de gerar</b><p>Revise o cliente, os itens e o local de entrega.</p></li>
<li><b>! Entenda o que precisa de atenção</b><p>Erros e avisos aparecem separados, com orientação.</p></li>
<li><b>↓ Encontre seu PDF</b><p>O documento fica junto do resultado, quando disponível.</p></li></ul>
<p class="dav-note">Uma planilha corrigida cria um novo envio e preserva o histórico anterior.</p></aside></div>
<section class="cartao dav-card"><h2>Seus DAVs</h2><p class="dav-note">Somente seus envios · período pela data de submissão · Brasília</p>
{filtros_dav(dados, filtros)}<div id="dav-historico">{historico_dav(dados, filtros)}</div></section>"""
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
def inicio(usuario: str | None = Depends(_quem), origem: int | None = None,
           dias: int = 1, estado: str = "", busca: str = "", pagina: int = 1):
    if not usuario:
        return _login()
    _validar_origem(usuario, origem)
    return _tela_envio(usuario, origem=origem, dias=dias, estado=estado, busca=busca[:160], pagina=pagina)


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
    return cabecalho("Conferir orçamento", tarja=f"DAV · Envio #{dav_id}",
                     sub="Revise os dados. O orçamento só será enviado ao HSE quando você confirmar.") + f"""
<section class="cartao dav-card dav-entrada"><div class="dav-steps"><span>1 · Enviar planilha</span><span class="atual">2 · Conferir</span><span>3 · Gerar DAV</span></div>{avisos}
<dl class="dav-dados"><div><dt>Cliente</dt><dd>{e(o.cliente)}</dd></div><div><dt>Vendedor</dt><dd>{e(o.vendedor)}</dd></div>
<div><dt>Local de entrega</dt><dd>{e(o.local_entrega or 'Não informado')}</dd></div>
<div>
<dt>Filial</dt><dd>{e(o.filial)}</dd>
</div><div>
<dt>Pagamento</dt><dd>{e(o.forma_pg or '')} {e(o.parcelamento or '')}</dd>
</div><div>
<dt>Prazo (dias)</dt><dd>{e(prazo)}</dd>
</div><div><dt>OC</dt><dd>{e(o.ordem_compra or '')}</dd></div><div><dt>Observações</dt><dd>{e(o.observacoes)}</dd></div></dl>
<div class="dav-table">
<table><thead><tr><th>#</th><th>Produto</th><th>Qtd</th><th>Valor unit.</th><th>Código HSE</th></tr></thead>
<tbody>{itens}</tbody></table></div>
<form method="post" action="/dav/{dav_id}/gerar" data-dav-envio class="dav-acoes"><button type="submit">Confirmar e gerar DAV →</button><a href="/dav">Voltar ao envio</a></form></section>"""


@router.get("/{dav_id}/conferir", response_class=HTMLResponse)
def reconferir(dav_id: int, usuario: str | None = Depends(_quem)):
    if not usuario:
        return _login()
    d = banco.dav(dav_id, usuario)
    if d is None:
        raise HTTPException(404)
    if d["estado"] != "rascunho":
        return RedirectResponse(f"/dav/{dav_id}", status_code=303)
    try:
        orcamento = ler_planilha(FILA.planilha(dav_id))
    except Exception:
        return _erro(usuario, "A planilha da conferência não está disponível ou está inválida. Envie o arquivo corrigido.")
    return _html("Conferir DAV", _resumo(orcamento, dav_id), usuario)


@router.post("/conferir", response_class=HTMLResponse)
def conferir(planilha: UploadFile = File(...),
             usuario: str | None = Depends(_quem), origem: int | None = Form(None)):
    if not usuario:
        return _login()
    _validar_origem(usuario, origem)
    nome = Path(planilha.filename or "planilha.xlsx").name
    if not nome.lower().endswith(".xlsx"):
        return _rejeitar(usuario, nome, origem, "Envie um arquivo .xlsx (a PLANILHA-BASE v3).")
    dados = planilha.file.read(MAX_BYTES + 1)
    if len(dados) > MAX_BYTES:
        return _rejeitar(usuario, nome, origem, "O arquivo passa de 5 MB.")
    hash_ = hashlib.sha256(dados).hexdigest()
    pasta = FILA.pasta / "entrada"
    pasta.mkdir(parents=True, exist_ok=True)
    temp = pasta / f"{uuid.uuid4().hex}.xlsx"
    temp.write_bytes(dados)
    try:
        try:
            o = ler_planilha(temp)
        except ErroPlanilha as exc:
            return _rejeitar(usuario, nome, origem, *exc.erros)
        except Exception:
            return _rejeitar(usuario, nome, origem, "Não consegui abrir o arquivo. "
                                  "É a PLANILHA-BASE v3 em .xlsx?")
        with _TRAVA:
            _validar_origem(usuario, origem)
            antigo = banco.dav_ja_gerado(usuario, hash_)
            if antigo:
                if origem:
                    banco.dav_vincular_correcao(origem, antigo["id"], usuario)
                return _ja_gerou(usuario, antigo)
            dav_id = banco.dav_criar(usuario, nome, hash_, o.cliente)
            if origem:
                banco.dav_vincular_correcao(origem, dav_id, usuario)
            temp.replace(FILA.planilha(dav_id))
        return _html("Conferir DAV", _resumo(o, dav_id), usuario)
    finally:
        temp.unlink(missing_ok=True)


def _validar_origem(usuario: str, origem: int | None) -> None:
    if origem is None:
        return
    d = banco.dav(origem, usuario)
    if d is None:
        raise HTTPException(404)
    if d["estado"] not in ("erro", "rejeitado") or diagnostico(d, administrador=False)["salvamento"] == "incerto":
        raise HTTPException(409, "Confira o resultado no HSE antes de reenviar.")


def _rejeitar(usuario: str, nome: str, origem: int | None, *msgs: str) -> HTMLResponse:
    try:
        with _TRAVA:
            _validar_origem(usuario, origem)
            i = banco.dav_rejeitar(usuario, nome, list(msgs))
            if origem:
                banco.dav_vincular_correcao(origem, i, usuario)
    except sqlite3.Error:
        return HTMLResponse(pagina("Planilha não aceita", '<h1>Planilha não aceita</h1>'
            '<p>Não foi possível registrar a rejeição. Nenhum DAV foi enviado ao HSE.</p>', usuario), status_code=503)
    return _erro(usuario, *msgs)


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
        cookie_adm: str | None = Cookie(None, alias=adm.COOKIE_ADM),
        dias: int = 1, estado: str = "", busca: str = "", pagina: int = 1):
    if not usuario:
        if adm.autorizado(cookie_adm):
            return RedirectResponse(f"/adm/dav/{dav_id}", status_code=303)
        return _login()
    d = banco.dav(dav_id, usuario)
    if d is None:
        raise HTTPException(404)
    retorno = url_dav("/dav", dict(dias=dias, estado=estado, busca=busca[:160], pagina=pagina))
    meta = '<meta http-equiv="refresh" content="5">' if d["estado"] in ("fila", "gerando") else ""
    return _html("DAV", meta + detalhe_dav(d, administrador=False, retorno=retorno), usuario)


def detalhe_dav(dav: dict, *, administrador: bool, retorno: str) -> str:
    d = dav
    diag = diagnostico(d, administrador=administrador)
    incerto = diag["salvamento"] == "incerto"
    base = "/adm/dav" if administrador else "/dav"
    tom = "atencao" if incerto else {"pronto": "ok", "erro": "erro", "rejeitado": "atencao"}.get(d["estado"], "")
    corpo = cabecalho(diag["titulo"], tarja=f"Orçamentos DAV · Envio #{d['id']}",
                       sub=e(d["arquivo"]), acoes=f'<a class="botao2" href="{e(retorno)}">← Voltar ao histórico</a>')
    motivo = diag["motivo"] if d["estado"] in ("erro", "incerto", "rejeitado") else {
        "pronto": "O orçamento foi salvo no HSE. Consulte o documento disponível abaixo.",
        "fila": "Seu orçamento está aguardando a vez de execução.",
        "gerando": "O robô está trabalhando no HSE. Você pode acompanhar por esta tela.",
        "rascunho": "O envio ainda não foi confirmado.", "simulado": "Nada foi salvo no HSE."
    }.get(d["estado"], "Estado não reconhecido. Consulte os detalhes e o responsável pelo robô.")
    if incerto:
        motivo = "O orçamento pode já existir no HSE; confira antes de reenviar."
    acoes = (f'<a class="botao2" href="{base}/{d["id"]}/pdf">Baixar PDF ↓</a>' if d.get("pdf") else "")
    if not administrador and d["estado"] in ("erro", "rejeitado") and not incerto:
        acoes += f'<a class="botao2" href="/dav?origem={d["id"]}">Enviar planilha corrigida →</a>'
    if not administrador and d["estado"] == "rascunho":
        acoes += f'<a class="botao2" href="/dav/{d["id"]}/conferir">Conferir antes de gerar →</a>'
    corpo += f'<section class="dav-resultado-box {tom}">{_selo(d)}'
    if d.get("numero"):
        corpo += f'<h2>Orçamento {e(d["numero"])}</h2>'
    corpo += f'<p>{e(motivo)}</p>'
    if d["estado"] in ("erro", "incerto", "rejeitado"):
        orientacao = diag["orientacao"]
        if incerto and d.get("numero"):
            orientacao = orientacao[:1].lower() + orientacao[1:]
        corpo += f'<p><b>Próximo passo:</b> {e(orientacao)}</p>'
    if d["estado"] == "fila":
        with closing(banco._conectar()) as con:
            posicao = painel_dav.posicao_na_fila(con, d["id"])
        if posicao is not None:
            corpo += f'<p>Posição na fila: {posicao}</p>'
    corpo += f'<div class="dav-acoes">{acoes}</div></section>'
    if diag["aviso_financeiro"]:
        corpo += '<aside class="dav-aviso"><b>! Aviso financeiro do HSE</b><p>Consulte o financeiro sobre a pendência do cliente. Esse aviso é independente do resultado da criação.</p></aside>'
    elif diag["tem_aviso"]:
        corpo += '<aside class="dav-aviso"><b>! Aviso do HSE</b><p>Consulte os detalhes disponíveis ou o responsável pela operação.</p></aside>'
    dados = [("Cliente", d.get("cliente") or "Cliente não identificado"), ("Vendedor", d["usuario"]),
             ("Envio", d["criado_em"].replace("T", " ")), ("Início", (d.get("iniciado_em") or "Não iniciado").replace("T", " ")),
             ("Conclusão", (d.get("terminado_em") or "Não concluído").replace("T", " ")),
             ("Etapa conhecida", diag["etapa"] or "Não informada")]
    corpo += '<section class="cartao dav-card"><h2>Contexto do orçamento</h2><dl class="dav-dados">'
    corpo += "".join(f'<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>' for k, v in dados) + '</dl>'
    with closing(banco._conectar()) as con:
        resolvida = painel_dav.resolvidas(con, [d["id"]], None if administrador else d["usuario"])
        origens = [r[0] for r in con.execute(
            "SELECT c.origem_id FROM dav_correcao c JOIN dav a ON a.id=c.origem_id"
            " WHERE c.destino_id=? AND a.usuario=? ORDER BY c.origem_id", (d["id"], d["usuario"]))]
    for origem in origens:
        corpo += f'<p>Correção do envio <a href="{base}/{origem}">#{origem}</a>. Histórico preservado.</p>'
    if d["id"] in resolvida:
        destino = resolvida[d["id"]]
        corpo += f'<p>✓ Resolvida por novo envio <a href="{base}/{destino}">#{destino}</a>. O resultado desta tentativa foi preservado.</p>'
    corpo += (f'<details id="dav-relatorio"><summary>{"Relatório original e informações técnicas" if administrador else "Detalhes disponíveis ao vendedor"}</summary>'
              f'<pre>{e(diag["relatorio_visivel"] or "Nenhum relatório disponível.")}</pre></details>'
              f'<details id="dav-copia"><summary>Copiar diagnóstico</summary><pre id="dav-diagnostico">{e(diag["diagnostico_copiavel"])}</pre>'
              '<button type="button" data-dav-copiar>Copiar diagnóstico</button><p role="status" id="dav-copiado"></p></details></section>')
    return corpo


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
