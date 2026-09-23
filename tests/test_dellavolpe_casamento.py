"""A proposta sem carimbo encontrando a sua cotação.

O PDF real de 23/09/2026 (proposta 15693/26, fixture
dellavolpe_proposta_ac_vazio.txt) veio com o A/C VAZIO: o "(cot. N)" que o
robô põe no nome nunca volta. O ingestor passou a casar a proposta pela
carga:

- só entre cotações que ESTÃO esperando proposta na caixa do suporte, pedidas
  até 2 horas antes do e-mail;
- rota e peso real têm de bater;
- empate: nota fiscal (estimada pelo ad-valorem), depois peso cubado;
- empate de cargas idênticas: a mais antiga, e a próxima proposta vai para
  a seguinte;
- empate de cargas diferentes: NÃO grava.

Na dúvida, o preço não vai para cotação nenhuma — é o erro que chega na mesa
do cliente.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import pytest

from carriers.dellavolpe import ingestor
from carriers.dellavolpe.proposta import ler_proposta
from core.banco import Banco
from tests.apoio_pdf import pdf_com_texto

FIXTURE = (Path(__file__).parent / "fixtures"
           / "dellavolpe_proposta_ac_vazio.txt")
TEXTO = FIXTURE.read_text(encoding="utf-8")

# A carga da proposta 15693/26, como o Cotafrete a gravou: o formulário da
# Della Volpe recebeu 935 kg, 3 volumes de 200x80x185 e nota de 329.000.
CARGA = {"cep_origem": "09520000", "cep_destino": "29100000",
         "cidade_origem": "São Caetano do Sul", "uf_origem": "SP",
         "cidade_destino": "Vila Velha", "uf_destino": "ES",
         "peso_kg": "935", "quantidade": 3, "comprimento_cm": 200,
         "largura_cm": 80, "altura_cm": 185, "valor_nf": "329000",
         "material": "maquina de lavar louca",
         "email": "vendas2@venturainformatica.com.br"}


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def pedir(banco, *, resposta_em="tela", minutos_atras=5, usuario="enzo",
          **carga) -> int:
    """Uma cotação cujo vendedor apertou um dos botões da Della Volpe."""
    cid = banco.salvar_cotacao(usuario, {**CARGA, **carga})
    banco.reservar_envio(cid, "dellavolpe", resposta_em=resposta_em)
    quando = (datetime.now() - timedelta(minutes=minutos_atras)
              ).isoformat(timespec="seconds")
    with banco._conectar() as con:
        con.execute("UPDATE resultado SET pedido_em = ? WHERE cotacao_id = ?",
                    (quando, cid))
    banco.salvar_resultado(cid, "dellavolpe", status="aguardando_retorno")
    return cid


def email(texto=TEXTO, *, mid="<p1@dellavolpe.com.br>",
          quando: datetime | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"] = "CRISTIANE MARQUES <cristiane@dellavolpe.com.br>"
    msg["To"] = "suporte@venturainformatica.com.br"
    msg["Subject"] = "Proposta de Frete - 15693/26 - Della Volpe"
    msg["Date"] = format_datetime((quando or datetime.now()).astimezone())
    msg["Message-ID"] = mid
    msg.set_content("Olá, segue em anexo a sua proposta para análise.")
    msg.add_attachment(pdf_com_texto(texto), maintype="application",
                       subtype="pdf", filename="Proposta 15693.pdf")
    return msg.as_bytes()


def processar(banco, tmp_path, bruto):
    return ingestor.processar(bruto, banco, gravar=True, pasta=tmp_path)


def preco(banco, cid, usuario="enzo"):
    c = banco.buscar_cotacao(cid, usuario)
    r = next(r for r in c["resultados"] if r["transportadora"] == "dellavolpe")
    return r["valor"]


# ------------------------------------------------------ o PDF de verdade
def test_o_pdf_real_tem_o_ac_vazio_e_nao_inventa_destinatario():
    """O \\s antigo atravessava a linha e lia "ORIGEM: ..." como nome."""
    p = ler_proposta(TEXTO)

    assert p.destinatario == ""
    assert p.cotacao_id is None


def test_o_pdf_real_traz_o_que_liga_a_carga():
    p = ler_proposta(TEXTO)

    assert p.valor == Decimal("1873.91")          # o total, não o frete
    assert (p.cidade_origem, p.uf_origem) == ("SAO CAETANO DO SUL", "SP")
    assert (p.cidade_destino, p.uf_destino) == ("VILA VELHA", "ES")
    assert p.peso_real == Decimal("935.00")
    assert p.peso_cubado == Decimal("2664.00")
    assert p.cliente == "VENTURA INFORMATICA LTDA"


def test_a_nota_sai_do_ad_valorem():
    """R$ 658,00 a 0,20% = R$ 329.000,00 — o que foi digitado."""
    assert ler_proposta(TEXTO).nota_fiscal == Decimal("329000.00")


# ------------------------------------------------------ o caminho feliz
def test_casa_pela_rota_e_pelo_peso(banco, tmp_path):
    cid = pedir(banco)

    d = processar(banco, tmp_path, email())

    assert d.desfecho == "gravado" and d.cotacao_id == cid
    assert preco(banco, cid) == Decimal("1873.91")


def test_o_pdf_casado_fica_na_cotacao(banco, tmp_path):
    cid = pedir(banco)
    processar(banco, tmp_path, email())

    c = banco.buscar_cotacao(cid, "enzo")
    r = next(r for r in c["resultados"] if r["transportadora"] == "dellavolpe")
    assert r["evidencia"].endswith(".pdf") and Path(r["evidencia"]).exists()
    assert r["protocolo"] == "15693/26"
    assert f"cot{cid}" in r["evidencia"]


def test_o_email_e_registrado_com_a_cotacao(banco, tmp_path):
    cid = pedir(banco)
    processar(banco, tmp_path, email())

    [linha] = banco.emails_processados()
    assert (linha["desfecho"], linha["cotacao_id"]) == ("gravado", cid)


def test_acento_e_maiuscula_nao_atrapalham(banco, tmp_path):
    cid = pedir(banco, cidade_origem="sao caetano do sul")

    assert processar(banco, tmp_path, email()).cotacao_id == cid


def test_peso_quebrado_casa_com_o_arredondado_pra_cima(banco, tmp_path):
    """O robô digita 934,2 kg como 935 (mapping.peso_br). É 935 que volta."""
    cid = pedir(banco, peso_kg="934.2")

    assert processar(banco, tmp_path, email()).cotacao_id == cid


# -------------------------------------------- quem pode ser candidata
def test_quem_escolheu_meu_email_nao_e_candidata(banco, tmp_path):
    """A proposta dela foi para o vendedor. Uma proposta no suporte com a
    mesma rota é de outra cotação."""
    pedir(banco, resposta_em="email")

    assert processar(banco, tmp_path, email()).desfecho == "sem_par"


def test_quem_ja_tem_preco_nao_e_candidata(banco, tmp_path):
    cid = pedir(banco)
    banco.salvar_resultado(cid, "dellavolpe", status="cotado",
                           valor=Decimal("1"))

    assert processar(banco, tmp_path, email()).desfecho == "sem_par"


def test_pedida_ha_mais_de_duas_horas_nao_e_candidata(banco, tmp_path):
    pedir(banco, minutos_atras=3 * 60)

    assert processar(banco, tmp_path, email()).desfecho == "sem_par"


def test_o_formulario_assistido_tambem_e_candidato(banco, tmp_path):
    """Captcha na tela, vendedor enviou pelo formulário preenchido (que
    manda para o suporte). O relógio é a abertura do formulário."""
    cid = banco.salvar_cotacao("enzo", CARGA)
    banco.marcar_whatsapp_aberto(cid, "dellavolpe", "enzo")

    assert processar(banco, tmp_path, email()).cotacao_id == cid


def test_rota_diferente_nao_casa(banco, tmp_path):
    pedir(banco, cidade_destino="Vitória")

    d = processar(banco, tmp_path, email())

    assert d.desfecho == "sem_par" and "rota" in d.detalhe


def test_peso_diferente_nao_casa(banco, tmp_path):
    pedir(banco, peso_kg="500")

    d = processar(banco, tmp_path, email())

    assert d.desfecho == "sem_par" and "peso" in d.detalhe


# --------------------------------------------------------- os empates
def test_nota_fiscal_desempata(banco, tmp_path):
    outra = pedir(banco, valor_nf="50000", minutos_atras=10)
    certa = pedir(banco, minutos_atras=5)

    assert processar(banco, tmp_path, email()).cotacao_id == certa
    assert preco(banco, outra) is None


def test_peso_cubado_desempata_quando_a_nota_nao_separa(banco, tmp_path):
    """Mesma nota, medidas diferentes: o cubado do PDF (2.664 kg) é o das
    medidas 200x80x185 x 3."""
    outra = pedir(banco, comprimento_cm=100, minutos_atras=10)
    certa = pedir(banco, minutos_atras=5)

    assert processar(banco, tmp_path, email()).cotacao_id == certa
    assert preco(banco, outra) is None


def test_seguro_minimo_nao_descarta_todo_mundo(banco, tmp_path):
    """Se a Della Volpe cobrar seguro mínimo, a nota estimada não bate com
    nenhuma. O critério que não separa ninguém é ignorado — e o cubado
    ainda desempata."""
    texto = TEXTO.replace("R$658,00 0,20%", "R$90,00 0,20%")
    outra = pedir(banco, comprimento_cm=100, minutos_atras=10)
    certa = pedir(banco, minutos_atras=5)

    assert processar(banco, tmp_path, email(texto)).cotacao_id == certa
    assert preco(banco, outra) is None


def test_cargas_identicas_vao_uma_para_cada_na_ordem(banco, tmp_path):
    """Dois vendedores cotaram a MESMA carga. As propostas são iguais: a
    primeira vai para a mais antiga, a segunda para a outra."""
    primeira = pedir(banco, usuario="enzo", minutos_atras=10)
    segunda = pedir(banco, usuario="lucas", minutos_atras=5)

    a = processar(banco, tmp_path, email(mid="<a@dellavolpe.com.br>"))
    b = processar(banco, tmp_path, email(mid="<b@dellavolpe.com.br>"))

    assert (a.cotacao_id, b.cotacao_id) == (primeira, segunda)
    assert preco(banco, primeira, "enzo") == Decimal("1873.91")
    assert preco(banco, segunda, "lucas") == Decimal("1873.91")


def test_cargas_diferentes_que_o_pdf_nao_separa_nao_grava(banco, tmp_path):
    """Diferem só no material — que vai no formulário mas não aparece no
    PDF. Não são a MESMA carga, e escolher uma seria chute."""
    a = pedir(banco, material="geladeira", minutos_atras=10)
    b = pedir(banco, minutos_atras=5)

    d = processar(banco, tmp_path, email())

    assert d.desfecho == "ambigua"
    assert f"#{a}" in d.detalhe and f"#{b}" in d.detalhe
    assert preco(banco, a) is None and preco(banco, b) is None


def test_email_que_nao_casou_continua_nao_lido(banco, tmp_path):
    """E registrado: não é relido a cada minuto."""
    from tests.test_dellavolpe_ingestor import CAIXA, ImapFalso

    imap = ImapFalso({b"9": email()})

    [d] = ingestor.varrer(CAIXA, banco, gravar=True,
                          conectar_fn=lambda cx: imap, pasta=tmp_path)

    assert d.desfecho == "sem_par"
    assert not [c for c in imap.comandos if c[0] == "STORE"]
    assert banco.email_ja_processado("<p1@dellavolpe.com.br>")


def test_o_que_foi_sem_carimbo_ontem_ganha_segunda_leitura(tmp_path):
    """O ingestor de 22/09/2026 registrou como "sem_carimbo" as propostas
    reais — todas vêm com o A/C vazio. O banco esquece esses registros na
    subida, para a regra nova ler de novo."""
    caminho = tmp_path / "t.db"
    Banco(caminho).registrar_email("<velho@dellavolpe.com.br>", "dellavolpe",
                                   desfecho="sem_carimbo")

    assert not Banco(caminho).email_ja_processado("<velho@dellavolpe.com.br>")


# --------------------------------------------------- casar, puro
def test_pagador_diferente_tambem_nao_e_a_mesma_carga(banco, tmp_path):
    """Outro pagador pode ter outra tabela negociada: o mesmo preço não
    serve às duas."""
    pedir(banco, cnpj_pagador="60.042.686/0001-05", minutos_atras=10)
    pedir(banco, cnpj_pagador="08.310.365/0001-24", minutos_atras=5)

    assert processar(banco, tmp_path, email()).desfecho == "ambigua"


def test_casar_sem_candidatas():
    dona, desfecho, _ = ingestor.casar(ler_proposta(TEXTO), [])

    assert dona is None and desfecho == "sem_par"


def test_carimbo_quando_existir_continua_mandando(banco, tmp_path):
    """Se um dia a Della Volpe devolver o nome no A/C, o número manda — e a
    rota só confere, como antes."""
    cid = banco.salvar_cotacao("enzo", CARGA)
    texto = TEXTO.replace("A/C:", f"A/C: ENZO ZON (COT. {cid})")

    d = processar(banco, tmp_path, email(texto))

    assert (d.desfecho, d.cotacao_id) == ("gravado", cid)


def test_a_linha_de_comando_diz_com_quem_casaria_sem_gravar(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    banco = Banco("cotafrete.db")
    cid = pedir(banco)
    arquivo = tmp_path / "dv.pdf"
    arquivo.write_bytes(pdf_com_texto(TEXTO))

    assert ingestor.main(["--pdf", str(arquivo)]) == 0

    assert f"casaria agora com a cotação #{cid}" in capsys.readouterr().out
    assert preco(banco, cid) is None
