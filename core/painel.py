"""As contas do dashboard administrativo.

Camada PURA: recebe uma conexão sqlite3, devolve list[dict] ou dict. Nenhum
HTML — pelo mesmo motivo de carriers/*/mapping.py, o risco mora na conta, e
conta se testa sem navegador.

Só LEITURA. Nada aqui escreve no banco.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

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

    # None (sem dados) vai para o FIM da lista, depois até de quem tem a
    # melhor nota. A chave antiga ("is not None") fazia o contrário: None
    # virava (False, 0), que ordena ANTES de qualquer aproveitamento real —
    # "desconhecido" aparecia como pior do que "0% conhecido", e uma
    # transportadora sem nenhuma cotação no período ia parar no topo da
    # lista dos piores, à frente de quem de fato errou todas.
    return sorted(linhas.values(),
                  key=lambda a: (a["aproveitamento"] is None,
                                 a["aproveitamento"] or 0))


def _preco(bruto: str | None) -> Decimal | None:
    """`resultado.valor` é TEXTO no banco (ver core/banco.py) e pode estar
    ausente ou, em tese, corrompido — daqui não vira exceção, vira None."""
    if bruto is None:
        return None
    try:
        return Decimal(bruto)
    except InvalidOperation:
        return None


def historico(con: sqlite3.Connection, *, dias: int = 30,
              usuario: str | None = None, so_com_falha: bool = False,
              limite: int = 200) -> list[dict]:
    """As cotações de TODA a empresa, da mais nova para a mais velha.

    É a diferença central em relação a `banco.listar_cotacoes`, que mostra só
    as do próprio vendedor. Aquela função NÃO muda: a garantia dela é da tela
    do vendedor. Esta é outra porta, para outro público — em vez de um
    `if adm` no meio da que já existe."""
    condicoes = ["criado_em >= ?"]
    valores: list = [_desde(dias)]
    if usuario:
        condicoes.append("usuario = ?")
        valores.append(usuario)
    if so_com_falha:
        # Filtro precisa entrar ANTES do LIMIT: aplicá-lo depois, em Python,
        # deixava o SQL cortar nas `limite` cotações mais recentes e só então
        # descartar as sem falha — se a janela de `dias` tivesse mais que
        # `limite` cotações, falha antiga sumia sem aviso. `sorted()` porque
        # frozenset não garante ordem, e a quantidade de "?" tem que bater
        # com a de valores.
        falhas = sorted(FALHA)
        condicoes.append(
            "id IN (SELECT cotacao_id FROM resultado"
            f" WHERE status IN ({', '.join('?' * len(falhas))}))")
        valores.extend(falhas)

    cotacoes = con.execute(
        f"SELECT * FROM cotacao WHERE {' AND '.join(condicoes)}"
        f" ORDER BY id DESC LIMIT ?", [*valores, limite]).fetchall()
    if not cotacoes:
        return []

    ids = [c["id"] for c in cotacoes]
    marcas = ", ".join("?" * len(ids))
    por_cotacao: dict[int, list] = {i: [] for i in ids}
    for r in con.execute(
            f"SELECT cotacao_id, status, valor FROM resultado"
            f" WHERE cotacao_id IN ({marcas})", ids):
        por_cotacao[r["cotacao_id"]].append(r)

    linhas = []
    for c in cotacoes:
        resultados = por_cotacao[c["id"]]
        contagem: dict[str, int] = {}
        for r in resultados:
            chave = categoria(r["status"])
            contagem[chave] = contagem.get(chave, 0) + 1

        precos = [p for p in (_preco(r["valor"]) for r in resultados)
                  if p is not None]
        linhas.append({
            "id": c["id"],
            "criado_em": c["criado_em"],
            "usuario": c["usuario"],
            "rota": f"{c['cidade_origem'] or c['cep_origem']} -> "
                    f"{c['cidade_destino'] or c['cep_destino']}",
            "material": c["material"],
            # None, não 0: zero seria um preço. Não ter preço é outra coisa.
            "melhor_preco": min(precos) if precos else None,
            "contagem": contagem,
        })
    return linhas


# Quantas horas/dias/meses o gráfico do período mostra. A escolha não é
# estética: 3650 dias em barras de um dia dariam 3650 barras de meio pixel, e
# 24 horas numa barra só não é gráfico nenhum.
def unidade_do_periodo(dias: int) -> str:
    """FUNÇÃO PURA: o tamanho do balde para uma janela de `dias`."""
    if dias <= 2:
        return "hora"
    if dias <= 92:
        return "dia"
    return "mes"


# Quantos caracteres do `criado_em` ISO identificam o balde:
# "2026-09-02T14:33:07" -> 13 é a hora, 10 é o dia, 7 é o mês.
_TAMANHO = {"hora": 13, "dia": 10, "mes": 7}


def _inicio_do_balde(agora: datetime, dias: int, unidade: str) -> datetime:
    """O começo da janela, ALINHADO ao balde.

    Alinhar não é detalhe: com a janela começando às 14h37, o primeiro balde
    cobriria 23 minutos e apareceria como uma queda no gráfico que nunca
    aconteceu."""
    if unidade == "hora":
        return (agora - timedelta(hours=23)).replace(
            minute=0, second=0, microsecond=0)
    if unidade == "dia":
        return (agora - timedelta(days=dias - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
    return agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _chaves(inicio: datetime, fim: datetime, unidade: str) -> list[str]:
    """Todos os baldes da janela, INCLUSIVE os vazios.

    Balde vazio é dado: um dia sem nenhuma cotação é notícia. Sem ele, dois
    dias distantes ficariam colados e o gráfico mostraria um movimento
    contínuo que não existiu."""
    if unidade == "mes":
        chaves, ano, mes = [], inicio.year, inicio.month
        while (ano, mes) <= (fim.year, fim.month):
            chaves.append(f"{ano:04d}-{mes:02d}")
            ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
        return chaves

    passo = timedelta(hours=1) if unidade == "hora" else timedelta(days=1)
    molde = "%Y-%m-%dT%H" if unidade == "hora" else "%Y-%m-%d"
    chaves, quando = [], inicio
    while quando <= fim:
        chaves.append(quando.strftime(molde))
        quando += passo
    return chaves


def serie_por_periodo(con: sqlite3.Connection, dias: int) -> dict:
    """Cotações e cotações-com-preço por balde de tempo, para o gráfico.

    "com preço" usa `status = 'cotado'` — o MESMO critério de
    `resumo_do_dia`. Se aqui contasse `aguardando_retorno` também, o número
    do gráfico e o do cartão do topo discordariam na mesma tela."""
    unidade = unidade_do_periodo(dias)
    agora = datetime.now()
    inicio = _inicio_do_balde(agora, dias, unidade)

    if unidade == "mes":
        # Em meses a janela é longa demais para desenhar inteira: começa no
        # mês da cotação mais antiga que existe, e não em dez anos atrás.
        primeiro = con.execute(
            "SELECT MIN(criado_em) AS m FROM cotacao WHERE criado_em >= ?",
            (_desde(dias),)).fetchone()["m"]
        # Fatiar em vez de fromisoformat: `criado_em` é TEXTO, e uma linha
        # torta derrubaria a tela inteira em vez de sumir de um gráfico.
        if primeiro and len(primeiro) >= 7:
            try:
                inicio = min(inicio, datetime(int(primeiro[:4]),
                                              int(primeiro[5:7]), 1))
            except ValueError:
                pass

    corte = inicio.isoformat(timespec="seconds")
    # O `{tamanho}` no SQL vem de _TAMANHO[unidade], e `unidade` só pode ser
    # uma das três de unidade_do_periodo(). Nada de fora entra nesta string.
    tamanho = _TAMANHO[unidade]
    totais = {r["chave"]: r["n"] for r in con.execute(
        f"SELECT substr(criado_em, 1, {tamanho}) AS chave, COUNT(*) AS n"
        " FROM cotacao WHERE criado_em >= ? GROUP BY chave", (corte,))}
    com_preco = {r["chave"]: r["n"] for r in con.execute(
        f"SELECT substr(c.criado_em, 1, {tamanho}) AS chave,"
        " COUNT(DISTINCT c.id) AS n FROM cotacao c"
        " JOIN resultado r ON r.cotacao_id = c.id"
        " WHERE c.criado_em >= ? AND r.status = 'cotado' GROUP BY chave",
        (corte,))}

    return {"unidade": unidade, "pontos": [
        {"chave": chave, "cotacoes": totais.get(chave, 0),
         "com_preco": com_preco.get(chave, 0)}
        for chave in _chaves(inicio, agora, unidade)]}


def por_usuario(con: sqlite3.Connection, dias: int,
                limite: int = 8) -> list[dict]:
    """Quem cotou quanto no período, do mais ativo para o menos.

    Desempate por nome: sem ele, dois vendedores com a mesma contagem trocam
    de lugar entre dois carregamentos e a lista parece estar mexendo
    sozinha."""
    return [{"usuario": r["usuario"], "cotacoes": r["n"]}
            for r in con.execute(
                "SELECT usuario, COUNT(*) AS n FROM cotacao"
                " WHERE criado_em >= ? GROUP BY usuario"
                " ORDER BY n DESC, usuario LIMIT ?", (_desde(dias), limite))]
