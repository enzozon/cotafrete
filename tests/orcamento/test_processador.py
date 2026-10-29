import json
import os
import time
from pathlib import Path

import pytest

from orcamento import processador as proc
from orcamento.config import Config
from orcamento.ia import Ajudantes
from orcamento.processador import Cliente, Produto, arquivos_prontos, processar_arquivo, processar_pasta
from tests.orcamento.hse_falso import CLIENTE_VENTURA, MOUSE, HseFalso
from tests.orcamento.planilhas.gerar import NOVO, VARIANTES, criar

ESCRITA = {"cadastrar_produto", "montar_orcamento", "salvar_orcamento", "baixar_dav"}


def cfg(tmp_path: Path, dry_run: bool) -> Config:
    pasta = tmp_path / "ORCAMENTO"
    pasta.mkdir(exist_ok=True)
    prog = tmp_path / "prog"
    prog.mkdir(exist_ok=True)
    return Config(usuario="u", senha="s", client_id="ventura", pasta=pasta, dry_run=dry_run,
                  headless=True, intervalo_min=5, pasta_programa=prog)


def planilha(c: Config, celulas: dict | None = None, nome="orc.xlsx", velha=True) -> Path:
    p = criar(c.pasta, celulas, nome)
    if velha:
        t = time.time() - 600
        os.utime(p, (t, t))
    return p


def txt(c: Config, sub: str, nome="orc.txt") -> str:
    return (c.pasta / sub / nome).read_text(encoding="utf-8-sig")


# --- regras de produto -------------------------------------------------------

def test_codigo_ativo_real_processa_tudo(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {"A2": "IGNORADA", "L2": "123"})
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "PROCESSADOS"
    t = txt(c, "PROCESSADOS")
    assert "Item 1: usou produto existente 13370 - DELL MOUSE OPTICO MS116 (pelo código informado)" in t
    assert "orçamento 55555" in t
    assert not p.exists() and (c.pasta / "PROCESSADOS" / "orc.xlsx").exists()
    dav = c.pasta / "DAVs" / "DAV_55555_VENTURA COMERCIO VAREJISTA DE TECNOLOGIA LTDA.pdf"
    assert dav.exists()
    assert ("montar_orcamento", "18373", [(1, "13370")], True) in hse.chamadas
    assert "cadastrar_produto" not in hse.nomes()


def test_codigo_inativo_erro(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c)
    hse = HseFalso(produtos=[Produto("13370", "DELL MOUSE OPTICO MS116 (INATIVO)", False)])
    assert processar_arquivo(p, c, hse) == "ERRO"
    assert "Item 1: ERRO - código 13370 está inativo" in txt(c, "ERRO")
    assert not ESCRITA & set(hse.nomes())
    assert (c.pasta / "ERRO" / "orc.xlsx").exists()


def test_codigo_inexistente_erro(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {"K2": 99999})
    assert processar_arquivo(p, c, HseFalso()) == "ERRO"
    assert "código 99999 não encontrado" in txt(c, "ERRO")


def test_descricao_um_resultado(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {"K2": None, "A2": "dell  mouse óptico ms116"})
    assert processar_arquivo(p, c, HseFalso()) == "PROCESSADOS"
    assert "13370 - DELL MOUSE OPTICO MS116 (encontrado pela descrição)" in txt(c, "PROCESSADOS")


def test_descricao_ignora_inativo_e_parecido(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {"K2": None, "A2": "DELL MOUSE OPTICO MS116"})
    hse = HseFalso(produtos=[MOUSE, Produto("1", "DELL MOUSE OPTICO MS116 (INATIVO)", False),
                             Produto("2", "DELL MOUSE OPTICO MS116 PRETO", True)])
    assert processar_arquivo(p, c, hse) == "PROCESSADOS"


