"""Della Volpe — o preço que chega por e-mail, de volta na tela.

O formulário deles não devolve preço: devolve "Agradecemos a sua mensagem" e,
minutos depois, um e-mail com a proposta em PDF. Este módulo lê esse e-mail
na caixa do suporte, acha a cotação pelo carimbo "(cot. N)" que o Cotafrete
pôs no nome, e grava preço, prazo, validade e o PDF com `salvar_resultado` —
o mesmo caminho de toda automática.

Três regras, e todas existem porque a caixa é do SUPORTE, não do robô:

1. **Filtra por remetente** (`FROM dellavolpe.com.br`) direto na busca do
   servidor. O robô nunca baixa e-mail de cliente, fornecedor ou banco.
2. **Nunca apaga nem move.** Não existe EXPUNGE, MOVE, COPY nem \\Deleted
   neste arquivo — e há teste conferindo isso.
3. **Só marca como lido depois de gravar.** Um e-mail que o robô não soube
   ler (sem carimbo, rota que não bate) continua não lido, para uma pessoa
   ver. E o "já processei" mora no banco, não na bandeira de lido: gente
   abre e-mail no Outlook antes do robô passar.

Rodando à mão, para conferir sem mexer em nada:

    python -m carriers.dellavolpe.ingestor            # só lê e mostra
    python -m carriers.dellavolpe.ingestor --gravar   # grava e marca lido
    python -m carriers.dellavolpe.ingestor --pdf proposta.pdf   # sem rede

O padrão é SOMENTE LEITURA: abre a pasta em modo readonly e baixa com
BODY.PEEK, que não acende a bandeira de lido.
"""

from __future__ import annotations

import argparse
import email
import hashlib
import imaplib
import io
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Callable

from carriers.dellavolpe import caixa as config
from carriers.dellavolpe import proposta_ia
from carriers.dellavolpe.proposta import Proposta, ler_proposta
from core.models import StatusCotacao

SLUG = "dellavolpe"

# Dentro de teste_real/, como o print de toda transportadora: entra no backup
# (core/backup.py) e na faxina de 30 dias (core/evidencias.py). A proposta
# vale 7 dias; o preço, o prazo e o número dela ficam no banco para sempre.
PASTA_PROPOSTAS = Path("teste_real") / SLUG

# IMAP exige o mês em inglês no SINCE, qualquer que seja o idioma da máquina.
# strftime("%b") num Windows em português escreveria "set" e a busca voltaria
# vazia, em silêncio.
_MESES_IMAP = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Depois de uma volta que falhou (senha errada, servidor fora), a próxima
# espera o DOBRO, até este teto. Tentar login errado a cada minuto é o jeito
# mais rápido de bloquear a conta do suporte.
ESPERA_MAXIMA_APOS_FALHA_S = 30 * 60


# --------------------------------------------------------------- mensagem
@dataclass
class Anexo:
    nome: str
    dados: bytes


@dataclass
class Mensagem:
    message_id: str
    remetente: str
    assunto: str
    data: datetime | None
    pdfs: list[Anexo] = field(default_factory=list)


@dataclass
class Desfecho:
    """O que aconteceu com UM e-mail. `desfecho` é o que vai para o banco."""
    message_id: str
    desfecho: str
    cotacao_id: int | None = None
    detalhe: str = ""
    proposta: Proposta | None = None
    assunto: str = ""


def data_imap(dia: date) -> str:
    return f"{dia.day:02d}-{_MESES_IMAP[dia.month - 1]}-{dia.year}"


def _message_id(msg: Message, bruto: bytes) -> str:
    """O Message-ID do cabeçalho, ou um hash do e-mail inteiro.

    O hash é para o e-mail sem Message-ID (raro, mas o RFC deixa): sem uma
    chave estável ele seria relido a cada minuto, para sempre."""
    mid = (msg.get("Message-ID") or "").strip()
    return mid or "sha1:" + hashlib.sha1(bruto).hexdigest()


