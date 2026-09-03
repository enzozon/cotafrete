"""O painel administrativo: /adm.

Fica fora de web/app.py porque aquele arquivo já passou de 1500 linhas, e
porque as duas telas têm públicos diferentes — a do vendedor e a de quem
administra o sistema.

SEGURANÇA. A tela junta CNPJ, nome e valor de nota de todos os clientes num
lugar só. O Servidor.bat avisa que 0.0.0.0 inclui o Wi-Fi: numa rede com
visitantes, a senha do .env é a única barreira.

Três regras que não devem ser afrouxadas sem pensar:

1. Sem COTAFRETE_ADM_SENHA no ambiente, a rota responde 404. A tela não passa
   a existir "aberta por engano" numa pasta onde ninguém configurou nada.
2. O cookie guarda um HMAC derivado da senha, nunca "sim". Quem tem a senha
   produz o valor — que é exatamente a permissão concedida. Trocar a senha
   invalida todas as sessões, sem lista de sessões para administrar.
3. Senha errada dorme 1s. Não é bloqueio; é o bastante para inviabilizar
   tentativa em massa numa rede local. Se esta tela um dia for para a
   internet, isto precisa virar bloqueio de verdade.
"""

from __future__ import annotations

import hmac
import os
import time
from contextlib import closing
from itertools import groupby

from fastapi import APIRouter, Cookie, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from core.banco import Banco
from core import painel as contas
from web import painel_ui as ui
from web.layout import LOGO, e, moeda, pagina

# O banco chega por INJEÇÃO: `web/app.py` faz `adm.banco = banco` logo
# depois de criar o dele. Importar `web.app` daqui seria circular —
# `web/app.py` importa este módulo para registrar as rotas.
#
# É também o que deixa o teste trocar o banco por um temporário sem
# encostar no servidor.
banco: Banco | None = None

COOKIE_ADM = "cotafrete_adm"

# Acesso mais poderoso que o do vendedor (30 dias) dura menos.
VALIDADE_S = 60 * 60 * 12

# Atraso na senha errada. Ver a regra 3 no topo do módulo.
PAUSA_SENHA_ERRADA_S = 1.0

# include_in_schema=False: a Regra 1 do módulo (404 sem senha configurada) é
# aplicada no HANDLER, não no registro da rota — sem isto as quatro rotas do
# /adm aparecem em /openapi.json e /docs mesmo quando a tela responde 404.
router = APIRouter(prefix="/adm", include_in_schema=False)


def senha_configurada() -> str | None:
    """A senha do .env, ou None se ninguém montou o painel nesta pasta."""
    return os.getenv("COTAFRETE_ADM_SENHA") or None


def token_de(senha: str) -> str:
    """O valor que vai no cookie. Derivado da senha, então trocá-la derruba
    as sessões sozinha."""
    return hmac.new(senha.encode(), b"cotafrete-adm", "sha256").hexdigest()


def autorizado(cookie: str | None) -> bool:
    senha = senha_configurada()
    if not senha or not cookie:
        return False
    # compare_digest, não ==: comparação comum vaza tempo e conta a quem
    # tenta quantos caracteres já acertou.
    #
    # .encode() nos dois lados: compare_digest com `str` só aceita ASCII e
    # levanta TypeError (viraria 500) diante de qualquer outro caractere —
    # um cookie adulterado com acento bastava para derrubar a checagem.
    return hmac.compare_digest(cookie.encode(), token_de(senha).encode())


def _exigir_montado() -> str:
    """404 quando não há senha configurada. Ver a regra 1 no topo."""
    senha = senha_configurada()
    if not senha:
        raise HTTPException(status_code=404)
    return senha


@router.get("/entrar", response_class=HTMLResponse)
def tela_de_entrada():
    _exigir_montado()
    return HTMLResponse(pagina("Painel", f"""
<div class="login">
  <img src="data:image/png;base64,{LOGO}" alt="Ventura">
  <div class="cartao">
    <h1>Painel</h1>
    <p class="sub">Esta tela mostra as cotações de toda a empresa.</p>
    <form method="post" action="/adm/entrar">
      <input name="senha" type="password" placeholder="Senha do painel"
             autofocus required style="margin-bottom:12px">
      <button type="submit" style="width:100%">Entrar</button>
    </form>
  </div>
</div>"""))


