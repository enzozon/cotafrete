"""Cotafrete — interface do usuário.

    python -m uvicorn web.app:app --port 8000
    # abre http://localhost:8000

FASE 1 do plano: formulário único, as duas transportadoras que devolvem preço
na hora (Camilo e Jadlog) e os três cartões de WhatsApp. Generoso e Della
Volpe entram na fase 2 — são assíncronas e levam ~2 min.

Decisões de tela, todas documentadas em REGRAS_SITE_COTACAO.md:

- UM formulário e UM botão. Ninguém quer "cotar na Camilo"; quer saber quem
  leva mais barato.
- Resultado em DOIS grupos, porque as naturezas são diferentes: as
  automáticas o robô resolve; as de WhatsApp dependem de a pessoa apertar
  enviar.
- Cidade e estado NÃO são campos: saem do CEP. Foi digitar cidade à mão que
  gerou uma ficha dizendo "São José dos Campos" com CEP de São Bernardo.
- Quem falhou aparece COM o erro. Sumir com a transportadora que deu
  problema foi o bug que custou horas neste projeto.

O login é placeholder de propósito: digitou um nome, entrou. Serve para
separar o histórico por pessoa. Não é autenticação e não deve ser exposto
fora da rede local sem virar autenticação de verdade.
"""

from __future__ import annotations

import html
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

load_dotenv(override=False)

from carriers.camilo.adapter import CamiloAdapter
from carriers.jadlog.painel import JadlogPainelAdapter
from core import cep as buscador_cep
from core.banco import Banco
from core.models import (
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, Volume,
)

app = FastAPI(title="Cotafrete — Ventura")
banco = Banco()

COOKIE = "cotafrete_usuario"
LOGO = (Path(__file__).parent / "logo_b64.txt").read_text(encoding="utf-8").strip()

# Só atendem por WhatsApp. O resultado delas NUNCA é automático: o máximo que
# o sistema sabe é que a mensagem foi aberta para envio.
ZAP = [
    ("Movvi Logística", "553194910111"),
    ("Translovato", "558181990635"),
    ("Continental", "5527988928840"),
]

NOMES = {"camilo": "Camilo dos Santos", "jadlog": "Jadlog Entregas"}
NOTAS = {
    "camilo": "Frete fracionado, com coleta. Preço já com taxas e ICMS.",
    "jadlog": "Etiqueta pré-paga. Você leva a encomenda ao balcão.",
}

CSS = """
:root{--tinta:#16181d;--fraco:#6b7280;--borda:#e2e5ea;--fundo:#f5f6f8;
--papel:#fff;--marca:#3b4a9c;--ok:#00875a;--erro:#bf2600;--zap:#25d366}
*{box-sizing:border-box}
body{margin:0;background:var(--fundo);color:var(--tinta);line-height:1.45;
font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--marca)}
.topo{background:var(--papel);border-bottom:1px solid var(--borda);
padding:12px 24px;display:flex;align-items:center;gap:16px}
.topo img{height:38px}
.topo .quem{margin-left:auto;font-size:13px;color:var(--fraco)}
.wrap{max-width:1080px;margin:24px auto;padding:0 24px}
.cartao{background:var(--papel);border:1px solid var(--borda);
border-radius:10px;padding:18px;margin-bottom:16px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--fraco);font-size:13px;margin:0 0 18px}
fieldset{border:1px solid #eceef1;border-radius:8px;margin:0 0 14px;
padding:12px 14px}
legend{font-size:11px;font-weight:700;color:var(--fraco);padding:0 6px;
text-transform:uppercase;letter-spacing:.6px}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
label{display:block;font-size:11px;color:var(--fraco);margin-bottom:3px}
input{width:100%;padding:8px 10px;border:1px solid var(--borda);
border-radius:6px;font-size:14px;font-family:inherit}
button{font:inherit;cursor:pointer;border:0;border-radius:6px;
background:var(--marca);color:#fff;padding:12px 22px;font-weight:600;
font-size:15px}
button:hover{filter:brightness(1.12)}
.resultados{display:grid;gap:12px;
grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.res{border:1px solid var(--borda);border-radius:10px;padding:16px;
background:var(--papel)}
.res.melhor{border-color:var(--ok);box-shadow:0 0 0 1px var(--ok)}
.res .nome{font-weight:700;font-size:14px}
.res .valor{font-size:28px;font-weight:700;color:var(--ok);margin:6px 0 2px}
.res .nota{font-size:12px;color:var(--fraco)}
.falhou{color:var(--erro);font-size:13px;font-weight:600}
.selo{display:inline-block;font-size:10px;font-weight:700;color:#fff;
background:var(--ok);border-radius:99px;padding:2px 8px;letter-spacing:.4px}
.zap{display:flex;align-items:center;gap:10px;border:1px solid var(--borda);
border-radius:8px;padding:10px 12px;text-decoration:none;color:inherit;
margin-bottom:8px;background:var(--papel)}
.zap:hover{border-color:var(--zap)}
.zap .ir{margin-left:auto;background:var(--zap);color:#fff;border-radius:6px;
padding:7px 12px;font-size:13px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:11px;color:var(--fraco);text-transform:uppercase;
letter-spacing:.5px;padding:6px 8px;border-bottom:1px solid var(--borda)}
td{padding:8px;border-bottom:1px solid #f0f1f4}
tr:hover td{background:#fafbfc}
.login{max-width:380px;margin:70px auto;text-align:center}
.login img{height:64px;margin-bottom:18px}
.menu a{margin-right:14px;font-size:13px;text-decoration:none}
"""


