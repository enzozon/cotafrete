"""Os números do Mercado Eletrônico para o painel do administrador (/adm/me).

Mesma divisão de `core/painel.py`: aqui só consulta (recebe a conexão, devolve
dados), a tela mora em `web/adm_me.py`. O objetivo é o administrador saber o
que está acontecendo nas cotações do ME — erros do robô, leitura falhando,
rascunho salvo esquecido perto do prazo — sem precisar entrar no ME.

Horários: tudo em hora de Brasília sem fuso, como o resto do banco.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from core.painel import (_TAMANHO, _assinatura, _chaves, _desde, _inicio_do_balde,
                         unidade_do_periodo)
from mercado_eletronico import painel as pn

# O que no histórico de uma cotação é PROBLEMA. Fica numa lista só porque o
# filtro "só problemas", a contagem do topo e o destaque da linha precisam
# concordar — três listas diferentes discordariam na primeira mudança.
EVENTOS_PROBLEMA = (
    "erro do robô",
    "erro ao ler itens do ME",
    "revisão IA indisponível",
    "teste sem salvar: falhou",
)
ABERTOS = tuple(s.value for s in pn.ABERTOS)
NOME_CONTA = {"ventura": "VENTURA", "uniao": "UNIÃO"}


def _nome(conta: str) -> str:
    return NOME_CONTA.get(conta, conta.upper())
JANELA = pn.JANELA_URGENTE


def _dt(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def _abertas(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        f"SELECT * FROM me_cotacao WHERE status IN ({','.join('?' * len(ABERTOS))})"
        " AND na_lista = 1", ABERTOS)]


def resumo(con: sqlite3.Connection, agora: datetime) -> dict:
    """Os quatro números do topo."""
    abertas = _abertas(con)
    urgentes = [c for c in abertas
                if (lim := _dt(c["data_limite"])) and agora < lim <= agora + JANELA]
    return {
        "abertas": len(abertas),
        "salvas": sum(c["status"] == "salva" for c in abertas),
        "erros": sum(c["status"] == "erro" for c in abertas),
        "urgentes": len(urgentes),
    }


def leitura_por_conta(con: sqlite3.Connection, contas: tuple[str, ...]) -> list[dict]:
    """A saúde da leitura da lista do ME, conta por conta.

    `falhas_seguidas` conta de trás para frente até a última leitura boa: é o
    número que diz se é tropeço (1) ou se a leitura parou de vez (10)."""
    saida = []
    for conta in contas:
        linhas = [dict(r) for r in con.execute(
            "SELECT * FROM me_varredura WHERE conta = ? ORDER BY id DESC LIMIT 200", (conta,))]
        seguidas = 0
        for l in linhas:
            if l["ok"]:
                break
            seguidas += 1
        ultima_ok = next((l for l in linhas if l["ok"]), None)
        saida.append({
            "conta": conta,
            "ultima": linhas[0] if linhas else None,
            "ultima_ok": ultima_ok,
            "falhas_seguidas": seguidas,
            "desde": linhas[seguidas - 1]["quando"] if seguidas else None,
            "ultimo_erro": linhas[0]["erro"] if seguidas else None,
        })
    return saida


def atencao(con: sqlite3.Connection, agora: datetime, contas: tuple[str, ...]) -> list[dict]:
    """O que precisa de alguém, do mais grave para o menos.

    Cada item: nivel (critico/atencao), titulo, detalhe e, quando é de uma
    cotação, o id dela para o link."""
    itens = []
    for l in leitura_por_conta(con, contas):
        if l["falhas_seguidas"]:
            itens.append({
                "nivel": "critico" if l["falhas_seguidas"] >= 3 else "atencao",
                "titulo": f"Leitura do ME falhando — {_nome(l['conta'])}",
                "detalhe": (f"{l['falhas_seguidas']} vez(es) seguidas desde "
                            f"{_hora(l['desde'])}: {l['ultimo_erro'] or ''}"),
                "cid": None})
    for c in _abertas(con):
        lim = _dt(c["data_limite"])
        falta = pn.prazo(lim, agora)
        rotulo = f"{c['numero']} · {_nome(c['conta'])}"
        if c["status"] == "erro":
            itens.append({"nivel": "critico", "titulo": f"Robô falhou — {rotulo}",
                          "detalhe": f"{c['erro'] or ''} (fecha em {falta.texto})",
                          "cid": c["id"]})
        elif lim and agora < lim <= agora + JANELA:
            if c["status"] == "salva":
                itens.append({"nivel": "critico",
                              "titulo": f"Salva no ME mas NÃO enviada — {rotulo}",
                              "detalhe": f"fecha em {falta.texto}", "cid": c["id"]})
            elif c["status"] == "pendente":
                itens.append({"nivel": "atencao", "titulo": f"Ainda sem resposta — {rotulo}",
                              "detalhe": f"fecha em {falta.texto}", "cid": c["id"]})
    itens.sort(key=lambda i: i["nivel"] != "critico")
    return itens


def cotacoes(con: sqlite3.Connection, dias: int, conta: str | None = None,
             status: str | None = None) -> list[dict]:
    """As cotações do período (vistas desde `dias` atrás) e todas as abertas."""
    sql = ("SELECT c.*, (SELECT COUNT(*) FROM me_item i WHERE i.cotacao_id = c.id) AS n_itens,"
           " (SELECT COUNT(*) FROM me_item i WHERE i.cotacao_id = c.id"
           "  AND COALESCE(i.preco, '') <> '') AS n_com_preco,"
           " (SELECT COUNT(*) FROM me_historico h WHERE h.cotacao_id = c.id AND h.evento IN"
           f"  ({','.join('?' * len(EVENTOS_PROBLEMA))})) AS n_problemas"
           " FROM me_cotacao c WHERE (c.visto_em >= ? OR c.status IN"
           f" ({','.join('?' * len(ABERTOS))}))")
    args: list = [*EVENTOS_PROBLEMA, _desde(dias), *ABERTOS]
    if conta:
        sql += " AND c.conta = ?"
        args.append(conta)
    if status:
        sql += " AND c.status = ?"
        args.append(status)
    sql += (" ORDER BY c.status IN ('enviada', 'recusada', 'vencida'),"
            " c.data_limite IS NULL, c.data_limite DESC")
    return [dict(r) for r in con.execute(sql, args)]


def eventos(con: sqlite3.Connection, dias: int, conta: str | None = None,
            so_problemas: bool = False, limite: int = 400) -> list[dict]:
    """O histórico de TODAS as cotações do ME, mais novo primeiro, junto com
    as leituras da lista que falharam (elas não pertencem a uma cotação)."""
    sql = ("SELECT h.id, h.quando, h.usuario, h.evento, h.detalhe, c.id AS cid,"
           " c.numero, c.conta FROM me_historico h JOIN me_cotacao c ON c.id = h.cotacao_id"
           " WHERE h.quando >= ?")
    args: list = [_desde(dias)]
    if conta:
        sql += " AND c.conta = ?"
        args.append(conta)
    if so_problemas:
        sql += f" AND h.evento IN ({','.join('?' * len(EVENTOS_PROBLEMA))})"
        args += EVENTOS_PROBLEMA
    linhas = [dict(r) | {"problema": r["evento"] in EVENTOS_PROBLEMA}
              for r in con.execute(sql + " ORDER BY h.id DESC LIMIT ?", (*args, limite))]

    sql_v = "SELECT * FROM me_varredura WHERE ok = 0 AND quando >= ?"
    args_v: list = [_desde(dias)]
    if conta:
        sql_v += " AND conta = ?"
        args_v.append(conta)
    for v in con.execute(sql_v + " ORDER BY id DESC LIMIT ?", (*args_v, limite)):
        linhas.append({"id": None, "quando": v["quando"], "usuario": None,
                       "evento": "falha ao ler a lista do ME", "detalhe": v["erro"],
                       "cid": None, "numero": None, "conta": v["conta"], "problema": True})
    linhas.sort(key=lambda l: l["quando"], reverse=True)
    return linhas[:limite]


def serie(con: sqlite3.Connection, dias: int) -> dict:
    """Cotações que apareceram no ME × salvas pelo robô, por balde de tempo."""
    unidade = unidade_do_periodo(dias)
    agora = datetime.now()
    inicio = _inicio_do_balde(agora, dias, unidade)
    corte = inicio.isoformat(timespec="seconds")
    tamanho = _TAMANHO[unidade]   # só valores fixos de core/painel entram no SQL
    novas = {r["k"]: r["n"] for r in con.execute(
        f"SELECT substr(visto_em, 1, {tamanho}) AS k, COUNT(*) AS n FROM me_cotacao"
        " WHERE visto_em >= ? GROUP BY k", (corte,))}
    salvas = {r["k"]: r["n"] for r in con.execute(
        f"SELECT substr(quando, 1, {tamanho}) AS k, COUNT(DISTINCT cotacao_id) AS n"
        " FROM me_historico WHERE evento = 'salva no ME' AND quando >= ? GROUP BY k", (corte,))}
    return {"unidade": unidade, "pontos": [
        {"chave": k, "cotacoes": novas.get(k, 0), "com_preco": salvas.get(k, 0)}
        for k in _chaves(inicio, agora, unidade)]}


def quem_salvou(con: sqlite3.Connection, dias: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT usuario, COUNT(DISTINCT cotacao_id) AS salvas FROM me_historico"
        " WHERE evento = 'salva no ME' AND quando >= ? AND usuario IS NOT NULL"
        " GROUP BY usuario ORDER BY salvas DESC LIMIT 8", (_desde(dias),))]


def versao(con: sqlite3.Connection) -> str:
    """Muda quando entra evento, leitura ou cotação: o painel só se redesenha aí."""
    return _assinatura(*con.execute(
        "SELECT (SELECT COALESCE(MAX(id), 0) FROM me_historico),"
        "       (SELECT COALESCE(MAX(id), 0) FROM me_varredura),"
        "       (SELECT COUNT(*) FROM me_cotacao),"
        "       (SELECT COALESCE(MAX(atualizado_em), '') FROM me_cotacao)").fetchone())


def _hora(iso: str | None) -> str:
    d = _dt(iso)
    return d.strftime("%d/%m %H:%M") if d else "—"
