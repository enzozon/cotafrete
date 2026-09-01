"""Monitor do Cotafrete — quem cotou, o que deu certo, o que falhou.

    python monitorar.py                 acompanha, atualizando sozinho
    python monitorar.py --uma-vez       imprime uma vez e sai
    python monitorar.py --dias 7        olha os últimos 7 dias

Feito para ficar aberto numa janela enquanto a equipe usa o sistema. Não
conversa com o servidor: lê o mesmo arquivo cotafrete.db. Por isso funciona
com o Cotafrete rodando em outra máquina, desde que a pasta seja alcançável.

ABRE O BANCO EM MODO SOMENTE-LEITURA. É de propósito e não deve mudar: um
monitor que pode escrever é um monitor que pode corromper o que está
monitorando. De quebra, nunca cria um banco vazio por engano na pasta errada
— ele reclama em vez de inventar.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "cotafrete.db"

# As que o robô cota sozinho, na ordem em que aparecem na tela do vendedor.
# Tem que ser a MESMA lista de web/app.py — conferido por
# tests/test_dellavolpe_automatica.py. Esta copia ja parou em
# ("camilo", "jadlog") quando a Translovato entrou, e o monitor passou a
# mentir sobre quantas faltavam.
# A Della Volpe saiu em 31/08/2026: o site dela passou a exigir "confirme
# que e humano" e ela virou acionada pelo vendedor. Para trazer de volta,
# acrescente aqui E em web/app.py — o teste confere que as duas batem.
AUTOMATICAS = ("camilo", "jadlog", "translovato", "generoso")
TITULOS = {"camilo": "CAMILO", "jadlog": "JADLOG",
           "translovato": "TRANSLOVATO", "generoso": "GENEROSO"}

PAUSA_S = 5
LARGURA = 116


def conectar() -> sqlite3.Connection:
    """Somente leitura. `mode=ro` falha se o arquivo não existir, em vez de
    criar um banco vazio — o erro certo é "não achei", não "está vazio"."""
    if not BANCO.exists():
        raise SystemExit(
            f"Não achei {BANCO}.\n"
            f"Rode o monitor na mesma pasta do Cotafrete, ou aponte para a "
            f"pasta onde o servidor grava.")
    con = sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def _hora(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return "?"


def _moeda(valor: str | None) -> str:
    if valor in (None, ""):
        return ""
    try:
        return f"R$ {Decimal(valor):,.2f}".replace(",", "X").replace(
            ".", ",").replace("X", ".")
    except Exception:
        return str(valor)


def _celula(resultado: dict | None) -> str:
    """O que mostrar na coluna da transportadora.

    "..." é ainda cotando — diferente de "recusou", de "e-mail" e de "ERRO".
    Misturar esses estados esconderia justamente o que o monitor existe para
    mostrar: se o problema é demora, regra de negócio, ou defeito.

    "e-mail" é a Generoso: ela confirma o recebimento e manda o preço por
    e-mail depois. Sem preço e sem falha — mostrar ERRO aqui mandaria o Enzo
    caçar um defeito que não existe."""
    if resultado is None:
        return "..."
    if resultado["valor"]:
        return _moeda(resultado["valor"])
    # "SENHA" é a única falha desta lista que NÃO passa sozinha: enquanto
    # ninguém mexer no .env, toda cotação daquela transportadora vai falhar
    # igual. Misturada em "ERRO" ela se esconde no meio dos timeouts.
    return {"recusado": "recusou", "aguardando_retorno": "e-mail",
            "intervencao_necessaria": "SENHA",
            "erro": "ERRO"}.get(resultado["status"], resultado["status"])


def coletar(con: sqlite3.Connection, dias: int) -> dict:
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    cotacoes = [dict(r) for r in con.execute(
        "SELECT * FROM cotacao WHERE criado_em >= ? ORDER BY id DESC",
        (desde,))]

    ids = [c["id"] for c in cotacoes]
    marcas = ",".join("?" * len(ids)) or "NULL"

    resultados: dict[int, dict[str, dict]] = {}
    for r in con.execute(
            f"SELECT * FROM resultado WHERE cotacao_id IN ({marcas})", ids):
        resultados.setdefault(r["cotacao_id"], {})[r["transportadora"]] = dict(r)

    zaps: Counter = Counter()
    try:
        for r in con.execute(
                f"SELECT cotacao_id FROM whatsapp_aberto"
                f" WHERE cotacao_id IN ({marcas})", ids):
            zaps[r["cotacao_id"]] += 1
    except sqlite3.OperationalError:
        # Banco anterior ao rastreio de WhatsApp. Mostrar o resto do monitor
        # vale mais do que explodir por uma tabela que ainda não existe.
        pass

    return {"cotacoes": cotacoes, "resultados": resultados, "zaps": zaps}


def contar(cotacoes: list[dict], resultados: dict) -> dict[str, int]:
    contas = {"preco": 0, "recusadas": 0, "por_email": 0, "erros": 0,
              "andamento": 0}
    for c in cotacoes:
        por_slug = resultados.get(c["id"], {})
        for slug in AUTOMATICAS:
            r = por_slug.get(slug)
            if r is None:
                contas["andamento"] += 1
            elif r["valor"]:
                contas["preco"] += 1
            elif r["status"] == "recusado":
                contas["recusadas"] += 1
            elif r["status"] == "aguardando_retorno":
                contas["por_email"] += 1
            else:
                contas["erros"] += 1
    return contas


def desenhar(dados: dict, dias: int) -> None:
    cotacoes, resultados = dados["cotacoes"], dados["resultados"]
    contas = contar(cotacoes, resultados)

    print("=" * LARGURA)
    print(" COTAFRETE — monitor".ljust(LARGURA - 30)
          + f"atualizado {datetime.now():%H:%M:%S}".rjust(30))
    print("=" * LARGURA)
    print(f" {len(cotacoes)} cotações em {dias} dia(s)  ·  "
          f"{contas['preco']} com preço  ·  {contas['recusadas']} recusadas  ·  "
          f"{contas['por_email']} por e-mail  ·  {contas['erros']} com erro"
          f"  ·  {contas['andamento']} em andamento"
          f"  ·  {sum(dados['zaps'].values())} WhatsApp abertos")
    print("-" * LARGURA)

    cabecalho = (f"{'#':>4} {'QUANDO':<12} {'QUEM':<10} {'ROTA':<8} "
                 f"{'CARGA':<14}")
    for slug in AUTOMATICAS:
        cabecalho += f"{TITULOS[slug]:<14}"
    print(cabecalho + "ZAP")
    print("-" * LARGURA)

    if not cotacoes:
        print("  (ninguém cotou no período)")

    for c in cotacoes[:25]:
        por_slug = resultados.get(c["id"], {})
        rota = f"{c['uf_origem'] or '?'}>{c['uf_destino'] or '?'}"
        carga = f"{c['quantidade']}vol {c['peso_kg']}kg"
        linha = (f"{c['id']:>4} {_hora(c['criado_em']):<12} "
                 f"{(c['usuario'] or '')[:9]:<10} {rota:<8} {carga[:13]:<14}")
        for slug in AUTOMATICAS:
            linha += f"{_celula(por_slug.get(slug)):<14}"
        zap = dados["zaps"].get(c["id"], 0)
        print(linha + (str(zap) if zap else ""))

    # O erro por extenso, embaixo. Na coluna só cabe "ERRO", e "ERRO" sem
    # motivo obriga a abrir o sistema para descobrir o que houve.
    falhas = [(c["id"], slug, resultados[c["id"]][slug])
              for c in cotacoes
              for slug in AUTOMATICAS
              if slug in resultados.get(c["id"], {})
              and not resultados[c["id"]][slug]["valor"]
              and resultados[c["id"]][slug]["status"] != "aguardando_retorno"]
    if falhas:
        print("-" * LARGURA)
        print(" O QUE NÃO VOLTOU COM PREÇO (mais recentes)")
        for cid, slug, r in falhas[:6]:
            motivo = (r["erro"] or r["status"] or "").replace("\n", " ")
            print(f"  #{cid} {slug:<12} {motivo[:LARGURA - 22]}")


def main() -> int:
    dias = 1
    if "--dias" in sys.argv:
        try:
            dias = int(sys.argv[sys.argv.index("--dias") + 1])
        except (IndexError, ValueError):
            print("--dias precisa de um número. Ex: --dias 7")
            return 2

    uma_vez = "--uma-vez" in sys.argv
    con = conectar()
    try:
        while True:
            dados = coletar(con, dias)
            if not uma_vez:
                os.system("cls" if os.name == "nt" else "clear")
            desenhar(dados, dias)
            if uma_vez:
                return 0
            print("-" * LARGURA)
            print(f" atualiza a cada {PAUSA_S}s  ·  Ctrl+C para sair")
            time.sleep(PAUSA_S)
    except KeyboardInterrupt:
        print("\nmonitor encerrado.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
