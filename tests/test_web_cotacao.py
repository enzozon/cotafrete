"""A tela da cotação, no estado em que o usuário SEMPRE a vê primeiro.

Logo depois de enviar o formulário nenhuma transportadora respondeu ainda.
Esse é o caminho normal — e era exatamente ele que quebrava com HTTP 500,
porque a tela decidia "já desisti de esperar?" DEPOIS de desenhar os cartões
que dependem dessa resposta.

Os testes daqui batem na rota de verdade, com banco de verdade em pasta
temporária. Testar a função solta não pegaria o erro: ele só aparece quando
existe uma transportadora pendente.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco

CARGA = {
    "cep_origem": "29010-000", "cep_destino": "01310-100",
    "cidade_origem": "Vitória", "uf_origem": "ES",
    "cidade_destino": "São Paulo", "uf_destino": "SP",
    "peso_kg": "12", "quantidade": 3,
    "comprimento_cm": 80, "largura_cm": 60, "altura_cm": 50,
    "valor_nf": "1500.00", "material": "Bomba",
    # Com máscara porque é assim que /cotar grava (cnpj_formatado). O
    # fixture guardava 14 dígitos crus, que a tela nunca recebe na prática.
    "cnpj_remetente": "12.345.678/0001-90",
    "cnpj_destinatario": "98.765.432/0001-10",
    "cnpj_pagador": "12.345.678/0001-90", "nome_remetente": "Ventura",
    "nome_destinatario": "Cliente", "nome_pagador": "Ventura",
    # A Generoso responde por e-mail. Sem guardar o endereco, a tela final
    # nao tem como dizer ONDE o vendedor deve olhar.
    "email": "vendas@ventura.com.br",
}


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    """Banco isolado por teste: o histórico real do Enzo não entra aqui."""
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    return modulo


@pytest.fixture
def cliente(app_web):
    c = TestClient(app_web.app)
    c.cookies.set(app_web.COOKIE, "enzo")
    return c


def _criar(app_web, *, criado_em: str | None = None,
           email: str | None = None) -> int:
    carga = {**CARGA, "email": email} if email else CARGA
    cotacao_id = app_web.banco.salvar_cotacao("enzo", carga)
    if criado_em:
        with app_web.banco._conectar() as con:
            con.execute("UPDATE cotacao SET criado_em = ? WHERE id = ?",
                        (criado_em, cotacao_id))
    return cotacao_id


def test_tela_abre_com_todas_as_transportadoras_ainda_cotando(app_web, cliente):
    """O bug do 500: `desistiu` era lido antes de existir.

    Só quebrava quando faltava alguma transportadora — ou seja, em 100% das
    cotações recém-enviadas, e em nenhum teste que olhasse só o resultado
    pronto."""
    cotacao_id = _criar(app_web)

    resposta = cliente.get(f"/cotacao/{cotacao_id}")

    assert resposta.status_code == 200
    assert "cotando" in resposta.text
    assert 'http-equiv="refresh"' in resposta.text


def test_depois_do_teto_para_de_recarregar_e_avisa(app_web, cliente):
    """Passou o tempo máximo: assume que não vem mais e para de piscar."""
    velha = (datetime.now()
             - timedelta(seconds=app_web.ESPERA_MAXIMA_S + 60)).isoformat()
    cotacao_id = _criar(app_web, criado_em=velha)

    resposta = cliente.get(f"/cotacao/{cotacao_id}")

    assert resposta.status_code == 200
    assert "Sem retorno" in resposta.text
    assert "não responderam" in resposta.text
    assert 'http-equiv="refresh"' not in resposta.text


def test_cotacao_pronta_nao_recarrega(app_web, cliente):
    """Tudo respondido: recarregar faria a imagem piscar na cara de quem lê."""
    from decimal import Decimal

    cotacao_id = _criar(app_web)
    for slug in app_web.AUTOMATICAS:
        app_web.banco.salvar_resultado(cotacao_id, slug, status="cotado",
                                       valor=Decimal("69.91"))

    resposta = cliente.get(f"/cotacao/{cotacao_id}")

    assert resposta.status_code == 200
    assert 'http-equiv="refresh"' not in resposta.text
    assert "cotando…" not in resposta.text


def test_cotacao_de_outro_usuario_nao_abre(app_web, cliente):
    """Trocar o número na URL não pode dar acesso à cotação alheia."""
    cotacao_id = app_web.banco.salvar_cotacao("outra_pessoa", CARGA)

    assert cliente.get(f"/cotacao/{cotacao_id}").status_code == 404


def test_regex_da_mascara_chega_inteira_no_browser():
    """As regex do JS da máscara vivem dentro de uma f-string do Python.

    Sem prefixo `r`, `\\d` é sequência de escape inválida: hoje o Python só
    avisa, mas na versão em que isso virar erro o servidor não sobe. E se
    alguém "consertar" o aviso escapando errado, a máscara para de casar
    dígito e o CNPJ vai torto para a transportadora."""
    import inspect

    from web import app as modulo

    fonte = inspect.getsource(modulo._render_formulario)

    assert r"replace(/\D/g" in fonte
    assert r"/^(\d{{2}})(\d)/" in fonte


# --------------------------------------------------------------- ficha
# O Enzo pediu em 19/08/2026: a tela de resultado tem que mostrar os dados
# que geraram aquela cotação, depois dos botões de WhatsApp. Antes disso o
# vendedor via só os preços — e para conferir de onde vieram tinha que
# abrir o histórico e comparar de cabeça.
def test_ficha_mostra_o_que_foi_preenchido(app_web, cliente):
    html = cliente.get(f"/cotacao/{_criar(app_web)}").text

    for esperado in ("29010-000", "01310-100", "Vitória", "São Paulo",
                     "12.345.678/0001-90", "98.765.432/0001-10",
                     "Ventura", "Cliente", "Bomba"):
        assert esperado in html, f"a ficha não mostrou {esperado!r}"


def test_ficha_separa_peso_total_do_peso_por_volume(app_web, cliente):
    """CARGA são 3 volumes e 12 kg no TOTAL — 4 kg cada.

    O campo do formulário pede o peso de UM volume; o banco guarda o total.
    Escrever só "Peso: 12" deixa o vendedor sem saber qual dos dois é, e é
    esse número que ele redigita ao repetir a cotação."""
    html = cliente.get(f"/cotacao/{_criar(app_web)}").text

    assert "Peso total" in html
    assert "12" in html
    assert "4" in html          # o unitário, para conferir com a ficha


# ------------------------------------------- repetir sem inflar o peso (19/08)
def test_repetir_cotacao_devolve_o_peso_de_UM_volume(app_web, cliente):
    """BUG: `/cotar` grava req.peso_total_kg e `_valores_de` devolvia esse
    total para o campo "Peso de UM volume".

    Com 3 volumes de 4 kg (total 12), repetir preenchia 12 no campo unitário
    e a cotação seguinte saía com 36 kg — três vezes a carga real, sem aviso
    nenhum na tela, porque 36 kg é um peso perfeitamente válido. Repetindo de
    novo virava 108. Quanto maior a quantidade, maior o erro."""
    cotacao_id = _criar(app_web)

    html = cliente.get(f"/?repetir={cotacao_id}").text
    campo_peso = html.split('id="peso"')[1].split(">")[0]

    assert 'value="4"' in campo_peso, (
        f"o campo do peso unitário veio com {campo_peso!r} — "
        "o total de 12 kg voltaria multiplicado por 3 volumes")


def test_peso_quebrado_usa_virgula_como_o_resto_da_tela(app_web, cliente):
    """"12.5 kg" ao lado de "R$ 568,77" na mesma tela é o tipo de detalhe que
    faz o vendedor desconfiar do número — e desconfiar do peso é desconfiar
    do frete inteiro."""
    carga = {**CARGA, "peso_kg": "12.5", "quantidade": 1}
    html = cliente.get(f"/cotacao/{app_web.banco.salvar_cotacao('enzo', carga)}").text

    assert "12,5 kg" in html
    assert "12.5 kg" not in html


# ------------------------------------------- recusa que o vendedor entende
def test_recusa_da_transportadora_chega_na_tela(app_web, cliente):
    """BUG: `_rodar` gravava só `res.erro`, e os caminhos de recusa da
    Translovato preenchem `res.motivo_recusa`. A frase escrita para o
    vendedor era jogada fora e o cartão caía no genérico "o site respondeu:
    recusado" — exatamente o que essas mensagens existem para evitar."""
    from carriers.base import ResultadoCotacao
    from core.models import StatusCotacao

    cotacao_id = _criar(app_web)
    recusa = ResultadoCotacao(
        "translovato", StatusCotacao.RECUSADO,
        motivo_recusa="A Translovato só cota frete saindo da Ventura.")
    app_web._rodar(cotacao_id, "translovato", lambda _: recusa, None)

    html = cliente.get(f"/cotacao/{cotacao_id}").text

    assert "só cota frete saindo da Ventura" in html
    assert "o site respondeu" not in html


