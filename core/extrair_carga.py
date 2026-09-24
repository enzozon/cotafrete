"""Colar o pedido e preencher a cotação: texto livre → campos do formulário.

Pedido do usuário (24/09/2026): o vendedor recebe o pedido por e-mail ou
WhatsApp e redigita CEP, CNPJ, peso, medidas e valor. Aqui a IA lê o texto
colado e devolve os campos; o vendedor CONFERE e clica em Cotar. Nada é
cotado sozinho.

Duas camadas, e a segunda é a que manda:
1. A IA (`core/ia.py`) extrai o que o texto diz, sem inventar — o que não
   está no texto volta `null`.
2. `limpar()` — código, não IA — confere cada campo com as mesmas regras do
   formulário: CEP com 8 dígitos, CNPJ com dígito verificador certo, número
   que é número, quantidade inteira. O que não passa NÃO vai para a tela e
   vira aviso ("CNPJ do destinatário veio com dígito errado: confira"). Um
   CNPJ inventado pela IA com 14 dígitos plausíveis quase nunca acerta o
   dígito verificador — é a trava contra alucinação que sai de graça.

Peso: o formulário pede o peso de UM volume, e o pedido costuma trazer o
total ("3 caixas, 45 kg no total"). A IA separa os dois; a conta total ÷
quantidade é feita aqui, onde não erra.

Os campos de Contato (nome, e-mail, WhatsApp) são de quem PEDE a cotação — o
vendedor —, não do cliente do texto. Ficam de fora de propósito.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from core import ia
from core.models import cnpj_valido, formata_cnpj

MAX_TEXTO = 8000   # um e-mail comprido com assinatura cabe; um PDF colado inteiro, não

# O que a IA devolve. Tudo obrigatório e anulável: é o que o modo estrito do
# Groq exige, e `null` é a forma honesta de "o texto não diz".
_TEXTO_OU_NULO = {"type": ["string", "null"]}
_NUMERO_OU_NULO = {"type": ["number", "null"]}
ESQUEMA = {
    "type": "object",
    "properties": {
        "cep_origem": _TEXTO_OU_NULO,
        "cep_destino": _TEXTO_OU_NULO,
        "cnpj_remetente": _TEXTO_OU_NULO,
        "cnpj_destinatario": _TEXTO_OU_NULO,
        "tipo_frete": {"type": ["string", "null"], "enum": ["cif", "fob", None]},
        "quantidade_volumes": {"type": ["integer", "null"]},
        "peso_por_volume_kg": _NUMERO_OU_NULO,
        "peso_total_kg": _NUMERO_OU_NULO,
        "comprimento_cm": _NUMERO_OU_NULO,
        "largura_cm": _NUMERO_OU_NULO,
        "altura_cm": _NUMERO_OU_NULO,
        "valor_nf_reais": _NUMERO_OU_NULO,
        "material": _TEXTO_OU_NULO,
        "observacoes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["cep_origem", "cep_destino", "cnpj_remetente", "cnpj_destinatario",
                 "tipo_frete", "quantidade_volumes", "peso_por_volume_kg", "peso_total_kg",
                 "comprimento_cm", "largura_cm", "altura_cm", "valor_nf_reais", "material",
                 "observacoes"],
    "additionalProperties": False,
}

SISTEMA = """Você extrai dados de frete de um texto colado por um vendedor da Ventura
(distribuidora no Espírito Santo). O texto é um pedido de cliente, um e-mail ou
uma mensagem de WhatsApp. Os dados vão preencher um formulário de cotação de
frete que o vendedor confere antes de enviar.

Regra principal: NUNCA invente. Campo que o texto não diz = null. Não deduza
CEP a partir de cidade, não complete CNPJ, não estime peso ou medida.

Campos:
- cep_origem / cep_destino: de onde a carga SAI e para onde VAI. Endereço de
  entrega/destino do cliente = destino. Só dígitos ou com hífen, como está.
- cnpj_remetente / cnpj_destinatario: quem envia e quem recebe a mercadoria.
  O CNPJ do cliente que vai RECEBER é o destinatário. Copie como está.
- tipo_frete: "cif" se o texto diz CIF / frete por conta do remetente/vendedor
  / frete pago; "fob" se diz FOB / frete por conta do destinatário/comprador /
  a cobrar. Não diz = null.
- quantidade_volumes: número de volumes/caixas/embalagens/pallets.
- peso_por_volume_kg e peso_total_kg: separe os dois. "3 caixas de 15 kg" →
  por volume 15; "45 kg no total" / "peso bruto 45 kg" → total 45. Converta
  para kg (g, t).
- comprimento_cm, largura_cm, altura_cm: de UM volume, em CENTÍMETROS
  (converta metros e milímetros: 1,2 m = 120; 800 mm = 80). "60x40x30" = 60,
  40, 30 nessa ordem.
- valor_nf_reais: valor da nota fiscal / valor da mercadoria / valor total do
  pedido, em reais, como número (1.234,56 → 1234.56).
- material: o que é a carga, em poucas palavras ("notebooks", "cabos de rede",
  "móveis de escritório").
