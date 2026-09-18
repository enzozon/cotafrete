"""Cópia de segurança do `cotafrete.db`.

Todo o histórico da empresa — quem cotou, para onde, por quanto, qual
transportadora respondeu o quê — vive num arquivo só, dentro da VM. Os
prints expiram em 30 dias por desenho (`core/evidencias.py`), mas o texto
fica para sempre. Se esse arquivo se perder, não há de onde tirar de volta.

POR QUE NÃO DÁ PARA SÓ COPIAR O ARQUIVO

O banco roda em **WAL** (`core/banco.py`: `PRAGMA journal_mode = WAL`). Nesse
modo o que foi gravado há pouco ainda está em `cotafrete.db-wal`, e só passa
para o `.db` num checkpoint. Um `copy cotafrete.db` feito com o servidor no
ar produz um arquivo que **abre normalmente e parece íntegro** —
só que sem as cotações mais recentes. É a pior forma de falhar: silenciosa, e
só descoberta no dia em que alguém precisar restaurar.

Por isso aqui se usa a API de backup online do SQLite
(`sqlite3.Connection.backup`), que lê através do WAL, respeita quem está
escrevendo e entrega UM arquivo consistente — sem precisar parar o servidor.

E porque backup que ninguém testa não é backup, cada cópia é aberta e
conferida logo depois de gravada (ver `_conferir`).
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

CAMINHO_BANCO = Path("cotafrete.db")

# Destino: variável de ambiente primeiro, porque o lugar certo é FORA da VM
# (um compartilhamento de rede, um disco externo) e isso muda de empresa para
# empresa. O padrão local existe para a ferramenta funcionar sem configuração
# nenhuma — mas cópia no mesmo disco não protege contra o disco morrer, e por
# isso `rodar()` avisa quando é esse o caso.
VARIAVEL_DESTINO = "COTAFRETE_BACKUP_DIR"
DESTINO_PADRAO = Path("backup")

# Uma por dia dá duas semanas de histórico. O limite existe para o backup não
# virar o motivo de o disco encher — que seria trocar um problema por outro.
COPIAS_MANTIDAS = 14

# O nome carrega a data para ordenar sozinho e para alguém saber o que está
# restaurando sem abrir o arquivo.
MOLDE_NOME = "cotafrete-%Y%m%d-%H%M.db"
# Só arquivos GERADOS AQUI entram na faxina. Sem este filtro, a limpeza
# apagaria qualquer coisa que a pessoa tivesse guardado na mesma pasta.
RE_NOME = re.compile(r"^cotafrete-\d{8}-\d{4}\.db$")


def destino_configurado() -> Path:
    """A pasta de destino, da variável de ambiente ou o padrão."""
    return Path(os.getenv(VARIAVEL_DESTINO) or DESTINO_PADRAO)


def _contar_cotacoes(caminho: Path) -> int:
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM cotacao").fetchone()[0]
    finally:
        con.close()


def _conferir(copia: Path, minimo_de_cotacoes: int) -> int:
    """Abre a cópia e confirma que ela serve. Devolve quantas cotações tem.

    Duas checagens, e cada uma pega um defeito diferente:

    * `PRAGMA integrity_check` pega arquivo truncado ou corrompido;
    * a contagem pega o defeito do WAL descrito no topo — uma cópia pode
      estar perfeitamente íntegra e ainda assim ter menos cotações do que o
      banco tinha quando o backup começou. Linha de cotação nunca é apagada,
      então a cópia tem que ter pelo menos o que havia antes.
    """
    con = sqlite3.connect(f"file:{copia}?mode=ro", uri=True)
    try:
        estado = con.execute("PRAGMA integrity_check").fetchone()[0]
        if estado != "ok":
            raise RuntimeError(f"a cópia {copia.name} saiu corrompida: {estado}")
        quantas = con.execute("SELECT COUNT(*) FROM cotacao").fetchone()[0]
    finally:
        con.close()

    if quantas < minimo_de_cotacoes:
        raise RuntimeError(
            f"a cópia {copia.name} tem {quantas} cotações, e o banco tinha "
            f"{minimo_de_cotacoes} quando o backup começou — faltou o que "
            f"estava no WAL. NÃO confie nesta cópia.")
    return quantas


def copiar(origem: Path = CAMINHO_BANCO,
           destino: Path | None = None,
           agora: datetime | None = None) -> tuple[Path, int]:
    """Grava uma cópia consistente e já conferida. Devolve (arquivo, cotações).

    Pode rodar com o servidor no ar: a API de backup do SQLite se entende com
    quem está escrevendo. Não precisa (e não deve) parar o Cotafrete para
    isso — backup que exige parar o sistema é backup que ninguém faz.
    """
    origem = Path(origem)
    if not origem.exists():
        raise FileNotFoundError(f"banco não encontrado: {origem.resolve()}")

    pasta = Path(destino) if destino is not None else destino_configurado()
    pasta.mkdir(parents=True, exist_ok=True)

    antes = _contar_cotacoes(origem)
    arquivo = pasta / (agora or datetime.now()).strftime(MOLDE_NOME)

    fonte = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    try:
        copia = sqlite3.connect(arquivo)
        try:
            fonte.backup(copia)
            # A cópia nasce em WAL, herdado do original — e aí ela deixa de
            # ser UM arquivo: abrir para conferir cria `-wal` e `-shm` do
            # lado, que a faxina não reconhece e que sobrariam órfãos quando
            # o `.db` deles fosse apagado. Backup é para ser copiado,
            # levado embora e restaurado sozinho; DELETE deixa exatamente um
            # arquivo, sem nada pendurado.
            copia.execute("PRAGMA journal_mode = DELETE")
        finally:
            copia.close()
    finally:
        fonte.close()

    return arquivo, _conferir(arquivo, antes)


def limpar_antigas(destino: Path | None = None,
                   manter: int = COPIAS_MANTIDAS) -> int:
    """Deixa as `manter` cópias mais novas e apaga o resto. Devolve quantas
    apagou.

    Ordena pelo NOME, e não pela data do arquivo: o nome tem a data de quando
    a cópia foi feita, e copiar a pasta para outro lugar reescreve a data do
    arquivo — mas não o nome."""
    pasta = Path(destino) if destino is not None else destino_configurado()
    if not pasta.exists():
        return 0

    copias = sorted((a for a in pasta.iterdir()
                     if a.is_file() and RE_NOME.match(a.name)),
                    key=lambda a: a.name)
    velhas = copias[:-manter] if manter > 0 else copias
    for arquivo in velhas:
        arquivo.unlink(missing_ok=True)
    return len(velhas)


# As pastas de print. São DUAS, e a documentação dizia só "runs/" — errado:
# dos 619 resultados com evidência no banco de produção, 576 apontam para
# `teste_real/` e 43 para `runs/`. A primeira é onde as transportadoras
# gravam; a segunda é o `workdir` do fluxo assistido da Della Volpe e do
# simulador da Jadlog.
PASTAS_DE_EVIDENCIA = (Path("teste_real"), Path("runs"))
NOME_DO_ESPELHO = "evidencias"


def espelhar_evidencias(destino: Path | None = None,
                        origens: tuple[Path, ...] = PASTAS_DE_EVIDENCIA
                        ) -> tuple[int, int]:
    """Copia para o destino os prints que ainda não estão lá.

    Devolve (copiados, já tinha). **Nunca apaga nada no destino** — e é aí
    que está o ponto desta função. O `core/evidencias.py` apaga print local
    com mais de 30 dias, e isso é gestão de espaço em disco, não política de
    guarda: sem um espelho, a prova do preço que a transportadora deu some
    junto. O espelho existe para durar mais que a faxina.

    Copia só o que falta, comparando o tamanho. Print gravado nunca é
    reescrito, então não há caso de "mudou, copie de novo" — a comparação
    serve para refazer cópia interrompida no meio."""
    pasta = Path(destino) if destino is not None else destino_configurado()
    raiz = pasta / NOME_DO_ESPELHO
    copiados = ja_tinha = 0

    for origem in origens:
        origem = Path(origem)
        if not origem.exists():
            continue
        for arquivo in origem.rglob("*"):
            if not arquivo.is_file():
                continue
            alvo = raiz / origem.name / arquivo.relative_to(origem)
            if alvo.exists() and alvo.stat().st_size == arquivo.stat().st_size:
                ja_tinha += 1
                continue
            alvo.parent.mkdir(parents=True, exist_ok=True)
            # copy2 e não copy: preserva a data de modificação, que é o que
            # diz de quando é aquele print depois que o banco não estiver
            # mais por perto para contar.
            shutil.copy2(arquivo, alvo)
            copiados += 1
    return copiados, ja_tinha


def rodar() -> int:
    """O que o `Backup.bat` chama. Devolve o código de saída."""
    pasta = destino_configurado()
    try:
        arquivo, quantas = copiar()
    except Exception as erro:                      # noqa: BLE001
        print(f"  FALHOU: {erro}")
        return 1

    apagadas = limpar_antigas()
    tamanho = arquivo.stat().st_size / 1_048_576

    print(f"  Copia:    {arquivo.resolve()}")
    print(f"  Conteudo: {quantas} cotacoes, {tamanho:.1f} MB")
    if apagadas:
        print(f"  Faxina:   {apagadas} copia(s) antiga(s) apagada(s)")

    # Os prints vêm depois do banco de propósito: se esta parte falhar, o
    # histórico de texto — que é o que não se recupera de jeito nenhum — já
    # está salvo. Print perdido dói; cotação perdida não tem volta.
    try:
        novos, tinha = espelhar_evidencias(pasta)
        print(f"  Prints:   {novos} novo(s), {tinha} ja estavam la")
    except Exception as erro:                      # noqa: BLE001
        print(f"  Prints:   FALHOU ({erro}). O banco foi salvo assim mesmo.")

    # O aviso mais importante da ferramenta: cópia no mesmo disco do original
    # não protege contra o que mais acontece — a VM ou o disco se perderem.
    try:
        mesmo_lugar = pasta.resolve().is_relative_to(Path.cwd().resolve())
    except (OSError, ValueError):
        mesmo_lugar = False
    if mesmo_lugar:
        print()
        print("  ATENCAO: a copia esta na MESMA maquina do banco original.")
        print(f"  Aponte {VARIAVEL_DESTINO} para um compartilhamento de rede")
        print("  ou disco externo - senao ela se perde junto com a VM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(rodar())
