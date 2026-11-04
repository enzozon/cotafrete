"""Gestão de orçamentos DAV, somente leitura e atrás da porta administrativa."""
from __future__ import annotations

from contextlib import closing
import json
import logging
import uuid
from datetime import datetime
import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from core import painel_dav
from orcamento import config as cfg_dav, ia
from orcamento.correcao import aplicar
from orcamento.planilha import ErroPlanilha, ler_planilha
from web import adm, dav_ui, painel_ui as ui
from web.layout import CSS_DAV, cabecalho, e

log = logging.getLogger(__name__)
router = APIRouter(prefix="/adm/dav", include_in_schema=False)
IA_USO = Path("davs") / "ia_uso.csv"  # a mesma pasta que o FILA_DAV usa


def _us(v: float) -> str:
    return f"US$ {v:.4f}".replace(".", ",")


def gasto_ia() -> str:
    hoje, mes = ia.gasto(IA_USO, datetime.now())
    limite = cfg_dav._dolares(os.environ.get("IA_LIMITE_DIA_USD", ""), cfg_dav.Config.ia_limite_dia)
    parada = ' · <b>parada até amanhã (limite do dia)</b>' if hoje >= limite else ""
    return (f'<p class="dav-note">Gasto da IA (produto novo): {_us(hoje)} hoje · {_us(mes)} no mês · '
            f'limite {_us(limite)} por dia{parada}. Detalhe por tarefa: <code>python -m orcamento.ia</code>.</p>')


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


def _kpi(rotulo: str, valor, sub: str, tom: str = "") -> str:
    return (f'<div class="dav-kpi {tom}"><span>{e(rotulo)}</span><b>{valor}</b>'
            f'<small>{sub}</small></div>')


def indicadores(dados: dict) -> str:
    r = dados["resumo"]
    pendentes = sum(g["total"] for g in dados["quadro"]["precisa"])
    sucesso = f'{round(100 * r["criados"] / r["tentativas"])}% de sucesso' if r["tentativas"] else "sem tentativas"
    corrigidas = dados.get("corrigidas", 0)
    nota_corr = (f'{corrigidas} já {"resolvido" if corrigidas == 1 else "resolvidos"} fora da conta'
                 if corrigidas else "erros, conferências e avisos")
    inesperados = (f' · {r["inesperados"]} com estado não reconhecido' if r["inesperados"] else "")
    return ('<div class="dav-kpis">'
            + _kpi("Tentativas de geração", r["tentativas"], f'{r["falhas"]} falhas de criação')
            + _kpi("DAVs criados", r["criados"], e(sucesso), "ok")
            + _kpi("Pendentes agora", pendentes, e(nota_corr), "alerta" if pendentes else "")
            + _kpi("Em andamento", r["em_andamento"], f'fila: {r["fila"]} · gerando: {r["gerando"]}', "andamento")
            + '</div><p class="dav-note">Contagens por data de submissão no período, antes do filtro de resultado. '
            f'Criados incluem {r["com_aviso"]} com aviso conhecido. Reenvios contam como tentativas; '
            f'conferências, simulações e rejeições não são gerações{inesperados}.</p>')


# Colunas por quem resolve: o vendedor (planilha/cadastro), nós (robô/acesso) ou conferência no HSE.
COLUNAS_ADM = (("Planilha e cadastro", "erro", "Nenhuma correção de planilha pendente."),
               ("Conosco: automação e acesso", "erro", "Nenhuma falha do robô ou do acesso."),
               ("Conferir no HSE e avisos", "atencao", "Nada para conferir no HSE."))


def _coluna_de(g: dict) -> int:
    if g["tipo"] in ("confirmacao", "aviso"):
        return 2
    if g["origem"] in ("acesso_hse", "automacao") or g["origem_rotulo"] == "Causa não identificada":
        return 1
    return 0


def quadro_adm(dados: dict, filtros: dict) -> str:
    cartoes = [[], [], []]
    for g in dados["quadro"]["precisa"]:
        col = _coluna_de(g)
        tom = "atencao" if col == 2 else "erro"
        for d in g["envios"]:
            cartoes[col].append(dav_ui._cartao(d, dav_ui.url_dav(f'/adm/dav/{d["id"]}', filtros), tom,
                f'<p>{dav_ui.celulas(d.get("campos", []))}{e(g["titulo"])}</p>', extra=f' {e(d["usuario"])} · '))
    colunas = "".join(dav_ui._coluna(titulo, tom, cartoes[i], vazio)
                      for i, (titulo, tom, vazio) in enumerate(COLUNAS_ADM))
    andamento = dav_ui._andamento(dados, filtros, "/adm/dav", administrador=True)
    if andamento:
        colunas += dav_ui._coluna("Em andamento", "andamento", andamento, "")
    link = dav_ui.url_dav("/adm/dav/erros", filtros, pagina=1)
    return (colunas + f'<p class="dav-mais dav-quadro-rodape"><a href="{e(link)}">'
            'Resumo por causa, com orientação e detalhes técnicos →</a></p>')


