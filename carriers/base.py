"""Contrato que toda transportadora implementa."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from core.models import CotacaoRequest, StatusCotacao

# O print de diagnóstico é enfeite: nunca vale gastar o timeout inteiro do
# adapter nele, ainda mais dentro de um `except` que já tem erro em mãos.
TIMEOUT_PRINT_ERRO_MS = 8_000


# Assinatura do elemento: posição, tamanho e texto. Se isso não muda entre
# duas leituras E não há overlay de bloqueio na frente, a página está pronta
# para ser fotografada. Devolve null enquanto não estiver.
JS_ASSINATURA = """sel => {
    // O PrimeFaces cobre a tela com .ui-blockui durante o AJAX. Medido na
    // Jadlog em 13/08/2026: o painel fica com texto e geometria FINAIS aos
    // 200ms, mas o bloqueio só sai aos ~700ms. Olhar só para o elemento dá
    // "estável" no meio do bloqueio, e o print sai da tela cinza, com o
    // spinner "Procurar..." no meio.
    const bloqueado = [...document.querySelectorAll(
        '.ui-blockui, .ui-widget-overlay, .blockUI')].some(e => {
            const b = e.getBoundingClientRect();
            return b.width > 0 && b.height > 0
                   && getComputedStyle(e).visibility !== 'hidden';
        });
    if (bloqueado) return null;

    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width),
            Math.round(r.height), el.innerText.trim()].join('|');
}"""


def esperar_estabilidade(page, seletor: str, tentativas: int = 12,
                         intervalo_ms: int = 250) -> bool:
    """Espera o elemento parar de se mexer. True se parou, False se desistiu.

    Ter o texto na tela não quer dizer que dá para fotografar. No simulador da
    Jadlog o PrimeFaces ainda anima e repinta o painel depois que o resultado
    aparece; um print tirado nessa janela sai com o conteúdo deslocado ou com o
    painel em branco — inclusive o print de tela inteira, sem recorte nenhum.

    Espera ATIVA em vez de `wait_for_timeout` fixo: os 700ms que estavam aqui
    às vezes bastavam e às vezes não, o que dava um print quebrado a cada tanto
    sem nenhum padrão. E quando a página já está parada, sai em 250ms.

    Não levanta em caso de desistência: o print vale mesmo assim, só não é
    confiável — quem chama decide o que fazer com o False.
    """
    anterior = None
    for _ in range(tentativas):
        atual = page.evaluate(JS_ASSINATURA, seletor)
        if atual is not None and atual == anterior:
            return True
        anterior = atual
        page.wait_for_timeout(intervalo_ms)
    return False


def print_seguro(page, destino: Path) -> list[str]:
    """Screenshot que nunca derruba a cotação. Evidência é bônus, não requisito.

    `page.screenshot(full_page=True)` trava em página longa/carregada, e o
    timeout dele é o do adapter — 45s. Dois estragos, ambos vistos em produção
    13/08/2026 na Jadlog:

    - dentro de um `except`, a exceção nova substitui a ORIGINAL e escapa do
      adapter: `cotar()` deixa de devolver ResultadoCotacao e derruba o lote;
    - no caminho feliz, mata uma cotação que já tinha dado certo — o valor já
      estava lido, só faltava guardar o print.

    Devolve a lista de evidências: vazia se não deu para printar. Nunca levanta.
    """
    for extra in ({"full_page": True}, {}):     # full page, senão o viewport
        try:
            page.screenshot(path=str(destino),
                            timeout=TIMEOUT_PRINT_ERRO_MS, **extra)
            return [str(destino)]
        except Exception:
            continue
    return []


class Modo(str, Enum):
    SINCRONO = "sincrono"                    # API devolve preço na resposta HTTP
    ASSINCRONO_RAPIDO = "assincrono_rapido"  # form -> e-mail automático em minutos
    ASSINCRONO_LENTO = "assincrono_lento"    # form -> vendedor humano, horas/dias


class Severidade(str, Enum):
    ERRO = "erro"
    AVISO = "aviso"


@dataclass
class ErroValidacao:
    campo: str
    mensagem: str
    severidade: Severidade = Severidade.ERRO


@dataclass
class ResultadoCotacao:
    transportadora: str
    status: StatusCotacao
    protocolo: str | None = None
    valor_frete: Decimal | None = None   # None é resposta VÁLIDA, não falha
    prazo_dias: int | None = None
    moeda: str = "BRL"
    raw_response: Any = None
    evidencias: list[str] = field(default_factory=list)
    # motivo_recusa é a transportadora dizendo não (rota fora de cobertura,
    # carga fora do perfil). Não é `erro`: não tem nada para consertar aqui.
    motivo_recusa: str | None = None
    erro: str | None = None
    enviado_em: datetime | None = None
    respondido_em: datetime | None = None


class CredencialRecusada(RuntimeError):
    """O site recebeu usuário e senha e disse não.

    Separada das outras falhas porque é a única que NÃO pode ser repetida:
    três tentativas por cotação, com a equipe cotando o dia inteiro, travam
    a conta da Ventura — e aí não é mais uma transportadora que falha, são
    todas. Quem conserta isso é uma pessoa, no .env.

    Só para credencial REJEITADA. Login que não chegou a ser enviado (campo
    vazio, página que não carregou) é erro comum e deve repetir.
    """


def erro_do_adapter(slug: str, exc: BaseException,
                    **extras) -> ResultadoCotacao:
    """Falha do adapter virada em resultado, já classificada para a
    retentativa saber o que fazer com ela.

    `ERRO` é o "não sabemos" que se repete; `INTERVENCAO_NECESSARIA` é o que
    já se sabe que repetir não conserta. Ver `core.retentativa.vale_repetir`.
    """
    status = (StatusCotacao.INTERVENCAO_NECESSARIA
              if isinstance(exc, CredencialRecusada) else StatusCotacao.ERRO)
    return ResultadoCotacao(slug, status,
                            erro=f"{type(exc).__name__}: {exc}", **extras)


def recusa_por_validacao(slug: str,
                         erros: list[ErroValidacao]) -> ResultadoCotacao:
    """Carga que a transportadora não aceita é RECUSA, não erro.

    Existe uma vez só, e não copiada em cada adapter, porque é a decisão de
    que depende a retentativa: `core/retentativa.py` repete `ERRO` e nunca
    repete `RECUSADO`. Um adapter novo que devolvesse `ERRO` aqui ganharia
    três tentativas para chegar na mesma recusa — e ainda faria o cartão
    dizer ao vendedor que o sistema quebrou, quando o site só disse não.

    O texto vai em `motivo_recusa` pelo mesmo motivo: ele é escrito para o
    vendedor ler ("divida em volumes menores"), e `erro` é para o que
    ninguém entendeu.
    """
    return ResultadoCotacao(
        slug, StatusCotacao.RECUSADO,
        motivo_recusa="; ".join(f"{e.campo}: {e.mensagem}" for e in erros))


@dataclass
class CampoSpec:
    nome: str
    obrigatorio: bool
    tipo: str
    condicao: str | None = None


@runtime_checkable
class CarrierAdapter(Protocol):
    slug: str
    nome: str
    modo: Modo
    ativo: bool
    fator_cubagem: Decimal
    sla_esperado_min: int | None

    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]: ...

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]: ...

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        """Função PURA: modelo central -> campos da transportadora.
        É aqui que mora o risco de mapeamento, e é isso que os testes cobrem."""
        ...

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao: ...
