"""O Mercado Eletrônico no painel do administrador: /adm/me e /adm/me/{id}.

Pedido do usuário (24/09/2026): acompanhar os erros e o histórico das
cotações do ME como já se acompanha os fretes — sem precisar entrar no ME a
toda hora. Mesmo casco, mesma senha e mesmo "ao vivo" do /adm; os números
saem de `core/painel_me.py`.

O que a tela responde, de cima para baixo:
- quantas cotações estão abertas, salvas sem envio, com erro e fechando;
- o que precisa de alguém AGORA (robô falhou, rascunho esquecido perto do
  prazo, leitura do ME parada);
- o movimento do período, a saúde da leitura por conta e quem salvou;
- as cotações e o histórico inteiro de eventos, com filtro e busca.

Só leitura: daqui não se salva nem se envia nada. Quem mexe é a tela /me.
"""

from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from core import painel_me as pm
from mercado_eletronico import painel as pn
from mercado_eletronico import revisao as rv
from web import adm
from web import painel_ui as ui
from web.layout import e, print_embutido

router = APIRouter(prefix="/adm/me", include_in_schema=False)

CONTAS = {"ventura": "VENTURA", "uniao": "UNIÃO"}
PERIODOS = adm.PERIODOS
agora = datetime.now   # trocável no teste


def _porta(cookie: str | None):
    """A mesma porta do /adm: 404 sem senha no .env, login sem cookie."""
    adm._exigir_montado()
    if not adm.autorizado(cookie):
        return RedirectResponse("/adm/entrar", status_code=303)
    return None


def _periodo(dias: int) -> int:
    return dias if dias in {d for d, _ in PERIODOS} else 30


def _url(**q) -> str:
    return "/adm/me?" + urlencode({k: v for k, v in q.items() if v not in ("", None, 0)})


def _hora(iso: str | None) -> str:
    return pm._hora(iso)


def _selo(status: str) -> str:
    tom = {"pendente": "marca", "salvando": "roxo", "salva": "atencao", "erro": "erro",
           "enviada": "ok", "recusada": "neutro", "vencida": "erro"}.get(status, "neutro")
    cor, fraca = ui.TOM[tom]
    rotulo = pn.ROTULO.get(pn.Status(status), status) if status in {s.value for s in pn.Status} else status
    return f'<span class="pilula" style="color:{cor};background:{fraca}">{e(rotulo)}</span>'


# ------------------------------------------------------------- pedaços vivos
def _faixa(r: dict) -> str:
    return (
        '<div class="faixa">'
        + ui.numero("abertas no ME", r["abertas"], *ui.TOM["marca"], "cotacoes", conta=True)
        + ui.numero("salvas sem enviar", r["salvas"], *ui.TOM["atencao"], "relogio", conta=True)
        + ui.numero("com erro do robô", r["erros"], *ui.TOM["erro"], "alerta", conta=True,
                    ruim=bool(r["erros"]))
        + ui.numero("fecham em 24 h", r["urgentes"], *ui.TOM["atencao"], "relogio", conta=True,
                    ruim=bool(r["urgentes"]))
        + "</div>")


def _atencao(itens: list[dict]) -> str:
    if not itens:
        return '<p class="vazio">Nada precisando de atenção agora.</p>'
    linhas = ""
    for i in itens:
        cor = ui.TOM["erro" if i["nivel"] == "critico" else "atencao"][0]
        link = (f'<span class="quais"><a href="/adm/me/{i["cid"]}">abrir</a></span>'
                if i["cid"] else "")
        linhas += (f'<div class="alerta-linha"><span class="sino" style="color:{cor}">'
                   f'{ui._icone(ui.ICONES["alerta"])}</span>'
                   f'<span class="diz"><b>{e(i["titulo"])}</b>'
                   f'<p class="porque">{e(i["detalhe"])}</p></span>{link}</div>')
    return f'<div class="alertas">{linhas}</div>'


