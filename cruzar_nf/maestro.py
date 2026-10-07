"""Ligação do cruzamento de NF com o gerenciador do Maestro (gerenciador.py).

No gerenciador.py, depois de criar o `sio` e o `CONFIG_GLOBAL`:

    from cruzar_nf.maestro import registrar as registrar_sync_nf
    registrar_sync_nf(sio, CONFIG_GLOBAL, logger, schedule=schedule)

Isso registra:
- `comando_sync_nf_estado` -> `retorno_sync_nf_estado`: última sincronização
  e a janela que a próxima vai usar;
- `comando_sync_nf` -> `progresso_sync_nf` (vários) e `retorno_sync_nf`:
  exporta do HSE, junta na base, grava a NF nos pedidos;
- o agendamento diário (padrão 07:30, depois do backup das 07:00).

A gravação usa `planilha_manager.lock`: o planilha_manager carrega o
PEDIDOS.json uma vez e regrava tudo, então gravar por fora seria sobrescrito.

Compatível com Python 3.8.
"""

from __future__ import annotations

import datetime as _dt
import glob
import os
import shutil
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from cruzar_nf.cruzar import _chave_campo, campo, cruzar

HORARIO_PADRAO = "07:30"
CAMPO_NF = "Nº NOTA FISCAL"     # mesmo nome da coluna da planilha Excel antiga
MANTER_BACKUPS = 30


def _nome_campo_nf(pedido: Dict[str, Any]) -> str:
    """O campo como já está no pedido ("Nº NOTA FISCAL " com espaço), ou o padrão."""
    return next((k for k in pedido if _chave_campo(k) == _chave_campo(CAMPO_NF)), CAMPO_NF)


def _guardar_backup(caminho: str, dir_backup: str, prefixo: str = "PEDIDOS antes da NF") -> None:
    os.makedirs(dir_backup, exist_ok=True)
    carimbo = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    shutil.copy2(caminho, os.path.join(dir_backup, f"{prefixo} {carimbo}.json"))
    antigos = sorted(glob.glob(os.path.join(dir_backup, f"{prefixo} *.json")))
    for velho in antigos[:-MANTER_BACKUPS]:
        os.remove(velho)


def aplicar_nfs(manager: Any, vendas: List[Dict[str, Any]], gravar: bool = False,
                so_vazias: bool = True, dir_backup: Optional[str] = None) -> Tuple[dict, int]:
    """Cruza os pedidos do manager com as vendas. Com gravar=True, grava a NF.

    Devolve (relatório, quantos pedidos tiveram a NF alterada). Tudo dentro
    da trava: nenhum robô adiciona pedido no meio. Aplica por POSIÇÃO (há
    pedido repetido na planilha). so_vazias=True não troca NF que já existe.
    """
    manager.iniciar()
    with manager.lock:
        lista = [p for p in manager.pedidos.get("PEDIDOS", []) if isinstance(p, dict)]
        atualizados, relatorio = cruzar(lista, vendas)
        mudancas = []
        for original, novo in zip(lista, atualizados):
            atual = str(campo(original, CAMPO_NF) or "").strip()
            if so_vazias and atual:
                continue
            if novo["NF"] and novo["NF"] != atual:
                mudancas.append((original, novo["NF"]))
        if gravar and mudancas:
            if dir_backup and os.path.exists(manager.caminho_pedidos):
                _guardar_backup(manager.caminho_pedidos, dir_backup)
            for original, nf in mudancas:
                original[_nome_campo_nf(original)] = nf
            if not manager.salvar():
                raise RuntimeError("Não consegui gravar o PEDIDOS.json.")
        return relatorio, len(mudancas)


class _Execucao:
    """Garante uma sincronização por vez (botão + agendamento)."""

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self.rodando = False

    def iniciar(self) -> bool:
        with self._trava:
            if self.rodando:
                return False
            self.rodando = True
            return True

    def terminar(self) -> None:
        with self._trava:
            self.rodando = False


