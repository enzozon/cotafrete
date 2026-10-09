"""Resumo da semana no /adm (sugestão 6, 24/09/2026).

Mesma base do resumo do dia, mas sem IA: só números do banco, comparando os
últimos 7 dias com os 7 anteriores.
- aproveitamento de cada transportadora (respostas com preço / pedidos) e se
  melhorou ou piorou;
- rotas mais cotadas na semana;
- cotações que ficaram sem preço nenhum.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

# Diferença de aproveitamento (em pontos percentuais) que vira "melhorou" /
# "piorou". Menos que isso é ruído de semana fraca.
LIMIAR_PP = 10
MAX_ROTAS = 5


def _pct(com: int, total: int) -> int:
    return round(100 * com / total)


def fatos(con: sqlite3.Connection, hoje: date, nome_de=lambda s: s) -> dict:
    inicio = hoje - timedelta(days=6)            # 7 dias contando hoje
    anterior = inicio - timedelta(days=7)
    fim = (hoje + timedelta(days=1)).isoformat()
    por: dict[str, dict[str, tuple[int, int]]] = {}
    for t, esta, total, com in con.execute(
            "SELECT r.transportadora, c.criado_em >= ?, COUNT(*), SUM(r.valor IS NOT NULL)"
            " FROM resultado r JOIN cotacao c ON c.id = r.cotacao_id"
            " WHERE c.criado_em >= ? AND c.criado_em < ?"
            " GROUP BY 1, 2", (inicio.isoformat(), anterior.isoformat(), fim)):
        por.setdefault(t, {})["esta" if esta else "antes"] = (com or 0, total)

    transportadoras = []
    for slug, s in por.items():
        if "esta" not in s:
            continue
        agora = _pct(*s["esta"])
        antes = _pct(*s["antes"]) if "antes" in s else None
        tendencia = ("" if antes is None else "melhorou" if agora - antes >= LIMIAR_PP
                     else "piorou" if antes - agora >= LIMIAR_PP else "estável")
        transportadoras.append({"transportadora": nome_de(slug), "aproveitamento": agora,
                                "antes": antes, "pedidos": s["esta"][1], "tendencia": tendencia})
    transportadoras.sort(key=lambda t: t["aproveitamento"])

    rotas = [{"rota": r[0], "cotacoes": r[1]} for r in con.execute(
        "SELECT cidade_origem || '/' || uf_origem || ' → ' || cidade_destino || '/' || uf_destino,"
        " COUNT(*) FROM cotacao WHERE criado_em >= ? AND criado_em < ?"
        " GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?", (inicio.isoformat(), fim, MAX_ROTAS))]
    # "Sem preço" só conta cotação em que alguém já respondeu: a que ainda
    # está cotando (nenhum resultado gravado) não é cotação sem preço.
    total, sem = con.execute(
        "SELECT COUNT(*), SUM(EXISTS (SELECT 1 FROM resultado r WHERE r.cotacao_id = c.id)"
        "   AND NOT EXISTS (SELECT 1 FROM resultado r"
        "   WHERE r.cotacao_id = c.id AND r.valor IS NOT NULL))"
        " FROM cotacao c WHERE c.criado_em >= ? AND c.criado_em < ?",
        (inicio.isoformat(), fim)).fetchone()
    return {"de": inicio, "ate": hoje, "transportadoras": transportadoras, "rotas": rotas,
            "cotacoes": total or 0, "sem_preco": sem or 0}


def linhas(f: dict) -> list[str]:
    """O resumo em frases, para o cartão do /adm."""
    if not f["cotacoes"]:
        return ["Nenhuma cotação nos últimos 7 dias."]
    saida = [f"{f['cotacoes']} cotações de {f['de']:%d/%m} a {f['ate']:%d/%m}; "
             f"{f['sem_preco']} ficaram sem preço nenhum."]
    for t in f["transportadoras"]:
        comparar = (f" ({t['tendencia']}: era {t['antes']}% na semana anterior)"
                    if t["tendencia"] else " (sem pedidos na semana anterior)")
        saida.append(f"{t['transportadora']}: {t['aproveitamento']}% com preço "
                     f"em {t['pedidos']} pedidos{comparar}.")
    if f["rotas"]:
        saida.append("Rotas mais cotadas: " + "; ".join(
            f"{r['rota']} ({r['cotacoes']})" for r in f["rotas"]) + ".")
    return saida