def test_descricao_duplicada_erro(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, VARIANTES["descricao_duplicada"])
    hse = HseFalso(produtos=[MOUSE, Produto("11", "MOUSE DUPLICADO", True), Produto("12", "Mouse Duplicado", True)])
    assert processar_arquivo(p, c, hse) == "ERRO"
    t = txt(c, "ERRO")
    assert "Item 2: ERRO" in t and "11, 12" in t and "CÓDIGO HSE" in t


def test_produto_novo_real_cadastra(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, VARIANTES["completa"])
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "PROCESSADOS"
    assert ("cadastrar_produto", "PRODUTO TESTE ROBO", 2, True) in hse.chamadas
    assert "Item 2: CADASTROU produto novo 90001 - PRODUTO TESTE ROBO | NCM 84716053" in txt(c, "PROCESSADOS")
    assert ("montar_orcamento", "18373", [(1, "13370"), (2, "90001")], True) in hse.chamadas


def test_novo_sem_ncm_erro_sem_escrita(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, VARIANTES["novo_sem_ncm"])
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "ERRO"
    assert "Item 2: ERRO - produto novo sem NCM" in txt(c, "ERRO")
    assert not ESCRITA & set(hse.nomes())


def test_acha_pela_coluna_o_quando_a_nao_casa(tmp_path):
    # produto cadastrado antes pelo robô com a descrição da coluna O: não pode duplicar
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {**NOVO, "A3": "TEXTO LONGO DO FORNECEDOR", "O3": "CABO HDMI 2M"})
    hse = HseFalso(produtos=[MOUSE, Produto("76627", "CABO HDMI 2M", True)])
    assert processar_arquivo(p, c, hse) == "PROCESSADOS"
    assert "Item 2: usou produto existente 76627 - CABO HDMI 2M (encontrado pela descrição)" in txt(c, "PROCESSADOS")
    assert "cadastrar_produto" not in hse.nomes()


def test_ia_resume_descricao_longa_e_cadastra(tmp_path, monkeypatch):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {**NOVO, "A3": "TEXTO DO FORNECEDOR " * 10})
    monkeypatch.setattr(proc, "ajudantes", lambda cfg_: Ajudantes(resumir=lambda texto: "CABO HDMI 2M"))
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "PROCESSADOS"
    assert ("cadastrar_produto", "CABO HDMI 2M", 1, True) in hse.chamadas
    t = txt(c, "PROCESSADOS")
    assert "Item 2: descrição de cadastro resumida por IA: CABO HDMI 2M" in t
    assert "Item 2: CADASTROU produto novo 90001 - CABO HDMI 2M" in t


def test_ia_resumo_ja_existente_nao_duplica(tmp_path, monkeypatch):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {**NOVO, "A3": "TEXTO DO FORNECEDOR " * 10})
    monkeypatch.setattr(proc, "ajudantes", lambda cfg_: Ajudantes(resumir=lambda texto: "CABO HDMI 2M"))
    hse = HseFalso(produtos=[MOUSE, Produto("555", "CABO HDMI 2M", True)])
    assert processar_arquivo(p, c, hse) == "PROCESSADOS"
    assert "cadastrar_produto" not in hse.nomes()


def test_novo_com_referencia_ja_cadastrada_vira_erro(tmp_path, monkeypatch):
    # visto no DRY_RUN real: o resumo da IA não bate com a descrição do 76627, mas o modelo MDRT572EVD013 sim
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {**NOVO, "A3": "REFRIGERADOR TEXTO LONGO DO FORNECEDOR MIDEA / MDRT572EVD013 " * 3})
    monkeypatch.setattr(proc, "ajudantes", lambda cfg_: Ajudantes(resumir=lambda texto: "REFRIGERADOR MIDEA MDRT572EVD013 305L"))
    hse = HseFalso(produtos=[MOUSE, Produto("76627", "REFRIGERADOR FROST FREE INOX 2 PORTAS MIDEA MDRT572EVD013", True)])
    assert processar_arquivo(p, c, hse) == "ERRO"
    t = txt(c, "ERRO")
    assert "MDRT572EVD013" in t and "76627" in t and "CÓDIGO HSE" in t
    assert "cadastrar_produto" not in hse.nomes()