def e(v) -> str:
    """Escapa para HTML. O material vem do usuário e vai para a tela."""
    return html.escape(str(v if v is not None else ""))


def moeda(v: Decimal | None) -> str:
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pagina(titulo: str, corpo: str, usuario: str | None = None) -> str:
    quem = ""
    if usuario:
        quem = ('<span class="quem"><span class="menu">'
                '<a href="/">Nova cotação</a><a href="/historico">Histórico</a>'
                f'<a href="/sair">Sair</a></span> <b>{e(usuario)}</b></span>')
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title><style>{CSS}</style></head><body>
<div class="topo"><img src="data:image/png;base64,{LOGO}" alt="Ventura">
{quem}</div>
<div class="wrap">{corpo}</div></body></html>"""


# ------------------------------------------------------------------- login
@app.get("/login", response_class=HTMLResponse)
def tela_login() -> str:
    return pagina("Entrar", f"""
<div class="login">
  <img src="data:image/png;base64,{LOGO}" alt="Ventura">
  <div class="cartao">
    <h1>Cotafrete</h1>
    <p class="sub">Digite seu nome para começar. Suas cotações ficam
    separadas das dos outros.</p>
    <form method="post" action="/login">
      <input name="usuario" placeholder="Seu nome" autofocus required
             style="margin-bottom:12px">
      <button type="submit" style="width:100%">Entrar</button>
    </form>
  </div>
  <p class="sub">Sem senha por enquanto — serve para separar o histórico,
  não para proteger acesso.</p>
