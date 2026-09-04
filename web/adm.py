"""O painel administrativo: /adm e /adm/cotacao/{id}.

Fica fora de web/app.py porque aquele arquivo já passou de 1500 linhas, e
porque as duas telas têm públicos diferentes — a do vendedor e a de quem
administra o sistema.

São duas telas aqui dentro: o painel, com os números da empresa inteira, e a
de UMA cotação, que abre a de qualquer vendedor. Aquela é a irmã de
`/cotacao/{id}`, que continua sendo do vendedor e continua filtrando por
dono — duas portas separadas, em vez de uma porta com um `if adm` no meio.

SEGURANÇA. A tela junta CNPJ, nome e valor de nota de todos os clientes num
lugar só — e a de uma cotação junta ainda os prints que as transportadoras
devolveram, que também trazem dado de cliente. O Servidor.bat avisa que
0.0.0.0 inclui o Wi-Fi: numa rede com visitantes, a senha do .env é a única
barreira.

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
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Form, HTTPException
from fastapi.responses import (HTMLResponse, JSONResponse,
                               RedirectResponse, Response)

from core.banco import Banco
from core import painel as contas
from web import painel_ui as ui, transportadoras
from web.ficha_ui import ficha_da_cotacao, lugar, quando as _quando
from web.layout import LOGO, e, moeda, pagina, print_embutido

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
# aplicada no HANDLER, não no registro da rota — sem isto as rotas do /adm
# aparecem em /openapi.json e /docs mesmo quando a tela responde 404.
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


def _url(dias: int, quem: str = "", falhas: bool = False) -> str:
    """O endereço do painel com este recorte.

    UM lugar só para montar a URL: o seletor de período precisa preservar o
    vendedor escolhido, e o filtro de vendedor precisa preservar o período.
    Montados em separado, clicar em "7 dias" jogava fora o filtro sem avisar
    — e a tela passava a responder outra pergunta com a mesma cara.

    `quote` no nome porque o login é placeholder ("digitou um nome, entrou"):
    um vendedor chamado "ana & bia" quebraria a query string em duas."""
    partes = [f"dias={dias}"]
    if quem:
        partes.append(f"quem={quote(quem)}")
    if falhas:
        partes.append("falhas=1")
    return "/adm?" + "&".join(partes)


def _seletor(dias: int, quem: str = "", falhas: bool = False) -> str:
    """Qual recorte está na tela. Marcar o escolhido não é enfeite: um número
    lido no período errado é pior que número nenhum."""
    return '<div class="periodos">' + "".join(
        f'<a class="periodo{" atual" if d == dias else ""}" '
        f'href="{e(_url(d, quem, falhas))}">{e(rotulo)}</a>'
        for d, rotulo in PERIODOS) + "</div>"


def _filtros(dias: int, quem: str, falhas: bool,
             vendedores: list[dict]) -> str:
    """Quem cotou e o que deu errado — os dois cortes que o histórico já
    sabia fazer (`contas.historico` tem `usuario` e `so_com_falha` desde o
    primeiro dia) e que nenhuma tela oferecia. A busca do topo filtra o que
    está NA PÁGINA; estes voltam ao banco, e por isso enxergam além das 200
    linhas que a página carregou.

    A lista de vendedores sai do próprio período: um vendedor que não cotou
    nada nos 7 dias escolhidos não vira pastilha que devolve tela vazia."""
    def pastilha(destino: str, rotulo: str, ligado: bool,
                 perigo: bool = False) -> str:
        classe = "filtro-p" + (" perigo" if perigo else "") + \
                 (" atual" if ligado else "")
        return f'<a class="{classe}" href="{e(destino)}">{e(rotulo)}</a>'

    pessoas = pastilha(_url(dias, "", falhas), "todos", not quem)
    pessoas += "".join(
        pastilha(_url(dias, v["usuario"], falhas), v["usuario"],
                 v["usuario"] == quem)
        for v in vendedores)
    so_falha = pastilha(_url(dias, quem, not falhas), "só com falha", falhas,
                        perigo=True)
    return (f'<div class="filtros"><span class="rotulo">quem</span>{pessoas}'
            f'<span class="rotulo" style="margin-left:8px">o quê</span>'
            f'{so_falha}</div>')


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
        f'<tr><td>{e(transportadoras.nome_de(l["transportadora"]))}</td>'
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
    sem_preco = ' sem-preco' if l["melhor_preco"] is None else ""
    # A linha leva para /adm/cotacao/{id}, e NÃO para /cotacao/{id}: aquela é
    # a rota do vendedor — exige o cookie dele e filtra por dono em
    # `banco.buscar_cotacao`. Clicar ali jogava para /login ou devolvia 404
    # numa cotação que esta própria tela acabou de listar. Foi por isso que a
    # linha ficou sem link até 04/09/2026.
    #
    # `data-abrir` é para o JavaScript levar a linha inteira; o número
    # continua sendo um <a> de verdade, que é o que responde ao teclado e ao
    # "abrir em nova aba".
    abrir = f"/adm/cotacao/{l['id']}"
    return (
        f'<tr class="linha{sem_preco}" data-busca="{e(procuravel)}" '
        f'data-abrir="{e(abrir)}">'
        f'<td class="id"><a href="{e(abrir)}">#{l["id"]}</a></td>'
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
        f'<td>{ui.pilulas(l["contagem"])}</td>'
        f'<td class="seta">›</td></tr>')


def _quantas(n: int) -> str:
    """A mesma frase que o JavaScript da busca reescreve — ver SCRIPT."""
    return f'{n} cotaç{"ões" if n != 1 else "ão"}'


def _historico(linhas: list[dict]) -> str:
    """As cotações agrupadas por dia.

    Agrupar não é enfeite: a lista corrida obrigava a ler a data em toda
    linha para saber se ainda era hoje. `groupby` funciona porque
    `contas.historico` já devolve da mais nova para a mais velha — dias
    iguais chegam grudados.

    O `id="tabela"` fica num involucro que existe SEMPRE, inclusive no periodo
    sem cotacao nenhuma: ele e o alvo que a atualizacao ao vivo troca. Posto na
    tabela, ele sumiria junto com ela no dia vazio - e a primeira cotacao do
    dia nao teria onde entrar, deixando a tela presa em "Nenhuma cotacao no
    periodo" ate alguem recarregar. Foi assim que este bug apareceu, num banco
    recem-criado."""
    if not linhas:
        return ('<div id="tabela">'
                '<p class="vazio">Nenhuma cotação no período.</p></div>')

    grupos = ""
    for dia, cotacoes in groupby(linhas, key=lambda l: l["criado_em"][:10]):
        do_dia = list(cotacoes)
        # `data-todas` guarda a contagem cheia porque a busca reescreve este
        # número para o que sobrou na tela: um cabeçalho dizendo "12 cotações"
        # em cima de uma linha só é um número mentindo.
        quantas = e(_quantas(len(do_dia)))
        grupos += (
            '<tbody><tr class="dia"><td colspan="8">'
            f"{e(ui.dia_por_extenso(dia))}"
            f'<span class="conta" data-todas="{quantas}">{quantas}</span>'
            "</td></tr>"
            + "".join(_linha_historico(l) for l in do_dia)
            + "</tbody>")

    return (
        '<div id="tabela"><div class="rolagem"><table class="historico">'
        "<thead><tr><th>nº</th><th>hora</th><th>quem</th><th>rota</th>"
        "<th>material</th><th>melhor preço</th><th>resultado</th>"
        "<th></th></tr></thead>"
        f"{grupos}</table>"
        '<p class="nada" id="nada">Nenhuma cotação bate com a busca.</p>'
        "</div></div>")


def _periodo_valido(dias: int) -> int:
    """O `dias` da URL, ou 30 se nao for um periodo que a tela oferece.

    `dias` vem cru da URL - so precisa ser um int valido para o FastAPI, nao
    um periodo que a tela ofereca. Sem esta trava, ?dias=999999999 estourava
    OverflowError no timedelta la dentro de _desde(), ?dias=15 renderizava sem
    marcar nenhum link como atual, e ?dias=-5 buscava no futuro e devolvia
    tudo vazio.

    Existe uma vez so porque a tela e a atualizacao ao vivo PRECISAM concordar:
    se as duas tratassem `dias` diferente, a tabela seria trocada por um
    recorte que ninguem pediu."""
    return dias if dias in {d for d, _ in PERIODOS} else 30


@router.get("/agora")
def agora(adm: str | None = Cookie(None, alias=COOKIE_ADM),
          dias: int = 30, quem: str = "", falhas: int = 0, v: str = ""):
    """Os pedacos vivos do painel: a faixa do topo e a tabela do historico.

    Devolve 204 quando nada mudou desde a versao `v` que o navegador mandou. E
    o que faz a tela atualizar SO quando entra cotacao ou chega resposta, em
    vez de se redesenhar a cada poucos segundos debaixo de quem esta lendo.

    Recebe os mesmos filtros da tela porque a tabela depende deles: sem
    dias/quem/falhas, a atualizacao trocaria um historico de 7 dias filtrado
    por vendedor pelo de 30 dias inteiro, sem ninguem ter pedido.

    Tem os mesmos dados da tela, entao exige o mesmo cookie."""
    _exigir_montado()
    if not autorizado(adm):
        return RedirectResponse("/adm/entrar", status_code=303)

    dias = _periodo_valido(dias)
    with closing(banco._conectar()) as con:
        versao = contas.versao_do_painel(con)
        # A comparacao vem ANTES de montar qualquer HTML: no caso comum nada
        # mudou, e o trabalho que nao se faz e o que deixa isto barato o
        # bastante para rodar de cinco em cinco segundos.
        if v and v == versao:
            return Response(status_code=204)
        resumo = contas.resumo_do_dia(con)
        linhas = contas.historico(con, dias=dias, usuario=quem or None,
                                  so_com_falha=bool(falhas))

    return JSONResponse({"v": versao, "faixa": _faixa(resumo),
                         "tabela": _historico(linhas)})


# Fica FORA do f-string do corpo: chave de JavaScript dentro de f-string
# precisa ser duplicada, e `{{` espalhado por trinta linhas é o tipo de coisa
# que quebra na próxima edição sem ninguém perceber.
SCRIPT = """
// Intervalo do ao vivo. 5s porque a Jadlog responde em ~15s e a Della Volpe
// em ~110s: mais devagar e a resposta aparece muito depois de existir; mais
// rapido nao adianta, ninguem responde em menos de 15s.
const PULSO_MS = 5000;

