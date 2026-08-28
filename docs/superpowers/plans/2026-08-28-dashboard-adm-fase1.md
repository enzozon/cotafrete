# Dashboard administrativo — Fase 1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma tela `/adm`, protegida por senha, que mostra o que está acontecendo agora, a saúde de cada transportadora e o histórico de cotações de toda a empresa.

**Architecture:** Camada pura (`core/painel.py`) faz as contas sobre o SQLite e devolve `list[dict]`, sem HTML. `web/adm.py` só monta a tela. O layout compartilhado sai de `web/app.py` para `web/layout.py`, o que resolve o import circular e reduz um arquivo que já tem 1753 linhas.

**Tech Stack:** Python 3.14, FastAPI, SQLite (WAL já ligado), pytest, `hmac` da biblioteca padrão. **Nenhuma dependência nova.**

**Spec:** `docs/superpowers/specs/2026-08-28-dashboard-adm-design.md`

## Global Constraints

- **Nenhuma biblioteca nova.** Gráficos são CSS e SVG gerados em Python.
- **A senha nunca vai para log, HTML ou URL.** Só POST.
- **`banco.buscar_cotacao` e `banco.listar_cotacoes` não mudam.** Continuam travados por usuário; `test_cotacao_de_outro_usuario_nao_abre` tem de continuar passando.
- **Sem `COTAFRETE_ADM_SENHA` no ambiente, `/adm` responde 404.**
- Toda escrita nova no banco é **aditiva**: nenhuma linha existente é alterada ou apagada.
- Comentários e mensagens em português, como o resto do projeto.
- Rodar a suíte com `.venv/Scripts/python.exe -m pytest`.

## Classificação de status (vale para o plano inteiro)

Copiada da spec. Qualquer contagem usa isto:

| status | categoria |
|---|---|
| `cotado` | sucesso |
| `aguardando_retorno` | sucesso |
| `recusado` | recusa |
| `erro` | falha |
| `intervencao_necessaria` | falha |
| `interrompido` | nossa (fora do aproveitamento) |
| qualquer outro | inesperado |

`aproveitamento = sucesso / (sucesso + recusa + falha)`. `interrompido` fica fora do denominador.

Atenção: `interrompido` **não** está em `StatusCotacao`; é string literal gravada em `core/banco.py:299`.

---

### Task 1: Extrair o layout compartilhado

Sem isto, `web/adm.py` importaria de `web/app.py` enquanto `web/app.py` registra as rotas do adm — import circular. É refatoração pura: nenhum comportamento muda.

**Files:**
- Create: `web/layout.py`
- Modify: `web/app.py` (remove `LOGO` da linha 81, `CSS` de 283, `e()` de 471, `pagina()` de 514; importa os quatro de `web.layout`)
- Test: `tests/test_layout.py`

**Interfaces:**
- Consumes: nada
- Produces: `web.layout.LOGO: str`, `web.layout.CSS: str`, `web.layout.e(v) -> str`, `web.layout.pagina(titulo: str, corpo: str, usuario: str | None = None) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_layout.py
"""O casco compartilhado das telas.

Existe como módulo próprio porque web/adm.py precisa dele e web/app.py
registra as rotas do adm — importar um do outro seria circular. De quebra
tira ~200 linhas de um arquivo que tinha 1753."""

from web import layout


def test_a_pagina_monta_o_casco_completo():
    html = layout.pagina("Teste", "<p>oi</p>")

    assert html.startswith("<!doctype html>")
    assert 'lang="pt-BR"' in html
    assert "Teste — Cotafrete" in html
    assert "<p>oi</p>" in html
    assert layout.CSS in html


def test_o_menu_so_aparece_com_usuario():
    """Sem cookie não há para onde navegar — e mostrar 'Sair' para quem não
    entrou confunde."""
    assert "/historico" not in layout.pagina("t", "c")
    assert "/historico" in layout.pagina("t", "c", usuario="enzo")


def test_escapa_html_do_usuario():
    """O nome vem de um formulário aberto. Sem escapar, vira XSS."""
    assert "<script>" not in layout.pagina("t", "c", usuario="<script>x</script>")
    assert layout.e("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_layout.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'web.layout'`

- [ ] **Step 3: Create `web/layout.py`**

Mova, **sem alterar uma linha do conteúdo**, de `web/app.py` para `web/layout.py`: a atribuição de `LOGO` (linha 81), o bloco `CSS = """..."""` (a partir da linha 283), a função `e()` (linha 471) e a função `pagina()` (linha 514). O cabeçalho do módulo novo:

```python
"""O casco visual compartilhado: logo, CSS, escape e a moldura da página.

Vive fora de web/app.py porque web/adm.py precisa das mesmas peças, e
web/app.py registra as rotas do adm — um importar o outro seria circular.

Nada aqui conhece banco, cotação ou transportadora. É só desenho."""

from __future__ import annotations

import html
from pathlib import Path
```

- [ ] **Step 4: Update `web/app.py` to import from layout**

Substitua os quatro blocos removidos por, junto dos outros imports:

