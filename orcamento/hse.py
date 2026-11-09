"""Acesso ao HSE pela tela (Playwright). Seletores levantados em docs/mapa-hse.md."""
import functools
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

from orcamento.config import Config
from orcamento.planilha import Item, Orcamento, normalizar, observacoes_hse
from orcamento.processador import PARECIDO, Cliente, ErroHse, HseIndisponivel, Produto, SalvoIncerto, _parecido, _so_palavras

log = logging.getLogger("robo")

BASE = "https://app.hsesistemas.com.br/"
TIMEOUT_MS = 30000
MARKUP = Decimal(45)  # % aplicado no cadastro de produto novo (spec)
RE_CLIENTE = re.compile(r"^\s*(\d+)\s*-\s*(.*?)\s*(?:\(([\d./-]*)\))?\s*$")
RE_PRODUTO = re.compile(r"itemSelected_dsProduto\('([^']*)',\s*'((?:\\'|[^'])*)'")
# 3º argumento do itemSelected_dsProduto = preço de tabela (conferido com o vlOriginal da tela em 29/10/2026)
RE_PRECO = re.compile(r"itemSelected_dsProduto\('[^']*',\s*'(?:\\'|[^'])*',\s*'([\d.]+)'")


def preco_de_tabela(onclick: str) -> Decimal | None:
    m = RE_PRECO.search(onclick)
    return Decimal(m.group(1)) if m else None


RE_LOGIN_NEGADO = re.compile(r"ACESSO NEGADO!?\s*([^\n]*\S)?", re.I)


def _se_recusou(page: Page) -> None:
    """Levanta HseIndisponivel se a tela de login mostra a recusa do HSE (ex.: fora do horário)."""
    try:
        m = RE_LOGIN_NEGADO.search(page.inner_text("body"))
    except PlaywrightError:
        return
    if m:
        raise HseIndisponivel(f"O HSE recusou o login do robô: {m.group(1) or 'acesso negado'}") from None


def br(v: Decimal, casas: int = 2) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def _qtd(v: Decimal) -> str:
    return format(v.normalize(), "f").replace(".", ",")


_INFORMATIVOS = ("toastSuccess", "toastInfo", "toastOk")  # toastOk é o que a tela do pedido usa (envio #153)
RE_MENSAGEM = re.compile(r"""\b(alert|toast\w*)\(\s*(['"])(.+?)\2""")


def _roda_ao_chegar(html: str, pos: int) -> bool:
    """A chamada em `pos` está solta no <script>, fora de qualquer função?"""
    # ponytail: conta chaves, sem entender strings; uma chave dentro de texto esconde a mensagem e o
    # motivo vira "não informou" (a resposta inteira fica em respostas_hse/). Trocar por parser se acontecer.
    trecho = html[html.rfind("<script", 0, pos) + 1:pos]
    return trecho.count("{") <= trecho.count("}")


def _mensagens(html: str) -> list[tuple[str, str]]:
    """(função, texto) de cada alert/toast que a resposta abre na tela ao chegar.

    A resposta do Incluir traz o JavaScript da tela inteira: o toast dentro de uma função só aparece
    num clique ou numa falha futura, e entrava no motivo da recusa como se tivesse aparecido (envio #153)."""
    return [(m.group(1), re.sub(r"\s*<br\s*/?>\s*", " - ", m.group(3))) for m in RE_MENSAGEM.finditer(html)
            if _roda_ao_chegar(html, m.start())]


def motivo_recusa(html: str) -> str:
    """O Incluir recusado não dá erro HTTP: o motivo vem num <script> da resposta (visto no orçamento 16354)."""
    m = re.search(r"erroDescontoMsg\s*=\s*'([^']*)'", html)
    if not m:  # outra recusa (DAV 23): mostra o erro que a resposta abriria na tela, se houver
        erros = [t for f, t in _mensagens(html) if not f.startswith(_INFORMATIVOS)]
        if erros:
            return " - ".join(erros)
        avisos = [t for _, t in _mensagens(html)]
        # DAV 91/93: "Margem atualizada" só informa; mostrar como motivo escondia o problema real
        return ("o HSE não mostrou erro; respondeu só: " + " - ".join(avisos) if avisos
                else "o HSE não informou o motivo")
    motivo = re.sub(r"\s*<br\s*/?>\s*", " - ", m.group(1))
    original = re.search(r"'vlOriginal',\s*([\d.]+)", html)
    maximo = re.search(r"percentDescMax\s*=\s*([\d.]+)", html)
    if original and maximo:
        tabela = Decimal(original.group(1))
        minimo = tabela * (100 - Decimal(maximo.group(1))) / 100
        motivo += f"; preço de tabela {br(tabela)}, menor preço aceito {br(minimo)}"
    return motivo


def enderecos_do_local(local: str, opcoes: list[tuple[str, str]]) -> list[str]:
    """Endereços do cliente que contêm o texto da B30, sem ligar para pontuação.

    "Barão de cocais MG" não casava com ".../BARÃO DE COCAIS/MG" por causa da barra (DAV 20, 29/10/2026).
    Só um número ("2") escolhe pelo número da lista do HSE ("2 - Entrega - ..."): o CEP não aparece na lista
    e o nome da cidade pode casar com vários endereços (PETROBRAS, 29/10/2026)."""
    if re.fullmatch(r"\s*\d{1,3}\s*", local):
        return [v for v, t in opcoes if re.match(rf"\s*{int(local)}\s*-", t)]
    alvo = f" {_so_palavras(local)} "
    return [v for v, t in opcoes if alvo in f" {_so_palavras(t)} "]


