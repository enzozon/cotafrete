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
from mercado_eletronico import formulario as F
from mercado_eletronico import pagina as P
from mercado_eletronico import logins as L
from mercado_eletronico.regras import Conta, EntradaItem, PedidoDoComprador

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "runs" / "me"
URL_LOGIN_DESTINO = "https://www.me.com.br/supplier/inbox/pendencies/4"
URL_PELA_LISTA = "https://www.me.com.br/FornShowCotacao.asp?Cot={n}&SuperCleanPage=true"
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
    unidade: str = ""


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
_RE_UNIDADE = re.compile(r"Unidade:\s*(\S+)")
_RE_LOCAL = re.compile(r"Local de Entrega:([^\n]*)")


def ler_bloco(indice: int, numero: str, texto: str) -> ItemPagina:
    """Texto cru do item (da página) → ItemPagina. Puro, testável."""
    num = int(re.sub(r"\D", "", numero) or 0)
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    descricao = linhas[1] if len(linhas) > 1 else ""
    qtd = m.group(1) if (m := _RE_QTD.search(texto)) else ""
    adic = " ".join(m.group(1).split()) if (m := _RE_ADIC.search(texto)) else ""
    pedido = R.ler_campos_adicionais(adic)
    if pedido.uf_destino is None and (m := _RE_LOCAL.search(texto)):
        # Sem Campos Adicionais (EDP): a UF sai do "Local de Entrega", como na tela.
        if uf := P._RE_UF_DO_LOCAL.search(m.group(1)):
            pedido = replace(pedido, uf_destino=uf.group(1))
    unidade = m.group(1) if (m := _RE_UNIDADE.search(texto)) else ""
    return ItemPagina(indice, num, descricao, qtd, adic, pedido, unidade)


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
    for indice in sorted(set(plano.recusar) | set(plano.marcar) | set(plano.limpar)):
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
    # Clique NO checkbox, e não na posição dele na tela: com a página rolada,
    # o cabeçalho fixo do ME fica por cima e o clique caía nele (Alpek,
    # 28/09/2026). É o mesmo click, com os mesmos handlers do ME.
    for indice in plano.marcar:
        page.locator(f"#chkItem_{indice}").evaluate("e => { if (!e.checked) e.click(); }")
    for indice in plano.limpar:
        page.locator(f"#chkItem_{indice}").evaluate("e => { if (e.checked) e.click(); }")


def _clicar_salvar(page) -> None:
    # Pelo título e texto EXATOS, não pela posição: na Alpek (28/09/2026) dois
    # botões a mais no alto empurraram o Salvar de _5 para _7 — e o _5 lá é
    # "Exportar / Importar". Tem de haver UM só; o Confirmar ("...enviar ao
    # comprador") nunca casa com botao_e_salvar.
    salvar = [b for b in page.locator("[id^='MEComponentManager_MEButton_']").all()
              if T.botao_e_salvar(b.get_attribute("title") or b.get_attribute("data-original-title")
                                  or "", b.inner_text())]
    if len(salvar) != 1:
        raise RoboRecusou(f"esperava UM botão Salvar na página, achei {len(salvar)}")
    salvar[0].click()
    if _dispensar_marketplace(page):
        salvar[0].click()
        if _dispensar_marketplace(page):
            # Voltou: este comprador só aceita resposta de quem aderiu.
            raise RoboRecusou(MARKETPLACE)


MARKETPLACE = ("o ME só deixa responder este comprador depois da adesão ao Marketplace Privado "
               "(o ME oferece o plano grátis). Aderir é decisão da empresa — pelo site do ME; "
               "depois disso o robô salva normalmente. Nada foi gravado.")


