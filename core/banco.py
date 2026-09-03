"""Histórico de cotações em SQLite.

SQLite porque é da biblioteca padrão: um arquivo, zero servidor, zero
dependência nova. Para o volume disto — algumas dezenas de cotações por dia,
uma empresa — não há nada que um banco maior resolveria melhor.

Dinheiro e peso são guardados como TEXTO e devolvidos como Decimal. Float
acumula erro de arredondamento, e frete é dinheiro de cliente.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.retentativa import ESPERA_MAXIMA_S

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
    nome_pagador       TEXT,
    -- Onde a resposta da Generoso vai cair. Ela confirma o recebimento na
    -- tela e manda o preço por e-mail depois; sem guardar o endereço, a tela
    -- final não teria como dizer qual caixa o vendedor precisa abrir.
    email              TEXT,
    -- cif = paga o remetente, fob = paga o destinatario. Guardado para
    -- a mensagem do WhatsApp e para repetir a cotacao do mesmo jeito.
    tipo_frete         TEXT
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
    evidencia      TEXT,
    -- Quando a transportadora respondeu. NULL nas linhas anteriores a
    -- 28/08/2026, e a tela precisa dizer "sem dados ainda" em vez de zero.
    --
    -- Os adapters gravam datetime.now() só na tentativa BEM-SUCEDIDA (ver,
    -- por exemplo, carriers/camilo/adapter.py) — então respondido_em -
    -- criado_em inclui as esperas de QUALQUER retentativa que veio antes
    -- daquela. Quem for calcular "qual transportadora está lenta" na Fase 2
    -- vai culpar a transportadora pela nossa própria retentativa se não
    -- descontar isso.
    respondido_em  TEXT
);

-- Conversa de WhatsApp ABERTA. Nunca "enviada": o sistema abre a conversa
-- com o texto pronto, mas quem aperta enviar é a pessoa, do outro lado, e
-- disso aqui não chega notícia nenhuma. Registrar como "enviado" criaria a
-- pior cotação possível — a que todo mundo acha que saiu e não saiu.
--
-- UNIQUE porque reabrir é normal (fechou sem querer, voltou para conferir) e
-- não pode inflar a contagem. Com INSERT OR IGNORE, a hora guardada é a da
-- PRIMEIRA vez, que é a que diz quando a transportadora foi acionada.
CREATE TABLE IF NOT EXISTS whatsapp_aberto (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cotacao_id     INTEGER NOT NULL REFERENCES cotacao(id) ON DELETE CASCADE,
    transportadora TEXT NOT NULL,
    usuario        TEXT NOT NULL,
    aberto_em      TEXT NOT NULL,
    UNIQUE (cotacao_id, transportadora)
);

CREATE INDEX IF NOT EXISTS idx_cotacao_usuario ON cotacao(usuario, id DESC);
CREATE INDEX IF NOT EXISTS idx_resultado_cotacao ON resultado(cotacao_id);
"""

CAMPOS_CARGA = (
    "cep_origem", "cep_destino", "cidade_origem", "uf_origem",
    "cidade_destino", "uf_destino", "peso_kg", "quantidade",
    "comprimento_cm", "largura_cm", "altura_cm", "valor_nf", "material",
    "cnpj_remetente", "cnpj_destinatario", "cnpj_pagador",
    "nome_remetente", "nome_destinatario", "nome_pagador", "email",
    # Quem pediu a cotação, não quem envia/recebe a carga. Guardado por causa
    # do bookmarklet da Della Volpe: sem isto, "Nome completo" e "WhatsApp"
    # do formulário deles ficavam perdidos depois do /cotar terminar — só
    # existiam no POST original, igual o e-mail antes de 20/08/2026.
    "nome_solicitante", "whatsapp_solicitante",
    "tipo_frete",
    # Quem participa desta cotação. NULL = todas — ver core/selecao.py, que
    # explica por que ausência e escolha vazia precisam ser coisas distintas.
    "transportadoras",
)

# Colunas de `resultado` que nasceram depois do banco. Mesma razão de
# CAMPOS_CARGA: CREATE TABLE IF NOT EXISTS não altera tabela existente.
CAMPOS_RESULTADO = ("respondido_em",)


def _decimal(valor: str | None) -> Decimal | None:
    return Decimal(valor) if valor not in (None, "") else None


