# Conferência do DAV com o HSE — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a conferência do DAV simula a geração no HSE, só para leitura, e mostra
o que o HSE encontrou. Com erro certo, o Gerar fica bloqueado. Junto entram as
correções do local de entrega pelo número e do "nada foi criado".

**Architecture:**
- A simulação que já existe (`dry_run`) vira a função `conferir()` em
  `orcamento/processador.py`. Ela devolve um resultado estruturado.
- Uma fila própria (`orcamento/conferencia.py`, uma thread) roda essa função num
  navegador `HseSoLeitura`. Esse navegador aborta todo POST de gravação.
- O resultado vai para duas colunas novas da tabela `dav`. A tela `/dav/{id}/conferir`
  libera ou bloqueia o Gerar.

**Tech Stack:** Python 3.14, FastAPI, Playwright (sync), SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-dav-conferencia-hse-design.md`

## Global Constraints

- **HSE é produção:**
  - a conferência nunca clica em Incluir nem em Salvar;
  - todo POST cujo corpo case com `acao=\w*(incluir|salvar|excluir|gravar|alterar|cadastr|inserir|atualizar|delet)` é abortado.
- **Senhas e chaves:** só no `.env` (`HSE_USUARIO`, `HSE_SENHA`). Nunca em código,
  log, banco, relatório, tela ou commit. Não abrir nem mostrar o `.env`.
- **Limites:**
  - `PRECO_ACIMA_TABELA = Decimal("2")`: avisa só quando o valor é maior que 2× (2,0× não avisa);
  - `LIMITE_CONFERENCIA_S = 120`;
  - `DESCONTO_MAX` continua 15.
- **Estados da conferência** (coluna `conferencia`): `conferindo`, `ok`, `erros`,
  `nao_conferido`. `None` é um rascunho antigo, e o Gerar fica liberado.
- **Vendedor:** não vê texto financeiro (regra do `orcamento/diagnostico.py::_financeiro`).
- **Navegadores:** a conferência usa `core.retentativa.VAGA_NAVEGADOR`. O limite de 2 não muda.
- **Git e testes:**
  - commits em português, Conventional Commits, sem coautoria;
  - branch nova a partir da `origin/main`;
  - **não fazer push nem abrir PR sem perguntar ao usuário**;
  - TDD;
  - suíte arquivo por arquivo, pulando `tests/test_aceite_tela.py`.

## Review Focus

1. **O mesmo vendedor envia duas planilhas seguidas.** As duas conferências entram
   na fila e cada uma grava no seu próprio DAV. Teste em `test_conferencia.py`
   (Task 5).
2. **Clique no Gerar com a conferência ainda rodando,** por um POST manual ou por
   uma aba antiga. A resposta é 303 de volta para a conferência, e nada entra na
   fila. Teste na Task 6.
3. **Planilha sem local de entrega (B30 vazia).** O endereço aparece como "Cadastral
   do cliente (B30 vazia)" e o resultado não vira erro. Teste na Task 3.
4. **A conferência estoura os 120 s e termina depois.** O resultado atrasado não
   sobrescreve `nao_conferido` nem um DAV que já foi para a fila. Teste na Task 5.
5. **Aviso financeiro do HSE na conferência.** O vendedor vê só "consulte o
   financeiro". O admin vê o texto completo. Teste na Task 6.

---

### Task 0: PR do local de entrega pelo número e da nova tentativa

**Files:** branch `fix/dav-local-numero-e-retentativa` (commit `8041565`), com
mudanças em `orcamento/hse.py`, `orcamento/processador.py` e `tests/orcamento/test_hse.py`.

- [ ] **Step 1:** `git switch fix/dav-local-numero-e-retentativa && git merge origin/main`
  Resolva os conflitos mantendo os dois lados. O `ErroHse` mudou para o `processador.py` nessa branch.
- [ ] **Step 2:** rode `python -m pytest tests/orcamento -q` e `python -m pytest tests/test_dav_diagnostico.py tests/test_dav_tela.py -q`.
  Esperado: tudo passa.
- [ ] **Step 3:** confira que `diagnostico.py` ainda classifica a mensagem de local de entrega como `endereco`. Ela agora sugere "escreva na B30 só o número do endereço". Esperado: `test_vendedor_ve_os_enderecos_do_cliente_no_erro_de_local` passa.
- [ ] **Step 4:** commit do merge. **Pergunte ao usuário** antes do push e da PR.

### Task 1: "nada foi criado" deixa de mandar consultar o responsável

**Files:**
- Modify: `orcamento/diagnostico.py` (cálculo de `salvamento` e da `orientacao`)
- Test: `tests/test_dav_diagnostico.py`

**Interfaces:** Produces: `diagnostico(...)["salvamento"] == "nao_criado"` quando o
`Resultado:` contém "nada foi criado".

- [ ] **Step 1: teste que falha**

```python
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
```

- [ ] **Step 2:** `python -m pytest tests/test_dav_diagnostico.py -q`. Esperado: FAIL no `salvamento`.
- [ ] **Step 3:** em `diagnostico.py`:
  - acrescente `"nada foi criado"` à condição de `nao_criado`, ao lado de `"orcamento nao criado"`. O texto já passa por `_normal`, então compare sem acento;
  - quando `salvamento == "nao_criado"` e o DAV não é incerto, troque a `orientacao` padrão pela frase do teste. A orientação de endereço e de acesso ao HSE continua tendo prioridade.
- [ ] **Step 4:** `python -m pytest tests/test_dav_diagnostico.py tests/test_dav_tela.py tests/test_adm_dav.py -q`. Esperado: PASS.
- [ ] **Step 5:** commit `fix: DAV sem criação no HSE orienta corrigir e reenviar`. **Pergunte** antes do push e da PR.

> As Tasks 2 a 8 vão numa branch nova, `feat/dav-conferencia-hse`, criada a
> partir da `origin/main` depois do merge das Tasks 0 e 1. Leve junto o commit da
> spec (`7180c8f`) e deste plano.

### Task 2: navegador só leitura e endereço escolhido

**Files:**
- Modify: `orcamento/hse.py` (constante `GRAVACAO`, função `guarda_gravacao`, classe `HseSoLeitura`, atributo `Hse.endereco`)
- Modify: `tests/orcamento/hse_falso.py` (atributo `endereco`)
- Test: `tests/orcamento/test_hse.py`

**Interfaces:**
- Produces:
  - `GRAVACAO: re.Pattern`;
  - `guarda_gravacao(route, bloqueados: list[str]) -> None`;
  - `class HseSoLeitura(Hse)` com `self.bloqueados: list[str]`, que instala a rota em `_login_passos` depois do `super()` (cada login cria um contexto novo);
  - `Hse.endereco: str`, que é `""` até `montar_orcamento` e recebe o texto da opção escolhida em `#cdEndereco`.
