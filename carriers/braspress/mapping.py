"""Braspress — camada PURA. Zero Playwright, zero rede.

A conta da Ventura (CNPJ 08.310.365/0001-24) está SEMPRE de um lado da carga
no formulário de cotação — o site prende esse lado no CNPJ do login assim que
o campo "Tipo de Frete" é escolhido: CIF trava o remetente, FOB trava o
destinatário. O outro lado é digitado, e a Braspress resolve razão
social/CEP/endereço sozinha a partir do CNPJ (medido em 02/09/2026 com um CNPJ
público: só digitar já trouxe "MAGAZINE LUIZA S/A" e o endereço certo da
filial de Franca/SP).

Isso quer dizer que a cotação SEMPRE sai com o CNPJ da Ventura de um lado,
mesmo que a ficha tenha vindo com outro remetente/destinatário para aquele
lado — dali a mensagem fixa em NOTAS (web/app.py) avisando o vendedor.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from core.models import CotacaoRequest, TipoFrete, limpa_doc

SLUG = "braspress"
NOME = "Braspress"

# O CNPJ do login, que o site sempre amarra num dos lados da carga.
CNPJ_CONTA = "08310365000124"

TIPO_FRETE_CIF = "1"
TIPO_FRETE_FOB = "2"


def valor_tipo_frete(req: CotacaoRequest) -> str:
    return TIPO_FRETE_CIF if req.tipo_frete is TipoFrete.CIF else TIPO_FRETE_FOB


def cnpj_lado_livre(req: CotacaoRequest) -> str:
    """O CNPJ do lado que PRECISA ser digitado — o outro já vem travado no
    CNPJ da conta assim que o Tipo de Frete é escolhido.

    CIF trava o remetente -> o lado livre é o destinatário.
    FOB trava o destinatário -> o lado livre é o remetente."""
    parte = req.destinatario if req.tipo_frete is TipoFrete.CIF else req.remetente
    return limpa_doc(parte.cnpj)


def _digitos_2_casas(valor: Decimal) -> str:
    """Dinheiro/peso: o campo tem máscara que trata os dígitos digitados como
    centavos — type("125") -> "1,25". Medido em peso, vlrMercadoria e nas três
    dimensões da cubagem (02/09/2026, recon/recon_braspress.py)."""
    return str(int((valor * 100).to_integral_value()))


def peso_para_campo(peso_kg: Decimal) -> str:
    return _digitos_2_casas(peso_kg)


def valor_nf_para_campo(valor: Decimal) -> str:
    return _digitos_2_casas(valor)


def medida_para_campo(medida_cm: Decimal) -> str:
    """Comprimento/largura/altura: o campo mostra METROS com a mesma máscara
    de 2 casas dos campos de dinheiro. Como 1 m = 100 cm, o valor em
    CENTÍMETROS já é exatamente o que a máscara espera — type("120") -> "1,20"
    m, que é 120 cm. Não precisa converter, só arredondar pro inteiro."""
    return str(int(medida_cm.to_integral_value()))


def campo_cubagem(indice: int, sufixo: str) -> str:
    """id= do campo da N-ésima linha de cubagem (0-based). Cada linha extra
    nasce clicando #btnAdd — medido em 02/09/2026: os ids seguem
    cubagem{N}{sufixo} de forma previsível (cubagem0comprimento,
    cubagem1comprimento, ...), sem precisar reabrir popup nenhum."""
    return f"cubagem{indice}{sufixo}"


# --------------------------------------------------- leitura do resultado
#
# Medido no envio real de 02/09/2026 (cotação #373377732, CIF, Ventura ->
# Magazine Luiza): depois de clicar "Calcular" a Braspress NÃO navega para
# outra página — insere um bloco "Resultado da cotação" embaixo do próprio
# formulário, com uma caixa `.alert-success` e DUAS tabelas iguais (uma para
# desktop, uma para celular — "hidden-xs"/"visible-xs"). A tabela do celular
# tem rótulo e valor lado a lado, e é ESSA que os regex abaixo usam: é a
# única das duas onde o rótulo já vem junto do valor, então não depende de
# nenhuma ordem de colunas.
#
# ⚠ Recusa/erro NUNCA foi visto de verdade — só a cotação de sucesso. O
# padrão abaixo (`.alert-danger`) é um CHUTE educado a partir da convenção
# Bootstrap que o `.alert-success` já mostrou estar em uso no site, não uma
# medição. Precisa ser confirmado (ou corrigido) na primeira recusa real.
RE_VALOR_FRETE = re.compile(
    r"Valor Total Frete</td>\s*<td>\s*<span[^>]*>\s*([\d.,]+)\s*</span>",
    re.IGNORECASE)
RE_PROTOCOLO = re.compile(
    r"Protocolo da Cota[çc][ãa]o Online</td>\s*<td>\s*<span[^>]*>\s*(\d+)\s*"
    r"</span>", re.IGNORECASE)
RE_PRAZO_DIAS = re.compile(
    r"Dias\s*[uú]teis\s*/\s*Horas</td>\s*<td>\s*<span[^>]*>\s*(\d+)\s*</span>",
    re.IGNORECASE)
RE_DATA_ENTREGA = re.compile(
    r"Data Entrega Prevista</td>\s*<td>\s*<span[^>]*>\s*([\d/]+)\s*</span>",
    re.IGNORECASE)
RE_STATUS = re.compile(
    r">Status</td>\s*<td>\s*<span[^>]*>\s*([^<]+?)\s*</span>", re.IGNORECASE)
RE_SUCESSO = re.compile(r'alert-success', re.IGNORECASE)
RE_RECUSA_HTML = re.compile(
    r'alert-danger"[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL)
_TAG_HTML = re.compile(r"<[^>]+>")


def _dinheiro(bruto: str) -> Decimal | None:
    """'1.295,87' -> Decimal('1295.87'). Ponto é milhar, vírgula é decimal."""
    try:
        return Decimal(bruto.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


class ResultadoBraspress:
    """Só os campos que a tela de resultado dá — sem depender de
    ResultadoCotacao/StatusCotacao aqui, pra esta função continuar pura e
    testável sem o resto do projeto."""

    def __init__(self, valor_frete: Decimal | None, protocolo: str | None,
                prazo_dias: int | None, status: str | None):
        self.valor_frete = valor_frete
        self.protocolo = protocolo
        self.prazo_dias = prazo_dias
        self.status = status


def ler_sucesso(html: str) -> ResultadoBraspress | None:
    """None se a tela não tem o bloco de sucesso; os campos lidos dele
    quando tem — mesmo que algum venha faltando."""
    if not RE_SUCESSO.search(html or ""):
        return None
    valor = RE_VALOR_FRETE.search(html)
    protocolo = RE_PROTOCOLO.search(html)
    prazo = RE_PRAZO_DIAS.search(html)
    status = RE_STATUS.search(html)
    return ResultadoBraspress(
        valor_frete=_dinheiro(valor.group(1)) if valor else None,
        protocolo=protocolo.group(1) if protocolo else None,
        prazo_dias=int(prazo.group(1)) if prazo else None,
        status=status.group(1).strip() if status else None,
    )


def ler_recusa(html: str) -> str | None:
    """Texto da caixa de recusa, ou None. NÃO MEDIDO — ver aviso acima."""
    achado = RE_RECUSA_HTML.search(html or "")
    if not achado:
        return None
    texto = _TAG_HTML.sub(" ", achado.group(1))
    return " ".join(texto.split()) or None
