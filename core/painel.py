"""As contas do dashboard administrativo.

Camada PURA: recebe uma conexão sqlite3, devolve list[dict] ou dict. Nenhum
HTML — pelo mesmo motivo de carriers/*/mapping.py, o risco mora na conta, e
conta se testa sem navegador.

Só LEITURA. Nada aqui escreve no banco.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

# Como cada status conta. Definição única: sem ela, cada bloco da tela
# poderia contar diferente e os números não fechariam entre si.
#
# `aguardando_retorno` é SUCESSO: a Della Volpe recebeu e o preço vem por
# e-mail. Contar como falha a jogaria para o vermelho todo dia, sem nada de
# errado.
#
# `interrompido` é NOSSO: o servidor reiniciou no meio. Fica fora do
# aproveitamento — punir a transportadora por um restart nosso faria o número
# mentir.
SUCESSO = frozenset({"cotado", "aguardando_retorno"})
RECUSA = frozenset({"recusado"})
FALHA = frozenset({"erro", "intervencao_necessaria"})
NOSSA = frozenset({"interrompido"})


def categoria(status: str) -> str:
    """Status do banco -> categoria da tela. FUNÇÃO PURA."""
    if status in SUCESSO:
        return "sucesso"
    if status in RECUSA:
        return "recusa"
    if status in FALHA:
        return "falha"
    if status in NOSSA:
        return "nossa"
    # Status que ninguém previu aparece como "inesperado" em vez de sumir:
    # esconder o desconhecido foi como "(nenhuma mensagem visível)" nasceu.
    return "inesperado"


def _desde(dias: int) -> str:
    return (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")


def resumo_do_dia(con: sqlite3.Connection) -> dict:
    """Os números de hoje, para a faixa do topo."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    ids = [r["id"] for r in con.execute(
        "SELECT id FROM cotacao WHERE criado_em LIKE ?", (f"{hoje}%",))]
    if not ids:
        return {"cotacoes": 0, "com_preco": 0, "sem_nenhum_preco": 0,
                "em_andamento": 0}

    marcas = ", ".join("?" * len(ids))
    com_preco = {r["cotacao_id"] for r in con.execute(
        f"SELECT DISTINCT cotacao_id FROM resultado"
        f" WHERE cotacao_id IN ({marcas}) AND status = 'cotado'", ids)}
    respondidas = {r["cotacao_id"] for r in con.execute(
        f"SELECT DISTINCT cotacao_id FROM resultado"
        f" WHERE cotacao_id IN ({marcas})", ids)}

    return {
        "cotacoes": len(ids),
        "com_preco": len(com_preco),
        # Sem NENHUM preço: respondeu alguma coisa e nada virou valor. É a
        # métrica que diz "o vendedor ficou na mão".
        "sem_nenhum_preco": len(respondidas - com_preco),
        "em_andamento": len(set(ids) - respondidas),
    }


def saude_das_transportadoras(con: sqlite3.Connection,
                               dias: int) -> list[dict]:
    """Uma linha por transportadora, da pior para a melhor."""
    linhas: dict[str, dict] = {}
    for r in con.execute(
            "SELECT r.transportadora, r.status FROM resultado r"
            " JOIN cotacao c ON c.id = r.cotacao_id"
            " WHERE c.criado_em >= ?", (_desde(dias),)):
        alvo = linhas.setdefault(r["transportadora"], {
            "transportadora": r["transportadora"], "sucesso": 0,
            "recusa": 0, "falha": 0, "nossa": 0, "inesperado": 0})
        alvo[categoria(r["status"])] += 1

    for alvo in linhas.values():
        base = alvo["sucesso"] + alvo["recusa"] + alvo["falha"]
        # None, não 0: sem nada no denominador o aproveitamento é
        # DESCONHECIDO. Zero diria "nunca acertou", que é outra coisa.
        alvo["aproveitamento"] = alvo["sucesso"] / base if base else None

    return sorted(linhas.values(),
                  key=lambda a: (a["aproveitamento"] is not None,
                                 a["aproveitamento"] or 0))