@router.post("/entrar")
def entrar(senha: str = Form(...)):
    correta = _exigir_montado()
    # .encode() nos dois lados, pelo mesmo motivo de autorizado(): sem isto,
    # COTAFRETE_ADM_SENHA com acento ou cedilha no .env de produção — o caso
    # provável, escrevendo em português — faz até a senha CERTA levantar
    # TypeError (500) e o painel fica inacessível para sempre.
    if not hmac.compare_digest(senha.encode(), correta.encode()):
        time.sleep(PAUSA_SENHA_ERRADA_S)
        # Sem repetir o que foi digitado: nem na tela, nem em log.
        return HTMLResponse(pagina("Painel", """
<div class="login"><div class="cartao">
  <h1>Painel</h1>
  <div class="alerta">Senha incorreta.</div>
  <p><a href="/adm/entrar">Tentar de novo</a></p>
</div></div>"""), status_code=401)

    r = RedirectResponse("/adm", status_code=303)
    r.set_cookie(COOKIE_ADM, token_de(correta), max_age=VALIDADE_S,
                 httponly=True, samesite="lax")
    return r


@router.get("/sair")
def sair():
    _exigir_montado()
    r = RedirectResponse("/adm/entrar", status_code=303)
    r.delete_cookie(COOKIE_ADM)
    return r


PERIODOS = ((1, "24 h"), (7, "7 dias"), (30, "30 dias"), (3650, "tudo"))
# "24 h", não "hoje": esta faixa usa `_desde(1)` (agora menos 24 horas), e a
# faixa ao vivo do topo (resumo_do_dia) usa o dia do CALENDÁRIO. Às 9h da
# manhã os dois discordam — "hoje" prometia um recorte que a consulta não
# fazia. Só o rótulo mudou; a consulta continua a mesma de sempre.


def _seletor(dias: int) -> str:
    """Qual recorte está na tela. Marcar o escolhido não é enfeite: um número
    lido no período errado é pior que número nenhum."""
    return '<div class="periodos">' + "".join(
        f'<a class="periodo{" atual" if d == dias else ""}" '
        f'href="/adm?dias={d}">{e(rotulo)}</a>'
        for d, rotulo in PERIODOS) + "</div>"


def _faixa(resumo: dict) -> str:
    """A faixa ao vivo. Fragmento SEM casco: é ela que o JavaScript troca.

    O desenho mora em web/painel_ui.py; aqui fica só o nome que a rota
    /adm/agora usa."""
    return ui.faixa(resumo)


def _barra(fracao: float | None) -> str:
    """Barra em CSS puro. Sem biblioteca, funciona sem internet."""
    if fracao is None:
        return '<span class="sem-dado">sem dados ainda</span>'
    # Uma casa decimal: com .0f, 99,6% arredondava para "100%" numa
    # transportadora que acabou de falhar — o número mais otimista possível
    # bem em cima de quem não merecia.
    return (f'<div class="barra"><i style="width:{fracao * 100:.1f}%"></i>'
            f'</div> {fracao * 100:.1f}%')


# As colunas da tabela de saúde, na ordem. A ordem É a garantia: o teste
# confere a linha inteira célula a célula, porque conferir só os cabeçalhos
# passava mesmo com as colunas trocadas no render.
COLUNAS_SAUDE = ("Sucessos", "Recusas", "Falhas", "Interrompidas",
                 "Inesperado")

EXPLICA_SAUDE = (
    "Recusa é a transportadora dizendo não, com o motivo dela — não é "
    "defeito. Interrompida é o servidor tendo reiniciado no meio, e por isso "
    "fica fora do aproveitamento. Inesperado é status que core/painel.py "
    "ainda não conhece — mostrado, e não escondido, porque esconder o "
    'desconhecido foi como "(nenhuma mensagem visível)" nasceu.')


