"""Jadlog — calculadora do PAINEL, com login.

    https://jadlogentregas.com.br/login -> /painel -> /painel/calculadora

Substitui o simulador público (simulador.py), que a Jadlog descontinuou.

⚠ Este é o produto **Jadlog Entregas**: etiqueta pré-paga, pacote a pacote,
para e-commerce. O preço é de varejo, NÃO o frete fracionado contratado. Tem
saldo, créditos e limite de envios na conta.

⚠ A calculadora cota UM pacote. A ficha do Enzo pode ter N volumes iguais, e
a regra combinada é: N cálculos separados, um por volume. Somar os N dá o
total; cada resultado vem com o próprio print.

Credenciais no .env (JADLOG_PAINEL_USUARIO / JADLOG_PAINEL_SENHA). Nunca são
impressas nem gravadas nas evidências.

A ordem dos campos de medida é **Altura, Largura, Comprimento** — diferente do
simulador antigo (Larg., Altura, Comprimento). Os campos não têm name nem id,
então o casamento é pelo rótulo, nunca por posição.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao, print_seguro,
    CredencialRecusada, erro_do_adapter, recusa_por_validacao,
)
from carriers.jadlog import mapping as m
from core.models import CotacaoRequest, StatusCotacao, limpa_doc

URL_LOGIN = "https://jadlogentregas.com.br/login"
URL_CALCULADORA = "https://jadlogentregas.com.br/painel/calculadora"

# Login (ver _preencher_login): o site é um SPA React e pode terminar de montar
# DEPOIS do preenchimento, apagando o que foi digitado.
TENTATIVAS_PREENCHIMENTO = 4     # cobre a hidratação chegando atrasada
ESPERA_HIDRATACAO_MS = 800       # tempo para o React re-renderizar por cima
CONFIRMACOES_SEGUIDAS = 3        # 3 x 800ms = 2,4s de campo intacto
TENTATIVAS_LOGIN = 3
# Se não entrou em 15s, não vai entrar: os 45s antigos queimavam a cotação
# inteira numa espera que já estava perdida, sem sobrar tempo para tentar outra
# vez. Confirmado em 28/08/2026 com as credenciais reais: o login que dá certo
# termina em 1s, e o que trava fica ≥90s — não existe caso no meio.
TIMEOUT_LOGIN_MS = 15_000

# A chamada que autentica de verdade, achada no tráfego em 28/08/2026:
#   POST https://apigwjadlogentregas.azure-api.net/api/Usuario/LoginJWT
#        -> 200 {"token": "eyJ..."}
# O fragmento basta, e não amarra o teste ao domínio da API.
API_LOGIN = "Usuario/LoginJWT"

# Os únicos status que PROVAM senha recusada. Qualquer outra coisa — inclusive
# não haver resposta nenhuma — é falha nossa, de rede ou do site, e repetir
# pode resolver.
#
# A lista é curta de propósito. Chutar para o lado da recusa foi o defeito da
# #56: transforma um tropeço passageiro em "avise quem cuida do Cotafrete" e
# ainda desliga a retentativa, que era o que salvaria a cotação.
STATUS_CREDENCIAL_RECUSADA = (401, 403)

# Rótulo exato ao lado de cada campo, medido no recon de 13/08/2026.
ROTULO_ALTURA = "Altura (cm)"
ROTULO_LARGURA = "Largura (cm)"
ROTULO_COMPRIMENTO = "Comprimento (cm)"

RE_VALOR = re.compile(r"R\$\s*([\d.]+,\d{2}|\d+,\d{2})")


@dataclass
class Opcao:
    """Uma linha da tabela de resultado."""
    modalidade: str
    prazo: str
    valor: Decimal


def _num_br(txt: str) -> Decimal | None:
    t = txt.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except Exception:
        return None


def ler_opcoes(texto: str) -> list[Opcao]:
    """Tabela de resultado -> lista de opções.

    Formato medido: uma linha por modalidade, com transportadora, modalidade,
    balcão, prazo, valor e o botão Comprar. Ex.:
        jadlog  Express   2-3 dias   R$ 55,12   Comprar
        jadlog  Standard  3-4 dias   R$ 33,56   Comprar
    """
    opcoes: list[Opcao] = []
    for linha in texto.splitlines():
        achado = RE_VALOR.search(linha)
        if not achado:
            continue
        valor = _num_br(achado.group(1))
        if valor is None:
            continue

        # Uma linha de opção tem prazo E botão Comprar. O cabeçalho traz
        # "Valor do Produto: R$ 586,77" — sem isso ele virava a opção mais
        # barata e a cotação devolvia o valor da MERCADORIA como frete.
        prazo_achado = re.search(r"(\d+\s*-\s*\d+\s*dias?|\d+\s*dias?)", linha)
        if not prazo_achado and "comprar" not in linha.lower():
            continue

        antes = linha[:achado.start()]
        prazo = ""
        if p := re.search(r"(\d+\s*-\s*\d+\s*dias?|\d+\s*dias?)", antes):
            prazo = p.group(1).strip()
            antes = antes[:p.start()]
        modalidade = " ".join(antes.replace("jadlog", "").split())
        opcoes.append(Opcao(modalidade=modalidade or "?", prazo=prazo,
                            valor=valor))
    return opcoes


class JadlogPainelAdapter:
    slug = "jadlog_painel"
    nome = "Jadlog Entregas (calculadora do painel)"
    modo: Modo = Modo.SINCRONO
    ativo = True
    fator_cubagem: Decimal = m.FATOR_CUBAGEM
    sla_esperado_min: int | None = None

    def __init__(self, headless: bool = True, timeout_ms: int = 45_000,
                 workdir: str = "teste_real/jadlog") -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.workdir = Path(workdir)

    # ------------------------------------------------ delegações à camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return m.campos_obrigatorios(req)

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        return m.validar(req)

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        """Campos da calculadora — peso de UM volume, não o total.

        A calculadora cota um pacote de cada vez; a soma dos N volumes é feita
        por quem chama, com N chamadas. Mandar o peso total aqui cotaria uma
        caixa pesada com as medidas de uma caixa só."""
        v = req.volumes[0]
        return {
            "cep_origem": limpa_doc(req.origem.cep or ""),
            "cep_destino": limpa_doc(req.destino.cep or ""),
            "valor": f"{req.nota_fiscal.valor_total:.2f}".replace(".", ","),
            # SEMPRE 2 casas: o campo tem máscara de 2 decimais preenchida da
            # direita para a esquerda. Medido em 13/08/2026: "1" vira 0,01 e
            # "0,5" vira 0,05 — um centésimo/décimo da carga, cotado barato e
            # sem nenhum aviso na tela. Só "1,00" produz 1,00.
            "peso": f"{v.peso_kg:.2f}".replace(".", ","),
            ROTULO_ALTURA: f"{v.altura_cm.normalize():f}",
            ROTULO_LARGURA: f"{v.largura_cm.normalize():f}",
            ROTULO_COMPRIMENTO: f"{v.comprimento_cm.normalize():f}",
        }

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        """`raw` é o texto da tela de resultado."""
        texto = str(raw or "")
        opcoes = ler_opcoes(texto)
        if not opcoes:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO, raw_response=texto[:800],
                erro="Calculadora não devolveu nenhuma opção com valor.")

        barata = min(opcoes, key=lambda o: o.valor)
        return ResultadoCotacao(
            transportadora=self.slug,
            status=StatusCotacao.COTADO,
            valor_frete=barata.valor,
            prazo_dias=None,          # o painel dá faixa ("2-3 dias"), não número
            raw_response=texto[:800],
        )

    # ------------------------------------------------------------- mecânica
    def _credenciais(self) -> tuple[str, str]:
        usuario = os.getenv("JADLOG_PAINEL_USUARIO")
        senha = os.getenv("JADLOG_PAINEL_SENHA")
        if not usuario or not senha:
            raise RuntimeError(
                "Faltam JADLOG_PAINEL_USUARIO / JADLOG_PAINEL_SENHA no .env")
        return usuario, senha

    def _fechar_cookies(self, page) -> None:
        """O banner de cookies fica POR CIMA do botão Calcular Envio."""
        for texto in ("Aceitar todos os cookies", "Rejeitar Todos"):
            try:
                alvo = page.get_by_text(texto, exact=False).first
                if alvo.count() and alvo.is_visible(timeout=1500):
                    alvo.click()
                    page.wait_for_timeout(600)
                    return
            except Exception:
                continue

    def _preencher_login(self, page, usuario: str, senha: str) -> None:
        """Preenche e CONFERE que o valor ficou — o site é um SPA React.

        Medido em 17/08/2026, na cotação #5: com a máquina carregada (Camilo e
        Jadlog cotando ao mesmo tempo) o React terminava de montar depois do
        preenchimento e re-renderizava os campos VAZIOS. O clique em "Entrar"
        não submetia nada e o adapter esperava 45s por uma navegação que nunca
        vinha.

        Dormir mais tempo não conserta: só empurra o problema para a próxima
        máquina lenta. Conferir o valor conserta, e sai assim que der certo."""
        campo_email = page.locator('input[type="email"]').first
        campo_senha = page.locator('input[type="password"]').first
        campo_email.wait_for(state="visible")

        def preenchido() -> bool:
            return bool(campo_email.input_value().strip()
                        and campo_senha.input_value())

        for _ in range(TENTATIVAS_PREENCHIMENTO):
            campo_email.fill(usuario)
            campo_senha.fill(senha)
            # Uma leitura só não serve: logo depois do fill o valor SEMPRE
            # está lá — quem apaga é a hidratação, que chega depois. Só
            # confirmações seguidas provam que ela já passou.
            for confirmacao in range(1, CONFIRMACOES_SEGUIDAS + 1):
                page.wait_for_timeout(ESPERA_HIDRATACAO_MS)
                if not preenchido():
                    break
                if confirmacao == CONFIRMACOES_SEGUIDAS:
                    return

        raise RuntimeError(
            "o formulário de login apagou o que foi digitado em "
            f"{TENTATIVAS_PREENCHIMENTO} tentativas — a página da Jadlog não "
            "terminou de carregar")

    def _entrar(self, page) -> None:
        usuario, senha = self._credenciais()

        # O status de API_LOGIN é a ÚNICA prova de que a senha foi recusada.
        # A tela não diz nada: no print da cotação #56 (28/08/2026) estão os
        # dois campos preenchidos, os dois com o ✓ verde de validação do
        # site, o botão com foco — e nenhuma mensagem de erro em lugar
        # nenhum. Sem ler isto aqui, só sobra adivinhar.
        autenticacao: list[int] = []

        def anotar(resposta) -> None:
            if API_LOGIN in resposta.url:
                autenticacao.append(resposta.status)

        page.on("response", anotar)
        page.goto(URL_LOGIN, wait_until="domcontentloaded")
        self._fechar_cookies(page)

        for _ in range(TENTATIVAS_LOGIN):
            self._preencher_login(page, usuario, senha)
            # O banner de cookies pode não existir ainda quando _fechar_cookies
            # roda lá em cima, logo após o goto — e aparecer só agora, durante
            # o preenchimento (medido em 18/08/2026: 3 cotações seguidas
            # ficaram presas no login com os campos preenchidos e validados e
            # o botão com foco, mas a tela não saía do lugar). Fechar de novo
            # bem antes do clique pega o banner tardio.
            self._fechar_cookies(page)
            page.get_by_role("button", name="Entrar").first.click()
            try:
                page.wait_for_url(lambda u: "/login" not in u,
                                  timeout=TIMEOUT_LOGIN_MS)
                page.wait_for_timeout(2500)
                return
            except PlaywrightTimeoutError:
                # Três casos, e só UM deles é senha errada. Confundi-los foi o
                # que fez a #56 mandar o vendedor conferir uma senha que
                # estava certa.
                status = autenticacao[-1] if autenticacao else None

                if status in STATUS_CREDENCIAL_RECUSADA:
                    # O site recebeu e disse não, com todas as letras. Só aqui
                    # repetir martela a conta da Ventura.
                    raise CredencialRecusada(
                        f"a Jadlog recusou as credenciais (HTTP {status}). "
                        "Repetir não resolve e ainda arrisca bloquear a conta. "
                        f"Confira o login entrando à mão em {URL_LOGIN}.")

                if status is not None:
                    # Autenticou e o painel não abriu. É falha passageira, e
                    # medida: em 28/08/2026 uma tentativa ficou 90s presa e a
                    # seguinte entrou em 1s. Repetir é exatamente o certo.
                    raise RuntimeError(
                        f"a Jadlog autenticou (HTTP {status}) mas o painel não "
                        f"abriu em {TIMEOUT_LOGIN_MS // 1000}s. A senha está "
                        "certa; o site não saiu da tela de login.")

                # Nenhuma resposta de autenticação: o formulário nem chegou a
                # ser enviado. É o caso que a docstring de CredencialRecusada
                # manda repetir, e o laço faz isso.

        raise RuntimeError(
            f"não foi possível entrar no painel da Jadlog em {TENTATIVAS_LOGIN} "
            "tentativas — o clique em Entrar não chegou a enviar o formulário")

    def _campo_por_rotulo(self, page, rotulo: str):
        """Os campos não têm name nem id — só o rótulo os distingue.

        Casar por posição seria frágil de um jeito perigoso: a ordem aqui é
        Altura, Largura, Comprimento, ao contrário do simulador antigo. Trocar
        altura com largura numa caixa 80x60x50 muda a cubagem e o preço."""
        rotulos = page.get_by_text(rotulo, exact=False)
        for i in range(min(rotulos.count(), 5)):
            bloco = rotulos.nth(i).locator(
                "xpath=ancestor::*[self::div or self::label][1]")
            campo = bloco.locator("input").first
            if campo.count() and campo.is_visible():
                return campo
        raise RuntimeError(f"campo não encontrado pelo rótulo: {rotulo!r}")

    def _preencher(self, page, campos: dict[str, str]) -> None:
        page.get_by_placeholder("Digite o CEP de Origem").first.fill(
            campos["cep_origem"])
        page.get_by_placeholder("Digite o CEP de Destino").first.fill(
            campos["cep_destino"])

        for rotulo in (ROTULO_ALTURA, ROTULO_LARGURA, ROTULO_COMPRIMENTO):
            self._campo_por_rotulo(page, rotulo).fill(campos[rotulo])

        # valor e peso não têm placeholder; vêm com "0,00" e sufixo R$ / kg
        for sufixo, chave in (("R$", "valor"), ("kg", "peso")):
            self._campo_por_rotulo(page, sufixo).fill(campos[chave])

    def _print_resultado(self, page, destino: Path) -> list[str]:
        """Recorta os dois blocos que importam: Dados do Envio e Custo de Envio.

        A tela cheia traz menu lateral, saldo da conta, banner de cookies e
        rodapé — ruído que rouba a atenção do preço. Este print vai para o
        funcionário e para o cliente."""
        try:
            caixa = page.evaluate("""() => {
                const titulos = [...document.querySelectorAll('*')]
                    .filter(e => e.children.length === 0);
                const achar = (re) => titulos.find(e => re.test(e.textContent || ''));
                const topo = achar(/Dados do Envio/i);
                const base = achar(/levar a encomenda|Voltar/i);
                if (!topo || !base) return null;
                const a = topo.getBoundingClientRect();
                const b = base.getBoundingClientRect();
                // largura: até o botão Comprar, à direita da tabela
                let dir = a.right;
                for (const e of titulos) {
                    const r = e.getBoundingClientRect();
                    if (r.width && r.top >= a.top - 30 && r.bottom <= b.bottom + 30)
                        dir = Math.max(dir, r.right);
                }
                const x = Math.max(0, a.left - 20);
                return {x, y: Math.max(0, a.top - 30),
                        width: Math.min(dir - x + 30, window.innerWidth - x),
                        height: b.bottom - a.top + 60};
            }""")
            if caixa and caixa["height"] > 100 and caixa["width"] > 100:
                page.screenshot(path=str(destino), clip=caixa, timeout=10_000)
                return [str(destino)]
        except Exception:
            pass
        return print_seguro(page, destino)

    # ------------------------------------------------------------------ envio
    def cotar(self, req: CotacaoRequest) -> ResultadoCotacao:
        from playwright.sync_api import sync_playwright

        erros = m.bloqueantes(self.validar(req))
        if erros:
            return recusa_por_validacao(self.slug, erros)

        campos = self.preparar_payload(req)
        run = self.workdir / datetime.now().strftime("%Y%m%d-%H%M%S")
        run.mkdir(parents=True, exist_ok=True)
        enviado = datetime.now()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_context(
                locale="pt-BR",
                viewport={"width": 1500, "height": 1200}).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                self._entrar(page)
                page.goto(URL_CALCULADORA, wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
                if "/login" in page.url:
                    raise RuntimeError("sessão não persistiu até a calculadora")
                self._fechar_cookies(page)

                self._preencher(page, campos)
                page.get_by_role("button", name="Calcular Envio").first.click()

                # a tabela de opções só aparece depois do cálculo
                page.wait_for_function(
                    """() => /R\\$\\s*[\\d.,]+/.test(document.body.innerText)
                             && /comprar/i.test(document.body.innerText)""",
                    timeout=self.timeout_ms)
                page.wait_for_timeout(1200)

                texto = page.locator("body").inner_text()
                res = self.normalizar_resposta(texto)
                res.enviado_em = enviado
                res.respondido_em = datetime.now()
                res.evidencias = self._print_resultado(
                    page, run / "jadlog_resultado.png")
                return res

            except Exception as exc:
                return erro_do_adapter(
                    self.slug, exc, enviado_em=enviado,
                    evidencias=print_seguro(page, run / "jadlog_erro.png"))
            finally:
                browser.close()