def _eventos(linhas: list[dict]) -> str:
    if not linhas:
        return '<p class="vazio">Nenhum evento no período.</p>'
    corpo = ""
    for l in linhas:
        procuravel = " ".join(str(v or "") for v in (
            l["numero"], l["conta"], l["evento"], l["detalhe"], l["usuario"])).lower()
        cor = f' style="color:{ui.TOM["erro"][0]};font-weight:700"' if l["problema"] else ""
        cot = (f'<a href="/adm/me/{l["cid"]}">{l["numero"]}</a>' if l["cid"] else "—")
        abrir = f' data-abrir="/adm/me/{l["cid"]}"' if l["cid"] else ""
        corpo += (f'<tr class="linha" data-busca="{e(procuravel)}"{abrir}>'
                  f'<td class="hora">{e(_hora(l["quando"]))}</td>'
                  f'<td>{e(CONTAS.get(l["conta"], l["conta"] or ""))}</td>'
                  f'<td class="id">{cot}</td>'
                  f'<td{cor}>{e(l["evento"])}</td>'
                  f'<td class="material" title="{e(l["detalhe"] or "")}">{e(l["detalhe"] or "")}</td>'
                  f'<td>{e(l["usuario"] or "sistema")}</td></tr>')
    return ('<div class="rolagem"><table class="saude"><thead><tr><th>quando</th><th>conta</th>'
            '<th>cotação</th><th>evento</th><th>detalhe</th><th>quem</th></tr></thead>'
            f'<tbody>{corpo}</tbody></table></div>'
            '<p id="nada" class="vazio" hidden>Nada bate com a busca.</p>')


def _cotacoes(linhas: list[dict], momento: datetime) -> str:
    if not linhas:
        return '<p class="vazio">Nenhuma cotação do ME no período.</p>'
    corpo = ""
    for c in linhas:
        lim = pn.hora_de_brasilia(c["data_limite"])
        st = pn.Status(c["status"])
        prazo = pn.prazo(lim, momento).texto if st in pn.ABERTOS else ""
        aviso = pn.alerta(st, lim, momento)
        problemas = (f'<span class="pilula" style="color:{ui.TOM["erro"][0]};'
                     f'background:{ui.TOM["erro"][1]}">{c["n_problemas"]} problema(s)</span>'
                     if c["n_problemas"] else "")
        corpo += (
            f'<tr class="linha" data-abrir="/adm/me/{c["id"]}">'
            f'<td class="id"><a href="/adm/me/{c["id"]}">{c["numero"]}</a></td>'
            f'<td>{e(CONTAS.get(c["conta"], c["conta"]))}</td>'
            f'<td>{e(c["empresa"] or "")}<br><small>{e(c["comprador"] or "")}</small></td>'
            f'<td class="hora">{e(_hora(c["data_limite"]))}<br><small>{e(prazo)}</small></td>'
            f'<td>{_selo(c["status"])}'
            + (f'<br><small style="color:{ui.TOM["erro"][0]}">{e(aviso)}</small>' if aviso else "")
            + f'</td><td>{c["n_com_preco"]}/{c["n_itens"]}</td>'
            f'<td>{e(c["salvo_por"] or "—")}<br><small>{e(_hora(c["salvo_em"]))}</small></td>'
            f'<td>{problemas}</td><td class="seta">›</td></tr>')
    return ('<div class="rolagem"><table class="saude"><thead><tr><th>cotação</th><th>conta</th>'
            '<th>empresa / comprador</th><th>data limite</th><th>status</th><th>itens c/ preço</th>'
            '<th>salva por</th><th>problemas</th><th></th></tr></thead>'
            f'<tbody>{corpo}</tbody></table></div>')


def _leitura(linhas: list[dict]) -> str:
    corpo = ""
    for l in linhas:
        ult = l["ultima"]
        if ult is None:
            estado = '<span class="sem-dado">ainda não leu</span>'
        elif l["falhas_seguidas"]:
            cor, fraca = ui.TOM["erro"]
            estado = (f'<span class="pilula" style="color:{cor};background:{fraca}">'
                      f'falhando ({l["falhas_seguidas"]}×)</span>')
        else:
            cor, fraca = ui.TOM["ok"]
            estado = f'<span class="pilula" style="color:{cor};background:{fraca}">ok</span>'
        ok = l["ultima_ok"]
        corpo += (f'<tr><td>{e(CONTAS.get(l["conta"], l["conta"]))}</td><td>{estado}</td>'
                  f'<td class="hora">{e(_hora(ult["quando"]) if ult else "—")}</td>'
                  f'<td class="hora">{e(_hora(ok["quando"]) if ok else "—")}'
                  + (f' <small>({ok["cotacoes"]} pendentes, {ok["duracao_s"]} s)</small>' if ok else "")
                  + f'</td><td class="material" title="{e(l["ultimo_erro"] or "")}">'
                  f'{e(l["ultimo_erro"] or "")}</td></tr>')
    return ('<div class="rolagem"><table class="saude"><thead><tr><th>conta</th><th>agora</th>'
            '<th>última leitura</th><th>última que deu certo</th><th>erro</th></tr></thead>'
            f'<tbody>{corpo}</tbody></table></div>')


