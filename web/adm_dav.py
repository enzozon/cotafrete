"""Gestão de orçamentos DAV, somente leitura e atrás da porta administrativa."""
from __future__ import annotations

from contextlib import closing
import hashlib

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from core import painel_dav
from web import adm, dav_ui, painel_ui as ui
from web.layout import CSS_DAV, cabecalho, e

router = APIRouter(prefix="/adm/dav", include_in_schema=False)


def _porta(cookie: str | None, *, api: bool = False):
    adm._exigir_montado()
    if not adm.autorizado(cookie):
        if api:
            raise HTTPException(401)
        return RedirectResponse("/adm/entrar", status_code=303)
    return None


def _html(titulo: str, corpo: str):
    return HTMLResponse(ui.pagina_painel(titulo,
        f'<style>{CSS_DAV}</style><div class="dav">{corpo}</div>{dav_ui.SCRIPT_ACOES}{dav_ui.SCRIPT_PULSO}',
        base="/adm", ativo="dav"), headers={"Cache-Control": "no-store"})


def _filtros(dias=1, estado="", vendedor="", busca="", pagina=1, categoria="") -> dict:
    return dict(dias=dias if dias in (1, 7, 30) else 1, estado=estado[:40],
                vendedor=vendedor[:160], busca=busca[:160], pagina=max(1, pagina), categoria=categoria[:40])


def indicadores(dados: dict) -> str:
    r = dados["resumo"]
    faixa = '<div class="faixa">'
    for rotulo, chave, tom, icone in (("Tentativas de geração", "tentativas", "marca", "cotacoes"),
                                      ("DAVs criados", "criados", "ok", "preco"),
                                      ("Falhas de criação", "falhas", "erro", "alerta"),
                                      ("Em andamento", "em_andamento", "atencao", "relogio")):
        faixa += ui.numero(rotulo, r[chave], *ui.TOM[tom], icone)
    return faixa + ('</div><p class="dav-note">Contagens por data de submissão no período, antes do filtro de resultado. '
        f'Criados incluem {r["com_aviso"]} com aviso conhecido; {r["avisos_desconhecidos"]} com informação de aviso indisponível. '
        'Reenvios contam como tentativas. Conferências, simulações e rejeições não são gerações.</p>')


def atencao(dados: dict, filtros: dict) -> str:
    r = dados["resumo"]
    corpo = ""
    for n, estado, titulo in ((r["incertos"], "incerto", "Confira no HSE antes de reenviar"),
                               (r["rejeitados"], "rejeitado", "Planilhas rejeitadas antes da geração"),
                               (r["inesperados"], "", "Registros com estado não reconhecido")):
        if n:
            link = dav_ui.url_dav("/adm/dav", filtros, estado=estado, pagina=1)
            corpo += f'<div class="dav-atencao"><span><b>{n} · {e(titulo)}</b></span><a href="{e(link)}">Ver registros →</a></div>'
    for d in dados["atencao"][:5]:
        corpo += (f'<div class="dav-atencao"><span>{dav_ui._selo(d)} <b>#{d["id"]} · {e(d["cliente"] or d["arquivo"])}</b>'
                  f'<small> · {e(d["usuario"])}</small></span><a href="{e(dav_ui.url_dav(f"/adm/dav/{d['id']}", filtros))}">Abrir →</a></div>')
    return corpo or '<p class="dav-vazio">Nenhum resultado incerto ou planilha rejeitada neste período.</p>'


def grupos(dados: dict, filtros: dict) -> str:
    rotulos = {"endereco": "Local de entrega", "acesso_hse": "Acesso ao HSE",
               "planilha": "Validação da planilha", "desconhecido": "Motivo não classificado"}
    linhas = ""
    for categoria, n in sorted(dados["grupos"].items(), key=lambda x: -x[1]):
        link = dav_ui.url_dav("/adm/dav", filtros, estado="erro", categoria=categoria, pagina=1)
        linhas += f'<div class="dav-atencao"><span>{e(rotulos.get(categoria, categoria))}</span><a href="{e(link)}">{n} falha(s) →</a></div>'
    return linhas or '<p class="dav-vazio">Nenhuma falha registrada neste recorte.</p>'


def resumo_principal(con) -> str:
    r = painel_dav.consultar(con, usuario=None, dias=1, agora=dav_ui.agora())["resumo"]
    itens = ""
    for chave, estado, rotulo in (("falhas", "erro", "falhas"), ("incertos", "incerto", "para conferir no HSE"),
                                   ("rejeitados", "rejeitado", "planilhas rejeitadas")):
        link = dav_ui.url_dav("/adm/dav", dict(dias=1, estado=estado))
        itens += f'<p><a href="{e(link)}"><b>{r[chave]}</b> {rotulo} →</a></p>'
    return itens + '<p class="nota">Hoje · por data de submissão · independente das cotações de frete.</p>'