def test_recusa_longa_nao_e_cortada_no_meio_de_um_cnpj(app_web, cliente):
    """A mensagem da Translovato lista três CNPJs e passa de 180 caracteres.
    Cortar no meio de um CNPJ é pior que não mostrar: o vendedor copia um
    número incompleto."""
    from carriers.base import ResultadoCotacao
    from core.models import StatusCotacao

    from carriers.translovato import mapping as t
    frase = t.recusa_sem_tabela("60.042.686/0001-05")

    cotacao_id = _criar(app_web)
    app_web._rodar(cotacao_id, "translovato",
                   lambda _: ResultadoCotacao("translovato",
                                              StatusCotacao.RECUSADO,
                                              motivo_recusa=frase), None)
    html = cliente.get(f"/cotacao/{cotacao_id}").text

    for cnpj in t.CNPJS_REMETENTE_ACEITOS:
        assert cnpj in html, f"{cnpj} foi cortado da mensagem"


# --------------------------------------- Jadlog cota UM volume, nao a carga
def test_jadlog_avisa_que_o_preco_e_de_um_volume_so(app_web, cliente):
    """A calculadora da Jadlog cota um pacote (carriers/jadlog/painel.py).
    Ao lado da Camilo, que cota a carga inteira, o número dela parece o mais
    barato sem ser — e é assim que se fecha um frete pelo preço errado."""
    cotacao_id = _criar(app_web)                    # CARGA tem 3 volumes
    app_web.banco.salvar_resultado(cotacao_id, "jadlog",
                                   status="cotado", valor="33.29")
    app_web.banco.salvar_resultado(cotacao_id, "camilo",
                                   status="cotado", valor="69.91")

    html = cliente.get(f"/cotacao/{cotacao_id}").text

    assert "1 volume" in html, "faltou avisar que o preço é de um volume só"
    assert "99,87" in html, "faltou a estimativa dos 3 volumes (3 × 33,29)"