```python
from web.layout import CSS, LOGO, e, pagina
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — 505 passed, 1 xfailed, mais os 3 novos = **508 passed**. Qualquer falha aqui significa que a mudança não foi um movimento puro; desfaça e mova de novo sem editar conteúdo.

- [ ] **Step 6: Commit**

```bash
git add web/layout.py web/app.py tests/test_layout.py
git commit -m "refactor: casco visual sai para web/layout.py"
```

---
### Task 2: Guardar a hora da resposta

O adapter já calcula `respondido_em` e joga fora. Cada dia sem esta coluna é um dia de histórico que não volta.

**Files:**
- Modify: `core/banco.py` (`ESQUEMA`, `_migrar`, `salvar_resultado`)
- Modify: `web/app.py` (a chamada de `salvar_resultado` em `_rodar`)
- Test: `tests/test_banco.py`

**Interfaces:**
- Consumes: nada
- Produces: coluna `resultado.respondido_em TEXT`; `Banco.salvar_resultado(..., respondido_em: str | None = None)`

- [ ] **Step 1: Write the failing test**

```python
# acrescentar ao fim de tests/test_banco.py
def test_banco_antigo_ganha_a_coluna_sem_perder_linha(tmp_path):
    """Migração ADITIVA. CREATE TABLE IF NOT EXISTS não altera tabela que já
    existe: sem isto, quem já tem cotafrete.db recebe "table resultado has no
    column named respondido_em" no primeiro INSERT."""
    import sqlite3
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.executescript("""
        CREATE TABLE cotacao (id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL, criado_em TEXT NOT NULL,
            cep_origem TEXT, cep_destino TEXT, peso_kg TEXT,
            quantidade INTEGER, comprimento_cm INTEGER, largura_cm INTEGER,
            altura_cm INTEGER, valor_nf TEXT);
        CREATE TABLE resultado (id INTEGER PRIMARY KEY AUTOINCREMENT,
            cotacao_id INTEGER NOT NULL, transportadora TEXT NOT NULL,
            status TEXT NOT NULL, valor TEXT, protocolo TEXT, prazo TEXT,
            erro TEXT, evidencia TEXT);
        INSERT INTO cotacao (usuario, criado_em) VALUES ('enzo', '2026-08-01T10:00:00');
        INSERT INTO resultado (cotacao_id, transportadora, status)
            VALUES (1, 'camilo', 'cotado');
    """)
    con.commit()
    con.close()

    Banco(caminho)          # abrir já migra

    con = sqlite3.connect(caminho)
    colunas = {r[1] for r in con.execute("PRAGMA table_info(resultado)")}
    assert "respondido_em" in colunas
    assert con.execute("SELECT COUNT(*) FROM resultado").fetchone()[0] == 1, \
        "a migração não pode perder linha"
    con.close()


def test_guarda_a_hora_em_que_a_transportadora_respondeu(tmp_path):
    """Sem isto é impossível saber qual transportadora está lenta — e o
    adapter já calculava o valor para depois descartá-lo."""
    db = Banco(tmp_path / "t.db")
    cotacao_id = db.salvar_cotacao("enzo", CARGA)

    db.salvar_resultado(cotacao_id, "camilo", status="cotado",
                        respondido_em="2026-08-28T14:30:15")

    resultados = db.buscar_cotacao(cotacao_id, "enzo")["resultados"]
    assert resultados[0]["respondido_em"] == "2026-08-28T14:30:15"