- Consumes: `Hse._login_passos`, `Hse._preencher_cabecalho` (já existem).

- [ ] **Step 1: testes que falham.** Use um `route` falso, um `SimpleNamespace` com `request.method`, `request.post_data`, `request.url`, `abort()` e `continue_()` que registram a chamada.
  - `test_guarda_aborta_post_de_gravacao`: o corpo `acao=salvarObsItem&x=1` é abortado e entra em `bloqueados`.
  - `test_guarda_deixa_passar_leitura`: o corpo `acao=listar` e um GET passam por `continue_`.
  - `test_endereco_fica_com_a_opcao_escolhida`: no teste do local pelo número (Task 0), `hse.endereco == "2 - Entrega - RUA X, ..."`.
- [ ] **Step 2:** rode `python -m pytest tests/orcamento/test_hse.py -q`. Esperado: FAIL (import).
- [ ] **Step 3:** implemente:
  - o padrão de `simular_todas.py` do scratchpad (o regex da seção Global Constraints);
  - `HseSoLeitura`;
  - `self.endereco = ""` em `__init__` e em `montar_orcamento`, e o texto da opção em `_preencher_cabecalho`;
  - `HseFalso` ganha `endereco = ""`.
- [ ] **Step 4:** `python -m pytest tests/orcamento -q`. Esperado: PASS.
- [ ] **Step 5:** commit `feat: navegador do HSE só leitura e endereço escolhido no orçamento`.

### Task 3: `conferir()` estruturado, com o aviso de preço acima de 2x

