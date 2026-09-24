"""Resumo do dia no /adm (core/resumo_erros.py): os erros de hoje em português.

Três coisas travadas aqui:
1. os FATOS saem certos de cada fonte (transportadoras, leitura do ME,
   eventos do ME, e-mails da Della Volpe, IA) — é o que aparece mesmo sem IA;
2. a IA não inventa número: resposta com uma quantidade que não está nos
   fatos é recusada e a cadeia passa ao próximo modelo;
3. a tela: abrir o /adm não chama a IA; o botão chama, guarda e mostra.
"""

from __future__ import annotations

import json
from contextlib import closing
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from core import ia, resumo_erros as RE
from core.banco import Banco
from tests.test_ia import Provedor, Resp
from web import adm
from web import app as app_web

SENHA = "senha-de-teste-123"
HOJE = date.today()
CARGA = {"cep_origem": "29100000", "cep_destino": "01310100", "peso_kg": "10", "quantidade": 1,
         "comprimento_cm": 30, "largura_cm": 30, "altura_cm": 30, "valor_nf": "100",
         "material": "PECAS"}
CEP_FORA = "A Generoso não atende o CEP de destino 01310100 (fora de área)."
LOGIN = "Timeout 30000ms exceeded. waiting for locator(\"#login\")"


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def _falhas(banco, slug, erro, vezes, hora="14:10"):
    for _ in range(vezes):
        cid = banco.salvar_cotacao("enzo", CARGA)
        banco.salvar_resultado(cid, slug, status="erro", erro=erro,
                               respondido_em=f"{HOJE.isoformat()}T{hora}:00")


def _me(banco, conta="uniao", numero=23052403):
    with closing(banco._conectar()) as con, con:
        con.execute("INSERT INTO me_cotacao (conta, numero, status) VALUES (?, ?, 'pendente')",
                    (conta, numero))
        return con.execute("SELECT id FROM me_cotacao WHERE numero = ?", (numero,)).fetchone()[0]


def _fatos(banco):
    with closing(banco._conectar()) as con:
        return RE.fatos_do_dia(con, HOJE, lambda s: s.title())


# ------------------------------------------------------------------ fatos
def test_dia_sem_erro_nao_tem_problema(banco):
    cid = banco.salvar_cotacao("enzo", CARGA)
    banco.salvar_resultado(cid, "jadlog", status="cotado")
    assert not RE.tem_problema(_fatos(banco))


def test_falhas_da_transportadora_agrupadas_por_mensagem_mesmo_com_cep_diferente(banco):
    _falhas(banco, "generoso", CEP_FORA, 3)
    _falhas(banco, "generoso", CEP_FORA.replace("01310100", "04538133"), 2, hora="15:40")
    _falhas(banco, "generoso", LOGIN, 1, hora="09:05")
    [g] = _fatos(banco)["transportadoras"]
    assert (g["transportadora"], g["falhas"], g["cotacoes"]) == ("Generoso", 6, 6)
    assert g["erros"][0]["vezes"] == 5 and g["erros"][0]["horas"] == ["14h", "15h"]
    assert g["erros"][1]["vezes"] == 1 and g["erros"][1]["horas"] == ["9h"]


def test_transportadora_sem_falha_nao_entra(banco):
    cid = banco.salvar_cotacao("enzo", CARGA)
    banco.salvar_resultado(cid, "jadlog", status="recusado", erro="peso acima do limite")
    assert _fatos(banco)["transportadoras"] == []


def test_leitura_do_me_e_eventos_de_problema(banco):
    banco.me_registrar_varredura("uniao", ok=True, cotacoes=1)
    banco.me_registrar_varredura("uniao", ok=False, erro="TimeoutError: a lista do ME não respondeu")
    banco.me_registrar_varredura("uniao", ok=False, erro="TimeoutError: a lista do ME não respondeu")
    cid = _me(banco)
    banco.me_registrar(cid, "erro do robô", "campo NCM1 não existe na página")
    banco.me_registrar(cid, "salvo no ME", "ok")          # não é problema
    f = _fatos(banco)
    [leitura] = f["leitura_mercado_eletronico"]
    assert (leitura["conta"], leitura["leituras"], leitura["falhas"]) == ("UNIÃO", 3, 2)
    [evento] = f["problemas_mercado_eletronico"]
    assert evento["evento"] == "erro do robô" and evento["vezes"] == 1
    assert evento["cotacoes_me"] == [23052403]