def _saude(linhas: list[dict]) -> str:
    """A tabela detalhada. As roscas em cima dão o panorama; esta dá o
    número, que é o que se leva para uma conversa com a transportadora."""
    if not linhas:
        return '<p class="vazio">Nenhuma cotação no período.</p>'
    corpo = "".join(
        f'<tr><td>{e(l["transportadora"])}</td>'
        f'<td>{l["sucesso"]}</td><td>{l["recusa"]}</td>'
        f'<td>{l["falha"]}</td><td>{l["nossa"]}</td>'
        f'<td>{l["inesperado"]}</td>'
        f'<td>{_barra(l["aproveitamento"])}</td></tr>'
        for l in linhas)
    cabecalho = "".join(f"<th>{e(c)}</th>" for c in COLUNAS_SAUDE)
    return (
        '<div class="rolagem"><table class="saude">'
        f"<thead><tr><th>transportadora</th>{cabecalho}"
        "<th>aproveitamento</th></tr></thead>"
        f"<tbody>{corpo}</tbody></table></div>"
        f'<p class="sub" style="margin:14px 0 0">{e(EXPLICA_SAUDE)}</p>')


def _linha_historico(l: dict) -> str:
    origem, _, destino = l["rota"].partition(" -> ")
    # Tudo que a busca da tela varre, junto e em minúsculas. Montado aqui, e
    # não no JavaScript, porque o texto visível tem marcação no meio (avatar,
    # pastilhas) e procurar dentro do HTML acharia nome de classe CSS.
    procuravel = " ".join(str(v) for v in (
        l["id"], l["usuario"], l["rota"], l["material"] or "")).lower()
    sem_preco = ' class="sem-preco"' if l["melhor_preco"] is None else ""
    return (
        # SEM link de propósito: /cotacao/{id} é a rota do VENDEDOR — exige o
        # cookie dele e filtra por dono em banco.buscar_cotacao. Clicar aqui
        # jogava para /login ou devolvia 404 numa cotação que esta própria
        # tela acabou de listar. A rota própria do adm é Fase 2.
        f'<tr{sem_preco} data-busca="{e(procuravel)}">'
        f'<td class="id">#{l["id"]}</td>'
        f'<td class="hora">{e(l["criado_em"][11:16])}</td>'
        f'<td>{ui.avatar(l["usuario"])}</td>'
        f'<td class="rota">{e(origem)}'
        f'<span style="color:#b6bcc9"> → </span>{e(destino)}</td>'
        f'<td class="material" title="{e(l["material"] or "")}">'
        f'{e(l["material"] or "—")}</td>'
        # Célula do preço SEM classe nem marcação: `moeda(None)` devolve o
        # travessão, e é esse `<td>—</td>` cru que o teste procura para
        # garantir que "sem preço" nunca vire "R$ 0,00".
        f'<td>{moeda(l["melhor_preco"])}</td>'
        f'<td>{ui.pilulas(l["contagem"])}</td></tr>')


def _quantas(n: int) -> str:
    """A mesma frase que o JavaScript da busca reescreve — ver SCRIPT."""
    return f'{n} cotaç{"ões" if n != 1 else "ão"}'