// A versao que esta tela esta mostrando. Vai junto no pedido, e o servidor
// devolve 204 enquanto ela continuar sendo a atual - e ai a tela nao e
// tocada. E isso que faz o painel se redesenhar SO quando entra cotacao ou
// chega resposta, em vez de se refazer sozinho a cada cinco segundos debaixo
// de quem esta lendo.
let versao = document.getElementById('agora').dataset.versao || '';

// Busca no historico. Esconde a LINHA que nao bate e o dia inteiro que ficou
// sem nenhuma - cabecalho de dia sozinho no meio da tabela parece defeito.
//
// Funcao com nome, e nao um ouvinte anonimo, porque a atualizacao ao vivo
// precisa chama-la de novo: a tabela nova chega do servidor sem filtro
// nenhum, e quem tinha "generoso" digitado veria a tabela inteira voltar
// sozinha no meio da leitura.
function aplicarBusca() {
  const campo = document.getElementById('busca');
  if (!campo) return;
  const q = campo.value.trim().toLowerCase();
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
    // veio, ela diria "12 cotacoes" em cima de uma linha so.
    const conta = grupo.querySelector('.conta');
    if (conta) conta.textContent = q
      ? visiveis + (visiveis === 1 ? ' cotação' : ' cotações')
      : conta.dataset.todas;
    achou += visiveis;
  });
  const nada = document.getElementById('nada');
  if (nada) nada.classList.toggle('aparece', achou === 0);
}

