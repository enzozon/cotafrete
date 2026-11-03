"""Fila da conferência do rascunho: simula o DAV no HSE só leitura.

Uma conferência por vez, numa thread só. O resultado vai para as colunas
`conferencia` / `conferencia_relatorio` da tabela `dav`, e só se o DAV ainda
for um rascunho `conferindo` (senão alguém já mexeu nele). Passou do tempo, o
HSE caiu ou algo quebrou: `nao_conferido`; o robô confere de novo ao gerar.

A planilha é a mesma do FilaDav: `<pasta>/entrada/<id>.xlsx`.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable

from core.banco import Banco
from orcamento.fila import _sem_segredo, no_banco
from orcamento.processador import Conferencia, HseIndisponivel, conferir

log = logging.getLogger(__name__)

LIMITE_CONFERENCIA_S = 120
SEM_HSE = "Não consegui conferir com o HSE agora; o robô confere de novo ao gerar."
SEM_LOGIN = "Robô do HSE sem login configurado no servidor."


def _limpa(conf: Conferencia) -> Conferencia:
    """Cópia com a senha tirada de cada texto; o JSON gravado nunca é tocado."""
    s = _sem_segredo
    return replace(conf, relatorio=s(conf.relatorio), cliente=s(conf.cliente), endereco=s(conf.endereco),
                   vendedor=s(conf.vendedor), avisos=tuple(map(s, conf.avisos)), erros=tuple(map(s, conf.erros)),
                   itens=tuple(replace(i, descricao=s(i.descricao)) for i in conf.itens))


def _nao_conferido(motivo: str) -> Conferencia:
    return Conferencia("nao_conferido", motivo, "", "", "", (), (SEM_HSE,), ())


class FilaConferencia:
    def __init__(self, banco: Banco, pasta: Path,
                 executar: Callable[[Path], Conferencia] | None = None,
                 disparar: Callable[[Callable[[], None]], None] | None = None,
                 limite_s: float = LIMITE_CONFERENCIA_S) -> None:
        self.banco = banco
        self.pasta = Path(pasta)
        self._executar = executar or self._executar_no_hse
        self._disparar = disparar or self._na_thread
        self._limite_s = limite_s
        self._trava = threading.Lock()
        self._tarefas: queue.Queue = queue.Queue()
        self._trabalhadora: threading.Thread | None = None

    def enfileirar(self, dav_id: int) -> None:
        self._disparar(lambda: self._conferir(dav_id))

    def retomar(self) -> None:
        self.banco.dav_conferencia_interromper()

    # ------------------------------------------------------------ interno
    def _na_thread(self, tarefa: Callable[[], None]) -> None:
        with self._trava:
            if self._trabalhadora is None:
                self._trabalhadora = threading.Thread(
                    target=self._consumir, name="fila-conferencia", daemon=True)
                self._trabalhadora.start()
        self._tarefas.put(tarefa)

    def _consumir(self) -> None:
        while True:
            tarefa = self._tarefas.get()
            try:
                tarefa()
            except Exception as e:   # nunca derruba a thread; sem traceback (pode ter a senha)
                log.error("Fila da conferência: tarefa quebrou: %s", _sem_segredo(str(e)) or type(e).__name__)

    def _conferir(self, dav_id: int) -> None:
        conf = self._com_limite(self.pasta / "entrada" / f"{dav_id}.xlsx")
        linha = no_banco(self.banco.dav, dav_id, None)
        if linha is None or linha["estado"] != "rascunho" or linha["conferencia"] != "conferindo":
            log.warning("Fila da conferência: %s mudou durante a conferência, não gravado", dav_id)
            return
        no_banco(self.banco.dav_atualizar, dav_id, conferencia=conf.estado,
                 conferencia_relatorio=_limpa(conf).para_json())

    def _com_limite(self, planilha: Path) -> Conferencia:
        """Roda o executor numa thread auxiliar; passou do tempo, abandona-a
        (daemon): o resultado dela nunca é gravado."""
        saida: list[Conferencia] = []
        erro: list[Exception] = []

        def rodar() -> None:
            try:
                saida.append(self._executar(planilha))
            except Exception as e:
                erro.append(e)

        aux = threading.Thread(target=rodar, name="conferencia-hse", daemon=True)
        aux.start()
        aux.join(self._limite_s)
        if aux.is_alive():
            return _nao_conferido(SEM_HSE)
        if erro:
            e = erro[0]
            if isinstance(e, HseIndisponivel):
                return _nao_conferido(SEM_HSE)
            motivo = _sem_segredo(str(e)) or type(e).__name__
            log.error("Fila da conferência: %s quebrou: %s", planilha.name, motivo)
            return _nao_conferido(motivo)
        return saida[0]

    def _executar_no_hse(self, planilha: Path) -> Conferencia:
        # Import aqui: o playwright só carrega quando uma conferência roda de verdade.
        from core.retentativa import VAGA_NAVEGADOR
        from orcamento.config import config_do_ambiente
        from orcamento.hse import HseSoLeitura

        try:
            cfg = config_do_ambiente()
        except ValueError:
            return _nao_conferido(SEM_LOGIN)
        cfg = replace(cfg, dry_run=True, pasta_programa=self.pasta)
        with VAGA_NAVEGADOR, HseSoLeitura(cfg) as hse:
            return conferir(planilha, cfg, hse)
