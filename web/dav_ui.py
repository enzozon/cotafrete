"""Tela Gerar DAV: /dav (enviar, conferir, gerar, acompanhar, baixar o PDF).

O robô e a fila moram em orcamento/ (fila.py); aqui só a porta do vendedor.
`banco`, `vendedor` e `FILA` são injetados por web/app.py (importar web.app
daqui seria circular), como em web/me_ui.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from core.banco import Banco, origem_corrigivel
from core import painel_dav
from mercado_eletronico.painel import hora_de_brasilia
from orcamento.fila import FilaDav
from orcamento.conferencia import FilaConferencia
from orcamento.diagnostico import _financeiro, diagnostico
from orcamento.processador import SEM_HSE, Conferencia
from orcamento.relatorio import moeda
from orcamento.planilha import ErroPlanilha, ler_planilha, observacoes_hse
from web import adm
from web.layout import BOTAO_TEMA, CSS_DAV, cabecalho, e, pagina

banco: Banco | None = None
vendedor: Callable[[str | None], str | None] | None = None
FILA: FilaDav | None = None
FILA_CONFERENCIA: FilaConferencia | None = None
AVISO_FINANCEIRO = "Aviso financeiro: consulte o financeiro."
COOKIE = "cotafrete_usuario"
agora = datetime.now

MAX_BYTES = 5 * 1024 * 1024
MODELO = Path(__file__).resolve().parent.parent / "orcamento" / "modelo" / "PLANILHA-BASE-v3.xlsx"
ESTADOS = {"rascunho": "Conferindo", "fila": "Na fila", "gerando": "Gerando no HSE",
           "pronto": "Pronto", "erro": "Erro", "incerto": "Confira no HSE",
           "simulado": "Simulação (nada salvo)", "rejeitado": "Planilha não aceita"}
# ponytail: uma trava global; basta para uma VM com poucos vendedores.
_TRAVA = threading.Lock()

log = logging.getLogger(__name__)
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
document.addEventListener('click', ev => {
  document.querySelectorAll('.dav-filtro-menu[open]').forEach(menu => {
    if (!menu.contains(ev.target)) menu.open = false;
  });
});
document.addEventListener('keydown', ev => {
  if (ev.key !== 'Escape') return;
  const menu = document.activeElement.closest('.dav-filtro-menu[open]');
  if (menu) { menu.open = false; menu.querySelector('summary').focus(); }
});
</script>"""

SCRIPT_PULSO = """<script>
(() => {
  const barra = document.querySelector('[data-dav-pulso]');
  if (!barra) return;
  const status = barra.querySelector('[role="status"]');
  const botao = barra.querySelector('button');
  let versao = '', ocupado = false, continua = true, timer, ultimo = '';
  function trocar(id, html) {
    const el = document.getElementById(id);
    if (!el || el.innerHTML === html) return true;
    if (el.contains(document.activeElement)) return false;
    const abertos = [...el.querySelectorAll('details[open]')].map(d => d.id);
    const linhas = new Map([...el.querySelectorAll('[data-dav]')].map(r => [r.dataset.dav, r.innerHTML]));
    const numeros = [...el.querySelectorAll('.numero')].map(r => r.textContent);
    const y = window.scrollY;
    el.innerHTML = html;
    abertos.forEach(id => { const d = document.getElementById(id); if (d) d.open = true; });
    el.querySelectorAll('[data-dav]').forEach(r => { if (linhas.get(r.dataset.dav) !== r.innerHTML) r.classList.add('dav-mudou'); });
    el.querySelectorAll('.numero').forEach((r,i) => { if (numeros[i] !== r.textContent) r.classList.add('dav-mudou'); });
    el.querySelectorAll('.dav-mudou').forEach(r => r.addEventListener('animationend', () => r.classList.remove('dav-mudou'), {once:true}));
    window.scrollTo({top:y, behavior:'instant'});
    return true;
  }
  async function pulsar() {
    if (ocupado) return;
    ocupado = true;
    clearTimeout(timer);
    const q = new URLSearchParams(location.search);
    q.delete('origem'); q.set('v', versao);
    try {
      const r = await fetch(barra.dataset.endpoint + '?' + q, {cache:'no-store'});
      if (r.status === 401 || r.redirected) {
        status.textContent = 'Sessão expirada. Entre novamente para atualizar.';
        continua = false; botao.hidden = true; return;
      }
      if (r.status === 204) { ultimo = new Date().toLocaleTimeString('pt-BR'); status.textContent = 'Atualizado às ' + ultimo; return; }
      if (!r.ok) throw new Error('consulta indisponível');
      const d = await r.json();
      let adiou = false;
      Object.entries(d.fragmentos).forEach(([id,html]) => { if (!trocar(id,html)) adiou = true; });
      versao = adiou ? '' : d.v;
      continua = d.ativo || adiou;
      ultimo = d.atualizado_em;
      status.textContent = 'Última atualização: ' + ultimo + (continua ? '' : ' · Sem geração em andamento');
    } catch (erro) {
      status.textContent = 'Não foi possível atualizar. Última atualização: ' + (ultimo || 'não confirmada') + '. Os últimos dados foram mantidos.';
    } finally {
      ocupado = false;
      if (continua) timer = setTimeout(pulsar, 5000);
    }
  }
  botao.addEventListener('click', pulsar);
  pulsar();
})();
</script>"""


