"""Plano B da proposta da Della Volpe: a IA lê o PDF que o regex não entendeu.

O ponto destes testes é a CONFERÊNCIA, não a IA: a resposta da IA é
inventada aqui de propósito — certa, errada e mentirosa — e o que se trava
é que só entra na cotação o que o PDF prova. O erro caro continua o mesmo de
proposta.py: um preço errado na cotação faz a Della Volpe ganhar (ou perder)
a comparação com um número que não existe.

O PDF de partida é o REAL (fixture 15626/26), com o rótulo do valor e o
carimbo trocados — o "formato novo" que o leitor por regex não reconhece.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from carriers.dellavolpe import ingestor, proposta_ia as P
from carriers.dellavolpe.proposta import Proposta, ler_proposta
from core import ia
from tests.test_dellavolpe_ingestor import CARGA, FIXTURE, email_bruto
from tests.test_ia import Provedor, Resp

REAL = FIXTURE.read_text(encoding="utf-8")


def layout_novo(cid: int = 1, origem: str = "BELO HORIZONTE/MG") -> str:
    """O PDF real com o rótulo do total e o carimbo escritos de outro jeito."""
    return (REAL.replace("VALOR TOTAL DO FRETE: R$196,40",
                         "TOTAL A PAGAR (FRETE + TAXAS + ICMS): R$ 196,40")
            .replace("A/C: ENZO ZON", f"A/C: ENZO ZON - REF. COTAÇÃO {cid}")
            .replace("ORIGEM: BELO HORIZONTE/MG", f"ORIGEM: {origem}"))


def resposta_certa(cid: int = 1, **muda) -> dict:
    base = {"valor_total_frete": "196,40",
            "linha_do_valor": "TOTAL A PAGAR (FRETE + TAXAS + ICMS): R$ 196,40",
            "numero_proposta": "15626/26", "prazo_entrega_dias": 6, "validade_dias": 7,
            "data_emissao": "2026-09-22", "cotacao_carimbo": cid,
            "destinatario": f"ENZO ZON - REF. COTAÇÃO {cid}",
            "uf_origem": "MG", "uf_destino": "ES"}
    return base | muda


def test_o_regex_nao_le_o_layout_novo():
    """A premissa: sem o plano B esta proposta se perdia."""
    p = ler_proposta(layout_novo())
    assert p.valor is None and p.cotacao_id is None


# ------------------------------------------------------------- conferência
def test_resposta_certa_passa_inteira():
    p = P.conferir(resposta_certa(), layout_novo())
    assert p.valor == Decimal("196.40") and p.cotacao_id == 1
    assert (p.numero, p.prazo_dias, p.uf_origem, p.uf_destino) == ("15626/26", 6, "MG", "ES")
    assert p.emitida_em == date(2026, 9, 22) and p.validade == date(2026, 9, 29)


@pytest.mark.parametrize("valor, linha, porque", [
    ("167,63", "FRETE: R$167,63", "frete ANTES das taxas: não tem 'total'"),
    ("5.000,00", "VALOR TOTAL DA NOTA FISCAL: R$ 5.000,00", "linha não está no PDF"),
    ("0,02", "AD-VALOREM: R$0,02 0,20% SOBRE O VALOR TOTAL DA NOTA FISCAL", "é da nota fiscal"),
    ("198,40", "TOTAL A PAGAR (FRETE + TAXAS + ICMS): R$ 196,40", "número não está na linha"),
    ("196,40", "TOTAL: R$ 196,40", "linha inventada"),
    ("196,40", None, "sem linha de prova"),
    ("abc", "TOTAL A PAGAR (FRETE + TAXAS + ICMS): R$ 196,40", "não é dinheiro"),
])
def test_valor_sem_prova_no_pdf_nao_entra(valor, linha, porque):
    p = P.conferir(resposta_certa(valor_total_frete=valor, linha_do_valor=linha), layout_novo())
    assert p.valor is None, porque


def test_nota_fiscal_com_total_no_nome_nao_vira_frete():
    texto = layout_novo() + "\nVALOR TOTAL DA NOTA FISCAL: R$ 5.000,00"
    p = P.conferir(resposta_certa(valor_total_frete="5.000,00",
                                  linha_do_valor="VALOR TOTAL DA NOTA FISCAL: R$ 5.000,00"), texto)
    assert p.valor is None


def test_valor_com_milhar_confere_nos_dois_jeitos():
    texto = layout_novo().replace("R$ 196,40", "R$ 1.196,40")
    linha = "TOTAL A PAGAR (FRETE + TAXAS + ICMS): R$ 1.196,40"
    assert P.conferir(resposta_certa(valor_total_frete="1.196,40", linha_do_valor=linha),
                      texto).valor == Decimal("1196.40")


def test_carimbo_inventado_nao_entra():
    """Um carimbo errado mandaria o preço para a cotação de outra pessoa."""
    assert P.conferir(resposta_certa(cotacao_carimbo=208), layout_novo(cid=1)).cotacao_id is None
    assert P.conferir(resposta_certa(cotacao_carimbo=True), layout_novo()).cotacao_id is None


@pytest.mark.parametrize("campo, valor", [
    ("uf_origem", "SP"), ("uf_destino", "XX"), ("prazo_entrega_dias", 9),
    ("numero_proposta", "99999/26"), ("destinatario", "FULANO"),
])
def test_campos_que_o_pdf_nao_traz_ficam_vazios(campo, valor):
    p = P.conferir(resposta_certa(**{campo: valor}), layout_novo())
    lido = {"uf_origem": p.uf_origem, "uf_destino": p.uf_destino, "prazo_entrega_dias": p.prazo_dias,
            "numero_proposta": p.numero, "destinatario": p.destinatario}[campo]
    assert lido in (None, "")


def test_data_que_o_pdf_nao_traz_nao_vira_validade():
    p = P.conferir(resposta_certa(data_emissao="2026-09-25"), layout_novo())
    assert p.emitida_em is None and p.validade is None


def test_lixo_da_ia_vira_proposta_vazia():
    assert P.conferir("não sei", layout_novo()) == Proposta()
    assert P.conferir({}, layout_novo()) == Proposta()


# ----------------------------------------------------------------- mistura
def _ia(dados, modelo="falso:modelo"):
    chamadas = []

    def pedir(texto):
        chamadas.append(texto)
        return ia.Resposta(dados, modelo)
    pedir.chamadas = chamadas
    return pedir


@pytest.fixture
def ligada(monkeypatch):
    monkeypatch.setattr(P, "LIGADA", True)


def test_regex_manda_e_a_ia_so_preenche_o_que_faltou(ligada):
    texto = layout_novo()
    regex = ler_proposta(texto)          # leu prazo, número, data, UFs — não valor/carimbo
    p = P.completar(regex, texto, _ia(resposta_certa(prazo_entrega_dias=99, uf_origem="ES")))
    assert p.valor == Decimal("196.40") and p.cotacao_id == 1
    assert p.prazo_dias == regex.prazo_dias == 6 and p.uf_origem == "MG"   # regex venceu
    assert p.lido_por == "IA (falso:modelo): valor, cotacao_id"


def test_proposta_completa_nem_chama_a_ia(ligada):
    texto = REAL.replace("A/C: ENZO ZON", "A/C: ENZO ZON (COT. 1)")
    pedir = _ia(resposta_certa())
    p = P.completar(ler_proposta(texto), texto, pedir)
    assert pedir.chamadas == [] and p.lido_por == ""


def test_desligada_nao_chama(monkeypatch):
    monkeypatch.setattr(P, "LIGADA", False)
    pedir = _ia(resposta_certa())
    assert P.completar(Proposta(), layout_novo(), pedir) == Proposta() and pedir.chamadas == []


def test_ia_fora_do_ar_devolve_o_que_o_regex_leu(ligada):
    def fora(texto):
        raise ia.IAIndisponivel("nenhum modelo respondeu")
    regex = ler_proposta(layout_novo())
    assert P.completar(regex, layout_novo(), fora) == regex


def test_ia_que_so_inventa_nao_marca_lido_por(ligada):
    p = P.completar(ler_proposta(layout_novo()), layout_novo(),
                    _ia(resposta_certa(valor_total_frete="999,99", cotacao_carimbo=77)))
    assert p.valor is None and p.cotacao_id is None and p.lido_por == ""


# ---------------------------------------------- pela cadeia de modelos (core/ia)
def test_pedir_passa_pela_cadeia_com_o_nome_da_funcao(monkeypatch):
    prov = Provedor()
    registros = []
    monkeypatch.setattr(ia, "POST", prov)
    monkeypatch.setattr(ia, "_castigo", {})
    monkeypatch.setattr(ia, "REGISTRO", lambda **kw: registros.append(kw))
    monkeypatch.setenv("IA_MODELOS", "groq:melhor,openrouter:reserva:free")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "y")
    prov.roteiro["melhor"] = [Resp(conteudo="não é json")]
    prov.roteiro["reserva:free"] = [Resp(conteudo=json.dumps(resposta_certa()))]
    r = P.pedir(layout_novo())
    assert r.modelo == "openrouter:reserva:free" and r.dados["valor_total_frete"] == "196,40"
    assert [x["funcao"] for x in registros] == ["proposta Della Volpe"] * 2
    assert "TOTAL A PAGAR" in prov.pedidos[0][2]["messages"][1]["content"]


# ------------------------------------------------------ o e-mail inteiro
@pytest.fixture
def banco(tmp_path):
    from core.banco import Banco
    return Banco(tmp_path / "t.db")


def test_email_com_layout_novo_vira_preco_pela_ia(banco, tmp_path, monkeypatch, ligada):
    cid = banco.salvar_cotacao("enzo", CARGA)
    monkeypatch.setattr(P, "pedir", _ia(resposta_certa(cid=cid), "groq:openai/gpt-oss-120b"))
    d = ingestor.processar(email_bruto(layout_novo(cid)), banco, gravar=True, pasta=tmp_path / "pdf")
    assert d.desfecho == "gravado", d.detalhe
    assert "lido pela IA (groq:openai/gpt-oss-120b): valor, cotacao_id" in d.detalhe
    r = next(r for r in banco.buscar_cotacao(cid, "enzo")["resultados"]
             if r["transportadora"] == "dellavolpe")
    assert r["valor"] == Decimal("196.40") and r["prazo"] == "6" and r["validade"] == date(2026, 9, 29)


def test_rota_diferente_continua_barrando_mesmo_lido_pela_ia(banco, tmp_path, monkeypatch, ligada):
    cid = banco.salvar_cotacao("enzo", CARGA)   # a cotação é MG → ES
    texto = layout_novo(cid, origem="SAO PAULO/SP")
    monkeypatch.setattr(P, "pedir", _ia(resposta_certa(cid=cid, uf_origem="SP")))
    d = ingestor.processar(email_bruto(texto), banco, gravar=True, pasta=tmp_path / "pdf")
    assert d.desfecho == "rota_diferente"
    assert not [r for r in banco.buscar_cotacao(cid, "enzo")["resultados"]
                if r["transportadora"] == "dellavolpe" and r["valor"]]


def test_ia_mentirosa_nao_grava_nada(banco, tmp_path, monkeypatch, ligada):
    cid = banco.salvar_cotacao("enzo", CARGA)
    monkeypatch.setattr(P, "pedir", _ia(resposta_certa(cid=cid, valor_total_frete="150,00",
                                                     linha_do_valor="TOTAL: R$ 150,00")))
    d = ingestor.processar(email_bruto(layout_novo(cid)), banco, gravar=True, pasta=tmp_path / "pdf")
    assert d.desfecho == "sem_valor"
    assert not list((tmp_path / "pdf").glob("**/*.pdf"))


def test_sem_plano_b_o_mesmo_email_se_perde(banco, tmp_path):
    """Com a IA desligada (padrão dos testes) o comportamento é o de antes."""
    cid = banco.salvar_cotacao("enzo", CARGA)
    d = ingestor.processar(email_bruto(layout_novo(cid)), banco, gravar=True, pasta=tmp_path / "pdf")
    assert d.desfecho in ("sem_valor", "sem_carimbo")
