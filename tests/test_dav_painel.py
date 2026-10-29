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