def test_resultado_sem_hora_continua_valendo(tmp_path):
    """As 325 linhas que já existem não têm hora. NULL é resposta legítima, e
    a tela precisa mostrar 'sem dados ainda' em vez de fingir zero."""
    db = Banco(tmp_path / "t.db")
    cotacao_id = db.salvar_cotacao("enzo", CARGA)

    db.salvar_resultado(cotacao_id, "camilo", status="cotado")

    assert db.buscar_cotacao(cotacao_id, "enzo")["resultados"][0]["respondido_em"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_banco.py -k "respondido or ganha_a_coluna" -v`
Expected: FAIL — `sqlite3.OperationalError: table resultado has no column named respondido_em`

- [ ] **Step 3: Add the column to the schema and the migration**

Em `core/banco.py`, dentro de `ESQUEMA`, na `CREATE TABLE resultado`, depois de `evidencia TEXT`:

```sql
    -- Quando a transportadora respondeu. NULL nas linhas anteriores a
    -- 28/08/2026, e a tela precisa dizer "sem dados ainda" em vez de zero.
    respondido_em  TEXT
```

Logo abaixo de `CAMPOS_CARGA`, acrescente:

```python
# Colunas de `resultado` que nasceram depois do banco. Mesma razão de
# CAMPOS_CARGA: CREATE TABLE IF NOT EXISTS não altera tabela existente.
CAMPOS_RESULTADO = ("respondido_em",)
```

E em `_migrar`, logo depois do laço de `CAMPOS_CARGA`:

```python
        existentes = {r["name"] for r in con.execute("PRAGMA table_info(resultado)")}
        for coluna in CAMPOS_RESULTADO:
            if coluna not in existentes:
                con.execute(f"ALTER TABLE resultado ADD COLUMN {coluna} TEXT")
```

- [ ] **Step 4: Persist it in `salvar_resultado`**

```python
    def salvar_resultado(self, cotacao_id: int, transportadora: str, *,
                         status: str, valor: Decimal | None = None,
                         protocolo: str | None = None,
                         prazo: str | None = None,
                         erro: str | None = None,
                         evidencia: str | None = None,
                         respondido_em: str | None = None) -> None:
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT INTO resultado (cotacao_id, transportadora, status,"
                " valor, protocolo, prazo, erro, evidencia, respondido_em)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (cotacao_id, transportadora) DO UPDATE SET"
                " status = excluded.status, valor = excluded.valor,"
                " protocolo = excluded.protocolo, prazo = excluded.prazo,"
                " erro = excluded.erro, evidencia = excluded.evidencia,"
                " respondido_em = excluded.respondido_em",
                (cotacao_id, transportadora, status,
                 str(valor) if valor is not None else None,
                 protocolo, prazo, erro, evidencia, respondido_em))
```

- [ ] **Step 5: Pass it from the quotation loop**

Em `web/app.py`, na função `_rodar`, onde `banco.salvar_resultado(...)` grava o resultado, acrescente o argumento:

```python
        respondido_em=(res.respondido_em.isoformat(timespec="seconds")
                       if res.respondido_em else None),
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_banco.py tests/test_web_cotacao.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/banco.py web/app.py tests/test_banco.py
git commit -m "feat: guarda a hora em que cada transportadora respondeu"
```

---
### Task 3: As contas — resumo do dia e saúde das transportadoras

**Files:**
- Create: `core/painel.py`
- Test: `tests/test_painel.py`

**Interfaces:**
- Consumes: `Banco._conectar()` de `core/banco.py`
- Produces:
  - `core.painel.categoria(status: str) -> str` — `"sucesso" | "recusa" | "falha" | "nossa" | "inesperado"`
  - `core.painel.resumo_do_dia(con) -> dict` — chaves `cotacoes`, `com_preco`, `sem_nenhum_preco`, `em_andamento`
  - `core.painel.saude_das_transportadoras(con, dias: int) -> list[dict]` — chaves `transportadora`, `sucesso`, `recusa`, `falha`, `nossa`, `inesperado`, `aproveitamento`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_painel.py
"""As contas do dashboard. Camada PURA: recebe conexão, devolve dicionário.

Nenhum HTML mora aqui, pelo mesmo motivo de carriers/*/mapping.py: o risco
está na conta, e conta se testa sem navegador.

Os números da tela são a razão de a tela existir. Um aproveitamento errado
manda o Enzo cobrar a transportadora errada."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.banco import Banco
from core import painel

CARGA = {"cep_origem": "29105770", "cep_destino": "01310100",
         "cidade_origem": "Vila Velha", "cidade_destino": "São Paulo",
         "peso_kg": "10", "quantidade": 1, "comprimento_cm": 30,
         "largura_cm": 30, "altura_cm": 30, "valor_nf": "1000",
         "material": "PLACA DE VIDEO"}


@pytest.fixture
def db(tmp_path):
    return Banco(tmp_path / "painel.db")


def test_classifica_cada_status_como_a_spec_manda():
    assert painel.categoria("cotado") == "sucesso"
    assert painel.categoria("aguardando_retorno") == "sucesso"
    assert painel.categoria("recusado") == "recusa"
    assert painel.categoria("erro") == "falha"
    assert painel.categoria("intervencao_necessaria") == "falha"
    assert painel.categoria("interrompido") == "nossa"
    assert painel.categoria("coisa_nova") == "inesperado"


def test_aguardando_retorno_e_sucesso_e_nao_falha():
    """A Della Volpe recebeu e o preço vem por e-mail. Contar como falha
    jogaria ela para o vermelho todo dia, sem nada de errado."""
    assert painel.categoria("aguardando_retorno") == "sucesso"


def test_interrompido_fica_fora_do_aproveitamento(db):
    """É o servidor reiniciando no meio — coisa nossa. Descontar isso da
    transportadora seria puni-la por um restart que ela não causou."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado")
    db.salvar_resultado(cid, "jadlog", status="interrompido")

    with db._conectar() as con:
        linhas = {l["transportadora"]: l
                  for l in painel.saude_das_transportadoras(con, dias=30)}

    assert linhas["camilo"]["aproveitamento"] == 1.0
    assert linhas["jadlog"]["nossa"] == 1
    assert linhas["jadlog"]["aproveitamento"] is None, \
        "sem nada no denominador, aproveitamento é desconhecido, não zero"


def test_aproveitamento_conta_recusa_no_denominador(db):
    """Recusa não é defeito, mas também não é preço: entra na conta."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado")
    cid2 = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid2, "camilo", status="recusado")

    with db._conectar() as con:
        linha = painel.saude_das_transportadoras(con, dias=30)[0]

    assert linha["sucesso"] == 1 and linha["recusa"] == 1
    assert linha["aproveitamento"] == 0.5


def test_resumo_conta_cotacao_que_ficou_sem_nenhum_preco(db):
    """A métrica que mais importa: o vendedor ficou na mão."""
    boa = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(boa, "camilo", status="cotado")
    ruim = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(ruim, "camilo", status="erro")
    db.salvar_resultado(ruim, "jadlog", status="recusado")

    with db._conectar() as con:
        r = painel.resumo_do_dia(con)

    assert r["cotacoes"] == 2
    assert r["com_preco"] == 1
    assert r["sem_nenhum_preco"] == 1


def test_banco_vazio_nao_quebra(db):
    """Pasta nova, primeiro dia. A tela precisa abrir mesmo assim."""
    with db._conectar() as con:
        assert painel.saude_das_transportadoras(con, dias=30) == []
        assert painel.resumo_do_dia(con)["cotacoes"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_painel.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'core.painel'`

- [ ] **Step 3: Write `core/painel.py`**

```python
"""As contas do dashboard administrativo.

Camada PURA: recebe uma conexão sqlite3, devolve list[dict] ou dict. Nenhum
HTML — pelo mesmo motivo de carriers/*/mapping.py, o risco mora na conta, e
conta se testa sem navegador.

Só LEITURA. Nada aqui escreve no banco.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

# Como cada status conta. Definição única: sem ela, cada bloco da tela
# poderia contar diferente e os números não fechariam entre si.
#
# `aguardando_retorno` é SUCESSO: a Della Volpe recebeu e o preço vem por
# e-mail. Contar como falha a jogaria para o vermelho todo dia, sem nada de
# errado.
#
# `interrompido` é NOSSO: o servidor reiniciou no meio. Fica fora do
# aproveitamento — punir a transportadora por um restart nosso faria o número
# mentir.
SUCESSO = frozenset({"cotado", "aguardando_retorno"})
RECUSA = frozenset({"recusado"})
FALHA = frozenset({"erro", "intervencao_necessaria"})
NOSSA = frozenset({"interrompido"})


def categoria(status: str) -> str:
    """Status do banco -> categoria da tela. FUNÇÃO PURA."""
    if status in SUCESSO:
        return "sucesso"
    if status in RECUSA:
        return "recusa"
    if status in FALHA:
        return "falha"
    if status in NOSSA:
        return "nossa"
    # Status que ninguém previu aparece como "inesperado" em vez de sumir:
    # esconder o desconhecido foi como "(nenhuma mensagem visível)" nasceu.
    return "inesperado"


def _desde(dias: int) -> str:
    return (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")


def _preco(bruto: str | None) -> Decimal | None:
    if bruto is None:
        return None
    try:
        return Decimal(bruto)
    except InvalidOperation:
        return None


def resumo_do_dia(con: sqlite3.Connection) -> dict:
    """Os números de hoje, para a faixa do topo."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    ids = [r["id"] for r in con.execute(
        "SELECT id FROM cotacao WHERE criado_em LIKE ?", (f"{hoje}%",))]
    if not ids:
        return {"cotacoes": 0, "com_preco": 0, "sem_nenhum_preco": 0,
                "em_andamento": 0}

    marcas = ", ".join("?" * len(ids))
    com_preco = {r["cotacao_id"] for r in con.execute(
        f"SELECT DISTINCT cotacao_id FROM resultado"
        f" WHERE cotacao_id IN ({marcas}) AND status = 'cotado'", ids)}
    respondidas = {r["cotacao_id"] for r in con.execute(
        f"SELECT DISTINCT cotacao_id FROM resultado"
        f" WHERE cotacao_id IN ({marcas})", ids)}

    return {
        "cotacoes": len(ids),
        "com_preco": len(com_preco),
        # Sem NENHUM preço: respondeu alguma coisa e nada virou valor. É a
        # métrica que diz "o vendedor ficou na mão".
        "sem_nenhum_preco": len(respondidas - com_preco),
        "em_andamento": len(set(ids) - respondidas),
    }


def saude_das_transportadoras(con: sqlite3.Connection,
                              dias: int) -> list[dict]:
    """Uma linha por transportadora, da pior para a melhor."""
    linhas: dict[str, dict] = {}
    for r in con.execute(
            "SELECT r.transportadora, r.status FROM resultado r"
            " JOIN cotacao c ON c.id = r.cotacao_id"
            " WHERE c.criado_em >= ?", (_desde(dias),)):
        alvo = linhas.setdefault(r["transportadora"], {
            "transportadora": r["transportadora"], "sucesso": 0,
            "recusa": 0, "falha": 0, "nossa": 0, "inesperado": 0})
        alvo[categoria(r["status"])] += 1

    for alvo in linhas.values():
        base = alvo["sucesso"] + alvo["recusa"] + alvo["falha"]
        # None, não 0: sem nada no denominador o aproveitamento é
        # DESCONHECIDO. Zero diria "nunca acertou", que é outra coisa.
        alvo["aproveitamento"] = alvo["sucesso"] / base if base else None

    return sorted(linhas.values(),
                  key=lambda a: (a["aproveitamento"] is not None,
                                 a["aproveitamento"] or 0))
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_painel.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add core/painel.py tests/test_painel.py
git commit -m "feat: contas do painel - resumo do dia e saude por transportadora"
```

---

### Task 4: As contas — histórico de toda a empresa

**Files:**
- Modify: `core/painel.py`
- Test: `tests/test_painel.py`

**Interfaces:**
- Consumes: `core.painel.categoria` e `core.painel._preco` da Task 3
- Produces: `core.painel.historico(con, *, dias: int = 30, usuario: str | None = None, so_com_falha: bool = False, limite: int = 200) -> list[dict]` — cada item tem `id`, `criado_em`, `usuario`, `rota`, `material`, `melhor_preco`, `contagem` (dict de categoria para int)

- [ ] **Step 1: Write the failing test**

```python
# acrescentar ao fim de tests/test_painel.py
def test_historico_traz_cotacao_de_todos_os_usuarios(db):
    """É a diferença central em relação ao histórico do vendedor, que só
    mostra as dele. Aqui o adm vê a empresa inteira."""
    a = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(a, "camilo", status="cotado", valor=Decimal("100.00"))
    b = db.salvar_cotacao("leandro", CARGA)
    db.salvar_resultado(b, "camilo", status="cotado", valor=Decimal("90.00"))

    with db._conectar() as con:
        linhas = painel.historico(con)

    assert {l["usuario"] for l in linhas} == {"enzo", "leandro"}


def test_historico_mostra_o_melhor_preco_de_cada_cotacao(db):
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado", valor=Decimal("150.00"))
    db.salvar_resultado(cid, "generoso", status="cotado", valor=Decimal("90.50"))

    with db._conectar() as con:
        assert painel.historico(con)[0]["melhor_preco"] == Decimal("90.50")


def test_historico_sem_preco_nenhum_devolve_none_e_nao_zero(db):
    """Zero seria um preço. None é "não teve preço" — coisas diferentes."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="erro", erro="deu ruim")

    with db._conectar() as con:
        assert painel.historico(con)[0]["melhor_preco"] is None


def test_historico_filtra_por_usuario(db):
    db.salvar_cotacao("enzo", CARGA)
    db.salvar_cotacao("leandro", CARGA)

    with db._conectar() as con:
        linhas = painel.historico(con, usuario="leandro")

    assert [l["usuario"] for l in linhas] == ["leandro"]


def test_historico_filtra_so_as_que_tiveram_falha(db):
    """O filtro que o Enzo vai usar mais: mostra só o que deu problema."""
    boa = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(boa, "camilo", status="cotado", valor=Decimal("10.00"))
    ruim = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(ruim, "jadlog", status="erro", erro="timeout")

    with db._conectar() as con:
        linhas = painel.historico(con, so_com_falha=True)

    assert [l["id"] for l in linhas] == [ruim]


def test_historico_vem_do_mais_novo_para_o_mais_velho(db):
    primeiro = db.salvar_cotacao("enzo", CARGA)
    segundo = db.salvar_cotacao("enzo", CARGA)

    with db._conectar() as con:
        assert [l["id"] for l in painel.historico(con)] == [segundo, primeiro]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_painel.py -k historico -v`
Expected: FAIL com `AttributeError: module 'core.painel' has no attribute 'historico'`

- [ ] **Step 3: Implement `historico`**

Acrescente ao fim de `core/painel.py`:

```python
def historico(con: sqlite3.Connection, *, dias: int = 30,
              usuario: str | None = None, so_com_falha: bool = False,
              limite: int = 200) -> list[dict]:
    """As cotações de TODA a empresa, da mais nova para a mais velha.

    É a diferença central em relação a `banco.listar_cotacoes`, que mostra só
    as do próprio vendedor. Aquela função NÃO muda: a garantia dela é da tela
    do vendedor. Esta é outra porta, para outro público — em vez de um
    `if adm` no meio da que já existe."""
    condicoes = ["criado_em >= ?"]
    valores: list = [_desde(dias)]
    if usuario:
        condicoes.append("usuario = ?")
        valores.append(usuario)

    cotacoes = con.execute(
        f"SELECT * FROM cotacao WHERE {' AND '.join(condicoes)}"
        f" ORDER BY id DESC LIMIT ?", [*valores, limite]).fetchall()
    if not cotacoes:
        return []

    ids = [c["id"] for c in cotacoes]
    marcas = ", ".join("?" * len(ids))
    por_cotacao: dict[int, list] = {i: [] for i in ids}
    for r in con.execute(
            f"SELECT cotacao_id, status, valor FROM resultado"
            f" WHERE cotacao_id IN ({marcas})", ids):
        por_cotacao[r["cotacao_id"]].append(r)

    linhas = []
    for c in cotacoes:
        resultados = por_cotacao[c["id"]]
        contagem: dict[str, int] = {}
        for r in resultados:
            chave = categoria(r["status"])
            contagem[chave] = contagem.get(chave, 0) + 1

        if so_com_falha and not contagem.get("falha"):
            continue

        precos = [p for p in (_preco(r["valor"]) for r in resultados)
                  if p is not None]
        linhas.append({
            "id": c["id"],
            "criado_em": c["criado_em"],
            "usuario": c["usuario"],
            "rota": f"{c['cidade_origem'] or c['cep_origem']} -> "
                    f"{c['cidade_destino'] or c['cep_destino']}",
            "material": c["material"],
            # None, não 0: zero seria um preço. Não ter preço é outra coisa.
            "melhor_preco": min(precos) if precos else None,
            "contagem": contagem,
        })
    return linhas
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_painel.py -v`
Expected: PASS — 12 passed

- [ ] **Step 5: Commit**

```bash
git add core/painel.py tests/test_painel.py
git commit -m "feat: historico do painel enxerga a empresa inteira"
```

---
### Task 5: A porta do adm

**Files:**
- Create: `web/adm.py`
- Modify: `web/app.py` (registrar o router)
- Test: `tests/test_adm_acesso.py`

**Interfaces:**
- Consumes: `web.layout.LOGO`, `web.layout.pagina` da Task 1
- Produces:
  - `web.adm.COOKIE_ADM = "cotafrete_adm"`
  - `web.adm.senha_configurada() -> str | None`
  - `web.adm.token_de(senha: str) -> str`
  - `web.adm.autorizado(cookie: str | None) -> bool`
  - `web.adm.router` (um `fastapi.APIRouter` com prefixo `/adm`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adm_acesso.py
"""Quem entra no /adm, e quem não entra.

A tela junta CNPJ, nome e valor de nota de todos os clientes num lugar só. O
Servidor.bat avisa que 0.0.0.0 inclui o Wi-Fi: numa rede com visitantes, esta
senha é a única barreira entre eles e o histórico comercial da Ventura.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from web import adm, app as app_web

SENHA = "senha-de-teste-123"


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))
    return TestClient(app_web.app)


def test_sem_senha_no_ambiente_a_rota_nem_existe(monkeypatch, tmp_path):
    """404, não 401. Sem a variável configurada a tela não deve existir —
    ninguém abre um painel por engano numa pasta onde nada foi montado."""
    monkeypatch.delenv("COTAFRETE_ADM_SENHA", raising=False)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))

    resposta = TestClient(app_web.app).get("/adm", follow_redirects=False)

    assert resposta.status_code == 404


def test_sem_cookie_cai_na_tela_de_senha(cliente):
    resposta = cliente.get("/adm", follow_redirects=False)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/adm/entrar"


def test_senha_certa_entra(cliente):
    resposta = cliente.post("/adm/entrar", data={"senha": SENHA},
                            follow_redirects=False)

    assert resposta.status_code == 303
    assert adm.COOKIE_ADM in resposta.cookies


def test_senha_errada_nao_entra(cliente):
    resposta = cliente.post("/adm/entrar", data={"senha": "chutando"},
                            follow_redirects=False)

    assert adm.COOKIE_ADM not in resposta.cookies


def test_cookie_forjado_nao_entra(cliente):
    """O cookie não pode ser "adm=sim": qualquer um que soubesse o nome
    entraria digitando no navegador."""
    cliente.cookies.set(adm.COOKIE_ADM, "sim")

    assert cliente.get("/adm", follow_redirects=False).status_code == 303


def test_trocar_a_senha_invalida_as_sessoes(cliente, monkeypatch):
    """O token sai da própria senha, então trocá-la derruba todo mundo — sem
    precisar de uma lista de sessões para administrar."""
    antigo = adm.token_de(SENHA)
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "outra-senha")

    assert not adm.autorizado(antigo)


def test_a_senha_nunca_aparece_na_resposta(cliente):
    """Nem em campo escondido, nem em URL, nem em mensagem de erro."""
    resposta = cliente.post("/adm/entrar", data={"senha": "chutando"})

    assert SENHA not in resposta.text
    assert "chutando" not in resposta.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_adm_acesso.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'web.adm'`

- [ ] **Step 3: Write `web/adm.py`**

```python
"""O painel administrativo: /adm.

Fica fora de web/app.py porque aquele arquivo já passou de 1500 linhas, e
porque as duas telas têm públicos diferentes — a do vendedor e a de quem
administra o sistema.

SEGURANÇA. A tela junta CNPJ, nome e valor de nota de todos os clientes num
lugar só. O Servidor.bat avisa que 0.0.0.0 inclui o Wi-Fi: numa rede com
visitantes, a senha do .env é a única barreira.

Três regras que não devem ser afrouxadas sem pensar:

1. Sem COTAFRETE_ADM_SENHA no ambiente, a rota responde 404. A tela não passa
   a existir "aberta por engano" numa pasta onde ninguém configurou nada.
2. O cookie guarda um HMAC derivado da senha, nunca "sim". Quem tem a senha
   produz o valor — que é exatamente a permissão concedida. Trocar a senha
   invalida todas as sessões, sem lista de sessões para administrar.
3. Senha errada dorme 1s. Não é bloqueio; é o bastante para inviabilizar
   tentativa em massa numa rede local. Se esta tela um dia for para a
   internet, isto precisa virar bloqueio de verdade.
"""

from __future__ import annotations

import hmac
import os
import time

from fastapi import APIRouter, Cookie, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from core.banco import Banco
from web.layout import LOGO, pagina

# O banco chega por INJEÇÃO: `web/app.py` faz `adm.banco = banco` logo
# depois de criar o dele. Importar `web.app` daqui seria circular —
# `web/app.py` importa este módulo para registrar as rotas.
#
# É também o que deixa o teste trocar o banco por um temporário sem
# encostar no servidor.
banco: Banco | None = None

COOKIE_ADM = "cotafrete_adm"

# Acesso mais poderoso que o do vendedor (30 dias) dura menos.
VALIDADE_S = 60 * 60 * 12

# Atraso na senha errada. Ver a regra 3 no topo do módulo.
PAUSA_SENHA_ERRADA_S = 1.0

router = APIRouter(prefix="/adm")


def senha_configurada() -> str | None:
    """A senha do .env, ou None se ninguém montou o painel nesta pasta."""
    return os.getenv("COTAFRETE_ADM_SENHA") or None


def token_de(senha: str) -> str:
    """O valor que vai no cookie. Derivado da senha, então trocá-la derruba
    as sessões sozinha."""
    return hmac.new(senha.encode(), b"cotafrete-adm", "sha256").hexdigest()


def autorizado(cookie: str | None) -> bool:
    senha = senha_configurada()
    if not senha or not cookie:
        return False
    # compare_digest, não ==: comparação comum vaza tempo e conta a quem
    # tenta quantos caracteres já acertou.
    return hmac.compare_digest(cookie, token_de(senha))


def _exigir_montado() -> str:
    """404 quando não há senha configurada. Ver a regra 1 no topo."""
    senha = senha_configurada()
    if not senha:
        raise HTTPException(status_code=404)
    return senha


@router.get("/entrar", response_class=HTMLResponse)
def tela_de_entrada():
    _exigir_montado()
    return HTMLResponse(pagina("Painel", f"""
<div class="login">
  <img src="data:image/png;base64,{LOGO}" alt="Ventura">
  <div class="cartao">
    <h1>Painel</h1>
    <p class="sub">Esta tela mostra as cotações de toda a empresa.</p>
    <form method="post" action="/adm/entrar">
      <input name="senha" type="password" placeholder="Senha do painel"
             autofocus required style="margin-bottom:12px">
      <button type="submit" style="width:100%">Entrar</button>
    </form>
  </div>
</div>"""))


@router.post("/entrar")
def entrar(senha: str = Form(...)):
    correta = _exigir_montado()
    if not hmac.compare_digest(senha, correta):
        time.sleep(PAUSA_SENHA_ERRADA_S)
        # Sem repetir o que foi digitado: nem na tela, nem em log.
        return HTMLResponse(pagina("Painel", """
<div class="login"><div class="cartao">
  <h1>Painel</h1>
  <div class="alerta">Senha incorreta.</div>
  <p><a href="/adm/entrar">Tentar de novo</a></p>
</div></div>"""), status_code=401)

    r = RedirectResponse("/adm", status_code=303)
    r.set_cookie(COOKIE_ADM, token_de(correta), max_age=VALIDADE_S,
                 httponly=True, samesite="lax")
    return r


@router.get("/sair")
def sair():
    _exigir_montado()
    r = RedirectResponse("/adm/entrar", status_code=303)
    r.delete_cookie(COOKIE_ADM)
    return r


@router.get("", response_class=HTMLResponse)
def painel(adm: str | None = Cookie(None, alias=COOKIE_ADM)):
    _exigir_montado()
    if not autorizado(adm):
        return RedirectResponse("/adm/entrar", status_code=303)
    return HTMLResponse(pagina("Painel", "<p>em construção</p>"))
```

- [ ] **Step 4: Register the router in `web/app.py`**

Depois de `app = FastAPI(...)` (linha 64) e de `banco = Banco()` (linha 65):

```python
from web import adm

app.include_router(adm.router)
# O painel usa o MESMO banco do resto do sistema. Injetado aqui, e não
# importado lá, porque `web/adm.py` importar `web/app.py` seria circular.
adm.banco = banco
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_adm_acesso.py -v`
Expected: PASS — 7 passed. O teste da senha errada leva ~1s pela pausa proposital.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Confirme especificamente que `test_cotacao_de_outro_usuario_nao_abre` continua passando — a garantia da tela do vendedor não pode ter sido afrouxada.

- [ ] **Step 7: Commit**

```bash
git add web/adm.py web/app.py tests/test_adm_acesso.py
git commit -m "feat: porta do painel administrativo, com senha"
```

---

### Task 6: A tela

**Files:**
- Modify: `web/adm.py`
- Modify: `web/layout.py` (o CSS da faixa e das barras)
- Test: `tests/test_adm_tela.py`

**Interfaces:**
- Consumes: `core.painel.resumo_do_dia`, `core.painel.saude_das_transportadoras`, `core.painel.historico` (Tasks 3 e 4); `web.adm.autorizado`, `web.adm.COOKIE_ADM`, `web.adm._exigir_montado` (Task 5)
- Produces: `GET /adm` (tela completa), `GET /adm/agora` (fragmento da faixa ao vivo)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adm_tela.py
"""O que a tela do painel mostra.

Os números são a razão de a tela existir: um aproveitamento errado manda o
Enzo cobrar a transportadora errada. Por isso o teste confere o CONTEÚDO, não
só o status 200.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from web import adm, app as app_web

SENHA = "senha-de-teste-123"
CARGA = {"cep_origem": "29105770", "cep_destino": "01310100",
         "cidade_origem": "Vila Velha", "cidade_destino": "São Paulo",
         "peso_kg": "10", "quantidade": 1, "comprimento_cm": 30,
         "largura_cm": 30, "altura_cm": 30, "valor_nf": "1000",
         "material": "PLACA DE VIDEO"}


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))
    c = TestClient(app_web.app)
    c.cookies.set(adm.COOKIE_ADM, adm.token_de(SENHA))
    return c


