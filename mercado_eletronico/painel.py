"""Estado das cotações do ME no CotaFrete — regra pura, sem banco nem navegador.

O que o teste real de Salvar (23/09/2026) mostrou manda aqui: o ME NÃO marca
rascunho. Depois do Salvar a lista continua "Não Respondida". Então:

- "Salva no ME" é estado NOSSO — só existe porque o robô gravou e o banco
  lembrou. Nenhuma varredura da lista o apaga.
- "Enviada" vem do ME: `answerStatus` Parcialmente/Totalmente Respondida.
  Também conta a cotação que SUMIU de "Oportunidades a Responder" antes do
  prazo — alguém respondeu por fora. Sumiu DEPOIS do prazo sem resposta
  conhecida → "Vencida".
- Enviada e Recusada são finais: nenhuma varredura volta atrás.

Horários: tudo em hora de Brasília, sem fuso (naive), como o resto do banco.
O ME manda `dueDate` em UTC (00:00Z = 21:00 do dia anterior). Brasília não
tem horário de verão desde 2019, então o deslocamento é fixo em -3 h — e
evita depender de `tzdata`, que o Windows do servidor não traz.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

BRASILIA = timezone(timedelta(hours=-3))

RESPONDIDA = frozenset({"Parcialmente Respondida", "Totalmente Respondida"})
RECUSADA = "Recusada"

# Faltando menos que isto, a cotação ganha destaque na lista.
JANELA_URGENTE = timedelta(hours=24)


class Status(str, Enum):
    PENDENTE = "pendente"
    SALVANDO = "salvando"   # robô trabalhando agora
    SALVA = "salva"         # rascunho gravado no ME; falta um humano enviar
    ERRO = "erro"
    ENVIADA = "enviada"
    RECUSADA = "recusada"
    VENCIDA = "vencida"


ROTULO = {
    Status.PENDENTE: "Pendente",
    Status.SALVANDO: "Salvando no ME…",
    Status.SALVA: "Salva no ME",
    Status.ERRO: "Erro",
    Status.ENVIADA: "Enviada",
    Status.RECUSADA: "Recusada",
    Status.VENCIDA: "Vencida",
}

FINAIS = frozenset({Status.ENVIADA, Status.RECUSADA})
ABERTOS = frozenset({Status.PENDENTE, Status.SALVANDO, Status.SALVA, Status.ERRO})


def hora_de_brasilia(valor: datetime | str | None) -> datetime | None:
    """`dueDate` do ME (UTC, com ou sem Z) ou datetime → Brasília sem fuso.

    Datetime sem fuso é tomado como JÁ em Brasília (é o que a página de
    resposta mostra: "23/09/2026 21:00")."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    if valor.tzinfo is not None:
        valor = valor.astimezone(BRASILIA).replace(tzinfo=None)
    return valor


def status_apos_varredura(atual: Status, *, status_resposta: str | None,
                          na_lista: bool, data_limite: datetime | None,
                          agora: datetime) -> Status:
    """O status depois de olhar a lista do ME mais uma vez."""
    if status_resposta in RESPONDIDA:
        return Status.ENVIADA
    if status_resposta == RECUSADA:
        return Status.RECUSADA
    if atual in FINAIS:
        return atual
    if not na_lista:
        if data_limite is not None and agora > data_limite:
            return Status.VENCIDA
        return Status.ENVIADA
    if atual is Status.VENCIDA:  # voltou para a lista: prazo reaberto
        return Status.PENDENTE
    return atual


@dataclass(frozen=True)
class Prazo:
    texto: str      # "2 d 5 h", "3 h 10 min", "venceu"
    urgente: bool
    vencido: bool


def prazo(data_limite: datetime | None, agora: datetime) -> Prazo:
    if data_limite is None:
        return Prazo("—", False, False)
    falta = data_limite - agora
    if falta <= timedelta(0):
        return Prazo("venceu", True, True)
    minutos = int(falta.total_seconds() // 60)
    dias, resto = divmod(minutos, 24 * 60)
    horas, mins = divmod(resto, 60)
    if dias:
        texto = f"{dias} d {horas} h"
    elif horas:
        texto = f"{horas} h {mins:02d} min"
    else:
        texto = f"{mins} min"
    return Prazo(texto, falta < JANELA_URGENTE, False)


def alerta(status: Status, data_limite: datetime | None, agora: datetime) -> str:
    """A frase de destaque da linha, ou "". A mais importante: rascunho salvo
    que ninguém enviou, com o prazo acabando — é o jeito de perder a cotação
    achando que já respondeu."""
    p = prazo(data_limite, agora)
    if status not in ABERTOS or not p.urgente or p.vencido:
        return ""
    if status is Status.SALVA:
        return f"Salva no ME mas NÃO enviada — fecha em {p.texto}"
    if status is Status.ERRO:
        return f"Robô falhou — fecha em {p.texto}"
    return f"Fecha em {p.texto}"


def chave_material(descricao: str) -> str:
    """Chave para lembrar NCM/marca/origem entre cotações.

    Os itens da Samarco vêm como "000000000000263252 - BATERIA…": o código é
    o que identifica o material. Sem código, a descrição normalizada."""
    d = " ".join((descricao or "").split()).upper()
    cabeca, sep, _ = d.partition(" - ")
    if sep and cabeca.isdigit():
        return cabeca.lstrip("0") or cabeca
    return d
