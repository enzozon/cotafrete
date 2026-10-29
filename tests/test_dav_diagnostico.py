"""Diagnóstico real, com separação entre resultado e pendência financeira."""
import pytest


def registro(estado="erro", erro="", relatorio="", **kw):
    return dict(estado=estado, erro=erro, relatorio=relatorio, **kw)


def relatorio(erro="", info=""):
    return ("Robô de Orçamentos HSE\nArquivo: plan.xlsx\nData: 29/10/2026 13:20\n"
            "Modo: REAL\nResultado: ERRO - orçamento não criado\n\nItens:\n"
            + ("\nDetalhes:\n" + info if info else "")
            + ("\nErros:\nERRO: " + erro if erro else ""))


def test_endereco_e_pendencia_sao_independentes():
    from orcamento.diagnostico import diagnostico
    texto = relatorio("Local de entrega 'Barao': 0 endereço(s) do cliente contém esse texto",
                      "O HSE avisou: Pendência Cliente bloqueado. Consultar o setor financeiro DF15653")
    d = diagnostico(registro(relatorio=texto), administrador=False)
    assert d["categoria"] == "endereco" and d["aviso_financeiro"] is True
    pronto = diagnostico(registro("pronto", relatorio=texto, numero="16410"), administrador=False)
    assert pronto["salvamento"] == "confirmado" and pronto["tem_aviso"] is True


def test_erro_existe_so_no_relatorio():
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro(relatorio=relatorio("Local de entrega não encontrado")), administrador=False)
    assert d["categoria"] == "endereco"
    assert d["salvamento"] == "nao_criado"


def test_erro_e_relatorio_conciliados():
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro(erro="HSE fora do ar", relatorio=relatorio("Local de entrega inválido")), administrador=True)
    assert "HSE fora do ar" in d["relatorio_visivel"]
    assert "Local de entrega inválido" in d["relatorio_visivel"]


@pytest.mark.parametrize("campo", ["erro", "info", "desconhecido"])
def test_financeiro_multilinha_nao_vaza(campo):
    from orcamento.diagnostico import diagnostico
    divida = "Pendência financeira\nDF15653 valor 1234,56\nVenc: 27/09/2026"
    r = registro(erro=divida) if campo == "erro" else registro(
        relatorio=relatorio(info=divida) if campo == "info" else "Seção desconhecida:\n" + divida)
    vendedor = diagnostico(r, administrador=False)
    for segredo in ("DF15653", "1234,56", "27/09/2026"):
        assert segredo not in str(vendedor)
        assert segredo in diagnostico(r, administrador=True)["relatorio_visivel"]


def test_legado_desconhecido_nao_inventa():
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro(erro="falha desconhecida"), administrador=False)
    assert d["tem_aviso"] is None and d["etapa"] is None
    assert d["salvamento"] == "desconhecido"
    assert diagnostico(registro("incerto", relatorio="OK - salvo"), administrador=False)["salvamento"] == "incerto"


def test_numero_persistido_em_erro_exige_conferencia():
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro(numero="16410"), administrador=False)
    assert d["salvamento"] == "incerto"
    assert "HSE" in d["orientacao"]


def test_relatorio_completo_sem_aviso_e_mensagem_desconhecida():
    from orcamento.diagnostico import diagnostico
    assert diagnostico(registro("pronto", relatorio=relatorio()), administrador=False)["tem_aviso"] is False
    r = registro(erro="Segredo de formato futuro DF15653 vencimento 27/09/2026")
    assert "DF15653" not in str(diagnostico(r, administrador=False))
