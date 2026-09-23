"""O ingestor de e-mail da Della Volpe, sem rede.

Um e-mail de verdade (RFC 822, com PDF anexado de verdade) passa pelo mesmo
caminho da produção: `processar` para um e-mail, `varrer` para a caixa —
esta com um servidor IMAP de mentira que anota cada comando recebido.

O que estes testes travam são as três regras da caixa do suporte: só
e-mail da Della Volpe, nunca apagar, e só marcar lido depois de gravar. E a
regra mais cara do módulo: na dúvida, o preço NÃO vai para a cotação.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path

import pytest

from carriers.dellavolpe import ingestor
from carriers.dellavolpe.caixa import Caixa
from core.banco import Banco
from tests.apoio_pdf import pdf_com_texto

FIXTURE = Path(__file__).parent / "fixtures" / "dellavolpe_proposta.txt"

CARGA = {"cep_origem": "30140071", "cep_destino": "29100000",
         "cidade_origem": "Belo Horizonte", "uf_origem": "MG",
         "cidade_destino": "Vila Velha", "uf_destino": "ES",
         "peso_kg": "2", "quantidade": 1, "comprimento_cm": 30,
         "largura_cm": 30, "altura_cm": 30, "valor_nf": "10",
         "material": "PECAS", "email": "vendedor@ventura.com.br"}


def texto_proposta(carimbo: str | None = "(COT. {id})", cid: int = 1,
                   origem: str = "BELO HORIZONTE/MG") -> str:
    texto = FIXTURE.read_text(encoding="utf-8")
    if carimbo:
        texto = texto.replace("A/C: ENZO ZON",
                              "A/C: ENZO ZON " + carimbo.format(id=cid))
    return texto.replace("ORIGEM: BELO HORIZONTE/MG", f"ORIGEM: {origem}")


def email_bruto(texto_pdf: str | None, *, remetente="cotacao@dellavolpe.com.br",
                mid="<proposta-1@dellavolpe.com.br>",
                extra_pdfs: tuple[bytes, ...] = ()) -> bytes:
    msg = EmailMessage()
    msg["From"] = f"Della Volpe <{remetente}>"
    msg["To"] = "suporte@ventura.com.br"
    msg["Subject"] = "Proposta de frete"
    msg["Date"] = "Tue, 22 Sep 2026 14:05:00 -0300"
    if mid:
        msg["Message-ID"] = mid
    msg.set_content("Segue proposta em anexo.")
    for dados in extra_pdfs:
        msg.add_attachment(dados, maintype="application", subtype="pdf",
                           filename="folder.pdf")
    if texto_pdf is not None:
        msg.add_attachment(pdf_com_texto(texto_pdf), maintype="application",
                           subtype="pdf", filename="Proposta 15626.pdf")
    return msg.as_bytes()


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


@pytest.fixture
def cotacao(banco):
    return banco.salvar_cotacao("enzo", CARGA)


def _resultado(banco, cid):
    c = banco.buscar_cotacao(cid, "enzo")
    return next((r for r in c["resultados"]
                 if r["transportadora"] == "dellavolpe"), None)


# -------------------------------------------------------- o caminho feliz
def test_proposta_com_carimbo_vira_preco_na_cotacao(banco, cotacao, tmp_path):
    d = ingestor.processar(email_bruto(texto_proposta(cid=cotacao)), banco,
                           gravar=True, pasta=tmp_path / "pdfs")

    assert d.desfecho == "gravado"
    r = _resultado(banco, cotacao)
    # O TOTAL, com taxas e ICMS — nunca o "FRETE:" de R$ 167,63.
    assert r["valor"] == Decimal("196.40")
    assert r["status"] == "cotado"
    assert r["prazo"] == "6"
    assert r["validade"] == date(2026, 9, 29)
    assert r["protocolo"] == "15626/26"


def test_o_pdf_fica_guardado_e_e_a_evidencia(banco, cotacao, tmp_path):
    ingestor.processar(email_bruto(texto_proposta(cid=cotacao)), banco,
                       gravar=True, pasta=tmp_path / "pdfs")

    caminho = Path(_resultado(banco, cotacao)["evidencia"])
    assert caminho.suffix == ".pdf"
    assert caminho.read_bytes().startswith(b"%PDF")
    assert tmp_path / "pdfs" in caminho.parents


def test_respondido_em_e_a_hora_do_email_sem_fuso(banco, cotacao, tmp_path):
    """O banco grava hora local sem fuso (datetime.now()). O Date: do e-mail
    vem com -0300; misturar os dois formatos quebra a conta de "respondeu
    em"."""
    ingestor.processar(email_bruto(texto_proposta(cid=cotacao)), banco,
                       gravar=True, pasta=tmp_path)

    respondido = _resultado(banco, cotacao)["respondido_em"]
    assert respondido and "+" not in respondido and "-03" not in respondido


