"""Consultas DAV completas; HTML e autorização das rotas ficam em web/."""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta

from mercado_eletronico.painel import hora_de_brasilia
from orcamento.diagnostico import diagnostico

ESTADOS = {"rascunho", "fila", "gerando", "pronto", "erro", "incerto", "simulado", "rejeitado"}


def resolvidas(con, ids: list[int], usuario: str | None) -> dict[int, int]:
    if not ids:
        return {}
    marcas = ",".join("?" for _ in ids)
    linhas = con.execute(
        f"WITH RECURSIVE cadeia(origem, id, usuario) AS ("
        f" SELECT id, id, usuario FROM dav WHERE id IN ({marcas})"
        " AND (? IS NULL OR usuario = ?) UNION "
        " SELECT a.origem, d.id, a.usuario FROM cadeia a"
        " JOIN dav_correcao c ON c.origem_id = a.id"
        " JOIN dav d ON d.id = c.destino_id AND d.usuario = a.usuario)"
        " SELECT a.origem, MAX(d.id) AS destino FROM cadeia a JOIN dav d ON d.id = a.id"
        " WHERE d.estado = 'pronto' AND d.id <> a.origem GROUP BY a.origem",
        (*ids, usuario, usuario))
    return {r["origem"]: r["destino"] for r in linhas}


def posicao_na_fila(con, dav_id: int) -> int | None:
    d = con.execute("SELECT estado FROM dav WHERE id = ?", (dav_id,)).fetchone()
    if not d or d["estado"] != "fila":
        return None
    return con.execute("SELECT COUNT(*) FROM dav WHERE estado = 'fila' AND id <= ?", (dav_id,)).fetchone()[0]


def consultar(con, *, usuario: str | None, dias: int, agora: datetime,
              estado: str = "", vendedor: str = "", busca: str = "", pagina: int = 1,
              categoria: str = "") -> dict:
    dias = dias if dias in (1, 7, 30) else 1
    agora = hora_de_brasilia(agora)
    inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=dias - 1)
    sql = "SELECT * FROM dav WHERE criado_em >= ? AND criado_em <= ?"
    args = [inicio.isoformat(timespec="seconds"), agora.isoformat(timespec="seconds")]
    if usuario is not None:
        sql += " AND usuario = ?"
        args.append(usuario)
    elif vendedor:
        sql += " AND usuario = ?"
        args.append(vendedor)
    linhas = [dict(r) for r in con.execute(sql + " ORDER BY criado_em DESC, id DESC", args)]
    if busca:
        q = busca.casefold()
        linhas = [d for d in linhas if q in " ".join(str(d.get(c) or "") for c in
                  ("cliente", "usuario", "arquivo", "numero")).casefold()]
    contagem = Counter(d["estado"] for d in linhas)
    diags = {d["id"]: diagnostico(d, administrador=False) for d in linhas}
    criados = [d for d in linhas if d["estado"] == "pronto"]
    resumo = {"tentativas": sum(contagem[e] for e in ("pronto", "erro", "incerto", "fila", "gerando")),
              "criados": contagem["pronto"], "falhas": contagem["erro"], "incertos": contagem["incerto"],
              "em_andamento": contagem["fila"] + contagem["gerando"], "fila": contagem["fila"],
              "gerando": contagem["gerando"], "rejeitados": contagem["rejeitado"],
              "com_aviso": sum(diags[d["id"]]["tem_aviso"] is True for d in criados),
              "avisos_desconhecidos": sum(diags[d["id"]]["tem_aviso"] is None for d in criados),
              "inesperados": sum(n for e, n in contagem.items() if e not in ESTADOS)}
    grupos = Counter(diags[d["id"]]["categoria"] for d in linhas if d["estado"] == "erro")
    atencao = [d for d in linhas if d["estado"] in ("incerto", "rejeitado") or
               (d["estado"] == "erro" and diags[d["id"]]["salvamento"] == "incerto")]
    if estado == "com_aviso":
        linhas = [d for d in criados if diags[d["id"]]["tem_aviso"] is True]
    elif estado:
        linhas = [d for d in linhas if d["estado"] == estado]
    if categoria:
        linhas = [d for d in linhas if diags[d["id"]]["categoria"] == categoria]
    total = len(linhas)
    paginas = max(1, math.ceil(total / 25))
    pagina = min(max(1, pagina), paginas)
    pagina_linhas = linhas[(pagina - 1) * 25:pagina * 25]
    resolucao = resolvidas(con, [d["id"] for d in pagina_linhas], usuario)
    for d in pagina_linhas:
        d["resolvida_por"] = resolucao.get(d["id"])
    vendedores = ([r[0] for r in con.execute("SELECT DISTINCT usuario FROM dav ORDER BY usuario")]
                  if usuario is None else [])
    return {"resumo": resumo, "atencao": atencao, "grupos": dict(grupos),
            "linhas": pagina_linhas, "total": total, "pagina": pagina, "paginas": paginas,
            "vendedores": vendedores, "periodo": {"dias": dias, "inicio": inicio.isoformat(),
                                                      "fim": agora.isoformat()}}
