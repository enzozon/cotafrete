"""O PDF de proposta da Della Volpe, lido. Camada PURA.

Recebe TEXTO, não bytes: quem extrai o texto do PDF é quem tem o arquivo na
mão (o ingestor), e separar as duas coisas é o que permite testar a parte
arriscada — esta — com uma fixture de 2 KB em vez de um PDF de 1,7 MB.

O ERRO CARO mora aqui. O PDF traz DOIS valores:

    FRETE: R$167,63
    AD-VALOREM: R$0,02 ... TAXA DE EMISSÂO CTE: R$15,00 ... ICMS R$13,75
    VALOR TOTAL DO FRETE: R$196,40

O primeiro é o frete antes das taxas; o segundo é o que a Ventura paga. Ler o
primeiro mostraria a Della Volpe 17% mais barata do que ela é — e como a tela
dá o selo de MAIS BARATO ao menor número, ela ganharia a comparação com um
preço que não existe. As outras já mostram preço com taxas e ICMS, então o
total é o único número comparável.

Por isso NADA aqui casa "o primeiro R$ que aparecer". Cada campo tem âncora
no rótulo inteiro, e rótulo que muda vira None — nunca um número vizinho.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")

# "VALOR TOTAL DO FRETE: R$196,40". O rótulo INTEIRO porque "FRETE:" sozinho
# casaria com o valor errado oito linhas acima.
RE_VALOR_TOTAL = re.compile(
    r"VALOR\s+TOTAL\s+DO\s+FRETE\s*:?\s*R\$\s*([\d.]*\d,\d{2})", re.IGNORECASE)

# "Proposta n.º 15626/26"
RE_NUMERO = re.compile(r"Proposta\s+n\.?[ºo°]?\s*(\d+/\d+)", re.IGNORECASE)

# "PREVISÂO DE ENTREGA: 6 Dias úteis" — o texto é normalizado antes de casar,
# então o circunflexo do PDF não atrapalha.
RE_PRAZO = re.compile(r"PREVISAO\s+DE\s+ENTREGA\s*:?\s*(\d+)", re.IGNORECASE)

# "Validade da proposta: 7 dias"
RE_VALIDADE = re.compile(r"Validade\s+da\s+proposta\s*:?\s*(\d+)\s*dias?",
                         re.IGNORECASE)

# "São Paulo, 22 de setembro de 2026"
RE_DATA = re.compile(r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})",
                     re.IGNORECASE)

# "A/C: ENZO ZON (COT. 208)" — o carimbo que o Cotafrete põe no campo "Nome
# completo" do formulário e que a Della Volpe devolve em maiúsculas.
RE_DESTINATARIO = re.compile(r"A/C\s*:\s*(.+)")
RE_CARIMBO = re.compile(r"\(\s*COT\.?\s*(\d+)\s*\)", re.IGNORECASE)

# "ORIGEM: BELO HORIZONTE/MG" e "DESTINO: VILA VELHA/ES". Servem de CONFERÊNCIA
# do carimbo: se o número da cotação vier trocado (digitado de novo do lado
# de lá, ou um carimbo velho num nome reaproveitado), a rota não bate e o
# preço não vai parar na cotação de outra pessoa.
RE_ORIGEM = re.compile(r"ORIGEM\s*:\s*([^\n]+?)\s*/\s*([A-Z]{2})\b")
RE_DESTINO = re.compile(r"DESTINO\s*:\s*([^\n]+?)\s*/\s*([A-Z]{2})\b")


class Proposta(NamedTuple):
    """Tudo None quando não deu para ler. Nunca um chute.

    A tela sabe desenhar "sem preço"; o que ela não sabe é desconfiar de um
    número que parece certo."""

    valor: Decimal | None = None
    numero: str | None = None
    prazo_dias: int | None = None
    emitida_em: date | None = None
    validade: date | None = None
    destinatario: str = ""
    cotacao_id: int | None = None
    # "BELO HORIZONTE/MG": cidade como a Della Volpe escreveu, e a UF.
    origem: str = ""
    uf_origem: str | None = None
    destino: str = ""
    uf_destino: str | None = None


def _sem_acento(texto: str) -> str:
    """PREVISÂO, PREVISÃO e PREVISAO viram a mesma coisa.

    O PDF escreve "PREVISÂO" e "EMISSÂO" com circunflexo — erro de digitação
    deles, congelado no documento. Apostar na grafia certa deixaria o prazo em
    branco para sempre; apostar na errada quebraria no dia em que
    corrigissem."""
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def _dinheiro(bruto: str) -> Decimal | None:
    """'1.196,40' -> Decimal('1196.40'). Ponto é milhar, vírgula é decimal."""
    try:
        return Decimal(bruto.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def _data_por_extenso(texto: str) -> date | None:
    achado = RE_DATA.search(texto)
    if not achado:
        return None
    dia, mes, ano = achado.groups()
    alvo = _sem_acento(mes.lower())
    for numero, nome in enumerate(MESES, start=1):
        if _sem_acento(nome) == alvo:
            try:
                return date(int(ano), numero, int(dia))
            except ValueError:
                return None
    return None


def ler_proposta(texto: str) -> Proposta:
    """Lê o que interessa do PDF. Nunca levanta.

    O ingestor roda em segundo plano: uma exceção aqui mataria a thread e o
    PDF seguinte nunca seria lido."""
    texto = texto or ""
    plano = _sem_acento(texto)

    valor = RE_VALOR_TOTAL.search(plano)
    numero = RE_NUMERO.search(plano)
    prazo = RE_PRAZO.search(plano)
    validade_dias = RE_VALIDADE.search(plano)
    emitida = _data_por_extenso(texto)

    # O destinatário sai do texto ORIGINAL, com acento: é nome de gente, e vai
    # para a tela como a Della Volpe escreveu.
    achado = RE_DESTINATARIO.search(texto)
    destinatario = achado.group(1).strip() if achado else ""
    carimbo = RE_CARIMBO.search(_sem_acento(destinatario))
    origem = RE_ORIGEM.search(texto)
    destino = RE_DESTINO.search(texto)

    return Proposta(
        valor=_dinheiro(valor.group(1)) if valor else None,
        numero=numero.group(1) if numero else None,
        prazo_dias=int(prazo.group(1)) if prazo else None,
        emitida_em=emitida,
        # Validade só existe se as DUAS pontas existirem: "7 dias" sem a data
        # do documento não é data nenhuma, e contar a partir de hoje daria uma
        # validade nova a cada vez que o PDF fosse relido.
        validade=(emitida + timedelta(days=int(validade_dias.group(1)))
                  if emitida and validade_dias else None),
        destinatario=destinatario,
        cotacao_id=int(carimbo.group(1)) if carimbo else None,
        origem=f"{origem.group(1).strip()}/{origem.group(2)}" if origem else "",
        uf_origem=origem.group(2) if origem else None,
        destino=(f"{destino.group(1).strip()}/{destino.group(2)}"
                 if destino else ""),
        uf_destino=destino.group(2) if destino else None,
    )
