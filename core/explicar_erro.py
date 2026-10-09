"""Explicar em UMA frase o erro que ninguém traduziu (sugestão 2, 24/09/2026).

O cartão da cotação mostra `mensagem_amigavel()` (web/app.py) antes do texto
técnico. Quando ela devolve None — o erro é novo, ninguém escreveu a frase —
o vendedor lia só "TimeoutError: Locator.click...". Aqui a IA escreve a frase.

Regras:
- Uma explicação por TIPO de erro: a chave é a transportadora + a mensagem sem
  números (`resumo_erros._chave`). O mesmo timeout com outro CEP não gasta
  pedido de novo.
- Como a frase vale para todas as variações do erro, ela NÃO pode ter número
  nenhum: o validador descarta (vai para o próximo modelo da cadeia).
- Nunca na hora de abrir a página: `explicar_em_fundo` dispara uma thread e o
  cartão mostra a frase quando ela estiver guardada. A IA fora do ar não
  atrasa nem quebra o cartão; o texto técnico continua lá, sempre.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime
from typing import Callable

from core import ia
from core.resumo_erros import _chave

FUNCAO = "explicar erro"
MAX_FRASE = 260
# Desligada nos testes (tests/conftest.py): abrir uma cotação com erro num
# teste não pode chamar a IA de verdade com a chave do .env da máquina.
LIGADA = True

SISTEMA = """Você explica para um vendedor, em português simples, por que um robô
não conseguiu cotar o frete no site de uma transportadora. Escreva UMA frase
curta (até 200 caracteres): o que provavelmente houve e o que o vendedor pode
fazer (repetir a cotação, conferir CEP/CNPJ/medidas, ou cotar pelo WhatsApp).
Não use números. Não invente detalhes que a mensagem não sugere; se a causa
não estiver clara, diga que foi uma falha no site ou no robô e sugira repetir.
Responda em JSON: {"frase": "..."}"""

ESQUEMA = {
    "type": "object",
    "properties": {"frase": {"type": "string"}},
    "required": ["frase"],
    "additionalProperties": False,
}

# chave → quando foi pedida. Falhou: a chave fica até ESPERA_FALHA_S, senão
# cada abertura da cotação (que se recarrega sozinha) gastaria a cota grátis.
ESPERA_FALHA_S = 30 * 60
_pedidos: dict[str, float] = {}
_trava = threading.Lock()


def chave(slug: str, erro: str | None) -> str:
    return f"{slug}|{_chave(erro)}"


def _criar_tabela(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS erro_explicado ("
                " chave TEXT PRIMARY KEY, frase TEXT NOT NULL, modelo TEXT,"
                " criado_em TEXT NOT NULL)")


def guardada(con: sqlite3.Connection, slug: str, erro: str | None) -> str | None:
    _criar_tabela(con)
    r = con.execute("SELECT frase FROM erro_explicado WHERE chave = ?",
                    (chave(slug, erro),)).fetchone()
    return r[0] if r else None


def _validar(dados) -> str:
    frase = " ".join(str((dados or {}).get("frase") or "").split())
    if not frase or len(frase) > MAX_FRASE:
        raise ValueError("frase vazia ou longa demais")
    if re.search(r"\d", frase):
        raise ValueError("frase com número (vale para o tipo de erro, não para este)")
    return frase


def pedir(nome: str, erro: str) -> ia.Resposta:
    """Levanta ia.IAIndisponivel se nenhum modelo der uma frase que passe."""
    return ia.completar_json(SISTEMA, f"Transportadora: {nome}\nMensagem do robô: {erro[:600]}",
                             ESQUEMA, funcao=FUNCAO, validar=_validar, max_tokens=300)


def explicar(conectar: Callable[[], sqlite3.Connection], slug: str, nome: str,
             erro: str) -> str | None:
    """Pede e guarda. None se a IA não deu frase que passasse."""
    try:
        r = pedir(nome, erro)
    except ia.IAIndisponivel:
        return None
    with closing(conectar()) as con:
        _criar_tabela(con)
        con.execute("INSERT OR REPLACE INTO erro_explicado VALUES (?, ?, ?, ?)",
                    (chave(slug, erro), r.dados, r.modelo,
                     datetime.now().isoformat(timespec="seconds")))
        con.commit()
    return r.dados


def explicar_em_fundo(conectar: Callable[[], sqlite3.Connection], slug: str, nome: str,
                      erro: str) -> bool:
    """Dispara `explicar` numa thread, uma vez por chave. True se disparou."""
    if not (LIGADA and erro and ia.configurada()):
        return False
    k = chave(slug, erro)
    with _trava:
        if time.monotonic() - _pedidos.get(k, -ESPERA_FALHA_S) < ESPERA_FALHA_S:
            return False
        _pedidos[k] = time.monotonic()

    def rodar():
        try:
            explicar(conectar, slug, nome, erro)
        except Exception:      # a explicação nunca derruba nada
            pass
        # Deu certo: a frase está no banco e ninguém pede de novo. Falhou: a
        # chave fica em _pedidos e só volta a tentar depois de ESPERA_FALHA_S.

    threading.Thread(target=rodar, name="explicar-erro", daemon=True).start()
    return True