def test_jadlog_nao_leva_o_selo_de_mais_barato_com_varios_volumes(app_web,
                                                                  cliente):
    """R$ 33,29 por volume não é mais barato que R$ 69,91 pela carga toda —
    são 3 volumes, R$ 99,87. Coroar o número não comparável é o erro que a
    mensagem sozinha não impede."""
    cotacao_id = _criar(app_web)
    app_web.banco.salvar_resultado(cotacao_id, "jadlog",
                                   status="cotado", valor="33.29")
    app_web.banco.salvar_resultado(cotacao_id, "camilo",
                                   status="cotado", valor="69.91")

    html = cliente.get(f"/cotacao/{cotacao_id}").text
    cartao_jadlog = html.split("Jadlog")[1].split("</div></div>")[0]

    assert "MAIS BARATO" not in cartao_jadlog
    assert "MAIS BARATO" in html, "a Camilo devia ficar com o selo"


def test_com_um_volume_so_o_preco_da_jadlog_vale_e_disputa_normal(app_web,
                                                                  cliente):
    """Com 1 volume o preço dela É o da carga: nada de aviso nem de exclusão.
    Aviso que aparece sempre vira aviso que ninguém lê."""
    cotacao_id = app_web.banco.salvar_cotacao(
        "enzo", {**CARGA, "quantidade": 1, "peso_kg": "4"})
    app_web.banco.salvar_resultado(cotacao_id, "jadlog",
                                   status="cotado", valor="33.29")
    app_web.banco.salvar_resultado(cotacao_id, "camilo",
                                   status="cotado", valor="69.91")

    html = cliente.get(f"/cotacao/{cotacao_id}").text
    cartao_jadlog = html.split("Jadlog")[1].split("</div></div>")[0]

    assert "MAIS BARATO" in cartao_jadlog
    assert "estimativa" not in cartao_jadlog.lower()


