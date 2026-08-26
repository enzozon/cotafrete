"""A aba de Documentacao.

Documentacao que descreve o sistema que EU IMAGINO e pior que documentacao
nenhuma: o vendedor confia nela e erra com confianca. Por isso os testes
daqui nao conferem "existe um texto bonito" — conferem que os numeros e as
regras citados na pagina saem do MESMO lugar de onde o sistema os tira.

Os dois que importam de verdade:

    test_os_numeros_saem_do_codigo        — 5, 14, 18, 1 kg, 1 cm
    test_toda_transportadora_documentada  — entrar em AUTOMATICAS e nao
                                            aparecer na ajuda

O segundo ja teria pego a Della Volpe: ela entrou no rodizio em 26/08/2026 e
nenhum texto da tela dizia que o preco dela chega por e-mail.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    return modulo


@pytest.fixture
def cliente(app_web):
    c = TestClient(app_web.app)
    c.cookies.set(app_web.COOKIE, "enzo")
    return c


@pytest.fixture
def texto(cliente):
    """A pagina sem as marcacoes — e o que o vendedor de fato le."""
    html = cliente.get("/documentacao").text
    return re.sub(r"<[^>]+>", " ", html)


# ------------------------------------------------------------- ela existe
def test_a_aba_abre(cliente):
    assert cliente.get("/documentacao").status_code == 200


def test_a_aba_aparece_no_menu_de_todas_as_telas(cliente):
    """De nada adianta a pagina existir se nao houver como chegar nela."""
    for rota in ("/", "/historico", "/documentacao"):
        assert '/documentacao"' in cliente.get(rota).text, f"sem link em {rota}"


def test_sem_login_manda_para_a_tela_de_entrar(app_web):
    """Mesma regra das outras telas: nada do sistema abre deslogado."""
    sem_cookie = TestClient(app_web.app)

    r = sem_cookie.get("/documentacao", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/login"


# ----------------------------------------- os numeros nao podem ser escritos
def test_os_numeros_saem_do_codigo(app_web, texto):
    """"todas as 17 transportadoras" ficou mentindo por semanas porque era
    frase escrita a mao. Aqui os numeros sao conferidos contra a fonte."""
    from core import retentativa

    assert str(len(app_web.AUTOMATICAS)) in texto
    assert str(len(app_web.transportadoras.com_whatsapp())) in texto
    assert str(len(app_web.TODAS_AS_SLUGS)) in texto
    assert str(retentativa.TENTATIVAS_MAXIMAS) in texto


def test_toda_transportadora_automatica_esta_documentada(app_web, texto):
    """Entrar no rodizio e nao aparecer na ajuda."""
    for slug in app_web.AUTOMATICAS:
        assert app_web.NOMES[slug] in texto, f"{slug} fora da documentacao"


def test_o_prazo_da_dellavolpe_e_o_mesmo_do_cartao(app_web, texto):
    """Dois lugares dizendo prazos diferentes e pior que um lugar so."""
    assert app_web.ESPERA_DO_EMAIL["dellavolpe"] in texto


def test_os_minimos_sao_os_que_a_validacao_usa(app_web, texto):
    assert f"{app_web.PESO_MINIMO_KG} kg" in texto
    assert f"{app_web.MEDIDA_MINIMA_CM} cm" in texto


# --------------------------------------------- o que o Enzo pediu por escrito
def test_explica_que_medida_e_em_centimetro(texto):
    """A armadilha mais cara do sistema: metro digitado em campo de cm cota
    uma carga 100x menor, calado."""
    assert "CENT" in texto.upper()
    assert "metro" in texto.lower()


def test_avisa_que_nada_pode_ser_zero(texto):
    assert "zero" in texto.lower()


def test_explica_que_o_peso_e_de_um_volume(texto):
    """Peso do lote no campo de peso unitario multiplica a carga pela
    quantidade."""
    assert "de um volume" in texto.lower() or "um volume" in texto.lower()


def test_explica_que_erro_vem_com_print(texto):
    assert "print" in texto.lower()


def test_explica_a_dellavolpe_por_email(app_web, texto):
    assert app_web.NOMES["dellavolpe"] in texto
    assert "spam" in texto.lower()


def test_explica_o_filtro_de_transportadoras(texto):
    assert "Escolher" in texto or "desmarc" in texto.lower()


def test_explica_a_mensagem_do_whatsapp(texto):
    """O ponto que mais confunde: "aberta" nao e "enviada"."""
    assert "WhatsApp" in texto
    assert "abert" in texto.lower()


def test_explica_o_preco_por_volume_da_jadlog(app_web, texto):
    for slug in app_web.COTAM_POR_VOLUME:
        assert app_web.NOMES[slug] in texto
    assert "por volume" in texto.lower()


def test_explica_cif_e_fob(texto):
    assert "CIF" in texto and "FOB" in texto


def test_explica_o_historico(texto):
    assert "hist" in texto.lower()


# ---------------------------------------- a conta tem que fechar na tela
def test_a_soma_das_listas_nao_confunde_o_leitor(app_web, texto):
    """5 automaticas + 14 de WhatsApp da 19, mas o total e 18: a Translovato
    esta nas DUAS listas.

    Dizer "e as OUTRAS 14" fazia o vendedor somar 19 e procurar uma
    transportadora que nao existe. A pagina precisa nomear quem se repete."""
    zap = {r.slug for r in app_web.transportadoras.com_whatsapp()}
    nas_duas = [s for s in app_web.AUTOMATICAS if s in zap]

    assert nas_duas, "se ninguem mais se repete, este teste perdeu o sentido"
    for slug in nas_duas:
        assert app_web.NOMES[slug] in texto
    assert str(len(app_web.TODAS_AS_SLUGS)) in texto