def ocorrencias(dados: dict, filtros: dict) -> str:
    rotulos = {"falha": "Falha de criação", "rejeitado": "Planilha rejeitada",
               "conferencia": "Conferência inválida", "confirmacao": "Resultado sem confirmação",
               "aviso": "Criado com aviso"}
    corpo = ""
    for g in dados["ocorrencias"]:
        corpo += (f'<section class="cartao dav-card dav-guia-erro" data-tipo="{e(g["tipo"])}"><p class="dav-note">{e(rotulos[g["tipo"]])}</p>'
                  f'<h2>{e(g["titulo"])}</h2><p><b>{g["total"]} {"envio" if g["total"] == 1 else "envios"}</b></p>'
                  f'<p><b>Origem:</b> {e(g["origem_rotulo"])}</p>'
                  f'<p><b>Onde conferir:</b> {e(g["onde_conferir"])}</p>'
                  f'<p><b>Como corrigir:</b> {e(g["como_corrigir"])}</p>')
        for d in g["envios"]:
            link = dav_ui.url_dav(f'/adm/dav/{d["id"]}', filtros)
            corpo += (f'<details id="dav-ocorrencia-{d["id"]}"><summary><a href="{e(link)}">'
                      f'#{d["id"]} · {e(d["cliente"] or d["arquivo"])}</a> · {e(d["usuario"])}'
                      f' · {e(d["criado_em"].replace("T", " ")[:16])}'
                      + (f' · <b>Células:</b> {e(", ".join(d["campos"]))}' if d.get("campos") else "")
                      + '</summary>'
                      f'<pre>{e(d["detalhes"] or "Nenhum detalhe técnico disponível.")}</pre></details>')
        corpo += '</section>'
    return corpo or '<p class="dav-vazio">Nenhuma ocorrência neste recorte.</p>'


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
    corpo = cabecalho("Orçamentos DAV", tarja="Administração", acoes=ui.BOTAO_TEMA)
    corpo += dav_ui.barra_pulso('/adm/dav/agora') + f'<div id="dav-indicadores">{indicadores(dados)}</div>' + gasto_ia()
    corpo += (f'<div id="dav-quadro" class="dav-quadro">{quadro_adm(dados, filtros)}</div>'
              '<section class="cartao dav-card" id="historico"><h2>Histórico de envios</h2>'
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
    fragmentos = {"dav-indicadores": indicadores(dados), "dav-quadro": quadro_adm(dados, filtros),
                  "dav-historico": dav_ui.historico_dav(dados, filtros, administrador=True)}
    return dav_ui.resposta_pulso(fragmentos, v, contexto=dados["periodo"]["inicio"] + str(filtros))


@router.get("/erros", response_class=HTMLResponse)
def erros(cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM), dias: int = 1, estado: str = "",
          vendedor: str = "", busca: str = "", pagina: int = 1, categoria: str = ""):
    porta = _porta(cookie)
    if porta:
        return porta
    filtros = _filtros(dias, estado, vendedor, busca, pagina, categoria)
    with closing(adm.banco._conectar()) as con:
        dados = painel_dav.consultar(con, usuario=None, agora=dav_ui.agora(), **filtros)
    retorno = dav_ui.url_dav("/adm/dav", filtros)
    corpo = cabecalho("Erros e avisos DAV", tarja="Administração", acoes=ui.BOTAO_TEMA)
    corpo += (f'<p><a href="{e(retorno)}">← Orçamentos DAV</a></p>'
              + dav_ui.filtros_dav(dados, filtros, administrador=True, base="/adm/dav/erros")
              + dav_ui.barra_pulso('/adm/dav/erros/agora')
              + f'<div id="dav-ocorrencias">{ocorrencias(dados, filtros)}</div>')
    return _html("Erros e avisos DAV", corpo)


@router.get("/erros/agora")
def erros_agora(cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM), dias: int = 1, estado: str = "",
                vendedor: str = "", busca: str = "", pagina: int = 1, categoria: str = "", v: str = ""):
    _porta(cookie, api=True)
    filtros = _filtros(dias, estado, vendedor, busca, pagina, categoria)
    with closing(adm.banco._conectar()) as con:
        dados = painel_dav.consultar(con, usuario=None, agora=dav_ui.agora(), **filtros)
    return dav_ui.resposta_pulso({"dav-ocorrencias": ocorrencias(dados, filtros)}, v,
                                contexto=dados["periodo"]["inicio"] + str(filtros))


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
                                ativo=d["estado"] in ("fila", "gerando") or d.get("diagnostico_estado") == "pendente")


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


