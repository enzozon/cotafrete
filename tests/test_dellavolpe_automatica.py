"""A Della Volpe entrando no rodizio das automaticas.

Ate 25/08/2026 ela era a unica transportadora validada que NAO cotava
sozinha: o envio real exigia janela visivel e caia como spam. Isso caiu — a
janela agora roda fora da tela e dois envios reais foram aceitos.

O que estes testes travam:

1. Entrar em AUTOMATICAS e esquecer a fabrica. `fabricas[slug]` morava
   DENTRO do handler /cotar, entao nada obrigava as duas listas a
   concordarem. Um slug sem fabrica so estoura no EXECUTOR, numa thread, e
   o cartao fica "cotando..." para sempre — o mesmo desaparecimento
   silencioso que ja custou cinco envios neste projeto.

2. O cartao mentir sobre o prazo. A Della Volpe responde em minutos; a
   Generoso, quando cai neste ramo, responde em horas. Um numero so para as
   duas manda o vendedor desistir cedo de uma e esperar demais pela outra.

3. O e-mail do site nao ser o e-mail do formulario. E o unico caminho pelo
   qual o preco chega: errar isso manda a cotacao para a caixa de outra
   pessoa, e ninguem descobre — a tela diz "enviada" do mesmo jeito.
"""

from __future__ import annotations

import pytest

import monitorar
from web import app as app_web

SLUG = "dellavolpe"


# ------------------------------------------------- ela esta ligada mesmo
def test_dellavolpe_saiu_das_automaticas():
    """Invertido em 31/08/2026. O site dela passou a exigir "confirme que e
    humano" (Cloudflare Turnstile) e o envio automatico deixou de gerar
    e-mail. Ver tests/test_dellavolpe_assistida.py para o fluxo novo.

    O arquivo continua existindo porque o que ele protege — a coerencia entre
    AUTOMATICAS, FABRICAS e o monitor, e a trava SEM_REPETICAO — vale para as
    quatro que ficaram, e voltaria a valer para ela."""
    assert SLUG not in app_web.AUTOMATICAS


def test_o_monitor_enxerga_as_mesmas_automaticas():
    """Listas separadas ja divergiram: a do monitor parou em
    ("camilo", "jadlog") quando a Translovato entrou."""
    assert tuple(monitorar.AUTOMATICAS) == tuple(app_web.AUTOMATICAS)


# ------------------------------- quem entra na lista tem que ser despachavel
def test_toda_automatica_tem_fabrica():
    """O erro que este arquivo existe para impedir.

    Sem isto, acrescentar um slug em AUTOMATICAS compila, sobe, e so falha
    quando um vendedor cota — dentro de uma thread do executor, onde o
    KeyError vira um cartao girando."""
    faltando = [s for s in app_web.AUTOMATICAS if s not in app_web.FABRICAS]

    assert not faltando, f"em AUTOMATICAS sem fabrica: {faltando}"


def test_nenhuma_fabrica_orfa():
    """O outro sentido: fabrica de quem nao esta na lista nunca roda."""
    sobrando = [s for s in app_web.FABRICAS if s not in app_web.AUTOMATICAS]

    assert not sobrando, f"fabrica sem entrada em AUTOMATICAS: {sobrando}"


def test_toda_automatica_tem_nome_e_nota():
    """O cartao usa os dois. Slug sem nome aparece como slug cru na tela."""
    for slug in app_web.AUTOMATICAS:
        assert app_web.NOMES.get(slug), f"{slug} sem nome"
        assert app_web.NOTAS.get(slug), f"{slug} sem nota"


def test_a_nota_da_dellavolpe_continua_explicando_o_e_mail():
    """Ela saiu das automaticas, mas o NOME e a NOTA seguem em uso: o cartao
    de "Precisa de voce" e a Documentacao leem os dois. Nota vazia deixaria a
    tela mostrando slug cru."""
    assert app_web.NOMES[SLUG]
    assert "-mail" in app_web.NOTAS[SLUG]


# --------------------------------------------------------- o cartao da tela
def test_sem_prazo_cadastrado_o_cartao_nao_promete_prazo():
    """ESPERA_DO_EMAIL ficou VAZIO em 31/08/2026: nada mais e enviado
    sozinho, entao nao ha prazo honesto a prometer. O mecanismo continua —
    quem entrar nele volta a ter prazo no cartao."""
    html = app_web.cartao_resposta_por_email("a@b.com", "dellavolpe")

    assert "A resposta costuma chegar" not in html
    assert "minutos" not in html


def test_o_cartao_nomeia_o_email_digitado_no_formulario():
    html = app_web.cartao_resposta_por_email("arthur@ventura.com.br", SLUG)

    assert "arthur@ventura.com.br" in html


def test_o_cartao_manda_abrir_o_email():
    """Pedido do Enzo, com estas tres informacoes: foi para o e-mail que voce
    digitou, va olhar la, e o prazo."""
    html = app_web.cartao_resposta_por_email("arthur@ventura.com.br", SLUG)

    assert "spam" in html.lower()
    assert "formulário" in html


def test_o_cartao_da_generoso_nao_promete_o_prazo_da_dellavolpe():
    """A Generoso responde por vendedor, em horas. Herdar "2 a 5 minutos"
    faria o vendedor dar a cotacao por perdida em cinco minutos."""
    html = app_web.cartao_resposta_por_email("arthur@ventura.com.br",
                                             "generoso")

    assert "costuma chegar" not in html