def test_tela_mostra_cotacao_de_outro_usuario(cliente):
    """É o ponto do painel: o adm vê a empresa inteira, não só as dele."""
    cid = adm.banco.salvar_cotacao("leandro", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                                   valor=Decimal("123.45"))

    html = cliente.get("/adm").text

    assert "leandro" in html
    assert "123,45" in html


def test_tela_separa_falha_de_recusa(cliente):
    """Juntar as duas mandaria o Enzo cacar um problema que nao existe: as
    recusas da Jadlog por peso sao a transportadora funcionando."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "jadlog", status="recusado",
                                   erro="peso acima de 120 kg")
    adm.banco.salvar_resultado(cid, "generoso", status="erro",
                                   erro="TimeoutError: nao abriu")

    html = cliente.get("/adm").text

    assert "Recusas" in html and "Falhas" in html


def test_tela_vazia_nao_quebra(cliente):
    """Pasta nova, primeiro dia, banco sem nada."""
    assert cliente.get("/adm").status_code == 200


def test_o_periodo_escolhido_fica_marcado(cliente):
    """Sem marcar, ninguém sabe qual recorte está vendo — e um número lido
    no período errado é pior que número nenhum."""
    html = cliente.get("/adm?dias=7").text

    assert 'class="periodo atual"' in html
    assert "?dias=7" in html


def test_faixa_ao_vivo_e_um_fragmento_e_nao_a_pagina(cliente):
    """A faixa troca sozinha a cada 10s. Se devolvesse a página inteira, o
    JavaScript recolocaria uma página dentro dela mesma."""
    fragmento = cliente.get("/adm/agora").text

    assert "<!doctype" not in fragmento.lower()
    assert "<html" not in fragmento.lower()


def test_faixa_ao_vivo_tambem_exige_cookie(monkeypatch, tmp_path):
    """O fragmento tem os mesmos dados da tela: não pode ser porta dos
    fundos."""
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))

    resposta = TestClient(app_web.app).get("/adm/agora",
                                           follow_redirects=False)

    assert resposta.status_code == 303
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_adm_tela.py -v`
Expected: FAIL — `/adm/agora` não existe (404) e `/adm` devolve "em construção"

- [ ] **Step 3: Add the CSS to `web/layout.py`**

Ao fim da string `CSS`, antes das aspas de fechamento:

```css
.faixa{display:flex;gap:18px;flex-wrap:wrap;margin:16px 0}
.numero{background:#f4f4f6;border-radius:10px;padding:12px 18px;min-width:120px}
.numero b{display:block;font-size:28px;line-height:1.1}
.numero span{font-size:12px;color:#666}
.numero.ruim b{color:#b00020}
.barra{display:inline-block;width:90px;height:9px;background:#e6e6ea;
       border-radius:5px;vertical-align:middle;overflow:hidden}
.barra i{display:block;height:100%;background:#1f9d55}
.sem-dado{color:#888;font-size:12px}
.periodo{text-decoration:none;color:#555}
.periodo.atual{font-weight:700;color:#111;text-decoration:underline}
```

- [ ] **Step 4: Implement the screen in `web/adm.py`**

Acrescente aos imports do módulo:

```python
from decimal import Decimal

from core import painel as contas
from web.layout import e
```

Acrescente as funções de desenho e substitua a rota `painel` provisória:

```python
def _moeda(valor: Decimal | None) -> str:
    """Preço em português. None vira travessão, nunca "0,00" — zero seria um
    preço, e não ter preço é outra coisa."""
    if valor is None:
        return "—"
    return "R$ " + f"{valor:.2f}".replace(".", ",")


PERIODOS = ((1, "hoje"), (7, "7 dias"), (30, "30 dias"), (3650, "tudo"))


def _seletor(dias: int) -> str:
    """Qual recorte está na tela. Marcar o escolhido não é enfeite: um número
    lido no período errado é pior que número nenhum."""
    return '<p class="sub">' + " · ".join(
        f'<a class="periodo{" atual" if d == dias else ""}" '
        f'href="/adm?dias={d}">{e(rotulo)}</a>'
        for d, rotulo in PERIODOS) + "</p>"


def _faixa(resumo: dict) -> str:
    """A faixa ao vivo. Fragmento SEM casco: é ela que o JavaScript troca."""
    def bloco(rotulo: str, valor: int, destaque: str = "") -> str:
        return (f'<div class="numero{destaque}"><b>{valor}</b>'
                f'<span>{e(rotulo)}</span></div>')

    return (
        '<div class="faixa">'
        + bloco("cotações hoje", resumo["cotacoes"])
        + bloco("com preço", resumo["com_preco"])
        # O número que mais importa: o vendedor ficou na mão.
        + bloco("sem nenhum preço", resumo["sem_nenhum_preco"],
                " ruim" if resumo["sem_nenhum_preco"] else "")
        + bloco("cotando agora", resumo["em_andamento"])
        + "</div>")


def _barra(fracao: float | None) -> str:
    """Barra em CSS puro. Sem biblioteca, funciona sem internet."""
    if fracao is None:
        return '<span class="sem-dado">sem dados ainda</span>'
    return (f'<div class="barra"><i style="width:{fracao * 100:.0f}%"></i>'
            f'</div> {fracao * 100:.0f}%')


def _saude(linhas: list[dict]) -> str:
    if not linhas:
        return ("<h2>Saúde das transportadoras</h2>"
                "<p>Nenhuma cotação no período.</p>")
    corpo = "".join(
        f'<tr><td>{e(l["transportadora"])}</td>'
        f'<td>{l["sucesso"]}</td><td>{l["recusa"]}</td>'
        f'<td>{l["falha"]}</td><td>{l["nossa"]}</td>'
        f'<td>{_barra(l["aproveitamento"])}</td></tr>'
        for l in linhas)
    return (
        "<h2>Saúde das transportadoras</h2>"
        "<table><tr><th>transportadora</th><th>Sucessos</th>"
        "<th>Recusas</th><th>Falhas</th><th>Interrompidas</th>"
        "<th>aproveitamento</th></tr>"
        f"{corpo}</table>"
        '<p class="sub">Recusa é a transportadora dizendo não, com o motivo '
        "dela — não é defeito. Interrompida é o servidor tendo reiniciado no "
        "meio, e por isso fica fora do aproveitamento.</p>")


def _historico(linhas: list[dict]) -> str:
    if not linhas:
        return ""
    corpo = "".join(
        f'<tr><td><a href="/cotacao/{l["id"]}">#{l["id"]}</a></td>'
        f'<td>{e(l["criado_em"][5:16].replace("T", " "))}</td>'
        f'<td>{e(l["usuario"])}</td><td>{e(l["rota"])}</td>'
        f'<td>{e(l["material"] or "")}</td>'
        f'<td>{_moeda(l["melhor_preco"])}</td>'
        f'<td>{l["contagem"].get("falha", 0)}</td></tr>'
        for l in linhas)
    return ("<h2>Histórico</h2>"
            "<table><tr><th>nº</th><th>quando</th><th>quem</th><th>rota</th>"
            "<th>material</th><th>melhor preço</th><th>falhas</th></tr>"
            f"{corpo}</table>")


@router.get("/agora", response_class=HTMLResponse)
def agora(adm: str | None = Cookie(None, alias=COOKIE_ADM)):
    """Só a faixa. Tem os mesmos dados da tela, então exige o mesmo cookie."""
    _exigir_montado()
    if not autorizado(adm):
        return RedirectResponse("/adm/entrar", status_code=303)
    with banco._conectar() as con:
        return HTMLResponse(_faixa(contas.resumo_do_dia(con)))


@router.get("", response_class=HTMLResponse)
def painel(adm: str | None = Cookie(None, alias=COOKIE_ADM),
           dias: int = 30):
    _exigir_montado()
    if not autorizado(adm):
        return RedirectResponse("/adm/entrar", status_code=303)

    with banco._conectar() as con:
        resumo = contas.resumo_do_dia(con)
        saude = contas.saude_das_transportadoras(con, dias=dias)
        linhas = contas.historico(con, dias=dias)

    corpo = f"""