const busca = document.getElementById('busca');
if (busca) busca.addEventListener('input', aplicarBusca);

// A linha inteira abre a cotacao. O numero dentro dela ja e um link de
// verdade - isto aqui e para o resto da linha, que e onde o dedo cai. O
// clique em cima de um link e devolvido para o proprio link: sem essa
// checagem, "abrir em nova aba" abria a aba E navegava esta.
//
// Delegacao, e nao um ouvinte por linha: a tabela e substituida inteira a
// cada cotacao nova, e ouvinte preso a uma linha morre junto com ela. A
// partir da primeira atualizacao, clicar na linha nao abriria mais nada.
const secaoHistorico = document.getElementById('historico');
if (secaoHistorico) secaoHistorico.addEventListener('click', ev => {
  const tr = ev.target.closest('tr[data-abrir]');
  if (!tr || ev.target.closest('a')) return;
  location.href = tr.dataset.abrir;
});

async function pulsar() {
  // Os filtros da tela vao junto: a tabela depende de dias/quem/falhas, e
  // location.search ja e exatamente isso.
  const busca_url = new URLSearchParams(location.search);
  busca_url.set('v', versao);
  try {
    const r = await fetch('/adm/agora?' + busca_url);
    // fetch segue redirect por padrao: passadas as 12h do cookie, /adm/agora
    // redireciona para /adm/entrar e o fetch recebe 200 com a PAGINA DE LOGIN
    // inteira - r.ok sozinho nao percebe isso. r.redirected denuncia que a
    // resposta veio de outro lugar.
    if (r.redirected) { location.href = '/adm/entrar'; return; }
    if (r.status === 204 || !r.ok) return;   // 204 = nada mudou desde a ultima
    const d = await r.json();
    versao = d.v;
    document.getElementById('agora').innerHTML = d.faixa;
    const tabela = document.getElementById('tabela');
    if (tabela) { tabela.outerHTML = d.tabela; aplicarBusca(); }
  } catch (erro) { /* rede caiu; a proxima volta tenta de novo */ }
}
setInterval(pulsar, PULSO_MS);

