"""Ligação do cruzamento de NF com o gerenciador do Maestro (gerenciador.py).

No gerenciador.py, depois de criar o `sio` e o `CONFIG_GLOBAL`:

    from cruzar_nf.maestro import registrar as registrar_sync_nf
    registrar_sync_nf(sio, CONFIG_GLOBAL, logger, schedule=schedule)

Isso registra:
- `comando_sync_nf_estado` -> `retorno_sync_nf_estado`: última sincronização
  e a janela que a próxima vai usar;
- `comando_sync_nf` -> `progresso_sync_nf` (vários) e `retorno_sync_nf`:
  exporta do HSE, junta na base, grava a NF nos pedidos;
- `comando_nf_painel` -> `retorno_nf_painel` e `comando_eventos_nf` ->
  `retorno_eventos_nf`: só leitura, para os dashboards (painel_nf.py);
- o agendamento diário (padrão 07:30, depois do backup das 07:00).

A gravação usa `planilha_manager.lock`: o planilha_manager carrega o
PEDIDOS.json uma vez e regrava tudo, então gravar por fora seria sobrescrito.

Compatível com Python 3.8.
"""

from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import shutil
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from cruzar_nf.cruzar import _chave_campo, campo, cruzar, gravar_json

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

    def _sincronizar_nf(de: _dt.date, ate: _dt.date, gravar: bool, progresso: Callable[[str], None],
                        origem: str) -> Dict[str, Any]:
        """HSE -> PEDIDOS.json. A falha fica no histórico e sobe para quem chamou."""
        inicio = sync.agora_iso()
        try:
            return sync.sincronizar(_pasta(), _manager(), de=de, ate=ate, exportar=_exportar(),
                                    gravar=gravar, dir_backup=config.get("caminho_backups"),
                                    progresso=progresso, origem=origem)
        except sync.SincronizacaoEmAndamento:   # outra rodada segurando a trava não é falha da NF
            raise
        except Exception as e:
            logger.error(f"[sync NF] falhou: {e}")
            sync.registrar_falha(_pasta(), de, ate, str(e), origem, inicio)
            raise

    def _rodar(de: _dt.date, ate: _dt.date, gravar: bool, client_id: Optional[str], origem: str) -> None:
        def progresso(msg: str) -> None:
            logger.info(f"[sync NF] {msg}")
            sio.emit("progresso_sync_nf", {"mensagem": msg, "clientId": client_id})
        try:
            resultado = _sincronizar_nf(de, ate, gravar, progresso, origem)
            sio.emit("retorno_sync_nf", {"sucesso": True, "resultado": resultado, "clientId": client_id})
            if resultado.get("nfs_gravadas"):
                sio.emit("planilha_atualizada")
        except Exception as e:   # o robô não pode cair por causa da sincronização
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

    def _conferencia() -> Optional[Dict[str, Any]]:
        from cruzar_nf.planilha_portal import resumo_para_tela
        try:
            return resumo_para_tela(_pasta())
        except Exception as e:
            return {"erro": f"Erro ao ler a conferência: {e}"}

    def _planilha_e_pedidos() -> Tuple[str, str]:
        from cruzar_nf.cadastro_pedidos import PLANILHA_PADRAO
        planilha = config.get("caminho_planilha") or os.environ.get("CADASTRO_PLANILHA") or PLANILHA_PADRAO
        return planilha, config.get("caminho_pedidos") or _manager().caminho_pedidos

    def _gravar_planilha(gravar: bool, progresso: Callable[[str], None]) -> Dict[str, Any]:
        from cruzar_nf import nf_planilha
        planilha, pedidos = _planilha_e_pedidos()
        return nf_planilha.gravar_nf_na_planilha(planilha, pedidos, _pasta(), gravar=gravar, progresso=progresso)

    def _nf_planilha(gravar: bool, client_id: Optional[str]) -> None:
        def progresso(msg: str) -> None:
            logger.info(f"[NF na planilha] {msg}")
            sio.emit("progresso_nf_planilha", {"mensagem": msg, "clientId": client_id})
        try:
            res = _gravar_planilha(gravar, progresso)
            sio.emit("retorno_nf_planilha", {"sucesso": True, "resultado": res, "clientId": client_id})
        except Exception as e:   # planilha aberta, mudou no meio, rede: nada foi gravado
            logger.error(f"[NF na planilha] {e}")
            sio.emit("retorno_nf_planilha", {"sucesso": False, "erro": str(e), "clientId": client_id})

    def comando_nf_planilha(dados: Optional[dict] = None) -> None:
        dados = dados or {}
        args = (dados.get("gravar") is True, dados.get("clientId"))   # só grava se pedirem explicitamente
        if em_thread:
            threading.Thread(target=_nf_planilha, args=args, daemon=True).start()
        else:
            _nf_planilha(*args)

    def comando_sync_nf_estado(dados: Optional[dict] = None) -> None:
        dados = dados or {}
        try:
            estado = sync.estado_para_tela(_pasta())
            estado["rodando"] = execucao.rodando
            estado["cadastro_pedidos"] = _estado_cadastro()
            estado["conferencia_planilha"] = _conferencia()
            try:
                from cruzar_nf.sync_planilha_portal import estado_para_tela as estado_sync_planilha
                estado["sync_planilha_portal"] = estado_sync_planilha(_pasta())
            except Exception as e:
                estado["sync_planilha_portal"] = {"erro": str(e)}
            sio.emit("retorno_sync_nf_estado", {"sucesso": True, "estado": estado,
                                                "clientId": dados.get("clientId")})
        except Exception as e:
            sio.emit("retorno_sync_nf_estado", {"sucesso": False, "erro": str(e),
                                                "clientId": dados.get("clientId")})

    def comando_sync_planilha_painel(dados: Optional[dict] = None) -> None:
        dados = dados or {}
        try:
            from cruzar_nf.sync_planilha_portal import painel_para_tela
            sio.emit("retorno_sync_planilha_painel", {"sucesso": True, "painel": painel_para_tela(_pasta()),
                                                      "clientId": dados.get("clientId")})
        except Exception as e:
            sio.emit("retorno_sync_planilha_painel", {"sucesso": False, "erro": str(e),
                                                      "clientId": dados.get("clientId")})

    def _responder(evento: str, chave: str, ler: Callable[[dict], Any]) -> Callable:
        """Comando só de leitura dos dashboards: devolve `chave` ou o erro, sempre com o clientId."""
        def comando(dados: Optional[dict] = None) -> None:
            dados = dados if isinstance(dados, dict) else {}
            try:
                sio.emit(evento, {"sucesso": True, chave: ler(dados), "clientId": dados.get("clientId")})
            except Exception as e:
                sio.emit(evento, {"sucesso": False, "erro": str(e), "clientId": dados.get("clientId")})
        return comando

    def _painel_nf(_dados: dict) -> Dict[str, Any]:
        from cruzar_nf.painel_nf import painel_para_tela
        painel = painel_para_tela(_pasta())
        painel["rodando"] = execucao.rodando
        return painel

    def _eventos_nf(dados: dict) -> Dict[str, Any]:
        from cruzar_nf.painel_nf import eventos
        return eventos(_pasta(), dados.get("limite", 200), dados.get("desde"))

    comando_nf_painel = _responder("retorno_nf_painel", "painel", _painel_nf)
    comando_eventos_nf = _responder("retorno_eventos_nf", "resultado", _eventos_nf)

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

    # -- Sincronização manual (botões do dashboard do admin; docs/sincronizacao no portal) ---------------
    execucao_planilha = _Execucao()
    ARQ_MANUAL = "sincronizacao_manual.json"   # último resultado de cada botão (a falha na planilha não fica em outro lugar)

    def _nf_completo(progresso: Callable[[str], None]) -> str:
        """HSE -> portal e, se deu certo, portal -> coluna N da planilha. Mesma janela da rodada agendada.
        Fica "rodando" até o fim da planilha: antes disso outro clique faria uma segunda exportação do HSE."""
        if not execucao.iniciar():
            raise sync.SincronizacaoEmAndamento("Já existe uma sincronização de NF rodando.")
        try:
            de, ate = sync.janela(_pasta(), None, None)
            resultado = _sincronizar_nf(de, ate, True, progresso, "portal")
            if resultado.get("nfs_gravadas"):
                sio.emit("planilha_atualizada")
            feito = f"HSE → portal: {resultado.get('nfs_gravadas', 0)} NF(s) gravada(s)"
            try:
                res = _gravar_planilha(True, progresso)
            except Exception as e:   # planilha aberta, mudou no meio: o portal já está certo
                raise RuntimeError(f"{feito}; a planilha não foi gravada: {e}") from e
            return f"{feito}; portal → planilha: {res.get('gravadas', 0)} NF(s) gravada(s)"
        finally:
            execucao.terminar()

    def _sync_planilha(progresso: Callable[[str], None]) -> str:
        """Planilha ⇄ portal gravando, sem o `--diario`: roda mesmo depois da rodada do dia."""
        from cruzar_nf import sync_planilha_portal as SP
        if not execucao_planilha.iniciar():
            raise sync.SincronizacaoEmAndamento("O sync da planilha já está rodando.")
        try:
            planilha, pedidos = _planilha_e_pedidos()
            progresso("Comparando a planilha dos estagiários com o portal...")
            try:
                r = SP.sincronizar(planilha, pedidos, _pasta(), gravar=True)
            except Exception as e:
                try:
                    SP.registrar_erro(_pasta(), e)
                except Exception as e2:   # o erro original é o que importa para quem clicou
                    logger.error(f"[sync_planilha] não consegui registrar o erro no painel: {e2}")
                raise
        finally:
            execucao_planilha.terminar()
        if r.get("gravou"):
            sio.emit("planilha_atualizada")
        if r.get("adiado"):
            raise RuntimeError(f"Adiado: {r.get('aviso') or 'a planilha está aberta no Excel'}")
        if r.get("primeira_vez"):
            return "Primeira rodada: foto inicial registrada (nada foi copiado)."
        n = {k: len(r.get(k) or []) for k in ("acoes", "conflitos", "ambiguas")}
        partes = [f"{n['acoes']} alteração(ões) gravada(s)"]
        if n["conflitos"]:
            partes.append(f"{n['conflitos']} conflito(s) para revisar no painel")
        if n["ambiguas"]:
            partes.append(f"{n['ambiguas']} ambígua(s)")
        return "; ".join(partes)

    manuais = {"nf_completo": _nf_completo, "sync_planilha": _sync_planilha}

    def _responder_sincronizacao(dados: dict, sucesso: bool, texto: str) -> None:
        sio.emit("retorno_sincronizacao", {"servico": dados.get("servico"), "sucesso": sucesso,
                                           ("mensagem" if sucesso else "erro"): texto,
                                           "clientId": dados.get("clientId"), "audit_id": dados.get("audit_id")})

    def _ler_manual() -> Dict[str, Any]:
        arq = os.path.join(_pasta(), ARQ_MANUAL)
        if not os.path.exists(arq):
            return {}
        with open(arq, encoding="utf-8") as f:
            return json.load(f)

    def _guardar_manual(servico: str, sucesso: bool, texto: str) -> None:
        arq = os.path.join(_pasta(), ARQ_MANUAL)
        try:
            atual = _ler_manual()
            atual[servico] = {"em": sync.agora_iso(), "nivel": "ok" if sucesso else "erro", "resumo": texto,
                              "detalhe": {"origem": "portal"}}
            gravar_json(arq, atual)
        except Exception as e:   # é só para o cartão; não muda o resultado do botão
            logger.error(f"[{servico}] resultado não guardado para o cartão: {e}")

    def _rodar_manual(dados: dict) -> None:
        servico = dados["servico"]

        def progresso(msg: str) -> None:
            logger.info(f"[{servico}] {msg}")
            sio.emit("progresso_sincronizacao", {"servico": servico, "mensagem": msg})
        try:
            progresso("Começou.")
            texto = manuais[servico](progresso)
            _guardar_manual(servico, True, texto)
            _responder_sincronizacao(dados, True, texto)
        except sync.SincronizacaoEmAndamento as e:   # recusado: nada rodou, o último resultado continua o mesmo
            _responder_sincronizacao(dados, False, str(e))
        except Exception as e:   # o serviço não pode cair por causa de um botão
            logger.error(f"[{servico}] {e}")
            _guardar_manual(servico, False, str(e))
            _responder_sincronizacao(dados, False, str(e))

    def comando_sincronizacao(dados: Optional[dict] = None) -> None:
        dados = dados if isinstance(dados, dict) else {}
        if not isinstance(dados.get("servico"), str) or dados["servico"] not in manuais:
            _responder_sincronizacao(dados, False, f"Serviço desconhecido: {dados.get('servico')}")
        elif em_thread:
            threading.Thread(target=_rodar_manual, args=(dados,), daemon=True).start()
        else:
            _rodar_manual(dados)

    def _ultimas_sincronizacao() -> Dict[str, Any]:
        """Último resultado de cada cartão, no formato dos eventos do gerenciador ({em, nivel, resumo})."""
        from cruzar_nf.sync_planilha_portal import FMT_HORA, ultima_rodada
        ultimas: Dict[str, Any] = {}
        try:   # cada cartão por si: um arquivo ruim não derruba os outros nem o "rodando"
            h = next((x for x in sync.carregar_estado(_pasta()).get("historico", [])
                      if x.get("gravou") or not x.get("sucesso")), None)   # prévia não conta
            if h:
                ultimas["nf_completo"] = {
                    "em": h.get("rodou_em"), "nivel": "ok" if h.get("sucesso") else "erro",
                    "resumo": (f"{h.get('nfs_gravadas', 0)} NF(s) gravada(s) no portal" if h.get("sucesso")
                               else h.get("erro")), "detalhe": {"origem": h.get("origem")}}
        except Exception as e:
            logger.error(f"[estado] histórico da NF ilegível: {e}")
        try:
            rod = ultima_rodada(_pasta())
            if rod:
                ultimas["sync_planilha"] = {
                    "em": _dt.datetime.strptime(rod["em"], FMT_HORA).isoformat(timespec="seconds"),
                    "nivel": "erro" if rod.get("resultado") in ("erro", "adiado") else "ok",
                    "resumo": rod.get("resultado", "") + (f": {rod['aviso']}" if rod.get("aviso") else "")}
        except Exception as e:
            logger.error(f"[estado] histórico do sync da planilha ilegível: {e}")
        try:   # o botão mais recente vale mais (ex.: o portal recebeu a NF mas a planilha estava aberta)
            for servico, manual in _ler_manual().items():
                if servico not in ultimas or str(manual.get("em", "")) >= str(ultimas[servico].get("em") or ""):
                    ultimas[servico] = manual
        except Exception as e:
            logger.error(f"[estado] resultado dos botões ilegível: {e}")
        return ultimas

    def comando_sincronizacao_estado(dados: Optional[dict] = None) -> None:
        dados = dados if isinstance(dados, dict) else {}
        try:
            rodando = [s for s, ex in (("nf_completo", execucao), ("sync_planilha", execucao_planilha)) if ex.rodando]
            sio.emit("retorno_sincronizacao_estado", {"sucesso": True, "clientId": dados.get("clientId"),
                                                      "estado": {"rodando": rodando, "ultimas": _ultimas_sincronizacao()}})
        except Exception as e:
            sio.emit("retorno_sincronizacao_estado", {"sucesso": False, "erro": str(e), "clientId": dados.get("clientId")})

    sio.on("comando_sincronizacao", comando_sincronizacao)
    sio.on("comando_sincronizacao_estado", comando_sincronizacao_estado)
    sio.on("comando_sync_nf_estado", comando_sync_nf_estado)
    sio.on("comando_sync_nf", comando_sync_nf)
    sio.on("comando_nf_planilha", comando_nf_planilha)
    sio.on("comando_sync_planilha_painel", comando_sync_planilha_painel)
    sio.on("comando_nf_painel", comando_nf_painel)
    sio.on("comando_eventos_nf", comando_eventos_nf)
    if schedule is not None and horario:
        schedule.every().day.at(horario).do(agendado)
    return {"estado": comando_sync_nf_estado, "sincronizar": comando_sync_nf, "agendado": agendado,
            "nf_planilha": comando_nf_planilha, "painel_planilha": comando_sync_planilha_painel,
            "painel_nf": comando_nf_painel, "eventos_nf": comando_eventos_nf,
            "sincronizacao": comando_sincronizacao, "sincronizacao_estado": comando_sincronizacao_estado}