def test_o_email_fica_registrado_como_processado(banco, cotacao, tmp_path):
    ingestor.processar(email_bruto(texto_proposta(cid=cotacao)), banco,
                       gravar=True, pasta=tmp_path)

    assert banco.email_ja_processado("<proposta-1@dellavolpe.com.br>")
    [linha] = banco.emails_processados()
    assert linha["desfecho"] == "gravado"
    assert linha["cotacao_id"] == cotacao


def test_o_mesmo_email_nao_e_processado_duas_vezes(banco, cotacao, tmp_path):
    bruto = email_bruto(texto_proposta(cid=cotacao))
    ingestor.processar(bruto, banco, gravar=True, pasta=tmp_path)

    d = ingestor.processar(bruto, banco, gravar=True, pasta=tmp_path)

    assert d.desfecho == "ja_processado"
    assert len(list(tmp_path.rglob("*.pdf"))) == 1


def test_proposta_que_chega_depois_do_interrompido_apaga_o_aviso(
        banco, cotacao, tmp_path):
    """A varredura da subida pode ter carimbado "o sistema foi fechado" antes
    de a proposta chegar. A proposta é a prova de que o envio saiu."""
    banco.salvar_resultado(cotacao, "dellavolpe", status="interrompido",
                           erro="O sistema foi fechado durante a cotação.")

    ingestor.processar(email_bruto(texto_proposta(cid=cotacao)), banco,
                       gravar=True, pasta=tmp_path)

    r = _resultado(banco, cotacao)
    assert r["status"] == "cotado" and r["erro"] is None


def test_acha_a_proposta_mesmo_que_ela_nao_seja_o_primeiro_anexo(
        banco, cotacao, tmp_path):
    folder = pdf_com_texto("Conheca nossos servicos")
    bruto = email_bruto(texto_proposta(cid=cotacao), extra_pdfs=(folder,))

    assert ingestor.processar(bruto, banco, gravar=True,
                              pasta=tmp_path).desfecho == "gravado"


# ------------------------------------------- na dúvida, NÃO grava o preço
def test_sem_carimbo_nao_grava(banco, cotacao, tmp_path):
    """A proposta de um envio feito ANTES do carimbo, ou pelo e-mail avulso.
    Adivinhar a cotação pela rota poria o preço na carga de outra pessoa."""
    d = ingestor.processar(email_bruto(texto_proposta(carimbo=None)), banco,
                           gravar=True, pasta=tmp_path)

    assert d.desfecho == "sem_carimbo"
    assert _resultado(banco, cotacao) is None
    assert not list(tmp_path.rglob("*.pdf"))


def test_carimbo_de_cotacao_que_nao_existe_nao_grava(banco, cotacao, tmp_path):
    d = ingestor.processar(email_bruto(texto_proposta(cid=9999)), banco,
                           gravar=True, pasta=tmp_path)

    assert d.desfecho == "sem_cotacao"


def test_rota_que_nao_bate_nao_grava(banco, cotacao, tmp_path):
    """O carimbo diz #1, mas o PDF é de SP e a cotação #1 sai de MG: o número
    veio trocado. O preço fica fora — e o e-mail, não lido, para alguém ver."""
    d = ingestor.processar(
        email_bruto(texto_proposta(cid=cotacao, origem="SAO PAULO/SP")),
        banco, gravar=True, pasta=tmp_path)

    assert d.desfecho == "rota_diferente"
    assert "SP" in d.detalhe and "MG" in d.detalhe
    assert _resultado(banco, cotacao) is None


def test_pdf_sem_valor_total_nao_grava(banco, cotacao, tmp_path):
    texto = texto_proposta(cid=cotacao).replace("VALOR TOTAL DO FRETE",
                                                "TOTAL")
    d = ingestor.processar(email_bruto(texto), banco, gravar=True,
                           pasta=tmp_path)

    assert d.desfecho == "sem_valor"
    assert _resultado(banco, cotacao) is None


def test_email_sem_pdf_nao_grava(banco, cotacao, tmp_path):
    d = ingestor.processar(email_bruto(None), banco, gravar=True,
                           pasta=tmp_path)

    assert d.desfecho == "sem_pdf"


def test_remetente_de_fora_nem_e_registrado(banco, cotacao, tmp_path):
    """`naodellavolpe.com.br` também TERMINA com o domínio. A busca do IMAP é
    por trecho; a conferência daqui é exata."""
    bruto = email_bruto(texto_proposta(cid=cotacao),
                        remetente="golpe@naodellavolpe.com.br")

    d = ingestor.processar(bruto, banco, gravar=True, pasta=tmp_path)

    assert d.desfecho == "outro_remetente"
    assert _resultado(banco, cotacao) is None
    assert not banco.emails_processados()