def _cabecalho(valor) -> str:
    """Cabeçalho de e-mail em texto: "=?utf-8?b?Q290YcOnw6Nv?=" → "Cotação".
    Cru, o assunto codificado ia assim para o registro do desfecho `sem_pdf`.
    Cabeçalho mal formado fica como veio — melhor feio do que perdido."""
    try:
        return str(make_header(decode_header(str(valor or ""))))
    except Exception:
        return str(valor or "")


def ler_mensagem(bruto: bytes) -> Mensagem:
    msg = email.message_from_bytes(bruto)
    try:
        data = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    except (TypeError, ValueError):
        data = None
    pdfs: list[Anexo] = []
    for parte in msg.walk():
        if parte.is_multipart():
            continue
        nome = parte.get_filename() or ""
        tipo = parte.get_content_type()
        if tipo == "application/pdf" or nome.lower().endswith(".pdf"):
            dados = parte.get_payload(decode=True) or b""
            if dados:
                pdfs.append(Anexo(nome or "proposta.pdf", dados))
    return Mensagem(
        message_id=_message_id(msg, bruto),
        remetente=parseaddr(msg.get("From", ""))[1].lower(),
        assunto=_cabecalho(msg.get("Subject", "")),
        data=data,
        pdfs=pdfs,
    )


def do_remetente(endereco: str, dominio: str) -> bool:
    """`x@dellavolpe.com.br` ou `x@algo.dellavolpe.com.br` — e nada mais.

    Terminar com o domínio não basta: `x@naodellavolpe.com.br` também
    termina. A busca do servidor já filtra por FROM, mas o FROM do IMAP é
    busca por TRECHO — isto aqui é a conferência exata."""
    endereco = (endereco or "").lower().strip()
    dominio = dominio.lower().strip().lstrip("@")
    return endereco.endswith("@" + dominio) or endereco.endswith("." + dominio)


def texto_do_pdf(dados: bytes) -> str:
    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(dados))
    return "\n".join((pagina.extract_text() or "") for pagina in leitor.pages)


# ------------------------------------------------------------ a decisão
def decidir(p: Proposta, carga: dict | None) -> tuple[str, str]:
    """Grava ou não grava — e por quê. FUNÇÃO PURA.

    A ordem é a do custo do erro. Um preço na cotação ERRADA é o pior que
    pode acontecer aqui: o vendedor fecha um frete com número de outra carga.
    Por isso qualquer dúvida vira "não grava", e o e-mail fica não lido para
    uma pessoa olhar."""
    if p.valor is None:
        return "sem_valor", "o PDF não traz 'VALOR TOTAL DO FRETE'"
    if p.cotacao_id is None:
        return "sem_carimbo", (f"o A/C do PDF não tem '(cot. N)': "
                               f"{p.destinatario or 'vazio'}")
    if carga is None:
        return "sem_cotacao", f"não existe cotação #{p.cotacao_id}"
    for lado, do_pdf, da_cotacao in (
            ("origem", p.uf_origem, carga.get("uf_origem")),
            ("destino", p.uf_destino, carga.get("uf_destino"))):
        # Só compara quando os DOIS lados sabem a UF. PDF sem a linha de
        # origem não é motivo para jogar fora um preço com carimbo certo.
        if do_pdf and da_cotacao and do_pdf.upper() != str(da_cotacao).upper():
            return "rota_diferente", (
                f"{lado} do PDF é {do_pdf}, a cotação #{p.cotacao_id} é "
                f"{da_cotacao}")
    return "gravado", f"R$ {p.valor} na cotação #{p.cotacao_id}"


