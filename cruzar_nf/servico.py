"""Serviço de NF: sincroniza as NFs do HSE com o PEDIDOS.json SEM mexer no gerenciador.py.

Roda num processo à parte, no servidor, ao lado do gerenciador:

    python -m cruzar_nf.servico          (ou ServicoNF.bat)

- conecta no portal (o mesmo URL_SERVIDOR do gerenciador) e se identifica
  com `sou_o_sync_nf` + SYNC_NF_TOKEN (o portal recusa sem o token certo);
- atende `comando_sync_nf_estado` e `comando_sync_nf` (botão do portal);
- roda sozinho todo dia às 07:30;
- grava a NF com `ArquivoPedidosConcorrente`: o planilha_manager do
  gerenciador recarrega o PEDIDOS.json quando o arquivo muda.

Variáveis no .env (o mesmo do gerenciador serve):
    URL_SERVIDOR        portal (padrão: https://maestro.ventura.inf.br)
    SYNC_NF_TOKEN       senha do serviço — igual à configurada no portal
    SYNC_NF_DADOS       pasta da base (vendas_hse.json / sync_nf.json)
    SYNC_NF_PEDIDOS     o PEDIDOS.json do Maestro (o mesmo da linha de comando)
    SYNC_NF_BACKUPS     pasta dos backups do PEDIDOS.json (padrão: SYNC_NF_DADOSackups)
    SYNC_NF_HORARIO     horário da rodada diária (padrão 07:30; vazio = sem)
    SYNC_NF_LOG         arquivo de log (opcional)
    SYNC_NF_EXCEL       (opcional) Excel de Venda (pedido) já baixado: sincroniza
                        com ele em vez de usar o robô do HSE (plano B manual)
    HSE_USUARIO, HSE_SENHA, HSE_HEADLESS   login do robô do HSE

Compatível com Python 3.8.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any, Dict, Optional

URL_PADRAO = "https://maestro.ventura.inf.br"   # portal no Cloudflare Tunnel (a Render saiu do ar)
ESPERA_RECONEXAO_S = 30


class ConfigInvalida(ValueError):
    pass


def config_do_ambiente(ambiente: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    amb = os.environ if ambiente is None else ambiente
    token = (amb.get("SYNC_NF_TOKEN") or "").strip()
    if not token:
        raise ConfigInvalida("Falta SYNC_NF_TOKEN no .env (a mesma senha configurada no portal).")
    # as mesmas pastas e padrões da linha de comando (SincronizarNF.bat), lidas do mesmo .env
    from cruzar_nf.sincronizar import DADOS_PADRAO, PEDIDOS_PADRAO
    dados = amb.get("SYNC_NF_DADOS") or DADOS_PADRAO
    return {
        "url": amb.get("URL_SERVIDOR") or URL_PADRAO,
        "token": token,
        "caminho_banco_dados": dados,
        "caminho_pedidos": amb.get("SYNC_NF_PEDIDOS") or PEDIDOS_PADRAO,
        "caminho_backups": amb.get("SYNC_NF_BACKUPS") or os.path.join(dados, "backups"),
        "horario": amb.get("SYNC_NF_HORARIO", "07:30").strip(),
        "log": amb.get("SYNC_NF_LOG") or None,
        # plano B manual: usa um Excel de Venda (pedido) já baixado em vez do robô do HSE
        "excel_fixo": amb.get("SYNC_NF_EXCEL") or None,
    }


def montar(sio: Any, config: Dict[str, Any], logger: Any, schedule: Any = None,
           exportar: Any = None, em_thread: bool = True) -> Dict[str, Any]:
    """Registra no `sio` a identificação e os comandos. Devolve os handlers (para teste)."""
    from cruzar_nf.arquivo_pedidos import ArquivoPedidosConcorrente
    from cruzar_nf.maestro import registrar

    def progresso(msg: str) -> None:
        logger.info(f"[sync NF] {msg}")

    manager = ArquivoPedidosConcorrente(config["caminho_pedidos"], progresso=progresso)
    if exportar is None and config.get("excel_fixo"):
        excel = config["excel_fixo"]

        def exportar(_de: Any, _ate: Any, aviso: Any = progresso) -> Dict[str, Any]:
            aviso(f"Usando o Excel já baixado {excel} (SYNC_NF_EXCEL), sem o robô do HSE.")
            return {"arquivo": excel, "linhas_tela": None}
    handlers = registrar(sio, config, logger, manager=manager, exportar=exportar,
                         schedule=schedule, horario=config.get("horario") or "", em_thread=em_thread)

    def ao_conectar() -> None:
        logger.info("Conectado ao portal; identificando o serviço de NF...")
        sio.emit("sou_o_sync_nf", {"token": config["token"]})

    def recusado(_dados: Any = None) -> None:
        logger.error("O portal recusou o serviço de NF: confira o SYNC_NF_TOKEN (aqui e na Render).")

    def ao_desconectar() -> None:
        logger.warning("Desconectado do portal; o socket tenta reconectar sozinho.")

    sio.on("connect", ao_conectar)
    sio.on("sync_nf_recusado", recusado)
    sio.on("disconnect", ao_desconectar)
    handlers.update({"connect": ao_conectar, "recusado": recusado})
    return handlers


def _configurar_log(caminho: Optional[str]) -> logging.Logger:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("servico_nf")
    logger.setLevel(logging.INFO)
    tela = logging.StreamHandler(sys.stdout)
    tela.setFormatter(fmt)
    logger.addHandler(tela)
    if caminho:
        try:
            arq = logging.FileHandler(caminho, encoding="utf-8")
            arq.setFormatter(fmt)
            logger.addHandler(arq)
        except OSError as e:
            logger.warning(f"Sem log em arquivo ({e}).")
    return logger


def main() -> int:
    try:
        from dotenv import load_dotenv     # o gerenciador já usa python-dotenv
        load_dotenv()
    except ImportError:
        pass
    try:
        config = config_do_ambiente()
    except ConfigInvalida as e:
        print(f"[ERRO] {e}", file=sys.stderr)
        return 1
    logger = _configurar_log(config["log"])

    import schedule
    import socketio

    sio = socketio.Client(reconnection=True, reconnection_delay=5, reconnection_delay_max=60)
    montar(sio, config, logger, schedule=schedule)

    def agenda() -> None:
        while True:
            try:
                schedule.run_pending()
            except Exception as e:      # uma rodada que falha não para o agendamento
                logger.error(f"Erro no agendamento: {e}")
            time.sleep(30)

    threading.Thread(target=agenda, daemon=True).start()
    logger.info(f"Serviço de NF iniciado. Portal: {config['url']} | dados: {config['caminho_banco_dados']}"
                f" | rodada diária: {config['horario'] or 'desligada'}")
    while True:
        try:
            sio.connect(config["url"], transports=["websocket", "polling"])
            sio.wait()
        except Exception as e:
            logger.error(f"Sem conexão com o portal ({e}); nova tentativa em {ESPERA_RECONEXAO_S}s.")
        time.sleep(ESPERA_RECONEXAO_S)


if __name__ == "__main__":
    sys.exit(main())