</div>""")


@app.post("/login")
def entrar(usuario: str = Form(...)):
    nome = usuario.strip()[:40] or "sem-nome"
    r = RedirectResponse("/", status_code=303)
    r.set_cookie(COOKIE, nome, max_age=60 * 60 * 24 * 30, httponly=True,
                 samesite="lax")
    return r


@app.get("/sair")
def sair():
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(COOKIE)
    return r


# ---------------------------------------------------------------- formulário
PADRAO = {
    "cep_origem": "09895-003", "cep_destino": "29105-770",
    "cnpj_remetente": "60.042.686/0001-05",
    "cnpj_destinatario": "05.954.058/0001-98",
    "cnpj_pagador": "05.954.058/0001-98",
    "peso": "1", "quantidade": "1",
    "comprimento": "30", "largura": "30", "altura": "30",
    "valor_nf": "568,77", "material": "LUVA DE BOMBEIRO",
    "nome": "Enzo Zon", "email": "vendas2@venturainformatica.com.br",
    "whatsapp": "(27) 3339-1891",
}


def campo(nome: str, rotulo: str) -> str:
    return (f'<div><label for="{nome}">{rotulo}</label>'
            f'<input id="{nome}" name="{nome}" value="{e(PADRAO[nome])}"'
            f' required></div>')


@app.get("/", response_class=HTMLResponse)
def formulario(usuario: str | None = Cookie(None, alias=COOKIE)):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(pagina("Nova cotação", f"""
<h1>Nova cotação</h1>
<p class="sub">Preencha uma vez. Cotamos na Camilo e na Jadlog, e preparamos
a mensagem para as três que atendem por WhatsApp.</p>
<form method="post" action="/cotar" class="cartao">
  <fieldset><legend>Rota</legend><div class="grid">
    {campo("cep_origem", "CEP de origem")}
    {campo("cep_destino", "CEP de destino")}
  </div>
  <p class="sub" style="margin:8px 0 0">Cidade e estado saem do CEP — não
  precisa digitar.</p></fieldset>

  <fieldset><legend>Documentos</legend><div class="grid">
    {campo("cnpj_remetente", "CNPJ do remetente")}
    {campo("cnpj_destinatario", "CNPJ do destinatário")}
    {campo("cnpj_pagador", "CNPJ de quem paga")}
  </div></fieldset>

  <fieldset><legend>Carga</legend><div class="grid">
    {campo("peso", "Peso de UM volume (kg)")}
    {campo("quantidade", "Quantidade de volumes")}
    {campo("comprimento", "Comprimento (cm)")}
    {campo("largura", "Largura (cm)")}
    {campo("altura", "Altura (cm)")}
    {campo("valor_nf", "Valor da nota fiscal (R$)")}
    {campo("material", "Material")}
  </div></fieldset>

  <fieldset><legend>Contato</legend><div class="grid">
    {campo("nome", "Nome")}
    {campo("email", "E-mail")}
    {campo("whatsapp", "WhatsApp")}
  </div></fieldset>

  <button type="submit">Cotar fretes</button>