<h1>Painel</h1>
<div id="agora">{_faixa(resumo)}</div>
{_seletor(dias)}
{_saude(saude)}
{_historico(linhas)}
<p class="sub"><a href="/adm/sair">Sair do painel</a></p>
<script>
// Troca SÓ a faixa. Recarregar a página inteira perderia a rolagem de quem
// estivesse lendo a tabela embaixo.
setInterval(async () => {{
  try {{
    const r = await fetch('/adm/agora');
    if (r.ok) document.getElementById('agora').innerHTML = await r.text();
  }} catch (erro) {{ /* rede caiu; a próxima volta tenta de novo */ }}
}}, 10000);
</script>"""
    return HTMLResponse(pagina("Painel", corpo))
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_adm_tela.py -v`
Expected: PASS — 5 passed

- [ ] **Step 6: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 7: See it in the real app**

```bash
COTAFRETE_ADM_SENHA=teste .venv/Scripts/python.exe -m uvicorn web.app:app --port 8001
```

Abra `http://127.0.0.1:8001/adm`, entre com `teste`, e confira: a faixa mostra os números do dia, a tabela lista as transportadoras com as colunas separadas, e o histórico traz cotações de mais de um vendedor.

**Use a porta 8001. A 8000 é a de produção** — o `Servidor.bat` tem uma trava por causa disso, e em 25/08 a empresa passou uma manhã cotando contra o código de desenvolvimento.

- [ ] **Step 8: Commit**

```bash
git add web/adm.py web/layout.py tests/test_adm_tela.py
git commit -m "feat: tela do painel - faixa ao vivo, saude e historico"
```

---

## Depois da Fase 1

Fases 2 e 3 ganham planos próprios, escritos quando esta terminar. Escrever
agora os passos de TDD delas seria adivinhar interfaces que esta fase ainda
vai definir — e plano com código inventado é pior que plano nenhum.

- **Fase 2 — entender o que quebra:** `assinatura_do_erro`, falhas agrupadas,
  recusas agrupadas, alerta de 3 falhas seguidas.
- **Fase 3 — enxergar o conjunto:** `web/graficos.py`, os dois gráficos, e os
  números do período (economia, rotas, WhatsApp).

## Para subir em produção

O `.env` da pasta `cotafrete-producao` vai precisar de `COTAFRETE_ADM_SENHA`.
**Essa linha o Enzo escreve**, como a `DV_ENVIO_REAL_AUTORIZADO`.

Sem ela o `/adm` responde 404 e o resto do sistema segue normal — o que torna
a subida segura mesmo antes de a senha existir. E o servidor precisa ser
reiniciado para o código novo entrar em memória: o uvicorn sobe sem
`--reload`, de propósito.