def test_email_da_della_volpe_sem_preco_entra_e_gravado_nao(banco):
    banco.registrar_email("<a@dv>", "dellavolpe", desfecho="sem_valor",
                          detalhe="o PDF não traz 'VALOR TOTAL DO FRETE'")
    banco.registrar_email("<b@dv>", "dellavolpe", desfecho="gravado", cotacao_id=1, detalhe="R$ 196,40")
    [e] = _fatos(banco)["emails_della_volpe_sem_preco"]
    assert (e["desfecho"], e["vezes"]) == ("sem_valor", 1)


def test_resumo_sem_ia_junta_as_horas_de_todas_as_mensagens(banco):
    """Achado da prova com o banco real: "sem carimbo 2× (10h)" escondia o das 13h."""
    with closing(banco._conectar()) as con, con:
        for mid, detalhe, hora in (("<a>", "A/C: FULANO", "10:05"), ("<b>", "A/C: BELTRANO", "13:20")):
            con.execute("INSERT INTO email_processado (message_id, transportadora, cotacao_id, desfecho,"
                        " detalhe, processado_em) VALUES (?, 'dellavolpe', NULL, 'sem_carimbo', ?, ?)",
                        (mid, detalhe, f"{HOJE.isoformat()}T{hora}:00"))
    [linha] = RE.resumo_sem_ia(_fatos(banco))
    assert linha == "Della Volpe — e-mail sem preço (sem_carimbo): 2× (10h a 13h)."


def test_assunto_de_email_em_mime_vira_texto(banco):
    """Achado da prova com o banco real: o ingestor grava o Subject cru."""
    banco.registrar_email("<c>", "dellavolpe", desfecho="sem_pdf",
                          detalhe="=?utf-8?b?Q290YcOnw6Nv?= Della Volpe")
    [e] = _fatos(banco)["emails_della_volpe_sem_preco"]
    assert e["detalhes"][0]["erro"] == "Cotação Della Volpe"


def test_ia_so_entra_quando_falhou_mais_do_que_respondeu(banco):
    # a cadeia grátis: um modelo no limite e o próximo responde é o normal
    banco.ia_registrar(funcao="revisão ME", modelo="groq:a", ok=False, erro="limite por minuto atingido")
    banco.ia_registrar(funcao="revisão ME", modelo="groq:b", ok=True)
    for _ in range(3):
        banco.ia_registrar(funcao="preencher cotação", modelo="groq:a", ok=False, erro="limite diário atingido")
    [f] = _fatos(banco)["ia_com_falhas"]
    assert (f["funcao"], f["falhas"], f["tentativas"]) == ("preencher cotação", 3, 3)


def test_resumo_sem_ia_sai_so_dos_fatos(banco):
    _falhas(banco, "generoso", CEP_FORA, 5)
    banco.me_registrar_varredura("uniao", ok=False, erro="TimeoutError")
    linhas = RE.resumo_sem_ia(_fatos(banco))
    assert linhas[0].startswith("Generoso: 5 falha(s) em 5 resultado(s)") and "5× (14h)" in linhas[0]
    assert linhas[1].startswith("Leitura do ME (UNIÃO): 1 de 1 falharam")


# -------------------------------------------------------------- a IA
@pytest.fixture
def prov(monkeypatch):
    p = Provedor()
    monkeypatch.setattr(ia, "POST", p)
    monkeypatch.setattr(ia, "_castigo", {})
    monkeypatch.setattr(ia, "REGISTRO", None)
    monkeypatch.setenv("IA_MODELOS", "groq:melhor,openrouter:reserva:free")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "y")
    return p


def _resumo(qtd=5, gravidade="atencao"):
    return json.dumps({"manchete": f"A Generoso falhou {qtd} vezes hoje por CEP fora de área.",
                       "itens": [{"gravidade": gravidade,
                                  "texto": f"A Generoso falhou {qtd} vezes às 14h: o CEP de destino "
                                           "fica fora da área que ela atende.",
                                  "o_que_fazer": "Cote essas rotas com outra transportadora."}]})


def test_ia_que_inventa_numero_e_recusada_e_o_proximo_modelo_responde(banco, prov):
    _falhas(banco, "generoso", CEP_FORA, 5)
    prov.roteiro["melhor"] = [Resp(conteudo=_resumo(qtd=7))]       # 7 não existe nos fatos
    prov.roteiro["reserva:free"] = [Resp(conteudo=_resumo(qtd=5))]
    r = RE.pedir_resumo(_fatos(banco))
    assert r.modelo == "openrouter:reserva:free"
    assert "números que não estão nos fatos" in r.tentativas[0]
    assert r.dados["itens"][0]["texto"].startswith("A Generoso falhou 5 vezes")


def test_gravidade_fora_da_lista_e_recusada(banco, prov):
    _falhas(banco, "generoso", CEP_FORA, 5)
    prov.roteiro["melhor"] = [Resp(conteudo=_resumo(gravidade="urgentíssimo"))]
    prov.roteiro["reserva:free"] = [Resp(conteudo=_resumo())]
    assert RE.pedir_resumo(_fatos(banco)).modelo == "openrouter:reserva:free"


