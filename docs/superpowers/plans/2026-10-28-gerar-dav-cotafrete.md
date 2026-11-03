# Gerar DAV no Cotafrete — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aba "Gerar DAV" no Cotafrete: o vendedor envia a planilha v3, confere, gera o orçamento no HSE pelo robô do RoboOrcamento, baixa o PDF e vê o histórico; o portal Maestro ganha o botão que abre a aba.

**Architecture:** O código do RoboOrcamento (`C:\RoboOrcamento\robo`) vira o pacote `orcamento/` do Cotafrete, com uma entrada nova (`gerar`) que devolve o resultado em vez de mover arquivos. Uma fila de uma thread roda um DAV por vez com uma vaga de `VAGA_NAVEGADOR`. A tabela `dav` do `cotafrete.db` guarda estado, relatório e PDF. A tela `web/dav_ui.py` (router `/dav`) segue o padrão do `web/me_ui.py`.

**Tech Stack:** Python 3.14 (VM Windows 10), FastAPI, Playwright (já no projeto), openpyxl, sqlite. Portal: Node/Express, ExcelJS.

**Spec:** `docs/superpowers/specs/2026-10-28-gerar-dav-cotafrete-design.md` (leia inteiro antes de começar).

## Global Constraints

- Repositório principal: `C:\Users\vendas12\enzo\cotafrete-sincronizacao`, branch `feat/gerar-dav-cotafrete` (já criada a partir de `origin/main`, com o design commitado). Portal: `C:\Users\vendas12\enzo\portaismaestro-cotacoes`, branch nova `feat/botao-gerar-dav` a partir da `main`.
- Origem do código: `C:\RoboOrcamento` (repo `enzozon/robo-orcamento-hse`). **Só leia e copie**; não altere nada lá nem em `\\SERVIDOR2\Publico\ENZO\ORCAMENTO`.
- `orcamento/` roda só na VM (Python 3.14). Não importe nada dele em `cruzar_nf/` (Python 3.8).
- Dependência nova permitida: só `anthropic` (para `IA=api`). Nada mais em `requirements.txt`.
- HSE (https://app.hsesistemas.com.br) é **produção**. Testes usam o HSE falso (`tests/orcamento/hse_falso.py`). Nunca rodar contra o HSE real com `DAV_DRY_RUN=0` sem o Enzo dizer "pode salvar" no chat.
- Senha do HSE e `ANTHROPIC_API_KEY` só no `.env`. Nunca em log, banco, relatório, tela ou commit.
- Testes: `python -m pytest tests -q -p no:cacheprovider --ignore=tests/test_aceite_tela.py` (esse arquivo trava hoje, problema antigo, fora do escopo). Portal: `npm test` (7 falhas já existem na `main`: não aumente o número).
- TDD em cada tarefa, commits em português (Conventional Commits, sem linha de coautoria). Sem push nem PR sem perguntar.
- Mudou uma parte descrita em `docs/MAPA_DO_SISTEMA.md`? Atualize o mapa no mesmo commit (regra do `CLAUDE.md`).

## Review Focus

1. **Mesma planilha enviada duas vezes** (duplo clique, ou o vendedor reenvia o arquivo que já gerou): não pode gerar um segundo orçamento. Esperado: "Esta planilha já gerou o orçamento N" e nada vai para a fila (Task 3 e Task 5).
2. **Servidor reiniciado no meio de um DAV** (`atualizar.py` depois de um merge, queda da VM): o DAV "gerando" vira "confira no HSE", nunca roda de novo (Task 4).
3. **Vendedor trocando o número na URL** (`/dav/123` ou `/dav/123/pdf` de outro): 404, como `/cotacao/{id}` (Task 5).
4. **Arquivo errado no upload** (`.xls`, PDF, xlsx corrompido, mais de 5 MB, aba ORÇAMENTO ausente): mensagem clara, nada criado (Task 5).
5. **Export do portal na v3 perdendo as listas suspensas** (ExcelJS pode descartar as validações x14 da aba LISTAS): o arquivo exportado precisa continuar lendo no `ler_planilha` e manter a aba LISTAS. Se as listas suspensas se perderem, o teste registra isso e o vendedor é avisado (Task 6).

---

## Task 1: Trazer o RoboOrcamento para `orcamento/`

**Files:**
- Create: `orcamento/__init__.py`, `orcamento/config.py`, `orcamento/planilha.py`, `orcamento/relatorio.py`, `orcamento/processador.py`, `orcamento/hse.py`, `orcamento/ia.py` (cópias de `C:\RoboOrcamento\robo\*.py`)
- Create: `orcamento/modelo/PLANILHA-BASE-v3.xlsx` (cópia de `\\SERVIDOR2\Publico\ENZO\ORCAMENTO\PLANILHA-BASE-v3.xlsx`)
- Create: `tests/orcamento/` com os testes de `C:\RoboOrcamento\tests` (menos `test_main.py` e `test_atualizar_listas.py`), `hse_falso.py` e `planilhas/`
- Modify: `requirements.txt` (+ `anthropic`), `.gitignore` (+ `davs/`)

**Interfaces:**
- Produces: `orcamento.config.config_do_ambiente(ambiente: Mapping[str, str] | None = None) -> Config` lendo `HSE_USUARIO`, `HSE_SENHA`, `HSE_CLIENT_ID` (padrão `ventura`), `DAV_DRY_RUN` (padrão `1`), `DAV_HEADLESS` (padrão `1`), `IA` (`desligada`|`api`, padrão `desligada`), `IA_MODELO`, `ANTHROPIC_API_KEY`. `Config.pasta` passa a ser opcional (`Path | None`, só o modo pasta usa). Faltando usuário ou senha → `ValueError("Faltam no .env: ...")`. Todas as outras assinaturas do RoboOrcamento ficam iguais, com `robo.` trocado por `orcamento.`.

- [ ] **Step 1:** Copiar os arquivos e trocar os imports `robo.` → `orcamento.` (código e testes). Rodar `python -m pytest tests/orcamento -q`. Esperado: passa tudo, menos os testes de `claude_cli` e de `carregar_config` (próximos passos).
- [ ] **Step 2: Teste falhando** em `tests/orcamento/test_config.py`:
```python
def test_config_do_ambiente_le_as_chaves_do_dav():
    cfg = config_do_ambiente({"HSE_USUARIO": "u", "HSE_SENHA": "s"})
    assert (cfg.usuario, cfg.client_id, cfg.dry_run, cfg.headless, cfg.ia, cfg.pasta) == \
           ("u", "ventura", True, True, "desligada", None)
    assert "s" not in repr(cfg)

def test_config_sem_senha_recusa():
    with pytest.raises(ValueError, match="HSE_SENHA"):
        config_do_ambiente({"HSE_USUARIO": "u"})

def test_ia_claude_cli_vira_desligada(monkeypatch):
    # nenhuma chamada externa: o servidor não tem o Claude Code
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("chamou o claude"))
    cfg = config_do_ambiente({"HSE_USUARIO": "u", "HSE_SENHA": "s", "IA": "claude_cli"})
    assert cfg.ia == "desligada"
```
- [ ] **Step 3:** Implementar `config_do_ambiente`; tirar de `ia.py` o modo `claude_cli` (`_rodar_cli` e o ramo dele): qualquer `IA` diferente de `api` = desligada. Apagar os testes que só cobriam `claude_cli` e `carregar_config`.
- [ ] **Step 4:** `python -m pytest tests/orcamento -q` → tudo passa. Depois a suíte inteira (comando das Global Constraints) → nada quebrou.
- [ ] **Step 5: Commit** `feat(orcamento): robo de orcamentos do HSE dentro do cotafrete`

## Task 2: `gerar()`: o resultado de um DAV sem mexer em pasta

**Files:**
- Modify: `orcamento/processador.py`
- Test: `tests/orcamento/test_gerar.py`

**Interfaces:**
- Consumes: `ler_planilha`, `validar_online`, `_executar_real`, `_executar_dry`, `Relatorio`, `HseApi` (Task 1).
- Produces:
```python
@dataclass(frozen=True)
class Resultado:
    estado: str             # "pronto" | "erro" | "incerto" | "simulado" | "adiado"
    numero: str | None      # nº do orçamento no HSE (pronto/incerto, ou erro com orçamento salvo)
    pdf: Path | None        # PDF gravado (só "pronto")
    relatorio: str          # Relatorio.texto()
    cliente: str            # "8411 - BELO VALE ..." ou "" se não chegou a achar

def gerar(path: Path, cfg: Config, hse: HseApi, pasta_pdf: Path) -> Resultado
```
  `pasta_pdf` recebe `DAV_<numero>_<cliente>.pdf` (mesmo nome de hoje, `destino_livre`). `gerar` não move, não marca estado em JSON e não olha `cfg.pasta`. `processar_arquivo` (modo pasta) passa a chamar `gerar` e só cuida de mover, gravar o `.txt` e marcar `processados_estado.json`: os testes dele continuam passando sem mudança.
  "incerto" = `SalvoIncerto` **e** "orçamento FOI SALVO mas o DAV falhou" (nos dois o orçamento pode existir). "adiado" = `HseIndisponivel` antes de criar qualquer coisa.

- [ ] **Step 1: Testes falhando** (HSE falso + planilhas de `tests/orcamento/planilhas`):
  - `test_gerar_pronto_devolve_numero_pdf_e_relatorio`: `estado == "pronto"`, `pdf.exists()`, `pdf.parent == pasta_pdf`, `"orçamento <n> salvo" in relatorio`, planilha original continua onde estava.
  - `test_gerar_planilha_com_erro_nao_chama_o_hse`: `estado == "erro"`, HSE falso sem nenhuma chamada.
  - `test_gerar_salvo_incerto_vira_incerto_com_numero`: HSE falso levanta `SalvoIncerto("16400", ...)` → `estado == "incerto"`, `numero == "16400"`, `"NÃO reenvie" in relatorio`.
  - `test_gerar_dav_que_falha_depois_do_salvar_vira_incerto`: `baixar_dav` levanta → `estado == "incerto"`, `numero` preenchido.
  - `test_gerar_hse_fora_do_ar_vira_adiado`.
  - `test_gerar_dry_run_vira_simulado_sem_pdf`.
- [ ] **Step 2:** Rodar → falham (`gerar` não existe).
- [ ] **Step 3:** Implementar extraindo o miolo de `processar_arquivo` e `_executar_real` (hoje eles devolvem o nome da pasta). Sem duplicar a lógica: o modo pasta usa `gerar`.
- [ ] **Step 4:** `python -m pytest tests/orcamento -q` → tudo passa (inclusive `test_processador.py` antigo).
- [ ] **Step 5: Commit** `feat(orcamento): gerar devolve o resultado do DAV sem mover a planilha`

## Task 3: Tabela `dav` no banco

**Files:**
- Modify: `core/banco.py` (ESQUEMA + métodos)
- Test: `tests/test_dav_banco.py`

**Interfaces:**
- Produces (métodos de `Banco`):
  - `dav_criar(usuario: str, arquivo: str, hash_planilha: str, cliente: str) -> int` (estado `"rascunho"`, `criado_em` ISO)
  - `dav_atualizar(dav_id: int, **campos) -> None` (campos válidos: `estado`, `numero`, `cliente`, `relatorio`, `pdf`, `erro`, `iniciado_em`, `terminado_em`; outro nome → `ValueError`, como `_me_conferir`)
  - `dav(dav_id: int, usuario: str | None) -> dict | None` (`usuario=None` = admin, vê qualquer um)
  - `davs(usuario: str | None, limite: int = 50) -> list[dict]` (mais novos primeiro, sem `rascunho`)
  - `dav_ja_gerado(usuario: str, hash_planilha: str) -> dict | None` (o DAV desse usuário com esse hash em `fila`, `gerando`, `pronto` ou `incerto`)
  - `dav_interromper() -> list[int]`: `gerando` → `incerto` (com `erro = "O servidor reiniciou durante o DAV: confira no HSE antes de gerar de novo."`); devolve os ids em `fila`, mais antigos primeiro
  - Colunas: `id INTEGER PRIMARY KEY`, `usuario`, `arquivo`, `hash_planilha`, `estado`, `numero`, `cliente`, `relatorio`, `pdf`, `erro`, `criado_em`, `iniciado_em`, `terminado_em`.

- [ ] **Step 1: Testes falhando:** criar e ler pelo dono; `dav(id, "outro") is None`; `dav(id, None)` acha; `davs("ana")` sem os de `bia` e sem rascunho; `dav_ja_gerado` acha `pronto`/`incerto`/`fila` e ignora `erro`/`rascunho`; `dav_interromper` muda `gerando` → `incerto` e devolve as filas em ordem; `dav_atualizar(id, senha="x")` → `ValueError`.
- [ ] **Step 2:** Rodar → falham.
- [ ] **Step 3:** Implementar no padrão das tabelas `me_*`.
- [ ] **Step 4:** Passa, e a suíte inteira continua verde.
- [ ] **Step 5: Commit** `feat(dav): tabela dav no banco do cotafrete`

## Task 4: Fila do DAV (uma por vez, sobrevive a reinício)

**Files:**
- Create: `orcamento/fila.py`
- Modify: `web/app.py` (criar a fila na subida; `/_ocupado` soma `fila.em_curso`)
- Test: `tests/orcamento/test_fila.py`

**Interfaces:**
- Consumes: `Banco.dav_*` (Task 3), `gerar`/`Resultado` (Task 2), `config_do_ambiente`, `orcamento.hse.Hse` (context manager), `core.retentativa.VAGA_NAVEGADOR`.
- Produces:
```python
class FilaDav:
    def __init__(self, banco: Banco, pasta: Path, executar: Callable[[Path, Path], Resultado] | None = None,
                 disparar: Callable[[Callable[[], None]], None] | None = None) -> None
    em_curso: int                    # na fila + gerando
    def enfileirar(self, dav_id: int) -> int      # posição (1 = o próximo)
    def retomar(self) -> None        # na subida: banco.dav_interromper() e re-enfileira as filas
```
  `pasta` = `davs/` (planilhas em `davs/entrada/`, PDFs em `davs/pdf/`). `executar(planilha, pasta_pdf)` padrão = abre `Hse(config_do_ambiente())` com `VAGA_NAVEGADOR` e chama `gerar`. `disparar` padrão = uma thread trabalhadora daemon que consome uma `queue.Queue`; o teste passa um que roda na hora. Antes de executar: `estado="gerando"`, `iniciado_em`. Depois: `estado` = `resultado.estado`, exceto `"adiado"`, que vira `erro` com "O HSE está fora do ar agora. Tente de novo em alguns minutos." (na tela não há "próximo ciclo"). Exceção inesperada vira `erro` com o texto e nunca derruba a thread. A senha não aparece no `erro` (troque `HSE_SENHA` por `***`, como em `dav/maestro.py` da branch antiga).

- [ ] **Step 1: Testes falhando:** `pronto` grava número/PDF/relatório; `adiado` vira `erro` com a mensagem acima; exceção do `executar` vira `erro` e o próximo da fila ainda roda; `em_curso` sobe ao enfileirar e volta a 0; `retomar` com um `gerando` e duas `fila` → o primeiro vira `incerto` e as duas rodam na ordem; erro com a senha no texto sai com `***`.
- [ ] **Step 2:** Rodar → falham.
- [ ] **Step 3:** Implementar. Em `web/app.py`: `FILA_DAV = FilaDav(banco, Path("davs"))`, `FILA_DAV.retomar()` no `_vida` (subida) e `"em_curso": EXECUTOR.em_curso + FILA_DAV.em_curso` no `/_ocupado`.
- [ ] **Step 4:** Passa, e a suíte inteira continua verde.
- [ ] **Step 5: Commit** `feat(dav): fila do DAV no cotafrete, um por vez e sem repetir depois de reinicio`

## Task 5: Tela "Gerar DAV" (`/dav`) e lista do admin

**Files:**
- Create: `web/dav_ui.py`
- Modify: `web/app.py` (`include_router`, `dav_ui.banco`, `dav_ui.vendedor`, `dav_ui.FILA`), `web/layout.py` (link "Gerar DAV" no menu de `pagina`, entre "Mercado Eletrônico" e "Documentação"), `web/adm.py` (rota `/adm/dav`)
- Test: `tests/test_dav_tela.py`

**Interfaces:**
- Consumes: `vendedor` (cookie, `web/app.py`), `adm.autorizado`, `Banco.dav_*`, `FilaDav.enfileirar`, `ler_planilha`/`ErroPlanilha`, `layout.pagina`.
- Rotas (router `prefix="/dav"`, sem login → `RedirectResponse("/login", 303)`):
  - `GET /dav`: envio (campo `.xlsx` + link "Baixar o modelo v3") e histórico do vendedor (`davs(usuario)`: data, arquivo, cliente, número, estado, link).
  - `GET /dav/modelo`: devolve `orcamento/modelo/PLANILHA-BASE-v3.xlsx`.
  - `POST /dav/conferir` (multipart `planilha`): recusa tamanho > 5 MB ou extensão ≠ `.xlsx`; grava em `davs/entrada/<uuid>.xlsx`; `ler_planilha`. Com erro: lista os erros e apaga o arquivo. Com `dav_ja_gerado(usuario, hash)`: "Esta planilha já gerou o orçamento N" com link para ele, sem Gerar. Sem erro: `dav_criar(...)` (rascunho) e o resumo só leitura (spec §6.2) com o botão Gerar (`POST /dav/{id}/gerar`).
  - `POST /dav/{id}/gerar`: só do dono e só em `rascunho` (senão 404 ou redireciona para `/dav/{id}`); `estado="fila"`, `FILA.enfileirar`, redireciona para `/dav/{id}`.
  - `GET /dav/{id}`: estado em português, posição se na fila, `<meta http-equiv="refresh" content="5">` enquanto `fila`/`gerando`; em `pronto`: número, "Baixar PDF" e o relatório em `<pre>`; em `incerto`: o aviso "confira no HSE o orçamento N e não gere de novo" em destaque; em `erro`: o erro e o relatório.
  - `GET /dav/{id}/pdf`: dono ou admin (cookie `COOKIE_ADM` válido); outro → 404.
  - `GET /adm/dav`: só admin; todos os DAVs (`davs(None)`) com a coluna vendedor e o link para `/dav/{id}` (que aceita o admin).
- Textos sempre escapados (`layout.e`): nome de arquivo e conteúdo da planilha vêm do vendedor.

- [ ] **Step 1: Testes falhando** (`TestClient`, `entrar` de `tests/apoio.py`, `FilaDav` com `disparar` que só anota o id):
  - sem login: `/dav` → 303 `/login`
  - conferir planilha boa → mostra cliente e itens e tem o botão Gerar; planilha com erro → mostra os erros, sem botão, sem linha no banco
  - `.xls`, arquivo de 6 MB, xlsx corrompido → mensagem e nada criado
  - gerar → `estado == "fila"`, id enfileirado, redirect para `/dav/{id}`; gerar de novo o mesmo id → não enfileira duas vezes
  - mesma planilha depois de `pronto` → "já gerou o orçamento"
  - `/dav/{id}` e `/dav/{id}/pdf` de outro vendedor → 404; admin → 200
  - histórico mostra só os do vendedor; `/adm/dav` sem admin → redirect `/adm/entrar`
  - nome de arquivo `<script>x</script>.xlsx` aparece escapado
- [ ] **Step 2:** Rodar → falham.
- [ ] **Step 3:** Implementar no padrão do `me_ui.py` (injeção de `banco`/`vendedor` pelo `web/app.py`).
- [ ] **Step 4:** Passa, e a suíte inteira continua verde. Suba o servidor local com `DAV_DRY_RUN=1` e confira só a tela: abra `/dav`, envie uma planilha de `tests/orcamento/planilhas` e veja o resumo. **Não clique em Gerar** com credenciais reais do HSE.
- [ ] **Step 5:** Atualizar `docs/MAPA_DO_SISTEMA.md` (sistema novo: Gerar DAV, `orcamento/`, tabela `dav`, `davs/`) e o `.env` de exemplo, se houver, com as chaves da spec §6.5 (sem valores).
- [ ] **Step 6: Commit** `feat(dav): aba Gerar DAV no cotafrete com historico por vendedor`

## Task 6: Portal Maestro: botão GERAR DAV e export na v3

**Files (repo do portal, branch `feat/botao-gerar-dav` a partir de `main`):**
- Modify: `public/minhas_cotacoes.html` (botão), `public/PLANILHA BASE.xlsx` e `public/vendor/template_planilha_base.js` (trocar pela v3, mesmo formato base64 de hoje), a função de export da planilha base em `public/minhas_cotacoes.html`
- Test: `tests/minhas-cotacoes-gerar-dav.test.js`

**Interfaces:**
- Botão: `<a href="https://cotafrete.ventura.inf.br/dav" target="_blank" rel="noopener">GERAR DAV</a>` com o mesmo estilo dos botões da barra da tela.
- Export: continua escrevendo itens em A–G das linhas 2–25 e observações em B26; não escreve K–Q nem B30–B37.

- [ ] **Step 1: Testes falhando:** a página tem o link GERAR DAV com `target="_blank"` e o endereço acima; o arquivo exportado de uma cotação de 2 itens tem a aba `ORÇAMENTO` com `K1 == "CÓDIGO HSE"`, `A33 == "VENDEDOR"`, os 2 itens em A2:A3, e a aba `LISTAS`. Registrar no teste se as validações de dados de B33 sobrevivem ao ExcelJS (Review Focus 5).
- [ ] **Step 2:** Rodar → falham.
- [ ] **Step 3:** Implementar. Se o ExcelJS perder as listas suspensas, mantenha o export (o robô não precisa delas) e mostre na tela, ao exportar: "As listas de seleção (vendedor, pagamento…) não vêm no arquivo exportado: use o modelo do Gerar DAV se precisar delas."
- [ ] **Step 4:** `npm test`: os testes novos passam e as falhas continuam as 7 de antes.
- [ ] **Step 5: Commit** `feat(minhas-cotacoes): botao Gerar DAV e planilha base v3`

## Task 7: Ponta a ponta (precisa do Enzo)

- [ ] **Step 1:** Mostrar ao Enzo o que copiar para a VM e o `.env` (spec §6.5, sem valores) e pedir que ele suba a branch na VM com `DAV_DRY_RUN=1`. O Claude não copia nada para o servidor (`docs/SERVIDOR.md`).
- [ ] **Step 2:** Com o Enzo: enviar uma planilha de teste pela tela em DRY_RUN e conferir o relatório "simulação concluída".
- [ ] **Step 3:** Só depois de "pode salvar" no chat, com cliente e produtos que o Enzo indicar: `DAV_DRY_RUN=0`, gerar um DAV real, baixar o PDF e conferir o número no HSE.
- [ ] **Step 4:** Rodar a suíte inteira dos dois repositórios, mostrar o resultado e perguntar ao Enzo sobre push/PR. Lembrar: o modo pasta do `C:\RoboOrcamento` é desligado só quando o Enzo disser (spec Q7).
