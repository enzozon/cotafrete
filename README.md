# Cotafrete — rebranding Codex / contexto enxuto

Branch: `rebranding/contexto-enxuto`. Duas implementações independentes do mesmo pedido: rebranding corporativo de todas as telas, heroes SVG animados, formulário, resultados, histórico, ajuda e painel administrativo. Identidade Ventura e funcionalidades preservadas. Sem dependências novas de animação.

## Resultado visual e validação

- **321 testes funcionais passaram em cada branch**, na mesma suíte de layout, painel, cotação, ficha, documentação e autenticação administrativa.
- **44 verificações visuais passaram por branch**: 11 telas × 390/1440px × claro/escuro. HTTP 200, nenhum erro JavaScript, nenhum overflow horizontal do documento e nenhuma animação longa em execução com movimento reduzido.
- Capturas usam somente dados fictícios. A rede externa foi bloqueada durante as capturas; nenhuma cotação real, mensagem ou e-mail foi enviado.
- [Direção visual, referências e mapa de telas](docs/rebranding/IMPLEMENTACAO.md) · [Medições visuais](docs/rebranding/qa-comum/results.json) · [Saída dos testes](docs/rebranding/qa-comum/pytest.txt).

![Login desktop](docs/rebranding/qa-comum/login-1440-claro.png)

![Dashboard desktop](docs/rebranding/qa-comum/dashboard-1440-claro.png)

[Login no celular](docs/rebranding/qa-comum/login-390-claro.png) · [Formulário](docs/rebranding/qa-comum/formulario-1440-claro.png) · [Dashboard no celular](docs/rebranding/qa-comum/dashboard-390-claro.png) · [Tema escuro](docs/rebranding/qa-comum/dashboard-1440-escuro.png).

## Consumo medido das duas sessões Codex

| Métrica em tokens | Skills atuais | Contexto enxuto |
|---|---:|---:|
| Entrada total (inclui cache) | 3.701.482 | 3.048.708 |
| Entrada reutilizada em cache | 3.249.152 | 2.612.352 |
| Entrada sem cache | 452.330 | 436.356 |
| Saída total | 20.777 | 16.947 |
| Raciocínio (já incluído na saída) | 2.423 | 2.331 |
| Total processado: entrada + saída | 3.722.259 | 3.065.655 |

Nesta execução, o perfil enxuto processou **656.604 tokens a menos (17.64%)**. Considerando apenas entrada sem cache + saída, os valores foram **473.107 e 453.303**, diferença de **4.19%**. Essa segunda soma também não é uma tarifa: entrada e saída podem ter pesos diferentes.

Os milhões representam a soma de entradas repetidas a cada chamada, incluindo histórico e ferramentas; não representam milhões de palavras diferentes produzidas. Cache já faz parte da entrada e raciocínio já faz parte da saída: somá-los novamente daria dupla contagem. `cache_write_input_tokens` foi zero nas duas sessões.

### Fonte e contagem

Os números vêm do último evento `token_count.info.total_token_usage` de cada sessão do Codex, conferido com `threads.tokens_used` no estado local. Esse total é cumulativo: inclui os turnos anteriores às interrupções, retomadas e correções finais. Não somamos novamente os totais cumulativos de cada retomada.

- Skills atuais: `01a0a0e0-876d-7440-83ee-459d490274d0`; última medição `2026-09-20T00:59:30.695Z`.
- Enxuto: `01a0a0e5-4f9f-7082-8887-59bb62c24151`; última medição `2026-09-20T00:59:30.316Z`.
- [Dados completos, hashes e evidências](docs/rebranding/dados-tokens.json). Os logs integrais ficam localmente em `C:/Users/vendas12/enzo/cotafrete-benchmark/` e no histórico do Codex; não foram publicados porque podem incluir contexto privado da máquina.

### Condições do teste

Mesmo commit-base `806f1ff6ca882235d9f12ed6fa543c6862a1ce43`, prompt inicial idêntico, modelo `gpt-6-astra`, esforço `low`, sessões novas e worktrees separados. Cada sessão fez sua própria pesquisa e implementação, sem ler o resultado da outra e sem subagentes. [Prompt original](docs/rebranding/PROMPT.txt).

