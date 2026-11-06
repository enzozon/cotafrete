"""Resumo diário dos erros por e-mail (P1 #10): cotafrete, DAV e robôs do SERVIDOR2.

Roda uma vez por dia pelo `atualizar.py`: `python -m core.resumo_email`.
Junta, sem IA:
- `resumo_erros.fatos_do_dia` (transportadoras, ME, Della Volpe, IA);
- envios do DAV que terminaram em erro, incerto ou recusados;
- linhas de erro de hoje nos logs de `\\\\SERVIDOR2\\Publico\\ALLAN\\Logs`.
Vai sempre, mesmo sem erro: e-mail que não chega é o aviso de que algo parou.

SMTP: `SMTP_USER` e `SMTP_PASSWORD` no .env (os mesmos do gerenciador).
Destino: `RESUMO_EMAIL_PARA`.
"""
from __future__ import annotations

import os
import re
import smtplib
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from core import resumo_erros

PARA_PADRAO = "vendas2@venturainformatica.com.br"
SMTP_HOST, SMTP_PORTA = "email-ssl.com.br", 465
PASTA_LOGS = Path(r"\\SERVIDOR2\Publico\ALLAN\Logs")
LOGS = {"Gerenciador": "gerenciador.txt", "Coupa": "log-coupa.txt", "Vale": "log-vale.txt",
        "Findes": "findes.txt", "Ariba": "aribasourcing.txt", "Mercado Eletrônico": "mercadoeletronico.txt",
        "Datasheet": "datasheet.txt"}
MAX_LEITURA = 8 * 1024 * 1024   # o fim do arquivo basta: as linhas de hoje estão lá
MAX_POR_LOG = 5
_MODULO = re.compile(r"\[(?:MÓDULO|ID): [^\]]*\] ?")
_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2}) [\d:,]+ .*? (?:ERROR|CRITICAL) (.*)$")
_BR = re.compile(r"^\[(\d{2})/(\d{2})/(\d{4}) [\d:]+\] \[(?:ERRO|ERROR|CRITICO)[^\]]*\] (.*)$")


def erros_do_log(caminho: Path, dia: date) -> list[str]:
    """Mensagens de erro de `dia` num log (formato do gerenciador ou do datasheet)."""
    tam = caminho.stat().st_size
    with open(caminho, "rb") as f:
        f.seek(max(0, tam - MAX_LEITURA))
        texto = f.read().decode("utf-8", "replace")
    achadas = []
    for linha in texto.splitlines():
        m = _ISO.match(linha)
        if m and m[1] == dia.isoformat():
            achadas.append(m[2].strip())
            continue
        m = _BR.match(linha)
        if m and f"{m[3]}-{m[2]}-{m[1]}" == dia.isoformat():
            achadas.append(m[4].partition("Descrição do problema: ")[2].strip()[:300]
                           or _MODULO.sub("", m[4]).strip())
    return achadas


def secao_logs(dia: date, pasta: Path = PASTA_LOGS) -> list[str]:
    linhas = []
    for nome, arquivo in LOGS.items():
        try:
            erros = erros_do_log(pasta / arquivo, dia)
        except OSError:
            linhas.append(f"{nome}: log não pôde ser lido ({arquivo}).")
            continue
        if not erros:
            continue
        grupos = Counter(resumo_erros._chave(e) for e in erros)
        linhas.append(f"{nome}: {len(erros)} erro(s).")
        linhas += [f"   {n}× {msg[:150]}" for msg, n in grupos.most_common(MAX_POR_LOG)]
    return linhas


def secao_dav(con: sqlite3.Connection, dia: date) -> list[str]:
    linhas = con.execute("SELECT id, usuario, estado, cliente, erro FROM dav WHERE criado_em LIKE ?"
                         " AND estado IN ('erro', 'incerto', 'rejeitado') ORDER BY id", (f"{dia.isoformat()}%",)).fetchall()
    return [f"Envio #{r[0]} ({r[1]}, {r[2]}): {(r[3] or 'sem cliente')[:40]} - {(r[4] or 'ver detalhe no ADM')[:120]}"
            for r in linhas]


def montar(con: sqlite3.Connection, dia: date, nome_de=lambda s: s, pasta_logs: Path = PASTA_LOGS) -> tuple[str, str]:
    """(assunto, corpo)."""
    fatos = resumo_erros.fatos_do_dia(con, dia, nome_de)
    cotafrete, dav, logs = resumo_erros.resumo_sem_ia(fatos), secao_dav(con, dia), secao_logs(dia, pasta_logs)
    total = len(cotafrete) + len(dav) + sum(1 for l in logs if not l.startswith("   "))
    corpo = [f"Resumo de erros de {dia:%d/%m/%Y}", ""]
    for titulo, itens in (("COTAFRETE", cotafrete), ("ORÇAMENTOS (DAV)", dav), ("ROBÔS E SERVIDOR2", logs)):
        corpo += [titulo, *(itens or ["Nenhum erro."]), ""]
    assunto = f"Resumo de erros {dia:%d/%m}: " + (f"{total} ponto(s) para olhar" if total else "tudo certo")
    return assunto, "\n".join(corpo)


def enviar(assunto: str, corpo: str, ambiente=None, smtp=smtplib.SMTP_SSL) -> None:
    env = os.environ if ambiente is None else ambiente
    usuario, senha = env.get("SMTP_USER", ""), env.get("SMTP_PASSWORD", "")
    if not usuario or not senha:
        raise RuntimeError("faltam SMTP_USER e SMTP_PASSWORD no .env")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = assunto, usuario, env.get("RESUMO_EMAIL_PARA") or PARA_PADRAO
    msg.set_content(corpo)
    with smtp(SMTP_HOST, SMTP_PORTA, timeout=30) as s:
        s.login(usuario, senha)
        s.send_message(msg)


def main() -> int:
    from dotenv import load_dotenv

    from core.banco import CAMINHO_PADRAO
    from web import transportadoras
    load_dotenv()
    with closing(sqlite3.connect(CAMINHO_PADRAO)) as con:
        assunto, corpo = montar(con, datetime.now().date(), transportadoras.nome_de)
    try:
        enviar(assunto, corpo)
    except (OSError, RuntimeError, smtplib.SMTPException) as e:
        print(f"Resumo por e-mail falhou: {type(e).__name__}: {str(e)[:200]}")
        return 1
    print(f"Resumo enviado: {assunto}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
