"""A tela de UMA cotação no painel: /adm/cotacao/{id}.

É a porta que faltava. Até 04/09/2026 o histórico do painel listava as
cotações da empresa inteira e nenhuma linha era clicável: `/cotacao/{id}` é a
rota do VENDEDOR, exige o cookie dele e filtra por dono — clicar ali jogava
para /login, ou dava 404 numa cotação que a própria tela tinha acabado de
listar.

Os dois riscos que estes testes seguram:

1. **A porta nova não pode afrouxar a antiga.** O adm passa a ver tudo; o
   vendedor continua vendo só o dele. As duas coisas são testadas juntas de
   propósito — foi um `if adm` no meio de uma consulta só que o desenho do
   painel decidiu não fazer.
2. **Tudo nesta tela vem de fora.** Nome de vendedor (o login é placeholder),
   material, texto de erro do site da transportadora. Tudo desemboca no HTML
   de quem administra.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from web import adm, app as app_web

SENHA = "senha-de-teste-123"
CARGA = {"cep_origem": "29105770", "cep_destino": "01310100",
         "cidade_origem": "Vila Velha", "uf_origem": "ES",
         "cidade_destino": "São Paulo", "uf_destino": "SP",
         "peso_kg": "36", "quantidade": 3, "comprimento_cm": 30,
         "largura_cm": 40, "altura_cm": 25, "valor_nf": "12345.67",
         "material": "PLACA DE VIDEO", "tipo_frete": "cif",
         "cnpj_remetente": "60.042.686/0001-05",
         "nome_remetente": "VENTURA INFORMATICA LTDA"}


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))
    c = TestClient(app_web.app)
    c.cookies.set(adm.COOKIE_ADM, adm.token_de(SENHA))
    return c


# ------------------------------------------------------------- quem entra

def test_sem_senha_no_ambiente_a_rota_nem_existe(monkeypatch, tmp_path):
    """Mesma regra do resto do painel: sem COTAFRETE_ADM_SENHA a tela não
    existe, e não é só protegida."""
    monkeypatch.delenv("COTAFRETE_ADM_SENHA", raising=False)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))

    r = TestClient(app_web.app).get("/adm/cotacao/1", follow_redirects=False)

    assert r.status_code == 404


def test_sem_cookie_cai_na_tela_de_senha(monkeypatch, tmp_path):
    """A tela traz CNPJ, razão social e valor de nota. Não pode ser porta dos
    fundos para quem não passou pela senha."""
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))
    cid = adm.banco.salvar_cotacao("leandro", CARGA)

    r = TestClient(app_web.app).get(f"/adm/cotacao/{cid}",
                                    follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/adm/entrar"


def test_cookie_forjado_tambem_nao_entra(monkeypatch, tmp_path):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))
    c = TestClient(app_web.app)
    c.cookies.set(adm.COOKIE_ADM, "sim")

    assert c.get("/adm/cotacao/1", follow_redirects=False).status_code == 303


# --------------------------------------------------------- o que ela abre

def test_o_adm_abre_a_cotacao_de_outro_vendedor(cliente):
    """O ponto da tela inteira."""
    cid = adm.banco.salvar_cotacao("leandro", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("123.45"), prazo="3 dias",
                               protocolo="998877")

    html = cliente.get(f"/adm/cotacao/{cid}").text

    assert "leandro" in html
    assert "123,45" in html
    assert "998877" in html


def test_o_vendedor_continua_sem_ver_a_do_colega(cliente):
    """A porta nova não afrouxou a antiga: a mesma cotação que o adm abre
    continua fechada para o vendedor errado."""
    cid = adm.banco.salvar_cotacao("leandro", CARGA)
    vendedor = TestClient(app_web.app)
    vendedor.cookies.set(app_web.COOKIE, "enzo")
    # A tela do vendedor usa o banco de web.app, não o do painel — o que
    # importa aqui é que ela NÃO abre a cotação de outro, e 404 é isso.
    assert cliente.get(f"/adm/cotacao/{cid}").status_code == 200
    assert vendedor.get(f"/cotacao/{cid}").status_code == 404


def test_numero_que_nao_existe_da_404_com_caminho_de_volta(cliente):
    """404 de verdade, e não uma tela em branco: quem chegou por um link
    velho precisa voltar para algum lugar."""
    r = cliente.get("/adm/cotacao/4242")

    assert r.status_code == 404
    assert 'href="/adm"' in r.text


def test_a_linha_do_historico_leva_para_a_tela_da_cotacao(cliente):
    """O link que faltava. Precisa apontar para a rota do ADM — apontar para
    /cotacao/{id} era o bug que deixou a linha sem link por semanas."""
    cid = adm.banco.salvar_cotacao("leandro", CARGA)

    html = cliente.get("/adm").text

    assert f'href="/adm/cotacao/{cid}"' in html
    assert f'href="/cotacao/{cid}"' not in html


# ------------------------------------------------- o que a tela mostra

def test_o_mais_barato_ganha_o_selo(cliente):
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("150.00"))
    adm.banco.salvar_resultado(cid, "braspress", status="cotado",
                               valor=Decimal("90.50"))

    html = cliente.get(f"/adm/cotacao/{cid}").text

    assert "MAIS BARATO" in html
    assert html.count("MAIS BARATO") == 1


def test_preco_por_volume_nao_disputa_o_selo(cliente):
    """A MESMA regra da tela do vendedor, agora com a mesma lista
    (transportadoras.cota_por_volume). Se as duas discordassem, o adm
    cobraria a transportadora errada por um preço que nunca foi o mais
    barato: R$ 33,29 por volume não é mais barato que R$ 69,91 pela carga
    quando são 3 volumes."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)   # 3 volumes
    adm.banco.salvar_resultado(cid, "jadlog", status="cotado",
                               valor=Decimal("33.29"))
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("69.91"))

    html = cliente.get(f"/adm/cotacao/{cid}").text

    # O selo é da Camilo, e a Jadlog vem com o aviso da estimativa.
    assert "R$ 69,91 <span class=\"selo\">MAIS BARATO</span>" in html
    assert "R$ 99,87" in html