**Files:**
- Modify: `orcamento/processador.py`
- Test: `tests/orcamento/test_conferir.py` (novo)

**Interfaces:**
- Produces, em `processador.py`:

```python
PRECO_ACIMA_TABELA = Decimal("2")

@dataclass(frozen=True)
class ItemConferido:
    numero: int
    codigo: str            # "" para produto novo
    descricao: str         # descrição no HSE ("" para novo)
    preco_tabela: Decimal | None
    valor_unit: Decimal
    por: str               # "codigo" | "descricao" | "novo" | "" (com erro)

@dataclass(frozen=True)
class Conferencia:
    estado: str            # "ok" | "erros" | "nao_conferido"
    relatorio: str
    cliente: str           # "6303 - TANGARA ..." ou ""
    endereco: str
    vendedor: str
    itens: tuple[ItemConferido, ...]
    avisos: tuple[str, ...]
    erros: tuple[str, ...]
    def para_json(self) -> str: ...            # Decimal como str
    @staticmethod
    def de_json(texto: str) -> "Conferencia": ...

def aviso_preco_acima(r: Resolucao) -> str | None: ...
def conferir(path: Path, cfg: Config, hse: HseApi) -> Conferencia: ...
```

- Consumes: `ler_planilha`, `validar_online`, `_listar_itens`, `_executar_dry`,
  `ajudantes` e `HseIndisponivel` (já existem). Também `hse.endereco` (Task 2),
  lido com `getattr(hse, "endereco", "")`.

- [ ] **Step 1: testes que falham** (com o `HseFalso` e as planilhas de `tests/orcamento/planilhas/`, como em `test_gerar.py`):
  - `test_conferencia_ok_lista_cliente_endereco_e_itens`: o estado é `"ok"`, `cliente == "8411 - ..."` (o do falso), e `itens[0].codigo`, `preco_tabela` e `valor_unit` vêm preenchidos.
  - `test_desconto_acima_do_maximo_vira_erros`, com os valores do DAV 49 (tabela 12,18; valor 3,41): `estado == "erros"` e `erros[0]` igual à linha `ERRO:` do `conferir_desconto`.
  - `test_cliente_nao_encontrado_vira_erros`, `test_vendedor_inexistente_vira_erros` e `test_produto_novo_incompleto_vira_erros` (DAV 53).
  - `test_local_de_entrega_sem_endereco_vira_erros`: o falso levanta `ErroHse` em `montar_orcamento` com o texto do DAV 50. O resultado é `"erros"`, não uma exceção.
  - `test_sem_local_de_entrega_mostra_cadastral` (Review Focus 3): com a B30 vazia, `endereco == "Cadastral do cliente (B30 vazia)"`.
  - `test_preco_acima_de_2x_avisa_na_fronteira`:
    - tabela 100: valor 200,00 → nenhum aviso; 200,01 → aviso;
    - texto exato: `"Item 1: R$ 200,01 está 2,0× acima da tabela (R$ 100,00) do código 123 – PRODUTO X; confira se o código está certo"`;
    - um item `por="descricao"` gera o aviso `"Item N: produto achado pela descrição, não pelo código: 123 – PRODUTO X; confira se é o produto certo"`.
  - `test_hse_indisponivel_vira_nao_conferido`.
  - `test_conferir_nunca_inclui_nem_salva`: em `hse.nomes`, nenhum `salvar_orcamento`, e `montar_orcamento` só com `incluir=False`.
  - `test_conferencia_ida_e_volta_json`: `Conferencia.de_json(c.para_json()) == c`.
- [ ] **Step 2:** rode `python -m pytest tests/orcamento/test_conferir.py -q`. Esperado: FAIL (import).
- [ ] **Step 3:** implemente `conferir`:
  - `cfg = replace(cfg, dry_run=True)`;
  - `ler_planilha`: se der erro, devolva `"erros"` com os erros da planilha;
  - `validar_online` e depois `_listar_itens(..., dry_run=True)`;
  - sem erro, rode `_executar_dry` dentro de `try`. `ErroHse` e `Exception` viram `rel.erro(_resumo(e))`;
  - `HseIndisponivel`, em qualquer ponto, vira `"nao_conferido"`;
  - `erros` são as linhas `ERRO: ` de `rel.texto()`;
  - `avisos` juntam `orc.avisos`, os avisos de preço e de descrição, e as linhas `O HSE avisou:`.

  O aviso de 2x usa `moeda()` e a razão com uma casa decimal e vírgula. Ele fica de fora quando `preco` é `None` ou `r.erro` está preenchido.