def _historico(linhas: list[dict]) -> str:
    """As cotações agrupadas por dia.

    Agrupar não é enfeite: a lista corrida obrigava a ler a data em toda
    linha para saber se ainda era hoje. `groupby` funciona porque
    `contas.historico` já devolve da mais nova para a mais velha — dias
    iguais chegam grudados."""
    if not linhas:
        return '<p class="vazio">Nenhuma cotação no período.</p>'

    grupos = ""
    for dia, cotacoes in groupby(linhas, key=lambda l: l["criado_em"][:10]):
        do_dia = list(cotacoes)
        # `data-todas` guarda a contagem cheia porque a busca reescreve este
        # número para o que sobrou na tela: um cabeçalho dizendo "12 cotações"
        # em cima de uma linha só é um número mentindo.
        quantas = e(_quantas(len(do_dia)))
        grupos += (
            '<tbody><tr class="dia"><td colspan="7">'
            f"{e(ui.dia_por_extenso(dia))}"
            f'<span class="conta" data-todas="{quantas}">{quantas}</span>'
            "</td></tr>"
            + "".join(_linha_historico(l) for l in do_dia)
            + "</tbody>")

    return (
        '<div class="rolagem"><table class="historico">'
        "<thead><tr><th>nº</th><th>hora</th><th>quem</th><th>rota</th>"
        "<th>material</th><th>melhor preço</th><th>resultado</th></tr></thead>"
        f"{grupos}</table>"
        '<p class="nada" id="nada">Nenhuma cotação bate com a busca.</p></div>')


@router.get("/agora", response_class=HTMLResponse)
def agora(adm: str | None = Cookie(None, alias=COOKIE_ADM)):
    """Só a faixa. Tem os mesmos dados da tela, então exige o mesmo cookie."""
    _exigir_montado()
    if not autorizado(adm):
        return RedirectResponse("/adm/entrar", status_code=303)
    with closing(banco._conectar()) as con:
        return HTMLResponse(_faixa(contas.resumo_do_dia(con)))


# Fica FORA do f-string do corpo: chave de JavaScript dentro de f-string
# precisa ser duplicada, e `{{` espalhado por trinta linhas é o tipo de coisa
# que quebra na próxima edição sem ninguém perceber.
SCRIPT = """
// Troca SÓ a faixa. Recarregar a página inteira perderia a rolagem de quem
// estivesse lendo a tabela embaixo.
setInterval(async () => {
  try {
    const r = await fetch('/adm/agora');
    // fetch segue redirect por padrão: passadas as 12h do cookie, /adm/agora
    // redireciona para /adm/entrar e o fetch recebe 200 com a PÁGINA DE LOGIN
    // inteira — r.ok sozinho não percebe isso, e o <!doctype> inteiro ia
    // parar dentro da faixa. r.redirected denuncia que a resposta veio de
    // outro lugar.
    if (r.ok && !r.redirected) document.getElementById('agora').innerHTML = await r.text();
    else location.href = '/adm/entrar';
  } catch (erro) { /* rede caiu; a próxima volta tenta de novo */ }
}, 10000);

const parado = matchMedia('(prefers-reduced-motion: reduce)').matches;

// Contagem crescente, UMA vez, no carregamento. A troca da faixa lá em cima
// substitui os elementos por outros já com o número certo escrito dentro —
// então ela NÃO reanima, e o painel não pisca de zero a cada 10 segundos na
// cara de quem está tentando ler.
if (!parado) document.querySelectorAll('[data-conta]').forEach(el => {
  const fim = Number(el.textContent);
  if (!fim) return;
  let inicio = null;
  const passo = agora => {
    if (inicio === null) inicio = agora;
    const p = Math.min((agora - inicio) / 700, 1);
    el.textContent = Math.round(fim * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(passo);
  };
  requestAnimationFrame(passo);
});

// Busca no histórico. Esconde a LINHA que não bate e o dia inteiro que ficou
// sem nenhuma — cabeçalho de dia sozinho no meio da tabela parece defeito.
const busca = document.getElementById('busca');
if (busca) busca.addEventListener('input', () => {
  const q = busca.value.trim().toLowerCase();
  let achou = 0;
  document.querySelectorAll('#historico tbody').forEach(grupo => {
    let visiveis = 0;
    grupo.querySelectorAll('tr[data-busca]').forEach(tr => {
      const bate = !q || tr.dataset.busca.includes(q);
      tr.classList.toggle('sumiu', !bate);
      if (bate) visiveis++;
    });
    grupo.classList.toggle('sumiu', visiveis === 0);
    // A contagem do dia passa a contar o que SOBROU na tela. Deixada como
    // veio, ela diria "12 cotações" em cima de uma linha só.
    const conta = grupo.querySelector('.conta');
    conta.textContent = q
      ? visiveis + (visiveis === 1 ? ' cotação' : ' cotações')
      : conta.dataset.todas;
    achou += visiveis;
  });
  document.getElementById('nada').classList.toggle('aparece', achou === 0);
});

// Qual seção está na frente dos olhos, marcada no menu da lateral.
const secoes = document.querySelectorAll('#topo,#movimento,#transportadoras,#historico');
if (window.IntersectionObserver && secoes.length) {
  const olho = new IntersectionObserver(entradas => {
    entradas.forEach(en => {
      if (!en.isIntersecting) return;
      document.querySelectorAll('.lateral a[data-secao]').forEach(a =>
        a.classList.toggle('atual', a.dataset.secao === en.target.id));
    });
  }, {rootMargin: '-15% 0px -75% 0px'});
  secoes.forEach(s => olho.observe(s));
}
"""