def barra_pulso(endpoint: str) -> str:
    return (f'<div class="dav-pulso" data-dav-pulso data-endpoint="{e(endpoint)}">'
            '<span role="status" aria-live="polite">Consultando atualizações…</span>'
            '<button type="button">Atualizar agora</button></div>')


def resposta_pulso(fragmentos: dict, v: str, *, ativo: bool = True, contexto: str = ""):
    versao = hashlib.sha256(json.dumps([fragmentos, ativo, contexto], ensure_ascii=False,
                                      sort_keys=True).encode("utf-8")).hexdigest()
    cab = {"Cache-Control": "no-store"}
    if v == versao:
        return Response(status_code=204, headers=cab)
    return JSONResponse(dict(v=versao, atualizado_em=agora().strftime("%d/%m/%Y %H:%M:%S"),
                             fragmentos=fragmentos, ativo=ativo), headers=cab)


def _quem(usuario: str | None = Cookie(None, alias=COOKIE)):
    return vendedor(usuario)


def _login():
    return RedirectResponse("/login", status_code=303)


def _html(titulo: str, corpo: str, usuario: str | None) -> HTMLResponse:
    return HTMLResponse(pagina(titulo, f'<style>{CSS_DAV}</style><div class="dav">{corpo}</div>{SCRIPT_ACOES}{SCRIPT_PULSO}', usuario),
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
    if estado == "rascunho" and d.get("conferencia") == "erros":
        tom, texto = "erro", "Com erros"
    simbolo = {"ok": "✓", "erro": "×", "atencao": "!", "marca": "◷"}.get(tom, "·")
    return f'<span class="dav-selo {tom}">{simbolo} {e(texto)}</span>'


def url_dav(base: str, filtros: dict | None = None, **alteracoes) -> str:
    q = dict(filtros or {})
    q.update(alteracoes)
    query = urlencode({k: v for k, v in q.items() if v not in ("", None)})
    return base + ("?" + query if query else "")


def tempo_dav(d: dict, *, instante: datetime | None = None) -> str:
    """Datas do banco são Brasília; datas com fuso passam pelo conversor existente."""
    estado = d.get("estado")
    inicio = d.get("criado_em") if estado == "fila" else d.get("iniciado_em")
    fim = (instante or agora()) if estado in ("fila", "gerando") else d.get("terminado_em")
    if not inicio or not fim:
        return ""
    try:
        segundos = int((hora_de_brasilia(fim) - hora_de_brasilia(inicio)).total_seconds())
    except (ValueError, TypeError, AttributeError, OverflowError):
        return ""
    if segundos < 0:
        return ""
    duracao = (f"{segundos} s" if segundos < 60 else f"{segundos // 60} min" if segundos < 3600
               else f"{segundos // 3600} h {(segundos % 3600) // 60} min")
    prefixo = {"fila": "Na fila há ", "gerando": "Em execução há "}.get(estado, "Duração: ")
    return prefixo + duracao


def bloco_orientacao(d: dict, *, administrador: bool = False) -> str:
    diag = diagnostico(d, administrador=administrador)
    referencias = diag.get("campos", [])
    quantidades = [c for c in referencias if re.fullmatch(r"B(?:[2-9]|1\d|2[0-5])", c)]
    campos = ", ".join(f"Quantidade do item {int(c[1:])-1} ({c})" if c in quantidades else c for c in referencias)
    correcao = diag.get("como_corrigir", diag["orientacao"])
    if quantidades and diag.get("origem") == "planilha":
        correcao += " A quantidade deve ser um número maior que zero nos itens indicados."
    return ('<section class="dav-orientacao" aria-label="Orientação sobre o erro">'
            f'<h3>{e(diag.get("origem_rotulo", "Causa não identificada"))}</h3>'
            f'<p><b>Onde conferir:</b> {e(diag.get("onde_conferir", "Consulte os detalhes do envio."))}</p>'
            + (f'<p class="dav-celulas"><b>Células:</b> {e(campos)}</p>' if campos else "")
            + f'<p><b>Como corrigir:</b> {e(correcao)}</p></section>')


def tabela_davs(linhas: list[dict], com_vendedor: bool = False, *, administrador: bool = False,
                filtros: dict | None = None) -> str:
    if not linhas:
        return '<p class="dav-vazio">Nenhum DAV encontrado. Ajuste os filtros.</p>'
    corpo = ""
    base = "/adm/dav" if administrador else "/dav"
    for d in linhas:
        diag = diagnostico(d, administrador=administrador)
        destino = f"{base}/{d['id']}"
        if d["estado"] == "rascunho" and not administrador:
            destino += "/conferir"
        motivo = (f'<small class="dav-motivo">{e(diag["motivo"])}</small>'
                  if d["estado"] in ("erro", "incerto", "rejeitado") else "")
        correcao_url = url_dav(f'{base}/{d.get("resolvida_por")}', filtros)
        resolvida = (f'<small class="dav-correcao">✓ Resolvida por <a href="{e(correcao_url)}">novo envio #{d["resolvida_por"]}</a></small>'
                     if d.get("resolvida_por") else "")
        tempo = tempo_dav(d)
        pdf = f'<a href="{base}/{d["id"]}/pdf">PDF</a>' if d.get("pdf") else "—"
        corpo += (f'<tr data-dav="{d["id"]}"><td><b>#{d["id"]}</b><small>{e(d["criado_em"].replace("T", " ")[:16])}</small></td>'
                  + (f'<td>{e(d["usuario"])}</td>' if com_vendedor else "")
                  + f'<td><b>{e(d.get("cliente") or "Cliente não identificado")}</b><small>{e(d["arquivo"])}</small></td>'
                  + f'<td class="dav-resultado">{_selo(d)}{motivo}{resolvida}'
                  + (f'<small>{e(tempo)}</small>' if tempo else "")
                  + (f'<small>Orçamento {e(d["numero"])}</small>' if d.get("numero") else "")
                  + f'</td><td>{pdf}</td><td><a href="{e(url_dav(destino, filtros))}">Abrir →</a></td></tr>')
    return ('<div class="dav-table"><table><thead><tr><th>Envio / data</th>'
            + ('<th>Vendedor</th>' if com_vendedor else '')
            + '<th>Cliente / arquivo</th><th>Resultado e motivo</th><th>PDF</th><th>Ação</th>'
            + f'</tr></thead><tbody>{corpo}</tbody></table></div>')


def filtros_dav(dados: dict, filtros: dict, *, administrador: bool = False,
                base: str | None = None) -> str:
    base = base or ("/adm/dav" if administrador else "/dav")
    atuais = dict(filtros, dias=dados["periodo"]["dias"])
    if not administrador:
        atuais.pop("vendedor", None)
    estados = [("", "Todos os resultados"), ("com_aviso", "Criado com aviso")]
    estados += list(ESTADOS.items())
    if filtros.get("estado") and filtros["estado"] not in dict(estados):
        estados.append((filtros["estado"], filtros["estado"]))
    periodos = [(1, "Hoje"), (7, "Últimos 7 dias"), (30, "Últimos 30 dias")]

    def menu(chave, titulo, opcoes):
        valor = atuais.get(chave, "")
        rotulo = dict(opcoes).get(valor, str(valor))
        links = "".join(f'<a href="{e(url_dav(base, atuais, **{chave: v, "pagina": 1}))}"'
                        + (' aria-current="true"' if str(v) == str(valor) else '')
                        + f'>{e(t)}</a>' for v, t in opcoes)
        return (f'<details class="dav-filtro-menu"><summary><span class="dav-campo-nome">{titulo}: </span>'
                f'{e(rotulo)}<span aria-hidden="true">⌄</span></summary>'
                f'<nav class="dav-menu-opcoes" aria-label="{titulo}">{links}</nav></details>')

    ocultos = "".join(f'<input type="hidden" name="{k}" value="{e(atuais[k])}">'
                      for k in ("dias", "estado", "vendedor", "categoria") if atuais.get(k))
    menus = menu("dias", "Período", periodos) + menu("estado", "Resultado", estados)
    if administrador:
        menus += menu("vendedor", "Vendedor", [("", "Todos os vendedores")] + [(v, v) for v in dados["vendedores"]])
    chips = ""
    rotulos = {"dias": "Período", "estado": "Resultado", "vendedor": "Vendedor", "busca": "Busca", "categoria": "Motivo"}
    categorias = {"endereco": "Local de entrega", "acesso_hse": "Acesso ao HSE", "planilha": "Planilha", "desconhecido": "Não classificado"}
    for chave, nome in rotulos.items():
        valor = atuais.get(chave)
        if not valor or (chave == "dias" and valor == 1):
            continue
        rotulo = dict(periodos).get(valor, valor) if chave == "dias" else dict(estados).get(valor, valor) if chave == "estado" else categorias.get(valor, valor) if chave == "categoria" else valor
        destino = url_dav(base, atuais, **{chave: 1 if chave == "dias" else "", "pagina": 1})
        chips += f'<a class="dav-chip" aria-label="Remover filtro {nome}" href="{e(destino)}">{e(rotulo)} <span aria-hidden="true">×</span></a>'
    ativos = f'<div class="dav-filtros-ativos" aria-label="Filtros ativos">{chips}<a class="dav-limpar" href="{base}">Limpar filtros</a></div>' if chips else ""
    return (f'<div class="dav-filtros-area"><form class="dav-barra" method="get" action="{base}">{ocultos}'
            '<label class="dav-busca"><span class="dav-campo-nome">Buscar cliente, arquivo ou orçamento</span>'
            f'<input type="search" name="busca" placeholder="Buscar cliente, arquivo ou orçamento" value="{e(atuais.get("busca", ""))}" maxlength="160">'
            '<button type="submit" class="botao2" aria-label="Buscar DAVs">Buscar</button></label>'
            f'{menus}</form>{ativos}</div>')


def historico_dav(dados: dict, filtros: dict, *, administrador: bool = False) -> str:
    base = "/adm/dav" if administrador else "/dav"
    anterior = (f'<a href="{e(url_dav(base, filtros, pagina=dados["pagina"]-1))}">← Anterior</a>' if dados["pagina"] > 1 else '<span>Início</span>')
    proxima = (f'<a href="{e(url_dav(base, filtros, pagina=dados["pagina"]+1))}">Próxima →</a>' if dados["pagina"] < dados["paginas"] else '<span>Fim</span>')
    return (tabela_davs(dados["linhas"], administrador, administrador=administrador, filtros=filtros)
            + f'<nav class="dav-paginacao" aria-label="Páginas do histórico DAV">{anterior}<span>{dados["total"]} {"registro" if dados["total"] == 1 else "registros"} · Página {dados["pagina"]} de {dados["paginas"]}</span>{proxima}</nav>')


PERIODOS = {1: "Hoje", 7: "Últimos 7 dias", 30: "Últimos 30 dias"}
MAX_PRONTOS = 5  # o quadro é o resumo do período; o resto fica no histórico abaixo


def celulas(campos: list[str]) -> str:
    return "".join(f'<span class="dav-cel">{e(c)}</span>' for c in campos)


def _cartao(d: dict, link: str, tom: str, corpo: str, rodape: str = "", extra: str = " ") -> str:
    return (f'<article class="dav-cartao {tom}"><p class="dav-l1"><b>#{d["id"]}</b>{extra}'
            f'{e(d["criado_em"].replace("T", " ")[11:16])}</p>'
            f'<h3><a href="{e(link)}">{e(d.get("cliente") or d.get("arquivo") or "Cliente não identificado")}</a></h3>'
            f'{corpo}{rodape}</article>')


def _coluna(titulo: str, tom: str, cartoes: list[str], vazio: str, mais: str = "") -> str:
    corpo = "".join(cartoes) or f'<p class="dav-vazio">{e(vazio)}</p>'
    return (f'<section class="dav-col"><h2><i class="dav-ponto {tom}" aria-hidden="true"></i>{e(titulo)}'
            f'<span class="dav-conta">{len(cartoes)}</span></h2>{corpo}{mais}</section>')


def _precisa_vendedor(dados: dict, filtros: dict) -> list[str]:
    cartoes = []
    for g in dados["quadro"]["precisa"]:
        if g["tipo"] == "aviso":
            continue  # o DAV foi criado: aparece em Prontos com o aviso
        tom = "atencao" if g["tipo"] == "confirmacao" else "erro"
        corrige = g["tipo"] in ("falha", "rejeitado") and g["origem"] not in ("automacao", "acesso_hse")
        for d in g["envios"]:
            link = url_dav(f'/dav/{d["id"]}', filtros)
            acao = (f'<a class="dav-btnc" href="/dav?origem={d["id"]}">Enviar corrigida →</a>' if corrige
                    else f'<a class="dav-btnc" href="{e(link)}">Ver detalhes →</a>')
            cartoes.append(_cartao(d, link, tom,
                f'<p>{e(g["titulo"])}</p><div class="dav-faca"><b>O que fazer</b>{e(g["como_corrigir"])} '
                f'{celulas(d.get("campos", []))}</div>', acao))
    return cartoes


def _andamento(dados: dict, filtros: dict, base: str, administrador: bool = False) -> list[str]:
    cartoes = []
    for d in dados["quadro"]["andamento"]:
        barra = '<div class="dav-prog" aria-hidden="true"><span></span></div>' if d["estado"] == "gerando" else ""
        quem = f' {e(d["usuario"])} · ' if administrador else " "
        cartoes.append(_cartao(d, url_dav(f'{base}/{d["id"]}', filtros), "andamento",
                               f'<p>{e(tempo_dav(d) or ESTADOS[d["estado"]])}</p>{barra}', extra=quem))
    return cartoes


def _prontos(dados: dict, filtros: dict, base: str) -> tuple[list[str], str]:
    prontos = dados["quadro"]["prontos"]
    cartoes = []
    for d in prontos[:MAX_PRONTOS]:
        diag = diagnostico(d, administrador=False)
        duracao = tempo_dav(d).removeprefix("Duração: ")
        pdf = f'<a class="dav-btnc" href="{base}/{d["id"]}/pdf">Baixar PDF ↓</a>' if d.get("pdf") else ""
        cartoes.append(_cartao(d, url_dav(f'{base}/{d["id"]}', filtros), "ok",
            f'<p>Orçamento <b>{e(d.get("numero") or "—")}</b>{" · " + e(duracao) if duracao else ""}</p>', pdf))
    mais = (f'<p class="dav-mais"><a href="{e(url_dav(base, filtros, estado="pronto", pagina=1))}#historico">'
            f'Ver os {len(prontos)} prontos no histórico →</a></p>' if len(prontos) > MAX_PRONTOS else "")
    return cartoes, mais


def resumo_dia(dados: dict) -> str:
    q = dados["quadro"]
    precisa = sum(len(g["envios"]) for g in q["precisa"] if g["tipo"] != "aviso")
    prontos = len(q["prontos"])
    return (f'{PERIODOS.get(dados["periodo"]["dias"], "Período")}: {prontos} '
            f'{"pronto" if prontos == 1 else "prontos"} · {len(q["andamento"])} em andamento · '
            f'<b>{precisa} {"precisa" if precisa == 1 else "precisam"} de você</b>')


def quadro_vendedor(dados: dict, filtros: dict) -> str:
    prontos, mais = _prontos(dados, filtros, "/dav")
    return (_coluna("Precisa de você", "erro", _precisa_vendedor(dados, filtros), "Nada pendente agora.")
            + _coluna("Em andamento", "andamento", _andamento(dados, filtros, "/dav"),
                      "Nenhum orçamento em andamento.")
            + _coluna("Prontos", "ok", prontos, "Nenhum DAV pronto neste período.", mais))


def _tela_envio(usuario: str, aviso: str = "", origem: int | None = None, **filtros) -> HTMLResponse:
    referencia = f'<input type="hidden" name="origem" value="{origem}">' if origem else ""
    with closing(banco._conectar()) as con:
        dados = painel_dav.consultar(con, usuario=usuario, agora=agora(), **({"dias": 1} | filtros))
    nome = usuario[:1].upper() + usuario[1:]
    corpo = f"""
<section class="dav-ola"><div><p class="dav-ola-tarja">Orçamentos · Área do vendedor</p>
<h1>Olá, {e(nome)}</h1><p id="dav-resumo-dia">{resumo_dia(dados)}</p></div>
<form class="dav-enviar" method="post" action="/dav/conferir" enctype="multipart/form-data" data-dav-envio>
{referencia}<label for="dav-planilha">{'Corrigir envio #' + str(origem) if origem else 'Novo orçamento DAV'}</label>
  <input id="dav-planilha" type="file" name="planilha" accept=".xlsx" required aria-describedby="dav-limites">
  <button type="submit">Conferir planilha →</button>
  <p id="dav-limites">.xlsx · até 5 MB · <a href="/dav/modelo">Baixar o modelo v3 ↓</a></p>
</form></section>
{aviso}{barra_pulso('/dav/agora')}
<div id="dav-quadro" class="dav-quadro">{quadro_vendedor(dados, filtros)}</div>
<section class="cartao dav-card" id="historico"><h2>Histórico</h2><p class="dav-note">Somente seus envios · período pela data de submissão · Brasília</p>
{filtros_dav(dados, filtros)}<div id="dav-historico">{historico_dav(dados, filtros)}</div></section>"""
    return _html("Gerar DAV", corpo, usuario)


def _erro(usuario: str, *msgs: str, origem: int | None = None) -> HTMLResponse:
    itens = "".join(f"<li>{e(m)}</li>" for m in msgs)
    d = banco.dav(origem, usuario) if origem else None
    guia = bloco_orientacao(d) if d and d["estado"] == "rejeitado" else ""
    return _tela_envio(usuario, f'<div class="alerta" role="alert"><ul>{itens}</ul></div>{guia}', origem=origem)


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


def _filtrar(textos) -> list[str]:
    """O vendedor não vê detalhe financeiro: vira um aviso único (sem repetir)."""
    saida: list[str] = []
    for t in textos:
        t = AVISO_FINANCEIRO if _financeiro(t) else t
        if t not in saida:
            saida.append(t)
    return saida


def _conferencia_de(d: dict | None) -> tuple[str | None, Conferencia | None]:
    estado = (d or {}).get("conferencia")
    if estado not in ("ok", "erros", "nao_conferido") or not d.get("conferencia_relatorio"):
        return estado, None
    try:
        return estado, Conferencia.de_json(d["conferencia_relatorio"])
    except Exception:
        return estado, None


ILEGIVEL = "Não consegui ler o resultado da conferência; envie a planilha de novo."


def _bloco_hse(conf: Conferencia | None) -> str:
    if conf is None or not (conf.cliente or conf.endereco or conf.vendedor):
        return ""
    return ('<dl class="dav-dados"><div><dt>Cliente no HSE</dt><dd>%s</dd></div>'
            '<div><dt>Endereço no HSE</dt><dd>%s</dd></div>'
            '<div><dt>Vendedor no HSE</dt><dd>%s</dd></div></dl>'
            % (e(conf.cliente), e(conf.endereco), e(conf.vendedor)))


def _conferencia_admin(d: dict) -> str:
    """Visão do admin: estado, erros, avisos (sem filtro financeiro) e relatório completo."""
    estado = d.get("conferencia")
    if not estado:
        return ""
    corpo = f'<section class="cartao dav-card" id="dav-conferencia"><h2>Conferência com o HSE</h2><p>Estado: <b>{e(estado)}</b></p>'
    if d.get("conferencia_relatorio"):
        try:
            conf = Conferencia.de_json(d["conferencia_relatorio"])
        except Exception:
            return corpo + "<p>Não foi possível ler o resultado salvo da conferência.</p></section>"
        for titulo, textos in (("Erros", conf.erros), ("Avisos", conf.avisos)):
            if textos:
                corpo += f'<h3>{titulo}</h3><ul class="dav-lista">' + "".join(f"<li>{e(t)}</li>" for t in textos) + "</ul>"
        corpo += _bloco_hse(conf) + f"<pre>{e(conf.relatorio)}</pre>"
    return corpo + "</section>"


def _tabela_itens(o, conf: Conferencia | None) -> str:
    if conf is None or not conf.itens:
        linhas = "".join(
            f"<tr><td>{i.numero}</td><td>{e(i.produto)}</td><td>{e(i.quantidade)}</td>"
            f"<td>{e(i.valor_unit)}</td><td>"
            f"{e(i.codigo) if i.codigo else 'procurar pela descrição / cadastrar se não existir'}"
            f"</td><td>{e(i.descricao)}</td></tr>" for i in o.itens)
        cab = "<th>#</th><th>Produto</th><th>Qtd</th><th>Valor unit.</th><th>Código HSE</th><th>Descrição</th>"
    else:
        achados = {i.numero: i for i in conf.itens}
        linhas = ""
        for i in o.itens:
            h = achados.get(i.numero)
            if h:
                codigo, desc_hse = h.codigo or "novo", h.descricao
                tabela = moeda(h.preco_tabela) if h.preco_tabela is not None else "—"
                plan = moeda(h.valor_unit)
            else:
                codigo, desc_hse, tabela, plan = "", "", "—", i.valor_unit
            linhas += (f"<tr><td>{i.numero}</td><td>{e(i.produto)}</td><td>{e(i.quantidade)}</td>"
                       f"<td>{e(i.descricao)}</td><td>{e(codigo)}</td><td>{e(desc_hse)}</td>"
                       f"<td>{e(tabela)}</td><td>{e(plan)}</td></tr>")
        cab = ("<th>#</th><th>Produto</th><th>Qtd</th><th>Descrição</th><th>Código HSE</th>"
               "<th>Descrição no HSE</th><th>Tabela</th><th>Planilha</th>")
    return f'<div class="dav-table"><table><thead><tr>{cab}</tr></thead><tbody>{linhas}</tbody></table></div>'


def _resumo(o, dav_id: int, d: dict | None = None) -> str:
    estado, conf = _conferencia_de(d)
    cabeca = cabecalho("Conferir orçamento", tarja=f"DAV · Envio #{dav_id}",
                       sub="Revise os dados. O orçamento só será enviado ao HSE quando você confirmar.")
    passos = ('<div class="dav-steps"><span>1 · Enviar planilha</span><span class="atual">2 · Conferir</span>'
              '<span>3 · Gerar DAV</span></div>')
    if estado == "conferindo":
        return (f'<meta http-equiv="refresh" content="5;url=/dav/{dav_id}/conferir">' + cabeca
                + f'<section class="cartao dav-card dav-entrada">{passos}<p role="status">Conferindo com o HSE…</p>'
                '<div class="dav-acoes"><a href="/dav">Voltar ao envio</a></div></section>')
    obs = "<br>".join(e(linha) for linha in observacoes_hse(o).split("\n"))  # o mesmo texto que vai ao HSE
    avisos = "".join(f'<div class="aviso">{e(a)}</div>'
                     for a in _filtrar(list(o.avisos) + (list(conf.avisos) if conf else [])
                                       + ([SEM_HSE] if estado == "nao_conferido" else [])))
    if conf:
        avisos += "".join(f'<div class="alerta">{e(a)}</div>' for a in _filtrar(conf.erros))
    elif estado == "erros":
        avisos += f'<div class="alerta">{e(ILEGIVEL)}</div>'
    prazo = o.prazo_dias if o.prazo_dias is not None else ""
    if estado == "erros":
        acao = (f'<div class="dav-acoes"><a class="botao2" href="/dav?origem={dav_id}">Enviar planilha corrigida →</a>'
                '<a href="/dav">Voltar ao envio</a></div>')
    else:
        acao = (f'<form method="post" action="/dav/{dav_id}/gerar" data-dav-envio class="dav-acoes">'
                '<button type="submit">Confirmar e gerar DAV →</button><a href="/dav">Voltar ao envio</a></form>')
    guia = bloco_orientacao(d) if d and estado == "erros" else ""
    return cabeca + f"""
<section class="cartao dav-card dav-entrada">{passos}{avisos}{_bloco_hse(conf)}
{guia}
<dl class="dav-dados"><div><dt>Cliente</dt><dd>{e(o.cliente)}</dd></div><div><dt>Vendedor</dt><dd>{e(o.vendedor)}</dd></div>
<div><dt>Local de entrega</dt><dd>{e(o.local_entrega or 'Não informado')}</dd></div>
<div>
<dt>Filial</dt><dd>{e(o.filial)}</dd>
</div><div>
<dt>Pagamento</dt><dd>{e(o.forma_pg or '')} {e(o.parcelamento or '')}</dd>
</div><div>
<dt>Prazo (dias)</dt><dd>{e(prazo)}</dd>
</div><div><dt>OC</dt><dd>{e(o.ordem_compra or '')}</dd></div><div><dt>Observações</dt><dd>{obs}</dd></div></dl>
{_tabela_itens(o, conf)}
{acao}</section>"""


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
    return _html("Conferir DAV", _resumo(orcamento, dav_id, d), usuario)


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
            return _rejeitar(usuario, nome, origem, *exc.erros, arquivo=temp)
        except Exception:
            return _rejeitar(usuario, nome, origem, "Não consegui abrir o arquivo. "
                                  "É a PLANILHA-BASE v3 em .xlsx?", arquivo=temp)
        with _TRAVA:
            _validar_origem(usuario, origem)
            antigo = banco.dav_ja_gerado(usuario, hash_)
            if antigo:
                if origem:
                    banco.dav_vincular_correcao(origem, antigo["id"], usuario)
                return _ja_gerou(usuario, antigo)
            # já nasce "conferindo": a fila só grava em "conferindo"
            dav_id = banco.dav_criar(usuario, nome, hash_, o.cliente, conferencia="conferindo")
            if origem:
                banco.dav_vincular_correcao(origem, dav_id, usuario)
            temp.replace(FILA.planilha(dav_id))
        FILA_CONFERENCIA.enfileirar(dav_id)
        return _html("Conferir DAV", _resumo(o, dav_id, banco.dav(dav_id, usuario)), usuario)
    finally:
        temp.unlink(missing_ok=True)


def _validar_origem(usuario: str, origem: int | None) -> None:
    if origem is None:
        return
    d = banco.dav(origem, usuario)
    if d is None:
        raise HTTPException(404)
    if not origem_corrigivel(d) or diagnostico(d, administrador=False)["salvamento"] == "incerto":
        raise HTTPException(409, "Confira o resultado no HSE antes de reenviar.")


def _rejeitar(usuario: str, nome: str, origem: int | None, *msgs: str,
              arquivo: Path | None = None) -> HTMLResponse:
    try:
        with _TRAVA:
            _validar_origem(usuario, origem)
            i = banco.dav_rejeitar(usuario, nome, list(msgs))
            if origem:
                banco.dav_vincular_correcao(origem, i, usuario)
    except sqlite3.Error:
        return HTMLResponse(pagina("Planilha não aceita", '<h1>Planilha não aceita</h1>'
            '<p>Não foi possível registrar a rejeição. Nenhum DAV foi enviado ao HSE.</p>', usuario), status_code=503)
    if arquivo:  # guarda a recusada: o ADM abre o Excel que o vendedor mandou
        try:
            arquivo.replace(FILA.planilha(i))
        except OSError as exc:
            log.error("DAV %s: não guardei a planilha recusada: %s", i, exc)
    return _erro(usuario, *msgs, origem=i)


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
        if d.get("conferencia") in ("conferindo", "erros"):
            return RedirectResponse(f"/dav/{dav_id}/conferir", status_code=303)
        antigo = banco.dav_ja_gerado(usuario, d["hash_planilha"])
        if antigo:
            with closing(banco._conectar()) as con:
                origens = painel_dav.origens_da_correcao(con, dav_id, usuario)
            for origem in origens:
                banco.dav_vincular_correcao(origem, antigo["id"], usuario)
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


@router.get("/agora")
def historico_agora(usuario: str | None = Depends(_quem), dias: int = 1, estado: str = "",
                    busca: str = "", pagina: int = 1, v: str = ""):
    if not usuario:
        raise HTTPException(401)
    filtros = dict(dias=dias if dias in (1, 7, 30) else 1, estado=estado[:40], busca=busca[:160], pagina=max(1, pagina))
    with closing(banco._conectar()) as con:
        dados = painel_dav.consultar(con, usuario=usuario, agora=agora(), **filtros)
    return resposta_pulso({"dav-historico": historico_dav(dados, filtros), "dav-quadro": quadro_vendedor(dados, filtros),
                           "dav-resumo-dia": resumo_dia(dados)}, v,
                          contexto=dados["periodo"]["inicio"] + str(filtros))


@router.get("/{dav_id}/agora")
def detalhe_agora(dav_id: int, usuario: str | None = Depends(_quem), dias: int = 1,
                  estado: str = "", busca: str = "", pagina: int = 1, v: str = ""):
    if not usuario:
        raise HTTPException(401)
    d = banco.dav(dav_id, usuario)
    if d is None:
        raise HTTPException(404)
    retorno = url_dav("/dav", dict(dias=dias, estado=estado, busca=busca[:160], pagina=pagina))
    return resposta_pulso({"dav-detalhe": detalhe_dav(d, administrador=False, retorno=retorno)}, v,
                          ativo=d["estado"] in ("fila", "gerando"))


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
    corpo = barra_pulso(f"/dav/{dav_id}/agora") + f'<div id="dav-detalhe">{detalhe_dav(d, administrador=False, retorno=retorno)}</div>'
    return _html("DAV", corpo, usuario)


def detalhe_dav(dav: dict, *, administrador: bool, retorno: str) -> str:
    d = dav
    diag = diagnostico(d, administrador=administrador)
    incerto = diag["salvamento"] == "incerto"
    base = "/adm/dav" if administrador else "/dav"
    filtros_retorno = dict(parse_qsl(urlsplit(retorno).query))
    tom = "atencao" if incerto else {"pronto": "ok", "erro": "erro", "rejeitado": "atencao"}.get(d["estado"], "")
    corpo = cabecalho(diag["titulo"], tarja=f"Orçamentos DAV · Envio #{d['id']}",
                       sub=e(d["arquivo"]), acoes=f'<a class="botao2" href="{e(retorno)}">← Voltar ao histórico</a>'
                       + (BOTAO_TEMA if administrador else ""))
    com_erros = d["estado"] == "rascunho" and d.get("conferencia") == "erros"
    motivo = diag["motivo"] if d["estado"] in ("erro", "incerto", "rejeitado") or com_erros else {
        "pronto": "O orçamento foi salvo no HSE. Consulte o documento disponível abaixo.",
        "fila": "Seu orçamento está aguardando a vez de execução.",
        "gerando": "O robô está trabalhando no HSE. Você pode acompanhar por esta tela.",
        "rascunho": "O envio ainda não foi confirmado.", "simulado": "Nada foi salvo no HSE."
    }.get(d["estado"], "Estado não reconhecido. Consulte os detalhes e o responsável pelo robô.")
    if incerto:
        motivo = "O orçamento pode já existir no HSE; confira antes de reenviar."
    acoes = (f'<a class="botao2" href="{base}/{d["id"]}/pdf">Baixar PDF ↓</a>' if d.get("pdf") else "")
    if administrador and FILA.planilha(d["id"]).is_file():
        acoes += f'<a class="botao2" href="/adm/dav/{d["id"]}/planilha">Baixar planilha enviada ↓</a>'
    if (not administrador and d["estado"] in ("erro", "rejeitado") and not incerto
            and diag.get("origem") not in ("automacao", "acesso_hse")):
        acoes += f'<a class="botao2" href="/dav?origem={d["id"]}">Enviar planilha corrigida →</a>'
    if not administrador and d["estado"] == "rascunho":
        acoes += f'<a class="botao2" href="/dav/{d["id"]}/conferir">Conferir antes de gerar →</a>'
    corpo += f'<section class="dav-resultado-box {tom}">{_selo(d)}'
    if d.get("numero"):
        corpo += f'<h2>Orçamento {e(d["numero"])}</h2>'
    corpo += f'<p>{e(motivo)}</p>'
    if d["estado"] in ("erro", "incerto", "rejeitado") or (d["estado"] == "rascunho" and d.get("conferencia") == "erros"):
        # Uma caixa só: a orientação por origem já traz o próximo passo.
        corpo += bloco_orientacao(d, administrador=administrador)
    if d["estado"] == "fila":
        with closing(banco._conectar()) as con:
            posicao = painel_dav.posicao_na_fila(con, d["id"])
        if posicao is not None:
            corpo += f'<p>Posição na fila: {posicao}</p>'
    corpo += f'<div class="dav-acoes">{acoes}</div></section>'
    if diag["tem_aviso"]:
        corpo += '<aside class="dav-aviso"><b>! Aviso do HSE</b><p>Consulte os detalhes disponíveis ou o responsável pela operação.</p></aside>'
    dados = [("Cliente", d.get("cliente") or "Cliente não identificado"), ("Vendedor", d["usuario"]),
             ("Envio", d["criado_em"].replace("T", " ")), ("Início", (d.get("iniciado_em") or "Não iniciado").replace("T", " ")),
             ("Conclusão", (d.get("terminado_em") or "Não concluído").replace("T", " ")),
             ("Etapa conhecida", diag["etapa"] or "Não informada")]
    tempo = tempo_dav(d)
    if tempo:
        dados.append(("Tempo", tempo.removeprefix("Duração: ")))
    corpo += '<section class="cartao dav-card"><h2>Dados do orçamento</h2><dl class="dav-dados">'
    corpo += "".join(f'<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>' for k, v in dados) + '</dl>'
    if diag["itens"]:
        corpo += '<h3>Itens identificados</h3><ul class="dav-lista">' + "".join(f'<li>{e(item)}</li>' for item in diag["itens"]) + '</ul>'
    with closing(banco._conectar()) as con:
        resolvida = painel_dav.resolvidas(con, [d["id"]], None if administrador else d["usuario"])
        origens = painel_dav.origens_da_correcao(con, d["id"], d["usuario"])
    for origem in origens:
        corpo += f'<p class="dav-correcao">Correção do envio <a href="{e(url_dav(f"{base}/{origem}", filtros_retorno))}">#{origem}</a>.</p>'
    if d["id"] in resolvida:
        destino = resolvida[d["id"]]
        corpo += f'<p class="dav-correcao">✓ Resolvida por novo envio <a href="{e(url_dav(f"{base}/{destino}", filtros_retorno))}">#{destino}</a>. O resultado desta tentativa foi preservado.</p>'
    if administrador:
        corpo += _conferencia_admin(d)
    resumo_copia = (f'Envio #{d["id"]}\nHorário do envio: {d["criado_em"]}\n'
                   f'Etapa: {diag["etapa"] or ESTADOS.get(d["estado"], "Não informada")}\n'
                   + diag["diagnostico_copiavel"])
    if d["estado"] in ("erro", "incerto", "rejeitado") or d.get("conferencia") == "erros":
        resumo_copia += (f'\nOrigem: {diag.get("origem_rotulo", "Não identificada")}\n'
                         f'Onde conferir: {diag.get("onde_conferir", "")}\n'
                         + (f'Células: {", ".join(diag["campos"])}\n' if diag.get("campos") else "")
                         + f'Como corrigir: {diag.get("como_corrigir", diag["orientacao"])}')
    corpo += (f'<details id="dav-relatorio"><summary>{"Relatório original e informações técnicas" if administrador else "Detalhes disponíveis ao vendedor"}</summary>'
              f'<pre>{e(diag["relatorio_visivel"] or "Nenhum relatório disponível.")}</pre></details>'
              f'<details id="dav-copia"><summary>Copiar resumo para suporte</summary><pre id="dav-diagnostico">{e(resumo_copia)}</pre>'
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
    return FileResponse(caminho, media_type="application/pdf", filename=caminho.name,
                        headers={"Cache-Control": "no-store"})


@router.get("/{dav_id}/planilha")
def planilha_enviada(dav_id: int, usuario: str | None = Depends(_quem),
                     cookie_adm: str | None = Cookie(None, alias=adm.COOKIE_ADM)):
    d, ir = _acesso(dav_id, usuario, cookie_adm)
    if ir:
        return ir
    caminho = FILA.planilha(dav_id)
    if not caminho.is_file():
        raise HTTPException(404)
    return FileResponse(caminho, filename=Path(d["arquivo"]).name or caminho.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Cache-Control": "no-store"})
