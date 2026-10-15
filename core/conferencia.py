"""O que conferir com o vendedor ANTES de cotar. FUNÇÃO PURA.

Nasceu do levantamento do /adm em 15/10/2026:

- CIF marcado com o destinatário do grupo (ou FOB com o remetente): #411,
  #412, #415 na Favorita, #350 e #374 na Generoso. Cada transportadora
  recusava do seu jeito, depois de abrir o navegador; a pergunta certa era
  uma só, feita uma vez, no formulário.
- Medida digitada errada: #342 (freezer de 63 kg com 1 cm de largura) e
  #374 (altura de 1 cm). O site cota o que recebe, e o preço parece certo.

Só AVISA: o vendedor confirma e segue. Barrar cotação boa é pior que o erro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from carriers.generoso.mapping import EMPRESAS, empresa_de, lado_do_grupo
from core.models import CotacaoRequest, TipoFrete

# Menor medida plausível de um volume despachado, em cm.
MEDIDA_MINIMA_CM = Decimal(3)
# Densidade acima disto (kg/m³) é quase sempre medida digitada errada: o
# freezer da #342 dava 9.600 kg/m³; aço maciço tem 7.850.
DENSIDADE_MAXIMA = Decimal(3000)


@dataclass(frozen=True)
class Aviso:
    texto: str
    # O que o botão "corrigir" muda no formulário, ou vazio se não há
    # correção óbvia (medida: só o vendedor sabe a certa).
    correcao: dict = field(default_factory=dict)
    rotulo_correcao: str = ""


def avisos(req: CotacaoRequest) -> list[Aviso]:
    saida: list[Aviso] = []

    lado = lado_do_grupo(req, EMPRESAS)
    if lado == "destino" and req.tipo_frete is TipoFrete.CIF:
        empresa = empresa_de(req.destinatario.cnpj, EMPRESAS)
        saida.append(Aviso(
            f"Quem recebe é a {empresa.nome}, uma empresa do grupo: carga que "
            "chega para o grupo é FOB, e esta está marcada como CIF.",
            {"tipo_frete": "fob"}, "Trocar para FOB e cotar"))
    elif lado == "origem" and req.tipo_frete is TipoFrete.FOB:
        empresa = empresa_de(req.remetente.cnpj, EMPRESAS)
        saida.append(Aviso(
            f"Quem envia é a {empresa.nome}, uma empresa do grupo: carga que "
            "sai do grupo é CIF, e esta está marcada como FOB.",
            {"tipo_frete": "cif"}, "Trocar para CIF e cotar"))

    for v in req.volumes:
        for nome, medida in (("comprimento", v.comprimento_cm),
                             ("largura", v.largura_cm),
                             ("altura", v.altura_cm)):
            if medida < MEDIDA_MINIMA_CM:
                saida.append(Aviso(
                    f"Confere a {nome}? {_num(medida)} cm para um volume de "
                    f"{_num(v.peso_kg)} kg."))
        volume_m3 = v.comprimento_cm * v.largura_cm * v.altura_cm / Decimal(1_000_000)
        if (volume_m3 > 0 and v.peso_kg / volume_m3 > DENSIDADE_MAXIMA
                and not any("Confere a" in a.texto for a in saida)):
            saida.append(Aviso(
                f"Confere as medidas? {_num(v.peso_kg)} kg em "
                f"{_num(v.comprimento_cm)} × {_num(v.largura_cm)} × "
                f"{_num(v.altura_cm)} cm é mais pesado que aço maciço."))
    return saida


def _num(d: Decimal) -> str:
    return f"{d.normalize():f}".replace(".", ",")