def _dispensar_marketplace(page) -> bool:
    """A janela "Adesão ao Marketplace Privado!" que o ME abre no Salvar de
    alguns compradores (Alpek, 28/09/2026). SÓ "Ver depois" — fecha sem aderir.
    "Avançar" (aderir) é decisão da empresa e o robô nunca clica."""
    titulo = page.get_by_text("Adesão ao Marketplace Privado", exact=False)
    try:
        titulo.first.wait_for(state="visible", timeout=3_000)
    except Exception:
        return False
    ver_depois = page.get_by_role("button", name="Ver depois", exact=True).locator("visible=true")
    if ver_depois.count() != 1:
        raise RoboRecusou("o ME abriu a janela do Marketplace Privado sem o \"Ver depois\" — parei")
    ver_depois.click()
    page.wait_for_timeout(500)
    return True


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

    def __init__(self, conta: "Conta | L.Login | str", headless: bool = True,
                 pasta: Path | None = None, seguir: Callable | None = None, browser=None,
                 timeout_ms: int = TIMEOUT_MS):
        # `conta` é o LOGIN (onde entrar); `self.conta` fica a EMPRESA (impostos).
        self.login_me = L.de(conta)
        self.conta, self.headless = self.login_me.empresa, headless
        self.pasta = (pasta or PASTA) / self.login_me.chave
        self._seguir = seguir  # testes: responder sem ir à rede
        self._browser_externo = browser
        self.timeout_ms = timeout_ms
        self.logado = True
        self.acao_em_curso = False
        self.liberados = 0
        self.bloqueios: list[str] = []
        # Arquivos que a trava deixa EXCLUIR agora: só os que o robô subiu, e
        # só durante excluir_anexo (trava.motivo_anexo).
        self.excluiveis: set[str] = set()

    # --- travas
    def _rota(self, route, request) -> None:
        # Corpo em bytes → texto sem nunca falhar: o upload de anexo é
        # multipart com o PDF dentro, que não é UTF-8.
        buffer = request.post_data_buffer
        corpo = buffer.decode("latin-1") if buffer else None
        motivo = T.motivo_bloqueio(request.method, request.url, corpo, self.logado,
                                   frozenset(self.excluiveis))
        if motivo:
            self.bloqueios.append(f"{request.method} {request.url[:120]}: {motivo}")
            return route.abort()
        if request.method.upper() == "POST" and T.acao_do_corpo(corpo):
            self.liberados += 1
        return self._seguir(route, request) if self._seguir else route.continue_()

    def _dialogo(self, d) -> None:
        aceita = d.type in ("alert", "beforeunload") or (
            d.type == "confirm" and T.confirm_aceito(d.message, self.acao_em_curso))
        d.accept() if aceita else d.dismiss()

    # --- ciclo de vida
    # O Playwright síncrono deixa um laço asyncio "rodando" na thread enquanto
    # não recebe stop(). Se a sessão falhar no meio da abertura (navegador que
    # não sobe, estado.json estragado) ou do fechamento (navegador que caiu),
    # e o stop() não rodar, TODA sessão seguinte na mesma thread morre com
    # "It looks like you are using Playwright Sync API inside the asyncio
    # loop". Foi o que aconteceu com o vigia do ME em 28/09/2026: 91 leituras
    # seguidas falhando em cada conta, de madrugada, sem ninguém mexer. Por
    # isso abrir e fechar arrumam a própria bagunça, passo a passo.
    def __enter__(self) -> "Sessao":
        from playwright.sync_api import sync_playwright

        self.pasta.mkdir(parents=True, exist_ok=True)
        estado = self.pasta / "estado.json"
        self._pw = self._browser = self.ctx = None
        try:
            if self._browser_externo is None:
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(headless=self.headless)
            else:
                self._browser = self._browser_externo
            self.ctx = self._abrir_contexto(estado)
            self.ctx.add_init_script(T.JS_TRAVA_FORM)
            self.ctx.route("**/*", self._rota)
            self.page = self.ctx.new_page()
            self.page.set_default_timeout(self.timeout_ms)
            self.page.on("dialog", self._dialogo)
        except BaseException:
            self._fechar()
            raise
        return self

    def _abrir_contexto(self, estado: Path):
        opcoes = dict(locale="pt-BR", timezone_id="America/Sao_Paulo",
                      viewport={"width": 1500, "height": 950})
        if estado.exists():
            try:
                return self._browser.new_context(storage_state=str(estado), **opcoes)
            except Exception:
                # estado.json estragado (gravação cortada no meio): sem ele a
                # sessão só faz login de novo — melhor do que parar para sempre.
                estado.unlink(missing_ok=True)
        return self._browser.new_context(**opcoes)

    def _fechar(self) -> None:
        """Fecha o que foi aberto, na ordem, e o stop() do Playwright SEMPRE
        roda — mesmo com o navegador já morto."""
        for passo in (lambda: self.ctx and self.ctx.close(),
                      lambda: self._pw and self._browser and self._browser.close(),
                      lambda: self._pw and self._pw.stop()):
            try:
                passo()
            except Exception:
                pass
        self._pw = self._browser = self.ctx = None

    def __exit__(self, *exc) -> None:
        self._fechar()

    def print(self, nome: str) -> str:
        caminho = self.pasta / f"{time.strftime('%Y%m%d-%H%M%S')}_{nome}.png"
        self.page.screenshot(path=str(caminho), full_page=True)
        return str(caminho)

    # --- ME
    def login(self) -> None:
        pref = self.login_me.prefixo
        cred = self.login_me.credenciais()
        if not cred:
            raise RoboRecusou(f"Faltam {pref}_LOGIN / {pref}_SENHA no .env.")
        login, senha = cred
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
        # Espera o FORMULÁRIO, não a rede parada: na página da Alpek o chat
        # mantém a rede ocupada e "networkidle" nunca chegava (28/09/2026).
        self.page.goto(URL_RESPOSTA.format(n=numero), wait_until="domcontentloaded")
        if "login" in self.page.url.lower():
            self.login()
            self.page.goto(URL_RESPOSTA.format(n=numero), wait_until="domcontentloaded")
        # Segunda tentativa pelo link da LISTA de Oportunidades (FornShowCotacao,
        # que redireciona para o formulário). 29/09/2026: no login EDP e WEG, a
        # 23023842 pelo link direto caía em "Cotações Recebidas" — o ME só
        # abre direto depois da primeira abertura pela lista (que marca "Lida
        # em", como quando um vendedor abre). Também cobre a página lenta.
        for tentativa in (1, 2):
            try:
                self.page.wait_for_selector("form[name='RespCota']", state="attached",
                                            timeout=self.timeout_ms)
                self.page.wait_for_load_state("load")
                return
            except Exception:
                if tentativa == 2:
                    raise RoboRecusou(f"cotação {numero} não abriu o formulário de resposta") from None
                self.page.goto(URL_PELA_LISTA.format(n=numero), wait_until="domcontentloaded")

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


