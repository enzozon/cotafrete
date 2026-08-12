"""Registry: descobre quais transportadoras estão disponíveis e cota em todas.

O ponto da arquitetura: o orquestrador não sabe que a Della Volpe usa browser e
a Jadlog usa HTTP. Ele só chama `cotar()`. Falha de uma não derruba as outras.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from carriers.base import ResultadoCotacao
from core.models import CotacaoRequest, StatusCotacao


def adapters_disponiveis(incluir_browser: bool = True) -> list:
    disponiveis: list = []

    from carriers.jadlog.adapter import JadlogAdapter
    jadlog = JadlogAdapter()
    if jadlog.ativo:                       # só entra se houver token
        disponiveis.append(jadlog)

    if incluir_browser:
        from carriers.dellavolpe.adapter import DellavolpeAdapter
        disponiveis.append(DellavolpeAdapter())

    return disponiveis


def cotar_em_todas(
    req: CotacaoRequest,
    adapters: list | None = None,
    timeout_s: int = 120,
) -> list[ResultadoCotacao]:
    """Fan-out isolado: exceção em um adapter vira ResultadoCotacao(ERRO),
    nunca interrompe os demais."""
    adapters = adapters if adapters is not None else adapters_disponiveis()
    resultados: list[ResultadoCotacao] = []

    with ThreadPoolExecutor(max_workers=max(len(adapters), 1)) as pool:
        futuros = {pool.submit(a.cotar, req): a for a in adapters}
        for fut in as_completed(futuros, timeout=timeout_s):
            adapter = futuros[fut]
            try:
                resultados.append(fut.result())
            except Exception as exc:
                resultados.append(ResultadoCotacao(
                    adapter.slug, StatusCotacao.ERRO,
                    erro=f"{type(exc).__name__}: {exc}",
                ))

    ordem = {StatusCotacao.COTADO: 0, StatusCotacao.AGUARDANDO_RETORNO: 1}
    resultados.sort(key=lambda r: (ordem.get(r.status, 9),
                                   r.valor_frete or float("inf")))
    return resultados


def formatar_comparativo(req: CotacaoRequest, resultados: list[ResultadoCotacao]) -> str:
    linhas = [
        "COTAÇÃO DE FRETE",
        f"Origem: {req.origem.cidade}/{req.origem.uf}",
        f"Destino: {req.destino.cidade}/{req.destino.uf}",
        f"Peso: {req.peso_total_kg} kg  |  Volumes: {req.quantidade_volumes}"
        f"  |  Cubagem: {req.cubagem_m3} m³",
        f"Valor NF: R$ {req.nota_fiscal.valor_total}",
        "-" * 46,
    ]
    for r in resultados:
        linhas.append(r.transportadora.upper())
        if r.valor_frete is not None:
            linhas.append(f"  Frete: R$ {r.valor_frete}")
        if r.prazo_dias is not None:
            linhas.append(f"  Prazo: {r.prazo_dias} dias")
        linhas.append(f"  Status: {r.status.value}")
        if r.erro:
            linhas.append(f"  Obs: {r.erro}")
        linhas.append("-" * 46)
    return "\n".join(linhas)