O perfil atual manteve os plugins habilitados. O perfil enxuto desativou ECC e Superpowers e acrescentou um `AGENTS.md` curto. Neste ambiente, somente os overrides de plugin não removeram ECC do catálogo: foi necessário também desativar as skills por caminho no perfil separado `cotafrete-benchmark-enxuto.config.toml`. A configuração global principal não foi substituída.

O catálogo inicial registrado mostrou **311 e 57 entradas visíveis**, respectivamente; ECC teve **283 e zero**. Superpowers não apareceu no catálogo inicial de nenhuma das duas, apesar de habilitado na configuração original: não é possível atribuir a ele uma economia isolada. As descrições das skills remanescentes também podem ocupar mais espaço quando há menos entradas.

A primeira chamada usou **25.689 e 23.552 tokens de entrada**, redução de **8,32%**. Isso mede toda a entrada inicial, não apenas as skills. A redução total posterior inclui diferenças na quantidade de leituras, tentativas, correções e respostas.

### Gastos adicionais e limitações

- Uma primeira tentativa enxuta carregou ECC indevidamente e foi interrompida: **105.859 tokens** (105.443 de entrada, incluindo 71.424 em cache, e 416 de saída). Está registrada separadamente como `tentativa-invalida`; não entra na comparação válida, mas foi consumo real do experimento.
- A conversa coordenadora também consumiu tokens preparando, monitorando, diagnosticando, revisando e documentando o experimento. No recorte desde o pedido original até **2026-09-20T19:38:00.462Z**, foram **14.560.548 tokens processados**, dos quais **13.870.848 de entrada em cache**. Esse é um retrato parcial anterior à publicação e resposta final, compartilhado entre as duas branches, sem divisão arbitrária. Não está incluído nos totais das sessões da tabela.
- A conta atingiu limites durante o trabalho em 14/09; houve retomadas em datas posteriores, erros de permissão do sandbox e correções após QA externo. Tempo de calendário não equivale a tempo de implementação. A memória compartilhada também ficou indisponível durante parte do experimento.
- As sessões tiveram as mesmas regras de sandbox. A validação comum do coordenador foi feita fora do bloqueio do navegador, nas duas versões. Scripts/testes externos não fazem chamadas ao modelo; sua preparação e revisão pertencem ao custo compartilhado do coordenador.
- Na revisão visual final, o coordenador acrescentou `width:auto` em `.abertas .hora` na versão skills atuais: a sessão havia corrigido a quebra de texto, mas deixado a largura de célula herdada, tornando o horário vertical. Essa intervenção de uma linha pertence ao consumo compartilhado, não à sessão da tabela. Os artefatos incluem essa correção assistida.
- É **uma execução por configuração**, com mudanças simultâneas de catálogo e instruções locais, efeitos de cache e escolhas de implementação. O resultado não demonstra que desativar skills sempre economiza esta porcentagem nem isola causalmente cada plugin.
- Login do vendedor continua com o comportamento do commit-base. As branches não incorporam os commits posteriores da `main`, inclusive mudanças posteriores de autenticação. Antes de usar em produção, integrar a versão escolhida à base atual e repetir a validação.
- Os contadores são de tokens do Codex, **não uma fatura em reais/dólares** nem uma conversão exata do limite do plano Plus. O consumo do observador Claude Mem e de outras sessões/aplicativos não está nesses contadores.
- As duas branches do Claude são experimentos separados (`rebranding/claude-skills-atuais` e `rebranding/claude-contexto-enxuto`). Seus arquivos, commits e relatórios não foram alterados por esta entrega; estes números não são uma comparação Codex × Claude.

## Como visualizar nesta máquina

Na pasta desta branch, execute:

```powershell
& C:/Users/vendas12/enzo/cotafrete-dev/.venv/Scripts/python.exe docs/rebranding/validar.py --serve
```

Abra `http://127.0.0.1:8012`. A prévia usa dados sintéticos e não envia operações às transportadoras. O roteiro de cada branch tem sua própria implementação; a suíte externa comum é a evidência equivalente usada na comparação. As animações são originais e finitas; as capturas estáticas não demonstram o movimento.

## Organização das branches

Esta é uma alternativa completa, não um complemento da outra. As quatro branches têm nomes e worktrees diferentes e podem coexistir. Como redesenham os mesmos arquivos, mesclá-las entre si pode gerar conflitos. Não foi feito merge na `main` nem deploy.

---

## Documentação original do projeto

