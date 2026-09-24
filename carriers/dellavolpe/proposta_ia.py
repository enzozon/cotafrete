"""Plano B da proposta da Della Volpe: a IA lê o PDF que o leitor não entendeu.

Pedido do usuário (24/09/2026): quando o PDF chega num formato que
`proposta.ler_proposta` não reconhece (rótulo trocado, carimbo escrito de
outro jeito), a proposta se perdia como "sem_valor". Agora a IA lê o texto
— mas a IA NÃO decide nada sozinha.

A trava contra alucinação é a mesma ideia do CNPJ em core/extrair_carga.py:
o que a IA diz só vale se o PDF provar. `conferir` (código, puro):

- valor: a IA tem de devolver o número E a linha de onde tirou. A linha tem
  de estar LITERALMENTE no PDF, conter o número, falar em "total" e não
  falar em nota fiscal/mercadoria. Isso barra os dois erros caros: o
  "FRETE: R$167,63" (antes das taxas, 17% mais barato que o real) e o valor
  da NF, que também tem "total" no nome;
- carimbo "(cot. N)": o PDF tem de trazer "COT" seguido de N;
- prazo, validade, número da proposta, UFs: cada um tem de aparecer no texto.

O que não passa vira None — e `ingestor.decidir` continua dizendo "não
grava" como sempre. Com o carimbo e as UFs conferidos, a regra de rota do
ingestor (UF do PDF × UF da cotação) segue valendo em cima do que a IA leu.

O leitor por regex continua mandando: campo que ele leu não é trocado pelo
da IA. A IA só preenche o que ficou em branco.

Liga/desliga: `LIGADA` (padrão: ligada; `DELLAVOLPE_IA=0` no .env desliga).
Os testes desligam isto — e só isto — em tests/conftest.py.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from carriers.dellavolpe.proposta import MESES, Proposta
from core import ia

LIGADA = os.getenv("DELLAVOLPE_IA", "1").strip() != "0"
FUNCAO = "proposta Della Volpe"
MAX_TEXTO = 12_000   # proposta real tem ~2.500 caracteres; folder anexado não precisa ir inteiro
UFS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
# linha do valor que parece total mas NÃO é o frete a pagar
PROIBIDO_NO_TRECHO = ("NOTA FISCAL", "MERCADORIA", "VALOR DA NF", "VALOR NF")

_TEXTO_OU_NULO = {"type": ["string", "null"]}
_INTEIRO_OU_NULO = {"type": ["integer", "null"]}
ESQUEMA = {
    "type": "object",
    "properties": {
        "valor_total_frete": _TEXTO_OU_NULO,
        "linha_do_valor": _TEXTO_OU_NULO,
        "numero_proposta": _TEXTO_OU_NULO,
        "prazo_entrega_dias": _INTEIRO_OU_NULO,
        "validade_dias": _INTEIRO_OU_NULO,
        "data_emissao": _TEXTO_OU_NULO,
        "cotacao_carimbo": _INTEIRO_OU_NULO,
        "destinatario": _TEXTO_OU_NULO,
        "uf_origem": _TEXTO_OU_NULO,
        "uf_destino": _TEXTO_OU_NULO,
    },
    "required": ["valor_total_frete", "linha_do_valor", "numero_proposta",
                 "prazo_entrega_dias", "validade_dias", "data_emissao",
                 "cotacao_carimbo", "destinatario", "uf_origem", "uf_destino"],
    "additionalProperties": False,
}

SISTEMA = """Você lê o texto de uma PROPOSTA DE FRETE da transportadora Della Volpe,
extraído de um PDF. Devolva só o que o texto diz. NUNCA invente, calcule ou
estime: campo que o texto não traz = null.

- valor_total_frete: o valor FINAL do frete a pagar, já com taxas e impostos
  (ICMS, ad-valorem, taxa de emissão). NÃO é o "FRETE:" antes das taxas e NÃO
  é o valor da nota fiscal/mercadoria. Copie como está no texto, ex. "196,40".
- linha_do_valor: a linha do texto de onde você tirou o valor, copiada
  EXATAMENTE (ex.: "VALOR TOTAL DO FRETE: R$196,40").
- numero_proposta: o número da proposta como está (ex.: "15626/26").
- prazo_entrega_dias: prazo/previsão de ENTREGA em dias (não o de coleta).
- validade_dias: validade da proposta em dias.
- data_emissao: data do documento, no formato AAAA-MM-DD.
- cotacao_carimbo: o número N de uma marca "(COT. N)" / "COT N" / "COTAÇÃO N",
  normalmente junto do nome no "A/C". Só o número.