@router.get("/{dav_id}/planilha")
def planilha(dav_id: int, cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM)):
    porta = _porta(cookie)
    if porta:
        return porta
    return dav_ui.planilha_enviada(dav_id, usuario=None, cookie_adm=cookie)


@router.post("/{dav_id}/diagnosticar")
def diagnosticar(dav_id: int, cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM)):
    porta = _porta(cookie)
    if porta:
        return porta
    if adm.banco.dav(dav_id, None) is None:
        raise HTTPException(404)
    if dav_ui.FILA_DIAGNOSTICO is not None:   # enfileirar já grava "pendente"
        dav_ui.FILA_DIAGNOSTICO.enfileirar(dav_id)
    return RedirectResponse(f"/adm/dav/{dav_id}", status_code=303)


@router.post("/{dav_id}/corrigir")
def corrigir(dav_id: int, cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM)):
    """Aprova as correções da IA: cria um envio novo (do vendedor original) para conferir. Nunca gera no HSE."""
    porta = _porta(cookie)
    if porta:
        return porta
    d = adm.banco.dav(dav_id, None)
    if d is None:
        raise HTTPException(404)

    def falha(msg: str):
        retorno = dav_ui.url_dav("/adm/dav", _filtros())
        return _html("Detalhe DAV", f'<p class="dav-note">{e(msg)}</p>'
                     + dav_ui.detalhe_dav(d, administrador=True, retorno=retorno))
    try:
        correcoes = json.loads(d.get("diagnostico") or "{}")["correcoes"]
    except (ValueError, KeyError, TypeError):
        correcoes = None
    if not isinstance(correcoes, list) or not correcoes:
        return falha("Não há correção para aprovar.")
    if not dav_ui.corrigivel_pelo_adm(d):
        return falha("Este envio não pode ser corrigido por aqui: confira no HSE primeiro.")
    ja = adm.banco.dav_correcao_de(dav_id)
    if ja:
        return RedirectResponse(f"/adm/dav/{ja}", status_code=303)
    vendedor = d["usuario"]
    pasta = dav_ui.FILA.pasta / "entrada"
    pasta.mkdir(parents=True, exist_ok=True)
    temp = pasta / f"{uuid.uuid4().hex}.xlsx"
    try:
        try:
            if not aplicar(dav_ui.FILA.planilha(dav_id), correcoes, temp):
                return falha("Nenhuma célula da correção é permitida.")
            o = ler_planilha(temp)
        except ErroPlanilha as exc:
            return falha("A correção gerou uma planilha inválida: " + "; ".join(exc.erros))
        except Exception:
            log.exception("corrigir DAV %s: falha ao aplicar/ler a planilha", dav_id)
            return falha("Não consegui aplicar a correção: planilha original indisponível ou ilegível.")
        hash_ = hashlib.sha256(temp.read_bytes()).hexdigest()
        with dav_ui._TRAVA:
            ja = adm.banco.dav_correcao_de(dav_id)
            if ja:
                return RedirectResponse(f"/adm/dav/{ja}", status_code=303)
            novo = adm.banco.dav_criar(vendedor, f"corrigida_{d['arquivo']}", hash_, o.cliente, conferencia="conferindo")
            temp.replace(dav_ui.FILA.planilha(novo))
            try:
                adm.banco.dav_vincular_correcao(dav_id, novo, vendedor)
            except ValueError as exc:
                adm.banco.dav_atualizar(novo, estado="erro", erro=str(exc))
                return falha(str(exc))
        dav_ui.FILA_CONFERENCIA.enfileirar(novo)
        return RedirectResponse(f"/adm/dav/{novo}", status_code=303)
    finally:
        temp.unlink(missing_ok=True)


@router.get("/{dav_id}/hse/{nome}")
def arquivo_hse(dav_id: int, nome: str, cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM)):
    porta = _porta(cookie)
    if porta:
        return porta
    # só nomes que o próprio robô gravou para este envio: nada de caminho vindo da URL
    arquivo = next((f for f in dav_ui.arquivos_hse(dav_id) if f.name == nome), None)
    if arquivo is None:
        raise HTTPException(404)
    tipo = "image/png" if arquivo.suffix == ".png" else "text/plain; charset=utf-8"
    return FileResponse(arquivo, media_type=tipo, headers={"Cache-Control": "no-store"})