def _melhor_proposta(pdfs: list[Anexo]) -> tuple[Proposta, Anexo | None, str]:
    """O primeiro PDF que PARECE proposta (tem valor ou carimbo).

    O e-mail pode vir com mais de um anexo — assinatura, folder, termo. Ler
    só o primeiro faria uma proposta válida virar "sem_valor" por causa da
    ordem dos anexos."""
    melhor, dono, erros = Proposta(), None, []
    lidos: list[tuple[Proposta, Anexo, str]] = []
    for anexo in pdfs:
        try:
            texto = texto_do_pdf(anexo.dados)
            p = ler_proposta(texto)
        except Exception as exc:              # PDF quebrado, cifrado, etc.
            erros.append(f"{anexo.nome}: {type(exc).__name__}")
            continue
        if p.valor is not None and p.cotacao_id is not None:
            return p, anexo, ""
        lidos.append((p, anexo, texto))
    # Plano B (proposta_ia): o regex não achou valor E carimbo juntos em
    # nenhum PDF. A IA lê o que faltou, e o que ela disser só fica se o PDF
    # provar. Primeiro o PDF que o regex já leu em parte, depois os outros.
    # Com a IA desligada ou fora do ar, `completar` devolve `p` como veio e
    # isto se comporta exatamente como antes.
    lidos.sort(key=lambda t: t[0].valor is None and t[0].cotacao_id is None)
    for p, anexo, texto in lidos:
        p = proposta_ia.completar(p, texto)
        if p.valor is not None or p.cotacao_id is not None:
            return p, anexo, ""
        if dono is None:
            melhor, dono = p, anexo
    return melhor, dono, "; ".join(erros)


def _guardar_pdf(anexo: Anexo, p: Proposta, pasta: Path) -> Path:
    numero = re.sub(r"[^0-9A-Za-z-]", "-", p.numero or "sem-numero")
    destino = (pasta / f"{datetime.now():%Y%m%d-%H%M%S}-cot{p.cotacao_id}"
               / f"proposta-{numero}.pdf")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(anexo.dados)
    return destino


def _hora_local(data: datetime | None) -> str | None:
    """O `Date:` do e-mail em hora local, sem fuso — como o resto do banco
    grava (`datetime.now()`). Misturar os dois formatos faria "respondeu em"
    sair negativo ou três horas errado."""
    if data is None:
        return None
    if data.tzinfo is not None:
        data = data.astimezone().replace(tzinfo=None)
    return data.isoformat(timespec="seconds")


def processar(bruto: bytes, banco, *, gravar: bool,
              dominio: str = config.REMETENTE_PADRAO,
              pasta: Path | None = None) -> Desfecho:
    """Um e-mail, do começo ao fim. Com `gravar=False` não escreve NADA —
    nem no banco, nem no disco."""
    pasta = PASTA_PROPOSTAS if pasta is None else pasta
    msg = ler_mensagem(bruto)

    def fim(desfecho: str, detalhe: str = "", p: Proposta | None = None,
            registrar: bool = True) -> Desfecho:
        cid = p.cotacao_id if p else None
        if gravar and registrar:
            banco.registrar_email(msg.message_id, SLUG, desfecho=desfecho,
                                  cotacao_id=cid, detalhe=detalhe)
        return Desfecho(msg.message_id, desfecho, cid, detalhe, p,
                        msg.assunto)

    if banco.email_ja_processado(msg.message_id):
        return fim("ja_processado", registrar=False)
    if not do_remetente(msg.remetente, dominio):
        # Não registra: não é da Della Volpe, e não é da nossa conta.
        return fim("outro_remetente", msg.remetente, registrar=False)
    if not msg.pdfs:
        return fim("sem_pdf", msg.assunto)

    p, anexo, erros = _melhor_proposta(msg.pdfs)
    if anexo is None:
        # Nenhum PDF abriu. Pode ser passageiro (download cortado): não
        # registra, e a próxima volta tenta de novo.
        return fim("pdf_ilegivel", erros, registrar=False)

    carga = (banco.carga_da_cotacao(p.cotacao_id)
             if p.cotacao_id is not None else None)
    desfecho, detalhe = decidir(p, carga)
    if p.lido_por:   # fica no registro do e-mail e no resumo do /adm
        detalhe = f"{detalhe} — lido pela {p.lido_por}"
    if desfecho != "gravado" or not gravar:
        return fim(desfecho, detalhe, p)

    caminho = _guardar_pdf(anexo, p, pasta)
    banco.salvar_resultado(
        p.cotacao_id, SLUG, status=StatusCotacao.COTADO.value, valor=p.valor,
        protocolo=p.numero,
        prazo=str(p.prazo_dias) if p.prazo_dias is not None else None,
        validade=p.validade, evidencia=str(caminho),
        respondido_em=_hora_local(msg.data))
    return fim(desfecho, detalhe, p)