def registrar(sio: Any, config: Dict[str, Any], logger: Any, manager: Any = None,
              exportar: Optional[Callable] = None, schedule: Any = None,
              horario: str = HORARIO_PADRAO, em_thread: bool = True) -> Dict[str, Callable]:
    """Registra os comandos no `sio` do gerenciador. Devolve os handlers (para teste)."""
    from cruzar_nf import sincronizar as sync

    execucao = _Execucao()

    def _manager():
        if manager is not None:
            return manager
        from planilha_manager import planilha_manager   # o do gerenciador
        return planilha_manager

    def _pasta() -> str:
        return config.get("caminho_banco_dados") or "."

    def _exportar():
        if exportar is not None:
            return exportar
        from cruzar_nf.hse_robo import exportador_do_config
        return exportador_do_config(config)

    def _rodar(de: _dt.date, ate: _dt.date, gravar: bool, client_id: Optional[str], origem: str) -> None:
        def progresso(msg: str) -> None:
            logger.info(f"[sync NF] {msg}")
            sio.emit("progresso_sync_nf", {"mensagem": msg, "clientId": client_id})
        try:
            resultado = sync.sincronizar(_pasta(), _manager(), de=de, ate=ate, exportar=_exportar(),
                                         gravar=gravar, dir_backup=config.get("caminho_backups"),
                                         progresso=progresso, origem=origem)
            sio.emit("retorno_sync_nf", {"sucesso": True, "resultado": resultado, "clientId": client_id})
            if resultado.get("nfs_gravadas"):
                sio.emit("planilha_atualizada")
        except Exception as e:   # o robô não pode cair por causa da sincronização
            logger.error(f"[sync NF] falhou: {e}")
            sync.registrar_falha(_pasta(), de, ate, str(e), origem)
            sio.emit("retorno_sync_nf", {"sucesso": False, "erro": str(e), "clientId": client_id})
        finally:
            execucao.terminar()

    def disparar(de: _dt.date, ate: _dt.date, gravar: bool, client_id: Optional[str], origem: str) -> bool:
        if not execucao.iniciar():
            sio.emit("retorno_sync_nf", {"sucesso": False, "clientId": client_id,
                                         "erro": "Já existe uma sincronização rodando."})
            return False
        if em_thread:
            threading.Thread(target=_rodar, args=(de, ate, gravar, client_id, origem), daemon=True).start()
        else:
            _rodar(de, ate, gravar, client_id, origem)
        return True

    def _estado_cadastro() -> Dict[str, Any]:
        """Cadastro automático de pedidos (cadastro_pedidos.py): mesma pasta de dados,
        vai junto para o portal não precisar de evento novo. Erro aqui não derruba a NF."""
        from cruzar_nf.cadastro_pedidos import estado_para_tela
        try:
            return estado_para_tela(_pasta())
        except Exception as e:
            return {"ativo": False, "erro": {"em": None, "mensagem": f"Erro ao ler o estado: {e}"}}

    def comando_sync_nf_estado(dados: Optional[dict] = None) -> None:
        dados = dados or {}
        try:
            estado = sync.estado_para_tela(_pasta())
            estado["rodando"] = execucao.rodando
            estado["cadastro_pedidos"] = _estado_cadastro()
            sio.emit("retorno_sync_nf_estado", {"sucesso": True, "estado": estado,
                                                "clientId": dados.get("clientId")})
        except Exception as e:
            sio.emit("retorno_sync_nf_estado", {"sucesso": False, "erro": str(e),
                                                "clientId": dados.get("clientId")})

    def comando_sync_nf(dados: Optional[dict] = None) -> None:
        dados = dados or {}
        client_id = dados.get("clientId")
        try:
            de, ate = sync.janela(_pasta(), dados.get("de"), dados.get("ate"))
        except ValueError as e:
            sio.emit("retorno_sync_nf", {"sucesso": False, "erro": str(e), "clientId": client_id})
            return
        disparar(de, ate, dados.get("gravar", True) is not False, client_id, "portal")

    def agendado() -> None:
        de, ate = sync.janela(_pasta(), None, None)
        disparar(de, ate, True, None, "agendado")

    sio.on("comando_sync_nf_estado", comando_sync_nf_estado)
    sio.on("comando_sync_nf", comando_sync_nf)
    if schedule is not None and horario:
        schedule.every().day.at(horario).do(agendado)
    return {"estado": comando_sync_nf_estado, "sincronizar": comando_sync_nf, "agendado": agendado}