def pulso_principal(con) -> tuple[str, str]:
    html = resumo_principal(con)
    versao = hashlib.sha256((html + dav_ui.agora().date().isoformat()).encode()).hexdigest()
    return versao, html


@router.get("", response_class=HTMLResponse)
def painel(cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM), dias: int = 1, estado: str = "",
           vendedor: str = "", busca: str = "", pagina: int = 1, categoria: str = ""):
    porta = _porta(cookie)
    if porta:
        return porta
    filtros = _filtros(dias, estado, vendedor, busca, pagina, categoria)
    with closing(adm.banco._conectar()) as con:
        dados = painel_dav.consultar(con, usuario=None, agora=dav_ui.agora(), **filtros)
    corpo = cabecalho("Orçamentos DAV", tarja="Administração · Controle da operação",
                     sub="Acompanhe a criação, encontre falhas e entenda o próximo passo.", acoes=ui.BOTAO_TEMA)
    corpo += dav_ui.barra_pulso('/adm/dav/agora') + f'<div id="dav-indicadores">{indicadores(dados)}</div>'
    corpo += (f'<div class="dav-grid"><section class="cartao dav-card"><h2>Precisa de atenção</h2><div id="dav-atencao">{atencao(dados, filtros)}</div></section>'
              f'<section class="cartao dav-card"><h2>Motivos das falhas</h2><div id="dav-grupos">{grupos(dados, filtros)}</div></section></div>'
              '<section class="cartao dav-card"><h2>Atividade dos vendedores</h2>'
              + dav_ui.filtros_dav(dados, filtros, administrador=True)
              + f'<div id="dav-historico">{dav_ui.historico_dav(dados, filtros, administrador=True)}</div></section>')
    return _html("Orçamentos DAV", corpo)


@router.get("/agora")
def ao_vivo(cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM), dias: int = 1, estado: str = "",
            vendedor: str = "", busca: str = "", pagina: int = 1, categoria: str = "", v: str = ""):
    _porta(cookie, api=True)
    filtros = _filtros(dias, estado, vendedor, busca, pagina, categoria)
    with closing(adm.banco._conectar()) as con:
        dados = painel_dav.consultar(con, usuario=None, agora=dav_ui.agora(), **filtros)
    fragmentos = {"dav-indicadores": indicadores(dados), "dav-atencao": atencao(dados, filtros),
                  "dav-grupos": grupos(dados, filtros),
                  "dav-historico": dav_ui.historico_dav(dados, filtros, administrador=True)}
    return dav_ui.resposta_pulso(fragmentos, v, contexto=dados["periodo"]["inicio"] + str(filtros))


@router.get("/{dav_id}/agora")
def detalhe_agora(dav_id: int, cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM),
                  dias: int = 1, estado: str = "", vendedor: str = "", busca: str = "", pagina: int = 1,
                  categoria: str = "", v: str = ""):
    _porta(cookie, api=True)
    d = adm.banco.dav(dav_id, None)
    if d is None:
        raise HTTPException(404)
    retorno = dav_ui.url_dav("/adm/dav", _filtros(dias, estado, vendedor, busca, pagina, categoria))
    return dav_ui.resposta_pulso({"dav-detalhe": dav_ui.detalhe_dav(d, administrador=True, retorno=retorno)}, v,
                                ativo=d["estado"] in ("fila", "gerando"))


@router.get("/{dav_id}", response_class=HTMLResponse)
def detalhe(dav_id: int, cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM),
            dias: int = 1, estado: str = "", vendedor: str = "", busca: str = "", pagina: int = 1, categoria: str = ""):
    porta = _porta(cookie)
    if porta:
        return porta
    d = adm.banco.dav(dav_id, None)
    if d is None:
        raise HTTPException(404)
    retorno = dav_ui.url_dav("/adm/dav", _filtros(dias, estado, vendedor, busca, pagina, categoria))
    return _html("Detalhe DAV", dav_ui.barra_pulso(f"/adm/dav/{dav_id}/agora")
                 + f'<div id="dav-detalhe">{dav_ui.detalhe_dav(d, administrador=True, retorno=retorno)}</div>')


@router.get("/{dav_id}/pdf")
def pdf(dav_id: int, cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM)):
    porta = _porta(cookie)
    if porta:
        return porta
    return dav_ui.pdf(dav_id, usuario=None, cookie_adm=cookie)