- [ ] **Step 4:** `python -m pytest tests/orcamento -q`. Esperado: PASS.
- [ ] **Step 5:** commit `feat: conferir() simula o DAV no HSE e devolve o que foi encontrado`.

### Task 4: colunas da conferência no banco

**Files:**
- Modify: `core/banco.py`
- Test: `tests/test_dav_banco.py`

**Interfaces:** Produces:
- as colunas `dav.conferencia` e `dav.conferencia_relatorio` (TEXT), que entram em `CAMPOS_DAV`;
- `Banco.dav_conferencia_interromper() -> list[int]`: passa todo `rascunho` com `conferencia='conferindo'` para `'nao_conferido'` e devolve os ids.

- [ ] **Step 1: testes que falham:**
  - `test_banco_antigo_ganha_colunas_da_conferencia`: cria a tabela `dav` sem as colunas, abre o `Banco` e verifica que o `PRAGMA` lista as duas;
  - `test_dav_atualizar_aceita_conferencia`;
  - `test_conferencia_interrompida_vira_nao_conferido`: um DAV `fila` com `conferencia='conferindo'` não muda.
- [ ] **Step 2:** rode `python -m pytest tests/test_dav_banco.py -q`. Esperado: FAIL.
- [ ] **Step 3:** implemente:
  - `CAMPOS_DAV_NOVOS = ("conferencia", "conferencia_relatorio")`, com o laço de `ALTER TABLE` igual aos de `me_item` (perto da linha 415). Coloque as duas também no `CREATE TABLE` e em `CAMPOS_DAV`;
  - `dav_conferencia_interromper`, no molde de `dav_interromper`.
- [ ] **Step 4:** `python -m pytest tests/test_dav_banco.py tests/test_dav_tela.py -q`. Esperado: PASS.
- [ ] **Step 5:** commit `feat: colunas da conferência do DAV no banco`.

### Task 5: fila de conferência

**Files:**
- Create: `orcamento/conferencia.py`
- Test: `tests/orcamento/test_conferencia.py`

**Interfaces:**
- Produces:

```python
LIMITE_CONFERENCIA_S = 120
SEM_HSE = "Não consegui conferir com o HSE agora; o robô confere de novo ao gerar."

class FilaConferencia:
    def __init__(self, banco: Banco, pasta: Path,
                 executar: Callable[[Path], Conferencia] | None = None,
                 disparar: Callable[[Callable[[], None]], None] | None = None,
                 limite_s: float = LIMITE_CONFERENCIA_S): ...
    def enfileirar(self, dav_id: int) -> None: ...
    def retomar(self) -> None: ...   # chama banco.dav_conferencia_interromper()
```

- Consumes:
  - `Banco.dav`, `Banco.dav_atualizar` e `dav_conferencia_interromper` (Task 4);
  - `conferir` e `Conferencia` (Task 3);
  - `HseSoLeitura` (Task 2).

  A planilha fica em `pasta / "entrada" / f"{id}.xlsx"`, o mesmo caminho de `FilaDav.planilha`.
- **Comportamento:**
  - Uma thread daemon (`name="fila-conferencia"`) consome uma `queue.Queue`. O padrão é o de `FilaDav._na_thread` e `_consumir`.
  - Cada tarefa roda `executar(planilha)` numa thread auxiliar e espera com `join(limite_s)`.
  - Estourou o tempo: grava `conferencia="nao_conferido"` e um `conferencia_relatorio` com o `SEM_HSE`, e segue para a próxima tarefa.
  - Resultado atrasado: só é gravado se o DAV ainda estiver em `estado == "rascunho"` e `conferencia == "conferindo"`.
  - O padrão de `executar` é `with VAGA_NAVEGADOR, HseSoLeitura(replace(config_do_ambiente(), dry_run=True, pasta_programa=pasta)) as hse: return conferir(planilha, cfg, hse)`.
  - Exceção inesperada vira `nao_conferido`, com o texto passado por `fila._sem_segredo`.
