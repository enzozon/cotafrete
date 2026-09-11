"""O JavaScript do painel, conferido como TEXTO.

Não há navegador nos testes, então o que dá para guardar aqui é a forma do
script — e a forma foi exatamente o que quebrou em 10/09/2026.

O que aconteceu: ao inserir `trocarFaixa` e `trocarTabela` antes de
`pulsar()`, o `});` que fechava o ouvinte de clique do histórico foi comido.
O arquivo continuou sendo JavaScript VÁLIDO — as duas funções simplesmente
passaram a nascer dentro do ouvinte, e só existiam depois de alguém clicar
numa linha. `pulsar()` chamava as duas a cada cinco segundos, recebia
ReferenceError, e o `catch` da época engolia tudo sem uma linha no console.

O painel parava de se atualizar e nada na tela dizia isso.

Nenhum teste pegava, porque nenhum olhava para a estrutura: o HTML continha
o texto "trocarFaixa", o servidor respondia 200 e o script parseava. É o tipo
de defeito que só a forma denuncia.
"""

import re

import pytest

from web import adm

SCRIPTS = {"painel": adm.SCRIPT, "cotacao": adm.SCRIPT_COTACAO}


def sem_ruido(js: str) -> str:
    """O script sem comentário e sem texto — só a estrutura.

    Sem isto, uma chave dentro de um comentário ou de uma string entraria na
    conta de profundidade e o teste acusaria defeito onde não há."""
    js = re.sub(r"//[^\n]*", "", js)
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    js = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", js)
    js = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', js)
    return re.sub(r"`(?:[^`\\]|\\.)*`", "``", js)


def profundidade_de(js: str, alvo: str) -> int:
    """Quantas chaves estão abertas no ponto em que `alvo` aparece."""
    limpo = sem_ruido(js)
    onde = limpo.index(alvo)
    return limpo[:onde].count("{") - limpo[:onde].count("}")


@pytest.mark.parametrize("nome,js", list(SCRIPTS.items()))
def test_as_chaves_fecham(nome, js):
    limpo = sem_ruido(js)
    abertas, fechadas = limpo.count("{"), limpo.count("}")

    assert abertas == fechadas, (
        f"script do {nome}: {abertas} chaves abertas e {fechadas} fechadas")


@pytest.mark.parametrize("funcao", ["trocarFaixa", "trocarTabela", "pulsar"])
def test_o_que_o_pulso_chama_esta_no_escopo_de_cima(funcao):
    """Declarada dentro de um ouvinte, a função só existe depois do evento.

    `pulsar()` roda de fora, a cada cinco segundos: ela só alcança o que foi
    declarado no topo do script. Profundidade zero é a diferença entre o
    painel se atualizar e o painel parecer congelado."""
    profundidade = profundidade_de(adm.SCRIPT, f"function {funcao}")

    assert profundidade == 0, (
        f"`{funcao}` está {profundidade} nível(is) dentro de outro bloco — "
        f"`pulsar()` não enxerga de lá")


def test_o_pulso_nao_engole_defeito_de_codigo():
    """Rede caindo é normal e não merece console; ReferenceError merece.

    O `catch` mudo que existia aqui foi o que escondeu o defeito acima — o
    painel parava de se atualizar e o console ficava limpo."""
    for nome, js in SCRIPTS.items():
        assert "instanceof TypeError" in js, (
            f"script do {nome}: o catch precisa separar falha de rede "
            f"(TypeError do fetch) de defeito de código")
        assert "console.error" in js, (
            f"script do {nome}: defeito de código precisa aparecer")


def test_o_realce_so_marca_o_que_realmente_mudou():
    """O realce serve para dizer O QUE mudou.

    Marcando tudo a cada volta, o painel piscaria inteiro de cinco em cinco
    segundos e o realce deixaria de querer dizer qualquer coisa — que é o
    mesmo que não ter realce, com movimento no caminho."""
    assert "antes[i] !== b.textContent.trim()" in adm.SCRIPT
    assert "!antigas.has(tr.dataset.abrir)" in adm.SCRIPT
