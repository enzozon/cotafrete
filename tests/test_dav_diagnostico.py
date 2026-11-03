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


def test_vendedor_ve_o_erro_do_robo_para_corrigir_a_planilha():
    # DAV 28 e DAV 24 (29/10/2026): com "Motivo não identificado" o vendedor não teria como corrigir sozinho
    from orcamento.diagnostico import diagnostico
    desconto = ("Item 8: valor unitário R$ 407,19 abaixo do mínimo R$ 16.022,50 "
                "(preço de tabela R$ 18.850,00, desconto máximo 15%)")
    d = diagnostico(registro(relatorio=relatorio(desconto)), administrador=False)
    assert desconto in d["motivo"] and desconto in d["relatorio_visivel"]
    vendedor = "Vendedor 'MICHELI' não encontrado no HSE (use o nome exato da lista)"
    assert vendedor in diagnostico(registro(relatorio=relatorio(vendedor)), administrador=False)["relatorio_visivel"]


def test_vendedor_ve_os_enderecos_do_cliente_no_erro_de_local():
    # DAV 33: a lista de endereços (e a dica do número) é o que permite corrigir a B30
    from orcamento.diagnostico import diagnostico
    erro = ("falha durante a criação no HSE: Local de entrega 'São luis MA': 0 endereço(s) do cliente contém esse "
            "texto (1 - Cadastral - AV DOS PORTUGUESES, S/N, ITAQUI, SÃO LUÍS/MA)")
    d = diagnostico(registro(relatorio=relatorio(erro)), administrador=False)
    assert d["categoria"] == "endereco"
    assert "AV DOS PORTUGUESES" in d["relatorio_visivel"]


def test_linha_de_erro_financeira_ou_continuacao_nao_aparece_ao_vendedor():
    from orcamento.diagnostico import diagnostico
    texto = relatorio("Pendência Cliente bloqueado DF15653 Venc: 27/09/2026") \
        + "\nERRO: Item 2: produto novo sem GRUPO\ncontinuação privada DF15654 valor 99,90 vencimento 01/10/2026"
    d = diagnostico(registro(relatorio=texto), administrador=False)
    assert "Item 2: produto novo sem GRUPO" in d["relatorio_visivel"]
    for segredo in ("DF15653", "27/09/2026", "DF15654", "99,90"):
        assert segredo not in str(d)


def test_validacao_sem_criacao_orienta_corrigir_e_reenviar():
    # DAV 49 (30/10/2026): nada foi criado; mandar "consultar o responsável" assustava o vendedor
    from orcamento.diagnostico import diagnostico
    rel = ("Robô de Orçamentos HSE\nArquivo: b.xlsx\nData: 30/10/2026 11:39\nModo: REAL\n"
           "Resultado: ERRO na validação com o HSE (nada foi criado)\n\nItens:\n"
           "\nErros:\nERRO: Item 1: valor unitário R$ 3,41 abaixo do mínimo R$ 10,35 "
           "(preço de tabela R$ 12,18, desconto máximo 15%)")
    d = diagnostico(dict(estado="erro", erro="", relatorio=rel), administrador=False)
    assert d["salvamento"] == "nao_criado"
    assert d["orientacao"] == "Nada foi criado no HSE. Corrija a planilha e envie de novo."
    assert "responsável" not in d["relatorio_visivel"]


@pytest.mark.parametrize("erro,origem,campos", [
    ("Item 3: quantidade deve ser maior que zero", "planilha", ["B4"]),
    ("Cliente (B31) é obrigatório", "planilha", ["B31"]),
    ("Cliente 8411 não encontrado no HSE (use o código ou CNPJ/CPF exato)", "desconhecida", ["B31"]),
    ("Local de entrega 'ABC': 2 endereço(s) do cliente contém esse texto", "desconhecida", ["B30"]),
    ("Cliente sem endereço cadastrado no HSE", "cadastro_hse", ["B30"]),
    ("O HSE recusou o login do robô: acesso negado", "acesso_hse", []),
    ("Item 3: tela ficou com qtd/preço (1, 2), esperado (3, 4)", "automacao", []),
    ("Falha jamais vista B31 Item 3", "desconhecida", []),
    ("Item 25: quantidade inválida", "desconhecida", []),
])
def test_origem_e_celulas_confirmadas(erro, origem, campos):
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro(erro=erro), administrador=False)
    assert d["origem"] == origem
    assert d["campos"] == campos
    assert d["origem_rotulo"] and d["onde_conferir"] and d["como_corrigir"]
    if origem == "automacao":
        assert "Enzo, Allan ou Lucas" in d["como_corrigir"]
        assert "envio" in d["como_corrigir"]


