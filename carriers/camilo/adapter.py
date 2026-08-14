"""Camilo dos Santos — cotação pelo SSW, com login.

    https://sistema.ssw.inf.br/bin/ssw0422   login
    https://sistema.ssw.inf.br/bin/ssw1608   110 - Cotação de Fretes pelo Cliente

O SSW é plataforma compartilhada; o domínio da Camilo dos Santos é RCS. Credenciais
no .env (SSW_DOMINIO / SSW_CPF / SSW_USUARIO / SSW_SENHA), nunca impressas.

Esta é a única das quatro que devolve o preço NA HORA com a composição inteira
(frete peso, GRIS, pedágio, TAS, ICMS...). Della Volpe e Generoso só confirmam
recebimento; a Jadlog dá preço mas é etiqueta de varejo.

⚠ A CUBAGEM É EM METROS. O popup diz "Dimensões em metros": uma caixa de 30 cm
vai como 0,300. Mandar 30 cotaria 30 metros — e ao contrário das outras
armadilhas do projeto (Della Volpe 10x menor, Jadlog 100x menor), esta erra
para MAIS. Frete absurdo em vez de frete barato.

Medido no recon de 14/08/2026:
- login é AJAX (`<a id="5" onclick="ajaxEnvia('L',0)">`); Enter não submete
- depois de logar, dá para ir DIRETO ao ssw1608, sem passar pelo menu
- a cubagem abre num popup com 20 linhas (cub_alt_1..20 etc.), o que permite
  cotar 80 volumes de dois tamanhos numa cotação só
- os campos não têm <label>: o casamento é por `name`
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao, print_seguro,
)
from core.models import CotacaoRequest, StatusCotacao, limpa_doc

URL_LOGIN = "https://sistema.ssw.inf.br/bin/ssw0422"
URL_COTACAO = "https://sistema.ssw.inf.br/bin/ssw1608"

FRETE_CIF = "1"     # paga o remetente
FRETE_FOB = "2"     # paga o destinatário

# O popup de cubagem tem exatamente 20 linhas.
MAX_LINHAS_CUBAGEM = 20

CM_POR_METRO = Decimal(100)


def _metros(cm: Decimal) -> str:
    """Centímetros -> metros com 3 casas, vírgula decimal.

    3 casas porque é o que o site mostra (0,300) e o menor passo útil: 1 cm."""
    return f"{cm / CM_POR_METRO:.3f}".replace(".", ",")


def _num_br(valor: str) -> Decimal | None:
    t = (valor or "").strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(t) if t else None
    except Exception:
        return None


def ler_resultado(campos: dict[str, str]) -> tuple[Decimal | None, str]:
    """(valor do frete, número da cotação) a partir dos campos da tela."""
    return (_num_br(campos.get("vlr_frete", "")),
            (campos.get("nro_cotacao") or "").strip())


class CamiloAdapter:
    slug = "camilo"
    nome = "Camilo dos Santos (SSW)"
    modo: Modo = Modo.SINCRONO          # devolve preço na hora
    ativo = True
    fator_cubagem: Decimal = Decimal(300)   # ⚠ presumido; o site calcula sozinho
    sla_esperado_min: int | None = None

    def __init__(self, headless: bool = True, timeout_ms: int = 45_000,
                 workdir: str = "teste_real/camilo",
                 tipo_frete: str = FRETE_FOB) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.workdir = Path(workdir)
        self.tipo_frete = tipo_frete

    # ------------------------------------------------------- camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return [
            CampoSpec("CNPJ pagador", True, "text"),
            CampoSpec("CEP de origem", True, "text"),
            CampoSpec("CEP de destino", True, "text"),
            CampoSpec("Valor da NF", True, "text"),
            CampoSpec("Peso", True, "text"),
            CampoSpec("Quantidade de volumes", True, "text"),
            CampoSpec("Cubagem", True, "text"),
        ]

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        erros: list[ErroValidacao] = []
        if not limpa_doc(req.origem.cep or ""):
            erros.append(ErroValidacao("cep_origem",
                                       "CEP de origem é obrigatório."))
        if not limpa_doc(req.destino.cep or ""):
            erros.append(ErroValidacao("cep_destino",
                                       "CEP de destino é obrigatório."))
        if req.peso_total_kg <= 0:
            erros.append(ErroValidacao("peso",
                                       "Peso precisa ser maior que zero."))
        if len(req.volumes) > MAX_LINHAS_CUBAGEM:
            erros.append(ErroValidacao(
                "volumes",
                f"O popup de cubagem tem {MAX_LINHAS_CUBAGEM} linhas e a carga "
                f"tem {len(req.volumes)} tamanhos distintos."))
        return erros

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        if len(req.volumes) > MAX_LINHAS_CUBAGEM:
            raise ValueError(
                f"O popup de cubagem do SSW tem {MAX_LINHAS_CUBAGEM} linhas; "
                f"a carga tem {len(req.volumes)} tamanhos distintos. "
                f"Divida em mais de uma cotação.")

        campos: dict[str, Any] = {
            "cgc_pag": limpa_doc(req.pagador_frete.cnpj),
            "cep_origem": limpa_doc(req.origem.cep or ""),
            "cep_destino": limpa_doc(req.destino.cep or ""),
            "tp_frete": self.tipo_frete,
            "vlr_merc": f"{req.nota_fiscal.valor_total:.2f}".replace(".", ","),
            "peso": f"{req.peso_total_kg:.3f}".replace(".", ","),
            "qtde_vol": str(req.quantidade_volumes),
            # confirmados pelo Enzo em 14/08/2026; são os defaults do site
            "coletar": "S",
            "contribuinte": "S",
            "ent_dif": "N",
            # opcionais que ele não preenche à mão — ficam vazios de propósito
            "chave_nfe": "",
            "tp_merc": "",
            "cgc_rem": "",
            "cgc_dest": "",
            "qtde_pares": "",
        }

        # Uma linha do popup por TAMANHO, não por volume: 40 caixas iguais são
        # uma linha com "vezes = 40".
        for i, v in enumerate(req.volumes, start=1):
            campos[f"cub_alt_{i}"] = _metros(v.altura_cm)
            campos[f"cub_larg_{i}"] = _metros(v.largura_cm)
            campos[f"cub_comp_{i}"] = _metros(v.comprimento_cm)
            campos[f"cub_nro_vezes_{i}"] = str(v.qtd)
        return campos

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        campos = raw if isinstance(raw, dict) else {}
        valor, protocolo = ler_resultado(campos)
        if valor is None:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO, raw_response=str(raw)[:800],
                erro="A tela não devolveu valor de frete.")
        return ResultadoCotacao(
            transportadora=self.slug,
            status=StatusCotacao.COTADO,
            valor_frete=valor,
            protocolo=protocolo or None,
            prazo_dias=None,   # a tela dá data de previsão, não número de dias
            raw_response=str(raw)[:800],
        )

    # --------------------------------------------------------- mecânica
    def _credenciais(self) -> dict[str, str]:
        valores = {
            "f1": os.getenv("SSW_DOMINIO", ""),
            "f2": os.getenv("SSW_CPF", ""),
            "f3": os.getenv("SSW_USUARIO", ""),
            "f4": os.getenv("SSW_SENHA", ""),
        }
        if not (valores["f1"] and valores["f3"] and valores["f4"]):
            raise RuntimeError(
                "Faltam SSW_DOMINIO / SSW_USUARIO / SSW_SENHA no .env")
        return valores

    def _entrar(self, page) -> None:
        page.goto(URL_LOGIN, wait_until="domcontentloaded")
        page.wait_for_selector('input[name="f1"]')
        page.wait_for_timeout(1_200)
        for nome, valor in self._credenciais().items():
            if valor:
                page.locator(f'input[name="{nome}"]').first.fill(valor)
                page.wait_for_timeout(150)
        # O envio é AJAX; Enter não submete. Medido no recon.
        page.locator('a[id="5"]').first.click()
        page.wait_for_timeout(4_000)

    @staticmethod
    def _preencher(page, campos: dict[str, Any], prefixo: str = "") -> None:
        for nome, valor in campos.items():
            if prefixo and not nome.startswith(prefixo):
                continue
            if not prefixo and nome.startswith("cub_"):
                continue          # cubagem só depois de abrir o popup
            alvo = page.locator(f'input[name="{nome}"]')
            if not alvo.count() or not str(valor):
                continue
            alvo.first.fill(str(valor))
            page.wait_for_timeout(120)

    def _conferir(self, page, campos: dict[str, Any]) -> list[str]:
        """Lê de volta. Campo com máscara devolve outra coisa — foi assim que
        o peso da Jadlog virou 0,01 e a medida da Della Volpe virou 3,0."""
        so_digitos = lambda s: "".join(c for c in str(s) if c.isdigit())
        problemas = []
        for nome, valor in campos.items():
            if not str(valor):
                continue
            alvo = page.locator(f'input[name="{nome}"]')
            if not alvo.count():
                continue
            obtido = alvo.first.input_value()
            if so_digitos(obtido) != so_digitos(valor):
                problemas.append(f"{nome}: mandei {valor!r}, campo tem {obtido!r}")
        return problemas

    @staticmethod
    def _fechar_aviso(page) -> None:
        """Fecha o "Operação realizada com sucesso".

        O aviso cobre a coluna do meio da tabela de custos — Frete Valor,
        Despacho, TDE, Pedágio ficam escondidos atrás dele. Sem fechar, o
        print sai com um buraco justo na composição do preço."""
        for seletor in ('a:has-text("OK")', 'text=/^\\s*\\d+\\.\\s*OK\\s*$/'):
            try:
                alvo = page.locator(seletor).first
                if alvo.count() and alvo.is_visible(timeout=1_500):
                    alvo.click()
                    page.wait_for_timeout(900)
                    return
            except Exception:
                continue

    def _print_resultado(self, page, destino: Path) -> list[str]:
        """Recorta a área útil: do topo até o valor do frete.

        A tela tem 1000px de branco embaixo. O funcionário e o cliente
        recebem esse print — sobra em branco só rouba a atenção do número."""
        try:
            caixa = page.evaluate("""() => {
                const folhas = [...document.querySelectorAll('*')]
                    .filter(e => e.children.length === 0);

                // LARGURA: só elementos ESTREITOS entram na conta. A linha
                // azul de separação e os contêineres ocupam a janela toda —
                // incluí-los fazia o recorte pegar 500px de branco à direita.
                let direita = 0;
                for (const e of folhas) {
                    const b = e.getBoundingClientRect();
                    const temTexto = (e.textContent || '').trim().length > 0;
                    if (b.width > 0 && b.width < 420 && (temTexto || e.tagName === 'INPUT'))
                        direita = Math.max(direita, b.right);
                }

                // ALTURA: até os botões ▶ ✕ do rodapé do formulário, que
                // ficam ABAIXO do valor do frete. Parar no valor cortava eles.
                const rodape = document.querySelector('a[id="lnk_simula"]')
                            || document.querySelector('a[id="lnk_fec"]');
                const fim = folhas.reverse().find(
                    e => /Valor do frete/i.test(e.textContent || ''));
                if (!fim && !rodape) return null;
                const base = Math.max(
                    rodape ? rodape.getBoundingClientRect().bottom : 0,
                    fim ? fim.getBoundingClientRect().bottom : 0);

                return {x: 0, y: 0,
                        width: Math.min(direita + 28, window.innerWidth),
                        height: base + 16};
            }""")
            if caixa and caixa["height"] > 100:
                page.screenshot(path=str(destino), clip=caixa, timeout=10_000)
                return [str(destino)]
        except Exception:
            pass
        return print_seguro(page, destino)

    def cotar(self, req: CotacaoRequest,
              *, confirmar_envio: bool = False) -> ResultadoCotacao:
        """confirmar_envio=False faz DRY-RUN: preenche tudo, printa e PARA
        antes de clicar em "simular"."""
        from playwright.sync_api import sync_playwright

        erros = self.validar(req)
        if erros:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO,
                erro="; ".join(f"{e.campo}: {e.mensagem}" for e in erros))

        campos = self.preparar_payload(req)
        run = self.workdir / datetime.now().strftime("%Y%m%d-%H%M%S")
        run.mkdir(parents=True, exist_ok=True)
        enviado = datetime.now()
        evidencias: list[str] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_context(
                locale="pt-BR",
                viewport={"width": 1500, "height": 1100}).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                self._entrar(page)

                # atalho medido no recon: dá para pular o menu
                page.goto(URL_COTACAO, wait_until="domcontentloaded")
                page.wait_for_selector('input[name="cgc_pag"]')
                page.wait_for_timeout(1_500)

                self._preencher(page, campos)
                page.wait_for_timeout(1_500)   # o site busca CNPJ e CEPs

                # cubagem fica num popup à parte
                page.locator('a[id="lnk_cubagem"]').first.click()
                page.wait_for_timeout(1_200)
                self._preencher(page, campos, prefixo="cub_")
                avisos = self._conferir(
                    page, {k: v for k, v in campos.items()
                           if k.startswith("cub_")})
                page.locator('a[id="cub_lnk_mais"]').first.click()
                page.wait_for_timeout(2_000)

                avisos += self._conferir(
                    page, {k: v for k, v in campos.items()
                           if not k.startswith("cub_")})
                evidencias += print_seguro(page, run / "preenchido.png")

                if not confirmar_envio:
                    return ResultadoCotacao(
                        self.slug, StatusCotacao.RASCUNHO, enviado_em=enviado,
                        raw_response="DRY-RUN: preenchido, nada simulado.",
                        erro="; ".join(avisos) if avisos else None,
                        evidencias=evidencias)

                page.locator('a[id="lnk_simula"]').first.click()
                page.wait_for_timeout(6_000)
                self._fechar_aviso(page)
                evidencias += self._print_resultado(page, run / "resultado.png")

                lidos = {
                    n: page.locator(f'input[name="{n}"]').first.input_value()
                    for n in ("vlr_frete", "nro_cotacao")
                    if page.locator(f'input[name="{n}"]').count()
                }
                res = self.normalizar_resposta(lidos)
                res.enviado_em = enviado
                res.respondido_em = datetime.now()
                res.evidencias = evidencias
                return res

            except Exception as exc:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.ERRO, enviado_em=enviado,
                    erro=f"{type(exc).__name__}: {exc}",
                    evidencias=evidencias
                    + print_seguro(page, run / "erro.png"))
            finally:
                browser.close()