def salvar_cotacao(conta: "Conta | L.Login | str", numero: int, itens: list[EntradaItem], validade_dias: int,
                   *, dry_run: bool = True, hoje: date | None = None, obs_geral: str = "",
                   sessao: Sessao | None = None, headless: bool = True,
                   frete: str = "FOB", anexos: dict[str, Path] | None = None) -> ResultadoRobo:
    """Preenche a cotação e (se não for dry-run) SALVA. Nunca envia.
    `frete`: CIF ou FOB, de `regras.tipo_frete`."""
    hoje = hoje or date.today()
    res = ResultadoRobo(dry_run=dry_run)
    dono = sessao is None
    s = sessao or Sessao(conta, headless=headless)
    if dono:
        s.__enter__()
    try:
        _executar(s, res, L.de(conta).empresa, numero, {i.numero: i for i in itens},
                  validade_dias, hoje, obs_geral, dry_run, frete, anexos)
    except (RoboRecusou, M.PlanoInvalido, R.RegraDesconhecida, F.FormularioDesconhecido) as exc:
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


def anexar(s: Sessao, anexo: "F.Anexo", arquivo: Path) -> None:
    """Sobe UM arquivo na janela de anexo do ME e confere que ele aparece na
    lista. Pela mesma sessão, com as mesmas travas: o único POST que passa ali
    é o do "Enviar" do arquivo (trava.motivo_anexo)."""
    if not anexo.url:
        raise RoboRecusou(f"{anexo.nome}: a página não trouxe a janela de anexo")
    pg = s.ctx.new_page()
    pg.set_default_timeout(s.timeout_ms)
    try:
        pg.goto("https://www.me.com.br/" + anexo.url, wait_until="domcontentloaded")
        pg.locator("#fuArquivo").set_input_files(str(arquivo))
        # O <button>, não o <span> de mesmo final de id que o ME põe dentro dele.
        enviar = pg.locator("button[id$='formUpload_btnEnviar']")
        if enviar.count() != 1 or enviar.inner_text().strip() != "Enviar":
            raise RoboRecusou(f"{anexo.nome}: botão de enviar arquivo não é o esperado")
        with pg.expect_navigation(wait_until="domcontentloaded"):
            enviar.click()
        if arquivo.stem not in pg.inner_text("body"):
            raise RoboRecusou(f"{anexo.nome}: o ME não listou {arquivo.name} depois do envio")
    finally:
        pg.close()