def test_o_pedido_leva_os_fatos_e_o_nome_da_funcao(banco, prov, monkeypatch):
    registros = []
    monkeypatch.setattr(ia, "REGISTRO", lambda **kw: registros.append(kw))
    _falhas(banco, "generoso", CEP_FORA, 5)
    prov.roteiro["melhor"] = [Resp(conteudo=_resumo())]
    RE.pedir_resumo(_fatos(banco))
    assert "fora de área" in prov.pedidos[0][2]["messages"][1]["content"]
    assert registros[0]["funcao"] == "resumo de erros"


def test_gerar_guarda_e_sabe_quando_ficou_velho(banco, prov):
    _falhas(banco, "generoso", CEP_FORA, 5)
    prov.roteiro["melhor"] = [Resp(conteudo=_resumo())]
    with closing(banco._conectar()) as con:
        g = RE.gerar(con, HOJE, agora=datetime(2026, 9, 24, 17, 30))
        assert g["modelo"] == "groq:melhor" and g["gerado_em"] == "2026-09-24T17:30:00"
        assert g["assinatura"] == RE.assinatura(RE.fatos_do_dia(con, HOJE))
    _falhas(banco, "generoso", CEP_FORA, 1)
    with closing(banco._conectar()) as con:
        assert RE.guardado(con, HOJE)["assinatura"] != RE.assinatura(RE.fatos_do_dia(con, HOJE))


def test_dia_limpo_nem_chama_a_ia(banco, prov):
    with closing(banco._conectar()) as con:
        g = RE.gerar(con, HOJE)
    assert prov.pedidos == [] and g["itens"] == [] and g["modelo"] is None


# ------------------------------------------------------------------ a tela
@pytest.fixture
def cliente(monkeypatch, banco):
    monkeypatch.setattr(adm, "banco", banco)
    monkeypatch.setattr(app_web, "banco", banco)
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    c = TestClient(app_web.app)
    c.cookies.set(adm.COOKIE_ADM, adm.token_de(SENHA))
    return c


def test_painel_mostra_os_numeros_sem_chamar_a_ia(cliente, banco, prov):
    _falhas(banco, "generoso", CEP_FORA, 5)
    html = cliente.get("/adm").text
    assert "Resumo do dia" in html and "Os números do dia" in html
    assert "5 falha(s) em 5 resultado(s)" in html and "Explicar com IA" in html
    assert prov.pedidos == []


def test_botao_gera_guarda_e_mostra_o_resumo(cliente, banco, prov):
    _falhas(banco, "generoso", CEP_FORA, 5)
    prov.roteiro["melhor"] = [Resp(conteudo=_resumo())]
    r = cliente.post("/adm/resumo-ia", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/adm#resumo"
    html = cliente.get("/adm").text
    assert "A Generoso falhou 5 vezes hoje por CEP fora de área." in html
    assert "Atenção · A Generoso falhou 5 vezes às 14h" in html
    assert "O que fazer: Cote essas rotas com outra transportadora." in html
    assert "Gerar de novo" in html and len(prov.pedidos) == 1


def test_ia_fora_do_ar_volta_com_aviso_e_os_numeros(cliente, banco, prov):
    _falhas(banco, "generoso", CEP_FORA, 5)
    prov.roteiro["melhor"] = [Resp(status=500)]
    prov.roteiro["reserva:free"] = [Resp(status=429)]
    r = cliente.post("/adm/resumo-ia", follow_redirects=False)
    assert r.headers["location"] == "/adm?resumo_ia=indisponivel#resumo"
    html = cliente.get("/adm?resumo_ia=indisponivel").text
    assert "A IA não respondeu agora" in html and "5 falha(s)" in html


def test_resumo_escapa_html_vindo_da_ia(cliente, banco, prov):
    _falhas(banco, "generoso", CEP_FORA, 5)
    prov.roteiro["melhor"] = [Resp(conteudo=json.dumps({
        "manchete": "<script>alert('x')</script>", "itens": [
            {"gravidade": "info", "texto": "<b>x</b>", "o_que_fazer": "nada"}]}))]
    cliente.post("/adm/resumo-ia")
    html = cliente.get("/adm").text
    assert "<script>alert('x')</script>" not in html and "&lt;script&gt;" in html


def test_sem_login_de_adm_o_botao_nao_funciona(monkeypatch, banco, prov):
    monkeypatch.setattr(adm, "banco", banco)
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    r = TestClient(app_web.app).post("/adm/resumo-ia", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/adm/entrar"
    assert prov.pedidos == []
