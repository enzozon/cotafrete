"""Robô do Mercado Eletrônico: preenche e SALVA a resposta. NUNCA envia.

    from mercado_eletronico.robo import salvar_cotacao
    r = salvar_cotacao(Conta.UNIAO, 23052403, itens, validade_dias=30, dry_run=True)

Fluxo por página (10 itens por página; índices recomeçam em 1):
  ler itens → plano (mapa.plano_pagina) → preencher → [dry-run: conferir e
  parar] → última página: Salvar (Acao=9); senão: próxima página (Acao=1x,
  que também grava o rascunho — autorizado pelo usuário em 23/09/2026).
Depois de salvar: reabre a cotação e confere campo a campo (regras.conferir).

As três travas de `trava.py` ficam instaladas no contexto do navegador
inteiro, antes de qualquer script do ME: clique só no Salvar, form.submit só
Acao 9/4/11-19, rede aborta todo o resto. O único confirm aceito é o
"Você verificou todas as informações digitadas?", e só durante Salvar/paginar.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Callable

from mercado_eletronico import mapa as M
from mercado_eletronico import regras as R
from mercado_eletronico import trava as T
from mercado_eletronico.lista import URL_RESPOSTA
from mercado_eletronico.regras import Conta, EntradaItem, PedidoDoComprador

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "runs" / "me"
URL_LOGIN_DESTINO = "https://www.me.com.br/supplier/inbox/pendencies/4"
TIMEOUT_MS = 60_000


class RoboRecusou(RuntimeError):
    """Algo na página não bate com o que o recon provou — parar, não chutar."""


@dataclass(frozen=True)
class ItemPagina:
    indice: int
    numero: int
    descricao: str
    quantidade: str
    campos_adicionais: str
    pedido: PedidoDoComprador


@dataclass
class ResultadoRobo:
    ok: bool = False
    salvo: bool = False
    dry_run: bool = True
    divergencias: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    prints: list[str] = field(default_factory=list)
    erro: str | None = None
    posts_liberados: int = 0
    bloqueios: list[str] = field(default_factory=list)


# ------------------------------------------------------------ leitura (JS)
# Texto de cada item = do spanItem_N até o spanItem_N+1 (ou fim do form).
JS_BLOCOS = """
() => {
  const max = parseInt((document.querySelector("[name='MaxItem']") || {}).value || '0');
  const fim = document.forms['RespCota'];
  const out = [];
  for (let n = 1; n <= max; n++) {
    const ini = document.getElementById('spanItem_' + n);
    if (!ini) continue;
    const prox = document.getElementById('spanItem_' + (n + 1));
    const r = document.createRange();
    r.setStartBefore(ini);
    // último item: até o FIM do form (inclui o texto solto dos Campos Adicionais)
    if (prox) r.setEndBefore(prox); else r.setEnd(fim, fim.childNodes.length);
    out.push({indice: n, numero: ini.textContent.trim(), texto: r.toString()});
  }
  return out;
}
"""

JS_VALORES = """
(nomes) => {
  const out = {};
  for (const nome of nomes) {
    const el = document.querySelector(`[name='${nome}'], [name='${nome} ']`);
    if (el) out[nome] = el.type === 'checkbox' ? String(el.checked) : (el.value || '');
  }
  return out;
}
"""

JS_DISPARAR = """
e => {
  e.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: '0'}));
  e.dispatchEvent(new Event('change', {bubbles: true}));
  e.dispatchEvent(new Event('blur'));
  try { if (e.onblur) e.onblur(); } catch (err) {}
}
"""

JS_IE_UNICA = """
() => {
  const s = document.querySelector("select[name='InscricaoEstadual']");
  if (!s) return 'sem campo';
  const opcoes = [...s.options].filter(o => o.value);
  if (opcoes.length !== 1) return 'IE ambígua: ' + opcoes.length + ' opções';
  s.value = opcoes[0].value;
  s.dispatchEvent(new Event('change', {bubbles: true}));
  return '';
}
"""

_RE_QTD = re.compile(r"Quantidade:\s*([\d.,]+)")
_RE_ADIC = re.compile(r"Campos Adicionais:\s*(.*?)(?:Anexo do Produto|$)", re.S)


def ler_bloco(indice: int, numero: str, texto: str) -> ItemPagina:
    """Texto cru do item (da página) → ItemPagina. Puro, testável."""
    num = int(re.sub(r"\D", "", numero) or 0)
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    descricao = linhas[1] if len(linhas) > 1 else ""
    qtd = m.group(1) if (m := _RE_QTD.search(texto)) else ""
    adic = " ".join(m.group(1).split()) if (m := _RE_ADIC.search(texto)) else ""
    return ItemPagina(indice, num, descricao, qtd, adic, R.ler_campos_adicionais(adic))


def ler_itens(page) -> list[ItemPagina]:
    return [ler_bloco(b["indice"], b["numero"], b["texto"]) for b in page.evaluate(JS_BLOCOS)]


def ler_valores(page, nomes: list[str]) -> dict[str, str]:
    return page.evaluate(JS_VALORES, list(nomes))


# -------------------------------------------------------------- escrita
# "Deseja Recusar o Item?" é um botão de JavaScript que só alterna o estado
# do item na página (HabilitarRecusa: limpa e trava os campos, mostra a
# justificativa). Nenhuma requisição sai dali. O robô chama a MESMA função
# em vez de clicar num botão com "Recusar" no texto, e só quando o estado
# atual é o oposto do desejado — chamar duas vezes desfaz.
JS_ESTADO_RECUSA = """(i) => {
  const b = document.getElementById('btnNaoResponder_' + i);
  return b ? b.value === 'Responder item' : null;
}"""


def ajustar_recusas(page, plano: M.PlanoPagina) -> None:
    """Deixa cada item recusado ou não conforme o plano, ANTES de digitar:
    campo de item recusado fica readonly, e fill em readonly quebra."""
    for indice in sorted(set(plano.recusar) | set(plano.marcar)):
        recusado = page.evaluate(JS_ESTADO_RECUSA, indice)
        if recusado is None:  # sem o botão: o item não tem como estar recusado
            if indice in plano.recusar:
                raise RoboRecusou(f"item {indice} sem o botão de recusa do ME")
            continue
        if recusado != (indice in plano.recusar):
            page.evaluate("(i) => HabilitarRecusa(String(i))", indice)


def preencher(page, plano: M.PlanoPagina) -> None:
    erro_ie = page.evaluate(JS_IE_UNICA)
    if erro_ie and erro_ie != "sem campo":
        raise RoboRecusou(erro_ie)
    ajustar_recusas(page, plano)
    for nome, valor in plano.campos.items():
        loc = page.locator(f"[name='{nome}'], [name='{nome} ']").first
        if loc.count() == 0:
            raise RoboRecusou(f"campo {nome} não existe na página")
        if loc.evaluate("e => e.tagName") == "SELECT":
            loc.select_option(valor)
        else:
            loc.fill(valor)  # fill direto: tecla a tecla passa pela máscara do ME
        loc.evaluate(JS_DISPARAR)
    for indice in plano.marcar:
        page.locator(f"#chkItem_{indice}").check()


def _clicar_salvar(page) -> None:
    botao = page.locator("#MEComponentManager_MEButton_5")
    titulo = botao.get_attribute("title") or botao.get_attribute("data-original-title") or ""
    if not T.botao_e_salvar(titulo, botao.inner_text()):
        raise RoboRecusou(f"botão não é o Salvar esperado (title={titulo!r})")
    botao.click()


def _clicar_pagina(page, pagina: int) -> None:
    acao = str(10 + pagina)
    if acao not in T.ACOES_PAGINAR:
        raise RoboRecusou(f"página {pagina} fora do que a trava libera")
    page.locator(f"a[href*='Envia({acao})']").first.click()


def paginas(page) -> int:
    acoes = {int(a) for a in re.findall(r"Envia\((1\d)\)", page.content())}
    return max([a - 10 for a in acoes] or [1])


# -------------------------------------------------------------- sessão
class Sessao:
    """Contexto do navegador com as três travas. Use como `with Sessao(...) as s:`."""

    def __init__(self, conta: Conta, headless: bool = True, pasta: Path | None = None,
                 seguir: Callable | None = None, browser=None, timeout_ms: int = TIMEOUT_MS):
        self.conta, self.headless = conta, headless
        self.pasta = (pasta or PASTA) / conta.value
        self._seguir = seguir  # testes: responder sem ir à rede
        self._browser_externo = browser
        self.timeout_ms = timeout_ms
        self.logado = True
        self.acao_em_curso = False
        self.liberados = 0
        self.bloqueios: list[str] = []

    # --- travas
    def _rota(self, route, request) -> None:
        motivo = T.motivo_bloqueio(request.method, request.url, request.post_data, self.logado)
        if motivo:
            self.bloqueios.append(f"{request.method} {request.url[:120]}: {motivo}")
            return route.abort()
        if request.method.upper() == "POST" and T.acao_do_corpo(request.post_data):
            self.liberados += 1
        return self._seguir(route, request) if self._seguir else route.continue_()

    def _dialogo(self, d) -> None:
        aceita = d.type in ("alert", "beforeunload") or (
            d.type == "confirm" and T.confirm_aceito(d.message, self.acao_em_curso))
        d.accept() if aceita else d.dismiss()

    # --- ciclo de vida
    def __enter__(self) -> "Sessao":
        from playwright.sync_api import sync_playwright

        self.pasta.mkdir(parents=True, exist_ok=True)
        estado = self.pasta / "estado.json"
        if self._browser_externo is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
        else:
            self._pw, self._browser = None, self._browser_externo
        self.ctx = self._browser.new_context(
            locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width": 1500, "height": 950},
            storage_state=str(estado) if estado.exists() else None)
        self.ctx.add_init_script(T.JS_TRAVA_FORM)
        self.ctx.route("**/*", self._rota)
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        self.page.on("dialog", self._dialogo)
        return self

    def __exit__(self, *exc) -> None:
        self.ctx.close()
        if self._pw:
            self._browser.close()
            self._pw.stop()

    def print(self, nome: str) -> str:
        caminho = self.pasta / f"{time.strftime('%Y%m%d-%H%M%S')}_{nome}.png"
        self.page.screenshot(path=str(caminho), full_page=True)
        return str(caminho)

    # --- ME
    def login(self) -> None:
        pref = f"ME_{self.conta.name}"
        login, senha = os.environ.get(f"{pref}_LOGIN"), os.environ.get(f"{pref}_SENHA")
        if not login or not senha:
            raise RoboRecusou(f"Faltam {pref}_LOGIN / {pref}_SENHA no .env.")
        self.logado = False
        try:
            if "login" not in self.page.url.lower():
                self.page.goto(URL_LOGIN_DESTINO, wait_until="domcontentloaded")
            self.page.fill("#LoginName", login)
            self.page.fill("#RAWSenha", senha)
            self.page.click("#SubmitAuth")
            self.page.wait_for_load_state("networkidle")
        finally:
            self.logado = True
        if "login" in self.page.url.lower():
            raise RoboRecusou("ME recusou o login — conferir usuário/senha no .env.")
        self.ctx.storage_state(path=str(self.pasta / "estado.json"))

    def abrir(self, numero: int) -> None:
        self.page.goto(URL_RESPOSTA.format(n=numero), wait_until="networkidle")
        if "login" in self.page.url.lower():
            self.login()
            self.page.goto(URL_RESPOSTA.format(n=numero), wait_until="networkidle")
        if not self.page.locator("form[name='RespCota']").count():
            raise RoboRecusou(f"cotação {numero} não abriu o formulário de resposta")

    def acao(self, clicar: Callable[[], None]) -> int:
        """Clica em Salvar/página e espera o POST voltar. Devolve POSTs liberados."""
        antes = self.liberados
        self.acao_em_curso = True
        try:
            with self.page.expect_navigation(wait_until="networkidle", timeout=self.timeout_ms):
                clicar()
        finally:
            self.acao_em_curso = False
        return self.liberados - antes


# ------------------------------------------------------------ orquestração
def _itens_por_indice(itens_pag: list[ItemPagina], entradas: dict[int, EntradaItem]):
    """Casa as entradas do usuário (por número de item) com os índices da página."""
    plano_itens: dict[int, EntradaItem | None] = {}
    for ip in itens_pag:
        e = entradas.pop(ip.numero, None)
        if e is not None and e.pedido == PedidoDoComprador():
            e = replace(e, pedido=ip.pedido)  # UF/origem/remessa vêm da página
        plano_itens[ip.indice] = e
    return plano_itens


def _conferir(page, plano: M.PlanoPagina, so_respondidos: bool) -> list[str]:
    esperado = dict(plano.campos)
    if so_respondidos:  # o ME devolve BaseCalculo=100,00 nos vazios ao recarregar
        esperado = {k: v for k, v in esperado.items() if not (k.startswith("BaseCalculo") and v == "")}
    return R.conferir(esperado, ler_valores(page, list(esperado)))


def salvar_cotacao(conta: Conta, numero: int, itens: list[EntradaItem], validade_dias: int,
                   *, dry_run: bool = True, hoje: date | None = None, obs_geral: str = "",
                   sessao: Sessao | None = None, headless: bool = True) -> ResultadoRobo:
    """Preenche a cotação e (se não for dry-run) SALVA. Nunca envia."""
    hoje = hoje or date.today()
    res = ResultadoRobo(dry_run=dry_run)
    dono = sessao is None
    s = sessao or Sessao(conta, headless=headless)
    if dono:
        s.__enter__()
    try:
        _executar(s, res, conta, numero, {i.numero: i for i in itens},
                  validade_dias, hoje, obs_geral, dry_run)
    except (RoboRecusou, M.PlanoInvalido, R.RegraDesconhecida) as exc:
        res.erro = str(exc)
    except Exception as exc:  # navegador/ME: registra com print para quem for olhar
        res.erro = f"{type(exc).__name__}: {exc}"
        try:
            res.prints.append(s.print("erro"))
        except Exception:
            pass
    finally:
        res.posts_liberados, res.bloqueios = s.liberados, list(s.bloqueios)
        if dono:
            s.__exit__(None, None, None)
    res.ok = res.erro is None and not res.divergencias
    return res


def _executar(s: Sessao, res: ResultadoRobo, conta: Conta, numero: int,
              entradas: dict[int, EntradaItem], validade: int, hoje: date,
              obs: str, dry_run: bool) -> None:
    s.abrir(numero)
    total = paginas(s.page)
    planos: list[M.PlanoPagina] = []
    for pagina in range(1, total + 1):
        plano = M.plano_pagina(conta, _itens_por_indice(ler_itens(s.page), entradas),
                               validade, hoje, obs)
        res.avisos += plano.avisos
        preencher(s.page, plano)
        planos.append(plano)
        if dry_run:
            res.divergencias += _conferir(s.page, plano, so_respondidos=False)
            res.prints.append(s.print(f"{numero}_p{pagina}_dryrun"))
            if total > 1:
                res.avisos.append(f"dry-run parou na página 1 de {total}: ir à próxima grava o rascunho.")
            break
        if pagina < total and s.acao(lambda p=pagina: _clicar_pagina(s.page, p + 1)) != 1:
            raise RoboRecusou(f"passagem para a página {pagina + 1} não gravou")
    if entradas:
        res.avisos.append(f"itens não encontrados na cotação: {sorted(entradas)}")
    if dry_run:
        return
    if not any(p.marcar for p in planos):
        raise RoboRecusou("nenhum item com preço — o ME não salva")
    if s.acao(lambda: _clicar_salvar(s.page)) != 1:
        raise RoboRecusou("o Salvar não gerou o POST esperado — nada garantido no ME")
    res.salvo = True
    res.prints.append(s.print(f"{numero}_salvo"))
    # conferência: reabre e relê cada página (ir à próxima regrava o que já está lá)
    s.abrir(numero)
    for pagina, plano in enumerate(planos, start=1):
        res.divergencias += [f"p{pagina} {d}" for d in _conferir(s.page, plano, so_respondidos=True)]
        if pagina < len(planos):
            s.acao(lambda p=pagina: _clicar_pagina(s.page, p + 1))