# Cotafrete — Ventura

Cotação de frete em várias transportadoras a partir de **um formulário só**.

O problema que resolve: para saber quem leva mais barato, alguém abria sete
sites, redigitava os mesmos dados em cada um, anotava num papel e comparava.
Aqui se preenche uma vez e o sistema faz o resto.

```
Cotafrete.bat        <- duplo clique, abre em http://localhost:8001
Servidor.bat         <- publica na rede da empresa, na porta 8000
```

Para instalar no servidor da empresa: [docs/DEPLOY_SERVIDOR.md](docs/DEPLOY_SERVIDOR.md).
O Server 2012 R2 não roda o Chromium das transportadoras — o guia explica por
que, e como subir numa VM dentro do próprio servidor.

---

## As sete transportadoras, e por que não são iguais

A diferença que define a interface inteira: **nem todas devolvem preço**.

| transportadora | como cota | tempo | o que devolve |
|---|---|---|---|
| **Camilo dos Santos** (SSW) | login + formulário | ~25 s | **preço + composição completa** |
| **Jadlog Entregas** (painel) | login + formulário | ~15 s | preço de varejo (balcão) |
| **Generoso** | formulário em 5 etapas | ~50 s | só confirmação; preço por e-mail |
| **Della Volpe** | formulário único | ~110 s | só confirmação; preço por e-mail |
| **Movvi** | WhatsApp | — | pessoa responde |
| **Translovato** | WhatsApp | — | pessoa responde |
| **Continental** | WhatsApp | — | pessoa responde |

Três consequências de projeto:

1. **Os resultados aparecem conforme chegam.** A Jadlog responde em 15 s; a
   Della Volpe em 110 s. Esperar a mais lenta seria dois minutos de tela
   branca.
2. **Cada preço diz o que inclui.** R$ 33,35 da Jadlog (você leva ao balcão)
   ao lado de R$ 69,91 da Camilo (coleta na porta, com CT-e e ICMS) leva à
   decisão errada sem contexto.
3. **WhatsApp nunca é automático.** O sistema prepara a mensagem; quem aperta
   enviar é a pessoa. Não existe status "aguardando retorno" para elas.

---

## A armadilha central: o mesmo número, quatro formatos

Você digita `30`. Cada site quer isso escrito de um jeito, e **errar não dá
erro** — cota a carga errada e o preço parece certo.

| site | medida | peso |
|---|---|---|
| Della Volpe | `30,0` — 1 casa obrigatória | livre |
| Jadlog painel | `30` — inteiro | `1,00` — 2 casas |
| Generoso | `30` — inteiro | `1,00` — 2 casas |
| Camilo (SSW) | **`0,300` — METROS** | `1,000` |

Isso já quebrou três vezes neste projeto: a Della Volpe cotou carga 10× menor,
a Jadlog 100× menor, e a Camilo cotaria uma caixa de 30 metros.

**A tradução mora no adapter, nunca no formulário.** O usuário digita
centímetros; quem sabe o resto é o código, e cada regra tem teste.

---

## Como usar