class UltimoAnexo(RoboRecusou):
    """O ME não deixa excluir o último anexo de um tipo obrigatório."""


# Regra do ME (29/09/2026, Oitamérica 23079560): depois de salva com o anexo
# obrigatório, a cotação não fica sem nenhum — só dá para TROCAR o arquivo.
MSG_ULTIMO_ANEXO = "É preciso adicionar outro anexo para permitir a exclusão"
PREFIXO_TESTE = "TESTE_ROBO_"


def _janela_anexo(s: Sessao, anexo: "F.Anexo"):
    if not anexo.url:
        raise RoboRecusou(f"{anexo.nome}: a página não trouxe a janela de anexo")
    pg = s.ctx.new_page()
    pg.set_default_timeout(s.timeout_ms)
    pg.goto("https://www.me.com.br/" + anexo.url, wait_until="domcontentloaded")
    return pg


def _linhas_do_arquivo(pg, nome: str):
    exato = re.compile(r"^\s*" + re.escape(nome) + r"\s*$")
    return pg.locator("tbody tr").filter(has=pg.locator("td", has_text=exato))


def nomes_no_me(s: Sessao, anexo: "F.Anexo") -> list[str]:
    """Os nomes dos arquivos que o ME lista neste anexo (só leitura)."""
    pg = _janela_anexo(s, anexo)
    try:
        return pg.evaluate("""() => [...document.querySelectorAll("tbody[id^='tBody_jsTable'] tr")]
            .map(tr => tr.cells.length > 1 ? tr.cells[1].innerText.trim() : '').filter(Boolean)""")
    finally:
        pg.close()


def excluir_anexo(s: Sessao, anexo: "F.Anexo", nome: str) -> bool:
    """Exclui do ME UM arquivo que o robô subiu, pelo nome EXATO. False = ele não
    está lá. Desmarca as linhas antes (a janela abre com todas marcadas) e a
    trava só deixa passar se o pedido citar apenas esse arquivo. UltimoAnexo se
    o ME recusar por ser o último do tipo."""
    pg = _janela_anexo(s, anexo)
    s.excluiveis = {nome}
    try:
        linhas = _linhas_do_arquivo(pg, nome)
        if linhas.count() == 0:
            return False
        if linhas.count() != 1:
            raise RoboRecusou(f"{anexo.nome}: {linhas.count()} arquivos chamados {nome} — parei")
        pg.evaluate("() => { if (typeof UnSelectAll === 'function') UnSelectAll(); }")
        with pg.expect_navigation(wait_until="domcontentloaded"):
            linhas.first.locator("img[title='Excluir']").click()
        if _linhas_do_arquivo(pg, nome).count():
            if MSG_ULTIMO_ANEXO in pg.inner_text("body"):
                raise UltimoAnexo(f"{anexo.nome}: o ME não deixa excluir o último anexo "
                                  f"obrigatório ({nome}) — só trocar por outro arquivo")
            raise RoboRecusou(f"{anexo.nome}: {nome} continua no ME depois de excluir")
        return True
    finally:
        s.excluiveis = set()
        pg.close()


def _excluir_anexos_do_robo(s: Sessao, res: ResultadoRobo, nomes: set[str],
                            dry_run: bool) -> bool:
    """No "Limpar no ME": tira os anexos que o robô subiu nesta cotação. O
    último de um tipo obrigatório o ME não deixa tirar: vira aviso, e a
    limpeza do resto segue."""
    excluiu = False
    for a in F.anexos_obrigatorios(s.page):
        if not a.qtd:
            continue
        for nome in sorted(nomes):
            if dry_run:
                res.avisos.append(f"no Limpar, vai excluir {nome} de {a.nome} (se estiver lá)")
                continue
            try:
                if excluir_anexo(s, a, nome):
                    res.avisos.append(f"anexo excluído do ME: {nome} ({a.nome})")
                    excluiu = True
            except UltimoAnexo as exc:
                res.avisos.append(str(exc))
    return excluiu