# ------------------------------------------------------------------- IMAP
def conectar(cx: config.Caixa) -> imaplib.IMAP4:
    imap = imaplib.IMAP4_SSL(cx.host, cx.porta, timeout=60)
    imap.login(cx.usuario, cx.senha)
    return imap


def _ok(resposta) -> list:
    tipo, dados = resposta
    if tipo != "OK":
        raise imaplib.IMAP4.error(f"servidor respondeu {tipo}: {dados!r}")
    return dados


def _corpo(dados: list) -> bytes:
    """O pedaço de bytes dentro da resposta de um FETCH (vem numa tupla)."""
    for item in dados:
        if isinstance(item, tuple) and len(item) >= 2:
            return item[1]
    return b""


def varrer(cx: config.Caixa, banco, *, gravar: bool,
           conectar_fn: Callable[[config.Caixa], imaplib.IMAP4] | None = None,
           pasta: Path | None = None,
           hoje: date | None = None) -> list[Desfecho]:
    """Uma volta na caixa. Levanta se não conseguir nem entrar nela — quem
    chama decide quanto esperar para tentar de novo.

    `conectar_fn` e `pasta` são resolvidos NA CHAMADA, e não na definição:
    default de parâmetro congela o valor do import, e trocar a conexão (num
    teste, num servidor de mentira) passaria reto pela thread."""
    pasta = PASTA_PROPOSTAS if pasta is None else pasta
    imap = (conectar_fn or conectar)(cx)
    desfechos: list[Desfecho] = []
    try:
        # readonly quando não grava: o servidor nem aceitaria marcar lido.
        _ok(imap.select(f'"{cx.pasta}"', readonly=not gravar))
        desde = data_imap((hoje or date.today()) - timedelta(days=cx.dias))
        uids = _ok(imap.uid("SEARCH", None, "FROM", f'"{cx.remetente}"',
                            "SINCE", desde))
        for uid in (uids[0] or b"").split():
            try:
                # Primeiro só o Message-ID: e-mail já processado não precisa
                # baixar o PDF de novo a cada minuto.
                cab = _corpo(_ok(imap.uid(
                    "FETCH", uid,
                    "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")))
                mid = (email.message_from_bytes(cab).get("Message-ID")
                       or "").strip()
                if mid and banco.email_ja_processado(mid):
                    continue
                # PEEK: baixar não acende a bandeira de lido.
                bruto = _corpo(_ok(imap.uid("FETCH", uid, "(BODY.PEEK[])")))
                d = processar(bruto, banco, gravar=gravar,
                              dominio=cx.remetente, pasta=pasta)
            except Exception as exc:
                # Um e-mail que quebra não pode derrubar os outros.
                desfechos.append(Desfecho(uid.decode(), "falhou",
                                          detalhe=f"{type(exc).__name__}: {exc}"))
                continue
            if gravar and d.desfecho == "gravado":
                _ok(imap.uid("STORE", uid, "+FLAGS", r"(\Seen)"))
            desfechos.append(d)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return desfechos


