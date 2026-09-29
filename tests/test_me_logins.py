"""Os 14 logins do ME, o frete CIF/FOB e a tela da cotação completa (28/09/2026).

- `mercado_eletronico.logins`: um login por (cliente, empresa); a empresa
  decide os impostos (ALIANÇA só ICMS, como a UNIÃO).
- `regras.tipo_frete`: aviso do comprador > formulário "Preço a Prazo CIF" >
  cliente (Nestlé, Autoglass, EDP CIF; WEG FOB) > FOB.
- A varredura: cada login no seu intervalo, 30 min de folga depois de 3
  falhas seguidas, e o log de chegadas.
- A tela: a linha se completa ao escolher a origem, pelo mesmo cálculo do
  robô, e a prévia não grava nada.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.banco import Banco
from mercado_eletronico import logins as L
from mercado_eletronico import mapa as M
from mercado_eletronico import pagina as pg
from mercado_eletronico import regras as R
from mercado_eletronico.regras import Conta
from tests.test_me_tela import _id, cliente, robo  # noqa: F401  (fixtures)
from web import me_ui

FIX = Path(__file__).parent / "fixtures" / "me_real"
HOJE = date(2026, 9, 28)


# ------------------------------------------------------------------ cadastro
def test_quatorze_logins_com_chave_unica_e_o_me_geral_com_a_chave_antiga():
    assert len(L.LOGINS) == 14
    assert len({l.chave for l in L.LOGINS}) == 14
    assert len({l.prefixo for l in L.LOGINS}) == 14
    # As cotações já gravadas em produção usam "ventura" e "uniao".
    assert L.de(Conta.VENTURA).rotulo == "ME geral · VENTURA"
    assert L.de("uniao").prefixo == "ME_UNIAO"


def test_autoglass_e_da_alianca_e_o_robo_vale_em_todos_os_logins():
    assert L.de("autoglass").empresa is Conta.ALIANCA
    assert L.de("autoglass").prefixo == "ME_AUTOGLASS"
    # Desde 28/09/2026 o robô lê o formulário de cada comprador (formulario.py).
    assert all(l.robo_liberado for l in L.LOGINS)


@pytest.fixture
def nestle_sem_robo(monkeypatch):
    from dataclasses import replace
    monkeypatch.setitem(L._POR_CHAVE, "nestle_ventura",
                        replace(L.de("nestle_ventura"), robo_liberado=False))


def test_chave_desconhecida_para_em_vez_de_entrar_em_outra_conta():
    with pytest.raises(KeyError):
        L.de("nestle")


def test_login_so_conta_como_configurado_com_login_e_senha():
    amb = {"WEG_UNIAO_LOGIN": "a", "WEG_UNIAO_SENHA": "b",
           "EDP_ALIANCA_LOGIN": "a", "EDP_ALIANCA_SENHA": ""}
    assert [l.chave for l in L.configurados(amb)] == ["weg_uniao"]


def test_alianca_paga_so_icms_como_a_uniao():
    for origem, uf in ((0, "ES"), (2, "RJ"), (0, "SP")):
        assert R.impostos(Conta.ALIANCA, origem, uf) == R.impostos(Conta.UNIAO, origem, uf)


# --------------------------------------------------------------------- frete
@pytest.mark.parametrize("avisos, empresa, formulario, esperado", [
    (["Frete Padrão: CIF"], "Samarco", "", "CIF"),
    (["Frete: FOB Vitória"], "EDP - Outsourcing", "", "FOB"),   # aviso manda
    ([], "ALPEK POLYESTER", "CIF", "CIF"),
    ([], "Nestlé Brasil", "", "CIF"),
    ([], "EDP - Outsourcing", "", "CIF"),
    ([], "AUTOGLASS", "", "CIF"),
    ([], "WLI - WEG Linhares", "", "FOB"),
    ([], "Samarco Mineração", "", "FOB"),
    ([], "NORWEGIAN SHIPPING", "", "FOB"),                        # não é a WEG
    (["Condição de Pagamento padrão EDP: 60 Dias"], None, "", "FOB"),
])
def test_tipo_de_frete(avisos, empresa, formulario, esperado):
    frete, motivo = R.tipo_frete(avisos, empresa, formulario)
    assert frete == esperado and motivo


def test_o_motivo_diz_de_onde_veio():
    assert "aviso do comprador" in R.tipo_frete(["Frete Padrão: CIF"], "WEG")[1]
    assert R.tipo_frete([], "Samarco")[1] == "padrão da empresa"


def test_robo_digita_o_frete_da_cotacao():
    item = R.EntradaItem(numero=10, preco="10", ncm="85365090", prazo_dias=5, marca="X",
                         origem=0, pedido=R.PedidoDoComprador("ES"))
    cif = M.plano_pagina(Conta.ALIANCA, {1: item}, 30, HOJE, frete="CIF").campos
    assert cif["IcoTerms"] == "CIF" and cif["atrib_CidadeEstado_1_1_0_0"] == "Frete CIF"
    assert M.plano_pagina(Conta.UNIAO, {1: item}, 30, HOJE).campos["IcoTerms"] == "FOB"
    with pytest.raises(M.PlanoInvalido):
        M.campos_cabecalho(30, HOJE, "", "DAP")


# ------------------------------------------------------------ página do ME
def test_pagina_da_edp_traz_avisos_frete_e_local_de_entrega():
    p = pg.ler((FIX / "edp_23050183.html").read_text(encoding="utf-8"))
    assert "Frete Padrão: CIF" in p.avisos
    assert "Condição de Pagamento padrão EDP: 60 Dias" in p.avisos
    assert not any(a.startswith("Após preencher") for a in p.avisos)  # rodapé do ME
    assert p.frete_formulario == ""
    assert len(p.itens) == 5
    assert p.itens[0].local_entrega.startswith("EDP TRANSMISSAO GOIAS S/A")
    # Sem "Campos Adicionais": a UF de entrega (o ICMS) sai do endereço.
    assert {i.pedido.uf_destino for i in p.itens} == {"GO"}
    assert R.tipo_frete(p.avisos, "EDP - Outsourcing")[0] == "CIF"


def test_formulario_que_pede_preco_cif_e_aviso_repetido_uma_vez_so():
    html = ('<input name="CotacaoID" value="1"><div class="me-info">Atenção: DIFAL</div>'
            '<td>Preço a Prazo CIF:</td><div class="me-info">Atenção: DIFAL</div>')
    p = pg.ler(html)
    assert p.avisos == ["DIFAL"] and p.frete_formulario == "CIF"


# ---------------------------------------------------------------- varredura
def test_cada_login_no_seu_intervalo_e_folga_depois_de_tres_falhas(monkeypatch):
    monkeypatch.setattr(me_ui, "VARREDURA", me_ui.EstadoVarredura())
    monkeypatch.setattr(me_ui, "contas_configuradas", lambda: ["ventura", "weg_uniao"])
    agora = [1000.0]
    relogio = lambda: agora[0]  # noqa: E731
    assert me_ui.devidas(relogio) == ["ventura", "weg_uniao"]

    me_ui._agendar("ventura", ok=True, relogio=relogio)
    me_ui._agendar("weg_uniao", ok=True, relogio=relogio)
    agora[0] += 7 * 60
    assert me_ui.devidas(relogio) == ["ventura"]           # ME geral: 7 min
    agora[0] += 8 * 60
    assert me_ui.devidas(relogio) == ["ventura", "weg_uniao"]  # clientes: 15 min

    for _ in range(3):
        me_ui._agendar("weg_uniao", ok=False, relogio=relogio)
    agora[0] += 29 * 60
    assert "weg_uniao" not in me_ui.devidas(relogio)
    agora[0] += 60
    assert "weg_uniao" in me_ui.devidas(relogio)
    me_ui._agendar("weg_uniao", ok=True, relogio=relogio)
    assert me_ui.VARREDURA.falhas["weg_uniao"] == 0


def test_log_de_chegadas(monkeypatch, tmp_path):
    monkeypatch.setattr(me_ui, "banco", Banco(tmp_path / "t.db"))
    log = tmp_path / "log" / "me_chegadas.txt"
    monkeypatch.setattr(me_ui, "LOG_CHEGADAS", log)
    p = lambda n: {"numero": n, "empresa": "EDP - Outsourcing", "comprador": "X",  # noqa: E731
                   "codigo": "", "data_limite": None, "status_resposta": "Não Respondida"}
    me_ui.sincronizar("nestle_ventura", [p(1)], datetime(2026, 9, 28, 8, 0))
    me_ui.sincronizar("nestle_ventura", [p(1), p(2)], datetime(2026, 9, 28, 8, 15))
    linhas = log.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2                      # a 1 não é anotada de novo
    assert linhas[0].startswith("2026-09-28 08:00:00 | Nestlé e EDP · VENTURA (nestle_ventura) | cotação 1")
    assert linhas[0].endswith("já estava lá na 1ª leitura deste login")
    assert "cotação 2 | EDP - Outsourcing" in linhas[1] and "1ª leitura" not in linhas[1]


def test_sem_log_configurado_nao_grava_nada(monkeypatch, tmp_path):
    monkeypatch.setattr(me_ui, "banco", Banco(tmp_path / "t.db"))
    monkeypatch.setattr(me_ui, "LOG_CHEGADAS", None)
    me_ui.sincronizar("weg_uniao", [{"numero": 9, "data_limite": None}], datetime(2026, 9, 28))
    assert not list(tmp_path.rglob("*.txt"))


# ------------------------------------------------------------ robô liberado
def test_robo_nao_entra_em_login_nao_liberado(monkeypatch, tmp_path, nestle_sem_robo):
    banco = Banco(tmp_path / "t.db")
    monkeypatch.setattr(me_ui, "banco", banco)
    disparos = []
    monkeypatch.setattr(me_ui, "DISPARAR", lambda *a: disparos.append(a))
    cid = banco.me_criar("nestle_ventura", 23050183, status="pendente")
    assert me_ui.mandar_robo(cid, "enzo", dry_run=False) == me_ui.NAO_LIBERADO
    assert me_ui.mandar_limpeza(cid, "enzo") == me_ui.NAO_LIBERADO
    assert disparos == [] and banco.me_cotacao(cid)["status"] == "pendente"


def test_robo_recebe_o_frete_da_cotacao(monkeypatch, tmp_path):
    banco = Banco(tmp_path / "t.db")
    monkeypatch.setattr(me_ui, "banco", banco)
    recebido = {}
    monkeypatch.setattr(me_ui, "ROBO", lambda *a, frete, anexos: recebido.setdefault("frete", frete)
                        and SimpleNamespace(ok=True, divergencias=[], prints=[], erro=None))
    cid = banco.me_criar("uniao", 7, status="salvando",
                         avisos_comprador='{"avisos": ["Frete Padrão: CIF"]}')
    me_ui._rodar_robo(cid, "enzo", True, "pendente")
    assert recebido == {"frete": "CIF"}


# --------------------------------------------------------------------- tela
def _item(**mudou):
    return {"numero": 10, "preco": "", "ncm": "", "prazo_dias": None, "marca": "",
            "obs": "", "origem": None, "uf_destino": "GO", "origem_pedida": None,
            "data_remessa": None, "quantidade": "5,00", **mudou}


def test_linha_sem_origem_pede_a_origem():
    html = me_ui.linha_previa({"conta": "nestle_ventura"}, _item(), HOJE)
    assert "Escolha a origem" in html and 'data-pronta="0"' in html


def test_escolher_a_origem_ja_mostra_os_impostos_da_empresa_do_login():
    html = me_ui.linha_previa({"conta": "nestle_ventura"}, _item(origem=2), HOJE)
    assert "<small>ICMS</small> 4,00% (sim)" in html          # GO, origem 2
    assert "<small>PIS</small> 0,65% (sim)" in html            # VENTURA cobra PIS
    assert "prazo de entrega obrigatório" in html               # o que falta, na linha
    alianca = me_ui.linha_previa({"conta": "edp_alianca"}, _item(origem=0), HOJE)
    assert "<small>ICMS</small> 12,00% (sim)" in alianca
    assert "<small>PIS</small> 0,00% (Isento)" in alianca       # ALIANÇA: só ICMS


def test_linha_completa_fica_pronta_com_entrega_e_total():
    html = me_ui.linha_previa({"conta": "uniao"}, _item(
        origem=0, preco="12,50", ncm="85365090", prazo_dias=10, marca="WEG"), HOJE)
    assert 'data-pronta="1"' in html
    assert "<small>entrega</small> 08/10/2026 (10 dias corridos)" in html
    assert "<small>total</small> R$ 62,50 (5,00 × 12,50)" in html
    assert "<small>NCM</small> 8536.50.90" in html


def test_previa_pela_rota_nao_grava_e_o_quadro_mostra_o_frete(cliente):
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    antes = me_ui.banco.me_cotacao(cid)["itens"]
    n = antes[0]["numero"]
    r = cliente.get(f"/me/{cid}/linha/{n}", params={
        "origem": "0", "prazo": "45", "preco": "10,00", "ncm": "85365090", "marca": "X"})
    assert r.status_code == 200
    assert "<small>ICMS</small> 12,00% (sim)" in r.text        # VENTURA entregando em MG
    assert "<small>preço</small> R$ 10,00" in r.text
    assert me_ui.banco.me_cotacao(cid)["itens"] == antes        # só calcula

    html = cliente.get(f"/me/{cid}").text
    assert "Frete FOB" in html and "itens prontos" in html
    assert 'id="linha-' in html and "/linha/" in html
    assert cliente.get(f"/me/{cid}/linha/99999").status_code == 404


def test_previa_pede_login(cliente):
    cliente.cookies.clear()
    assert cliente.get("/me/1/linha/10").status_code == 401


def test_login_sem_robo_liberado_nao_mostra_salvar_nem_limpar(monkeypatch, tmp_path, cliente,
                                                             nestle_sem_robo):
    cid = me_ui.banco.me_criar("nestle_ventura", 23050183, status="pendente")
    monkeypatch.setattr(me_ui, "LEITOR", lambda conta, n: [
        (FIX / "edp_23050183.html").read_text(encoding="utf-8")])
    me_ui.carregar_itens(cid)
    html = cliente.get(f"/me/{cid}").text
    assert 'value="salvar" disabled' in html and 'value="dry_run" class="botao2" disabled' in html
    assert "Limpar no ME" not in html
    assert "O robô ainda não preenche este login" in html


def test_busca_pelo_numero_da_cotacao(cliente):
    cliente.post("/me/atualizar")
    tudo = cliente.get("/me").text
    assert "23049227" in tudo and "23052403" in tudo
    html = cliente.get("/me", params={"numero": "2304922"}).text      # pedaço do número
    assert "23049227" in html and "23052403" not in html
    assert 'name="numero" value="2304922"' in html and "limpar busca" in html
    assert "Nenhuma cotação com o número 999" in cliente.get("/me", params={"numero": "999"}).text
    # Só dígitos: o resto some antes de filtrar (e nada entra cru no HTML).
    sujo = cliente.get("/me", params={"numero": "<b>2305</b>"}).text
    assert 'value="2305"' in sujo and "<b>2305" not in sujo and "23052403" in sujo


def test_nomes_dos_logins_compartilhados():
    assert L.de("nestle_ventura").rotulo == "Nestlé e EDP · VENTURA"
    assert L.de("edp_alianca").rotulo == "EDP e WEG · ALIANÇA"


def test_alpek_aparece_como_nao_atendemos_e_o_robo_nem_abre(cliente, robo):
    from mercado_eletronico import regras as R
    assert R.nao_atendemos("ALPEK POLYESTER") and not R.nao_atendemos("Samarco")
    cid = me_ui.banco.me_criar("nestle_uniao", 23065661, status="pendente",
                               empresa="ALPEK POLYESTER")
    assert "não atendemos" in cliente.get("/me").text
    assert "Não atendemos este comprador." in cliente.get(f"/me/{cid}").text
    assert "Não atendemos" in me_ui.mandar_robo(cid, "enzo", dry_run=False)
    assert robo.chamadas == []