@router.get("", response_class=HTMLResponse)
def painel(adm: str | None = Cookie(None, alias=COOKIE_ADM),
           dias: int = 30):
    _exigir_montado()
    if not autorizado(adm):
        return RedirectResponse("/adm/entrar", status_code=303)

    # `dias` vem cru da URL — só precisa ser um int válido para o FastAPI, não
    # um período que a tela ofereça. Sem esta trava, ?dias=999999999 estourava
    # OverflowError no timedelta lá dentro de _desde(), ?dias=15 renderizava
    # sem marcar nenhum link como atual, e ?dias=-5 buscava no futuro e
    # devolvia tudo vazio. Cai em 30 — o padrão — fora dos valores da tela.
    if dias not in {d for d, _ in PERIODOS}:
        dias = 30

    with closing(banco._conectar()) as con:
        resumo = contas.resumo_do_dia(con)
        saude = contas.saude_das_transportadoras(con, dias=dias)
        serie = contas.serie_por_periodo(con, dias=dias)
        vendedores = contas.por_usuario(con, dias=dias)
        linhas = contas.historico(con, dias=dias)

    rotulo = dict(PERIODOS)[dias]
    busca = ('<label class="busca">'
             f'{ui._icone(ui.ICONES["busca"])}'
             '<input id="busca" type="search" autocomplete="off"'
             ' placeholder="buscar nº, vendedor, rota, material"></label>')
    grade = (
        ui.cartao(
            "Movimento", ui.grafico_periodo(serie["pontos"], serie["unidade"]),
            ident="movimento", nota=f"por {serie['unidade']} · {rotulo}",
            direita=ui.legenda((("#4c5fc7", "cotações"),
                                ("#00875a", "com preço"))),
            classe="c8", atraso=0.05)
        + ui.cartao("Como as transportadoras responderam",
                    ui.pizza_de_status(saude), classe="c4", atraso=0.10)
        + ui.cartao("Aproveitamento", ui.roscas_das_transportadoras(saude),
                    ident="transportadoras", nota="da pior para a melhor",
                    classe="c8", atraso=0.15)
        + ui.cartao("Quem mais cotou",
                    ui.ranking(vendedores, "usuario", "cotacoes"),
                    classe="c4", atraso=0.20)
        + ui.cartao("Saúde das transportadoras", _saude(saude),
                    nota="números do período", classe="c12", atraso=0.25)
        + ui.cartao("Histórico", _historico(linhas), ident="historico",
                    nota=f"{len(linhas)} no período", direita=busca,
                    classe="c12", atraso=0.30))

    corpo = f"""
<div class="cabecalho" id="topo">
  <div><h1>Painel</h1>
  <p class="sub">As cotações de toda a empresa, {e(rotulo.lower())}.</p></div>
  <span class="aovivo"><i></i>ao vivo</span>
  {_seletor(dias)}
</div>
<div id="agora">{_faixa(resumo)}</div>
<div class="grade">{grade}</div>
<script>{SCRIPT}</script>"""
    return HTMLResponse(ui.pagina_painel("Painel", corpo))