const parado = matchMedia('(prefers-reduced-motion: reduce)').matches;

// Contagem crescente, UMA vez, no carregamento. A troca da faixa la em cima
// substitui os elementos por outros ja com o numero certo escrito dentro -
// entao ela NAO reanima, e o painel nao pisca de zero a cada atualizacao na
// cara de quem esta tentando ler.
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

// Qual secao esta na frente dos olhos, marcada no menu da lateral.
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


# Quantos vendedores viram pastilha de filtro. Mais que isto e a fileira
# quebra em três linhas em cima da tabela — o filtro passa a atrapalhar a
# leitura do que ele deveria ajudar a achar. Os oito primeiros do ranking são
# os que cotam de verdade; quem cotou uma vez no mês continua alcançável pela
# busca da própria tela.
VENDEDORES_NO_FILTRO = 8


@router.get("", response_class=HTMLResponse)
def painel(adm: str | None = Cookie(None, alias=COOKIE_ADM),
           dias: int = 30, quem: str = "", falhas: int = 0):
    _exigir_montado()
    if not autorizado(adm):
        return RedirectResponse("/adm/entrar", status_code=303)

    dias = _periodo_valido(dias)
    so_falhas = bool(falhas)

    with closing(banco._conectar()) as con:
        resumo = contas.resumo_do_dia(con)
        versao = contas.versao_do_painel(con)
        saude = contas.saude_das_transportadoras(con, dias=dias)
        serie = contas.serie_por_periodo(con, dias=dias)
        vendedores = contas.por_usuario(con, dias=dias,
                                        limite=VENDEDORES_NO_FILTRO)
        rotas = contas.rotas(con, dias=dias)
        # Só alerta quem ainda está no pipeline automático. Uma
        # transportadora retirada dali (a Della Volpe, em 31/08/2026, por
        # exemplo) nunca mais grava um resultado novo — sem este filtro o
        # alerta dela ficaria preso na tela até sair da janela de `dias`,
        # sem ninguém poder fazer nada para "resolvê-lo".
        avisos = [a for a in contas.falhas_seguidas(con, dias=dias)
                  if a["transportadora"] in transportadoras.AUTOMATICAS]
        # `quem` vem cru da URL e vai direto para o WHERE, como parâmetro
        # ligado (nunca concatenado). Nome que não existe devolve lista
        # vazia, que é a resposta honesta — inventar "todos" seria mostrar a
        # empresa inteira para quem pediu uma pessoa.
        linhas = contas.historico(con, dias=dias, usuario=quem or None,
                                  so_com_falha=so_falhas)

    rotulo = dict(PERIODOS)[dias]
    busca = ('<label class="busca">'
             f'{ui._icone(ui.ICONES["busca"])}'
             '<input id="busca" type="search" autocomplete="off"'
             ' placeholder="buscar nº, vendedor, rota, material"></label>')
    # A seta é literal e não "->": a rota é para ler, não para copiar.
    rotas_na_tela = [{"rota": r["rota"].replace(" -> ", " → "),
                      "cotacoes": r["cotacoes"]} for r in rotas]
    recorte = " · ".join(p for p in (
        f"{len(linhas)} no período", f"de {quem}" if quem else "",
        "só com falha" if so_falhas else "") if p)

    grade = (
        # Os alertas entram PRIMEIRO e só existem quando há o que alertar. Um
        # cartão "nenhum alerta" fixo no topo treina o olho a pular a região —
        # e aí ele pula também no dia em que o alerta está lá.
        (ui.cartao("Precisa de atenção",
                   ui.alertas(avisos, transportadoras.nome_de),
                   nota="falhas seguidas, sem sucesso no meio",
                   classe="c12", atraso=0.02) if avisos else "")
        + ui.cartao(
            "Movimento", ui.grafico_periodo(serie["pontos"], serie["unidade"]),
            ident="movimento", nota=f"por {serie['unidade']} · {rotulo}",
            direita=ui.legenda((("#4c5fc7", "cotações"),
                                ("#00875a", "com preço"))),
            classe="c8", atraso=0.05)
        + ui.cartao("Como as transportadoras responderam",
                    ui.pizza_de_status(saude), classe="c4", atraso=0.10)
        + ui.cartao("Aproveitamento",
                    ui.roscas_das_transportadoras(
                        saude, transportadoras.nome_de),
                    ident="transportadoras", nota="da pior para a melhor",
                    classe="c8", atraso=0.15)
        + ui.cartao("Quem mais cotou",
                    ui.ranking(vendedores, "usuario", "cotacoes"),
                    classe="c4", atraso=0.20)
        + ui.cartao("Saúde das transportadoras", _saude(saude),
                    nota="números do período", classe="c8", atraso=0.25)
        + ui.cartao("Rotas mais cotadas",
                    ui.ranking(rotas_na_tela, "rota", "cotacoes"),
                    nota="origem → destino", classe="c4", atraso=0.28)
        + ui.cartao("Histórico",
                    _filtros(dias, quem, so_falhas, vendedores)
                    + _historico(linhas),
                    ident="historico", nota=recorte, direita=busca,
                    classe="c12", atraso=0.30))

    corpo = f"""
<div class="cabecalho" id="topo">
  <div><h1>Painel</h1>
  <p class="sub">As cotações de toda a empresa, {e(rotulo.lower())}.</p></div>
  <span class="aovivo"><i></i>ao vivo</span>
  {_seletor(dias, quem, so_falhas)}
</div>
<div id="agora" data-versao="{versao}">{_faixa(resumo)}</div>
<div class="grade">{grade}</div>
<script>{SCRIPT}</script>"""
    return HTMLResponse(ui.pagina_painel("Painel", corpo))