def _dados(con, dias: int, conta: str, status: str, problemas: bool) -> dict:
    momento = agora()
    return {
        "v": pm.versao(con),
        "faixa": _faixa(pm.resumo(con, momento)),
        "atencao": _atencao(pm.atencao(con, momento, tuple(CONTAS))),
        "cotacoes": _cotacoes(pm.cotacoes(con, dias, conta or None, status or None), momento),
        "eventos": _eventos(pm.eventos(con, dias, conta or None, problemas)),
        "leitura": _leitura(pm.leitura_por_conta(con, tuple(CONTAS))),
    }


# ---------------------------------------------------------------------- rotas
@router.get("/agora")
def ao_vivo(adm_cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM), dias: int = 30,
            conta: str = "", status: str = "", problemas: int = 0, v: str = ""):
    if (porta := _porta(adm_cookie)) is not None:
        return porta
    with closing(adm.banco._conectar()) as con:
        if v and v == pm.versao(con):
            return Response(status_code=204)
        return JSONResponse(_dados(con, _periodo(dias), conta if conta in CONTAS else "",
                                   status, bool(problemas)))


SCRIPT = """
const PULSO_MS = 10000;
let versao = document.getElementById('me-painel').dataset.versao || '';
function aplicarBusca() {
  const campo = document.getElementById('busca');
  const q = campo ? campo.value.trim().toLowerCase() : '';
  let achou = 0;
  document.querySelectorAll('#me-eventos tr[data-busca]').forEach(tr => {
    const bate = !q || tr.dataset.busca.includes(q);
    tr.hidden = !bate; if (bate) achou++;
  });
  const nada = document.getElementById('nada');
  if (nada) nada.hidden = achou !== 0 || !q;
}
document.getElementById('busca')?.addEventListener('input', aplicarBusca);
document.addEventListener('click', ev => {
  const tr = ev.target.closest('tr[data-abrir]');
  if (!tr || ev.target.closest('a')) return;
  location.href = tr.dataset.abrir;
});
async function pulsar() {
  const q = new URLSearchParams(location.search); q.set('v', versao);
  try {
    const r = await fetch('/adm/me/agora?' + q);
    if (r.redirected) { location.href = '/adm/entrar'; return; }
    if (r.status === 204 || !r.ok) return;
    const d = await r.json();
    versao = d.v;
    for (const k of ['faixa', 'atencao', 'cotacoes', 'eventos', 'leitura']) {
      const alvo = document.getElementById('me-' + k);
      if (alvo) alvo.innerHTML = d[k];
    }
    aplicarBusca();
  } catch (erro) { if (!(erro instanceof TypeError)) console.error('[cotafrete]', erro); }
}
setInterval(pulsar, PULSO_MS);
"""


