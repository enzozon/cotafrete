"""Todo texto das telas legível no tema escuro (e no claro).

Pedido do usuário (24/09/2026), com print: no escuro, "Reler itens do ME",
"Limpar no ME", "Testar sem salvar"... eram texto #061021 sobre o papel
#101b30 — 1.1:1, presente e ilegível. A causa era UMA regra
(`[data-tema=escuro] button{color:var(--sobre-marca)}`) pegando também o
botão secundário, que não tem preenchimento da marca.

Aqui o próprio app gera as páginas (com dados: fretes em todos os status,
cotações do ME em todos os status, botões travados), o Chromium as abre em
cada tema e mede a razão de contraste WCAG de cada texto visível contra o
fundo que ele tem de verdade (fundos dos ancestrais compostos, opacidade
acumulada). Mínimo 4.5:1; 3:1 para texto grande. Desabilitado também conta:
o pedido foi "o usuário conseguir ler".
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from mercado_eletronico import lista
from tests.apoio import entrar
from tests.test_web_cotacao import CARGA
from web import adm, me_ui
from web import app as app_web

FIX = Path(__file__).resolve().parent / "fixtures" / "me_real"
SENHA = "senha-de-teste-123"

# Mede cada elemento com texto próprio visível; devolve os abaixo do mínimo.
JS_CONTRASTE = r"""() => {
  const parse = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0],p[1],p[2],p.length>3?p[3]:1]; };
  const lum = c => { const f = v => { v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4); };
    return 0.2126*f(c[0])+0.7152*f(c[1])+0.0722*f(c[2]); };
  const over = (top, bot) => { const a = top[3]; return [top[0]*a+bot[0]*(1-a), top[1]*a+bot[1]*(1-a), top[2]*a+bot[2]*(1-a), 1]; };
  const fundo = el => { const pilha = []; let grad = false;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage && cs.backgroundImage.includes('gradient')) {
        const c = parse(cs.backgroundImage); if (c) { pilha.push(c); grad = true; if (c[3] >= 1) break; } }
      const c = parse(cs.backgroundColor); if (c && c[3] > 0) { pilha.push(c); if (c[3] >= 1) break; } }
    let base = [255,255,255,1]; for (let i = pilha.length-1; i >= 0; i--) base = over(pilha[i], base);
    return [base, grad]; };
  const opac = el => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (['SCRIPT','STYLE','NOSCRIPT','svg','path','OPTION'].includes(el.tagName)) continue;
    let txt = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
    if ((el.tagName === 'INPUT' && !['hidden','checkbox','radio'].includes(el.type)) || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA')
      txt = el.value || el.placeholder || '';
    if (el.tagName === 'INPUT' && ['button','submit'].includes(el.type)) txt = el.value;
    if (!txt) continue;
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (r.width < 1 || r.height < 1 || cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (el.closest('details:not([open])') && !el.closest('summary')) continue;
    const [bg, grad] = fundo(el);
    let fg = parse(cs.color); if (!fg) continue;
    fg = [fg[0], fg[1], fg[2], fg[3] * opac(el)];
    const cor = over(fg, bg);
    const l1 = lum(cor), l2 = lum(bg);
    const razao = (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);
    const grande = parseFloat(cs.fontSize) >= 24 || (parseFloat(cs.fontSize) >= 18.66 && parseInt(cs.fontWeight) >= 700);
    const minimo = grande ? 3 : 4.5;
    if (razao < minimo) out.push({razao: +razao.toFixed(2), tag: el.tagName.toLowerCase(),
      cls: (el.className && el.className.baseVal === undefined ? el.className : '') || '', disabled: !!el.disabled,
      texto: txt.slice(0,50), cor: cs.color, fundo: 'rgb(' + bg.slice(0,3).map(Math.round).join(',') + ')', grad});
  }
  return out;
}"""


PARADO = ("<style>*,*::before,*::after{transition:none!important;"
          "animation:none!important}</style>")


@pytest.fixture(scope="module")
def navegador():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def site(monkeypatch, tmp_path):
    """O app com dados de verdade em todas as telas que têm tema."""
    b = Banco(tmp_path / "t.db")
    for m in (app_web, adm, me_ui):
        monkeypatch.setattr(m, "banco", b)
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setenv("GROQ_API_KEY", "x")   # mostra a caixa "Colar o pedido" em /
    monkeypatch.setattr(me_ui, "FONTE", lambda c: lista.ler_busca(
        json.loads((FIX / f"lista_{c}.json").read_text(encoding="utf-8"))))
    monkeypatch.setattr(me_ui, "LEITOR", lambda c, n: [
        p.read_text(encoding="utf-8") for p in sorted(FIX.glob(f"{n}_p*.html"))])
    monkeypatch.setattr(me_ui, "DISPARAR", lambda fn, *a: fn(*a))
    monkeypatch.setattr(me_ui, "VARREDURA", me_ui.EstadoVarredura())

    cid = b.salvar_cotacao("enzo", CARGA)
    for t, st, v, erro in (("camilo", "cotado", Decimal("812.40"), None),
                           ("translovato", "recusado", None, "CEP fora de área"),
                           ("generoso", "erro", None, "TimeoutError: site não respondeu"),
                           ("dellavolpe", "aguardando_retorno", None, None),
                           ("braspress", "interrompido", None, "servidor reiniciou")):
        b.salvar_resultado(cid, t, status=st, valor=v, erro=erro,
                           prazo="5 dias úteis" if v else None,
                           validade=date.today() + timedelta(days=7) if v else None)

    me_ui.atualizar(["ventura", "uniao"])
    ids = {c["numero"]: c["id"] for c in b.me_cotacoes()}
    for i in ids.values():
        me_ui.carregar_itens(i)
    me_ui.gravar_formulario(ids[23052403], {
        "validade_dias": "30", "preco_10": "5,00", "ncm_10": "123", "prazo_10": "30",
        "marca_10": "3M", "obs_10": "", "origem_10": "2", "preco_20": "", "obs_20": "fora de linha"})
    b.me_registrar(ids[23052403], "erro do robô", "TimeoutError: o Salvar não gerou o POST", "enzo")
    b.me_trocar_status(ids[23052403], ("pendente",), "erro", erro="TimeoutError")
    # a do print do usuário: robô trabalhando, botões travados
    b.me_trocar_status(ids[23049227], ("pendente",), "salvando")
    b.me_registrar_varredura("uniao", ok=False, erro="TimeoutError: lista não respondeu")

    cliente = entrar(TestClient(app_web.app), app_web)
    cliente.cookies.set(adm.COOKIE_ADM, adm.token_de(SENHA))
    paginas = ["/", "/historico", f"/cotacao/{cid}", "/documentacao", "/me",
               *(f"/me/{i}" for i in ids.values()),
               "/adm", f"/adm/cotacao/{cid}", "/adm/me", *(f"/adm/me/{i}" for i in ids.values())]
    return {p: cliente.get(p).text for p in paginas}


@pytest.mark.parametrize("tema", ["escuro", "claro"])
def test_todo_texto_legivel(navegador, site, tema):
    ruins = []
    pg = navegador.new_page(viewport={"width": 1440, "height": 900})
    pg.route("**/*", lambda r: r.abort())          # nada sai: só o HTML do app
    try:
        for caminho, html in site.items():
            # Mede o estado FINAL: as telas entram com animação que parte de
            # opacidade 0, e a troca de tema tem transição de cor.
            pg.set_content(html.replace("</head>", PARADO + "</head>", 1),
                           wait_until="domcontentloaded")
            pg.evaluate(f"() => {{ document.documentElement.dataset.tema = '{tema}';"
                        " document.querySelectorAll('details').forEach(d => d.open = true); }")
            ruins += [f"{caminho}: {a['razao']}:1 <{a['tag']} class='{a['cls']}'> «{a['texto']}» "
                      f"{a['cor']} sobre {a['fundo']}" for a in pg.evaluate(JS_CONTRASTE)
                      if not a["grad"]]
    finally:
        pg.close()
    assert not ruins, "\n".join(ruins)


def test_o_botao_secundario_nao_herda_a_tinta_do_botao_cheio():
    """A causa do print, dita em uma linha: a regra do texto sobre a marca
    não pode pegar o `.botao2`."""
    from web.layout import CSS
    assert '[data-tema="escuro"] button:not(.tema):not(.botao2){color:var(--sobre-marca)}' in CSS