# ------------------------------------------------------- uma cotação só

def _quantidade(c: dict) -> int:
    """Quantos volumes, com o chão em 1.

    `quantidade` é INTEGER no esquema, mas as colunas que nasceram depois
    entram como TEXT pelo _migrar — e a tela não pode cair por causa de uma
    linha antiga. Sem volume nenhum a carga não existe, então 1 é o palpite
    seguro: ele só afeta o aviso do preço por volume, e para o lado de não
    avisar."""
    try:
        return max(int(c["quantidade"]), 1)
    except (TypeError, ValueError):
        return 1


def _comparaveis(c: dict, qtd: int) -> list:
    """Os preços que disputam ENTRE SI nesta cotação.

    Quem cotou um volume só, numa carga de vários, fica de fora — a mesma
    regra da tela do vendedor, e agora com a mesma lista
    (`transportadoras.cota_por_volume`). Se as duas telas discordassem, o adm
    cobraria a transportadora errada por um preço que nunca foi o mais
    barato: R$ 33,29 por volume não é mais barato que R$ 69,91 pela carga
    quando são 3 volumes.

    Uma lista só, usada pelo selo e pela faixa do topo: com duas listas, o
    cartão elegeria um vencedor e o número lá em cima diria outro."""
    return [r["valor"] for r in c["resultados"]
            if r["valor"] is not None
            and not transportadoras.cota_por_volume(r["transportadora"], qtd)]


def _melhor_preco(c: dict, qtd: int):
    precos = _comparaveis(c, qtd)
    return min(precos) if precos else None


