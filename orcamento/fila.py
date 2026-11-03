"""Fila do Gerar DAV: um DAV por vez, numa thread só.

O estado de verdade fica na tabela `dav` (core/banco.py); a fila em memória é
só a ordem. Se o servidor cair, `retomar()` na subida põe o `gerando` como
`incerto` (nunca roda de novo sozinho: o orçamento pode já estar no HSE) e
re-enfileira os que ainda estavam em `fila`.

A planilha de cada DAV é `<pasta>/entrada/<id>.xlsx` e o PDF vai para
`<pasta>/pdf/`.
"""

from __future__ import annotations

import inspect
import logging
import os
import queue
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from core.banco import Banco
from orcamento.processador import HseIndisponivel, Resultado

log = logging.getLogger(__name__)

HSE_FORA = "O HSE está fora do ar agora. Tente de novo em alguns minutos."
RECUSA_LOGIN = "O HSE recusou o login"  # prefixo da HseIndisponivel levantada por Hse._login
HSE_RECUSOU = " Tente de novo mais tarde, dentro do horário de login do HSE."
SEM_LOGIN = "Robô do HSE sem login configurado no servidor."
TENTATIVAS_BANCO = 5
ESPERA_BANCO_S = 0.5


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sem_segredo(texto: str | None) -> str | None:
    for chave in ("HSE_SENHA", "ANTHROPIC_API_KEY"):
        segredo = (os.environ.get(chave) or "").strip()
        if segredo and texto:
            texto = texto.replace(segredo, "***")
    return texto


class FilaDav:
    def __init__(self, banco: Banco, pasta: Path,
                 executar: Callable[[Path, Path], Resultado] | None = None,
                 disparar: Callable[[Callable[[], None]], None] | None = None) -> None:
        self.banco = banco
        self.pasta = Path(pasta)
        self._executar = executar or self._executar_no_hse
        self._disparar = disparar or self._na_thread
        self._trava = threading.Lock()
        self._esperando: list[int] = []
        self._gerando: int | None = None
        self._tarefas: queue.Queue = queue.Queue()
        self._trabalhadora: threading.Thread | None = None

    @property
    def em_curso(self) -> int:
        """Na fila + gerando (o que o /_ocupado soma)."""
        with self._trava:
            return len(self._esperando) + (self._gerando is not None)

    def planilha(self, dav_id: int) -> Path:
        return self.pasta / "entrada" / f"{dav_id}.xlsx"

    def enfileirar(self, dav_id: int) -> int:
        """Posição na fila (1 = o próximo). O mesmo id não entra duas vezes."""
        with self._trava:
            if dav_id == self._gerando:
                return 0
            if dav_id in self._esperando:
                return self._esperando.index(dav_id) + 1
            self._esperando.append(dav_id)
            posicao = len(self._esperando)
        self._disparar(lambda: self._rodar(dav_id))
        return posicao

    def retomar(self) -> None:
        for dav_id in self._no_banco(self.banco.dav_interromper):
            self.enfileirar(dav_id)

    # ------------------------------------------------------------ interno
    def _na_thread(self, tarefa: Callable[[], None]) -> None:
        with self._trava:
            if self._trabalhadora is None:
                self._trabalhadora = threading.Thread(
                    target=self._consumir, name="fila-dav", daemon=True)
                self._trabalhadora.start()
        self._tarefas.put(tarefa)

    def _consumir(self) -> None:
        while True:
            tarefa = self._tarefas.get()
            try:
                tarefa()
            except Exception:   # nunca derruba a thread
                log.exception("Fila do DAV: tarefa quebrou")

    def _no_banco(self, chamada, *args, **kw):
        """O sqlite trava às vezes ("database is locked"): tenta de novo."""
        for tentativa in range(TENTATIVAS_BANCO):
            try:
                return chamada(*args, **kw)
            except sqlite3.OperationalError:
                if tentativa == TENTATIVAS_BANCO - 1:
                    raise
                time.sleep(ESPERA_BANCO_S)

    def _rodar(self, dav_id: int) -> None:
        with self._trava:
            self._esperando.remove(dav_id)
            self._gerando = dav_id
        try:
            self._gerar(dav_id)
        except Exception:
            log.exception("Fila do DAV: DAV %s quebrou fora do robô", dav_id)
        finally:
            with self._trava:
                self._gerando = None

    def _gerar(self, dav_id: int) -> None:
        linha = self._no_banco(self.banco.dav, dav_id, None)
        if linha is None or linha["estado"] != "fila":
            log.warning("Fila do DAV: %s não está em fila (%s), pulando", dav_id,
                        linha and linha["estado"])
            return
        self._no_banco(self.banco.dav_atualizar, dav_id, estado="gerando",
                       iniciado_em=_agora())
        try:
            campos = self._campos(self._chamar_executor(dav_id, linha["arquivo"]))
        except HseIndisponivel as e:
            erro = str(e) + HSE_RECUSOU if str(e).startswith(RECUSA_LOGIN) else HSE_FORA
            campos = {"estado": "erro", "erro": _sem_segredo(erro)}
        except Exception as e:
            campos = {"estado": "erro", "erro": _sem_segredo(str(e) or type(e).__name__)}
        linha = self._no_banco(self.banco.dav, dav_id, None)
        if linha is None or linha["estado"] != "gerando":
            log.warning("Fila do DAV: %s saiu de gerando (%s), resultado não gravado",
                        dav_id, linha and linha["estado"])
            return
        self._no_banco(self.banco.dav_atualizar, dav_id, terminado_em=_agora(), **campos)

    def _chamar_executor(self, dav_id: int, nome: str) -> Resultado:
        def ao_salvar(numero: str) -> None:
            # Já existe no HSE: grava já, para a queda não virar "incerto" sem número.
            self._no_banco(self.banco.dav_atualizar, dav_id, numero=numero)
            log.warning("Fila do DAV: DAV %s salvo no HSE como orçamento %s", dav_id, numero)

        extras = {"ao_salvar": ao_salvar, "nome": nome}
        aceitos = inspect.signature(self._executar).parameters
        return self._executar(self.planilha(dav_id), self.pasta / "pdf",
                              **{k: v for k, v in extras.items() if k in aceitos})

    @staticmethod
    def _campos(r: Resultado) -> dict:
        campos = {"estado": r.estado, "numero": r.numero, "cliente": r.cliente,
                  "relatorio": _sem_segredo(r.relatorio),
                  "pdf": str(r.pdf) if r.pdf else None}
        if r.estado == "adiado":
            campos.update(estado="erro", erro=HSE_FORA)
        return campos

    def _executar_no_hse(self, planilha: Path, pasta_pdf: Path,
                         ao_salvar=None, nome: str | None = None) -> Resultado:
        # Import aqui: o playwright só carrega quando um DAV roda de verdade.
        from core.retentativa import VAGA_NAVEGADOR
        from orcamento.config import config_do_ambiente
        from orcamento.hse import Hse
        from orcamento.processador import gerar

        try:
            cfg = config_do_ambiente()
        except ValueError:
            raise RuntimeError(SEM_LOGIN) from None
        # ia_uso.csv / ia_cache.json ficam em davs/, nunca na raiz do repo.
        cfg = replace(cfg, pasta_programa=self.pasta)
        pasta_pdf.mkdir(parents=True, exist_ok=True)
        try:
            with VAGA_NAVEGADOR, Hse(cfg) as hse:
                return gerar(planilha, cfg, hse, pasta_pdf, ao_salvar, nome)
        except HseIndisponivel as e:
            if str(e).startswith(RECUSA_LOGIN):
                raise
            return Resultado("adiado", None, None, "", "")
