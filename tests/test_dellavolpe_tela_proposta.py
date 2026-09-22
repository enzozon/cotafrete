"""A Della Volpe na tela da cotação, agora que o preço dela volta.

Três estados novos da mesma linha, e o que cada um precisa mostrar:

- **com proposta** (o ingestor leu o PDF): preço, prazo, validade, número da
  proposta e o link do PDF — e o cartão "Semiautomática" some, senão o
  vendedor manda a mesma cotação de novo;
- **captcha na tela** (o robô parou antes de enviar): diz que NADA saiu e
  aponta o formulário preenchido. Nunca a frase da senha errada;
- **enviada, esperando o e-mail**: se a resposta vai para a caixa do
  suporte, diz que o preço aparece AQUI — não manda abrir um e-mail que o
  vendedor não vai receber.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from carriers.base import ResultadoCotacao
from carriers.dellavolpe.adapter import CAPTCHA_NA_TELA
from core.banco import Banco
from core.models import Local, StatusCotacao
from tests.apoio import entrar
from tests.apoio_pdf import pdf_com_texto
from tests.test_web_cotacao import CARGA, FORM_VALIDO, linha_de

IMAP = {"DV_IMAP_HOST": "imap.exemplo.com.br",
        "DV_IMAP_USUARIO": "suporte@ventura.com.br",
        "DV_IMAP_SENHA": "segredo"}


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    monkeypatch.setattr(modulo, "TENTATIVAS_EM_CURSO", {})
    for chave in (*IMAP, "DV_EMAIL_RESPOSTA"):
        monkeypatch.delenv(chave, raising=False)
    return modulo


@pytest.fixture
def cliente(app_web):
    c = TestClient(app_web.app)
    entrar(c, app_web)
    return c


@pytest.fixture
def pdf(tmp_path):
    arquivo = tmp_path / "proposta-15626-26.pdf"
    arquivo.write_bytes(pdf_com_texto("Proposta n. 15626/26"))
    return arquivo


def _com_proposta(app_web, pdf) -> int:
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    app_web.banco.salvar_resultado(
        cid, "dellavolpe", status="cotado", valor=Decimal("196.40"),
        protocolo="15626/26", prazo="6", validade=date(2099, 9, 29),
        evidencia=str(pdf))
    return cid


def _so_texto(html: str) -> str:
    return " ".join(html.split())


# ------------------------------------------------------------ com proposta
def test_a_linha_mostra_preco_prazo_validade_e_numero(app_web, cliente, pdf):
    cid = _com_proposta(app_web, pdf)

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "dellavolpe")

    assert "196,40" in linha
    assert "6 dias" in linha
    assert "29/09" in linha


def test_o_numero_da_proposta_aparece(app_web, cliente, pdf):
    cid = _com_proposta(app_web, pdf)

    assert "15626/26" in cliente.get(f"/cotacao/{cid}").text


def test_no_lugar_do_print_vai_o_link_do_pdf(app_web, cliente, pdf):
    cid = _com_proposta(app_web, pdf)

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "dellavolpe")

    assert f'href="/cotacao/{cid}/proposta/dellavolpe"' in linha
    assert "data:image/png;base64" not in linha


def test_com_preco_o_cartao_assistido_some(app_web, cliente, pdf):
    """Ela já respondeu. Oferecer o formulário é convidar a mandar DE NOVO
    para a fila de uma pessoa de verdade."""
    cid = _com_proposta(app_web, pdf)

    html = cliente.get(f"/cotacao/{cid}").text

    assert 'href="/dellavolpe/' not in html


def test_a_nota_nao_diz_mais_que_o_preco_nao_sai_na_tela(app_web, cliente,
                                                         pdf):
    cid = _com_proposta(app_web, pdf)

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "dellavolpe")

    assert "não sai na tela" not in linha
    assert "ICMS" in linha


def test_o_pdf_abre_para_o_dono(app_web, cliente, pdf):
    cid = _com_proposta(app_web, pdf)

    resposta = cliente.get(f"/cotacao/{cid}/proposta/dellavolpe")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "application/pdf"
    assert resposta.content.startswith(b"%PDF")


def test_o_pdf_nao_abre_para_outro_vendedor(app_web, pdf):
    cid = _com_proposta(app_web, pdf)
    outro = entrar(TestClient(app_web.app), app_web, "outra_pessoa")

    assert outro.get(f"/cotacao/{cid}/proposta/dellavolpe").status_code == 404


def test_sem_login_nao_abre_o_pdf(app_web, pdf):
    cid = _com_proposta(app_web, pdf)

    resposta = TestClient(app_web.app).get(
        f"/cotacao/{cid}/proposta/dellavolpe", follow_redirects=False)

    assert resposta.status_code == 303


def test_print_de_outra_transportadora_nao_sai_como_pdf(app_web, cliente,
                                                        tmp_path):
    png = tmp_path / "camilo.png"
    png.write_bytes(b"\x89PNG")
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    app_web.banco.salvar_resultado(cid, "camilo", status="cotado",
                                   valor=Decimal("10"), evidencia=str(png))

    assert cliente.get(
        f"/cotacao/{cid}/proposta/camilo").status_code == 404


def test_o_pdf_entra_no_zip_com_a_extensao_certa(app_web, cliente, pdf):
    cid = _com_proposta(app_web, pdf)

    resposta = cliente.get(f"/cotacao/{cid}/evidencias.zip")

    nomes = zipfile.ZipFile(io.BytesIO(resposta.content)).namelist()
    assert nomes == ["dellavolpe.pdf"]


def test_o_painel_do_adm_nao_embute_pdf_como_imagem(pdf):
    from web.layout import print_embutido

    assert print_embutido(str(pdf)) == ""


# ------------------------------------------------------------ captcha
def _com_captcha(app_web) -> int:
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    app_web.banco.salvar_resultado(
        cid, "dellavolpe",
        status=StatusCotacao.INTERVENCAO_NECESSARIA.value,
        erro=CAPTCHA_NA_TELA)
    return cid


def test_captcha_diz_que_nada_foi_enviado(app_web, cliente):
    cid = _com_captcha(app_web)

    linha = _so_texto(linha_de(cliente.get(f"/cotacao/{cid}").text,
                               "dellavolpe"))
    detalhe = _so_texto(cliente.get(f"/cotacao/{cid}").text)

    assert "Envie pelo formulário" in linha
    assert "Nada foi enviado à Della Volpe" in detalhe


def test_captcha_nao_fala_de_senha(app_web, cliente):
    """O ramo da senha recusada manda avisar quem cuida do sistema. Aqui não
    há o que consertar: quem resolve é o próprio vendedor, em dois cliques."""
    cid = _com_captcha(app_web)

    html = cliente.get(f"/cotacao/{cid}").text

    assert "senha desta transportadora" not in html


def test_captcha_mostra_o_formulario_preenchido(app_web, cliente,
                                                monkeypatch):
    monkeypatch.setattr(app_web, "AUTOMATICAS",
                        (*app_web.AUTOMATICAS, "dellavolpe"))
    cid = _com_captcha(app_web)

    html = cliente.get(f"/cotacao/{cid}").text

    assert f'href="/dellavolpe/{cid}"' in html


def test_o_captcha_da_senha_das_outras_continua_igual(app_web, cliente):
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    app_web.banco.salvar_resultado(
        cid, "translovato",
        status=StatusCotacao.INTERVENCAO_NECESSARIA.value,
        erro="senha recusada")

    assert "senha desta transportadora" in cliente.get(
        f"/cotacao/{cid}").text


# --------------------------------------------- automática, ainda cotando
def test_cotando_sozinha_nao_oferece_o_formulario(app_web, cliente,
                                                  monkeypatch):
    """Enquanto o robô envia, o formulário à mão seria a SEGUNDA cotação."""
    monkeypatch.setattr(app_web, "AUTOMATICAS",
                        (*app_web.AUTOMATICAS, "dellavolpe"))
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)

    html = cliente.get(f"/cotacao/{cid}").text

    assert f'href="/dellavolpe/{cid}"' not in html
    assert 'data-t="dellavolpe"' in html        # a linha "cotando…"


def test_assistida_continua_oferecendo_o_formulario(app_web, cliente,
                                                    monkeypatch):
    monkeypatch.setattr(app_web, "AUTOMATICAS",
                        tuple(s for s in app_web.AUTOMATICAS
                              if s != "dellavolpe"))
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)

    assert f'href="/dellavolpe/{cid}"' in cliente.get(f"/cotacao/{cid}").text


def test_erro_no_automatico_oferece_o_formulario_com_ressalva(
        app_web, cliente, monkeypatch):
    monkeypatch.setattr(app_web, "AUTOMATICAS",
                        (*app_web.AUTOMATICAS, "dellavolpe"))
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    app_web.banco.salvar_resultado(
        cid, "dellavolpe", status="erro",
        erro="Confirmação de envio não identificada na resposta.")

    html = _so_texto(cliente.get(f"/cotacao/{cid}").text)

    assert f'href="/dellavolpe/{cid}"' in html
    assert "O envio automático falhou" in html


# ------------------------------------------------ enviada, esperando e-mail
def _aguardando(app_web) -> int:
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    app_web.banco.salvar_resultado(
        cid, "dellavolpe", status=StatusCotacao.AGUARDANDO_RETORNO.value)
    return cid


def test_com_caixa_do_suporte_o_preco_aparece_aqui(app_web, cliente,
                                                   monkeypatch):
    for k, v in IMAP.items():
        monkeypatch.setenv(k, v)
    cid = _aguardando(app_web)

    html = _so_texto(cliente.get(f"/cotacao/{cid}").text)

    assert "O preço aparece aqui sozinho" in html
    assert "vendas@ventura.com.br" not in html   # não manda abrir o dele


def test_sem_caixa_do_suporte_continua_mandando_abrir_o_email(app_web,
                                                              cliente):
    cid = _aguardando(app_web)

    html = _so_texto(cliente.get(f"/cotacao/{cid}").text)

    assert "vendas@ventura.com.br" in html
    assert "aparece aqui sozinho" not in html


def test_enviada_nao_oferece_o_formulario_de_novo(app_web, cliente):
    cid = _aguardando(app_web)

    assert f'href="/dellavolpe/{cid}"' not in cliente.get(
        f"/cotacao/{cid}").text


def test_esperando_a_proposta_a_tela_se_atualiza_devagar(app_web, cliente,
                                                         monkeypatch):
    monkeypatch.setattr(app_web, "INGESTOR", object())
    monkeypatch.setattr(app_web, "AUTOMATICAS", ("dellavolpe",))
    cid = _aguardando(app_web)

    html = cliente.get(f"/cotacao/{cid}").text

    assert '<meta http-equiv="refresh" content="20">' in html


def test_sem_ingestor_nao_fica_recarregando(app_web, cliente, monkeypatch):
    monkeypatch.setattr(app_web, "INGESTOR", None)
    monkeypatch.setattr(app_web, "AUTOMATICAS", ("dellavolpe",))
    cid = _aguardando(app_web)

    assert 'http-equiv="refresh"' not in cliente.get(f"/cotacao/{cid}").text


# ------------------------------------------------------- o id até o adapter
def test_a_fabrica_da_dellavolpe_passa_carimbo_e_caixa(app_web, monkeypatch):
    for k, v in IMAP.items():
        monkeypatch.setenv(k, v)
    chamadas = {}

    class AdapterFalso:
        def __init__(self, **kw):
            chamadas["init"] = kw

        def cotar(self, req, **kw):
            chamadas["cotar"] = kw
            return ResultadoCotacao("dellavolpe",
                                    StatusCotacao.AGUARDANDO_RETORNO)

    monkeypatch.setattr(app_web, "DellavolpeAdapter", AdapterFalso)

    app_web._cotar_dellavolpe(object(), cotacao_id=208)

    assert chamadas["cotar"] == {
        "confirmar_envio": True, "cotacao_id": 208,
        "email_resposta": "suporte@ventura.com.br"}
    assert chamadas["init"]["workdir"] == "teste_real/dellavolpe"


def test_o_cotar_entrega_o_id_da_cotacao_a_fabrica(app_web, cliente,
                                                   monkeypatch):
    """O caminho inteiro do /cotar: o número que a fábrica recebe é o da
    cotação que acabou de ser gravada — é ele que vira o carimbo."""
    from tests.test_dellavolpe_mapping import montar

    req = montar(origem=Local(uf="ES", cidade="Vila Velha", cep="29105770"),
                 destino=Local(uf="SP", cidade="São Paulo", cep="01310100"))
    recebidos = []
    monkeypatch.setattr(app_web, "montar_request", lambda dados: req)
    monkeypatch.setattr(app_web.buscador_cnpj, "buscar", lambda cnpj: "X")
    monkeypatch.setattr(app_web, "AUTOMATICAS", ("camilo",))
    monkeypatch.setattr(app_web, "FABRICAS", {
        "camilo": lambda r, cotacao_id=None: recebidos.append(cotacao_id)})
    monkeypatch.setattr(app_web.EXECUTOR, "submit",
                        lambda fn, *args: fn(*args))

    resposta = cliente.post("/cotar", data={**FORM_VALIDO,
                                            "transportadora": ["camilo"]},
                            follow_redirects=False)

    cid = int(resposta.headers["location"].rsplit("/", 1)[1])
    assert recebidos == [cid]


# ------------------------------------------------------------- a ajuda
def test_a_ajuda_acompanha_o_estado_dela(app_web, monkeypatch):
    """Com ela automática, "agora quem envia é você" mandaria o vendedor
    enviar uma cotação que já saiu."""
    sem = tuple(s for s in app_web.AUTOMATICAS if s != "dellavolpe")
    monkeypatch.setattr(app_web, "AUTOMATICAS", sem)
    assert "agora quem envia é você" in app_web.pagina_documentacao()

    monkeypatch.setattr(app_web, "AUTOMATICAS", (*sem, "dellavolpe"))
    ajuda = app_web.pagina_documentacao()
    assert "voltou a cotar sozinha" in ajuda
    assert "agora quem envia é você" not in ajuda


def test_automatica_sem_retorno_volta_a_oferecer_o_formulario(
        app_web, cliente, monkeypatch):
    """Passou o teto e o robô não gravou nada: ninguém sabe se saiu. Esconder
    o formulário ali deixaria a cotação sem caminho nenhum."""
    from datetime import datetime, timedelta

    monkeypatch.setattr(app_web, "AUTOMATICAS", ("dellavolpe",))
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    velho = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    with app_web.banco._conectar() as con:
        con.execute("UPDATE cotacao SET criado_em = ? WHERE id = ?",
                    (velho, cid))

    html = _so_texto(cliente.get(f"/cotacao/{cid}").text)

    assert f'href="/dellavolpe/{cid}"' in html
    assert "O envio automático falhou" in html