def _resumo_das_respostas(c: dict) -> tuple[dict[str, int], int]:
    """Quantas respostas por categoria, e quantas trouxeram preco.

    Existe uma vez so porque a tela da cotacao e a atualizacao ao vivo dela
    mostram os MESMOS dois numeros - as pilulas do topo e o "3 de 5 com
    preco" do cabecalho do cartao. Contados em dois lugares, eles passariam a
    discordar na primeira vez que um status novo entrasse no sistema."""
    contagem: dict[str, int] = {}
    for r in c["resultados"]:
        chave = contas.categoria(r["status"])
        contagem[chave] = contagem.get(chave, 0) + 1
    com_preco = sum(1 for r in c["resultados"] if r["valor"] is not None)
    return contagem, com_preco


def _respostas(c: dict) -> str:
    """Um cartão por transportadora que respondeu."""
    qtd = _quantidade(c)
    melhor = _melhor_preco(c, qtd)

    cartoes = ""
    for r in c["resultados"]:
        slug = r["transportadora"]
        incerto = transportadoras.cota_por_volume(slug, qtd)
        avisos = []
        if incerto and r["valor"] is not None:
            avisos.append(
                f"Preço de 1 volume, não da carga. São {qtd} volumes: por "
                f"estimativa, {moeda(r['valor'] * qtd)} no total. Por isso "
                f"ela não disputa o selo de mais barato.")

        miudos = []
        if r["prazo"]:
            miudos.append(f"prazo {r['prazo']}")
        if r["protocolo"]:
            miudos.append(f"cotação nº {r['protocolo']}")
        segundos = contas.duracao_s(c["criado_em"], r["respondido_em"])
        miudos.append(f"respondeu em {ui.segundos_por_extenso(segundos)}"
                      if segundos is not None
                      else "sem hora de resposta guardada")

        cartoes += ui.cartao_resposta(
            nome=transportadoras.nome_de(slug),
            logo=transportadoras.logo_de(slug),
            status=r["status"],
            valor=moeda(r["valor"]) if r["valor"] is not None else "",
            incerto=incerto,
            melhor=(melhor is not None and not incerto
                    and r["valor"] == melhor),
            avisos=tuple(avisos),
            # O texto técnico vai INTEIRO, ao contrário da tela do vendedor,
            # que corta em 400 caracteres. Aqui é onde se investiga: cortar a
            # mensagem esconderia justamente a linha que explica o que houve.
            erro_cru=r["erro"] or "",
            miudos=tuple(miudos),
            print_html=print_embutido(r["evidencia"]))

    if not cartoes:
        return ('<p class="vazio">Nenhuma transportadora respondeu ainda '
                'nesta cotação.</p>')
    return f'<div class="respostas">{cartoes}</div>'


def _numeros_da_cotacao(c: dict) -> str:
    """A faixa do topo da cotação: o que se quer saber antes de ler cartão
    por cartão."""
    qtd = _quantidade(c)
    comparaveis = _comparaveis(c, qtd)
    com_preco = sum(1 for r in c["resultados"] if r["valor"] is not None)
    # Só com DOIS preços comparáveis existe diferença para mostrar. Com um
    # preço só, "R$ 0,00 de diferença" diria que tanto faz — quando na
    # verdade não houve com quem comparar.
    espalhamento = (max(comparaveis) - min(comparaveis)
                    if len(comparaveis) > 1 else None)
    tempos = [s for s in (contas.duracao_s(c["criado_em"], r["respondido_em"])
                          for r in c["resultados"]) if s is not None]

    return (
        '<div class="faixa">'
        + ui.numero("melhor preço", moeda(min(comparaveis) if comparaveis
                                          else None),
                    "#00875a", "#e6f4ee", "preco")
        + ui.numero("responderam com preço",
                    f'{com_preco} de {len(c["resultados"])}',
                    "#4c5fc7", "#eef0fb", "cotacoes")
        + ui.numero("entre a mais barata e a mais cara", moeda(espalhamento),
                    "#d97706", "#fdf3e3", "balanca")
        + ui.numero("até a última resposta",
                    ui.segundos_por_extenso(max(tempos)) if tempos else "—",
                    "#6b7280", "#eef0f4", "relogio")
        + "</div>")


def _tempos(c: dict) -> str:
    return ui.tempos_de_resposta([
        {"nome": transportadoras.nome_de(r["transportadora"]),
         "segundos": contas.duracao_s(c["criado_em"], r["respondido_em"]),
         "cor": ui.CORES[contas.categoria(r["status"])]}
        for r in c["resultados"]])