def _garantir_anexos(s: Sessao, res: ResultadoRobo, numero: int,
                     anexos: dict[str, Path], dry_run: bool) -> None:
    """Cada anexo obrigatório ("*") com o arquivo que o vendedor deu no CotaFrete
    (por TipoAnexo): sobe se ESSE arquivo ainda não está no ME. Depois, os
    arquivos de teste do robô (TESTE_ROBO_*) que sobraram ali saem — com a
    proposta de verdade lá, já não são o último. Anexo vazio no ME e sem
    arquivo aqui: para — o ME não salvaria."""
    obrigatorios = F.anexos_obrigatorios(s.page)
    sem = [a.nome for a in obrigatorios if a.qtd == 0 and a.tipo not in anexos]
    if sem:
        msg = (f"o comprador exige anexo para salvar ({', '.join(sem)}): suba o arquivo "
               "na tela da cotação e mande o robô de novo")
        if not dry_run:
            raise RoboRecusou(msg)
        res.avisos.append(msg)
    mexeu = False
    for a in obrigatorios:
        if a.tipo not in anexos:
            continue
        arq = Path(anexos[a.tipo])
        no_me = nomes_no_me(s, a) if a.qtd else []
        if arq.name not in no_me:
            if dry_run:
                res.avisos.append(f"no Salvar, vai anexar {arq.name} em {a.nome}")
            else:
                if not arq.is_file():
                    raise RoboRecusou(f"{a.nome}: o arquivo {arq.name} sumiu do servidor — suba de novo")
                anexar(s, a, arq)
                res.avisos.append(f"anexado no ME: {arq.name} em {a.nome}")
                mexeu = True
        for sobra in (n for n in no_me if n.startswith(PREFIXO_TESTE) and n != arq.name):
            if dry_run:
                res.avisos.append(f"no Salvar, vai excluir o arquivo de teste {sobra} de {a.nome}")
            elif excluir_anexo(s, a, sobra):
                res.avisos.append(f"arquivo de teste excluído do ME: {sobra} ({a.nome})")
                mexeu = True
    if mexeu:
        s.abrir(numero)
        if ainda := F.anexos_faltando(s.page):
            raise RoboRecusou(f"anexo enviado mas o ME ainda mostra vazio: {', '.join(ainda)}")


def _executar(s: Sessao, res: ResultadoRobo, conta: Conta, numero: int,
              entradas: dict[int, EntradaItem], validade: int, hoje: date,
              obs: str, dry_run: bool, frete: str = "FOB",
              anexos: dict[str, Path] | None = None) -> None:
    s.abrir(numero)
    _garantir_anexos(s, res, numero, anexos or {}, dry_run)
    total = paginas(s.page)
    planos: list[M.PlanoPagina] = []
    for pagina in range(1, total + 1):
        lidos = ler_itens(s.page)
        por_indice = _itens_por_indice(lidos, entradas)
        plano = M.plano_pagina(conta, por_indice, validade, hoje, obs, frete)
        # O formulário DESTE comprador (formulario.py): nomes, códigos e extras.
        plano = replace(plano, campos=F.adaptar(
            plano.campos, plano.marcar, F.ler(s.page), empresa=conta, itens=por_indice,
            unidades={i.indice: i.unidade for i in lidos}))
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
    from playwright.sync_api import TimeoutError as Esgotou
    try:
        gravou = s.acao(lambda: _clicar_salvar(s.page))
    except Esgotou:
        res.prints.append(s.print(f"{numero}_salvar_recusado"))
        raise RoboRecusou("o ME não aceitou o Salvar (algum campo obrigatório da página ficou "
                          "vazio ou inválido) — nada foi gravado; veja o print") from None
    if gravou != 1:
        raise RoboRecusou("o Salvar não gerou o POST esperado — nada garantido no ME")
    res.salvo = True
    res.prints.append(s.print(f"{numero}_salvo"))
    # conferência: reabre e relê cada página (ir à próxima regrava o que já está lá)
    s.abrir(numero)
    for pagina, plano in enumerate(planos, start=1):
        res.divergencias += [f"p{pagina} {d}" for d in _conferir(s.page, plano, so_respondidos=True)]
        if pagina < len(planos):
            s.acao(lambda p=pagina: _clicar_pagina(s.page, p + 1))