- observacoes: frases curtas em português sobre o que o vendedor precisa
  conferir: volumes de tamanhos diferentes (e quais), dado ambíguo, mais de um
  endereço, informação que parece faltar. Lista vazia se não houver."""

# campo do formulário → (rótulo para aviso)
ROTULOS = {
    "cep_origem": "CEP de origem", "cep_destino": "CEP de destino",
    "cnpj_remetente": "CNPJ do remetente", "cnpj_destinatario": "CNPJ do destinatário",
    "tipo_frete": "Tipo de frete", "peso": "Peso de UM volume",
    "quantidade": "Quantidade de volumes", "comprimento": "Comprimento",
    "largura": "Largura", "altura": "Altura", "valor_nf": "Valor da nota fiscal",
    "material": "Material",
}


class TextoInvalido(ValueError):
    """Texto vazio ou grande demais — nem vai para a IA."""


@dataclass
class Extracao:
    campos: dict[str, str] = field(default_factory=dict)   # nome do input → valor pronto
    avisos: list[str] = field(default_factory=list)        # o que conferir
    faltando: list[str] = field(default_factory=list)      # rótulos que o texto não trouxe
    modelo: str | None = None


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _dec(v) -> Decimal | None:
    """Número da IA (float, int ou texto "1.234,5") → Decimal; lixo → None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    t = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return Decimal(t)
    except (InvalidOperation, ValueError):
        return None


def _br(d: Decimal, casas: int = 2) -> str:
    """Decimal → como o vendedor digitaria: 12,5 / 1234,56 / 30."""
    q = d.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP).normalize()
    texto = format(q, "f")
    return texto.replace(".", ",")


def limpar(bruto: dict) -> Extracao:
    """A resposta da IA → só o que passa nas regras do formulário. Puro."""
    x = Extracao()

    for chave in ("cep_origem", "cep_destino"):
        d = _digitos(bruto.get(chave))
        if len(d) == 8:
            x.campos[chave] = f"{d[:5]}-{d[5:]}"
        elif d:
            x.avisos.append(f"{ROTULOS[chave]} no texto não tem 8 dígitos ({bruto.get(chave)}): não preenchi.")

    for chave in ("cnpj_remetente", "cnpj_destinatario"):
        d = _digitos(bruto.get(chave))
        if len(d) == 14 and cnpj_valido(d):
            x.campos[chave] = formata_cnpj(d)
        elif d:
            x.avisos.append(f"{ROTULOS[chave]} no texto ({bruto.get(chave)}) não é um CNPJ válido: "
                            "não preenchi — confira no pedido.")

    if bruto.get("tipo_frete") in ("cif", "fob"):
        x.campos["tipo_frete"] = bruto["tipo_frete"]

    qtd = _dec(bruto.get("quantidade_volumes"))
    if qtd is not None and qtd >= 1 and qtd == qtd.to_integral_value():
        x.campos["quantidade"] = str(int(qtd))
    elif qtd is not None:
        x.avisos.append(f"Quantidade de volumes estranha ({bruto.get('quantidade_volumes')}): não preenchi.")

    por_volume = _dec(bruto.get("peso_por_volume_kg"))
    total = _dec(bruto.get("peso_total_kg"))
    if por_volume is not None and por_volume > 0:
        x.campos["peso"] = _br(por_volume)
        if total and "quantidade" in x.campos:
            esperado = por_volume * int(x.campos["quantidade"])
            if abs(esperado - total) > max(Decimal("0.5"), total * Decimal("0.05")):
                x.avisos.append(f"Peso: {x.campos['quantidade']} × {_br(por_volume)} kg = {_br(esperado)} kg, "
                                f"mas o texto diz {_br(total)} kg no total. Confira.")
    elif total is not None and total > 0:
        if "quantidade" in x.campos:
            q = int(x.campos["quantidade"])
            x.campos["peso"] = _br(total / q)
            if q > 1:
                x.avisos.append(f"Peso de UM volume calculado: {_br(total)} kg ÷ {q} volumes "
                                f"= {x.campos['peso']} kg (o texto trazia o total).")
        else:
            x.avisos.append(f"O texto traz o peso total ({_br(total)} kg) mas não a quantidade de "
                            "volumes: preencha a quantidade e o peso de UM volume.")

    for chave, campo in (("comprimento_cm", "comprimento"), ("largura_cm", "largura"),
                         ("altura_cm", "altura")):
        m = _dec(bruto.get(chave))
        if m is not None and m > 0:
            x.campos[campo] = _br(m, 1)

    valor = _dec(bruto.get("valor_nf_reais"))
    if valor is not None and valor > 0:
        x.campos["valor_nf"] = _br(valor)

    material = " ".join(str(bruto.get("material") or "").split())[:80]
    if material:
        x.campos["material"] = material

    for obs in bruto.get("observacoes") or []:
        obs = " ".join(str(obs).split())
        if obs:
            x.avisos.append(obs[:300])

    x.faltando = [r for c, r in ROTULOS.items() if c not in x.campos and c != "tipo_frete"]
    return x


def _validar(dados) -> dict:
    """Formato mínimo da resposta; levantar = próximo modelo da cadeia."""
    if not isinstance(dados, dict):
        raise TypeError("resposta não é objeto")
    faltam = [k for k in ESQUEMA["required"] if k not in dados]
    # modelo sem esquema estrito às vezes omite os nulos: nulo implícito vale
    if len(faltam) == len(ESQUEMA["required"]):
        raise KeyError("nenhum campo esperado na resposta")
    return {k: dados.get(k) for k in ESQUEMA["required"]}


def extrair(texto: str) -> Extracao:
    """Texto colado → campos prontos + avisos. Levanta TextoInvalido e
    ia.IAIndisponivel; quem chama decide a mensagem."""
    texto = (texto or "").strip()
    if len(texto) < 10:
        raise TextoInvalido("Cole o texto do pedido (e-mail, WhatsApp) na caixa.")
    if len(texto) > MAX_TEXTO:
        raise TextoInvalido(f"Texto grande demais ({len(texto)} caracteres; máximo {MAX_TEXTO}). "
                            "Cole só a parte do pedido.")
    r = ia.completar_json(SISTEMA, "Texto colado pelo vendedor:\n\n" + texto, ESQUEMA,
                          funcao="preencher cotação", validar=_validar, max_tokens=2000)
    x = limpar(r.dados)
    x.modelo = r.modelo
    return x
