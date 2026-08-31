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
from decimal import Decimal

from fastapi import APIRouter, Cookie, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from core.banco import Banco
from core import painel as contas
from web.layout import LOGO, e, pagina

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

router = APIRouter(prefix="/adm")


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
    return hmac.compare_digest(cookie, token_de(senha))


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
    if not hmac.compare_digest(senha, correta):
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


def _moeda(valor: Decimal | None) -> str:
    """Preço em português. None vira travessão, nunca "0,00" — zero seria um
    preço, e não ter preço é outra coisa."""
    if valor is None:
        return "—"
    return "R$ " + f"{valor:.2f}".replace(".", ",")


PERIODOS = ((1, "hoje"), (7, "7 dias"), (30, "30 dias"), (3650, "tudo"))


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
    return (f'<div class="barra"><i style="width:{fracao * 100:.0f}%"></i>'
            f'</div> {fracao * 100:.0f}%')


def _saude(linhas: list[dict]) -> str:
    if not linhas:
        return ("<h2>Saúde das transportadoras</h2>"
                "<p>Nenhuma cotação no período.</p>")
    corpo = "".join(
        f'<tr><td>{e(l["transportadora"])}</td>'
        f'<td>{l["sucesso"]}</td><td>{l["recusa"]}</td>'
        f'<td>{l["falha"]}</td><td>{l["nossa"]}</td>'
        f'<td>{_barra(l["aproveitamento"])}</td></tr>'
        for l in linhas)
    return (
        "<h2>Saúde das transportadoras</h2>"
        "<table><tr><th>transportadora</th><th>Sucessos</th>"
        "<th>Recusas</th><th>Falhas</th><th>Interrompidas</th>"
        "<th>aproveitamento</th></tr>"
        f"{corpo}</table>"
        '<p class="sub">Recusa é a transportadora dizendo não, com o motivo '
        "dela — não é defeito. Interrompida é o servidor tendo reiniciado no "
        "meio, e por isso fica fora do aproveitamento.</p>")


def _historico(linhas: list[dict]) -> str:
    if not linhas:
        return ""
    corpo = "".join(
        f'<tr><td><a href="/cotacao/{l["id"]}">#{l["id"]}</a></td>'
        f'<td>{e(l["criado_em"][5:16].replace("T", " "))}</td>'
        f'<td>{e(l["usuario"])}</td><td>{e(l["rota"])}</td>'
        f'<td>{e(l["material"] or "")}</td>'
        f'<td>{_moeda(l["melhor_preco"])}</td>'
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
    if (r.ok) document.getElementById('agora').innerHTML = await r.text();
  }} catch (erro) {{ /* rede caiu; a próxima volta tenta de novo */ }}
}}, 10000);
</script>"""
    return HTMLResponse(pagina("Painel", corpo))