def test_referencia_curta_ou_so_numero_nao_bloqueia(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {**NOVO, "A3": "CABO HDMI 2M 127/220V 1500"})
    hse = HseFalso(produtos=[MOUSE, Produto("9", "FONTE 1500 220V", True)])
    assert processar_arquivo(p, c, hse) == "PROCESSADOS"


def test_ia_falhou_mantem_erro_de_descricao(tmp_path, monkeypatch):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {**NOVO, "A3": "TEXTO DO FORNECEDOR " * 10})
    monkeypatch.setattr(proc, "ajudantes", lambda cfg_: Ajudantes(resumir=lambda texto: None))
    assert processar_arquivo(p, c, HseFalso()) == "ERRO"
    assert "DESCRIÇÃO P/ CADASTRO com 199 caracteres" in txt(c, "ERRO")  # espaço final é cortado


SO_A_B_C = {"A3": "REFRIGERADOR FROST FREE INOX MIDEA XPTO99 305L", "B3": 1, "C3": 3043}


def test_produto_novo_so_com_descricao_e_custo(tmp_path, monkeypatch):
    # vendedor preenche só A, B, C: marca vem da descrição, grupo e NCM da IA
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, SO_A_B_C)
    monkeypatch.setattr(proc, "ajudantes", lambda cfg_: Ajudantes(
        grupo=lambda desc, grupos: "ELETRODOMÉSTICOS", ncm=lambda desc: "84181000"))
    hse = HseFalso(ncms=("84181000",))
    assert processar_arquivo(p, c, hse) == "PROCESSADOS"
    t = txt(c, "PROCESSADOS")
    assert "Item 2: marca encontrada na descrição: MIDEA" in t
    assert "Item 2: grupo escolhido por IA: ELETRODOMÉSTICOS" in t
    assert "Item 2: NCM sugerido por IA: 84181000 (confira antes de faturar)" in t
    assert ("Item 2: CADASTROU produto novo 90001 - REFRIGERADOR FROST FREE INOX MIDEA XPTO99 305L | NCM 84181000 "
            "| Origem 0 | ICMS 17% | custo R$ 3.043,00 | grupo ELETRODOMÉSTICOS | marca MIDEA") in t


def test_ncm_da_ia_que_nao_existe_no_hse_vira_erro(tmp_path, monkeypatch):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, SO_A_B_C)
    monkeypatch.setattr(proc, "ajudantes", lambda cfg_: Ajudantes(
        grupo=lambda desc, grupos: "ELETRODOMÉSTICOS", ncm=lambda desc: "99999999"))
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "ERRO"
    t = txt(c, "ERRO")
    assert "NCM sugerido por IA (99999999) não existe no HSE" in t and "sem NCM" in t
    assert "cadastrar_produto" not in hse.nomes()


def test_marca_ambigua_ou_ausente_continua_obrigatoria(tmp_path, monkeypatch):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {**SO_A_B_C, "A3": "REFRIGERADOR MIDEA OU LG XPTO99 305L"})
    monkeypatch.setattr(proc, "ajudantes", lambda cfg_: Ajudantes(
        grupo=lambda desc, grupos: "ELETRODOMÉSTICOS", ncm=lambda desc: "84716053"))
    assert processar_arquivo(p, c, HseFalso()) == "ERRO"
    assert "sem MARCA" in txt(c, "ERRO")


def test_marca_nao_casa_pedaco_de_palavra(tmp_path):
    assert proc.detectar_marca("CABO HDMI DELLAS", ["DELL", "LG"]) is None
    assert proc.detectar_marca("MOUSE dell óptico", ["DELL", "LG"]) == "DELL"