- destinatario: o texto depois de "A/C:", como está.
- uf_origem / uf_destino: a sigla do estado de ORIGEM e de DESTINO."""


# ------------------------------------------------------------- conferência
def _plano(texto: str) -> str:
    """Maiúsculas, sem acento, espaços colapsados: o mesmo texto para os dois lados."""
    t = "".join(c for c in unicodedata.normalize("NFD", texto or "")
                if unicodedata.category(c) != "Mn")
    return " ".join(t.upper().split())


def _dinheiro(bruto) -> Decimal | None:
    t = str(bruto or "").upper().replace("R$", "").replace(" ", "").strip()
    if not re.fullmatch(r"\d{1,3}(\.\d{3})*,\d{2}|\d+,\d{2}|\d+(\.\d{1,2})?", t):
        return None
    try:
        return Decimal(t.replace(".", "").replace(",", ".") if "," in t else t)
    except InvalidOperation:
        return None


def _como_no_pdf(v: Decimal) -> list[str]:
    """196.40 → ["196,40"]; 1196.40 → ["1.196,40", "1196,40"]."""
    inteiro, centavos = f"{v:.2f}".split(".")
    com_ponto = f"{int(inteiro):,}".replace(",", ".")
    return list(dict.fromkeys([f"{com_ponto},{centavos}", f"{inteiro},{centavos}"]))


def _valor(bruto: dict, plano: str) -> Decimal | None:
    v = _dinheiro(bruto.get("valor_total_frete"))
    linha = _plano(bruto.get("linha_do_valor") or "")
    if v is None or v <= 0 or not linha or linha not in plano:
        return None
    if "TOTAL" not in linha or any(p in linha for p in PROIBIDO_NO_TRECHO):
        return None
    if not any(re.search(rf"(?<![\d.,]){re.escape(f)}(?!\d)", linha) for f in _como_no_pdf(v)):
        return None
    return v


def _carimbo(bruto: dict, plano: str) -> int | None:
    n = bruto.get("cotacao_carimbo")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        return None
    return n if re.search(rf"\bCOT[A-Z]*\.?\s*(N[.O°º]*\s*)?{n}\b", plano) else None


def _inteiro_perto(bruto: dict, chave: str, plano: str, palavras: tuple[str, ...],
                   teto: int) -> int | None:
    n = bruto.get(chave)
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= teto:
        return None
    # o número tem de aparecer a até ~40 caracteres de uma das palavras
    for p in palavras:
        if re.search(rf"{p}.{{0,40}}?(?<!\d){n}(?!\d)", plano):
            return n
    return None


def _data(bruto: dict, texto: str, plano: str) -> date | None:
    try:
        d = date.fromisoformat(str(bruto.get("data_emissao") or ""))
    except ValueError:
        return None
    extenso = _plano(f"{d.day} de {MESES[d.month - 1]} de {d.year}")
    numerica = (f"{d.day:02d}/{d.month:02d}/{d.year}", f"{d.day}/{d.month}/{d.year}")
    return d if extenso in plano or any(n in texto for n in numerica) else None


def _uf(bruto: dict, chave: str, rotulo: str, plano: str) -> str | None:
    uf = str(bruto.get(chave) or "").strip().upper()
    if uf not in UFS:
        return None
    return uf if re.search(rf"{rotulo}[^A-Z]{{0,4}}\S.{{0,60}}?[/\- ]{uf}\b", plano) else None


def conferir(bruto: dict, texto: str) -> Proposta:
    """Resposta da IA → Proposta só com o que o PDF prova. Puro, nunca levanta."""
    if not isinstance(bruto, dict):
        return Proposta()
    plano = _plano(texto)
    numero = str(bruto.get("numero_proposta") or "").strip()
    destinatario = " ".join(str(bruto.get("destinatario") or "").split())
    emitida = _data(bruto, texto, plano)
    validade_dias = _inteiro_perto(bruto, "validade_dias", plano, ("VALIDADE",), 365)
    return Proposta(
        valor=_valor(bruto, plano),
        numero=numero if numero and _plano(numero) in plano else None,
        prazo_dias=_inteiro_perto(bruto, "prazo_entrega_dias", plano,
                                  ("ENTREGA", "PRAZO"), 90),
        emitida_em=emitida,
        validade=emitida + timedelta(days=validade_dias) if emitida and validade_dias else None,
        destinatario=destinatario if destinatario and _plano(destinatario) in plano else "",
        cotacao_id=_carimbo(bruto, plano),
        uf_origem=_uf(bruto, "uf_origem", "ORIGEM", plano),
        uf_destino=_uf(bruto, "uf_destino", "DESTINO", plano),
    )


# ------------------------------------------------------------------ chamada
def _validar(dados) -> dict:
    if not isinstance(dados, dict) or not set(ESQUEMA["required"]) & set(dados):
        raise ValueError("resposta sem nenhum campo da proposta")
    return {k: dados.get(k) for k in ESQUEMA["required"]}


def pedir(texto: str) -> ia.Resposta:
    """Uma chamada pela cadeia de modelos grátis. Levanta ia.IAIndisponivel."""
    return ia.completar_json(SISTEMA, "Texto do PDF:\n\n" + texto[:MAX_TEXTO], ESQUEMA,
                             funcao=FUNCAO, validar=_validar, max_tokens=1500)


def precisa(p: Proposta) -> bool:
    """Só vale gastar a IA quando falta o que decide gravar: valor ou carimbo."""
    return p.valor is None or p.cotacao_id is None


def completar(p: Proposta, texto: str, pedir_ia=None) -> Proposta:
    """O regex leu `p`; a IA preenche só o que ficou em branco. Nunca levanta:
    IA fora do ar ou desligada = devolve `p` como veio."""
    if not LIGADA or not precisa(p) or not (texto or "").strip():
        return p
    try:
        r = (pedir_ia or pedir)(texto)
    except Exception:          # IAIndisponivel, rede: segue sem o plano B
        return p
    da_ia = conferir(r.dados, texto)
    novo = {campo: (atual if atual not in (None, "") else getattr(da_ia, campo))
            for campo, atual in p._asdict().items() if campo != "lido_por"}
    if novo["origem"] == "" and da_ia.uf_origem and not p.uf_origem:
        novo["origem"] = da_ia.uf_origem
    if novo["destino"] == "" and da_ia.uf_destino and not p.uf_destino:
        novo["destino"] = da_ia.uf_destino
    ganhou = [c for c in ("valor", "cotacao_id") if getattr(p, c) is None and novo[c] is not None]
    return Proposta(**novo, lido_por=f"IA ({r.modelo}): {', '.join(ganhou)}" if ganhou else "")
