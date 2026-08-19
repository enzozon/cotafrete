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

    # Cadastradas em 17/08/2026, com os números que o Enzo passou.
    Transportadora("coruja", "Coruja", "5521975489707", "coruja.jpg"),
    Transportadora("nova_uniao", "Nova União", "5524981740082",
                   "nova_uniao.jpg"),
    Transportadora("favorita", "Favorita Transportes", "5527996072155",
                   "favorita.png"),
    Transportadora("dea", "Robson Dea Transportes", "5527999579754",
                   "dea.jpg"),
    # Único FIXO da lista (27 3434-5755): oito dígitos, sem o 9 do celular.
    # Só funciona se a Pretti usar WhatsApp Business no fixo — se não usar, o
    # link abre conversa que ninguém lê. Confirmar antes de confiar.
    Transportadora("pretti", "Pretti", "552734345755", "pretti.jpg"),
    Transportadora("gollog", "Gollog", "5527996885470", "gollog.jpg"),
    Transportadora("cgb", "CGB Todo Brasil", "5565996789712", "cgb.png"),
    Transportadora("trd", "TRD Comercial", "5527998542925", "trd.jpg"),
    Transportadora("tjb", "TJB Transporte e Logística", "5511941441881",
                   "tjb.png"),
    Transportadora("vitlog", "Vitlog (Grazyele)", "5527992689163",
                   "vitlog.png"),
    Transportadora("rv", "RV Log", "5511986959141", "rv.jpg"),
)


def com_whatsapp() -> tuple[Transportadora, ...]:
    """As que dá para acionar hoje — só as que têm número."""
    return tuple(t for t in WHATSAPP if t.tem_numero)


def por_slug(slug: str) -> Transportadora | None:
    """Acha pelo slug, ou None. Quem chama decide o que fazer com o None.

    É por aqui que o número de telefone entra na URL do WhatsApp — nunca pelo
    que veio no pedido. Montar o link com dado de fora viraria
    redirecionamento aberto: um link do nosso próprio site levando a qualquer
    lugar da internet."""
    return next((t for t in com_whatsapp() if t.slug == slug), None)


def sem_numero() -> tuple[Transportadora, ...]:
    """As que estão esperando o telefone, para não caírem no esquecimento."""
    return tuple(t for t in WHATSAPP if not t.tem_numero)