</form>""", usuario))


# -------------------------------------------------------------------- cotar
def _num(txt: str) -> Decimal:
    t = str(txt).strip()
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return Decimal(t)
    except (InvalidOperation, ValueError):
        raise ValueError(f"número inválido: {txt!r}")


def montar_request(d: dict) -> CotacaoRequest:
    """Formulário -> modelo central. Cidade e UF vêm do CEP."""
    origem = buscador_cep.buscar(d["cep_origem"])
    destino = buscador_cep.buscar(d["cep_destino"])
    return CotacaoRequest(
        solicitante=Solicitante(nome=d["nome"], email=d["email"],
                                whatsapp=d["whatsapp"]),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf=origem[1], cidade=origem[0], cep=d["cep_origem"],
                     codigo_ibge=origem[2]),
        destino=Local(uf=destino[1], cidade=destino[0], cep=d["cep_destino"],
                      codigo_ibge=destino[2]),
        remetente=Parte(cnpj=d["cnpj_remetente"]),
        destinatario=Parte(cnpj=d["cnpj_destinatario"]),
        pagador_frete=Parte(cnpj=d["cnpj_pagador"]),
        volumes=[Volume(qtd=int(_num(d["quantidade"])),
                        comprimento_cm=_num(d["comprimento"]),
                        largura_cm=_num(d["largura"]),
                        altura_cm=_num(d["altura"]),
                        peso_kg=_num(d["peso"]))],
        mercadoria=Mercadoria(tipo_material=d["material"]),
        nota_fiscal=NotaFiscal(valor_total=_num(d["valor_nf"])),
    )


@app.post("/cotar", response_class=HTMLResponse)
def cotar(usuario: str | None = Cookie(None, alias=COOKIE),
          cep_origem: str = Form(...), cep_destino: str = Form(...),
          cnpj_remetente: str = Form(...), cnpj_destinatario: str = Form(...),
          cnpj_pagador: str = Form(...), peso: str = Form(...),
          quantidade: str = Form(...), comprimento: str = Form(...),
          largura: str = Form(...), altura: str = Form(...),
          valor_nf: str = Form(...), material: str = Form(...),
          nome: str = Form(...), email: str = Form(...),
          whatsapp: str = Form(...)):
    """Endpoint SÍNCRONO de propósito: o FastAPI o roda numa thread do pool, e
    a API sync do Playwright não pode conviver com um event loop na mesma
    thread."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)

    dados = {k: v for k, v in locals().items() if k != "usuario"}
    try:
        req = montar_request(dados)
    except Exception as exc:
        return HTMLResponse(pagina("Erro", f"""
<div class="cartao"><h1 class="falhou">Não deu para montar a cotação</h1>
<p>{e(exc)}</p><p><a href="/">← voltar e corrigir</a></p></div>""", usuario))

    v = req.volumes[0]
    cotacao_id = banco.salvar_cotacao(usuario, {
        "cep_origem": req.origem.cep, "cep_destino": req.destino.cep,
        "cidade_origem": req.origem.cidade, "uf_origem": req.origem.uf,
        "cidade_destino": req.destino.cidade, "uf_destino": req.destino.uf,
        "peso_kg": req.peso_total_kg, "quantidade": req.quantidade_volumes,
        "comprimento_cm": int(v.comprimento_cm),
        "largura_cm": int(v.largura_cm), "altura_cm": int(v.altura_cm),
        "valor_nf": req.nota_fiscal.valor_total,
        "material": req.mercadoria.tipo_material,
    })

    # As duas em paralelo: ~25s no total, em vez de ~40s em série.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = {
            # confirmar_envio=True na Camilo só quer dizer "clique em
            # simular": é cálculo automático, não entra em fila de vendedor.
            # Sem isso ela para no dry-run e devolve "rascunho" sem preço.
            "camilo": pool.submit(
                lambda: CamiloAdapter().cotar(req, confirmar_envio=True)),
            "jadlog": pool.submit(JadlogPainelAdapter().cotar, req),
        }
        for slug, f in futuros.items():
            try:
                res = f.result()
                banco.salvar_resultado(
                    cotacao_id, slug, status=res.status.value,
                    valor=res.valor_frete, protocolo=res.protocolo,
                    erro=res.erro,
                    evidencia=res.evidencias[-1] if res.evidencias else None)
            except Exception as exc:
                # guardar a falha, não engolir: quem falhou aparece na tela
                banco.salvar_resultado(cotacao_id, slug, status="erro",
                                       erro=f"{type(exc).__name__}: {exc}")

    return RedirectResponse(f"/cotacao/{cotacao_id}", status_code=303)


# ------------------------------------------------------------- ver cotação
def mensagem_whatsapp(c: dict) -> str:
    """Mesmo texto para as três — decisão do Enzo em 14/08/2026."""
    return "\n".join([
        "Boa tarde! Tudo bem?", "", "Pode orçar pra mim, por favor?", "",
        f"ORIGEM: {c['cidade_origem']}/{c['uf_origem']} — CEP {c['cep_origem']}",
        f"DESTINO: {c['cidade_destino']}/{c['uf_destino']} — CEP {c['cep_destino']}",
        "",
        f"TD DE VOLUMES: {c['quantidade']}",
        f"MEDIDAS: {c['comprimento_cm']} cm x {c['largura_cm']} cm x "
        f"{c['altura_cm']} cm",
        f"Peso: {c['peso_kg']} kg",
        f"Valor NF: {moeda(c['valor_nf'])}",
        f"ITEM: {c['material']}",
    ])