# ------------------------------------------------------------------ limpeza
def _conferir_limpeza(page, plano: M.PlanoPagina, recarregada: bool) -> list[str]:
    """Os campos do plano + cada item sem marca e sem recusa. Na página
    recarregada o ME devolve BaseCalculo=100,00 — é o normal, não conta — e
    o Valor ST que a máscara pôs em "0,00" volta gravado vazio."""
    if recarregada:
        plano = replace(plano, campos={
            k: ("" if k.startswith("ValorSubstituicaoTributaria") else v)
            for k, v in plano.campos.items()})
    diverg = _conferir(page, plano, so_respondidos=recarregada)
    extras = {f"chkItem_{i}": "false" for i in plano.limpar}
    extras |= {f"txtJustificativaRecusa_{i}": "" for i in plano.limpar}
    lido = ler_valores(page, list(extras))  # item sem o botão de recusa não tem justificativa
    diverg += R.conferir({k: v for k, v in extras.items() if k in lido}, lido)
    diverg += [f"item {i} continua recusado" for i in plano.limpar
               if page.evaluate(JS_ESTADO_RECUSA, i)]
    return diverg


def limpar_cotacao(conta: "Conta | L.Login | str", numero: int, *, dry_run: bool = True,
                   sessao: Sessao | None = None, headless: bool = True,
                   anexos: "list[str] | tuple[str, ...]" = ()) -> ResultadoRobo:
    """Apaga do RASCUNHO do ME tudo o que o robô escreve: preços, impostos,
    NCM, prazo, marca, obs, recusas de item e a obs geral. Os itens voltam a
    ficar como chegaram; do cabeçalho ficam só os campos fixos da empresa que
    o ME exige para salvar (mapa.CABECALHO_LIMPO). É um Salvar (Acao=9) —
    nunca envia.

    ME real (24/09/2026, UNIÃO 23052403): o Salvar sem nenhum item marcado
    só mostra "Para salvar previamente é necessario…" e grava mesmo assim —
    o JS do ME avisa mas não para.

    `anexos`: nomes dos arquivos que o robô subiu nesta cotação — saem também
    (29/09/2026). Anexo de outra pessoa, nunca (trava)."""
    res = ResultadoRobo(dry_run=dry_run)
    dono = sessao is None
    s = sessao or Sessao(conta, headless=headless)
    if dono:
        s.__enter__()
    try:
        s.abrir(numero)
        if anexos and _excluir_anexos_do_robo(s, res, set(anexos), dry_run):
            s.abrir(numero)
        total = paginas(s.page)
        planos: list[M.PlanoPagina] = []
        for pagina in range(1, total + 1):
            plano = M.plano_limpeza([i.indice for i in ler_itens(s.page)])
            plano = replace(plano, campos=F.adaptar(plano.campos, [], F.ler(s.page),
                                                    empresa=s.conta, limpeza=True))
            preencher(s.page, plano)
            planos.append(plano)
            if dry_run:
                res.divergencias += _conferir_limpeza(s.page, plano, recarregada=False)
                res.prints.append(s.print(f"{numero}_p{pagina}_limpeza_dryrun"))
                if total > 1:
                    res.avisos.append(f"teste parou na página 1 de {total}: ir à próxima grava o rascunho.")
                break
            if pagina < total and s.acao(lambda p=pagina: _clicar_pagina(s.page, p + 1)) != 1:
                raise RoboRecusou(f"passagem para a página {pagina + 1} não gravou")
        if not dry_run:
            if s.acao(lambda: _clicar_salvar(s.page)) != 1:
                raise RoboRecusou("o Salvar não gerou o POST esperado — nada garantido no ME")
            res.salvo = True
            res.prints.append(s.print(f"{numero}_limpa"))
            s.abrir(numero)
            for pagina, plano in enumerate(planos, start=1):
                res.divergencias += [f"p{pagina} {d}"
                                     for d in _conferir_limpeza(s.page, plano, recarregada=True)]
                if pagina < len(planos):
                    s.acao(lambda p=pagina: _clicar_pagina(s.page, p + 1))
    except (RoboRecusou, F.FormularioDesconhecido) as exc:
        res.erro = str(exc)
    except Exception as exc:
        res.erro = f"{type(exc).__name__}: {exc}"
        try:
            res.prints.append(s.print("erro_limpeza"))
        except Exception:
            pass
    finally:
        res.posts_liberados, res.bloqueios = s.liberados, list(s.bloqueios)
        if dono:
            s.__exit__(None, None, None)
    res.ok = res.erro is None and not res.divergencias
    return res