def erro_local_entrega(local: str, opcoes: list[tuple[str, str]]) -> str:
    """Erro da B30 que não escolheu um endereço só. Se nenhum contém o texto mas um é claramente
    parecido (erro de digitação), diz qual é; nunca escolhe sozinho, porque o HSE é produção."""
    achados = enderecos_do_local(local, opcoes)
    msg = f"Local de entrega '{local}': {len(achados)} endereço(s) do cliente contém esse texto"
    notas = sorted(((_parecido(local, t), t) for _, t in opcoes), reverse=True)
    if not achados and notas and notas[0][0] >= PARECIDO and (len(notas) == 1 or notas[1][0] < notas[0][0]):
        numero = re.match(r"\s*(\d+)", notas[0][1])
        if numero:
            return f"{msg}. Parece ser o {numero[1]} ({notas[0][1]}): escreva {numero[1]} na B30"
    return f"{msg}; escreva na B30 só o número do endereço ({'; '.join(t for _, t in opcoes)})"


def recusa_do_incluir(numero: int, codigo: str, valor: Decimal, html: str) -> str:
    return f"Item {numero}: o HSE recusou o produto {codigo} a {br(valor)} ({motivo_recusa(html)})"


def _rede(fn):
    """Falha do navegador/rede durante leitura → HseIndisponivel (tenta no próximo ciclo)."""
    @functools.wraps(fn)
    def envolto(*a, **kw):
        try:
            return fn(*a, **kw)
        except PlaywrightError as e:
            raise HseIndisponivel(f"{fn.__name__}: {e}") from e
    return envolto


def _print_na_falha(fn):
    """Falhou mexendo na tela do pedido: guarda um print dela (davs/prints_hse/) antes de seguir com o erro."""
    @functools.wraps(fn)
    def envolto(self, *a, **kw):
        try:
            return fn(self, *a, **kw)
        except Exception:
            self._print_erro(getattr(self, "_pedido", None))
            raise
    return envolto