@app.get("/cotacao/{cotacao_id}", response_class=HTMLResponse)
def ver_cotacao(cotacao_id: int,
                usuario: str | None = Cookie(None, alias=COOKIE)):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c = banco.buscar_cotacao(cotacao_id, usuario)
    if c is None:
        return HTMLResponse(pagina("Não encontrada", """
<div class="cartao"><h1>Cotação não encontrada</h1>
<p class="sub">Ou ela não existe, ou é de outro usuário.</p>
<p><a href="/historico">← histórico</a></p></div>""", usuario),
            status_code=404)

    precos = [r["valor"] for r in c["resultados"] if r["valor"] is not None]
    melhor = min(precos) if precos else None

    cartoes = ""
    for r in c["resultados"]:
        slug = r["transportadora"]
        if r["valor"] is not None:
            destaque = " melhor" if r["valor"] == melhor else ""
            selo = '<span class="selo">MAIS BARATO</span>' if destaque else ""
            corpo = (f'<div class="valor">{moeda(r["valor"])}</div>'
                     f'<div class="nota">{e(NOTAS.get(slug, ""))}</div>')
            if r["protocolo"]:
                corpo += (f'<div class="nota">Cotação nº '
                          f'{e(r["protocolo"])}</div>')
        else:
            destaque, selo = "", ""
            # Sempre dizer POR QUE não veio preço. "Não retornou preço" sozinho
            # manda o operador adivinhar — e foi status sem explicação que
            # escondeu, neste projeto, cinco envios que nunca saíram.
            motivo = r["erro"] or f"o site respondeu: {r['status']}"
            corpo = ('<div class="falhou">Não retornou preço</div>'
                     f'<div class="nota">{e(motivo[:180])}</div>')
        cartoes += (f'<div class="res{destaque}"><div class="nome">'
                    f'{e(NOMES.get(slug, slug))} {selo}</div>{corpo}</div>')

    texto = quote(mensagem_whatsapp(c))
    zaps = "".join(
        f'<a class="zap" href="https://wa.me/{tel}?text={texto}"'
        f' target="_blank" rel="noopener"><b>{e(nome)}</b>'
        f'<span class="ir">Enviar no WhatsApp</span></a>'
        for nome, tel in ZAP)

    return HTMLResponse(pagina(f"Cotação {cotacao_id}", f"""
<h1>Cotação #{cotacao_id}</h1>
<p class="sub">{e(c['cidade_origem'])}/{e(c['uf_origem'])} →
{e(c['cidade_destino'])}/{e(c['uf_destino'])} · {e(c['quantidade'])} volume(s)
· {e(c['peso_kg'])} kg · {e(c['comprimento_cm'])}×{e(c['largura_cm'])}×{e(c['altura_cm'])} cm
· NF {moeda(c['valor_nf'])} · {e(c['material'])}</p>

<div class="cartao">
  <h2 style="font-size:15px;margin:0 0 12px">Cotadas automaticamente</h2>
  <div class="resultados">{cartoes or '<p class="sub">Nenhum resultado.</p>'}</div>
</div>

<div class="cartao">
  <h2 style="font-size:15px;margin:0 0 4px">Precisa de você</h2>
  <p class="sub">Estas atendem por WhatsApp. A mensagem abre pronta — você
  aperta enviar.</p>
  {zaps}
</div>

<p><a href="/">← nova cotação</a> &nbsp;·&nbsp; <a href="/historico">histórico</a></p>
""", usuario))


# ---------------------------------------------------------------- histórico
@app.get("/historico", response_class=HTMLResponse)
def historico(usuario: str | None = Cookie(None, alias=COOKIE)):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    linhas = ""
    for c in banco.listar_cotacoes(usuario):
        linhas += (
            f"""<tr onclick="location='/cotacao/{c['id']}'" style="cursor:pointer">
            <td>#{c['id']}</td>
            <td>{e(c['criado_em'].replace('T', ' '))}</td>
            <td><b>{e(c['material'])}</b></td>
            <td>{e(c['cidade_origem'])}/{e(c['uf_origem'])} →
                {e(c['cidade_destino'])}/{e(c['uf_destino'])}</td>
            <td>{e(c['peso_kg'])} kg</td>
            <td><b>{moeda(c['melhor_preco'])}</b></td></tr>""")

    return HTMLResponse(pagina("Histórico", f"""
<h1>Histórico</h1>
<p class="sub">Suas cotações. Clique numa linha para ver o preço de cada
transportadora.</p>
<div class="cartao"><table>
<tr><th>#</th><th>quando</th><th>material</th><th>rota</th><th>peso</th>
<th>melhor preço</th></tr>
{linhas or '<tr><td colspan="6" class="sub">Nenhuma cotação ainda.</td></tr>'}
</table></div>
<p><a href="/">← nova cotação</a></p>""", usuario))