SCRIPT_COTACAO = """
// Clique amplia o print. Na tela ele fica pequeno, e quem abriu esta pagina
// veio justamente ler o que apareceu no site da transportadora.
//
// Delegacao no documento, e nao um onclick em cada print: os cartoes de
// resposta sao substituidos conforme as transportadoras respondem, e um
// ouvinte posto em cada imagem morreria na primeira atualizacao - o print da
// transportadora que acabou de responder seria justamente o que nao ampliaria.
document.addEventListener('click', ev => {
  const print = ev.target.closest('.print');
  if (print) print.classList.toggle('zoom');
});

// O mesmo ao vivo do painel, com a versao EXATA desta cotacao: aqui a pessoa
// esta olhando a resposta chegar, e a Della Volpe leva ~110s.
const PULSO_MS = 5000;
const numeros = document.getElementById('numeros');
let versao = numeros.dataset.versao || '';

async function pulsar() {
  try {
    const r = await fetch('/adm/cotacao/' + numeros.dataset.cotacao
                          + '/agora?v=' + encodeURIComponent(versao));
    if (r.redirected) { location.href = '/adm/entrar'; return; }
    if (r.status === 204 || !r.ok) return;   // 204 = nada mudou desde a ultima
    const d = await r.json();
    versao = d.v;
    numeros.innerHTML = d.numeros;
    document.getElementById('respostas').innerHTML = d.respostas;
    document.getElementById('tempos').innerHTML = d.tempos;
    document.getElementById('pilulas').innerHTML = d.pilulas;
    // A nota vive no cabecalho do cartao, fora do pedaco trocado. Sem esta
    // linha ela continuaria dizendo "2 de 5 com preco" com cinco precos na
    // tela logo abaixo.
    const nota = document.querySelector('#cartao-respostas .nota');
    if (nota) nota.textContent = d.nota;
  } catch (erro) { /* rede caiu; a proxima volta tenta de novo */ }
}
setInterval(pulsar, PULSO_MS);
"""