- [ ] **Step 1: testes que falham.** Use `disparar=lambda t: t()` (roda na hora) e `executar` falso:
  - `test_ok_grava_estado_e_json`;
  - `test_erros_grava_erros`;
  - `test_excecao_vira_nao_conferido_sem_senha`: a mensagem contém `HSE_SENHA`, e a gravação não;
  - `test_tempo_estourado_vira_nao_conferido`: com `limite_s=0.05` e um executor que dorme 0,3 s;
  - `test_resultado_atrasado_nao_sobrescreve` (Review Focus 4);
  - `test_duas_planilhas_do_mesmo_vendedor_cada_uma_no_seu_dav` (Review Focus 1);
  - `test_retomar_marca_nao_conferido`.
- [ ] **Step 2:** rode `python -m pytest tests/orcamento/test_conferencia.py -q`. Esperado: FAIL (import).
- [ ] **Step 3:** implemente `orcamento/conferencia.py`.
- [ ] **Step 4:** `python -m pytest tests/orcamento -q`. Esperado: PASS.
- [ ] **Step 5:** commit `feat: fila de conferência do DAV no HSE só leitura`.

### Task 6: tela do vendedor (estado da conferência e trava do Gerar)

**Files:**
- Modify: `web/app.py`:
  - perto da linha 135: `FILA_CONFERENCIA = FilaConferencia(banco, Path("davs"))` e `dav_ui.FILA_CONFERENCIA = FILA_CONFERENCIA`;
  - perto da linha 107: `FILA_CONFERENCIA.retomar()` no mesmo `try` de `FILA_DAV.retomar()`.
- Modify: `web/dav_ui.py`:
  - `FILA_CONFERENCIA` injetado;
  - `conferir`, `reconferir`, `_resumo` e `gerar`.
- Test: `tests/test_dav_tela.py`. A fixture `app_web` injeta uma `FilaConferencia` com `disparar=lambda t: t()` e um `executar` falso que devolve `ok`.

**Interfaces:**
- Consumes:
  - `FilaConferencia.enfileirar` (Task 5);
  - `Conferencia.de_json` (Task 3);
  - `diagnostico._financeiro` (para filtrar avisos do vendedor).
- **Comportamento:**
  - `POST /dav/conferir`: depois de `dav_criar`, grava `conferencia="conferindo"`, chama `FILA_CONFERENCIA.enfileirar(dav_id)` e renderiza `_resumo(o, dav_id, banco.dav(dav_id, usuario))`.
  - `_resumo(o, dav_id, d)`:
    - com `conferindo`: mostra `<meta http-equiv="refresh" content="5;url=/dav/{id}/conferir">`, o texto "Conferindo com o HSE…" e nenhum botão de gerar;
    - com `ok`, `erros` ou `nao_conferido`: mostra cliente, endereço e vendedor encontrados, e na tabela de itens as colunas Código HSE, Descrição no HSE, Tabela e Planilha;
    - avisos em `div.aviso`, erros em `div.alerta`;
    - com `nao_conferido`: o aviso é o `SEM_HSE`;
    - o botão "Confirmar e gerar DAV →" aparece só quando `conferencia in (None, "ok", "nao_conferido")`;
    - com `erros`: o link "Enviar planilha corrigida →" para `/dav?origem={id}`. Hoje o `_validar_origem` só aceita `erro`/`rejeitado`; passe a aceitar também `rascunho` com `conferencia == "erros"`.
  - `POST /dav/{id}/gerar`: com `conferencia in ("conferindo", "erros")`, devolve 303 para `/dav/{id}/conferir` sem enfileirar.
  - **Avisos para o vendedor:** quando `_financeiro(aviso)` for verdadeiro, mostrar só "Aviso financeiro: consulte o financeiro." O admin vê o texto completo (Task 7).
