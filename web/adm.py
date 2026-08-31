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

from fastapi import APIRouter, Cookie, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from core.banco import Banco
from core import painel as contas
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
    return '<p class="sub">' + " · ".join(
        f'<a class="periodo{" atual" if d == dias else ""}" '
        f'href="/adm?dias={d}">{e(rotulo)}</a>'
        for d, rotulo in PERIODOS) + "</p>"


def _faixa(resumo: dict) -> str:
    """A faixa ao vivo. Fragmento SEM casco: é ela que o JavaScript troca."""
    def bloco(rotulo: str, valor: int, destaque: str = "") -> str:
        return (f'<div class="numero{destaque}"><b>{valor}</b>'
                f'<span>{e(rotulo)}</span></div>')

    return (
        '<div class="faixa">'
        + bloco("cotações hoje", resumo["cotacoes"])
        + bloco("com preço", resumo["com_preco"])
        # O número que mais importa: o vendedor ficou na mão.
        + bloco("sem nenhum preço", resumo["sem_nenhum_preco"],
                " ruim" if resumo["sem_nenhum_preco"] else "")
        + bloco("cotando agora", resumo["em_andamento"])
        + "</div>")


def _barra(fracao: float | None) -> str:
    """Barra em CSS puro. Sem biblioteca, funciona sem internet."""
    if fracao is None:
        return '<span class="sem-dado">sem dados ainda</span>'
    # Uma casa decimal: com .0f, 99,6% arredondava para "100%" numa
    # transportadora que acabou de falhar — o número mais otimista possível
    # bem em cima de quem não merecia.
    return (f'<div class="barra"><i style="width:{fracao * 100:.1f}%"></i>'
            f'</div> {fracao * 100:.1f}%')


def _saude(linhas: list[dict]) -> str:
    if not linhas:
        return ("<h2>Saúde das transportadoras</h2>"
                "<p>Nenhuma cotação no período.</p>")
    corpo = "".join(
        f'<tr><td>{e(l["transportadora"])}</td>'
        f'<td>{l["sucesso"]}</td><td>{l["recusa"]}</td>'
        f'<td>{l["falha"]}</td><td>{l["nossa"]}</td>'
        f'<td>{l["inesperado"]}</td>'
        f'<td>{_barra(l["aproveitamento"])}</td></tr>'
        for l in linhas)
    return (
        "<h2>Saúde das transportadoras</h2>"
        "<table><tr><th>transportadora</th><th>Sucessos</th>"
        "<th>Recusas</th><th>Falhas</th><th>Interrompidas</th>"
        "<th>Inesperado</th><th>aproveitamento</th></tr>"
        f"{corpo}</table>"
        '<p class="sub">Recusa é a transportadora dizendo não, com o motivo '
        "dela — não é defeito. Interrompida é o servidor tendo reiniciado no "
        "meio, e por isso fica fora do aproveitamento. Inesperado é status "
        "que core/painel.py ainda não conhece — mostrado, e não escondido, "
        'porque esconder o desconhecido foi como "(nenhuma mensagem '
        'visível)" nasceu.</p>')


def _historico(linhas: list[dict]) -> str:
    if not linhas:
        return "<h2>Histórico</h2><p>Nenhuma cotação no período.</p>"
    corpo = "".join(
        # SEM link de propósito: /cotacao/{id} é a rota do VENDEDOR — exige o
        # cookie dele e filtra por dono em banco.buscar_cotacao. Clicar aqui
        # jogava para /login ou devolvia 404 numa cotação que esta própria
        # tela acabou de listar. A rota própria do adm é Fase 2.
        f'<tr><td>#{l["id"]}</td>'
        f'<td>{e(l["criado_em"][5:16].replace("T", " "))}</td>'
        f'<td>{e(l["usuario"])}</td><td>{e(l["rota"])}</td>'
        f'<td>{e(l["material"] or "")}</td>'
        f'<td>{moeda(l["melhor_preco"])}</td>'
        f'<td>{l["contagem"].get("falha", 0)}</td></tr>'
        for l in linhas)
    return ("<h2>Histórico</h2>"
            "<table><tr><th>nº</th><th>quando</th><th>quem</th><th>rota</th>"
            "<th>material</th><th>melhor preço</th><th>falhas</th></tr>"
            f"{corpo}</table>")


@router.get("/agora", response_class=HTMLResponse)
def agora(adm: str | None = Cookie(None, alias=COOKIE_ADM)):
    """Só a faixa. Tem os mesmos dados da tela, então exige o mesmo cookie."""
    _exigir_montado()
    if not autorizado(adm):
        return RedirectResponse("/adm/entrar", status_code=303)
    with closing(banco._conectar()) as con:
        return HTMLResponse(_faixa(contas.resumo_do_dia(con)))


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
        linhas = contas.historico(con, dias=dias)

    corpo = f"""
<h1>Painel</h1>
<div id="agora">{_faixa(resumo)}</div>
{_seletor(dias)}
{_saude(saude)}
{_historico(linhas)}
<p class="sub"><a href="/adm/sair">Sair do painel</a></p>
<script>
// Troca SÓ a faixa. Recarregar a página inteira perderia a rolagem de quem
// estivesse lendo a tabela embaixo.
setInterval(async () => {{
  try {{
    const r = await fetch('/adm/agora');
    // fetch segue redirect por padrão: passadas as 12h do cookie, /adm/agora
    // redireciona para /adm/entrar e o fetch recebe 200 com a PÁGINA DE LOGIN
    // inteira — r.ok sozinho não percebe isso, e o <!doctype> inteiro ia
    // parar dentro da faixa. r.redirected denuncia que a resposta veio de
    // outro lugar.
    if (r.ok && !r.redirected) document.getElementById('agora').innerHTML = await r.text();
    else location.href = '/adm/entrar';
  }} catch (erro) {{ /* rede caiu; a próxima volta tenta de novo */ }}
}}, 10000);
</script>"""
    return HTMLResponse(pagina("Painel", corpo))