def test_o_texto_tecnico_do_erro_aparece_inteiro(cliente):
    """A tela do vendedor corta em 400 caracteres para não despejar stack
    trace em cima de quem quer um preço. Esta é a tela de investigar."""
    enorme = "TimeoutError: " + "x" * 600
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "generoso", status="erro", erro=enorme)

    assert enorme in cliente.get(f"/adm/cotacao/{cid}").text


def test_a_ficha_da_carga_e_a_mesma_do_vendedor(cliente):
    """Uma cópia em cada tela funcionaria hoje e mentiria no primeiro dia em
    que alguém corrigisse um rótulo de um lado só."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)

    html = cliente.get(f"/adm/cotacao/{cid}").text

    assert "R$ 12.345,67" in html          # valor da nota, com milhar
    assert "3 × 12 kg cada" in html        # peso total x peso por volume
    assert "CIF — paga o remetente" in html


def test_o_tempo_de_resposta_aparece_quando_ha_hora_guardada(cliente):
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    with adm.banco._conectar() as con:
        criado = con.execute("SELECT criado_em FROM cotacao WHERE id = ?",
                             (cid,)).fetchone()[0]
    respondeu = datetime.fromisoformat(criado) + timedelta(seconds=25)
    adm.banco.salvar_resultado(
        cid, "camilo", status="cotado", valor=Decimal("10"),
        respondido_em=respondeu.isoformat(timespec="seconds"))

    assert "25 s" in cliente.get(f"/adm/cotacao/{cid}").text


def test_cotacao_antiga_sem_hora_de_resposta_nao_finge_zero(cliente):
    """`respondido_em` é NULL nas linhas anteriores a 28/08/2026. Zero ali
    inventaria a transportadora mais rápida do sistema."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("10"))

    html = cliente.get(f"/adm/cotacao/{cid}").text

    assert "sem dados ainda" in html
    assert "0 s" not in html


def test_a_tela_diz_quais_whatsapps_foram_abertos(cliente):
    """"Aberta", nunca "enviada": daqui em diante quem age é a pessoa."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.marcar_whatsapp_aberto(cid, "movvi", "enzo")

    html = cliente.get(f"/adm/cotacao/{cid}").text

    assert "Movvi Logística" in html
    assert "aberta não é enviada" in html


def test_cotacao_sem_resposta_nenhuma_nao_quebra(cliente):
    """Recém-criada, ninguém respondeu ainda."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)

    r = cliente.get(f"/adm/cotacao/{cid}")

    assert r.status_code == 200
    assert "Nenhuma transportadora respondeu ainda" in r.text


def test_a_tela_nao_puxa_nada_da_internet(cliente):
    """O Servidor.bat sobe numa máquina da empresa, e a tela precisa abrir
    com a internet caída."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("10"))

    html = cliente.get(f"/adm/cotacao/{cid}").text

    assert "http://" not in html
    assert "https://" not in html


def test_nada_que_vem_de_fora_vira_marcacao_na_tela(cliente):
    """Nome de vendedor (o login é placeholder), material e o texto de erro
    do site da transportadora: os três vêm de fora e desembocam aqui."""
    veneno = "<script>alert(1)</script>"
    cid = adm.banco.salvar_cotacao(veneno, {**CARGA, "material": veneno})
    adm.banco.salvar_resultado(cid, "camilo", status="erro", erro=veneno)

    html = cliente.get(f"/adm/cotacao/{cid}").text

    assert veneno not in html
    assert "<script>alert" not in html
