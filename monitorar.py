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
import shutil
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "cotafrete.db"

# Fallback puro: só entra em cena se o período não tiver NENHUM resultado
# ainda (banco novo), pra tela não subir sem coluna nenhuma. Fora isso, quem
# decide as colunas é `slugs_do_periodo` — o que já apareceu no banco, não
# uma lista copiada de web/app.py. Essa cópia já ficou desatualizada duas
# vezes (parou em "camilo","jadlog" quando a Translovato entrou; sumiu com a
# Della Volpe quando ela saiu das automáticas em 31/08/2026) e cada vez o
# histórico de erro de quem ficou de fora sumia da tela, sem aviso nenhum.
AUTOMATICAS = ("camilo", "jadlog", "translovato", "generoso", "braspress")
# Nomes bonitos para quem é conhecido; `_titulo` cai para `slug.upper()` no
# resto. Assim uma transportadora nova nunca desaparece da tela por faltar
# aqui — só aparece com o slug em maiúsculo até alguém cadastrar o nome.
TITULOS = {"camilo": "CAMILO", "jadlog": "JADLOG",
           "translovato": "TRANSLOVATO", "generoso": "GENEROSO",
           "dellavolpe": "DELLA VOLPE"}

PAUSA_S = 5
LARGURA_MINIMA = 116
FALHAS_MAX = 15
# Linhas que a moldura gasta além da tabela de cotações: cabeçalho (7),
# bloco de falhas (2 + FALHAS_MAX) e rodapé (2). Superestimado de propósito
# — sobrar linha em branco é inofensivo, faltar é o que faz a tela crescer
# mais que o terminal e "descer a página" a cada atualização.
LINHAS_MOLDURA = 7 + 2 + FALHAS_MAX + 2
LINHAS_MIN_TABELA = 3

_ANSI_LIMPAR = "\x1b[H\x1b[J"  # cursor pro topo + apaga da posição até o fim


def _preparar_console() -> None:
    """Liga o processamento ANSI do console do Windows.

    Sem isto, `_ANSI_LIMPAR` sai como texto cru (ESC[H ESC[J) na tela em vez
    de mover o cursor: cmd.exe só interpreta escape VT100 quando
    ENABLE_VIRTUAL_TERMINAL_PROCESSING está ligado, e ele começa desligado.
    O `os.system("cls")` que o monitor usava antes não precisava disto
    porque não usava escape nenhum — mas cada `cls` redesenha a tela do zero
    E deixa o terminal seguir o conteúdo novo até o fim, que é o que fazia a
    janela "descer a página" a cada atualização."""
    if os.name != "nt":
        return
    import ctypes
    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    handle = ctypes.windll.kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    modo = ctypes.c_uint32()
    if not ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(modo)):
        return  # saída redirecionada para arquivo, sem console de verdade
    ctypes.windll.kernel32.SetConsoleMode(
        handle, modo.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)


def _linhas_disponiveis() -> int:
    """Quantas linhas de cotação cabem no terminal sem precisar rolar.

    `shutil.get_terminal_size` é stdlib e já lida com o caso sem terminal de
    verdade (saída redirecionada): cai no fallback (80, 24) sozinho."""
    altura = shutil.get_terminal_size(fallback=(LARGURA_MINIMA, 24)).lines
    return max(LINHAS_MIN_TABELA, altura - LINHAS_MOLDURA)


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


def slugs_do_periodo(resultados: dict[int, dict[str, dict]]) -> tuple[str, ...]:
    """Toda transportadora que devolveu resultado no período, em ordem
    estável. Substitui a lista fixa AUTOMATICAS como base das colunas e do
    histórico de erro: aqui não tem como uma transportadora sumir da tela
    por alguém esquecer de atualizar uma cópia à mão — se ela apareceu no
    banco, ela aparece na tela.

    Vazio (banco novo, sem nenhum resultado ainda) cai para as automáticas
    conhecidas, só para a tela não subir sem coluna nenhuma."""
    vistas = {slug for por_slug in resultados.values() for slug in por_slug}
    return tuple(sorted(vistas)) if vistas else AUTOMATICAS


def _titulo(slug: str) -> str:
    return TITULOS.get(slug, slug.upper())


def contar(cotacoes: list[dict], resultados: dict,
          slugs: tuple[str, ...] | None = None) -> dict[str, int]:
    if slugs is None:
        slugs = slugs_do_periodo(resultados)
    contas = {"preco": 0, "recusadas": 0, "por_email": 0, "erros": 0,
              "andamento": 0}
    for c in cotacoes:
        por_slug = resultados.get(c["id"], {})
        for slug in slugs:
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


