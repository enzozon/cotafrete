"""A cópia de segurança do banco — e a armadilha que ela existe para evitar.

O banco roda em WAL (`core/banco.py`: `PRAGMA journal_mode = WAL`). Nesse
modo o que acabou de ser gravado ainda está em `cotafrete.db-wal`, e o
arquivo `.db` sozinho está ATRASADO.

O teste central deste arquivo é o `test_copia_burra_perde_o_que_esta_no_wal`:
ele prova que o jeito óbvio — copiar o arquivo — produz um banco que abre
normalmente e ainda assim está **sem as cotações mais recentes**. Sem essa
prova, o teste do jeito certo não valeria nada: passaria mesmo que a
implementação fosse um `shutil.copy`.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core import backup
from core.banco import CAMPOS_CARGA, Banco
from tests.test_banco import _carga


def _contar(caminho: Path) -> int:
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM cotacao").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def banco_com_wal(tmp_path):
    """Um banco com linhas gravadas e uma conexão AINDA ABERTA.

    A conexão aberta é o ponto: enquanto ela existe, o SQLite não dobra o WAL
    de volta no `.db`. É o estado da VM em horário comercial, com o servidor
    no ar e vendedores cotando."""
    caminho = tmp_path / "cotafrete.db"
    db = Banco(caminho)
    db.salvar_cotacao("enzo", _carga())            # esta ja foi para o .db

    con = sqlite3.connect(caminho)
    con.execute("PRAGMA journal_mode = WAL")
    colunas = ["usuario", "criado_em", *CAMPOS_CARGA]
    marcas = ", ".join("?" * len(colunas))
    for i in range(3):                             # estas ficam no WAL
        con.execute(
            f"INSERT INTO cotacao ({', '.join(colunas)}) VALUES ({marcas})",
            ["leandro", f"2026-09-14T10:0{i}:00", *["x"] * len(CAMPOS_CARGA)])
    con.commit()

    yield caminho, con
    con.close()


# --------------------------------------------------- a armadilha, provada
def test_copia_burra_perde_o_que_esta_no_wal(banco_com_wal, tmp_path):
    """O jeito óbvio falha, e falha CALADO.

    Se um dia este teste parar de falhar do jeito descrito, é porque o banco
    deixou de usar WAL — e aí o aviso no topo de core/backup.py precisa ser
    relido, não apagado."""
    caminho, _con = banco_com_wal
    burra = tmp_path / "copia-burra.db"
    shutil.copy(caminho, burra)

    assert _contar(caminho) == 4, "o banco de verdade tem as quatro"
    assert _contar(burra) == 1, (
        "a cópia crua deveria estar atrasada — só com o que já tinha sido "
        "dobrado no .db")


def test_a_copia_boa_pega_o_que_esta_no_wal(banco_com_wal, tmp_path):
    """O mesmo cenário, pelo caminho certo: nada se perde."""
    caminho, _con = banco_com_wal

    arquivo, quantas = backup.copiar(caminho, tmp_path / "saida")

    assert quantas == 4
    assert _contar(arquivo) == 4


# ------------------------------------------------------- o feijão com arroz
def test_a_copia_tem_o_mesmo_conteudo(tmp_path):
    db = Banco(tmp_path / "cotafrete.db")
    cid = db.salvar_cotacao("enzo", _carga(material="geladeira"))
    db.salvar_resultado(cid, "camilo", status="cotado")

    arquivo, _ = backup.copiar(tmp_path / "cotafrete.db", tmp_path / "saida")

    con = sqlite3.connect(f"file:{arquivo}?mode=ro", uri=True)
    try:
        assert con.execute(
            "SELECT material FROM cotacao WHERE id = ?", (cid,)
        ).fetchone()[0] == "geladeira"
        assert con.execute(
            "SELECT transportadora FROM resultado WHERE cotacao_id = ?", (cid,)
        ).fetchone()[0] == "camilo"
    finally:
        con.close()


def test_a_copia_e_um_arquivo_so(banco_com_wal, tmp_path):
    """Sem isto a cópia nasce em WAL (herdado do original) e ganha `-wal` e
    `-shm` do lado assim que alguém a abre. Dois estragos: a faxina não
    reconhece esses laterais e eles sobram órfãos, e quem leva o backup
    embora leva só o `.db` — achando que levou tudo."""
    caminho, _con = banco_com_wal
    saida = tmp_path / "saida"

    arquivo, _ = backup.copiar(caminho, saida)

    assert [a.name for a in saida.iterdir()] == [arquivo.name]


def test_nao_precisa_parar_o_servidor(banco_com_wal, tmp_path):
    """Backup que exige parar o sistema é backup que ninguém faz. Aqui a
    conexão do "servidor" segue aberta e gravando."""
    caminho, con = banco_com_wal

    arquivo, _ = backup.copiar(caminho, tmp_path / "saida")

    con.execute("INSERT INTO cotacao (usuario, criado_em, cep_origem, "
                "cep_destino, peso_kg, quantidade, comprimento_cm, "
                "largura_cm, altura_cm, valor_nf) "
                "VALUES ('novo','2026-09-14T11:00:00','1','2','1',1,1,1,1,'1')")
    con.commit()

    assert arquivo.exists(), "a cópia saiu com o banco em uso"
    assert _contar(caminho) == 5, "e o original continuou aceitando escrita"


def test_banco_que_nao_existe_avisa_em_vez_de_criar_vazio(tmp_path):
    """Sem isto, um caminho errado geraria uma cópia de 0 cotações todo dia —
    e ninguém perceberia até precisar restaurar."""
    with pytest.raises(FileNotFoundError):
        backup.copiar(tmp_path / "nao-existe.db", tmp_path / "saida")


def test_a_copia_e_conferida_e_a_incompleta_e_recusada(tmp_path):
    """`_conferir` é o que separa "arquivo gravado" de "backup". Cópia com
    menos cotações do que o banco tinha significa que faltou o WAL."""
    db = Banco(tmp_path / "cotafrete.db")
    db.salvar_cotacao("enzo", _carga())
    arquivo, _ = backup.copiar(tmp_path / "cotafrete.db", tmp_path / "saida")

    with pytest.raises(RuntimeError, match="WAL"):
        backup._conferir(arquivo, minimo_de_cotacoes=99)


# ----------------------------------------------------------------- faxina
def _falsa(pasta: Path, quando: datetime) -> Path:
    arquivo = pasta / quando.strftime(backup.MOLDE_NOME)
    arquivo.write_bytes(b"nao importa o conteudo")
    return arquivo


def test_faxina_mantem_as_mais_novas(tmp_path):
    hoje = datetime(2026, 9, 14, 3, 0)
    for dias in range(6):
        _falsa(tmp_path, hoje - timedelta(days=dias))

    assert backup.limpar_antigas(tmp_path, manter=3) == 3

    sobraram = sorted(a.name for a in tmp_path.iterdir())
    assert sobraram == ["cotafrete-20260912-0300.db",
                        "cotafrete-20260913-0300.db",
                        "cotafrete-20260914-0300.db"]


def test_faxina_nao_toca_no_que_nao_e_dela(tmp_path):
    """A pasta de backup pode ser um compartilhamento com outras coisas
    dentro. Apagar arquivo alheio seria estrago, não faxina."""
    _falsa(tmp_path, datetime(2026, 1, 1, 3, 0))
    _falsa(tmp_path, datetime(2026, 9, 14, 3, 0))
    alheio = tmp_path / "contrato-transportadora.pdf"
    alheio.write_bytes(b"%PDF")
    manual = tmp_path / "cotafrete-antes-da-migracao.db"
    manual.write_bytes(b"copia feita a mao")

    backup.limpar_antigas(tmp_path, manter=1)

    assert alheio.exists()
    assert manual.exists(), "nome fora do molde não é cópia automática"


def test_faxina_em_pasta_que_ainda_nao_existe(tmp_path):
    assert backup.limpar_antigas(tmp_path / "ainda-nao", manter=3) == 0


# ------------------------------------------------------- espelho de prints
def _print_falso(pasta: Path, caminho: str, conteudo: bytes = b"\x89PNG-falso"):
    arquivo = pasta / caminho
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_bytes(conteudo)
    return arquivo


def test_o_espelho_copia_os_prints_das_duas_pastas(tmp_path):
    """São duas: `teste_real/`, onde as transportadoras gravam, e `runs/`, o
    workdir do fluxo assistido. A documentação citava só a segunda."""
    tr = tmp_path / "teste_real"
    ru = tmp_path / "runs"
    _print_falso(tr, "generoso/20260917-100000/resultado.png")
    _print_falso(ru, "20260917-100000/dv_preenchido.png")
    destino = tmp_path / "rede"

    copiados, ja_tinha = backup.espelhar_evidencias(destino, (tr, ru))

    assert (copiados, ja_tinha) == (2, 0)
    assert (destino / "evidencias/teste_real/generoso/20260917-100000/"
                      "resultado.png").exists()
    assert (destino / "evidencias/runs/20260917-100000/"
                      "dv_preenchido.png").exists()


def test_rodar_de_novo_nao_recopia_o_que_ja_esta_la(tmp_path):
    """Sem isto, cada backup diário recopiaria 90 MB de print que não mudou."""
    tr = tmp_path / "teste_real"
    _print_falso(tr, "camilo/20260917-100000/resultado.png")
    destino = tmp_path / "rede"
    backup.espelhar_evidencias(destino, (tr,))

    copiados, ja_tinha = backup.espelhar_evidencias(destino, (tr,))

    assert (copiados, ja_tinha) == (0, 1)


def test_o_espelho_guarda_o_print_que_a_faxina_local_apagou(tmp_path):
    """O ponto da função. A faxina de 30 dias do core/evidencias.py é gestão
    de espaço; sem espelho, a prova do preço vai junto com ela."""
    tr = tmp_path / "teste_real"
    antigo = _print_falso(tr, "jadlog/20260101-090000/resultado.png")
    destino = tmp_path / "rede"
    backup.espelhar_evidencias(destino, (tr,))

    antigo.unlink()                       # a faxina passou
    backup.espelhar_evidencias(destino, (tr,))

    assert (destino / "evidencias/teste_real/jadlog/20260101-090000/"
                      "resultado.png").exists(), "o espelho nao apaga nada"


def test_copia_interrompida_e_refeita(tmp_path):
    """Arquivo truncado no destino (queda de rede no meio) precisa ser
    copiado de novo, senão fica um print pela metade para sempre."""
    tr = tmp_path / "teste_real"
    _print_falso(tr, "braspress/20260917-100000/r.png", b"conteudo-inteiro")
    destino = tmp_path / "rede"
    pela_metade = destino / "evidencias/teste_real/braspress/20260917-100000/r.png"
    pela_metade.parent.mkdir(parents=True)
    pela_metade.write_bytes(b"cont")

    copiados, _ = backup.espelhar_evidencias(destino, (tr,))

    assert copiados == 1
    assert pela_metade.read_bytes() == b"conteudo-inteiro"


def test_pasta_de_print_que_nao_existe_nao_atrapalha(tmp_path):
    """Numa máquina que nunca cotou, `runs/` não existe. Isso não pode
    derrubar o backup do banco."""
    copiados, ja_tinha = backup.espelhar_evidencias(
        tmp_path / "rede", (tmp_path / "nao-existe",))

    assert (copiados, ja_tinha) == (0, 0)


# ------------------------------------------------------------- o destino
def test_o_destino_sai_da_variavel_de_ambiente(monkeypatch, tmp_path):
    """O lugar certo é FORA da VM, e isso muda de empresa para empresa — por
    isso configuração, e não caminho escrito no código."""
    monkeypatch.setenv(backup.VARIAVEL_DESTINO, str(tmp_path / "rede"))

    assert backup.destino_configurado() == tmp_path / "rede"


def test_sem_variavel_cai_no_padrao(monkeypatch):
    monkeypatch.delenv(backup.VARIAVEL_DESTINO, raising=False)

    assert backup.destino_configurado() == backup.DESTINO_PADRAO
