from contextlib import closing
from datetime import datetime, timezone

import pytest

from core.banco import Banco


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def novo(banco, estado="pronto", usuario="ana", quando="2026-10-29T13:00:00", **kw):
    i = banco.dav_criar(usuario, "plan.xlsx", str(kw), "Cliente A")
    banco.dav_atualizar(i, estado=estado, **kw)
    with closing(banco._conectar()) as con, con:
        con.execute("UPDATE dav SET criado_em=? WHERE id=?", (quando, i))
    return i


def consulta(banco, **kw):
    from core.painel_dav import consultar
    args = dict(usuario=None, dias=1, agora=datetime(2026, 10, 29, 14))
    args.update(kw)
    with closing(banco._conectar()) as con:
        return consultar(con, **args)


def test_periodo_e_paginacao_nao_truncam_totais(banco):
    for n in range(205):
        novo(banco, numero=str(n))
    d = consulta(banco)
    assert (d["total"], len(d["linhas"]), d["paginas"]) == (205, 25, 9)
    assert d["resumo"]["criados"] == 205
    assert consulta(banco, pagina=999)["pagina"] == 9


def test_contagens_separam_estados(banco):
    for e in ("pronto", "erro", "incerto", "fila", "gerando", "rascunho", "simulado", "rejeitado"):
        novo(banco, e)
    d = consulta(banco)["resumo"]
    assert (d["tentativas"], d["criados"], d["falhas"], d["incertos"], d["em_andamento"], d["rejeitados"]) == (5, 1, 1, 1, 2, 1)


def test_fronteira_de_dia_brasilia(banco):
    novo(banco, quando="2026-10-28T23:59:59")
    novo(banco, quando="2026-10-29T00:00:00")
    assert consulta(banco, agora=datetime(2026, 10, 29, 3, 1, tzinfo=timezone.utc))["total"] == 1
    assert consulta(banco, dias=7)["total"] == 2


def test_filtro_vendedor_nao_sobrepoe_proprietario(banco):
    novo(banco)
    novo(banco, usuario="bia")
    assert consulta(banco, usuario="ana", vendedor="bia")["total"] == 1
    assert consulta(banco, busca="' OR 1=1 --")["total"] == 0
    assert consulta(banco, usuario="ana")["vendedores"] == []


def test_resolvida_so_com_descendente_pronto(banco):
    from core.painel_dav import resolvidas
    a = novo(banco, "erro")
    b = novo(banco, "rejeitado")
    c = novo(banco, "fila")
    solta = novo(banco, "erro")
    banco.dav_vincular_correcao(a, b, "ana")
    banco.dav_vincular_correcao(b, c, "ana")
    with closing(banco._conectar()) as con:
        assert resolvidas(con, [a, b, solta], "ana") == {}
        banco.dav_atualizar(c, estado="incerto")
        assert resolvidas(con, [a], "ana") == {}
        banco.dav_atualizar(c, estado="pronto")
        assert resolvidas(con, [a, b, solta], "ana") == {a: c, b: c}
        assert resolvidas(con, [a], "bia") == {}
    assert banco.dav(a, "ana")["estado"] == "erro"


def test_avisos_desconhecidos_nao_sao_zero(banco):
    novo(banco)
    assert consulta(banco)["resumo"]["avisos_desconhecidos"] == 1


def test_estado_novo_visivel(banco):
    novo(banco, "estado_futuro")
    d = consulta(banco)
    assert d["total"] == 1 and d["resumo"]["inesperados"] == 1
    assert d["resumo"]["tentativas"] == 0


def test_posicao_usa_toda_fila(banco):
    from core.painel_dav import posicao_na_fila
    for n in range(55):
        i = novo(banco, "fila", usuario="ana" if n % 2 else "bia")
    with closing(banco._conectar()) as con:
        assert posicao_na_fila(con, i) == 55
    assert consulta(banco, estado="erro")["resumo"]["em_andamento"] == 55


def test_ocorrencias_completas_filtradas_antes_da_paginacao(banco):
    ids = {novo(banco, "erro", erro="Local de entrega não encontrado") for _ in range(30)}
    novo(banco, "erro", usuario="bia", erro="HSE fora do ar")
    dados = consulta(banco, vendedor="ana", estado="erro", categoria="endereco", pagina=2)
    assert len(dados["linhas"]) == 5
    assert len(dados["ocorrencias"]) == 1
    grupo = dados["ocorrencias"][0]
    assert grupo["tipo"] == "falha" and grupo["total"] == 30
    assert {d["id"] for d in grupo["envios"]} == ids
    assert grupo["onde_conferir"] and grupo["como_corrigir"]
    assert consulta(banco, busca="inexistente")["ocorrencias"] == []