class Hse:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.rascunho: str | None = None
        self.endereco = ""  # texto do endereço de entrega escolhido em #cdEndereco
        self.avisos: list[str] = []  # avisos do HSE fechados pelo robô (vão para o relatório)
        self.notas: list[str] = []  # descrições de item que não gravaram (vão para o relatório)
        self._pw = self._browser = self._ctx = None
        self._filial: int | None = None
        self._buscas: dict[str, Page] = {}
        self._pedido: Page | None = None
        self._vendedores: dict[str, str] | None = None
        self._orc: Orcamento | None = None
        self._listas: tuple[list[str], list[str], list[str]] | None = None
        self.rotulo = ""  # nº do envio DAV (nome da planilha): nomeia prints e respostas guardados

    # --- sessão ----------------------------------------------------------------

    def __enter__(self):
        try:
            self._pw = sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch(channel="chrome", headless=self.cfg.headless)
            except PlaywrightError:
                self._browser = self._pw.chromium.launch(headless=self.cfg.headless)
            self._login(1)
        except PlaywrightError as e:
            self.__exit__()
            raise HseIndisponivel(f"login: {e}") from e
        except HseIndisponivel:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        for fechar in (self._browser and self._browser.close, self._pw and self._pw.stop):
            try:
                fechar and fechar()
            except Exception:  # noqa: BLE001
                pass
        return False

    def _login(self, filial: int) -> None:
        try:
            self._login_passos(filial)
        except PlaywrightError as e:
            # sem "from e"/mensagem completa: o call log do Playwright traz o fill() da senha
            raise HseIndisponivel(f"login falhou ({type(e).__name__}: {str(e).splitlines()[0][:120]})") from None

    def _login_passos(self, filial: int) -> None:
        if self._ctx:
            self._ctx.close()
        self._ctx = self._browser.new_context(viewport={"width": 1500, "height": 950})
        self._ctx.set_default_timeout(TIMEOUT_MS)
        self._buscas = {}
        self._pedido = None
        page = self._ctx.new_page()
        page.goto(f"{BASE}login2.php?clientID={self.cfg.client_id}", wait_until="networkidle")
        page.fill("#usuario", self.cfg.usuario)
        page.dispatch_event("#usuario", "change")
        page.fill("#senha", self.cfg.senha)
        page.click("#validarLogin")
        try:
            page.locator("#empresa").wait_for(state="visible", timeout=15000)
        except PlaywrightError:
            _se_recusou(page)
            raise HseIndisponivel("login recusado (confira HSE_USUARIO/HSE_SENHA)") from None
        empresa = page.evaluate("() => [...document.querySelectorAll('#empresa option')].find(o => o.value)?.value")
        page.select_option("#empresa", empresa)
        page.dispatch_event("#empresa", "change")
        achar = f"[...document.querySelectorAll('#filial option')].find(o => o.text.trim().startsWith('{filial} -'))"
        page.wait_for_function(f"() => !!{achar}")
        page.select_option("#filial", page.evaluate(f"() => {achar}.value"))
        page.dispatch_event("#filial", "change")
        page.click("#validarLogin")
        # Fora do horário do usuário o HSE fica em login2.php com "ACESSO NEGADO!": não espera o timeout.
        page.wait_for_function("() => !location.href.includes('login2.php') || /ACESSO NEGADO/i.test(document.body.innerText)")
        if "login2.php" in page.url:
            _se_recusou(page)
        page.wait_for_load_state("networkidle")
        page.close()
        self._filial = filial
        log.info("Login no HSE ok (filial %s)", filial)

    def _garantir_filial(self, filial: int) -> None:
        if filial != self._filial:
            self._login(filial)

    def _abrir(self, caminho: str) -> Page:
        page = self._ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.goto(BASE + caminho, wait_until="networkidle")
        if "login2.php" in page.url:  # sessão caiu
            page.close()
            self._login(self._filial or 1)
            return self._abrir(caminho)
        return page

    def _pagina_busca(self, tipo: str = "cliente") -> Page:
        """Uma vendaAlt.php por tipo: buscar cliente na mesma página zera a busca de produto."""
        page = self._buscas.get(tipo)
        if tipo == "ncm" and (not page or page.is_closed()):
            page = self._buscas[tipo] = self._abrir(f"produtoAlt.php?cdFilial={self._filial or 1}")
        elif not page or page.is_closed():
            page = self._buscas[tipo] = self._abrir("vendaAlt.php")
            # dsProduto nasce readonly até escolher cliente; a busca em si não depende dele
            page.evaluate("() => { const e = document.querySelector('#dsProduto');"
                          " e.readOnly = false; e.removeAttribute('readonly'); }")
        return page

    # --- autocomplete ------------------------------------------------------------

    @staticmethod
    def _autocomplete(page: Page, campo: str, termo: str) -> list[tuple[str, str]]:
        """Digita no campo de busca do HSE e devolve [(onclick, texto)] das sugestões."""
        def eh_busca(r) -> bool:
            q = parse_qs(urlparse(r.url).query)
            return ("searchAjax.php" in r.url and q.get("dsInput") == [campo]
                    and q.get("search") == [termo])
        # cola tudo menos a última letra e digita só ela (é a tecla que dispara a busca): digitar uma
        # descrição de 544 letras com 40 ms cada estourava os 30 s da espera (DAV 1 de 29/10/2026)
        for tentativa in (1, 2):  # uma lentidão do HSE não vira "fora do ar" na 1ª vez (davs__20, 29/10/2026)
            try:
                page.fill(f"#{campo}", termo[:-1])
                with page.expect_response(eh_busca):
                    page.type(f"#{campo}", termo[-1:])
                break
            except PlaywrightError:
                if tentativa == 2:
                    raise
                log.warning("Busca de %s demorou demais; tentando de novo", campo)
        page.wait_for_timeout(500)
        return page.eval_on_selector_all(
            f"[id^=searchItemClick_{campo}_]",
            "els => els.filter(e => e.offsetParent !== null)"
            ".map(e => [e.getAttribute('onclick') || '', e.innerText.trim()])")

    # --- leitura (HseApi) --------------------------------------------------------

    @_rede
    def buscar_cliente(self, chave: str) -> list[Cliente]:
        page = self._pagina_busca()
        clientes = []
        for _, texto in self._autocomplete(page, "dsCliente", chave):
            m = RE_CLIENTE.match(texto)
            if m:
                clientes.append(Cliente(m.group(1), m.group(2), m.group(3) or ""))
        page.keyboard.press("Escape")
        return clientes

    @_rede
    def vendedor_existe(self, nome: str) -> bool:
        return normalizar(nome) in self._lista_vendedores()

    @_rede
    def nomes_vendedores(self) -> list[str]:
        return list(self._lista_vendedores())

    def _lista_vendedores(self) -> dict[str, str]:
        if self._vendedores is None:
            opcoes = self._pagina_busca().eval_on_selector_all(
                "#cdVendedor option", "os => os.filter(o => o.value).map(o => [o.value, o.text.trim()])")
            self._vendedores = {normalizar(t): v for v, t in opcoes}
        return self._vendedores

    @_rede
    def buscar_produtos(self, termo: str) -> list[Produto]:
        page = self._pagina_busca("produto")
        produtos = []
        for onclick, texto in self._autocomplete(page, "dsProduto", termo):
            m = RE_PRODUTO.search(onclick)
            if not m:
                continue
            codigo, rotulo = m.group(1), m.group(2).replace("\\'", "'")
            desc = rotulo.split(" - ", 1)[1] if rotulo.startswith(f"{codigo} - ") else rotulo
            inativo = "(INATIVO)" in texto.upper() or "(INATIVO)" in desc.upper()
            desc = re.sub(r"\s*\(INATIVO\)\s*", " ", desc, flags=re.I).strip()
            produtos.append(Produto(codigo, desc, not inativo, preco_de_tabela(onclick)))
        page.keyboard.press("Escape")
        return produtos

    def marcas(self) -> list[str]:
        return self._listas_cache()[2]

    def grupos(self) -> list[str]:
        return self._listas_cache()[1]

    def _listas_cache(self):
        if self._listas is None:
            self._listas = self.listas()
        return self._listas

    @_rede
    def ncm_existe(self, ncm: str) -> bool:
        page = self._pagina_busca("ncm")
        achou = any(ncm in re.sub(r"\D", "", texto) for _, texto in self._autocomplete(page, "dsNcm", ncm))
        page.keyboard.press("Escape")
        return achou

    # --- orçamento ---------------------------------------------------------------

    @_print_na_falha
    def montar_orcamento(self, orc: Orcamento, cliente: Cliente,
                         itens: list[tuple[Item, Produto | None]], incluir: bool) -> None:
        self._garantir_filial(orc.filial)
        self.rascunho = None
        self.endereco = ""
        self.avisos = []
        self.notas = []
        page = self._pedido = self._abrir("vendaAlt.php")
        if page.input_value("#cdFilial") != str(orc.filial):
            raise ErroHse(f"tela abriu na filial {page.input_value('#cdFilial')}, esperado {orc.filial}")
        page.select_option("#idTipo", "0")
        page.select_option("#cdVendedor", self._lista_vendedores()[normalizar(orc.vendedor)])
        self._escolher_cliente(page, cliente)
        self._preencher_cabecalho(page, orc)
        for item, produto in itens:
            if produto is None:  # produto novo no DRY_RUN: ainda não existe no HSE
                continue
            self._preencher_item(page, item, produto, incluir)
        self._conferir_pagamento(page, orc)
        self._orc = orc

    def _escolher_cliente(self, page: Page, cliente: Cliente) -> None:
        self._autocomplete(page, "dsCliente", cliente.codigo)
        page.locator("[id^=searchItemClick_dsCliente_]").filter(
            has_text=re.compile(rf"^\s*{cliente.codigo} - ")).first.click()
        page.wait_for_function(f"() => document.querySelector('#cdCliente').value === '{cliente.codigo}'")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)  # o validaCliente abre o aviso logo depois
        self._fechar_aviso(page)

    def _fechar_aviso(self, page: Page) -> None:
        """Fecha o aviso modal do HSE (ex.: "Pendência Cliente bloqueado. Consultar o setor financeiro").

        Visto com a VALE 1485 em 29/10/2026: o aviso cobre a tela e o clique em Incluir caía nele.
        Num orçamento ele só informa, então o robô guarda o texto para o relatório e segue."""
        modal = page.locator("#modalAlert")
        if not modal.is_visible():
            return
        texto = " ".join(modal.inner_text().split())
        texto = re.sub(r"\s*\bok$", "", texto, flags=re.I)
        if texto and texto not in self.avisos:
            self.avisos.append(texto)
        page.evaluate("() => jQuery('#modalAlert').modal('hide')")
        page.wait_for_timeout(800)  # animação de saída do modal

    @staticmethod
    def _set_select_oculto(page: Page, seletor: str, valor: str) -> None:
        page.evaluate("""([s, v]) => { const e = document.querySelector(s); e.value = v;
            if (window.$) { $(e).trigger('change'); if ($(e).selectpicker) $(e).selectpicker('refresh'); }
            else e.dispatchEvent(new Event('change')); }""", [seletor, valor])

    def _preencher_cabecalho(self, page: Page, orc: Orcamento) -> None:
        if orc.local_entrega:
            opcoes = page.eval_on_selector_all("#cdEndereco option",
                                               "os => os.filter(o => o.value).map(o => [o.value, o.text])")
            achados = enderecos_do_local(orc.local_entrega, opcoes)
            if not achados and len(opcoes) == 1 and _parecido(orc.local_entrega, opcoes[0][1]) >= PARECIDO:
                # cliente com um endereço só e B30 com erro de digitação ("STRADA", DAV #36): não há outro
                achados = [opcoes[0][0]]
                self.notas.append(f"Local de entrega '{orc.local_entrega}' não bate com o cadastro; usei o "
                                  f"único endereço do cliente: {opcoes[0][1]}; confira")
            if len(achados) != 1:
                raise ErroHse(erro_local_entrega(orc.local_entrega, opcoes))
            self._set_select_oculto(page, "#cdEndereco", achados[0])
            self.endereco = next(t for v, t in opcoes if v == achados[0])
        self._pagamento(page, orc)
        if orc.prazo_dias is not None:
            previsao = date.today() + timedelta(days=orc.prazo_dias)
            page.evaluate("v => { document.querySelector('#dtPrevisao').value = v; }",
                          previsao.strftime("%d/%m/%Y"))
        if orc.ordem_compra:
            page.fill("#rfOrdemCompra", orc.ordem_compra)
        if obs := observacoes_hse(orc):
            page.fill("#txObservacao", obs)

    def _pagamento(self, page: Page, orc: Orcamento) -> None:
        """rfFormaPg recarrega cdCondPg via AJAX (listarCondPg): espera antes de escolher o parcelamento."""
        if orc.forma_pg and page.input_value("#rfFormaPg") != orc.forma_pg:
            with page.expect_response(lambda r: "vendaAlt.php" in r.url
                                      and "acao=listarCondPg" in (r.request.post_data or "")):
                page.select_option("#rfFormaPg", orc.forma_pg)
            page.wait_for_load_state("networkidle")
        if not orc.parcelamento:
            return
        opcoes = page.eval_on_selector_all("#cdCondPg option",
                                           "os => os.filter(o => o.value).map(o => [o.value, o.text])")
        valor = next((v for v, t in opcoes if normalizar(t) == normalizar(orc.parcelamento)), None)
        if not valor:
            raise ErroHse(f"Parcelamento '{orc.parcelamento}' não existe para essa forma de pagamento")
        page.select_option("#cdCondPg", valor)

    def _conferir_pagamento(self, page: Page, orc: Orcamento) -> None:
        """Cliente/itens podem resetar o parcelamento: confere (e refaz uma vez) antes de salvar."""
        def ok() -> bool:
            texto = page.evaluate("() => document.querySelector('#cdCondPg').selectedOptions[0]?.text || ''")
            return ((not orc.forma_pg or page.input_value("#rfFormaPg") == orc.forma_pg)
                    and (not orc.parcelamento or normalizar(texto) == normalizar(orc.parcelamento)))
        if not ok():
            log.info("Pagamento/parcelamento foi resetado pela tela; preenchendo de novo")
            self._pagamento(page, orc)
        if not ok():
            raise ErroHse(f"não consegui manter forma '{orc.forma_pg}' / parcelamento '{orc.parcelamento}'")

    def _preencher_item(self, page: Page, item: Item, produto: Produto, incluir: bool) -> None:
        self._fechar_aviso(page)
        self._autocomplete(page, "dsProduto", produto.codigo)
        alvo = page.locator(f"[id^=searchItemClick_dsProduto_][onclick*=\"itemSelected_dsProduto('{produto.codigo}'\"]")
        if alvo.count() == 0:
            raise ErroHse(f"Item {item.numero}: produto {produto.codigo} não apareceu na busca da tela")
        alvo.first.click()
        page.wait_for_function("() => document.querySelector('#vlUnitario').value !== ''")
        page.wait_for_load_state("networkidle")  # o preço do cadastro chega depois e sobrescreveria o nosso
        page.wait_for_timeout(800)
        # digita + Tab (nunca Enter: o Enter nesses campos dispara o Incluir)
        for campo, valor in (("#qtProduto", _qtd(item.quantidade)), ("#vlUnitario", br(item.valor_unit))):
            page.click(campo)
            page.keyboard.press("Control+A")
            page.keyboard.type(valor)
            page.keyboard.press("Tab")
            page.wait_for_load_state("networkidle")
        na_tela = (page.input_value("#qtProduto"), page.input_value("#vlUnitario"))
        if na_tela != (_qtd(item.quantidade), br(item.valor_unit)):
            raise ErroHse(f"Item {item.numero}: tela ficou com qtd/preço {na_tela}, "
                          f"esperado {(_qtd(item.quantidade), br(item.valor_unit))}")
        if not incluir:
            log.info("[DRY_RUN] item %s preenchido (%s x %s) — Incluir NÃO clicado",
                     produto.codigo, _qtd(item.quantidade), br(item.valor_unit))
            if page.locator("#selected_dsProduto").is_visible():
                page.dblclick("#selected_dsProduto")  # limpa a seleção para o próximo item
            return
        antes = page.locator("td.cellDelete").count()
        linhas = set(page.eval_on_selector_all("tr[id^=trItem_]", "ts => ts.map(t => t.id)"))
        self._incluir(page, item, produto, antes)
        log.info("Item %s incluído; rascunho %s", produto.codigo, self.rascunho)
        if item.descricao:
            self._gravar_descricao(page, item, linhas)

    def _incluir(self, page: Page, item: Item, produto: Produto, antes: int) -> None:
        # Nunca repetir o Incluir: nos DAV 91/93 o HSE incluiu (orçamentos 16533/16534/16536) e só o
        # nº do pedido demorou a aparecer na VM; clicar de novo duplicaria o item.
        html = self._clicar_incluir(page)
        if not self._item_entrou(page, antes):
            self._guardar_resposta(produto.codigo, html)
            raise ErroHse(recusa_do_incluir(item.numero, produto.codigo, item.valor_unit, html))

    def _clicar_incluir(self, page: Page) -> str:
        """Clica Incluir e devolve o HTML da resposta do vendaItem.php."""
        self._fechar_aviso(page)
        try:
            with page.expect_response(lambda r: "vendaItem.php" in r.url and r.request.method == "POST"
                                      and "acao=incluir" in (r.request.post_data or "")) as resp:
                page.click("#btAddProduto")
            page.wait_for_load_state("networkidle")
        finally:  # mesmo com timeout o servidor pode ter criado o pedido: guarda o nº para cancelar
            cd = self._cd_pedido(page)
            if cd:
                self.rascunho = cd
        return resp.value.text()

    def _item_entrou(self, page: Page, antes: int) -> bool:
        """A linha nova na tabela é a prova de que o item entrou; o nº do pedido pode chegar depois.

        DAV 91/93: o robô leu o #cdPedido logo após o Incluir, achou vazio e deu "recusado" com o
        pedido já criado no HSE. Espera a linha (até 15 s) e só então pega o nº do rascunho."""
        try:
            page.wait_for_function("n => document.querySelectorAll('td.cellDelete').length > n", arg=antes,
                                   timeout=15000)
        except PlaywrightError:
            return False
        cd = self._cd_pedido(page)
        if cd:
            self.rascunho = cd
        return True

    def _guardar_resposta(self, codigo: str, html: str) -> None:
        """A resposta inteira fica em davs/respostas_hse/ para achar o motivo real de uma recusa."""
        try:
            pasta = Path(self.cfg.pasta_programa) / "respostas_hse"
            pasta.mkdir(parents=True, exist_ok=True)
            arquivo = pasta / f"{getattr(self, 'rotulo', '') or 'hse'}_{datetime.now():%Y%m%d-%H%M%S}_{codigo}.html"
            arquivo.write_text(html, encoding="utf-8")
            log.warning("Resposta do Incluir recusado guardada em %s", arquivo)
        except Exception as e:  # noqa: BLE001 — nunca troca a recusa por um erro daqui
            log.warning("Não guardei a resposta do Incluir: %s", e)

    def _print_erro(self, page: Page | None) -> None:
        """Print da tela na hora do erro; nunca troca o erro original por um erro do print."""
        try:
            if page is None or page.is_closed():
                return
            pasta = Path(self.cfg.pasta_programa) / "prints_hse"
            pasta.mkdir(parents=True, exist_ok=True)
            arquivo = pasta / f"{getattr(self, 'rotulo', '') or 'hse'}_{datetime.now():%Y%m%d-%H%M%S}.png"
            page.screenshot(path=str(arquivo), full_page=True)
            log.warning("Print da tela do HSE no erro: %s", arquivo)
        except Exception as e:  # noqa: BLE001
            log.warning("Não consegui o print do erro: %s", e)

    def _gravar_descricao(self, page: Page, item: Item, antes: set[str]) -> None:
        """A caixa #dsObsItem_<cdItem> só existe depois do Incluir; o onblur chama salvarObsItem (vendaItem.php).

        Visto no DAV 16354 em 29/10/2026. Se não gravar, o DAV segue e o relatório avisa."""
        try:
            novas = set(page.eval_on_selector_all("tr[id^=trItem_]", "ts => ts.map(t => t.id)")) - antes
            if len(novas) != 1:
                raise ErroHse(f"{len(novas)} linha(s) nova(s) na tabela")
            cd = novas.pop().split("_")[1]
            campo = f"#dsObsItem_{cd}"
            page.click(f"#trItem_{cd} button[onclick^='abreObsItem']")
            page.fill(campo, item.descricao)
            with page.expect_response(lambda r: "vendaItem.php" in r.url and r.request.method == "POST"
                                      and "acao=salvarObsItem" in (r.request.post_data or "")) as resp:
                page.locator(campo).blur()
            if not resp.value.ok:
                raise ErroHse("o HSE respondeu com erro")
            if " ".join(page.inner_text(f"#divObsItem_{cd}").split()) != " ".join(item.descricao.split()):
                raise ErroHse("o texto não apareceu na linha do item")
        except (PlaywrightError, ErroHse) as e:
            motivo = str(e).splitlines()[0][:120]
            log.warning("Item %s: descrição não gravada (%s)", item.numero, motivo)
            self.notas.append(f"Item {item.numero}: descrição não gravada no HSE ({motivo}); confira no DAV")

    @staticmethod
    def _cd_pedido(page: Page) -> str:
        try:
            cd = page.input_value("#cdPedido", timeout=5000)
            if not cd or cd == "0":  # a spec diz que a URL ganha ?cdPedido=NNNNN
                cd = parse_qs(urlparse(page.url).query).get("cdPedido", [""])[0]
        except PlaywrightError:
            return ""
        return "" if cd in ("", "0") else cd

    # --- escrita (só com DRY_RUN=0 e teste autorizado) ---------------------------

    @_print_na_falha
    def salvar_orcamento(self) -> str:
        # A janela fecha ao salvar e a resposta costuma vir ilegível (visto nos testes 16295/16297/16298):
        # o nº vem do rascunho e o salvamento é conferido reabrindo o pedido.
        page = self._pedido
        self._conferir_pagamento(page, self._orc)
        pendente = self.rascunho or "?"
        self._fechar_aviso(page)
        try:
            with page.expect_response(lambda r: "vendaAlt.php" in r.url and r.request.method == "POST"
                                      and "acao=salvar" in (r.request.post_data or "")) as resp:
                page.click("#btSalvar")
        except PlaywrightError as e:  # pode ter salvo: nunca tratar como rascunho a cancelar
            self.rascunho = None
            raise SalvoIncerto(pendente, f"sem resposta do Salvar ({str(e).splitlines()[0][:120]})") from None
        try:
            dados = resp.value.json()
        except Exception as e:  # noqa: BLE001 — a janela fecha logo após salvar
            log.warning("Resposta do salvar ilegível (%s); uso o nº do rascunho %s", e, self.rascunho)
            dados = {}
        log.info("Resposta do salvar: %s", str(dados)[:300])
        if dados.get("error"):
            raise ErroHse(f"HSE recusou o salvar: {dados.get('message')}")
        numero = str(dados.get("cdPedido") or self.rascunho or "")
        self.rascunho = None  # daqui em diante o pedido pode estar salvo: nada de cancelar
        if not numero:
            raise SalvoIncerto("?", f"Salvar respondeu sem nº: {str(dados)[:200]}")
        try:
            self.confirmar_salvo(numero)
        except Exception as e:  # noqa: BLE001
            raise SalvoIncerto(numero, f"não confirmei o salvamento ({str(e).splitlines()[0][:120]})") from None
        return numero

    def confirmar_salvo(self, numero: str) -> None:
        """A resposta do salvar se perde quando a janela fecha: reabre o pedido e confere."""
        page = self._abrir(f"vendaAlt.php?cdPedido={numero}")
        try:
            try:
                page.get_by_role("button", name="Editar").first.wait_for(state="visible", timeout=10000)
                salvo = True
            except PlaywrightError:
                salvo = False
            tipo = page.evaluate("() => document.querySelector('#idTipo')?.selectedOptions[0]?.text")
            if not salvo or tipo != "Orçamento":
                raise ErroHse(f"pedido {numero} não ficou salvo como Orçamento (tipo={tipo}, salvo={salvo})")
        finally:
            page.close()

    def cancelar_rascunho(self) -> str | None:
        numero = self.rascunho
        if not numero:
            return None
        page = self._pedido if self._pedido and not self._pedido.is_closed() \
            else self._abrir(f"vendaAlt.php?cdPedido={numero}&editar=1")
        excluir = page.locator("td.cellDelete button.btnDelete:enabled")
        while (n := excluir.count()):
            excluir.first.click()
            with page.expect_response(lambda r: "vendaItem.php" in r.url):
                page.get_by_role("button", name="confirmar exclusão", exact=True).first.click()
            # a tabela é redesenhada depois da resposta: sem esperar, clica num botão que já sumiu (rascunho 16356)
            page.wait_for_function("n => document.querySelectorAll('td.cellDelete button.btnDelete:enabled')"
                                   ".length < n", arg=n)
            page.wait_for_load_state("networkidle")
        # A tela real não tem o botão Cancelar da spec (só a gestora exclui pedidos): o rascunho fica vazio.
        self.rascunho = None
        return numero

    def cadastrar_produto(self, item: Item, filial: int, salvar: bool) -> str | None:
        self._garantir_filial(filial)
        page = self._abrir(f"produtoAlt.php?cdFilial={filial}")
        try:
            self._preencher_produto(page, item)
            if not salvar:
                log.info("[DRY_RUN] cadastro de '%s' preenchido — Salvar NÃO clicado", item.descricao_cadastro)
                return None
            # ponytail: salvar produto não testado; validar no teste autorizado (um produto).
            with page.expect_response(lambda r: "produtoAjax.php" in r.url and r.request.method == "POST") as resp:
                page.click("#btnSalvar")
            try:
                dados = resp.value.json()
            except Exception as e:  # noqa: BLE001 — a janela pode fechar/navegar ao salvar
                log.warning("Resposta do cadastro ilegível (%s); procuro o código pela descrição", e)
                dados = {}
            log.info("Resposta do cadastro: %s", str(dados)[:300])
            if dados.get("error"):
                raise ErroHse(f"HSE recusou o cadastro: {dados.get('message')}")
            codigo = str(dados.get("rfProduto") or dados.get("cod_produto") or "") or self._codigo_por_descricao(item)
            log.info("Produto '%s' cadastrado com código %s", item.descricao_cadastro, codigo)
        except Exception:
            self._print_erro(page)
            raise
        finally:
            page.close()
        # O HSE gera cód. de barras ao salvar (e regera se apagado); combinado: fica o que ele gerar.
        return codigo

    def _codigo_por_descricao(self, item: Item) -> str:
        alvo = normalizar(item.descricao_cadastro)
        # busca com o texto original: o HSE guarda o acento e não acha "ABRACADEIRA" (envio #85)
        termo = " ".join(item.descricao_cadastro.split())
        achados = [p.codigo for p in self.buscar_produtos(termo) if normalizar(p.descricao) == alvo]
        if len(achados) != 1:
            raise ErroHse(f"cadastro salvo, mas não identifiquei o código de '{item.descricao_cadastro}' "
                          f"(achados: {achados}); confira no HSE")
        return achados[0]

    def _preencher_produto(self, page: Page, item: Item) -> None:
        def por_texto(seletor: str, nome: str, rotulo: str, so_nome: bool = False) -> str:
            opcoes = page.eval_on_selector_all(seletor + " option", "os => os.map(o => [o.value, o.text.trim()])")
            for v, t in opcoes:
                texto = t.split("-", 1)[1] if so_nome and "-" in t else t
                if v and normalizar(texto) == normalizar(nome):
                    return v
            raise ErroHse(f"Item {item.numero}: {rotulo} '{nome}' não existe no HSE")

        page.select_option("#cdGrupo", por_texto("#cdGrupo", item.grupo, "GRUPO", so_nome=True))
        page.select_option("#COD_MARCA", por_texto("#COD_MARCA", item.marca, "MARCA"))
        page.fill("#descricao", item.descricao_cadastro[:100])
        page.fill("#dsProdutoNfe", item.descricao_cadastro[:100])
        page.select_option("#rfUnidade", "UN")
        for campo in ("#vlPrecoCompra", "#vlUltimoCusto"):  # Custo unitário / Custo total (médio é readonly)
            page.fill(campo, br(item.custo, 6))
            page.dispatch_event(campo, "keyup")
            page.dispatch_event(campo, "change")
        page.fill("#vlMargem1", br(MARKUP, 4))
        page.dispatch_event("#vlMargem1", "keyup")  # a tela recalcula o TAB.1 no keyup
        esperado = (item.custo * (1 + MARKUP / 100)).quantize(Decimal("0.01"))
        tab1 = Decimal(page.input_value("#vlTabela1").replace(".", "").replace(",", "."))
        if tab1.quantize(Decimal("0.01")) != esperado:
            raise ErroHse(f"Item {item.numero}: preço TAB.1 calculado {tab1} ≠ esperado {esperado}")
        page.fill("#DS_COD_BARRA", "")
        self._autocomplete(page, "dsNcm", item.ncm)
        ncm = page.locator("[id^=searchItemClick_dsNcm_]").filter(has_text=item.ncm)
        if ncm.count() == 0:
            raise ErroHse(f"Item {item.numero}: NCM {item.ncm} não encontrado no HSE")
        ncm.first.click()
        page.wait_for_load_state("networkidle")
        page.select_option("#idNacional", str(item.origem))
        page.select_option("#TRIBUTACAO", "00")
        page.dispatch_event("#TRIBUTACAO", "change")
        page.wait_for_load_state("networkidle")
        if page.locator("#rfAliquota").is_visible():
            page.fill("#rfAliquota", br(item.icms))
        else:
            log.info("Item %s: ICMS segue a regra do NCM %s (campo oculto no HSE)", item.numero, item.ncm)

    # --- DAV ---------------------------------------------------------------------

    def baixar_dav(self, numero: str, destino: Path) -> None:
        """Espelho A4 em PDF. page.pdf() só existe em headless: navegador à parte com a mesma sessão."""
        estado = self._ctx.storage_state()
        try:
            headless = self._pw.chromium.launch(channel="chrome", headless=True)
        except PlaywrightError:
            headless = self._pw.chromium.launch(headless=True)
        try:
            page = headless.new_context(storage_state=estado).new_page()
            page.goto(f"{BASE}vendaEspelho.php?cdPedido={numero}", wait_until="networkidle")
            if numero not in page.inner_text("body"):
                raise ErroHse(f"espelho do orçamento {numero} não abriu")
            page.emulate_media(media="print")
            page.pdf(path=str(destino), format="A4", print_background=True,
                     margin={"top": "8mm", "bottom": "8mm", "left": "6mm", "right": "6mm"})
        finally:
            headless.close()

    # --- listas (atualizar_listas.py) ---------------------------------------------

    @_rede
    def listas(self) -> tuple[list[str], list[str], list[str]]:
        vendedores = sorted({t for t in self._pagina_busca().eval_on_selector_all(
            "#cdVendedor option", "os => os.filter(o => o.value).map(o => o.text.trim())")})
        page = self._abrir(f"produtoAlt.php?cdFilial={self._filial or 1}")
        try:
            grupos = page.eval_on_selector_all(
                "#cdGrupo option", "os => os.filter(o => o.value).map(o => o.text.trim())")
            marcas = page.eval_on_selector_all(
                "#COD_MARCA option", "os => os.filter(o => o.value).map(o => o.text.trim())")
        finally:
            page.close()
        grupos = sorted({g.split("-", 1)[1].strip() if "-" in g else g for g in grupos})
        return vendedores, grupos, sorted(set(marcas))


