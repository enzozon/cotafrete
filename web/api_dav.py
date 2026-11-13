"""API do DAV para o Maestro (o gerenciador.py chama; o vendedor não abre isto).

O vendedor manda a PLANILHA-BASE v3 no Maestro; o gerenciador repassa aqui,
pergunta pelo id de tempos em tempos (polling) e, com o DAV pronto, baixa o
PDF e responde a cotação do Coupa/Vale. O Cotafrete nunca chama o Maestro.

Rotas (todas exigem `Authorization: Bearer <DAV_API_TOKEN>`):

    POST /api/dav              planilha (arquivo), vendedor, cotacao
    GET  /api/dav/{id}         estado, número, avisos, erros e NCM de cada item
    GET  /api/dav/{id}/pdf     o PDF do DAV pronto

É o MESMO caminho da tela /dav, sem o clique em "Gerar": conferência
automática; com erros para, com ok/avisos (ou sem HSE para conferir, igual
à tela) segue para a fila do Gerar. A trava contra planilha repetida (hash)
também vale: reenviar a mesma planilha devolve o DAV que já existe.

Estado `incerto` nunca é refeito sozinho: quem decide é o vendedor/admin,
depois de conferir no HSE (gerar em dobro em produção é pior que esperar).

Dono no banco: `maestro:<vendedor>` — a trava do hash fica por vendedor e o
/adm/dav mostra de onde veio. A coluna `api_cotacao` marca a linha da API.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from orcamento.fila import no_banco
from orcamento.planilha import ErroPlanilha, ler_planilha
from orcamento.processador import Conferencia, _sem_segredo

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dav", include_in_schema=False)

# Injetados por web/app.py (mesmo banco e mesmas filas da tela /dav).
banco = None
FILA = None
FILA_CONFERENCIA = None
FILA_DIAGNOSTICO = None

MAX_BYTES = 5 * 1024 * 1024
PREFIXO = "maestro:"
SIMULADO = ("O Cotafrete está em modo simulação (DAV_DRY_RUN=1): nenhum DAV foi salvo no HSE. "
            "Avise o Enzo.")
INCERTO = "Confira no HSE se o DAV foi salvo antes de gerar de novo."
_CAMPO = re.compile(r"^[\w .@/-]{1,60}$")

# Nº do item → NCM, lido do relatório do robô (orcamento/relatorio.py e
# processador._completar). "CADASTROU" é a geração de verdade; "cadastraria" a conferência.
_NCM_NOVO = re.compile(r"^Item (\d+): (?:CADASTROU produto novo \S+|\[DRY_RUN\] cadastraria produto novo)"
                       r" - .*? \| NCM (\d{8}) \|", re.M)
_NCM_IA = re.compile(r"^Item (\d+): NCM sugerido por IA: (\d{8})", re.M)
_EXISTENTE = re.compile(r"^Item (\d+): usou produto existente (\S+) - ", re.M)


# ------------------------------------------------------------------ token
def _token_configurado() -> str:
    return (os.environ.get("DAV_API_TOKEN") or "").strip()


def _conferir_token(authorization: str | None) -> None:
    esperado = _token_configurado()
    if not esperado:
        raise HTTPException(503, "API do DAV desligada: falta DAV_API_TOKEN no .env do Cotafrete.")
    recebido = (authorization or "").strip()
    if recebido.lower().startswith("bearer "):
        recebido = recebido[7:].strip()
    # .encode(): compare_digest com str não-ASCII levanta TypeError (ver web/adm.py).
    if not recebido or not hmac.compare_digest(recebido.encode("utf-8"), esperado.encode("utf-8")):
        raise HTTPException(401, "Token inválido.")


def _da_api(dav_id: int) -> dict:
    """Só as linhas que a API criou: o token não abre DAV da tela /dav."""
    d = no_banco(banco.dav, dav_id, None)
    if d is None or not d.get("api_cotacao") or not str(d.get("usuario", "")).startswith(PREFIXO):
        raise HTTPException(404, "DAV não encontrado.")
    return d


# ------------------------------------------------------------------ envio
@router.post("")
def receber(planilha: UploadFile = File(...), vendedor: str = Form(...), cotacao: str = Form(...),
            authorization: str | None = Header(None)):
    _conferir_token(authorization)
    vendedor, cotacao = vendedor.strip(), cotacao.strip()
    if not _CAMPO.match(vendedor) or not _CAMPO.match(cotacao):
        raise HTTPException(400, "vendedor e cotacao são obrigatórios (até 60 letras, números, . _ - / @).")
    usuario = PREFIXO + vendedor
    nome = Path(planilha.filename or "planilha.xlsx").name
    if not nome.lower().endswith(".xlsx"):
        return _recusar(usuario, nome, cotacao, ["Envie um arquivo .xlsx (a PLANILHA-BASE v3)."])
    dados = planilha.file.read(MAX_BYTES + 1)
    if len(dados) > MAX_BYTES:
        return _recusar(usuario, nome, cotacao, ["O arquivo passa de 5 MB."])
    hash_ = hashlib.sha256(dados).hexdigest()
    pasta = FILA.pasta / "entrada"
    pasta.mkdir(parents=True, exist_ok=True)
    temp = pasta / f"{uuid.uuid4().hex}.xlsx"
    temp.write_bytes(dados)
    try:
        try:
            o = ler_planilha(temp)
        except ErroPlanilha as exc:
            return _recusar(usuario, nome, cotacao, list(exc.erros), arquivo=temp)
        except Exception:  # noqa: BLE001 — arquivo que nem abre
            return _recusar(usuario, nome, cotacao,
                            ["Não consegui abrir o arquivo. É a PLANILHA-BASE v3 em .xlsx?"], arquivo=temp)
        from web.dav_ui import _TRAVA   # a mesma trava da tela: o hash não passa duas vezes
        with _TRAVA:
            antigo = no_banco(banco.dav_ja_gerado, usuario, hash_)
            if antigo:
                if not antigo.get("api_cotacao"):   # antigo de antes da coluna: passa a ser da API
                    no_banco(banco.dav_atualizar, antigo["id"], api_cotacao=cotacao)
                corpo = situacao(no_banco(banco.dav, antigo["id"], None))
                return JSONResponse({**corpo, "ja_existia": True}, status_code=200)
            dav_id = no_banco(banco.dav_criar, usuario, nome, hash_, o.cliente, conferencia="conferindo")
            no_banco(banco.dav_atualizar, dav_id, api_cotacao=cotacao)
            temp.replace(FILA.planilha(dav_id))
        FILA_CONFERENCIA.enfileirar(dav_id)
        log.info("API do DAV: %s recebido (cotação %s, %s)", dav_id, cotacao, usuario)
        return JSONResponse({**situacao(no_banco(banco.dav, dav_id, None)), "ja_existia": False},
                            status_code=201)
    finally:
        temp.unlink(missing_ok=True)


def _recusar(usuario: str, nome: str, cotacao: str, motivos: list[str],
             arquivo: Path | None = None) -> JSONResponse:
    """Planilha que nem chega à conferência: mesmo registro da tela (rejeitado)."""
    dav_id = no_banco(banco.dav_rejeitar, usuario, nome, motivos)
    no_banco(banco.dav_atualizar, dav_id, api_cotacao=cotacao)
    if arquivo is not None:   # o ADM abre o Excel recusado
        try:
            arquivo.replace(FILA.planilha(dav_id))
        except OSError as exc:
            log.error("API do DAV %s: não guardei a planilha recusada: %s", dav_id, exc)
    if FILA_DIAGNOSTICO is not None:
        try:
            FILA_DIAGNOSTICO.enfileirar(dav_id)
        except Exception as exc:  # noqa: BLE001 — o diagnóstico nunca atrapalha a recusa
            log.error("API do DAV %s: não enfileirei o diagnóstico: %s", dav_id, exc)
    return JSONResponse({**situacao(no_banco(banco.dav, dav_id, None)), "ja_existia": False},
                        status_code=422)


# ------------------------------------------------------------------ consulta
@router.get("/{dav_id}")
def consultar(dav_id: int, authorization: str | None = Header(None)):
    _conferir_token(authorization)
    return situacao(_da_api(dav_id))


@router.get("/{dav_id}/pdf")
def baixar_pdf(dav_id: int, authorization: str | None = Header(None)):
    _conferir_token(authorization)
    d = _da_api(dav_id)
    if d["estado"] != "pronto" or not d.get("pdf"):
        raise HTTPException(409, "O DAV ainda não tem PDF.")
    pdf = Path(d["pdf"])
    base = (FILA.pasta / "pdf").resolve()
    try:
        dentro = pdf.resolve().is_relative_to(base)
    except OSError:
        dentro = False
    if not dentro or not pdf.is_file():
        raise HTTPException(404, "PDF não encontrado no servidor.")
    return FileResponse(pdf, media_type="application/pdf", filename=pdf.name)


# ------------------------------------------------------------------ resposta
def _conferencia(d: dict) -> Conferencia | None:
    try:
        return Conferencia.de_json(d["conferencia_relatorio"]) if d.get("conferencia_relatorio") else None
    except Exception:  # noqa: BLE001 — relatório antigo ou corrompido: só perde os avisos
        return None


def _filtrar(textos) -> list[str]:
    from web.dav_ui import _filtrar as filtrar_vendedor   # o vendedor não vê detalhe financeiro
    return filtrar_vendedor([_sem_segredo(t) or "" for t in textos if t])


def estado_publico(d: dict) -> str:
    """conferindo | gerando | pronto | erros | erro | incerto."""
    estado, conf = d["estado"], d.get("conferencia")
    if estado == "rejeitado" or (estado == "rascunho" and conf == "erros"):
        return "erros"
    if estado == "rascunho":
        return "conferindo"
    if estado in ("fila", "gerando"):
        return "gerando"
    if estado in ("pronto", "incerto"):
        return estado
    return "erro"   # erro, simulado e o que mais aparecer


def itens_ncm(d: dict) -> list[dict]:
    """NCM e de onde veio, por item. `cadastro HSE` ainda vem sem NCM: o
    Cotafrete não lê o NCM do produto cadastrado (ver INTEGRACAO_DAV_MAESTRO.md)."""
    try:
        orc = ler_planilha(FILA.planilha(d["id"]))
    except Exception:  # noqa: BLE001 — planilha recusada ou apagada: sem itens
        return []
    conf = _conferencia(d)
    textos = "\n".join(t for t in (d.get("relatorio"), conf.relatorio if conf else "") if t)
    ia = dict(_NCM_IA.findall(textos))
    novos = dict(_NCM_NOVO.findall(textos))
    existentes = dict(_EXISTENTE.findall(textos))
    saida = []
    for item in orc.itens:
        n = str(item.numero)
        if item.codigo or n in existentes:
            saida.append({"item": item.numero, "codigo": item.codigo or existentes.get(n),
                          "ncm": None, "origem": "cadastro HSE"})
        elif n in ia:
            saida.append({"item": item.numero, "codigo": None, "ncm": ia[n], "origem": "IA"})
        elif item.ncm or n in novos:
            saida.append({"item": item.numero, "codigo": None, "ncm": item.ncm or novos[n], "origem": "planilha"})
        else:
            saida.append({"item": item.numero, "codigo": None, "ncm": None, "origem": None})
    return saida


def situacao(d: dict) -> dict:
    publico = estado_publico(d)
    conf = _conferencia(d)
    avisos = _filtrar(conf.avisos) if conf else []
    erros: list[str] = []
    if d["estado"] == "rejeitado":
        erros = _filtrar((d.get("erro") or "").split("\n"))
    elif publico == "erros":
        erros = _filtrar(conf.erros) if conf and conf.erros else ["A conferência no HSE achou erros na planilha."]
    elif d["estado"] == "simulado":
        erros = [SIMULADO]
    elif publico == "incerto":
        erros = _filtrar([d.get("erro") or "", INCERTO])
    elif publico == "erro":
        erros = _filtrar([d.get("erro") or "O robô do HSE não conseguiu gerar o DAV."])
    return {"id": d["id"], "cotacao": d.get("api_cotacao"), "estado": publico,
            "numero": d.get("numero") or None, "cliente": d.get("cliente") or None,
            "avisos": avisos, "erros": erros, "pdf": publico == "pronto" and bool(d.get("pdf")),
            "itens": [] if d["estado"] == "rejeitado" else itens_ncm(d)}


# ------------------------------------------------------------------ fila
def seguir(dav_id: int) -> None:
    """Fim da conferência de um DAV da API: ok / avisos / sem HSE seguem para
    o Gerar (a tela faria o mesmo no clique); erros param ali."""
    if banco is None or FILA is None:
        return
    from web.dav_ui import _TRAVA
    with _TRAVA:
        d = no_banco(banco.dav, dav_id, None)
        if (d is None or not d.get("api_cotacao") or d["estado"] != "rascunho"
                or d.get("conferencia") not in ("ok", "nao_conferido")):
            return
        no_banco(banco.dav_atualizar, dav_id, estado="fila")   # antes: o robô só pega "fila"
        FILA.enfileirar(dav_id)
    log.info("API do DAV: %s conferido (%s), foi para a fila do Gerar", dav_id, d.get("conferencia"))


def retomar() -> None:
    """Na partida, depois de FILA_CONFERENCIA.retomar(): o que a API deixou
    conferido sem ir para a fila (servidor caiu no meio) segue agora."""
    for dav_id in no_banco(banco.dav_api_parados):
        seguir(dav_id)
