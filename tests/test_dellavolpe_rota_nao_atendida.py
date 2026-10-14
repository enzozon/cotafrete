"""Della Volpe: o e-mail "Rota não atendida" vira recusa na cotação certa.

Antes de 14/10/2026 ele caía em "sem_pdf" e a linha ficava para sempre em
"Cotação enviada — o preço aparece aqui sozinho" (#399, Pequi/MG). Ele não
diz de qual cotação é; quem diz é o irmão "Dados preenchidos no Formulário",
que sai no mesmo segundo com o mesmo começo de Message-ID e traz o
"(cot. N)". Textos copiados dos dois e-mails reais daquele dia.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from carriers.dellavolpe import ingestor
from core.banco import Banco
from core.models import StatusCotacao
from tests.test_dellavolpe_ingestor import ImapFalso, _varrer

CARGA = {"cep_origem": "29105770", "cep_destino": "35667000",
         "cidade_origem": "Vila Velha", "uf_origem": "ES",
         "cidade_destino": "Pequi", "uf_destino": "MG",
         "peso_kg": "80", "quantidade": 10, "comprimento_cm": 60,
         "largura_cm": 60, "altura_cm": 50, "valor_nf": "46500",
         "material": "Computador de mesa", "email": "vendedor@ventura.com.br"}

TEXTO_ROTA = (
    "Prezado(a),\nAgradecemos por utilizar nossos serviços e por considerar a "
    "Della Volpe para suas necessidades de transporte.\nNo momento, a rota que "
    "você selecionou ao criar sua cotação não é atendida por nossos serviços.")


def texto_dados(cid: int, uf_destino: str = "MG") -> str:
    return ("Olá,\nSegue abaixo os dados recebidos pelo formulário de Cotação "
            f"do site da Della Volpe:\nNome Completo: enzo zon (cot. {cid})\n"
            "UF Origem: ES\nCidade Origem: Vila Velha\n"
            f"UF Destino: {uf_destino}\nCidade Destino: Pequi\n"
            "Peso Total (kg): 80\nQuantidade de Volumes: 10\n"
            "Tipo de Serviço: Fracionado -LTL\n")


def email(assunto: str, texto: str, mid: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = "CRM Della Volpe <crm@dellavolpe.com.br>"
    msg["To"] = "suporte@ventura.com.br"
    msg["Subject"] = assunto
    msg["Date"] = "Wed, 14 Oct 2026 11:13:03 -0300"
    msg["Message-ID"] = mid
    msg.set_content(texto)
    return msg.as_bytes()


ROTA = email("Cotação Della Volpe Proposta Fracionado - Rota não atendida",
             TEXTO_ROTA, "<1791987183.a1kEYezS@crm.dellavolpe.com.br>")


def dados(cid: int, uf_destino: str = "MG") -> bytes:
    return email("Cotação Della Volpe - Dados preendhidos no Formulário - "
                 "11:13:03 14/10/2026", texto_dados(cid, uf_destino),
                 "<1791987183.fJ5zt1k8@crm.dellavolpe.com.br>")


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


@pytest.fixture
def cotacao(banco):
    cid = banco.salvar_cotacao("enzo", CARGA)
    banco.reservar_envio(cid, "dellavolpe", resposta_em="tela")
    banco.salvar_resultado(cid, "dellavolpe",
                           status=StatusCotacao.AGUARDANDO_RETORNO.value)
    return cid


def _dv(banco, cid):
    c = banco.buscar_cotacao(cid, "enzo")
    return next(r for r in c["resultados"] if r["transportadora"] == "dellavolpe")


def test_vira_recusa_na_cotacao_do_carimbo_do_irmao(banco, cotacao, tmp_path):
    d = ingestor.processar(ROTA, banco, gravar=True, pasta=tmp_path,
                           irmaos=lambda prefixo: [ROTA, dados(cotacao)])

    assert d.desfecho == "rota_nao_atendida" and d.cotacao_id == cotacao
    r = _dv(banco, cotacao)
    assert r["status"] == StatusCotacao.RECUSADO.value
    assert "não atende esta rota" in r["erro"]
    assert r["respondido_em"] == "2026-10-14T11:13:03"


def test_procura_o_irmao_pelo_comeco_do_message_id(banco, cotacao, tmp_path):
    pedidos = []
    ingestor.processar(ROTA, banco, gravar=True, pasta=tmp_path,
                       irmaos=lambda p: pedidos.append(p) or [dados(cotacao)])
    assert pedidos == ["<1791987183."]


def test_sem_o_irmao_nao_grava_e_fica_para_gente(banco, cotacao, tmp_path):
    d = ingestor.processar(ROTA, banco, gravar=True, pasta=tmp_path,
                           irmaos=lambda prefixo: [ROTA])

    assert d.desfecho == "sem_carimbo"
    assert _dv(banco, cotacao)["status"] == StatusCotacao.AGUARDANDO_RETORNO.value


def test_uf_que_nao_bate_nao_grava(banco, cotacao, tmp_path):
    d = ingestor.processar(ROTA, banco, gravar=True, pasta=tmp_path,
                           irmaos=lambda p: [dados(cotacao, uf_destino="SP")])

    assert d.desfecho == "rota_diferente"
    assert _dv(banco, cotacao)["status"] == StatusCotacao.AGUARDANDO_RETORNO.value


def test_sem_gravar_nao_escreve_nada(banco, cotacao, tmp_path):
    d = ingestor.processar(ROTA, banco, gravar=False, pasta=tmp_path,
                           irmaos=lambda p: [dados(cotacao)])

    assert d.desfecho == "rota_nao_atendida"
    assert _dv(banco, cotacao)["status"] == StatusCotacao.AGUARDANDO_RETORNO.value
    assert not banco.emails_processados()


def test_na_caixa_marca_lido_so_a_rota(banco, cotacao, tmp_path):
    imap = ImapFalso({b"9589": dados(cotacao), b"9590": ROTA})

    desfechos = _varrer(banco, imap, tmp_path)

    assert [d.desfecho for d in desfechos] == ["sem_pdf", "rota_nao_atendida"]
    lidos = [c for c in imap.comandos if c[0] == "STORE"]
    assert lidos == [("STORE", b"9590", "+FLAGS", r"(\Seen)")]
    assert _dv(banco, cotacao)["status"] == StatusCotacao.RECUSADO.value


def test_o_que_a_versao_antiga_deu_como_sem_pdf_e_relido_uma_vez(
        banco, cotacao, tmp_path):
    mid = "<1791987183.a1kEYezS@crm.dellavolpe.com.br>"
    banco.registrar_email(mid, "dellavolpe", desfecho="sem_pdf",
                          assunto="Cotação Della Volpe Proposta Fracionado - "
                                  "Rota não atendida")
    assert not banco.email_ja_processado(mid)

    ingestor.processar(ROTA, banco, gravar=True, pasta=tmp_path,
                       irmaos=lambda p: [dados(cotacao)])

    assert banco.email_ja_processado(mid)
    # a confirmação comum continua sendo "já processada"
    banco.registrar_email("<x@d>", "dellavolpe", desfecho="sem_pdf",
                          assunto="Cotação Della Volpe - Dados preendhidos")
    assert banco.email_ja_processado("<x@d>")


def test_o_cartao_troca_o_aguardando_pela_recusa(banco, cotacao, tmp_path,
                                                 monkeypatch):
    import web.app as app_web

    monkeypatch.setattr(app_web, "banco", banco)

    def tela() -> str:
        return app_web.ver_cotacao(cotacao, usuario="enzo").body.decode()

    assert "aparece aqui sozinho" in tela()
    ingestor.processar(ROTA, banco, gravar=True, pasta=tmp_path,
                       irmaos=lambda p: [dados(cotacao)])
    depois = tela()
    assert "aparece aqui sozinho" not in depois
    assert "O site não cotou" in depois
    assert "não atende esta rota" in depois
