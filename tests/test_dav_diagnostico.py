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


def test_nome_cliente_nao_e_aviso_financeiro():
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro("pronto", relatorio=relatorio(info="Cliente: Financeira Industrial S.A.")), administrador=False)
    assert d["aviso_financeiro"] is False and d["tem_aviso"] is False


def test_itens_reconhecidos_sem_reproduzir_continuacoes():
    from orcamento.diagnostico import diagnostico
    texto = relatorio().replace("Itens:\n", "Itens:\nItem 1: usou produto existente 49025 - PORTA CHAVES (pelo código informado)\n"
                               "continuação privada DF15653 valor 1234,56 vencimento 27/09/2026\n")
    d = diagnostico(registro("pronto", relatorio=texto), administrador=False)
    assert d["itens"] == ["Item 1: usou produto existente 49025 - PORTA CHAVES (pelo código informado)"]
    assert "DF15653" not in str(d)


@pytest.mark.parametrize("estado", ["simulado", "erro"])
def test_relatorio_real_de_simulacao_nao_indica_salvamento(estado):
    from orcamento.diagnostico import diagnostico
    from orcamento.relatorio import Relatorio
    rel = Relatorio("plan.xlsx", True)
    rel.resultado = "DRY_RUN - simulação concluída sem erros (nada foi salvo)"
    if estado == "erro":
        rel.erro("Local de entrega inválido")
    d = diagnostico(registro(estado, relatorio=rel.texto()), administrador=False)
    assert d["salvamento"] != "incerto"
    assert d["titulo"] != "Confira no HSE"


def test_evidencia_positiva_do_resultado_preserva_incerto():
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro("erro", relatorio="Resultado: ERRO - orçamento 16410 FOI SALVO no HSE, mas o DAV falhou; NÃO reenvie a planilha"), administrador=False)
    assert d["salvamento"] == "incerto"


def test_incerto_antigo_orienta_pelo_dia_da_execucao():
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro("incerto", criado_em="2026-10-29T23:55:00", iniciado_em="2026-10-30T00:10:00"), administrador=False)
    assert "30/10/2026" in d["orientacao"] and "de hoje" not in d["orientacao"]
    sem_data = diagnostico(registro("incerto", criado_em="invalida"), administrador=False)
    assert "de hoje" not in sem_data["orientacao"]