@router.get("/cotacao/{cotacao_id}", response_class=HTMLResponse)
def ver_cotacao(cotacao_id: int,
                adm: str | None = Cookie(None, alias=COOKIE_ADM)):
    """Uma cotação inteira, de QUALQUER vendedor.

    É a porta que faltava: `/cotacao/{id}` é a rota do vendedor e filtra por
    dono em `banco.buscar_cotacao` — clicar no histórico do painel dava 404
    numa cotação que a própria tela tinha acabado de listar. Esta rota usa
    `contas.cotacao`, que consulta sem o filtro; aquela NÃO muda, e a
    garantia da tela do vendedor fica intacta.

    Só LEITURA: nada aqui abre WhatsApp, repete cotação ou apaga linha. O
    adm entra para entender o que aconteceu, e as ações continuam sendo de
    quem cotou."""
    _exigir_montado()
    if not autorizado(adm):
        return RedirectResponse("/adm/entrar", status_code=303)

    with closing(banco._conectar()) as con:
        c = contas.cotacao(con, cotacao_id)
        versao = contas.versao_da_cotacao(con, cotacao_id)

    if c is None:
        # 404 de verdade, e com o casco do painel: quem chegou por um link
        # velho precisa do caminho de volta, não de uma página branca.
        #
        # A frase fala da PASTA porque é a explicação provável: o sistema roda
        # em mais de uma cópia (a do Enzo e a do servidor), cada uma com o seu
        # cotafrete.db, e o mesmo número é outra cotação em cada uma.
        return HTMLResponse(ui.pagina_painel("Cotação", f"""
<div class="cabecalho" id="topo"><div>
  {ui.voltar_para("/adm", "Painel")}
  <h1>Cotação #{cotacao_id}</h1>
  <p class="sub">Este número não existe no banco desta pasta.</p>
</div></div>
<div class="grade">{ui.cartao("Não encontrada", '''
<p class="vazio" style="text-align:left;padding:0">Ou o número está errado,
ou esta cópia do sistema usa outro <code>cotafrete.db</code> — cada pasta
tem o seu, e o mesmo número é outra cotação em cada uma.</p>
<p style="margin:12px 0 0"><a href="/adm#historico">ver o histórico
completo</a></p>''', classe="c8", atraso=0.05)}</div>""",
                                             base="/adm"), status_code=404)

    contagem, com_preco = _resumo_das_respostas(c)

    rota = (f'{lugar(c["cidade_origem"], c["uf_origem"]) or c["cep_origem"]}'
            f' → '
            f'{lugar(c["cidade_destino"], c["uf_destino"]) or c["cep_destino"]}')
    grade = (
        ui.cartao("Respostas das transportadoras",
                  f'<div id="respostas">{_respostas(c)}</div>',
                  ident="cartao-respostas",
                  nota=f'{com_preco} de {len(c["resultados"])} com preço',
                  classe="c12", atraso=0.05)
        + ui.cartao("Dados desta cotação", ficha_da_cotacao(c, casco=False),
                    nota="foi com estes valores que os sites cotaram",
                    classe="c8", atraso=0.10)
        # Os dois cartões baixos empilhados na mesma coluna: soltos na grade,
        # o segundo caía na linha de baixo e deixava meia tela em branco ao
        # lado da ficha, que é alta.
        + '<div class="c4 coluna">'
        + ui.cartao("Tempo de resposta",
                    f'<div id="tempos">{_tempos(c)}</div>',
                    # O aviso não é detalhe: `respondido_em` é gravado só na
                    # tentativa que deu certo, então a conta inclui a espera
                    # das retentativas anteriores. Sem dizer isso, o número
                    # culpa a transportadora pela nossa própria fila.
                    nota="retentativas incluídas", classe="", atraso=0.15)
        + ui.cartao("WhatsApp aberto pelo vendedor",
                    ui.abertas_no_whatsapp(c["whatsapp"],
                                           transportadoras.nome_de),
                    nota="aberta não é enviada", classe="", atraso=0.20)
        + "</div>")

    corpo = f"""
<div class="cabecalho" id="topo">
  <div>{ui.voltar_para("/adm#historico", "Painel")}
  <h1>Cotação #{c["id"]}</h1>
  <p class="sub">{ui.avatar(c["usuario"])} · {e(_quando(c["criado_em"]))}
  · {e(rota)} · {e(c["material"] or "sem material informado")}</p></div>
  <div class="direita" id="pilulas">{ui.pilulas(contagem)}</div>
</div>
<div id="numeros" data-cotacao="{c["id"]}" data-versao="{versao}">{_numeros_da_cotacao(c)}</div>
<div class="grade">{grade}</div>
<script>{SCRIPT_COTACAO}</script>"""
    return HTMLResponse(ui.pagina_painel(f"Cotação {c['id']}", corpo,
                                         base="/adm"))


@router.get("/cotacao/{cotacao_id}/agora")
def cotacao_agora(cotacao_id: int,
                  adm: str | None = Cookie(None, alias=COOKIE_ADM),
                  v: str = ""):
    """As respostas de UMA cotacao, para a tela mostra-las conforme chegam.

    Mesma ideia do /adm/agora, com duas diferencas:

    - a versao e exata (`versao_da_cotacao`), e nao contagem. Esta e a tela em
      que se fica olhando a resposta aparecer, e uma transportadora que sai de
      `erro` para `cotado` na retentativa nao mexe em contagem nenhuma;
    - devolve tambem a nota do cabecalho ("3 de 5 com preco"), que fica FORA
      do pedaco trocado. Sem ela, os precos novos apareceriam embaixo de um
      cabecalho dizendo o numero velho.

    Cotacao que nao existe devolve 404 SECO, sem o casco do painel: quem
    recebe isto e o JavaScript, nao uma pessoa - e o `ver_cotacao` continua
    respondendo a pagina inteira para quem chega pelo link."""
    _exigir_montado()
    if not autorizado(adm):
        return RedirectResponse("/adm/entrar", status_code=303)

    with closing(banco._conectar()) as con:
        versao = contas.versao_da_cotacao(con, cotacao_id)
        if v and v == versao:
            return Response(status_code=204)
        c = contas.cotacao(con, cotacao_id)

    if c is None:
        return Response(status_code=404)

    contagem, com_preco = _resumo_das_respostas(c)
    return JSONResponse({
        "v": versao,
        "numeros": _numeros_da_cotacao(c),
        "respostas": _respostas(c),
        "tempos": _tempos(c),
        "pilulas": ui.pilulas(contagem),
        "nota": f'{com_preco} de {len(c["resultados"])} com preço',
    })
