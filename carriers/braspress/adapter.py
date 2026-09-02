"""Braspress — cotação pelo formulário logado.

    https://blue.braspress.com/site/w/cliente/view     login
    https://blue.braspress.com/site/w/cotacao/view      formulário de cotação

A "Área do Cliente" em www.braspress.com é só a casca: quem faz login e
mostra o formulário é este outro domínio, dentro de um iframe — por isso o
adapter vai direto nele, sem passar pelo site principal (chatbot "Romilda",
banner de cookies, reCAPTCHA da busca de rastreio — nada disso tem a ver com
a cotação). Medido em 02/09/2026, ver recon/recon_braspress.py.

Credenciais no .env (BRASPRESS_USUARIO / BRASPRESS_SENHA) — o usuário é o
próprio CNPJ da Ventura, 08310365000124.

FORMULÁRIO DE UMA TELA SÓ (sem etapas, sem popup de cubagem à parte — a
tabela de linhas já fica na própria tela, com um botão "+" para cada volume
de tamanho diferente).

O CNPJ da Ventura está SEMPRE de um lado da carga: o select "Tipo de Frete"
prende remetente (CIF) ou destinatário (FOB) no CNPJ do login, com razão
social/CEP/filial já preenchidos pelo próprio site. O outro lado é digitado
— ver carriers.braspress.mapping.cnpj_lado_livre — e a Braspress resolve
razão social e endereço inteiros sozinha a partir do CNPJ.
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from carriers.base import (
    CampoSpec, CredencialRecusada, ErroValidacao, Modo, ResultadoCotacao,
    Severidade, argumentos_de_navegador_real, erro_do_adapter, print_seguro,
    recusa_por_validacao,
)
from carriers.braspress.mapping import (
    campo_cubagem, cnpj_lado_livre, ler_recusa, ler_sucesso,
    medida_para_campo, peso_para_campo, valor_nf_para_campo, valor_tipo_frete,
)
from core.models import CotacaoRequest, StatusCotacao, TipoFrete

URL_LOGIN = "https://blue.braspress.com/site/w/cliente/view"
URL_COTACAO = "https://blue.braspress.com/site/w/cotacao/view"

# Digitação humana: a busca de CNPJ do site não dispara com fill() — testado
# em 02/09/2026, fill() além de não disparar a busca CORTOU um dígito do CEP
# digitado direto (mascara de input).
DELAY_DIGITACAO_MS = 70
ESPERA_BUSCA_MS = 3_500


def _falhar_login(page) -> None:
    """Olha a tela parada, diz o que de fato aconteceu e levanta.

    Mesma lógica da Generoso: senha recusada é CredencialRecusada (não
    repete — três tentativas travam a conta da Ventura); formulário que nem
    chegou a ser enviado é erro comum."""
    try:
        preenchida = bool(
            page.locator('input[name="pass"]').first.input_value().strip())
    except Exception:
        raise RuntimeError("o login na Braspress não passou e não deu para "
                           "ver a tela para dizer por quê.")
    if preenchida:
        raise CredencialRecusada(
            "a Braspress não aceitou o login. Confira BRASPRESS_USUARIO e "
            "BRASPRESS_SENHA no .env, ou entre à mão em "
            f"{URL_LOGIN} para ver a mensagem do site. Não vou tentar de "
            "novo para não travar a conta.")
    raise RuntimeError(
        "o login na Braspress não passou: o campo de senha ficou vazio, ou "
        "seja, o formulário nem chegou a ser enviado. Costuma passar sozinho "
        "na tentativa seguinte.")


class BraspressAdapter:
    slug = "braspress"
    nome = "Braspress"
    modo: Modo = Modo.SINCRONO              # devolve preço na hora
    ativo = True
    fator_cubagem: Decimal = Decimal(300)   # ⚠ presumido; o site calcula sozinho
    sla_esperado_min: int | None = None

    def __init__(self, headless: bool = True, timeout_ms: int = 45_000,
                 workdir: str = "teste_real/braspress",
                 usuario: str | None = None, senha: str | None = None) -> None:
        self.usuario = usuario if usuario is not None else os.getenv(
            "BRASPRESS_USUARIO")
        self.senha = senha if senha is not None else os.getenv(
            "BRASPRESS_SENHA")
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.workdir = Path(workdir)

    def opcoes_do_navegador(self) -> dict:
        return {"headless": self.headless, "args": argumentos_de_navegador_real()}

    # ------------------------------------------------------- camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return [
            CampoSpec("CNPJ do lado livre", True, "text"),
            CampoSpec("Peso", True, "text"),
            CampoSpec("Valor da mercadoria", True, "text"),
            CampoSpec("Comprimento", True, "text"),
            CampoSpec("Largura", True, "text"),
            CampoSpec("Altura", True, "text"),
            CampoSpec("Quantidade de volumes", True, "text"),
        ]

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        erros: list[ErroValidacao] = []
        if req.peso_total_kg <= 0:
            erros.append(ErroValidacao("peso_kg",
                                       "Peso precisa ser maior que zero."))
        return erros

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        return {
            "tipoFrete": valor_tipo_frete(req),
            "cnpjLivre": cnpj_lado_livre(req),
            "peso": peso_para_campo(req.peso_total_kg),
            "vlrMercadoria": valor_nf_para_campo(req.nota_fiscal.valor_total),
            "altEmail": req.solicitante.email,
            "cubagem": [
                {
                    "comprimento": medida_para_campo(v.comprimento_cm),
                    "largura": medida_para_campo(v.largura_cm),
                    "altura": medida_para_campo(v.altura_cm),
                    "volumes": str(v.qtd),
                }
                for v in req.volumes
            ],
        }

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        """`raw` é o HTML inteiro da página (page.content()), não o texto
        visível: depois de "Calcular" a Braspress NÃO navega — insere o
        resultado embaixo do próprio formulário, e o texto visível sozinho
        (via inner_text) estourava os 800 caracteres do raw_response antes
        de chegar lá. Medido no envio real de 02/09/2026, cotação
        #373377732 — ver carriers.braspress.mapping."""
        html = str(raw or "")

        sucesso = ler_sucesso(html)
        if sucesso is not None:
            return ResultadoCotacao(
                transportadora=self.slug,
                status=StatusCotacao.COTADO,
                protocolo=sucesso.protocolo,
                valor_frete=sucesso.valor_frete,
                prazo_dias=sucesso.prazo_dias,
                raw_response=html[-2000:],
                erro=(None if sucesso.valor_frete is not None else
                      "A Braspress disse sucesso mas a tela não trouxe o "
                      "valor do frete."),
            )

        recusa = ler_recusa(html)
        if recusa:
            return ResultadoCotacao(
                self.slug, StatusCotacao.RECUSADO, raw_response=html[-2000:],
                motivo_recusa=f"A Braspress não cotou: {recusa}")

        return ResultadoCotacao(
            self.slug, StatusCotacao.ERRO, raw_response=html[-2000:],
            erro="A tela não trouxe nem confirmação de sucesso nem recusa "
                 "reconhecível depois de Calcular.")

    # --------------------------------------------------------- mecânica
    def _entrar(self, page) -> None:
        page.goto(URL_LOGIN, wait_until="domcontentloaded")
        page.wait_for_selector('input[name="login"]')
        page.wait_for_timeout(1_200)
        page.locator('input[name="login"]').first.fill(self.usuario)
        page.locator('input[name="pass"]').first.fill(self.senha)
        page.get_by_role("button", name="Acessar").first.click()
        page.wait_for_timeout(3_500)
        # Sem redirect de URL para esperar (o login fica na mesma view) —
        # confere pelo campo de senha ter sumido da tela.
        if page.locator('input[name="pass"]').count() and \
                page.locator('input[name="pass"]').first.is_visible():
            _falhar_login(page)

    @staticmethod
    def _fechar_popup_comunica(page) -> None:
        """"Braspress Comunica" é só marketing (pede XML de NF-e por
        e-mail), mas cobre o formulário inteiro e trava clique/digitação até
        ser fechado. Aparece toda vez que /cotacao/view abre."""
        fechar = page.get_by_role("button", name="Fechar")
        if fechar.count() and fechar.first.is_visible():
            fechar.first.click()
            page.wait_for_timeout(500)

    def _digitar(self, page, seletor: str, valor: str) -> None:
        campo = page.locator(seletor)
        campo.click()
        campo.fill("")
        page.wait_for_timeout(120)
        campo.type(valor, delay=DELAY_DIGITACAO_MS)
        page.wait_for_timeout(200)

    def _preencher_lado_livre(self, req: CotacaoRequest, page,
                              cnpj: str) -> str:
        """Digita o CNPJ do lado livre e espera a Braspress resolver o
        endereço sozinha. Devolve o endereço achado ("" se não achou)."""
        campo_id = ("#cnpjDestinatario" if req.tipo_frete is TipoFrete.CIF
                    else "#cnpjRemetente")
        self._digitar(page, campo_id, cnpj)
        page.locator(campo_id).blur()
        page.wait_for_timeout(ESPERA_BUSCA_MS)

        for _ in range(6):
            endereco = page.locator("#endereco").input_value().strip()
            if endereco:
                return endereco
            page.wait_for_timeout(700)
        return ""

    def _preencher_carga(self, page, c: dict[str, Any]) -> list[str]:
        """Preenche peso, valor da NF e uma linha de cubagem por volume da
        ficha — clicando "+" (#btnAdd) para cada linha além da primeira.
        Devolve divergências encontradas ao conferir de volta."""
        self._digitar(page, "#peso", c["peso"])
        self._digitar(page, "#vlrMercadoria", c["vlrMercadoria"])

        for i, linha in enumerate(c["cubagem"]):
            if i > 0:
                page.locator("#btnAdd").click()
                page.wait_for_timeout(600)
            for sufixo in ("comprimento", "largura", "altura", "volumes"):
                self._digitar(page, f"#{campo_cubagem(i, sufixo)}",
                              linha[sufixo])

        if c.get("altEmail"):
            self._digitar(page, "#altEmail", c["altEmail"])

        so_digitos = lambda s: "".join(ch for ch in s if ch.isdigit())
        problemas = []
        for seletor, esperado in (
                ("#peso", c["peso"]), ("#vlrMercadoria", c["vlrMercadoria"])):
            obtido = page.locator(seletor).input_value()
            if so_digitos(obtido) != so_digitos(esperado):
                problemas.append(
                    f"{seletor}: mandei {esperado!r}, campo tem {obtido!r}")
        return problemas

    def cotar(self, req: CotacaoRequest, *,
              confirmar_envio: bool = False) -> ResultadoCotacao:
        """confirmar_envio=False faz DRY-RUN: loga, preenche tudo, printa e
        PARA antes de "Calcular". Igual à Camilo, "Calcular" aqui é cálculo
        automático (não entra em fila de vendedor nem cria registro na conta
        da Ventura) — mas o default continua sendo dry-run até isso ser
        confirmado contra o site de verdade."""
        erros = [e for e in self.validar(req)
                if e.severidade is Severidade.ERRO]
        if erros:
            return recusa_por_validacao(self.slug, erros)

        if not (self.usuario and self.senha):
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO,
                erro="Faltam BRASPRESS_USUARIO e BRASPRESS_SENHA no .env.")

        from playwright.sync_api import sync_playwright

        c = self.preparar_payload(req)
        run = self.workdir / datetime.now().strftime("%Y%m%d-%H%M%S")
        run.mkdir(parents=True, exist_ok=True)
        enviado = datetime.now()
        evidencias: list[str] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(**self.opcoes_do_navegador())
            page = browser.new_context(
                locale="pt-BR",
                viewport={"width": 1500, "height": 1300}).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                self._entrar(page)

                page.goto(URL_COTACAO, wait_until="domcontentloaded")
                page.wait_for_selector("#tipoFrete")
                page.wait_for_timeout(1_500)
                self._fechar_popup_comunica(page)

                page.locator("#tipoFrete").select_option(
                    value=c["tipoFrete"])
                page.wait_for_timeout(1_500)   # o site preenche o lado travado

                endereco = self._preencher_lado_livre(
                    req, page, c["cnpjLivre"])
                if not endereco:
                    evidencias += print_seguro(
                        page, run / "sem_endereco.png")
                    return ResultadoCotacao(
                        self.slug, StatusCotacao.ERRO, enviado_em=enviado,
                        erro=f"A Braspress não trouxe endereço para o CNPJ "
                             f"{c['cnpjLivre']}; sem isso a cotação não tem "
                             f"a outra ponta da carga.",
                        evidencias=evidencias)

                avisos = self._preencher_carga(page, c)
                page.wait_for_timeout(800)
                evidencias += print_seguro(page, run / "preenchido.png")

                if not confirmar_envio:
                    return ResultadoCotacao(
                        self.slug, StatusCotacao.RASCUNHO, enviado_em=enviado,
                        raw_response="DRY-RUN: formulário preenchido, nada "
                                     "calculado.",
                        erro="; ".join(avisos) if avisos else None,
                        evidencias=evidencias)

                page.locator("#btnCalcular").click()
                page.wait_for_timeout(6_000)
                evidencias += print_seguro(page, run / "resultado.png")
                (run / "resultado.html").write_text(
                    page.content(), encoding="utf-8")

                res = self.normalizar_resposta(page.content())
                res.enviado_em = enviado
                res.respondido_em = datetime.now()
                res.evidencias = evidencias
                if avisos and not res.erro:
                    res.erro = "; ".join(avisos)
                return res

            except Exception as exc:
                return erro_do_adapter(
                    self.slug, exc, enviado_em=enviado,
                    evidencias=evidencias
                    + print_seguro(page, run / "erro.png"))
            finally:
                browser.close()
