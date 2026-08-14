"""Histórico de cotações em SQLite.

SQLite porque é da biblioteca padrão: um arquivo, zero servidor, zero
dependência nova. Para o volume disto — algumas dezenas de cotações por dia,
uma empresa — não há nada que um banco maior resolveria melhor.

Dinheiro e peso são guardados como TEXTO e devolvidos como Decimal. Float
acumula erro de arredondamento, e frete é dinheiro de cliente.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

CAMINHO_PADRAO = Path("cotafrete.db")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cotacao (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario         TEXT NOT NULL,
    criado_em       TEXT NOT NULL,
    cep_origem      TEXT NOT NULL,
    cep_destino     TEXT NOT NULL,
    cidade_origem   TEXT,
    uf_origem       TEXT,
    cidade_destino  TEXT,
    uf_destino      TEXT,
    peso_kg         TEXT NOT NULL,
    quantidade      INTEGER NOT NULL,
    comprimento_cm  INTEGER NOT NULL,
    largura_cm      INTEGER NOT NULL,
    altura_cm       INTEGER NOT NULL,
    valor_nf        TEXT NOT NULL,
    material        TEXT,
    cnpj_remetente     TEXT,
    cnpj_destinatario  TEXT,
    cnpj_pagador       TEXT,
    nome_remetente     TEXT,
    nome_destinatario  TEXT,
    nome_pagador       TEXT
);

CREATE TABLE IF NOT EXISTS resultado (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cotacao_id     INTEGER NOT NULL REFERENCES cotacao(id) ON DELETE CASCADE,
    transportadora TEXT NOT NULL,
    status         TEXT NOT NULL,
    valor          TEXT,
    protocolo      TEXT,
    prazo          TEXT,
    erro           TEXT,
    evidencia      TEXT
);

CREATE INDEX IF NOT EXISTS idx_cotacao_usuario ON cotacao(usuario, id DESC);
CREATE INDEX IF NOT EXISTS idx_resultado_cotacao ON resultado(cotacao_id);
"""

CAMPOS_CARGA = (
    "cep_origem", "cep_destino", "cidade_origem", "uf_origem",
    "cidade_destino", "uf_destino", "peso_kg", "quantidade",
    "comprimento_cm", "largura_cm", "altura_cm", "valor_nf", "material",
    "cnpj_remetente", "cnpj_destinatario", "cnpj_pagador",
    "nome_remetente", "nome_destinatario", "nome_pagador",
)


def _decimal(valor: str | None) -> Decimal | None:
    return Decimal(valor) if valor not in (None, "") else None


class Banco:
    def __init__(self, caminho: Path | str = CAMINHO_PADRAO) -> None:
        self.caminho = Path(caminho)
        if self.caminho.parent != Path(""):
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._conectar() as con:
            con.executescript(ESQUEMA)

    def _conectar(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.caminho)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    # ------------------------------------------------------------ escrita
    def salvar_cotacao(self, usuario: str, carga: dict[str, Any]) -> int:
        """Grava a carga e devolve o id. Os resultados vêm depois, um por
        transportadora, conforme cada uma responde."""
        valores = [usuario, datetime.now().isoformat(timespec="seconds")]
        valores += [str(carga.get(c)) if carga.get(c) is not None else None
                    for c in CAMPOS_CARGA]
        colunas = "usuario, criado_em, " + ", ".join(CAMPOS_CARGA)
        marcas = ", ".join("?" * (len(CAMPOS_CARGA) + 2))
        with self._conectar() as con:
            cur = con.execute(
                f"INSERT INTO cotacao ({colunas}) VALUES ({marcas})", valores)
            return int(cur.lastrowid)

    def salvar_resultado(self, cotacao_id: int, transportadora: str, *,
                         status: str, valor: Decimal | None = None,
                         protocolo: str | None = None,
                         prazo: str | None = None,
                         erro: str | None = None,
                         evidencia: str | None = None) -> None:
        with self._conectar() as con:
            con.execute(
                "INSERT INTO resultado (cotacao_id, transportadora, status,"
                " valor, protocolo, prazo, erro, evidencia)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cotacao_id, transportadora, status,
                 str(valor) if valor is not None else None,
                 protocolo, prazo, erro, evidencia))

    # ------------------------------------------------------------ leitura
    def listar_cotacoes(self, usuario: str, limite: int = 100) -> list[dict]:
        """Mais recentes primeiro, já com o melhor preço de cada uma.

        O melhor preço vem na listagem para não obrigar a abrir uma por uma
        só para lembrar qual saiu mais barata."""
        with self._conectar() as con:
            linhas = con.execute(
                "SELECT * FROM cotacao WHERE usuario = ?"
                " ORDER BY id DESC LIMIT ?", (usuario, limite)).fetchall()
            saida = []
            for linha in linhas:
                c = dict(linha)
                precos = con.execute(
                    "SELECT valor FROM resultado"
                    " WHERE cotacao_id = ? AND valor IS NOT NULL",
                    (c["id"],)).fetchall()
                valores = [Decimal(p["valor"]) for p in precos]
                c["melhor_preco"] = min(valores) if valores else None
                c["peso_kg"] = _decimal(c["peso_kg"])
                c["valor_nf"] = _decimal(c["valor_nf"])
                saida.append(c)
            return saida

    def buscar_cotacao(self, cotacao_id: int, usuario: str) -> dict | None:
        """Devolve None se a cotação for de OUTRO usuário.

        O usuário entra na consulta de propósito: sem isso, trocar o número
        na URL daria acesso à cotação alheia."""
        with self._conectar() as con:
            linha = con.execute(
                "SELECT * FROM cotacao WHERE id = ? AND usuario = ?",
                (cotacao_id, usuario)).fetchone()
            if linha is None:
                return None
            c = dict(linha)
            c["peso_kg"] = _decimal(c["peso_kg"])
            c["valor_nf"] = _decimal(c["valor_nf"])
            c["resultados"] = [
                {**dict(r), "valor": _decimal(r["valor"])}
                for r in con.execute(
                    "SELECT * FROM resultado WHERE cotacao_id = ? ORDER BY id",
                    (cotacao_id,)).fetchall()
            ]
            return c

    def usuarios(self) -> list[str]:
        with self._conectar() as con:
            return [r[0] for r in con.execute(
                "SELECT DISTINCT usuario FROM cotacao ORDER BY usuario")]