- [ ] **Step 1: testes que falham.** Ajuste `test_conferir_boa_mostra_resumo_e_botao_gerar` para o fluxo novo e acrescente:
  - `test_conferencia_com_erros_esconde_gerar_e_mostra_corrigir`;
  - `test_conferindo_atualiza_sozinho_e_nao_tem_gerar`;
  - `test_nao_conferido_avisa_e_libera_gerar`;
  - `test_gerar_recusado_com_conferencia_em_andamento_ou_com_erros` (Review Focus 2): o `FILA.enfileirar` não é chamado;
  - `test_rascunho_antigo_sem_conferencia_continua_gerando`;
  - `test_aviso_financeiro_da_conferencia_nao_aparece_ao_vendedor` (Review Focus 5): o texto `DF15653` não aparece;
  - `test_tabela_mostra_preco_de_tabela_e_da_planilha`.
- [ ] **Step 2:** rode `python -m pytest tests/test_dav_tela.py -q`. Esperado: FAIL nos novos.
- [ ] **Step 3:** implemente o comportamento acima.
- [ ] **Step 4:** `python -m pytest tests/test_dav_tela.py tests/test_dav_atualizacao.py tests/test_dav_painel.py -q`. Esperado: PASS.
- [ ] **Step 5:** commit `feat: tela de conferência mostra o que o HSE encontrou e trava o Gerar com erro`.

### Task 7: painel do admin

**Files:**
- Modify: `web/dav_ui.py::detalhe_dav` (bloco com `administrador=True`)
- Modify: `core/painel_dav.py::consultar` (lista `atencao`)
- Test: `tests/test_adm_dav.py`

- **Comportamento:**
  - `detalhe_dav` com `administrador=True` e `conferencia`: mostra uma seção "Conferência com o HSE" com o estado, os erros, os avisos completos e o `relatorio` do JSON em `<pre>`.
  - Em `atencao`, entram também os DAVs `rascunho` com `conferencia == "erros"`.
- [ ] **Step 1: testes que falham:**
  - `test_admin_ve_conferencia_completa_com_financeiro`;
  - `test_rascunho_com_erros_na_conferencia_aparece_em_atencao`.
- [ ] **Step 2:** rode `python -m pytest tests/test_adm_dav.py -q`. Esperado: FAIL.
- [ ] **Step 3:** implemente.
- [ ] **Step 4:** `python -m pytest tests/test_adm_dav.py tests/test_dav_painel.py -q`. Esperado: PASS.
- [ ] **Step 5:** commit `feat: admin vê a conferência do DAV e os rascunhos com erro`.

### Task 8: rodada real só leitura, documentação e PR

**Files:**
- Modify: `docs/MAPA_DO_SISTEMA.md` (seção do DAV: conferência, fila, colunas, `HseSoLeitura`)
- Script no scratchpad (não vai para o repositório): `conferir_todas.py`, que chama `conferir()` com `HseSoLeitura` em cada `.xlsx` de uma pasta e grava um CSV com `planilha;estado;segundos;erros;avisos;bloqueados`.

- [ ] **Step 1:** peça ao usuário as planilhas dos DAVs 35 a 65 (`davs/entrada/{id}.xlsx` na VM) numa pasta local. **Não** copie nada para a VM nem grave nela.
- [ ] **Step 2:** rode o script contra o HSE de produção. Esperado:
  - 35 e 50: `erros` (local), ou `ok` com a correção da Task 0 para o 35;
  - 39, 44 e 46: `erros` (cliente);
  - 49, 56 e 60: `erros` (desconto);
  - 53: `erros` (produto novo);
  - todas as que ficaram prontas: `ok`;
  - a coluna `bloqueados` vazia (nenhuma tentativa de gravação).
- [ ] **Step 3:** se alguma planilha divergir, investigue com `superpowers:systematic-debugging` antes de seguir.
- [ ] **Step 4:** rode a suíte inteira, arquivo por arquivo, pulando `tests/test_aceite_tela.py`. Esperado: nenhuma falha nova em relação à `main`.
- [ ] **Step 5:** atualize o `MAPA_DO_SISTEMA.md` e faça o commit `docs: mapa do sistema com a conferência do DAV`.
- [ ] **Step 6:** escreva para o usuário o texto do Guia do Vendedor: o número na B30 e a tela nova de conferência. **Pergunte** antes do push e da PR.
