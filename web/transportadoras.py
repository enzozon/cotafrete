"""Quem atende por WhatsApp: nome, número e logo, num lugar só.

Antes isto era uma lista de tuplas dentro do app.py e as logos viviam em
base64 no meio do HTML. Com três transportadoras dava para conviver; com
quatorze, não — cada nova exigia mexer em três lugares diferentes, e uma logo
em base64 no meio do código é impossível de conferir batendo o olho.

Agora: o arquivo da logo fica em `web/logos/`, o cadastro fica aqui, e
acrescentar uma transportadora é UMA linha.

O telefone vazio é de propósito. Serve para registrar a transportadora
enquanto o número não chegou: ela fica documentada aqui, mas NÃO aparece na
tela — um botão de WhatsApp que não abre conversa nenhuma é pior do que
transportadora nenhuma, porque o vendedor clica, não acontece nada, e ele não
sabe se o problema é o sistema ou o telefone dele.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PASTA_LOGOS = Path(__file__).parent / "logos"


@dataclass(frozen=True)
class Transportadora:
    """Telefone no formato do wa.me: só dígitos, com 55 na frente.

    Sem o 55 o link abre conversa com número truncado; com máscara,
    parêntese e traço quebram a URL."""

    slug: str
    nome: str
    telefone: str
    logo: str

    @property
    def tem_numero(self) -> bool:
        return bool(self.telefone.strip())


# Ordem = ordem na tela. As três primeiras já rodavam desde 14/08/2026.
WHATSAPP: tuple[Transportadora, ...] = (
    Transportadora("movvi", "Movvi Logística", "553194910111", "movvi.jpg"),
    Transportadora("translovato", "Translovato", "558181990635",
                   "translovato.jpg"),
    Transportadora("continental", "Continental Transportadora",
                   "5527988928840", "continental.jpg"),

    # Cadastradas em 17/08/2026. As logos chegaram; os números ainda não —
    # então elas não aparecem na tela até alguém preencher o telefone aqui.
    Transportadora("coruja", "Coruja", "", "coruja.jpg"),
    Transportadora("nova_uniao", "Nova União", "", "nova_uniao.jpg"),
    Transportadora("favorita", "Favorita Transportes", "", "favorita.png"),
    Transportadora("dea", "Robson Dea Transportes", "", "dea.jpg"),
    Transportadora("pretti", "Pretti", "", "pretti.jpg"),
    Transportadora("gollog", "Gollog", "", "gollog.jpg"),
    Transportadora("cgb", "CGB Todo Brasil", "", "cgb.png"),
    Transportadora("trd", "TRD Comercial", "", "trd.jpg"),
    Transportadora("tjb", "TJB Transporte e Logística", "", "tjb.png"),
    Transportadora("vitlog", "Vitlog (Grazyele)", "", "vitlog.png"),
    Transportadora("rv", "RV Log", "", "rv.jpg"),
)


def com_whatsapp() -> tuple[Transportadora, ...]:
    """As que dá para acionar hoje — só as que têm número."""
    return tuple(t for t in WHATSAPP if t.tem_numero)


def sem_numero() -> tuple[Transportadora, ...]:
    """As que estão esperando o telefone, para não caírem no esquecimento."""
    return tuple(t for t in WHATSAPP if not t.tem_numero)