# ------------------------------------------------------- rodando sozinho
class Vigia(threading.Thread):
    """A thread que o servidor sobe junto com ele (web/app.py).

    Daemon: fechar o servidor não espera a volta terminar. O pior que isso
    causa é uma proposta ser lida um minuto depois, na próxima subida."""

    def __init__(self, cx: config.Caixa, banco,
                 log: Callable[[str], None] = print) -> None:
        super().__init__(name="ingestor-dellavolpe", daemon=True)
        self.cx = cx
        self.banco = banco
        self.log = log
        self.parar = threading.Event()
        # Para quem quiser mostrar na tela: quando foi a última volta, e se
        # ela deu certo.
        self.ultima_volta: datetime | None = None
        self.ultimo_erro: str | None = None

    def volta(self) -> None:
        for d in varrer(self.cx, self.banco, gravar=True):
            if d.desfecho == "gravado":
                self.log(f"[ingestor] Della Volpe: {d.detalhe}")
            elif d.desfecho not in ("ja_processado",):
                self.log(f"[ingestor] Della Volpe: e-mail não gravado "
                         f"({d.desfecho}) — {d.detalhe}")

    def run(self) -> None:
        espera = self.cx.intervalo_s
        while not self.parar.is_set():
            try:
                self.volta()
                self.ultimo_erro = None
                espera = self.cx.intervalo_s
            except Exception as exc:
                self.ultimo_erro = f"{type(exc).__name__}: {exc}"
                espera = min(espera * 2, ESPERA_MAXIMA_APOS_FALHA_S)
                quando = (f"{espera // 60} min" if espera >= 120
                          else f"{espera} s")
                self.log(f"[ingestor] Della Volpe: a caixa não abriu "
                         f"({self.ultimo_erro}). Tento de novo em {quando}.")
            self.ultima_volta = datetime.now()
            self.parar.wait(espera)


def iniciar(banco, ambiente=None, log: Callable[[str], None] = print
            ) -> Vigia | None:
    """Sobe a vigia se o .env descreve a caixa. None se não descreve."""
    cx = config.caixa(ambiente)
    if cx is None:
        return None
    vigia = Vigia(cx, banco, log)
    vigia.start()
    return vigia


# -------------------------------------------------------------- à mão
def _mostrar(d: Desfecho) -> str:
    p = d.proposta
    linha = f"  [{d.desfecho}] {d.assunto or d.message_id}"
    if p and p.valor is not None:
        linha += (f"\n      proposta {p.numero}  R$ {p.valor}  "
                  f"prazo {p.prazo_dias} dias  validade {p.validade}  "
                  f"{p.origem} -> {p.destino}  A/C {p.destinatario}")
    if d.detalhe:
        linha += f"\n      {d.detalhe}"
    return linha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m carriers.dellavolpe.ingestor",
        description="Lê as propostas da Della Volpe na caixa do suporte.")
    parser.add_argument("--gravar", action="store_true",
                        help="grava no banco e marca como lido (padrão: só lê)")
    parser.add_argument("--pdf", type=Path,
                        help="só lê um PDF do disco e mostra o que entendeu")
    args = parser.parse_args(argv)

    if args.pdf:
        p = ler_proposta(texto_do_pdf(args.pdf.read_bytes()))
        for campo, valor in p._asdict().items():
            print(f"  {campo:14} {valor}")
        return 0 if p.valor is not None else 1

    from dotenv import load_dotenv

    from core.banco import Banco

    load_dotenv(override=False)
    cx = config.caixa()
    if cx is None:
        print("Caixa não configurada. No .env: DV_IMAP_HOST, DV_IMAP_USUARIO,"
              " DV_IMAP_SENHA (e DV_EMAIL_RESPOSTA se o usuário não for um"
              " e-mail).")
        return 2
    modo = "GRAVANDO" if args.gravar else "SOMENTE LEITURA"
    print(f"{modo} — {cx.usuario}@{cx.host}, pasta {cx.pasta}, "
          f"de {cx.remetente}, últimos {cx.dias} dias")
    desfechos = varrer(cx, Banco(), gravar=args.gravar)
    if not desfechos:
        print("  nenhum e-mail da Della Volpe no período.")
    for d in desfechos:
        print(_mostrar(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