def test_ocorrencias_distinguem_conferencia_rejeicao_confirmacao_e_aviso(banco):
    from orcamento.processador import Conferencia
    novo(banco, "erro", erro="Local de entrega não encontrado")
    novo(banco, "rejeitado", erro="Formato inválido")
    conf = Conferencia(estado="erros", relatorio="", cliente="", endereco="", vendedor="",
                      itens=(), avisos=(), erros=("Item 3: quantidade inválida",))
    novo(banco, "rascunho", conferencia="erros", conferencia_relatorio=conf.para_json())
    novo(banco, "erro", numero="16410", erro="Local de entrega não encontrado")
    novo(banco, "erro", erro="Salvar foi clicado; não reenvie a planilha")
    novo(banco, "pronto", relatorio="Cliente com pendência financeira DF123", numero="16411")
    novo(banco, "pronto")
    grupos = consulta(banco)["ocorrencias"]
    tipos = {g["tipo"] for g in grupos}
    # pronto com pendência financeira não é ocorrência: é normal e fica em Prontos
    assert tipos == {"falha", "rejeitado", "conferencia", "confirmacao"}
    assert sum(g["total"] for g in grupos) == 5
    assert sum(g["total"] for g in grupos if g["tipo"] == "confirmacao") == 2
    for g in grupos:
        if g["tipo"] == "confirmacao":
            assert "HSE" in g["como_corrigir"]


def test_ocorrencias_vendedor_nao_expoem_detalhes_tecnicos_ou_outro_usuario(banco):
    meu = novo(banco, "erro", erro="Falha desconhecida SEGREDO-TECNICO")
    novo(banco, "erro", usuario="bia", erro="HSE fora do ar")
    grupos = consulta(banco, usuario="ana")["ocorrencias"]
    assert [d["id"] for g in grupos for d in g["envios"]] == [meu]
    assert "SEGREDO-TECNICO" not in str(grupos)
    assert "SEGREDO-TECNICO" in str(consulta(banco, vendedor="ana")["ocorrencias"])


def test_ocorrencias_conferencia_preservam_campos_e_orientacao_por_causa(banco):
    from orcamento.processador import Conferencia
    ids = set()
    for erros in (("Item 3: quantidade inválida",), ("Cliente (B31) é obrigatório",),
                  ("Item 3: quantidade inválida",),
                  ("Item 3: quantidade inválida", "Cliente (B31) é obrigatório")):
        conf = Conferencia(estado="erros", relatorio="", cliente="", endereco="", vendedor="",
                          itens=(), avisos=(), erros=erros)
        ids.add(novo(banco, "rascunho", conferencia="erros", conferencia_relatorio=conf.para_json()))
    grupos = consulta(banco)["ocorrencias"]
    # Mesma causa = um cartão; as células diferentes ficam em cada envio.
    assert len(grupos) == 1 and grupos[0]["total"] == 4
    assert sorted(tuple(d["campos"]) for d in grupos[0]["envios"]) == sorted(
        [("B4",), ("B31",), ("B4",), ("B4", "B31")])
    envios = [d["id"] for d in grupos[0]["envios"]]
    assert len(envios) == len(set(envios)) == 4 and set(envios) == ids
    assert "Corrija os campos indicados" in grupos[0]["como_corrigir"]


def test_ocorrencias_ignoram_erro_ja_resolvido(banco):
    a = novo(banco, "erro", erro="Local de entrega não encontrado")
    b = novo(banco, "pronto")
    banco.dav_vincular_correcao(a, b, "ana")
    solta = novo(banco, "erro", erro="Local de entrega não encontrado")
    dados = consulta(banco)
    assert [d["id"] for g in dados["ocorrencias"] for d in g["envios"]] == [solta]
    assert dados["corrigidas"] == 1


def test_periodo_tudo_mostra_envio_antigo_e_a_tela_leva_ate_ele(banco):
    from web import dav_ui
    novo(banco, quando="2025-01-02T10:00:00")
    novo(banco)
    assert consulta(banco)["total"] == 1
    assert consulta(banco, dias=30)["total"] == 1
    tudo = consulta(banco, dias=0)
    assert (tudo["total"], tudo["periodo"]["dias"]) == (2, 0)

    hoje = dav_ui.historico_dav(consulta(banco), {"dias": 1})
    assert 'href="/dav?dias=0&amp;pagina=1#historico">Ver todos os envios' in hoje
    assert "Ver todos os envios" not in dav_ui.historico_dav(tudo, {"dias": 0})
    barra = dav_ui.filtros_dav(tudo, {"dias": 0})
    assert '<input type="hidden" name="dias" value="0">' in barra  # a busca não volta para Hoje
    assert "Tudo <span" in barra  # chip do filtro ativo
