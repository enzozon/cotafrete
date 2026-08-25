"""As empresas do grupo no portal da Generoso, e a regra do CIF/FOB.

Camada PURA: nada aqui abre navegador. Serve a dois propósitos que nasceram
juntos —

1. Escolher a empresa certa no "Alterar empresa" do site. Até 25/08/2026 toda
   cotação saía com o CNPJ da conta, qualquer que fosse o que o vendedor
   digitou no formulário.

2. Barrar, antes de gastar 40 segundos de navegador, a cotação em que o
   CIF/FOB está trocado.

Sobre (2): a Generoso PRENDE uma das pontas no CNPJ cadastrado — no CIF a
origem, no FOB o destino — e não deixa mexer no CEP dela. Marcar CIF com uma
empresa do grupo no DESTINO faz as duas pontas virarem a mesma casa. O site
recusa com "CEP de coleta não pode ser o mesmo de destino", mas essa frase
mora só no `aria-invalid` do campo: quem lê a tela não acha nada, e o
vendedor recebia "a etapa do destino não avançou. O site diz: (nenhuma
mensagem visível)".

Levantado no histórico inteiro em 25/08/2026: as três ocorrências dessa falha
(#5 e #20 de produção, #53 de desenvolvimento) têm a MESMA forma — CIF com
empresa do grupo no destino. Nenhuma outra falha da Generoso tem.
"""

from __future__ import annotations

from typing import NamedTuple

from core.models import CotacaoRequest, TipoFrete, limpa_doc


class Empresa(NamedTuple):
    cnpj: str
    nome: str          # como o SITE escreve, para casar no menu


# As três do "Alterar empresa". O nome é o rótulo do menu; o CNPJ é o que
# manda. Casar por CNPJ e não por nome é de propósito: nome o site pode
# abreviar ("Alianca Comercio de Produto...") e um dia mudar.
EMPRESAS = (
    Empresa("08.310.365/0001-24", "Ventura Inf Ltda me"),
    Empresa("05.954.058/0001-98", "Alianca Comercio de Produtos"),
    Empresa("20.837.281/0001-49", "Uniao Info Ltda - me"),
)


def empresa_de(cnpj: str | None) -> Empresa | None:
    """A empresa do grupo com este CNPJ, ou None. Ignora máscara e espaço."""
    digitos = limpa_doc(cnpj or "")
    if not digitos:
        return None
    return next((e for e in EMPRESAS if limpa_doc(e.cnpj) == digitos), None)


def lado_do_grupo(req: CotacaoRequest) -> str | None:
    """Em que ponta da carga está o grupo: "origem", "destino", "ambos"
    ou None.

    É o fato físico, lido dos CNPJs — independe do que o vendedor marcou.
    O CIF/FOB é a opinião dele sobre esse fato, e é a comparação entre os
    dois que revela o engano."""
    na_origem = empresa_de(req.remetente.cnpj) is not None
    no_destino = empresa_de(req.destinatario.cnpj) is not None
    if na_origem and no_destino:
        return "ambos"
    if na_origem:
        return "origem"
    if no_destino:
        return "destino"
    return None


# O que cada modo AFIRMA sobre onde o grupo está.
#   CIF  o grupo despacha  -> grupo na origem
#   FOB  o grupo recebe    -> grupo no destino
_LADO_ESPERADO = {TipoFrete.CIF: "origem", TipoFrete.FOB: "destino"}


def conflito_cif_fob(req: CotacaoRequest) -> str | None:
    """A frase para o vendedor quando o CIF/FOB contradiz os CNPJs, ou None.

    Só acusa o caso comprovado — grupo numa ponta e o modo apontando para a
    outra. Cotação sem o grupo em ponta nenhuma, ou com ele nas duas, passa:
    barrar cotação boa é pior que o bug, porque tira o preço do vendedor e
    ainda não diz o que fazer."""
    lado = lado_do_grupo(req)
    esperado = _LADO_ESPERADO.get(req.tipo_frete)
    if lado is None or lado == "ambos" or lado == esperado:
        return None

    marcado, correto = ("CIF", "FOB") if lado == "destino" else ("FOB", "CIF")
    empresa = empresa_de(req.destinatario.cnpj if lado == "destino"
                         else req.remetente.cnpj)
    quem = "recebe" if lado == "destino" else "despacha"
    return (
        f"Esta cotação está marcada como {marcado}, mas quem {quem} é a "
        f"{empresa.nome} — uma empresa do grupo. Carga que "
        f"{'chega para' if lado == 'destino' else 'sai do'} o grupo é "
        f"{correto}. A Generoso prende o endereço da empresa do grupo no "
        f"CNPJ cadastrado e não deixa trocar o CEP, então do jeito que está "
        f"a cotação sairia e chegaria no mesmo lugar — e o site trava sem "
        f"dizer por quê. Marque {correto} e cote de novo."
    )


def empresa_alvo(req: CotacaoRequest) -> Empresa | None:
    """A empresa que precisa estar selecionada no site, ou None.

    É a ponta que a Generoso TRAVA: no CIF a origem, no FOB o destino. Até
    25/08/2026 o robô nunca trocava, e toda cotação saía com o CNPJ da conta
    — mesmo quando o vendedor digitava outra das três empresas do grupo. A
    tela final avisava disso; agora não precisa mais avisar, porque o robô
    troca.

    None quando a ponta travada não é do grupo. Aí não há o que escolher: o
    site fica com o que já estava, que é o comportamento de sempre."""
    ponta = (req.remetente if req.tipo_frete is TipoFrete.CIF
             else req.destinatario)
    return empresa_de(ponta.cnpj)