def test_todos_os_erros_recebem_celula_sem_duplicar():
    from orcamento.diagnostico import diagnostico
    erros = ["Item 3: quantidade deve ser maior que zero", "Item 3: NCM deve ter 8 dígitos",
             "Cliente (B31) é obrigatório", "Item 3: quantidade inválida"]
    d = diagnostico(registro(erro="\n".join(erros)), administrador=False)
    assert d["origem"] == "planilha"
    assert d["campos"] == ["B4", "L4", "B31"]
    assert all(c in d["onde_conferir"] for c in d["campos"])


@pytest.mark.parametrize("estado,extras", [("incerto", {}), ("erro", {"numero": "16410"}),
    ("erro", {"relatorio": "Resultado: orçamento 16410 FOI SALVO no HSE"})])
def test_incerto_domina_instrucoes_de_correcao(estado, extras):
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro(estado, erro="Item 3: quantidade deve ser maior que zero", **extras), administrador=False)
    assert d["origem"] == "sem_confirmacao"
    assert d["como_corrigir"] == d["orientacao"]
    assert "HSE" in d["onde_conferir"]
    assert "envie de novo" not in d["como_corrigir"]


@pytest.mark.parametrize("administrador", [False, True])
def test_campos_novos_seguros_ate_para_administrador(administrador):
    from orcamento.diagnostico import diagnostico
    segredo = "Cliente bloqueado DF15653 valor 1234,56 vencimento 27/09/2026 B31"
    d = diagnostico(registro(erro=segredo), administrador=administrador)
    novos = str({k: d[k] for k in ("origem", "origem_rotulo", "onde_conferir", "como_corrigir", "campos")})
    assert d["campos"] == []
    for valor in ("DF15653", "1234,56", "27/09/2026"):
        assert valor not in novos


def test_erros_da_conferencia_no_rascunho():
    from orcamento.diagnostico import diagnostico
    from orcamento.processador import Conferencia
    conf = Conferencia("erros", "", "", "", "", (), (), ("Item 3: quantidade deve ser maior que zero",))
    d = diagnostico(registro("rascunho", conferencia="erros", conferencia_relatorio=conf.para_json()), administrador=False)
    assert d["origem"] == "planilha" and d["campos"] == ["B4"]
    assert d["categoria"] == "planilha"
    assert "B4" in d["onde_conferir"]


@pytest.mark.parametrize("texto", ["invalido", "null", "{}", "[]"])
def test_conferencia_legada_invalida_nao_quebra_diagnostico(texto):
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro("rascunho", conferencia="erros", conferencia_relatorio=texto), administrador=False)
    assert d["origem"] == "desconhecida" and d["campos"] == []


@pytest.mark.parametrize("erro,celula", [
    ("Item 2: valor unitário (coluna J) deve ser maior que zero", "J3"),
    ("Item 2: código 49025 não encontrado no HSE", "K3"),
    ("Item 2: NCM deve ter 8 dígitos", "L3"),
    ("Item 2: ORIGEM deve ser de 0 a 8", "M3"),
    ("Item 2: ICMS inválido(a)", "N3"),
    ("Item 2: produto novo sem GRUPO", "P3"),
    ("Item 2: DESCRIÇÃO NO DAV com 500 caracteres (máximo 200)", "R3"),
    ("Prazo de entrega (B32) inválido", "B32"),
    ("VENDEDOR (B33) é obrigatório", "B33"),
    ("Forma de pagamento (B34) desconhecida", "B34"),
    ("Filial inválida; use 1, 2 ou 3", "B37"),
    ("FRETE (B38) deve ser CIF ou FOB", "B38"),
])
def test_referencias_do_modelo(erro, celula):
    from orcamento.diagnostico import diagnostico
    assert diagnostico(registro(erro=erro), administrador=False)["campos"] == [celula]


def test_sem_criacao_nao_atribui_causa_desconhecida_a_planilha():
    from orcamento.diagnostico import diagnostico
    d = diagnostico(registro(relatorio=relatorio("mensagem desconhecida")), administrador=False)
    assert d["origem"] == "desconhecida"
    assert "Corrija a planilha e envie de novo" not in d["orientacao"]


def test_conferencia_com_decimal_invalido_e_tratada_como_desconhecida():
    from orcamento.diagnostico import diagnostico
    texto = ('{"itens":[{"numero":1,"codigo":"","descricao":"","preco_tabela":"xyz",'
             '"valor_unit":"1","por":""}]}')
    d = diagnostico(registro("rascunho", conferencia="erros", conferencia_relatorio=texto), administrador=False)
    assert d["origem"] == "desconhecida"