def test_preco_de_um_volume_perde_o_verde_de_bom_preco(app_web, cliente):
    """O olho compara os números grandes antes de ler o aviso. Verde é a cor
    de "mais barato" nesta tela — num preço que não é da carga toda, ela
    contradiz o texto logo abaixo."""
    cotacao_id = _criar(app_web)                    # 3 volumes
    app_web.banco.salvar_resultado(cotacao_id, "jadlog",
                                   status="cotado", valor="33.29")
    app_web.banco.salvar_resultado(cotacao_id, "camilo",
                                   status="cotado", valor="69.91")

    html = cliente.get(f"/cotacao/{cotacao_id}").text
    jadlog = html.split("Jadlog")[1].split("</div></div>")[0]
    camilo = html.split("Camilo")[1].split("</div></div>")[0]

    assert 'class="valor incerto"' in jadlog
    assert 'class="valor"' in camilo, "a Camilo cota a carga toda: segue verde"


# ------------------------------------------------- WhatsApp: contagem de ABERTAS
# Decisão do Enzo em 19/08/2026. O rótulo é "abertas", nunca "enviadas": o
# sistema abre a conversa com o texto pronto, mas quem aperta enviar é a
# pessoa, do outro lado, e disso aqui não chega notícia nenhuma.
def test_clicar_no_whatsapp_registra_e_leva_para_a_conversa(app_web, cliente):
    cotacao_id = _criar(app_web)

    r = cliente.get(f"/whatsapp/{cotacao_id}/movvi", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"].startswith("https://wa.me/553194910111?text=")
    assert app_web.banco.whatsapp_abertos(cotacao_id) == {"movvi"}


def _texto(html: str) -> str:
    """Só o que o vendedor lê, sem as tags.

    A contagem tem um <b> no meio (o JS atualiza ele no clique), então "3 de
    14" nunca é contíguo no HTML. Testar o texto renderizado é testar o que
    a pessoa vê, e não sobrevive a mim mudando a marcação."""
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_a_tela_mostra_quantas_ja_foram_abertas(app_web, cliente):
    cotacao_id = _criar(app_web)
    for slug in ("movvi", "translovato", "coruja"):
        cliente.get(f"/whatsapp/{cotacao_id}/{slug}", follow_redirects=False)

    texto = _texto(cliente.get(f"/cotacao/{cotacao_id}").text)

    assert "3 de 14 abertas" in texto
    # A frase da tela explica a diferença e por isso usa as duas palavras.
    # O que não pode existir é a CONTAGEM dizendo "enviadas": o sistema não
    # sabe se foi enviado, e prometer isso é pior que não contar nada.
    assert "de 14 enviadas" not in texto


def test_transportadora_ja_aberta_fica_marcada_na_lista(app_web, cliente):
    cotacao_id = _criar(app_web)
    cliente.get(f"/whatsapp/{cotacao_id}/movvi", follow_redirects=False)

    html = cliente.get(f"/cotacao/{cotacao_id}").text
    linha_movvi = html.split("Movvi")[1].split("</a>")[0]

    assert "aberta" in linha_movvi.lower()


def test_transportadora_inventada_na_url_nao_redireciona_para_lugar_nenhum(
        app_web, cliente):
    """A URL de destino sai SEMPRE do nosso cadastro, nunca do pedido. Montar
    o wa.me com o que vem na URL viraria redirecionamento aberto: bastaria
    mandar um link do nosso próprio site para jogar alguém em qualquer
    lugar."""
    cotacao_id = _criar(app_web)

    r = cliente.get(f"/whatsapp/{cotacao_id}/naoexiste", follow_redirects=False)

    assert r.status_code == 404
    assert app_web.banco.whatsapp_abertos(cotacao_id) == set()


def test_nao_da_para_registrar_abertura_em_cotacao_alheia(app_web, cliente):
    cotacao_id = app_web.banco.salvar_cotacao("maria", CARGA)

    r = cliente.get(f"/whatsapp/{cotacao_id}/movvi", follow_redirects=False)

    assert r.status_code == 404
    assert app_web.banco.whatsapp_abertos(cotacao_id) == set()


# ----------------------------------- Generoso responde por e-mail, nao aqui
def _aguardando(app_web, cotacao_id: int) -> None:
    """Grava o resultado real da Generoso: recebido, sem preco.

    Passa pelo _rodar de proposito — foi ali que a mensagem da Translovato se
    perdia antes, e o mesmo caminho carrega este status."""
    from carriers.base import ResultadoCotacao
    from core.models import StatusCotacao

    app_web._rodar(cotacao_id, "generoso",
                   lambda _: ResultadoCotacao("generoso",
                                              StatusCotacao.AGUARDANDO_RETORNO),
                   None)


def test_generoso_entra_na_lista_de_cotadas_automaticamente(app_web, cliente):
    """Ela tinha adapter pronto mas nao era disparada: a tela nem mencionava
    a Generoso, e o vendedor nao tinha como saber que ela ficou de fora."""
    cotacao_id = _criar(app_web)

    texto = _texto(cliente.get(f"/cotacao/{cotacao_id}").text)

    assert "Generoso" in texto
    assert "cotando" in texto


def test_generoso_manda_conferir_o_email_em_vez_de_dizer_que_falhou(
        app_web, cliente):
    """AGUARDANDO_RETORNO nao e falha. Cair no cartao de erro faria o vendedor
    desistir de uma cotacao que FOI enviada e esta a caminho."""
    cotacao_id = _criar(app_web)
    _aguardando(app_web, cotacao_id)

    texto = _texto(cliente.get(f"/cotacao/{cotacao_id}").text)

    assert "vendas@ventura.com.br" in texto
    assert "Nao retornou preco" not in texto
    assert "Não retornou preço" not in texto
    assert "o site respondeu" not in texto


def test_o_email_da_tela_e_o_que_o_vendedor_digitou(app_web, cliente):
    """Guarda contra endereco chumbado no codigo: mandar o vendedor olhar a
    caixa de outra pessoa e pior do que nao dizer nada."""
    cotacao_id = _criar(app_web, email="joao@ventura.com.br")
    _aguardando(app_web, cotacao_id)

    texto = _texto(cliente.get(f"/cotacao/{cotacao_id}").text)

    assert "joao@ventura.com.br" in texto
    assert "vendas@ventura.com.br" not in texto


def test_cotacao_antiga_sem_email_nao_quebra_a_tela(app_web, cliente):
    """Todo o historico anterior a esta mudanca tem email NULL. A tela precisa
    continuar abrindo, so sem conseguir dizer qual caixa conferir."""
    carga = {k: v for k, v in CARGA.items() if k != "email"}
    cotacao_id = app_web.banco.salvar_cotacao("enzo", carga)
    _aguardando(app_web, cotacao_id)

    resposta = cliente.get(f"/cotacao/{cotacao_id}")

    assert resposta.status_code == 200
    assert "None" not in _texto(resposta.text)


def test_generoso_nao_disputa_o_selo_de_mais_barato(app_web, cliente):
    """Sem preco nao ha o que comparar. O selo tem que continuar na Camilo."""
    from carriers.base import ResultadoCotacao
    from core.models import StatusCotacao
    from decimal import Decimal

    cotacao_id = _criar(app_web)
    _aguardando(app_web, cotacao_id)
    app_web._rodar(cotacao_id, "camilo",
                   lambda _: ResultadoCotacao("camilo", StatusCotacao.COTADO,
                                              valor_frete=Decimal("99.90")),
                   None)

    html = cliente.get(f"/cotacao/{cotacao_id}").text

    assert html.count("MAIS BARATO") == 1
    posicao_selo = html.index("MAIS BARATO")
    assert "Camilo" in html[:posicao_selo][-400:]


def test_o_print_da_confirmacao_aparece_no_cartao_enviada(app_web, cliente,
                                                          tmp_path):
    """A tela final do Generoso diz "Recebemos seu pedido de cotação". E a
    prova de que o envio saiu — sem ela o vendedor só tem a nossa palavra de
    que a cotação entrou na fila de alguém."""
    from carriers.base import ResultadoCotacao
    from core.models import StatusCotacao

    # PNG 1x1 de verdade: _img só embute arquivo que existe.
    print_falso = tmp_path / "resultado.png"
    print_falso.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000a49444154789c6300010000050001od"[:-2]
        + "0a2db40000000049454e44ae426082"))

    cotacao_id = _criar(app_web)
    app_web._rodar(cotacao_id, "generoso",
                   lambda _: ResultadoCotacao(
                       "generoso", StatusCotacao.AGUARDANDO_RETORNO,
                       evidencias=[str(print_falso)]), None)

    html = cliente.get(f"/cotacao/{cotacao_id}").text

    assert 'class="print"' in html