def desenhar(dados: dict, dias: int, linhas_tabela: int = 25) -> int:
    """Desenha o quadro e devolve a largura usada, pro rodapé alinhar."""
    cotacoes, resultados = dados["cotacoes"], dados["resultados"]
    slugs = slugs_do_periodo(resultados)
    contas = contar(cotacoes, resultados, slugs)

    cabecalho = (f"{'#':>4} {'QUANDO':<12} {'QUEM':<10} {'ROTA':<8} "
                 f"{'CARGA':<14}")
    for slug in slugs:
        cabecalho += f"{_titulo(slug):<14}"
    cabecalho += "ZAP"
    # Largura calculada do conteúdo de verdade, não um número fixo: o número
    # de colunas varia com quantas transportadoras aparecem no período.
    largura = max(LARGURA_MINIMA, len(cabecalho) + 2)

    print("=" * largura)
    print(" COTAFRETE — monitor".ljust(largura - 30)
          + f"atualizado {datetime.now():%H:%M:%S}".rjust(30))
    print("=" * largura)
    print(f" {len(cotacoes)} cotações em {dias} dia(s)  ·  "
          f"{contas['preco']} com preço  ·  {contas['recusadas']} recusadas  ·  "
          f"{contas['por_email']} por e-mail  ·  {contas['erros']} com erro"
          f"  ·  {contas['andamento']} em andamento"
          f"  ·  {sum(dados['zaps'].values())} WhatsApp abertos")
    print("-" * largura)
    print(cabecalho)
    print("-" * largura)

    if not cotacoes:
        print("  (ninguém cotou no período)")

    for c in cotacoes[:linhas_tabela]:
        por_slug = resultados.get(c["id"], {})
        rota = f"{c['uf_origem'] or '?'}>{c['uf_destino'] or '?'}"
        carga = f"{c['quantidade']}vol {c['peso_kg']}kg"
        linha = (f"{c['id']:>4} {_hora(c['criado_em']):<12} "
                 f"{(c['usuario'] or '')[:9]:<10} {rota:<8} {carga[:13]:<14}")
        for slug in slugs:
            linha += f"{_celula(por_slug.get(slug)):<14}"
        zap = dados["zaps"].get(c["id"], 0)
        print(linha + (str(zap) if zap else ""))
    if len(cotacoes) > linhas_tabela:
        print(f"  … e mais {len(cotacoes) - linhas_tabela} cotação(ões) "
              f"fora da tela (terminal maior mostra mais, ou use --uma-vez)")

    # O erro por extenso, embaixo. Na coluna só cabe "ERRO", e "ERRO" sem
    # motivo obriga a abrir o sistema para descobrir o que houve. Percorre
    # TODAS as transportadoras do período — antes só as automáticas fixas,
    # e um erro de quem tivesse saído dessa lista (a Della Volpe, em
    # 31/08/2026) sumia daqui mesmo estando salvo no banco.
    falhas = [(c["id"], slug, resultados[c["id"]][slug])
              for c in cotacoes
              for slug in slugs
              if slug in resultados.get(c["id"], {})
              and not resultados[c["id"]][slug]["valor"]
              and resultados[c["id"]][slug]["status"] != "aguardando_retorno"]
    if falhas:
        print("-" * largura)
        print(f" O QUE NÃO VOLTOU COM PREÇO ({len(falhas)} no período, "
              f"mais recentes primeiro)")
        for cid, slug, r in falhas[:FALHAS_MAX]:
            motivo = (r["erro"] or r["status"] or "").replace("\n", " ")
            print(f"  #{cid} {slug:<12} {motivo[:largura - 22]}")
        if len(falhas) > FALHAS_MAX:
            print(f"  … e mais {len(falhas) - FALHAS_MAX}. "
                  f"Amplie o terminal ou use --dias 1 para reduzir o período.")

    return largura


def main() -> int:
    dias = 1
    if "--dias" in sys.argv:
        try:
            dias = int(sys.argv[sys.argv.index("--dias") + 1])
        except (IndexError, ValueError):
            print("--dias precisa de um número. Ex: --dias 7")
            return 2

    uma_vez = "--uma-vez" in sys.argv
    # isatty(): saída redirecionada pra arquivo não tem cursor pra mover, e
    # jogar escape ANSI nela sujaria o arquivo com "ESC[H ESC[J" literal.
    dinamico = not uma_vez and sys.stdout.isatty()
    if dinamico:
        _preparar_console()

    con = conectar()
    try:
        while True:
            dados = coletar(con, dias)
            linhas_tabela = _linhas_disponiveis() if dinamico else 25
            if dinamico:
                print(_ANSI_LIMPAR, end="")
            elif not uma_vez:
                os.system("cls" if os.name == "nt" else "clear")
            largura = desenhar(dados, dias, linhas_tabela)
            if uma_vez:
                return 0
            print("-" * largura)
            print(f" atualiza a cada {PAUSA_S}s  ·  Ctrl+C para sair")
            time.sleep(PAUSA_S)
    except KeyboardInterrupt:
        print("\nmonitor encerrado.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