def test_sem_custo_nao_gasta_ia(tmp_path, monkeypatch):
    c = cfg(tmp_path, dry_run=False)
    chamadas = []
    p = planilha(c, {**SO_A_B_C, "C3": None, "J3": 10})
    monkeypatch.setattr(proc, "ajudantes", lambda cfg_: Ajudantes(
        grupo=lambda d, g: chamadas.append("g"), ncm=lambda d: chamadas.append("n")))
    assert processar_arquivo(p, c, HseFalso()) == "ERRO"
    assert chamadas == []


def test_trava_impede_dois_ciclos_ao_mesmo_tempo(tmp_path):
    c = cfg(tmp_path, dry_run=True)
    planilha(c)
    abertos = []
    fabrica = lambda: abertos.append(1) or HseFalso()
    with proc.trava(c) as conseguiu:
        assert conseguiu
        processar_pasta(c, fabrica)  # outro ciclo (o .bat) enquanto este roda
    assert abertos == []
    processar_pasta(c, fabrica)
    assert abertos == [1]


def test_novo_descricao_longa_erro(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {**NOVO, "O3": "X" * 101})
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "ERRO"
    assert "DESCRIÇÃO P/ CADASTRO com 101 caracteres (máximo 100;" in txt(c, "ERRO")
    assert not ESCRITA & set(hse.nomes())


def test_novo_sem_custo_grupo_marca(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {**NOVO, "C3": None, "J3": 10, "P3": None, "Q3": None})
    assert processar_arquivo(p, c, HseFalso()) == "ERRO"
    assert "sem CUSTO, GRUPO, MARCA" in txt(c, "ERRO")


# --- cliente / vendedor ------------------------------------------------------

def test_cliente_por_cnpj_formatado(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {"B31": "12345678000190"})
    hse = HseFalso(clientes=[CLIENTE_VENTURA])
    hse.buscar_cliente = lambda chave: [CLIENTE_VENTURA]
    assert processar_arquivo(p, c, hse) == "PROCESSADOS"


def test_cliente_parecido_nao_casa(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {"B31": 1837})
    hse = HseFalso()
    hse.buscar_cliente = lambda chave: [CLIENTE_VENTURA]  # busca do HSE é "contém"
    assert processar_arquivo(p, c, hse) == "ERRO"
    assert "Cliente 1837 não encontrado" in txt(c, "ERRO")


def test_vendedor_inexistente(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {"B33": "FULANO"})
    assert processar_arquivo(p, c, HseFalso()) == "ERRO"
    assert "Vendedor 'FULANO' não encontrado" in txt(c, "ERRO")


def test_erro_offline_nao_chama_hse(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {"B31": None})
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "ERRO"
    assert hse.chamadas == []
    assert "Cliente (B31) é obrigatório" in txt(c, "ERRO")


# --- DRY_RUN -----------------------------------------------------------------

def test_dry_run_nao_salva_nem_move(tmp_path):
    c = cfg(tmp_path, dry_run=True)
    p = planilha(c, VARIANTES["completa"])
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "DRYRUN"
    assert p.exists()
    assert ("cadastrar_produto", "PRODUTO TESTE ROBO", 2, False) in hse.chamadas
    assert ("montar_orcamento", "18373", [(1, "13370"), (2, None)], False) in hse.chamadas
    assert "salvar_orcamento" not in hse.nomes()
    t = txt(c, "DRYRUN")
    assert "Item 2: [DRY_RUN] cadastraria produto novo - PRODUTO TESTE ROBO" in t
    assert "Item 1: usou produto existente 13370" in t


def test_dry_run_erro_vai_para_dryrun(tmp_path):
    c = cfg(tmp_path, dry_run=True)
    p = planilha(c, {"B31": None})
    assert processar_arquivo(p, c, HseFalso()) == "DRYRUN"
    assert p.exists()
    assert "Cliente (B31)" in txt(c, "DRYRUN")


