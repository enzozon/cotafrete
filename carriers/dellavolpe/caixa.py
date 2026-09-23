"""Della Volpe — as três chaves do .env, lidas num lugar só.

Três perguntas diferentes, que o resto do sistema faz em lugares diferentes:

1. **Para onde a Della Volpe responde?** Para a caixa do suporte, quando o
   ingestor sabe ler essa caixa; para o e-mail do vendedor, quando não sabe.
   As duas coisas andam JUNTAS de propósito: mandar a proposta para uma caixa
   que ninguém lê — nem o robô, porque faltou a senha — é o pior dos mundos.
   A cotação sai, a resposta chega, e o preço fica parado num lugar onde
   ninguém olha.

2. **O ingestor roda?** Só com endereço, usuário e senha do IMAP no .env.

3. **Ela cota sozinha?** Só com `DV_AUTOMATICA_DESDE` E a trava de envio real
   liberada. A data não é enfeite: é a mesma de `AUTOMATICA_DESDE` em
   web/app.py, que impede a varredura de cotações interrompidas de carimbar
   o histórico inteiro — as 118 linhas fantasma da Braspress (03/09/2026).
   Escrita à mão no .env no dia em que for ligada, e não no código: uma data
   no código fica errada entre o commit e o dia em que alguém faz o `git pull`
   no servidor, e toda cotação desse intervalo viraria "o sistema foi fechado
   durante a cotação" para a Della Volpe.

Nada aqui abre rede nem navegador: recebe o dicionário do ambiente e devolve
decisão. É o que deixa os testes perguntarem "e se o .env tivesse isto?" sem
mexer no .env de ninguém.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

# O domínio de quem manda a proposta. Filtrar por ele é o que impede o
# ingestor de varrer a caixa do suporte inteira — que tem e-mail de cliente,
# de fornecedor, de banco.
REMETENTE_PADRAO = "dellavolpe.com.br"

# Uma consulta por minuto. A proposta chega em 2 a 5 minutos (medido em
# 25-26/08/2026), então um minuto de atraso a mais não muda nada para quem
# está esperando — e é pouco o bastante para o servidor de e-mail nem notar.
INTERVALO_PADRAO_S = 60

# Quantos dias para trás a busca olha. Não é "só o que não foi lido": a caixa
# do suporte é lida por GENTE, e um e-mail aberto no Outlook antes do robô
# passar ficaria pulado para sempre. O controle de "já processei" mora no
# banco (tabela email_processado), não na bandeira de lido.
DIAS_PADRAO = 3


@dataclass(frozen=True)
class Caixa:
    host: str
    usuario: str
    senha: str
    porta: int = 993
    pasta: str = "INBOX"
    remetente: str = REMETENTE_PADRAO
    intervalo_s: int = INTERVALO_PADRAO_S
    dias: int = DIAS_PADRAO
    # O endereço que vai no campo "E-mail" do formulário. Quase sempre é o
    # próprio usuário do IMAP; existe separado para o caso de o login ser
    # um apelido ("suporte") e não o endereço inteiro.
    endereco: str = ""

    @property
    def responder_para(self) -> str:
        return self.endereco or self.usuario


def _ambiente(ambiente: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if ambiente is None else ambiente


def _inteiro(texto: str | None, padrao: int) -> int:
    try:
        valor = int(str(texto).strip())
    except (TypeError, ValueError):
        return padrao
    return valor if valor > 0 else padrao


def caixa(ambiente: Mapping[str, str] | None = None) -> Caixa | None:
    """A caixa do suporte, ou None se o .env não a descreve inteira.

    Parcial conta como ausente: com host e sem senha o ingestor não loga, e
    se mesmo assim a resposta fosse para o suporte, ela ficaria sem ninguém."""
    amb = _ambiente(ambiente)
    host = (amb.get("DV_IMAP_HOST") or "").strip()
    usuario = (amb.get("DV_IMAP_USUARIO") or "").strip()
    senha = amb.get("DV_IMAP_SENHA") or ""
    if not (host and usuario and senha):
        return None
    endereco = (amb.get("DV_EMAIL_RESPOSTA") or "").strip()
    if not endereco and "@" not in usuario:
        # Login sem arroba ("suporte") não é endereço de e-mail: pôr isso no
        # formulário faria o site recusar o campo. Sem um endereço de
        # verdade, a caixa não serve de destino.
        return None
    return Caixa(
        host=host, usuario=usuario, senha=senha,
        porta=_inteiro(amb.get("DV_IMAP_PORTA"), 993),
        pasta=(amb.get("DV_IMAP_PASTA") or "INBOX").strip() or "INBOX",
        remetente=(amb.get("DV_IMAP_REMETENTE") or REMETENTE_PADRAO).strip()
        or REMETENTE_PADRAO,
        intervalo_s=_inteiro(amb.get("DV_IMAP_INTERVALO_S"),
                             INTERVALO_PADRAO_S),
        dias=_inteiro(amb.get("DV_IMAP_DIAS"), DIAS_PADRAO),
        endereco=endereco,
    )


def email_de_resposta(ambiente: Mapping[str, str] | None = None) -> str | None:
    """O e-mail que vai no formulário, ou None para usar o do vendedor."""
    cx = caixa(ambiente)
    return cx.responder_para if cx else None


def automatica_desde(ambiente: Mapping[str, str] | None = None) -> str | None:
    """A data de `DV_AUTOMATICA_DESDE`, normalizada para ISO, ou None.

    Data que não parseia vira None — e a Della Volpe continua assistida. Uma
    data errada aqui é exatamente o que gera linha fantasma, então na dúvida
    ela não liga."""
    bruto = (_ambiente(ambiente).get("DV_AUTOMATICA_DESDE") or "").strip()
    if not bruto:
        return None
    try:
        return datetime.fromisoformat(bruto).isoformat(timespec="seconds")
    except ValueError:
        return None


def envio_autorizado(ambiente: Mapping[str, str] | None = None) -> bool:
    return _ambiente(ambiente).get("DV_ENVIO_REAL_AUTORIZADO") == "sim"


def automatica(ambiente: Mapping[str, str] | None = None) -> bool:
    """Ela entra em AUTOMATICAS?

    As duas chaves, e não uma: sem a trava liberada o adapter recusa todo
    envio, e cada cotação viraria um cartão vermelho com texto de
    programador."""
    return (automatica_desde(ambiente) is not None
            and envio_autorizado(ambiente))


def o_que_falta(ambiente: Mapping[str, str] | None = None) -> list[str]:
    """Para o aviso da subida do servidor: o que o .env ainda não diz.

    Vazio quando não há nada a avisar — inclusive quando ninguém tentou
    ligar a automática, que é o estado normal e não merece barulho."""
    amb = _ambiente(ambiente)
    faltas: list[str] = []
    tentou = bool((amb.get("DV_AUTOMATICA_DESDE") or "").strip())
    if tentou and automatica_desde(amb) is None:
        faltas.append("DV_AUTOMATICA_DESDE não é uma data (use "
                      "2026-09-23T09:00:00)")
    if tentou and not envio_autorizado(amb):
        faltas.append("DV_ENVIO_REAL_AUTORIZADO=sim")
    tem_imap = any((amb.get(k) or "").strip() for k in
                   ("DV_IMAP_HOST", "DV_IMAP_USUARIO", "DV_IMAP_SENHA"))
    if tem_imap and caixa(amb) is None:
        faltas.append("DV_IMAP_HOST, DV_IMAP_USUARIO e DV_IMAP_SENHA juntos "
                      "(e DV_EMAIL_RESPOSTA se o usuário não for um e-mail)")
    return faltas