@pytest.mark.parametrize("endereco,esperado", [
    ("cotacao@dellavolpe.com.br", True),
    ("x@filial.dellavolpe.com.br", True),
    ("COTACAO@DELLAVOLPE.COM.BR", True),
    ("golpe@naodellavolpe.com.br", False),
    ("dellavolpe.com.br@golpe.com", False),
    ("", False),
])
def test_do_remetente(endereco, esperado):
    assert ingestor.do_remetente(endereco, "dellavolpe.com.br") is esperado


def test_pdf_quebrado_e_tentado_de_novo_na_proxima_volta(banco, cotacao,
                                                         tmp_path):
    """Download cortado não é desfecho: registrar aqui faria o e-mail ser
    pulado para sempre."""
    msg = EmailMessage()
    msg["From"] = "cotacao@dellavolpe.com.br"
    msg["Message-ID"] = "<quebrado@dellavolpe.com.br>"
    msg.set_content("x")
    msg.add_attachment(b"%PDF-1.4 cortado no meio", maintype="application",
                       subtype="pdf", filename="p.pdf")

    d = ingestor.processar(msg.as_bytes(), banco, gravar=True, pasta=tmp_path)

    assert d.desfecho == "pdf_ilegivel"
    assert not banco.email_ja_processado("<quebrado@dellavolpe.com.br>")


def test_sem_message_id_ainda_tem_chave_estavel(banco, cotacao, tmp_path):
    bruto = email_bruto(texto_proposta(cid=cotacao), mid=None)

    primeiro = ingestor.processar(bruto, banco, gravar=True, pasta=tmp_path)
    segundo = ingestor.processar(bruto, banco, gravar=True, pasta=tmp_path)

    assert primeiro.desfecho == "gravado"
    assert segundo.desfecho == "ja_processado"


# ------------------------------------------------ somente leitura é leitura
def test_sem_gravar_nao_escreve_nada(banco, cotacao, tmp_path):
    pasta = tmp_path / "pdfs"
    d = ingestor.processar(email_bruto(texto_proposta(cid=cotacao)), banco,
                           gravar=False, pasta=pasta)

    assert d.desfecho == "gravado"          # o que FARIA
    assert d.proposta.valor == Decimal("196.40")
    assert _resultado(banco, cotacao) is None
    assert not banco.emails_processados()
    assert not pasta.exists()


# ---------------------------------------------------------------- a caixa
class ImapFalso:
    """Anota cada comando. Os e-mails ficam em {uid: bytes}."""

    def __init__(self, emails: dict[bytes, bytes], falhar_em: bytes = b""):
        self.emails = emails
        self.falhar_em = falhar_em
        self.comandos: list[tuple] = []
        self.readonly = None

    def select(self, pasta, readonly=False):
        self.readonly = readonly
        self.comandos.append(("SELECT", pasta, readonly))
        return "OK", [str(len(self.emails)).encode()]

    def uid(self, comando, *args):
        self.comandos.append((comando.upper(), *args))
        comando = comando.upper()
        if comando == "SEARCH":
            return "OK", [b" ".join(self.emails)]
        if comando == "FETCH":
            uid, partes = args
            if uid == self.falhar_em:
                raise OSError("conexão caiu no meio")
            bruto = self.emails[uid]
            if "HEADER.FIELDS" in partes:
                cab = bruto.split(b"\n\n", 1)[0]
                return "OK", [(b"1 (UID)", cab), b")"]
            return "OK", [(b"1 (UID)", bruto), b")"]
        if comando == "STORE":
            return "OK", [b""]
        raise AssertionError(f"comando inesperado: {comando}")

    def logout(self):
        self.comandos.append(("LOGOUT",))


CAIXA = Caixa(host="imap.exemplo", usuario="suporte@ventura.com.br",
              senha="x")


def _varrer(banco, imap, tmp_path, gravar=True):
    return ingestor.varrer(CAIXA, banco, gravar=gravar,
                           conectar_fn=lambda cx: imap, pasta=tmp_path,
                           hoje=date(2026, 9, 22))


def test_busca_so_o_remetente_da_della_volpe(banco, tmp_path):
    imap = ImapFalso({})

    _varrer(banco, imap, tmp_path)

    [busca] = [c for c in imap.comandos if c[0] == "SEARCH"]
    assert busca[1:] == (None, "FROM", '"dellavolpe.com.br"',
                         "SINCE", "19-Sep-2026")


def test_marca_lido_so_o_que_gravou(banco, cotacao, tmp_path):
    imap = ImapFalso({
        b"10": email_bruto(texto_proposta(cid=cotacao)),
        b"11": email_bruto(texto_proposta(carimbo=None),
                           mid="<sem-carimbo@dellavolpe.com.br>"),
    })

    desfechos = _varrer(banco, imap, tmp_path)

    assert [d.desfecho for d in desfechos] == ["gravado", "sem_carimbo"]
    lidos = [c for c in imap.comandos if c[0] == "STORE"]
    assert lidos == [("STORE", b"10", "+FLAGS", r"(\Seen)")]


