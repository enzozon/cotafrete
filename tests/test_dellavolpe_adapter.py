"""Testes da camada de BROWSER da Della Volpe, contra o DOM real replicado.

tests/fixtures/dv_real.html reproduz as armadilhas que recon/recon_dellavolpe.py mediu
no site de produção: zero <label>, formulário duplicado oculto ANTES do visível,
selects sem placeholder, anexos por data-name, e reCAPTCHA v3 invisível.

Roda por file:// — não sobe servidor e não toca a rede.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from carriers.dellavolpe.adapter import DellavolpeAdapter
from core.models import (
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, Volume,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "dv_real.html").resolve()
URL_FIXTURE = FIXTURE.as_uri()


@pytest.fixture
def page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_context(locale="pt-BR").new_page()
        pg.set_default_timeout(8_000)
        pg.goto(URL_FIXTURE, wait_until="load")
        yield pg
        browser.close()


@pytest.fixture
def adapter():
    return DellavolpeAdapter(base_url=URL_FIXTURE, headless=True)


def carga(**over) -> CotacaoRequest:
    base = dict(
        solicitante=Solicitante(nome="Enzo Teste", email="enzo@exemplo.com.br",
                                whatsapp="27999887766"),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf="ES", cidade="Vitória"),
        destino=Local(uf="SP", cidade="São Paulo"),
        remetente=Parte(cnpj="11.222.333/0001-81"),
        destinatario=Parte(cnpj="45.723.174/0001-10"),
        pagador_frete=Parte(cnpj="61.139.432/0001-72"),
        volumes=[Volume(qtd=2, comprimento_cm=Decimal(100), largura_cm=Decimal(50),
                        altura_cm=Decimal(40), peso_kg=Decimal(10))],
        mercadoria=Mercadoria(tipo_material="Peças metálicas"),
        nota_fiscal=NotaFiscal(valor_total=Decimal(25_000)),
    )
    base.update(over)
    return CotacaoRequest(**base)


# ----------------------------------------------- BUG 1: selects sem rótulo
@pytest.mark.parametrize("rotulo, name_esperado", [
    ("Selecione o estado de origem", "estado_origem"),
    ("Selecione a cidade de origem", "cidade_origem"),
    ("Selecione o estado de destino", "estado_destino"),
    ("Selecione a cidade de destino", "cidade_destino"),
    ("Qual o serviço que você procura?", "servico"),
])
def test_selects_sem_label_sao_localizaveis(adapter, page, rotulo, name_esperado):
    """Os 5 selects não têm label nem placeholder — só o texto da 1ª option.

    Sem isso, origem e destino nunca são preenchidos e cotar() aborta inteiro."""
    loc = adapter._localizar(page, rotulo)
    assert loc.get_attribute("name") == name_esperado


# ------------------------------------- BUG 2: .first pega duplicata oculta
@pytest.mark.parametrize("rotulo", [
    "Nome completo", "E-mail", "CNPJ da empresa que pagará o frete",
])
def test_localizar_devolve_o_campo_visivel_nao_a_duplicata_oculta(
        adapter, page, rotulo):
    """O DOM real tem 9 formulários com os MESMOS name= e placeholders.

    .first pega o índice 0 e só depois testa visibilidade — então quando o
    primeiro do DOM está oculto, a estratégia inteira é descartada mesmo
    existindo um campo visível adiante."""
    loc = adapter._localizar(page, rotulo)
    assert loc.is_visible(), f"{rotulo!r} resolveu para um campo oculto"


# --------------------------------- BUG 3: FISPQ cai no slot da planilha
def test_fispq_e_planilha_vao_para_inputs_diferentes(adapter, page, tmp_path):
    """Os dois anexos caem no mesmo input[type=file].first do fallback.

    A FISPQ acabaria no campo de volumes — justamente o caso que
    separar_anexos() foi escrito para proteger."""
    planilha = tmp_path / "volumes.xlsx"
    planilha.write_bytes(b"xlsx-falso")
    fispq = tmp_path / "fispq.pdf"
    fispq.write_bytes(b"pdf-falso")

    adapter._anexar(page, "Anexar Planilha", [str(planilha)])
    adapter._anexar(page, "Anexar FISPQ", [str(fispq)])

    def nomes(data_name: str) -> list[str]:
        return page.locator(
            f'input[type="file"][data-name="{data_name}"]').last.evaluate(
            "el => [...(el.files || [])].map(f => f.name)")

    assert nomes("anexo-vol") == ["volumes.xlsx"]
    assert nomes("anexo-fispq") == ["fispq.pdf"]


# ------------------------------- BUG 4: reCAPTCHA v3 invisível não bloqueia
def test_recaptcha_v3_invisivel_nao_bloqueia(adapter, page):
    """O site carrega reCAPTCHA v3 (score, sem desafio) em toda página.

    Procurar a string 'recaptcha' no HTML faz o adapter abortar com
    INTERVENCAO_NECESSARIA em 100% das execuções reais, sem nunca digitar nada."""
    assert adapter._tem_captcha(page) is False


def test_desafio_de_captcha_visivel_bloqueia(adapter, page):
    """Contrapartida: um desafio de verdade PRECISA continuar bloqueando.

    bframe é o iframe do desafio de imagens do reCAPTCHA — só aparece quando o
    Google decide interrogar, e aí realmente exige humano."""
    page.evaluate("""() => {
        const f = document.createElement('iframe');
        f.src = 'https://www.google.com/recaptcha/api2/bframe?k=teste';
        f.width = 400; f.height = 580;
        document.body.appendChild(f);
    }""")
    assert adapter._tem_captcha(page) is True


def test_checkbox_do_recaptcha_v2_bloqueia(adapter, page):
    """v2 'não sou um robô': anchor SEM size=invisible. Também exige humano."""
    page.evaluate("""() => {
        const f = document.createElement('iframe');
        f.src = 'https://www.google.com/recaptcha/api2/anchor?k=teste&size=normal';
        f.width = 304; f.height = 78;
        document.body.appendChild(f);
    }""")
    assert adapter._tem_captcha(page) is True


# ------------------------- BUG 5: ordem alfabética viola serviço -> veículo
def test_servico_e_preenchido_antes_do_tipo_de_veiculo(adapter, page):
    """A ordenação é alfabética por rótulo, e 'Escolha o tipo de veículo' (E)
    vem antes de 'Qual o serviço que você procura?' (Q).

    No site real tipo-veiculo fica display:none até FTL ser escolhido, então o
    adapter tenta preencher um campo que ainda não existe."""
    req = carga(servico=Servico.LOTACAO_FTL,
                veiculo_desejado="Carreta Vanderleia (até 34.000 kg)")
    campos = {"Qual o serviço que você procura?": "Lotação/Dedicado-FTL",
              "Escolha o tipo de veículo": req.veiculo_desejado}

    adapter._preencher(page, campos)

    visivel = page.locator("#form-fracionado")
    assert visivel.locator('[name="servico"]').input_value() == "Lotação/Dedicado-FTL"
    assert (visivel.locator('[name="tipo-veiculo"]').input_value()
            == req.veiculo_desejado)


# --------------------------- BUG 6: espera fixa de 1200ms é race condition
def test_cidade_espera_as_opcoes_chegarem_do_xhr(adapter, page):
    """O fixture popula a cidade em 1800ms; o adapter espera 1200ms fixos.

    Numa rede mais lenta que a espera arbitrária, o select ainda está vazio e a
    cidade é silenciosamente deixada em branco."""
    campos = {"Selecione o estado de origem": "ES",
              "Selecione a cidade de origem": "Vitória"}

    adapter._preencher(page, campos)

    # escopo no formulário visível: o name= se repete no duplicado oculto, que
    # é exatamente a armadilha que este fixture existe para reproduzir
    assert (page.locator('#form-fracionado [name="cidade_origem"]').input_value()
            == "Vitória")


# ------------------------------------------- integração: formulário inteiro
def test_print_recorta_o_formulario_e_nao_o_site_inteiro(page, tmp_path):
    """O print é a única forma de o Enzo conferir o que foi enviado.

    Com full_page=True saía o site inteiro: o formulário virava uma tira no
    topo, ilegível, seguida de metros de banner laranja e rodapé. Recortado no
    <form>, cabe na tela e dá para ler campo por campo."""
    adapter = DellavolpeAdapter()
    destino = tmp_path / "preenchido.png"
    assert adapter._print_formulario(page, destino) == [str(destino)]

    dados = destino.read_bytes()
    largura = int.from_bytes(dados[16:20], "big")
    altura = int.from_bytes(dados[20:24], "big")

    # cabe tudo: o recorte é a união dos campos mais a margem dos dois lados
    campos = page.evaluate("""() => {
        const form = [...document.querySelectorAll('form')].find(f =>
            [...f.querySelectorAll('input,select,textarea')]
                .some(x => x.offsetWidth || x.offsetHeight));
        const r = [...form.querySelectorAll('input,select,textarea')]
            .filter(x => x.offsetWidth || x.offsetHeight)
            .map(x => x.getBoundingClientRect());
        return {w: Math.max(...r.map(b => b.right)) - Math.min(...r.map(b => b.x)),
                h: Math.max(...r.map(b => b.bottom)) - Math.min(...r.map(b => b.y))};
    }""")
    assert largura >= campos["w"]
    assert altura >= campos["h"]

    # e não é o site inteiro
    altura_pagina = page.evaluate("() => document.documentElement.scrollHeight")
    assert altura <= altura_pagina


def test_print_cai_para_a_pagina_se_o_formulario_sumir(page, tmp_path):
    """Sem formulário localizável ainda queremos evidência: print é melhor
    que nada quando o envio já aconteceu."""
    page.evaluate("() => document.querySelectorAll('form').forEach(f => f.remove())")
    destino = tmp_path / "preenchido.png"

    assert DellavolpeAdapter()._print_formulario(page, destino) == [str(destino)]
    assert destino.exists()


def test_preenche_todos_os_campos_do_dom_real(adapter, page):
    """Ponta a ponta no DOM real replicado: nenhum campo pode ficar vazio."""
    from carriers.dellavolpe import mapping as m

    campos = m.campos_do_formulario(m.preparar_payload(carga()))
    texto, _ = m.separar_anexos(campos)

    adapter._preencher(page, texto)

    vazios = page.evaluate("""() => {
        const f = document.getElementById('form-fracionado');
        return [...f.querySelectorAll('input:not([type=file]), select')]
            .filter(el => el.offsetParent && !el.value)
            .map(el => el.name);
    }""")
    assert vazios == []
