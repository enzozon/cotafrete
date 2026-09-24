"""A ponte entre a tela /me e o ME real: ler a lista e ler as páginas de itens.

Só leitura, e pelas travas do robô: tudo passa por `robo.Sessao` (rede,
form.submit e confirm travados, ver trava.py). Nada aqui clica em Salvar.

- `pendencias(conta)`: abre "Oportunidades a Responder" e captura o JSON da
  busca (`transactions/search`, a única escrita que a trava libera — é uma
  busca) → `lista.ler_busca`.
- `ler_paginas(conta, numero)`: HTML de cada página de itens da cotação,
  para `pagina.ler`. Da página 2 em diante o ME só abre pelo POST de troca
  de página (`Acao=12`...), que grava a página atual como está — autorizado
  pelo usuário em 23/09/2026. Não muda nada: a página vai do jeito que veio.
"""

from __future__ import annotations

from mercado_eletronico import lista
from mercado_eletronico import robo as R
from mercado_eletronico.regras import Conta

URL_PENDENCIAS = R.URL_LOGIN_DESTINO + "?CreateDateStart=2026-06-25"


def _eh_busca(resp) -> bool:
    return resp.url.endswith("/transactions/search") and resp.request.method == "POST"


def _buscar(s, espera_ms: int):
    """Abre a lista e devolve a resposta da busca, ou None se não veio."""
    from playwright.sync_api import TimeoutError as Esgotou
    try:
        with s.page.expect_response(_eh_busca, timeout=espera_ms) as resp:
            s.page.goto(URL_PENDENCIAS, wait_until="domcontentloaded")
        return resp.value
    except Esgotou:
        return None


def pendencias(conta: str, **sessao) -> list[lista.CotacaoPendente]:
    with R.Sessao(Conta(conta), **sessao) as s:
        # Sem sessão o ME carrega a lista e SÓ DEPOIS manda para o login, por
        # JavaScript — a busca nunca vem. `networkidle` não serve: o chat da
        # página deixa a rede ocupada para sempre.
        resp = _buscar(s, 25_000)
        if resp is None:
            if "login" not in s.page.url.lower():
                raise R.RoboRecusou(f"a lista do ME não respondeu ({s.page.url[:80]})")
            s.login()
            resp = _buscar(s, s.timeout_ms)
            if resp is None:
                raise R.RoboRecusou("a lista do ME não respondeu depois do login")
        return lista.ler_busca(resp.json())


def ler_paginas(conta: str, numero: int, **sessao) -> list[str]:
    with R.Sessao(Conta(conta), **sessao) as s:
        s.abrir(numero)
        htmls = [s.page.content()]
        for p in range(2, R.paginas(s.page) + 1):
            s.acao(lambda p=p: R._clicar_pagina(s.page, p))
            htmls.append(s.page.content())
        return htmls
