"""Grava a NF no PEDIDOS.json por FORA do gerenciador, sem perder nada.

O serviço de NF (caminho B) roda num processo separado do gerenciador.py.
Isso só é seguro porque o planilha_manager do servidor (versão de
01/10/2026) recarrega o PEDIDOS.json no `iniciar()` quando a data de
modificação do arquivo muda, e todo ponto do gerenciador que grava chama
`iniciar()` antes. Sobra uma janela pequena: o gerenciador recarregar,
nós gravarmos, e ele salvar a memória dele por cima. Por isso:

1. lê o arquivo e guarda a assinatura (data de modificação + tamanho);
2. grava só se a assinatura não mudou desde a leitura — senão relê e refaz;
3. grava num temporário na mesma pasta e troca de uma vez (`os.replace`):
   quem ler no meio vê o arquivo velho inteiro ou o novo inteiro;
4. espera um pouco e relê: se alguma NF sumiu (o gerenciador salvou por
   cima) ou apareceu pedido novo com NF a gravar, refaz — a sincronização só
   preenche NF vazia, então refazer não estraga nada;
5. arquivo lido no meio de uma gravação do gerenciador (JSON cortado, ele
   grava sem temporário) -> espera e lê de novo.

O formato gravado é o mesmo do planilha_manager: {"PEDIDOS": [...]} com
indent=1 e acentos preservados. Compatível com Python 3.8.
"""

from __future__ import annotations

import json
import os
import re
import threading
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from cruzar_nf.maestro import aplicar_nfs as _aplicar_nfs

TENTATIVAS = 6
ESPERA_ENTRE_TENTATIVAS_S = 1.0
ESPERA_VERIFICACAO_S = 3.0
LEITURAS_JSON_CORTADO = 10
PASSO_DATA_NS = 20 * 1000 * 1000


class ConflitoGravacao(RuntimeError):
    """O PEDIDOS.json mudou entre a leitura e a gravação."""


def _assinatura(caminho: str) -> Tuple[int, int]:
    st = os.stat(caminho)
    return st.st_mtime_ns, st.st_size


def _interpretar(texto: str) -> Dict[str, Any]:
    """Mesma tolerância do planilha_manager.iniciar()."""
    texto = re.sub(r",\s*\}", "}", texto)
    texto = re.sub(r",\s*\]", "]", texto)
    if not texto.strip().startswith("{"):
        texto = "{" + texto + "}"
    return json.loads(texto)


class ArquivoPedidosConcorrente:
    """Tem a interface que o `maestro.aplicar_nfs` espera (lock, pedidos,
    caminho_pedidos, iniciar, salvar) e um `aplicar_nfs` próprio, com
    repetição e verificação, que o `sincronizar` usa quando existe."""

    def __init__(self, caminho: str, tentativas: int = TENTATIVAS,
                 espera_verificacao: float = ESPERA_VERIFICACAO_S,
                 dormir: Callable[[float], None] = time.sleep,
                 progresso: Callable[[str], None] = lambda _m: None):
        self.caminho_pedidos = str(caminho)
        self.lock = threading.RLock()
        self.pedidos: Dict[str, Any] = {"PEDIDOS": []}
        self.tentativas = tentativas
        self.espera_verificacao = espera_verificacao
        self.dormir = dormir
        self.progresso = progresso
        self._assinatura: Optional[Tuple[int, int]] = None

    # -- interface do planilha_manager ---------------------------------------
    def iniciar(self, *_: Any) -> None:
        ultimo_erro: Optional[Exception] = None
        for _i in range(LEITURAS_JSON_CORTADO):
            antes = _assinatura(self.caminho_pedidos)
            with open(self.caminho_pedidos, "r", encoding="utf-8-sig") as f:
                texto = f.read()
            try:
                dados = _interpretar(texto)
            except ValueError as e:          # pegou o gerenciador no meio da gravação
                ultimo_erro = e
                self.dormir(0.5)
                continue
            if _assinatura(self.caminho_pedidos) != antes:
                continue                     # mudou durante a leitura: lê de novo
            self.pedidos = dados
            self._assinatura = antes
            return
        raise RuntimeError(f"Não consegui ler o PEDIDOS.json inteiro: {ultimo_erro}")

    def salvar(self) -> bool:
        if self._assinatura is None or _assinatura(self.caminho_pedidos) != self._assinatura:
            raise ConflitoGravacao("o PEDIDOS.json mudou depois da leitura")
        fd, temporario = tempfile.mkstemp(prefix=".sync_nf_", suffix=".tmp",
                                         dir=os.path.dirname(os.path.abspath(self.caminho_pedidos)))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.pedidos, f, indent=1, ensure_ascii=False)
        if _assinatura(self.caminho_pedidos) != self._assinatura:   # última conferência
            os.remove(temporario)
            raise ConflitoGravacao("o PEDIDOS.json mudou durante a gravação")
        try:
            os.replace(temporario, self.caminho_pedidos)
        except OSError as e:                 # o gerenciador estava com o arquivo aberto
            try:
                os.remove(temporario)
            except OSError:
                pass
            raise ConflitoGravacao(f"não consegui trocar o arquivo: {e}")
        lido_em = self._assinatura[0]
        if _assinatura(self.caminho_pedidos)[0] <= lido_em:
            # o planilha_manager só relê se a data AUMENTAR; no mesmo passo do relógio ele não veria
            avancada = lido_em + PASSO_DATA_NS
            os.utime(self.caminho_pedidos, ns=(avancada, avancada))
        self._assinatura = _assinatura(self.caminho_pedidos)
        return True

    # -- gravação com repetição e verificação --------------------------------
    def aplicar_nfs(self, vendas: List[Dict[str, Any]], gravar: bool = False, so_vazias: bool = True,
                    dir_backup: Optional[str] = None) -> Tuple[dict, int]:
        if not gravar:
            return _aplicar_nfs(self, vendas, gravar=False, so_vazias=so_vazias)
        total = 0
        backup = dir_backup
        for tentativa in range(1, self.tentativas + 1):
            try:
                relatorio, n = _aplicar_nfs(self, vendas, gravar=True, so_vazias=so_vazias, dir_backup=backup)
            except ConflitoGravacao as e:
                self.progresso(f"PEDIDOS.json mudou durante a gravação ({e}); tentando de novo...")
                self.dormir(ESPERA_ENTRE_TENTATIVAS_S)
                continue
            total += n
            backup = None                    # um backup por sincronização basta
            if n == 0:
                return relatorio, total
            self.dormir(self.espera_verificacao)
            relatorio_conf, faltam = _aplicar_nfs(self, vendas, gravar=False, so_vazias=so_vazias)
            if faltam == 0:
                return relatorio_conf, total
            self.progresso(f"{faltam} NF(s) não ficaram gravadas (o robô salvou junto); "
                           f"gravando de novo ({tentativa}/{self.tentativas})...")
            total = max(0, total - faltam)   # serão contadas de novo na próxima volta
        raise RuntimeError("Não consegui gravar as NFs: o PEDIDOS.json mudou em todas as tentativas.")