### Primeira vez

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
```

Copie o `.env` (nunca vai pelo Git — tem senhas) para a raiz do projeto.

### No dia a dia

Duplo clique em **`Cotafrete.bat`**. Ele sobe o servidor e abre o navegador.

**Fechar a janela desliga o sistema** — é de propósito. Em segundo plano ele
seguraria a porta 8000 e o próximo duplo clique falharia sem explicar. Se a
porta já estiver ocupada, o `.bat` detecta e pergunta se pode encerrar.

⚠ Cotação em andamento **não sobrevive** ao fechamento: as transportadoras
rodam em threads dentro do processo. Se a tela ainda mostra "cotando…",
espere os ~25 s. O que ficar pendente é marcado como *interrompido* na
próxima subida.

---

## As telas

| rota | o que faz |
|---|---|
| `/login` | digitou o nome, entrou — **placeholder, sem senha** |
| `/` | formulário único |
| `/cotar` | dispara e redireciona na hora |
| `/cotacao/N` | resultados, com selo no mais barato e print de cada uma |
| `/historico` | as cotações **da pessoa**, com o melhor preço de cada |
| `/adm` | painel da empresa inteira — senha própria, no `.env` |
| `/adm/cotacao/N` | a cotação de **qualquer** vendedor, inteira |

**Separação por usuário:** cada um vê só as suas. Trocar o número na URL não
abre a cotação alheia — o usuário entra na consulta ao banco.

### Painel do administrador

`COTAFRETE_ADM_SENHA` no `.env`. **Sem essa linha, `/adm` responde 404** — a
tela não passa a existir "aberta por engano" numa pasta onde ninguém
configurou nada. O cookie guarda um HMAC derivado da senha, e trocar a senha
derruba todas as sessões sozinha.

O painel mostra a empresa inteira no período escolhido (24 h / 7 / 30 dias /
tudo): faixa ao vivo de hoje, **alerta de falhas seguidas** a partir de 3,
movimento por dia, aproveitamento de cada transportadora, quem mais cotou,
rotas mais cotadas e o histórico de todo mundo — filtrável por vendedor e por
"só com falha".

Clicar numa linha do histórico abre **`/adm/cotacao/N`**: o que cada
transportadora respondeu, com preço, prazo, protocolo, o texto técnico do erro
**inteiro** (a tela do vendedor corta em 400 caracteres), o print de cada uma,
quanto tempo cada uma levou, a ficha da carga e quais conversas de WhatsApp o
vendedor chegou a abrir.

Essa é uma rota **própria** do adm: `/cotacao/N` continua exigindo o cookie do
vendedor e filtrando por dono. Duas portas separadas, em vez de uma porta com
um `if adm` no meio — e a garantia da tela do vendedor fica intacta, com teste
provando as duas coisas juntas.

A tela é **só leitura**: daqui não se apaga cotação, não se abre WhatsApp e
não se repete cotação. O adm entra para entender o que aconteceu; as ações
continuam sendo de quem cotou.

⚠ O painel junta CNPJ, razão social e valor de nota de todos os clientes num
lugar só. O `Servidor.bat` avisa que `0.0.0.0` inclui o Wi-Fi: numa rede com
visitantes, a senha do `.env` é a única barreira.

**Cidade e estado não são campos**: saem do CEP via ViaCEP. Foi digitar
cidade à mão que gerou uma ficha dizendo "São José dos Campos" com CEP de São
Bernardo do Campo — e como a Jadlog cota por CEP e a Della Volpe por cidade,
a mesma ficha cotava duas rotas diferentes.

**Razão social vem do CNPJ** (BrasilAPI), para a mensagem de WhatsApp dizer
quem envia, quem recebe e quem paga.

### Página de WhatsApp

`web/cotacao_whatsapp.html` — arquivo único, autocontido, abre com dois
cliques. Gera a mensagem no padrão da empresa e abre o WhatsApp das três
transportadoras com o texto pronto. Tem 24 checagens que rodam no
carregamento (`window.autoteste()` no console).

---

## Arquitetura

Separação **pura / IO**, que é o que torna o projeto testável:

```
core/
  models.py    modelo central — não conhece transportadora nenhuma
  ficha.py     texto "Chave: valor" -> modelo (puro; a busca de CEP é injetada)
  cep.py       CEP -> cidade/UF/IBGE (ViaCEP, com cache)
  cnpj.py      CNPJ -> razão social (BrasilAPI, com cache)
  banco.py     histórico em SQLite

carriers/
  base.py      contrato comum + utilitários de screenshot
  <nome>/
    mapping.py   camada PURA: modelo -> campos daquele site
    adapter.py   camada de BROWSER: Playwright

web/
  app.py                 interface FastAPI
  cotacao_whatsapp.html  página de WhatsApp, independente
