"""Os logins do Mercado Eletrônico: um por (cliente, empresa).

Até 28/09/2026 eram dois — VENTURA e UNIÃO no ME geral — e o login era a
própria empresa (`regras.Conta`). Com Nestlé, WEG, Autoglass, Oitamérica,
Profarma e EDP, cada cliente tem o seu usuário para cada empresa, e a
empresa passa a ser só um dos dados do login: é ela que decide os impostos
(`regras.impostos`), o login decide onde entrar.

A `chave` é o que o banco guarda em `me_cotacao.conta`. As duas primeiras
continuam "ventura" e "uniao" de propósito: são as cotações que já estão no
banco de produção.

O prefixo do .env não segue um padrão só (`ME_AUTOGLASS`, mas
`NESTLE_ALIANCA`) — é o que o Enzo cadastrou, e por isso mora aqui, escrito,
em vez de montado.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from mercado_eletronico.regras import Conta

EMPRESAS = {Conta.VENTURA: "VENTURA", Conta.UNIAO: "UNIÃO", Conta.ALIANCA: "ALIANÇA"}

# O ME geral é onde chega a maior parte; os clientes com login próprio são
# lidos com mais folga até o log de chegadas (me_ui.LOG_CHEGADAS) dizer quanto
# cada um recebe de verdade (pedido do Enzo, 28/09/2026).
INTERVALO_GERAL_S = 7 * 60
INTERVALO_CLIENTE_S = 15 * 60


@dataclass(frozen=True)
class Login:
    chave: str
    cliente: str
    empresa: Conta
    prefixo: str
    intervalo_s: int = INTERVALO_CLIENTE_S
    # O robô de SALVAR só entra onde o formulário foi mapeado e testado com um
    # Salvar real autorizado. O recon de 28/09/2026 mostrou que o formulário
    # muda com o COMPRADOR (EDP pede "Preço unitário", Unidade e Ref
    # Fabricante; Alpek pede "Preço a Prazo CIF", DIFAL e ficha técnica), e
    # que o login "Nestlé" recebe cotação da EDP. Até mapear, a conta só lê.
    robo_liberado: bool = False

    @property
    def rotulo(self) -> str:
        return f"{self.cliente} · {EMPRESAS[self.empresa]}"

    def credenciais(self, ambiente: Mapping[str, str] | None = None) -> tuple[str, str] | None:
        amb = os.environ if ambiente is None else ambiente
        login, senha = amb.get(f"{self.prefixo}_LOGIN"), amb.get(f"{self.prefixo}_SENHA")
        return (login, senha) if login and senha else None


LOGINS: tuple[Login, ...] = (
    Login("ventura", "ME geral", Conta.VENTURA, "ME_VENTURA", INTERVALO_GERAL_S, True),
    Login("uniao", "ME geral", Conta.UNIAO, "ME_UNIAO", INTERVALO_GERAL_S, True),
    Login("nestle_alianca", "Nestlé", Conta.ALIANCA, "NESTLE_ALIANCA"),
    Login("nestle_uniao", "Nestlé", Conta.UNIAO, "NESTLE_UNIAO"),
    Login("nestle_ventura", "Nestlé", Conta.VENTURA, "NESTLE_VENTURA"),
    Login("weg_uniao", "WEG", Conta.UNIAO, "WEG_UNIAO"),
    Login("weg_ventura", "WEG", Conta.VENTURA, "WEG_VENTURA"),
    Login("autoglass", "Autoglass", Conta.ALIANCA, "ME_AUTOGLASS"),
    Login("oitamerica_alianca", "Oitamérica", Conta.ALIANCA, "OITAMERICA_ALIANCA"),
    Login("oitamerica_uniao", "Oitamérica", Conta.UNIAO, "OITAMERICA_UNIAO"),
    Login("oitamerica_ventura", "Oitamérica", Conta.VENTURA, "OITAMERICA_VENTURA"),
    Login("profarma_uniao", "Profarma", Conta.UNIAO, "PROFARMA_UNIAO"),
    Login("profarma_alianca", "Profarma", Conta.ALIANCA, "PROFARMA_ALIANCA"),
    Login("edp_alianca", "EDP", Conta.ALIANCA, "EDP_ALIANCA"),
)

_POR_CHAVE = {l.chave: l for l in LOGINS}
ROTULOS = {l.chave: l.rotulo for l in LOGINS}


def de(chave: "str | Conta | Login") -> Login:
    """O login pela chave do banco. Aceita `Conta` (VENTURA/UNIÃO do ME geral,
    como o código chamava antes) e o próprio Login. Chave desconhecida é
    KeyError: melhor parar do que entrar na conta errada."""
    if isinstance(chave, Login):
        return chave
    return _POR_CHAVE[chave.value if isinstance(chave, Conta) else chave]


def configurados(ambiente: Mapping[str, str] | None = None) -> list[Login]:
    return [l for l in LOGINS if l.credenciais(ambiente)]