def test_nunca_apaga_nem_move(banco, cotacao, tmp_path):
    """A caixa é do suporte. O robô só lê — e, depois de gravar, marca lido."""
    imap = ImapFalso({b"10": email_bruto(texto_proposta(cid=cotacao))})

    _varrer(banco, imap, tmp_path)

    usados = {c[0] for c in imap.comandos}
    assert usados <= {"SELECT", "SEARCH", "FETCH", "STORE", "LOGOUT"}
    for c in imap.comandos:
        if c[0] == "STORE":
            assert c[2:] == ("+FLAGS", r"(\Seen)")
        if c[0] == "FETCH":
            assert "PEEK" in c[2], "FETCH sem PEEK marca lido antes de gravar"


def test_somente_leitura_abre_readonly_e_nao_marca_nada(banco, cotacao,
                                                        tmp_path):
    imap = ImapFalso({b"10": email_bruto(texto_proposta(cid=cotacao))})

    [d] = _varrer(banco, imap, tmp_path, gravar=False)

    assert d.desfecho == "gravado"
    assert imap.readonly is True
    assert not [c for c in imap.comandos if c[0] == "STORE"]
    assert _resultado(banco, cotacao) is None


def test_email_ja_processado_nem_e_baixado_de_novo(banco, cotacao, tmp_path):
    """A cada minuto a busca devolve os mesmos e-mails dos últimos dias.
    Baixar o PDF de todos, toda vez, é tráfego à toa na caixa do suporte."""
    bruto = email_bruto(texto_proposta(cid=cotacao))
    _varrer(banco, ImapFalso({b"10": bruto}), tmp_path)

    imap = ImapFalso({b"10": bruto})
    assert _varrer(banco, imap, tmp_path) == []
    baixados = [c for c in imap.comandos
                if c[0] == "FETCH" and "HEADER.FIELDS" not in c[2]]
    assert baixados == []


def test_um_email_que_quebra_nao_derruba_os_outros(banco, cotacao, tmp_path):
    imap = ImapFalso({
        b"10": email_bruto(texto_proposta(cid=cotacao),
                           mid="<um@dellavolpe.com.br>"),
        b"11": email_bruto(texto_proposta(cid=cotacao),
                           mid="<dois@dellavolpe.com.br>"),
    }, falhar_em=b"10")

    desfechos = _varrer(banco, imap, tmp_path)

    assert [d.desfecho for d in desfechos] == ["falhou", "gravado"]


def test_sempre_faz_logout(banco, tmp_path):
    class Quebra(ImapFalso):
        def uid(self, comando, *args):
            raise OSError("caiu")

    imap = Quebra({})
    with pytest.raises(OSError):
        _varrer(banco, imap, tmp_path)
    assert imap.comandos[-1] == ("LOGOUT",)


def test_data_do_imap_e_em_ingles_em_qualquer_maquina():
    """strftime('%b') num Windows em português escreve 'set' — e a busca
    volta vazia, em silêncio."""
    assert ingestor.data_imap(date(2026, 9, 3)) == "03-Sep-2026"
    assert ingestor.data_imap(date(2026, 2, 28)) == "28-Feb-2026"


# ----------------------------------------------------------- a thread
def test_sem_caixa_no_env_nao_sobe_thread(banco):
    assert ingestor.iniciar(banco, ambiente={}) is None


def test_falha_de_login_espera_cada_vez_mais(banco, monkeypatch):
    """Senha errada tentada a cada minuto bloqueia a conta do suporte."""
    vigia = ingestor.Vigia(CAIXA, banco, log=lambda _: None)
    esperas = []

    def volta():
        raise OSError("LOGIN failed")

    def espera(segundos):
        esperas.append(segundos)
        if len(esperas) >= 8:
            vigia.parar.set()

    monkeypatch.setattr(vigia, "volta", volta)
    monkeypatch.setattr(vigia.parar, "wait", espera)

    vigia.run()

    assert esperas[:3] == [120, 240, 480]
    assert max(esperas) == ingestor.ESPERA_MAXIMA_APOS_FALHA_S
    assert vigia.ultimo_erro and "LOGIN failed" in vigia.ultimo_erro


# ------------------------------------------------------------- à mão
def test_linha_de_comando_le_um_pdf_solto(tmp_path, capsys):
    arquivo = tmp_path / "p.pdf"
    arquivo.write_bytes(pdf_com_texto(texto_proposta(cid=208)))

    assert ingestor.main(["--pdf", str(arquivo)]) == 0

    saida = capsys.readouterr().out
    assert "196.40" in saida and "208" in saida
