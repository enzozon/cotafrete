"""Fila do diagnóstico: o agente explica por que um DAV falhou.

Uma por vez, numa thread só. O resultado (JSON) vai para as colunas
`diagnostico` / `diagnostico_estado` da tabela `dav`. Erro/incerto abrem o HSE
só leitura para buscar os pedidos; os demais casos usam só os arquivos locais.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable

from core.banco import Banco
from orcamento.fila import _sem_segredo, no_banco

log = logging.getLogger(__name__)

LIMITE_VAGA_S = 120


def deve_diagnosticar(dav: dict) -> bool:
    return (dav["estado"] in ("erro", "incerto", "rejeitado")
            or (dav["estado"] == "rascunho" and dav.get("conferencia") == "erros"))


class FilaDiagnostico:
    def __init__(self, banco: Banco, pasta: Path,
                 executar: Callable[[int], dict] | None = None,
                 disparar: Callable[[Callable[[], None]], None] | None = None) -> None:
        self.banco = banco
        self.pasta = Path(pasta)
        self._executar = executar or self._executar_padrao
        self._disparar = disparar or self._na_thread
        self._trava = threading.Lock()
        self._tarefas: queue.Queue = queue.Queue()
        self._trabalhadora: threading.Thread | None = None

    def enfileirar(self, dav_id: int) -> None:
        no_banco(self.banco.dav_atualizar, dav_id, diagnostico_estado="pendente")
        self._disparar(lambda: self._diagnosticar(dav_id))

    def retomar(self) -> None:
        for dav_id in self.banco.dav_diagnostico_pendentes():
            self._disparar(lambda i=dav_id: self._diagnosticar(i))

    # ------------------------------------------------------------ interno
    def _na_thread(self, tarefa: Callable[[], None]) -> None:
        with self._trava:
            if self._trabalhadora is None:
                self._trabalhadora = threading.Thread(
                    target=self._consumir, name="fila-diagnostico", daemon=True)
                self._trabalhadora.start()
        self._tarefas.put(tarefa)

    def _consumir(self) -> None:
        while True:
            tarefa = self._tarefas.get()
            try:
                tarefa()
            except Exception as e:   # nunca derruba a thread; sem traceback (pode ter a senha)
                log.error("Fila do diagnóstico: tarefa quebrou: %s", _sem_segredo(str(e)) or type(e).__name__)

    def _diagnosticar(self, dav_id: int) -> None:
        try:
            campos = {"diagnostico": json.dumps(self._executar(dav_id), ensure_ascii=False, default=str),
                      "diagnostico_estado": "feito"}
        except Exception as e:
            motivo = _sem_segredo(str(e)) or type(e).__name__
            log.error("Fila do diagnóstico: DAV %s falhou: %s", dav_id, motivo)
            campos = {"diagnostico": json.dumps({"motivo": motivo}, ensure_ascii=False),
                      "diagnostico_estado": "falhou"}
        no_banco(self.banco.dav_atualizar, dav_id, **campos)

    def _executar_padrao(self, dav_id: int) -> dict:
        # Import aqui: o playwright só carrega quando um diagnóstico roda de verdade.
        from core.retentativa import VAGA_NAVEGADOR
        from orcamento.agente import diagnosticar
        from orcamento.config import config_do_ambiente
        from orcamento.hse import HseSoLeitura
        from orcamento.processador import HseIndisponivel
        from orcamento.provas import buscador_hse, coletar
        from playwright.sync_api import Error as PlaywrightError

        cfg = replace(config_do_ambiente(), pasta_programa=self.pasta)   # gasto de IA junto ao do DAV-IA
        dav = self.banco.dav(dav_id, None)
        if dav is None:
            raise LookupError(f"DAV {dav_id} não existe")
        anterior = self.banco.dav_origem_da_correcao(dav_id)
        numero = str(dav.get("numero") or "")
        proprio = {int(numero)} if numero.isdigit() else set()   # outro DAV com o mesmo número não esconde o deste
        if dav["estado"] in ("erro", "incerto"):
            cfg_hse = replace(cfg, dry_run=True, pasta_programa=self.pasta)
            provas = None
            try:
                if not VAGA_NAVEGADOR.acquire(timeout=LIMITE_VAGA_S):
                    raise TimeoutError("navegador ocupado")
                try:
                    with HseSoLeitura(cfg_hse) as hse:
                        try:
                            provas = coletar(dav, self.pasta, buscador_hse(hse, self.banco.dav_numeros_com_hora()),
                                             ignorar=self.banco.dav_numeros_conhecidos(exceto=dav_id) - proprio,
                                             anterior=anterior)
                        finally:   # o alarme vale mesmo se a busca estourar
                            bloqueados = list(hse.bloqueados)
                            if bloqueados:   # a guarda segurou uma gravação: alarme, não indisponibilidade
                                raise RuntimeError("HSE bloqueou gravação na busca: " + "; ".join(bloqueados))
                finally:
                    VAGA_NAVEGADOR.release()
            except (HseIndisponivel, TimeoutError, ValueError, PlaywrightError) as e:
                # Sem sessão no HSE o diagnóstico segue, com os pedidos "não verificados".
                provas = coletar(dav, self.pasta, None, anterior=anterior)
                provas["motivo_nao_verificado"] = f"HSE indisponível: {_sem_segredo(str(e)) or type(e).__name__}"
        else:
            provas = coletar(dav, self.pasta, None, anterior=anterior)
        res = diagnosticar(provas, cfg)
        # a tela mostra por que os pedidos não foram verificados e o que o robô deixou no HSE
        for campo in ("motivo_nao_verificado", "produtos_criados", "rascunhos"):
            if provas.get(campo):
                res[campo] = provas[campo]
        self._issue(dav, res)
        return res

    def _issue(self, dav: dict, res: dict) -> None:
        """Culpa do robô com confiança alta vira issue no GitHub (só com GITHUB_TOKEN_ISSUES na VM)."""
        token = os.environ.get("GITHUB_TOKEN_ISSUES", "")
        if not token or res.get("culpa") != "robo" or res.get("confianca") != "alta":
            return
        from orcamento.issue_robo import registrar_issue
        try:
            url = registrar_issue(dav, res, self.pasta, token)
        except Exception as e:   # noqa: BLE001 — a issue nunca derruba o diagnóstico
            log.error("Fila do diagnóstico: issue do DAV %s falhou: %s", dav["id"], _sem_segredo(str(e))[:200])
            res["issue_erro"] = "não consegui abrir a issue no GitHub"
            return
        if url:
            res["issue"] = url