class Banco:
    def __init__(self, caminho: Path | str = CAMINHO_PADRAO) -> None:
        self.caminho = Path(caminho)
        if self.caminho.parent != Path(""):
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conectar()) as con, con:
            con.executescript(ESQUEMA)
            self._migrar(con)

    @staticmethod
    def _migrar(con: sqlite3.Connection) -> None:
        """Acrescenta colunas que passaram a existir depois do banco.

        CREATE TABLE IF NOT EXISTS não altera tabela existente: sem isto,
        quem já tinha cotafrete.db recebia "table cotacao has no column named
        cnpj_remetente" no primeiro INSERT. Acontece toda vez que o esquema
        cresce, então a checagem fica permanente."""
        existentes = {r["name"] for r in con.execute("PRAGMA table_info(cotacao)")}
        for coluna in CAMPOS_CARGA:
            if coluna not in existentes:
                con.execute(f"ALTER TABLE cotacao ADD COLUMN {coluna} TEXT")

        existentes = {r["name"] for r in con.execute("PRAGMA table_info(resultado)")}
        for coluna in CAMPOS_RESULTADO:
            if coluna not in existentes:
                con.execute(f"ALTER TABLE resultado ADD COLUMN {coluna} TEXT")

        # UMA linha por transportadora por cotação. Sem esta regra o banco
        # aceitava duas, e a tela desenhava as duas: foi assim que a #50
        # (24/08/2026) mostrou "O sistema foi fechado durante a cotação" ao
        # lado do resultado real da mesma Translovato, que tinha cotado
        # R$ 338,40. O mesmo já tinha acontecido na #17.
        #
        # Fica no _migrar e não no ESQUEMA porque o índice não nasce num
        # banco que já tem duplicata: primeiro apaga, depois cria. Mantém o
        # MAIOR id de cada par — quem escreveu por último sabia mais.
        con.execute(
            "DELETE FROM resultado WHERE id NOT IN ("
            " SELECT MAX(id) FROM resultado GROUP BY cotacao_id, transportadora)")
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS resultado_unico"
            " ON resultado (cotacao_id, transportadora)")

    def _conectar(self) -> sqlite3.Connection:
        """Sempre use com `closing(...)`: o `with` do sqlite3 faz commit e
        rollback, mas NÃO fecha a conexão. Cada cotação abre cinco delas."""
        con = sqlite3.connect(self.caminho)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        # WAL: leitor e escritor deixam de brigar pelo arquivo. Sem isso o
        # monitor (monitorar.py), que lê o banco enquanto as cotações gravam,
        # leva "database is locked" na hora de maior movimento — justo quando
        # olhar o monitor importa. Fica gravado no arquivo, basta uma vez.
        con.execute("PRAGMA journal_mode = WAL")
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
        with closing(self._conectar()) as con, con:
            cur = con.execute(
                f"INSERT INTO cotacao ({colunas}) VALUES ({marcas})", valores)
            return int(cur.lastrowid)

    def salvar_resultado(self, cotacao_id: int, transportadora: str, *,
                         status: str, valor: Decimal | None = None,
                         protocolo: str | None = None,
                         prazo: str | None = None,
                         erro: str | None = None,
                         evidencia: str | None = None,
                         respondido_em: str | None = None) -> None:
        # Sobrescreve em vez de acrescentar: a transportadora que responde
        # depois de ter sido dada como interrompida precisa APAGAR o aviso,
        # não conviver com ele. Ver o índice resultado_unico em _migrar.
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT INTO resultado (cotacao_id, transportadora, status,"
                " valor, protocolo, prazo, erro, evidencia, respondido_em)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (cotacao_id, transportadora) DO UPDATE SET"
                " status = excluded.status, valor = excluded.valor,"
                " protocolo = excluded.protocolo, prazo = excluded.prazo,"
                " erro = excluded.erro, evidencia = excluded.evidencia,"
                " respondido_em = excluded.respondido_em",
                (cotacao_id, transportadora, status,
                 str(valor) if valor is not None else None,
                 protocolo, prazo, erro, evidencia, respondido_em))

    def marcar_whatsapp_aberto(self, cotacao_id: int, transportadora: str,
                               usuario: str) -> None:
        """Registra que a conversa foi ABERTA com o texto pronto.

        OR IGNORE, não REPLACE: reabrir não pode reescrever a hora da
        primeira vez nem duplicar a linha."""
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT OR IGNORE INTO whatsapp_aberto"
                " (cotacao_id, transportadora, usuario, aberto_em)"
                " VALUES (?, ?, ?, ?)",
                (cotacao_id, transportadora, usuario,
                 datetime.now().isoformat(timespec="seconds")))

    def whatsapp_abertos(self, cotacao_id: int) -> set[str]:
        """Só os slugs — é o que a tela precisa para marcar cada linha."""
        with closing(self._conectar()) as con, con:
            return {r["transportadora"] for r in con.execute(
                "SELECT transportadora FROM whatsapp_aberto"
                " WHERE cotacao_id = ?", (cotacao_id,))}

    def whatsapp_detalhado(self, cotacao_id: int) -> list[dict]:
        """Com hora e usuário, para o monitor e para conferir depois."""
        with closing(self._conectar()) as con, con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM whatsapp_aberto WHERE cotacao_id = ?"
                " ORDER BY id", (cotacao_id,))]

    # ------------------------------------------------------------ leitura
    def listar_cotacoes(self, usuario: str, limite: int = 100) -> list[dict]:
        """Mais recentes primeiro, já com o melhor preço de cada uma.

        O melhor preço vem na listagem para não obrigar a abrir uma por uma
        só para lembrar qual saiu mais barata."""
        with closing(self._conectar()) as con, con:
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
        with closing(self._conectar()) as con, con:
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

    def marcar_interrompidas(self, esperadas: dict[str, str]) -> int:
        """Fecha cotações que ficaram sem resposta porque o sistema caiu.

        As transportadoras rodam em threads DENTRO do processo: fechar a
        janela mata as threads no meio do caminho. Sem isto o cartão fica
        "cotando..." para sempre e a página recarrega esperando um resultado
        que ninguém mais vai gravar.

        SÓ mexe no que já passou do teto de espera. A versão anterior mexia
        em tudo, apoiada na ideia de que "roda na subida do servidor, quando
        por definição nada está em andamento" — e essa premissa é falsa:
        `web/app.py` executa isto no IMPORT, então qualquer segundo processo
        na mesma pasta (pytest, um script solto, um segundo servidor) mata as
        cotações vivas do primeiro. Foi o que matou a #50 em 24/08/2026.

        `esperadas` mapeia slug -> desde quando essa automática existe (ISO
        8601), não só a lista de slugs. Cotação criada ANTES disso nunca teve
        chance de ser cotada por ela — sem essa data, toda vez que uma
        automática nova entra em produção esta varredura volta a TODO o
        histórico e carimba "sistema fechado no meio" numa transportadora que
        nunca chegou a ser chamada. Foi o que aconteceu com a Braspress em
        02-03/09/2026: 118 linhas fantasma, corrigidas na mão por não existir
        esta trava ainda.

        Passado o teto, a cotação está morta de qualquer jeito — a tela já
        parou de esperar por ela — e aí a linha só explica o porquê."""
        limite = (datetime.now() - timedelta(seconds=ESPERA_MAXIMA_S)
                  ).isoformat(timespec="seconds")
        marcadas = 0
        with closing(self._conectar()) as con, con:
            for linha in con.execute(
                    "SELECT id, criado_em FROM cotacao WHERE criado_em < ?",
                    (limite,)).fetchall():
                jah = {r["transportadora"] for r in con.execute(
                    "SELECT transportadora FROM resultado WHERE cotacao_id = ?",
                    (linha["id"],))}
                for slug, desde in esperadas.items():
                    if slug in jah or linha["criado_em"] < desde:
                        continue
                    con.execute(
                        "INSERT INTO resultado (cotacao_id, transportadora,"
                        " status, erro) VALUES (?, ?, 'interrompido', ?)",
                        (linha["id"], slug,
                         "O sistema foi fechado durante a cotação."))
                    marcadas += 1
        return marcadas

    def usuarios(self) -> list[str]:
        with closing(self._conectar()) as con, con:
            return [r[0] for r in con.execute(
                "SELECT DISTINCT usuario FROM cotacao ORDER BY usuario")]