def test_dry_run_nao_repete(tmp_path):
    c = cfg(tmp_path, dry_run=True)
    planilha(c)
    hses = []
    fabrica = lambda: hses.append(HseFalso()) or hses[-1]
    processar_pasta(c, fabrica)
    processar_pasta(c, fabrica)
    assert len(hses) == 1  # 2º ciclo nem abre o navegador
    estado = json.loads((c.pasta_programa / "dryrun_estado.json").read_text(encoding="utf-8"))
    assert [v["arquivo"] for v in estado.values()] == ["orc.xlsx"]


# --- falhas ------------------------------------------------------------------

def test_falha_ao_salvar_cancela_rascunho(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, VARIANTES["completa"])
    hse = HseFalso(falhar_em={"salvar_orcamento"})
    assert processar_arquivo(p, c, hse) == "ERRO"
    assert "cancelar_rascunho" in hse.nomes()
    t = txt(c, "ERRO")
    assert "rascunho 77777 ficou vazio" in t
    assert "90001" in t  # produto cadastrado continua no HSE e é informado


def test_salvo_incerto_nao_cancela_e_nao_reprocessa(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c)
    conteudo = p.read_bytes()
    hse = HseFalso(falhar_em={"salvo_incerto"})
    assert processar_arquivo(p, c, hse) == "ERRO"
    assert "cancelar_rascunho" not in hse.nomes()
    t = txt(c, "ERRO")
    assert "55555" in t and "NÃO reenvie" in t
    p.write_bytes(conteudo)  # alguém devolve a mesma planilha para a pasta
    assert processar_arquivo(p, c, HseFalso()) == "ADIADO"


def test_produto_novo_repetido_cadastra_uma_vez(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    repetido = {k.replace("3", "4"): v for k, v in NOVO.items()}
    p = planilha(c, {**NOVO, **repetido, "B4": 2})
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "PROCESSADOS"
    assert [n for n in hse.nomes() if n == "cadastrar_produto"] == ["cadastrar_produto"]
    assert ("montar_orcamento", "18373", [(1, "13370"), (2, "90001"), (3, "90001")], True) in hse.chamadas
    assert "Item 3: usou produto existente 90001 - PRODUTO TESTE ROBO (cadastrado no item 2)" in txt(c, "PROCESSADOS")


def test_um_arquivo_com_problema_nao_trava_os_outros(tmp_path, monkeypatch):
    c = cfg(tmp_path, dry_run=False)
    planilha(c, nome="a.xlsx")
    planilha(c, nome="b.xlsx")
    original = proc.processar_arquivo
    feitos = []

    def falha_no_a(path, cfg_, hse):
        if path.name == "a.xlsx":
            raise OSError("rede caiu no meio")
        feitos.append(path.name)
        return original(path, cfg_, hse)

    monkeypatch.setattr(proc, "processar_arquivo", falha_no_a)
    processar_pasta(c, HseFalso)
    assert feitos == ["b.xlsx"]


def test_relatorio_que_nao_grava_nao_derruba(tmp_path, monkeypatch):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c, {"B31": None})
    monkeypatch.setattr(proc.Relatorio, "gravar", lambda self, d: (_ for _ in ()).throw(OSError("sem acesso")))
    assert processar_arquivo(p, c, HseFalso()) == "ERRO"


def test_falha_no_dav_nao_cancela_orcamento_salvo(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c)
    hse = HseFalso(falhar_em={"baixar_dav"})
    assert processar_arquivo(p, c, hse) == "ERRO"
    assert "cancelar_rascunho" not in hse.nomes()
    assert "orçamento 55555 FOI SALVO" in txt(c, "ERRO")


def test_hse_fora_na_validacao_adia(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c)
    assert processar_arquivo(p, c, HseFalso(indisponivel_em={"buscar_cliente"})) == "ADIADO"
    assert p.exists()
    assert not (c.pasta / "ERRO" / "orc.txt").exists()