GRAVACAO = re.compile(r"acao=\w*(incluir|salvar|excluir|gravar|alterar|cadastr|inserir|atualizar|delet)", re.I)


def guarda_gravacao(route, bloqueados: list[str]) -> None:
    """Aborta qualquer requisição que grave no HSE; o resto passa."""
    corpo = route.request.post_data or ""
    if route.request.method != "GET" and GRAVACAO.search(corpo):
        bloqueados.append(f"{route.request.url.rsplit('/', 1)[-1]} {corpo[:60]}")
        return route.abort()
    return route.continue_()


class HseSoLeitura(Hse):
    """Navegador que nunca grava: usado para conferir um DAV já feito."""

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.bloqueados: list[str] = []

    def _login_passos(self, filial: int) -> None:
        super()._login_passos(filial)
        self._ctx.route("**/*", lambda route: guarda_gravacao(route, self.bloqueados))  # cada login cria um contexto novo

    @_rede
    def ler_pedido(self, numero: int) -> dict | None:
        """Cliente, data e itens de um pedido já gravado; None se o número não existe.

        Pedido incompleto (rascunho esvaziado) existe: #cdPedido preenchido, cliente/data vazios.
        Página que não carregou ou layout irreconhecível levantam erro: nunca viram "não existe"."""
        page = self._abrir(f"vendaAlt.php?cdPedido={numero}")
        try:
            page.wait_for_selector("#cdPedido", state="attached", timeout=15000)  # levanta se a página não carregou
            try:
                page.wait_for_selector("tr[id^=trItem_]", timeout=5000)
            except PlaywrightError:  # pedido sem itens existe
                pass
            cru = page.evaluate("""() => ({
                pedido: document.querySelector('#cdPedido')?.value || '',
                cliente: document.querySelector('#cdCliente')?.value || '',
                data: document.querySelector('#dtEmissao')?.value || '',
                linhas: [...document.querySelectorAll('tr[id^=trItem_]')]
                    .map(tr => [...tr.cells].map(c => c.innerText.trim()))})""")
        finally:
            page.close()
        if not cru["pedido"]:
            return None
        itens = [{"codigo": c[3], "qtd": c[10], "valor": c[12]} for c in cru["linhas"] if len(c) > 12]
        if cru["linhas"] and not itens:
            raise HseIndisponivel(f"pedido {numero}: linhas de item com layout desconhecido")
        return {"numero": numero, "cliente": cru["cliente"], "data": cru["data"], "itens": itens}