```

**O que é puro roda sem internet e tem teste.** O que é browser é fino de
propósito: só localizar campo e digitar.

**Seletores por rótulo, nunca por posição.** É o que faz a automação
sobreviver a mudança de layout — e na Camilo a ordem dos campos de medida é
Altura/Largura/Comprimento, invertida em relação aos outros.

---

## Formato de entrada

Ver **`REGRAS_FICHA.md`** — as 7 regras do arquivo de texto:

```
Nome Completo: Enzo Zon
email: vendas2@venturainformatica.com.br
WhatsApp: +55 (27) 3339-1891
CEP ORIGEM: 09895-003
CEP DESTINO: 29105-770
CNPJ Remetente: 60.042.686/0001-05
Peso Total (kg): 12          <- peso de UM volume
Quantidade de Volumes: 3     <- carga total = 36 kg
Comprimento (cm): 30
Valor Total Nota Fiscal: 568,77
Material: LUVA DE BOMBEIRO
```

Decisões de interface do site: **`REGRAS_SITE_COTACAO.md`**.

---

## Testes

```bash
python -m pytest tests\ -q      # 777 testes, nenhum usa internet
```

Cada teste tem o caso real que o gerou no docstring. Não são testes de
fachada: todos foram escritos **antes** do fix, e cada um falhou primeiro.

Scripts de verificação contra os sites reais:

| script | o que faz |
|---|---|
| `tests/manuais/testar_tudo.py` | 3 cargas em cada transportadora, dry-run |
| `tests/manuais/testar_teste_real.py` | ficha real na Jadlog e Della Volpe |
| `tests/manuais/testar_generoso_real.py` | 5 envios reais no Generoso |
| `recon/recon_*.py` | mapeamento read-only de cada site |

Todos rodam **a partir da raiz do projeto**. `recon/` mapeia site novo (lê, não
envia); `tests/manuais/` são os que se roda a mão contra os sites reais — ficam
dentro de `tests/` mas o `pytest` não os coleta, porque `testar_*` não casa com
o padrão `test_*` que ele procura.

---

## Credenciais e dados sensíveis

Tudo no **`.env`**, que nunca vai para o Git:

```
SSW_DOMINIO / SSW_USUARIO / SSW_SENHA      Camilo dos Santos
JADLOG_PAINEL_USUARIO / _SENHA             Jadlog Entregas
TRANSLOVATO_CNPJ / _USUARIO / _SENHA       Translovato
GENEROSO_USUARIO / GENEROSO_SENHA          Transporte Generoso
DV_ENVIO_REAL_AUTORIZADO                   trava do envio real da Della Volpe
COTAFRETE_ADM_SENHA                        senha do painel /adm
```

**`GENEROSO_USUARIO`** é o "E-mail corporativo" da tela de login deles. Sem
essas duas linhas a Generoso nem tenta: deslogada ela não mostra preço, só
confirma o recebimento e responde por e-mail horas depois.

Fora do Git também: `cotafrete.db`, `runs/`, `teste_real/`, `recon_out/`,
`.cache/` — todos têm CNPJ de cliente e valor de nota fiscal.

**`DV_ENVIO_REAL_AUTORIZADO`** é a trava do envio real da Della Volpe: cada
submissão vira uma cotação na fila de um vendedor. O código nunca liga isso
sozinho.

---

## Estado

**Fase 1 — pronta e em uso.** Camilo, Jadlog e os três cartões de WhatsApp,
com login, histórico por usuário, repetir cotação, máscaras de CNPJ e CEP,
validação antes de cotar e resultados aparecendo conforme chegam.

**Fase 2 — pendente.** Generoso e Della Volpe. Os adapters estão prontos e
validados; falta somá-los em `AUTOMATICAS` no `web/app.py`.

> **Decisão a tomar antes:** a Della Volpe só envia com **janela de navegador
> visível** — o reCAPTCHA v3 barra headless e responde "A submissão
> mencionou-se como spam", sem gerar e-mail. Medido: 5 envios headless não
> geraram nada; com janela real, passaram. Ou se aceita a janela abrindo a
> cada cotação, ou ela fica fora da automação.

**Fase 3 — depois.** Ingestor IMAP para ler as propostas em PDF e preencher
o preço que a Generoso e a Della Volpe mandam por e-mail.

### Onde rodar

Hoje roda na máquina do Enzo. O servidor da empresa é **Windows 8.1**, onde
o Python 3.12 funciona mas o Chromium do Playwright **não** — o Chrome 109,
de janeiro de 2023, foi o último a suportar esse sistema. Guia de
verificação em `TESTE_NO_SERVIDOR.txt`.

---

## O que já foi confirmado contra os sites reais

- **Fator de cubagem 300** na Della Volpe, por quatro propostas em PDF que
  declaram o peso cubado calculado por eles. Era suposição desde o início.
- **R$ 69,91** na Camilo, o mesmo valor da cotação feita à mão — prova de que
  o adapter reproduz o que uma pessoa faria.
- **5 cotações reais** na Della Volpe (4 propostas recebidas por e-mail) e
  **5 no Generoso**, todas confirmadas pelo site.