def test_login_falhou_nao_mexe_em_nada(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c)
    processar_pasta(c, lambda: HseFalso(indisponivel_em={"login"}))
    assert p.exists()


def test_arquivo_bloqueado_adia(tmp_path, monkeypatch):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c)
    monkeypatch.setattr(proc, "_livre", lambda path: False)
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "ADIADO"
    assert hse.chamadas == [] and p.exists()


def test_real_nao_reprocessa_mesmo_arquivo(tmp_path, monkeypatch):
    c = cfg(tmp_path, dry_run=False)
    p = planilha(c)
    conteudo = p.read_bytes()
    monkeypatch.setattr(proc, "_mover", lambda origem, pasta: (_ for _ in ()).throw(PermissionError("travado")))
    assert processar_arquivo(p, c, HseFalso()) == "PROCESSADOS"
    assert p.read_bytes() == conteudo
    hse = HseFalso()
    assert processar_arquivo(p, c, hse) == "ADIADO"
    assert hse.chamadas == []


def test_nome_destino_nao_sobrescreve(tmp_path):
    c = cfg(tmp_path, dry_run=False)
    (c.pasta / "ERRO").mkdir()
    (c.pasta / "ERRO" / "orc.xlsx").write_bytes(b"antigo")
    p = planilha(c, {"B31": None})
    processar_arquivo(p, c, HseFalso())
    assert (c.pasta / "ERRO" / "orc.xlsx").read_bytes() == b"antigo"
    assert (c.pasta / "ERRO" / "orc_2.xlsx").exists()
    assert (c.pasta / "ERRO" / "orc_2.txt").exists()


# --- seleção de arquivos -----------------------------------------------------

def test_arquivos_prontos(tmp_path):
    c = cfg(tmp_path, dry_run=True)
    velho = planilha(c, nome="a.xlsx")
    planilha(c, nome="~$a.xlsx")
    planilha(c, nome="PLANILHA-BASE-v3.xlsx")  # modelo que fica na pasta para as pessoas copiarem
    planilha(c, nome="novo.xlsx", velha=False)
    (c.pasta / "x.txt").write_text("x")
    (c.pasta / "ERRO").mkdir()
    planilha(c, nome="b.xlsx").rename(c.pasta / "ERRO" / "b.xlsx")
    assert arquivos_prontos(c.pasta, time.time()) == [velho]
    assert len(arquivos_prontos(c.pasta, time.time(), estabilidade=0)) == 2  # gerar_orcamento.bat


def test_planilha_salva_na_pasta_do_modelo_tambem_conta(tmp_path):
    c = cfg(tmp_path, dry_run=True)
    (c.pasta / "PLANILHA").mkdir()
    planilha(c, nome="PLANILHA-BASE-v3.xlsx").rename(c.pasta / "PLANILHA" / "PLANILHA-BASE-v3.xlsx")
    planilha(c, nome="ORC-X.xlsx").rename(c.pasta / "PLANILHA" / "ORC-X.xlsx")
    assert arquivos_prontos(c.pasta, time.time()) == [c.pasta / "PLANILHA" / "ORC-X.xlsx"]


def test_sanitizar_nome():
    assert proc.sanitizar('A/B: "C" <D>?') == "AB C D"


def test_marca_de_uma_letra_nao_conta():
    # DAV 22 (29/10/2026): o HSE tem marcas "C" e "X"; o robô achava o "C" de "C/ TAMPA" e o "X" de "26 x 34"
    marcas = ["C", "X", "LG", "LARPLASTICO"]
    assert proc.detectar_marca("CAIXA ORGANIZADORA C/ TAMPA AZUL 26L LARPLASTICO", marcas) == "LARPLASTICO"
    assert proc.detectar_marca("Caixa Organizadora com Tampa 26 x 34 Cm 25 Litros", marcas) is None
    assert proc.detectar_marca("TV LG 43", marcas) == "LG"
