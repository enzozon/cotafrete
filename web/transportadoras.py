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
    # Só para quem é acionada por e-mail em vez de WhatsApp. Vazio no resto.
    email: str = ""
    # Selo chamativo no cartão — para quando a transportadora tem uma
    # especialidade que o vendedor precisa ver ANTES de escolher para quem
    # manda. Vazio na maioria.
    observacao: str = ""

    @property
    def tem_numero(self) -> bool:
        return bool(self.telefone.strip())

    @property
    def tem_email(self) -> bool:
        return bool(self.email.strip())

    @property
    def tem_observacao(self) -> bool:
        return bool(self.observacao.strip())


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

    # Segundo contato da DEA Transportes (o outro é o slug "dea", com o
    # Robson) — a Dayse atende pelo próprio número, cadastrada em 02/09/2026.
    Transportadora("dea_carvalho", "Dayse Carvalho – DEA Transportes",
                   "5527998650176", "dea_transportes.png",
                   observacao="Especialista em linha branca no ES"),
)


# Quem o vendedor aciona por E-MAIL, com o texto pronto na tela.
#
# A Della Volpe entrou aqui em 31/08/2026, vinda das automáticas. Eles
# puseram Cloudflare Turnstile no formulário público — uma caixa "Confirme
# que é humano" — e sem ela marcada o Contact Form 7 recusa o envio como spam
# sem gerar e-mail nenhum. As cotações #78 a #84 falharam todas assim.
#
# Medido com envio real autorizado em 31/08/2026: o token fica vazio antes do
# clique, continua vazio 30s depois da recusa, e o segundo clique é recusado
# igual. Não é espera que resolve, e marcar a caixa por código seria derrubar
# um controle que o dono do site instalou de propósito.
#
# O endereço é o que está impresso no rodapé do formulário deles — o mesmo
# destino que o formulário usaria. Se um dia liberarem o acesso, voltar a
# automática é acrescentar o slug em AUTOMATICAS e a fábrica em FABRICAS.
POR_EMAIL: tuple[Transportadora, ...] = (
    Transportadora("dellavolpe", "Della Volpe", "", "DELLAVOLPE.png",
                   email="comercial@dellavolpe.com.br"),
)


# As AUTOMÁTICAS: nome de tela e arquivo da logo. Elas não atendem por
# WhatsApp, então não entram na lista de cima — mas o nome e a logo delas são
# cadastro igual ao das outras, e o topo deste arquivo já diz que cadastro mora
# aqui.
#
# Moravam em `web/app.py` até 04/09/2026, quando o painel do adm ganhou a tela
# de UMA cotação (`/adm/cotacao/N`): ela precisa escrever "Camilo dos Santos"
# onde o banco guardou "camilo", e `web/adm.py` não pode importar `web/app.py`
# — é o app que registra as rotas do adm, e o import de volta seria circular.
NOMES_AUTOMATICAS = {
    "camilo": "Camilo dos Santos",
    "jadlog": "Jadlog Entregas",
    "translovato": "Translovato",
    "generoso": "Transporte Generoso",
    "dellavolpe": "Della Volpe",
    "braspress": "Braspress",
}

# Slug sem arquivo aqui desenha um espaço vazio no lugar — melhor do que uma
# imagem quebrada. O par é conferido nos dois sentidos por
# tests/test_transportadoras.py: nome cadastrado tem que existir no disco, e
# arquivo no disco tem que estar cadastrado.
LOGOS_AUTOMATICAS = {
    "camilo": "camilo.png",
    "jadlog": "jadlog.png",
    "generoso": "generoso.png",
    # MAIUSCULA de proposito: e o nome exato do arquivo que o Enzo colocou
    # nas duas pastas em 26/08/2026. Renomear para minuscula deixaria um
    # arquivo orfao em cotafrete-producao, onde ele foi posto a mao.
    "dellavolpe": "DELLAVOLPE.png",
    "braspress": "braspress.png",
}


# A calculadora da Jadlog cota UM pacote por vez (carriers/jadlog/painel.py).
# Com mais de um volume o número dela não é comparável com o da Camilo e o da
# Translovato, que cotam a carga inteira — e o menor número na tela é o que
# fecha negócio.
#
# Está no cadastro, e não na tela, porque agora são DUAS telas comparando
# preço: a do vendedor e a do adm. Se cada uma tivesse a sua lista, a mesma
# cotação elegeria vencedores diferentes conforme quem olhasse.
COTAM_POR_VOLUME = ("jadlog",)


def cota_por_volume(slug: str, quantidade: int) -> bool:
    """A transportadora cotou UM volume e a carga tem mais de um?

    Só nesse caso o preço dela deixa de ser comparável. Com um volume só, o
    preço dela É o da carga — avisar ali seria ruído, e aviso que aparece
    sempre é aviso que ninguém lê."""
    return slug in COTAM_POR_VOLUME and quantidade > 1


def nome_de(slug: str) -> str:
    """O nome de tela do que o banco guardou como slug.

    Devolve o PRÓPRIO slug quando ninguém o cadastrou. É feio de propósito:
    uma transportadora nova aparece como "acme" na tela do adm, e quem olhar
    percebe o cadastro faltando. Devolver vazio apagaria a linha inteira — o
    resultado sumiria da tela em vez de pedir uma linha de cadastro."""
    if slug in NOMES_AUTOMATICAS:
        return NOMES_AUTOMATICAS[slug]
    achada = next((t for t in (*WHATSAPP, *POR_EMAIL) if t.slug == slug), None)
    return achada.nome if achada else slug


def logo_de(slug: str) -> str:
    """O arquivo da logo, ou "" para quem não tem nenhuma cadastrada.

    Quem chama decide o que fazer com o vazio — a tela do adm desenha a
    inicial num círculo, que é melhor do que o ícone de imagem quebrada."""
    if slug in LOGOS_AUTOMATICAS:
        return LOGOS_AUTOMATICAS[slug]
    achada = next((t for t in (*WHATSAPP, *POR_EMAIL) if t.slug == slug), None)
    return achada.logo if achada else ""


def com_email() -> tuple[Transportadora, ...]:
    """As que o vendedor aciona por e-mail, com o texto pronto."""
    return tuple(t for t in POR_EMAIL if t.tem_email)


def por_slug_email(slug: str) -> Transportadora | None:
    """Acha entre as de e-mail, ou None.

    Separada de `por_slug` de propósito: aquela protege um REDIRECIONAMENTO
    (o wa.me), e misturar as duas listas abriria a porta que o comentário
    dela existe para fechar. Esta aqui só alimenta uma página nossa."""
    return next((t for t in com_email() if t.slug == slug), None)


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