def test_sem_email_guardado_o_cartao_ainda_faz_sentido():
    """Cotacoes anteriores a 20/08/2026 nao tem e-mail na coluna.

    Sem e-mail o cartao fala do "e-mail que voce digitou" em vez de nomear
    um; o que nao pode e a palavra None vazar para a tela do vendedor."""
    html = app_web.cartao_resposta_por_email(None, SLUG)

    assert "None" not in html
    assert "e-mail que você digitou" in html


def test_email_no_cartao_sai_escapado():
    """O e-mail vem do formulario. Sem escapar, ele injeta HTML na tela."""
    html = app_web.cartao_resposta_por_email('a"><script>x()</script>@b.com',
                                             SLUG)

    assert "<script>" not in html


# -------------------------------------- o e-mail do formulario chega ao site
def test_o_email_do_formulario_e_o_que_vai_no_campo_do_site():
    """A ligacao inteira em um assert: o que o vendedor digitou e o que a
    Della Volpe vai usar para responder."""
    from carriers.dellavolpe import mapping
    from core.models import Solicitante
    from tests.test_dellavolpe_mapping import montar

    digitado = "vendas2@venturainformatica.com.br"
    req = montar(solicitante=Solicitante(nome="Prova", email=digitado,
                                         whatsapp="27999887766"))

    payload = mapping.preparar_payload(req)

    assert payload["E-mail"] == digitado


# ------------------------------------------- repetir a DV custa uma PESSOA
def test_a_dellavolpe_nao_e_repetida():
    """O risco que so ela tem.

    `vale_repetir` manda tentar de novo sempre que o status e ERRO — e ERRO
    inclui "Confirmacao de envio nao identificada na resposta", que a
    Della Volpe devolve quando o site ACEITOU o envio e a nossa leitura da
    resposta e que falhou. Repetir ali coloca uma SEGUNDA cotacao na fila de
    um vendedor de verdade, por um unico clique do nosso lado.

    As outras quatro sao auto-servico: repetir la nao incomoda ninguem, so
    gasta uma vaga de navegador. Por isso a excecao e nominal e nao uma
    regra geral."""
    from core.retentativa import SEM_REPETICAO

    assert "dellavolpe" in SEM_REPETICAO


def test_so_a_dellavolpe_perde_a_repeticao():
    """A repeticao salvou cotacoes reais (a Translovato na rodada de
    24/08/2026). Nao pode ser desligada por tabela."""
    from core.retentativa import SEM_REPETICAO

    assert set(SEM_REPETICAO) == {"dellavolpe"}


def test_sem_repeticao_o_envio_acontece_uma_vez_so(monkeypatch):
    """Prova de comportamento, nao de configuracao: mesmo devolvendo ERRO
    tres vezes seguidas, o formulario so e enviado uma."""
    from carriers.base import ResultadoCotacao
    from core import retentativa
    from core.models import StatusCotacao

    envios = []

    def cotar_fn(req):
        envios.append(1)
        return ResultadoCotacao("dellavolpe", StatusCotacao.ERRO,
                                erro="Confirmação de envio não identificada.")

    monkeypatch.setattr(retentativa, "PAUSA_ENTRE_TENTATIVAS_S", 0)
    res = retentativa.cotar_com_retentativa(cotar_fn, None, repetir=False)

    assert len(envios) == 1
    assert res.status is StatusCotacao.ERRO


def test_quem_pode_repetir_continua_repetindo(monkeypatch):
    """A trava nao pode vazar para as outras quatro."""
    from carriers.base import ResultadoCotacao
    from core import retentativa
    from core.models import StatusCotacao

    tentativas = []

    def cotar_fn(req):
        tentativas.append(1)
        return ResultadoCotacao("camilo", StatusCotacao.ERRO, erro="rede")

    monkeypatch.setattr(retentativa, "PAUSA_ENTRE_TENTATIVAS_S", 0)
    retentativa.cotar_com_retentativa(cotar_fn, None)

    assert len(tentativas) == retentativa.TENTATIVAS_MAXIMAS


def test_excecao_tambem_nao_repete_a_dellavolpe(monkeypatch):
    """O outro caminho: se o navegador cair DEPOIS do submit, a cotacao ja
    esta na fila do vendedor. Tentar de novo poe a segunda."""
    from core import retentativa

    envios = []

    def cotar_fn(req):
        envios.append(1)
        raise RuntimeError("navegador caiu")

    monkeypatch.setattr(retentativa, "PAUSA_ENTRE_TENTATIVAS_S", 0)
    with pytest.raises(RuntimeError):
        retentativa.cotar_com_retentativa(cotar_fn, None, repetir=False)

    assert len(envios) == 1


# ------------------------------------------------- vaga para todas as cinco
def test_o_executor_aceita_todas_as_automaticas_de_uma_vez():
    """Com 4 vagas e 5 automaticas, a quinta da fila nao era nem ACEITA — ela
    esperava uma thread livre em vez de esperar vaga de navegador, e a
    Della Volpe e justamente a ultima da lista. Com duas cotacoes ao mesmo
    tempo ela poderia nem comecar antes de a tela desistir aos 300s.

    O semaforo de NAVEGADORES_SIMULTANEOS e que limita o peso na maquina; o
    executor so precisa aceitar todo mundo."""
    assert app_web.EXECUTOR._max_workers >= len(app_web.AUTOMATICAS)
