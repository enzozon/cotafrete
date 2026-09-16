"""Ajudantes dos testes web.

Existe por um motivo só: desde 16/09/2026 o cookie do vendedor é assinado.
Antes bastava `cliente.cookies.set(COOKIE, "enzo")` — e era exatamente essa
facilidade que tornava o sistema inseguro, porque qualquer visitante fazia o
mesmo no inspetor do navegador. Agora entrar num teste custa o mesmo que
entrar de verdade: ter conta e um cookie que o servidor assinou.
"""

from __future__ import annotations

from core import sessao


def entrar(cliente, app_web, nome: str = "enzo"):
    """Deixa o cliente logado como `nome`, do jeito legítimo.

    Cria a conta (o `vendedor()` recusa sessão de conta que não existe) e
    assina o cookie com o segredo do banco que o teste montou."""
    app_web.banco.criar_conta(nome)
    cliente.cookies.set(
        app_web.COOKIE, sessao.assinar(nome, app_web.banco.segredo_sessao()))
    return cliente