@router.get("", response_class=HTMLResponse)
def painel(adm_cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM), dias: int = 30,
           conta: str = "", status: str = "", problemas: int = 0):
    if (porta := _porta(adm_cookie)) is not None:
        return porta
    dias = _periodo(dias)
    conta = conta if conta in CONTAS else ""
    status = status if status in {s.value for s in pn.Status} else ""
    so_problemas = bool(problemas)
    with closing(adm.banco._conectar()) as con:
        d = _dados(con, dias, conta, status, so_problemas)
        serie = pm.serie(con, dias)
        quem = pm.quem_salvou(con, dias)
    atual = dict(dias=dias, conta=conta, status=status, problemas=int(so_problemas))

    def pastilha(rotulo: str, ligado: bool, perigo: bool = False, **muda) -> str:
        classe = "filtro-p" + (" perigo" if perigo else "") + (" atual" if ligado else "")
        return f'<a class="{classe}" href="{e(_url(**(atual | muda)))}">{e(rotulo)}</a>'

    periodos = '<div class="periodos">' + "".join(
        f'<a class="periodo{" atual" if p == dias else ""}" href="{e(_url(**(atual | {"dias": p})))}">'
        f'{e(r)}</a>' for p, r in PERIODOS) + "</div>"
    filtros = (
        '<div class="filtros"><span class="rotulo">conta</span>'
        + pastilha("todas", not conta, conta="")
        + "".join(pastilha(n, conta == k, conta=k) for k, n in CONTAS.items())
        + '<span class="rotulo" style="margin-left:8px">status</span>'
        + pastilha("todos", not status, status="")
        + "".join(pastilha(pn.ROTULO[s], status == s.value, status=s.value)
                  for s in pn.Status if s is not pn.Status.SALVANDO)
        + "</div>")
    filtro_eventos = ('<div class="filtros">'
                      + pastilha("só problemas", so_problemas, perigo=True, problemas=int(not so_problemas))
                      + "</div>")
    busca = ('<label class="busca">' + ui._icone(ui.ICONES["busca"])
             + '<input id="busca" type="search" autocomplete="off"'
               ' placeholder="buscar nº, evento, erro, pessoa"></label>')
    rotulo = dict(PERIODOS)[dias].lower()

    grade = (
        ui.cartao("Precisa de atenção", f'<div id="me-atencao">{d["atencao"]}</div>',
                  nota="agora", classe="c12", atraso=0.02)
        + ui.cartao("Movimento",
                    ui.grafico_periodo(serie["pontos"], serie["unidade"],
                                       rotulos=("cotações recebidas", "salvas no ME"),
                                       vazio="Nenhuma cotação do ME no período."),
                    nota=f"por {serie['unidade']} · {rotulo}",
                    direita=ui.legenda((("var(--tom-marca)", "recebidas"), ("#00875a", "salvas no ME"))),
                    classe="c8", atraso=0.05)
        + ui.cartao("Quem salvou no ME", ui.ranking(quem, "usuario", "salvas")
                    if quem else '<p class="vazio">Ninguém salvou no período.</p>',
                    classe="c4", atraso=0.10)
        + ui.cartao("Leitura da lista do ME", f'<div id="me-leitura">{d["leitura"]}</div>',
                    nota="a cada 7 min, por conta", classe="c12", atraso=0.15)
        + ui.cartao("Cotações", filtros + f'<div id="me-cotacoes">{d["cotacoes"]}</div>',
                    nota=f"abertas e as vistas em {rotulo}", classe="c12", atraso=0.20)
        + ui.cartao("Histórico de eventos", filtro_eventos + f'<div id="me-eventos">{d["eventos"]}</div>',
                    nota="robô, leitura, revisão por IA, quem fez o quê", direita=busca,
                    classe="c12", atraso=0.25))

    corpo = f"""
<div class="cabecalho" id="topo">
  <div><h1>Mercado Eletrônico</h1>
  <p class="sub">As cotações do ME das duas contas, {e(rotulo)} — sem precisar abrir o ME.</p></div>
  <span class="aovivo"><i></i>ao vivo</span>
  {periodos}
  {ui.BOTAO_TEMA}
</div>
<div id="me-painel" data-versao="{d['v']}"><div id="me-faixa">{d['faixa']}</div></div>
<div class="grade">{grade}</div>
<script>{SCRIPT}</script>"""
    return HTMLResponse(ui.pagina_painel("Mercado Eletrônico", corpo, base="/adm"))


@router.get("/{cid}", response_class=HTMLResponse)
def cotacao(cid: int, adm_cookie: str | None = Cookie(None, alias=adm.COOKIE_ADM)):
    if (porta := _porta(adm_cookie)) is not None:
        return porta
    c = adm.banco.me_cotacao(cid)
    if not c:
        return HTMLResponse(ui.pagina_painel("Não encontrada",
                            ui.voltar_para("/adm/me", "Mercado Eletrônico")
                            + '<p class="vazio">Cotação do ME não encontrada.</p>', base="/adm"),
                            status_code=404)
    momento = agora()
    lim = pn.hora_de_brasilia(c["data_limite"])
    st = pn.Status(c["status"])
    aviso = pn.alerta(st, lim, momento)

    itens = "".join(
        f'<tr><td class="id">{i["numero"]}</td>'
        f'<td class="material" title="{e(i["descricao"] or "")}">{e(i["descricao"] or "")}'
        f'<br><small>{e(i["quantidade"] or "")} {e(i["unidade"] or "")} · entrega '
        f'{e(i["uf_destino"] or "?")}</small></td>'
        f'<td>{e(i["preco"] or "—")}</td><td>{e(i["ncm"] or "")}</td>'
        f'<td>{e(i["prazo_dias"] or "")}</td><td>{e(i["marca"] or "")}</td>'
        f'<td>{e(i["origem"] if i["origem"] is not None else "")}</td>'
        f'<td class="material" title="{e(i["obs"] or "")}">'
        + (("<b>recusado:</b> " if not (i["preco"] or "").strip() and (i["obs"] or "").strip() else "")
           + e(i["obs"] or "")) + "</td></tr>"
        for i in c["itens"])
    tabela_itens = ('<div class="rolagem"><table class="saude"><thead><tr><th>item</th>'
                    '<th>pedido</th><th>preço</th><th>NCM</th><th>prazo</th><th>marca</th>'
                    f'<th>origem</th><th>obs</th></tr></thead><tbody>{itens}</tbody></table></div>'
                    if itens else '<p class="vazio">Os itens ainda não foram lidos do ME.</p>')

    historico = adm.banco.me_historico(cid)
    linhas_hist = [{"quando": h["quando"], "usuario": h["usuario"], "evento": h["evento"],
                    "detalhe": h["detalhe"], "cid": None, "numero": None, "conta": c["conta"],
                    "problema": h["evento"] in pm.EVENTOS_PROBLEMA} for h in reversed(historico)]

    rev = rv.Revisao.de_json(c["revisao_ia"])
    if rev is None:
        ia = '<p class="vazio">Não revisada por IA.</p>'
    elif rev.indisponivel:
        ia = f'<p class="porque">Revisão IA indisponível: {e(rev.erro)}</p>'
    else:
        ia = "<ul>" + "".join(
            f'<li><b>{e(rv.ROTULO_NIVEL[a.nivel])}</b>'
            f'{" · item " + str(a.item) if a.item else ""}: {e(a.mensagem)}</li>'
            for a in rev.alertas) + "</ul>" if rev.alertas else '<p class="vazio">Nenhum alerta.</p>'

    prints = []
    if c["evidencia"]:
        try:
            prints = json.loads(c["evidencia"])
        except ValueError:
            prints = []
    imagens = "".join(print_embutido(p) for p in prints[-3:]) or '<p class="vazio">Sem prints.</p>'

    contexto = (f'{_selo(c["status"])} · prazo {e(_hora(c["data_limite"]))}'
                + (f' ({e(pn.prazo(lim, momento).texto)})' if st in pn.ABERTOS else "")
                + (f' · <b style="color:{ui.TOM["erro"][0]}">{e(aviso)}</b>' if aviso else "")
                + (f'<br>Erro: {e(c["erro"])}' if c["erro"] and st is pn.Status.ERRO else "")
                + (f'<br>Salva por {e(c["salvo_por"])} em {e(_hora(c["salvo_em"]))}' if c["salvo_em"] else "")
                + (f'<br>Enviada em {e(_hora(c["enviada_em"]))}' if c["enviada_em"] else ""))
    grade = (
        ui.cartao("Itens", tabela_itens, nota=f"{len(c['itens'])} itens", classe="c12", atraso=0.02)
        + ui.cartao("Histórico", _eventos(linhas_hist), classe="c8", atraso=0.05)
        + ui.cartao("Revisão por IA", ia, classe="c4", atraso=0.08)
        + ui.cartao("Prints do robô", imagens, nota="os 3 mais recentes", classe="c12", atraso=0.10))
    corpo = f"""
<div class="cabecalho" id="topo">
  <div>{ui.voltar_para("/adm/me", "Mercado Eletrônico")}
  <h1>Cotação {c['numero']} · {e(CONTAS.get(c['conta'], c['conta']))}</h1>
  <p class="sub">{e(c['empresa'] or '')} · {e(c['comprador'] or '')} · {e(c['codigo'] or '')}</p>
  <p class="sub">{contexto}</p></div>
  <a class="voltar" target="_blank" rel="noopener"
     href="https://www.me.com.br/RespostaCotaItem.asp?Cotacao={c['numero']}&SuperCleanPage=">Abrir no ME</a>
  {ui.BOTAO_TEMA}
</div>
<div class="grade">{grade}</div>"""
    return HTMLResponse(ui.pagina_painel(f"ME {c['numero']}", corpo, base="/adm"))
