# Braço 4 de 4 — Claude CLI seguindo o GUIA-CONTEXTO-CODEX-CLAUDE.md

Branch: `rebranding/claude-contexto-enxuto` · base: `806f1ff` · 14/09/2026

Esta branch é **um** dos quatro braços de um teste: a mesma tarefa de
rebranding visual, executada em duas ferramentas (Codex e Claude) × duas
configurações (tudo ligado × ECC e Superpowers desligados, como manda o
`GUIA-CONTEXTO-CODEX-CLAUDE.md`, seção 3). O objetivo não era a tela bonita:
era medir o que cada configuração cobra pelo mesmo trabalho.

> **Leia isto antes dos números:** três dos quatro braços não terminaram. Só o
> Codex com a configuração atual chegou ao fim (exit 0), e só na segunda
> tentativa, retomando a thread. O Codex com o guia falhou duas vezes; os dois
> do Claude foram cortados por limite de uso da conta (HTTP 429) aos ~3,2
> minutos. O que está medido abaixo é **trabalho por tempo e por dinheiro
> gastos**, não "quanto custa concluir o rebranding". Os números são reais e
> reproduzíveis; a conclusão que eles sustentam é mais estreita do que a
> pergunta original.

## O que o guia manda, e o que foi aplicado aqui

A seção 3 do guia diz para desativar sem apagar:

```powershell
claude plugin disable ecc@ecc
claude plugin disable superpowers@claude-plugins-official
```

Para não mexer na configuração global da máquina no meio de um teste, o mesmo
efeito foi obtido por execução, com `--settings`:

```json
{"enabledPlugins": {"ecc@ecc": false, "superpowers@claude-plugins-official": false}}
```

Ponytail, Claude Mem, Obsidian e commit-pt **continuaram ligados**, aqui e no
braço de comparação. O guia manda avaliar esses separadamente, e mexer em duas
variáveis por vez não mede nada.

## Como o teste foi montado

| controle | valor |
|---|---|
| commit base dos 4 braços | `806f1ff` |
| enunciado | idêntico, `cotafrete-benchmark/prompt.txt` |
| modelo (lado Claude) | `claude-opus-5` nos dois braços |
| sessão | nova por braço (`claude -p`), para o uso de uma não contaminar a outra |
| variável sob teste | **só** os plugins carregados |

## O efeito do guia, antes de qualquer trabalho

Sonda trivial ("responda apenas OK"), sessão nova, mesmo modelo:

| | catálogo carregado | contexto | custo do turno |
|---|---|---|---|
| config atual | 346 skills, 73 agentes, 510 comandos | 43.478 tokens | $0,0506 |
| **esta branch (guia aplicado)** | **43 skills, 5 agentes, 124 comandos** | **33.756 tokens** | **$0,0308** |

Custo fixo por sessão: **−9.722 tokens (−41,8%)** e **−39% no turno trivial**.
Este é o número mais sólido do experimento inteiro, porque não depende de a
tarefa ter terminado. É também exatamente o que o guia prometia — e ele já
avisava, no fim da seção 6, que menos contexto **não** implica a mesma redução
na cobrança. O resto desta página mostra por quê.

## Os dois braços do Claude, lado a lado

Ambos cortados pelo mesmo 429, com praticamente o mesmo tempo de parede:

| | config atual | **esta branch** (guia) |
|---|---|---|
| turnos completos | 45 | 49 |
| duração até o corte | 3 min 17 s | 3 min 13 s |
| tokens de entrada | 60 | 82 |
| tokens de saída | 17.615 | 27.609 |
| cache gravado | 156.646 | 152.954 |
| cache lido | 3.434.997 | 4.896.274 |
| **total de tokens** | **3.609.318** | **5.076.919** |
| **custo** | **US$ 3,81** | **US$ 4,75** |
| chamadas `Edit` | 4 | 16 |
| chamadas `Read` | 17 | 7 |
| `TaskCreate` / `TaskUpdate` | 6 | 0 |
| negações de permissão | 2 | 0 |
| **linhas entregues em `web/layout.py`** | **75** | **331** |

### O que isso diz

**Esta branch gastou mais dinheiro — e entregou muito mais.** Custou 25% a
mais ($4,75 contra $3,81) porque avançou mais no mesmo tempo: mais turnos, 57%
mais tokens de saída, quatro vezes mais edições. O cache lido é maior pelo
mesmo motivo — a conversa dela cresceu mais.

Quem olhar só a linha do custo vai concluir que o guia encareceu o trabalho.
Normalizando pelo que foi produzido, a direção se inverte:

| | config atual | esta branch |
|---|---|---|
| custo por linha entregue | US$ 0,0508 | **US$ 0,0144** |
| tokens por linha entregue | 48.124 | **15.338** |

**3,5× mais barato por linha de código entregue.**

O perfil de ferramentas mostra para onde foi a diferença: o braço com tudo
ligado gastou turnos em `Read` (17 contra 7) e em manter uma lista de tarefas
(`TaskCreate`/`TaskUpdate`, 6 chamadas que esta execução simplesmente não
fez), enquanto esta foi para `Edit` (16 contra 4). O outro braço também levou
2 negações de permissão; esta, nenhuma.

### O que isso NÃO diz

- Não diz que o rebranding custa $3,81 ou $4,75. Nenhum dos dois terminou.
- Não diz que o resultado visual desta branch é melhor — são 331 linhas contra
  75, e mais código não é melhor código. A comparação de qualidade precisa das
  corridas completas.
- Não compara Claude com Codex, porque o lado Codex não produziu medição
  nenhuma (ver abaixo).
- Uma corrida só por braço. Não há repetição para separar efeito de variação.

## Os dois braços do Codex

Não foram tocados por este trabalho, a pedido — as branches ficaram como
estavam. Os números abaixo são de leitura do rollout das threads
(`codex_usage.py`), acumulando a primeira corrida e a retomada.

A primeira tentativa morreu nos dois braços às 14:11, com 1 segundo de
diferença — o de skills após 7 minutos, o enxuto após 2, `exit 1`, zero turnos
completos, `usage` nulo. O stderr traz
`failed to record rollout items: thread ... not found`. Às 18:04 as duas
threads foram retomadas: **a de skills terminou (exit 0)**, a do guia falhou
de novo (exit 1).

| | Codex + config atual | Codex + guia |
|---|---|---|
| resultado final | **exit 0** | exit 1 |
| total de tokens | 2.427.804 | 1.757.641 |
| entrada | 2.409.372 | 1.744.400 |
| entrada em cache | 2.211.328 | 1.562.240 |
| saída | 18.432 (2.222 de raciocínio) | 13.241 (1.869) |
| contexto da 1ª requisição | 25.689 | 23.552 |
| arquivos alterados | 6 (+59 −18) | 5 (+64 −19) |
| CSS novo | 113 linhas | 148 linhas |
| evidência em `docs/rebranding/` | IMPLEMENTACAO.md + 8 telas em HTML | `qa-comum`, `validar.py` |

**Um achado importante para quem for aplicar o guia:** do lado Codex, desligar
os plugins quase não mexeu no contexto inicial — 25.689 → 23.552 tokens, só
**−8,3%**, contra os −41,8% medidos no Claude nesta mesma branch. O arnês do
Codex tem uma tentativa anterior registrada como `tentativa-invalida-*` e uma
rotina `--diagnose --skills-filter` no `run_experiment.py`, sinal de que fazer
a desativação valer de fato foi difícil ali. **O guia não rende igual nas duas
ferramentas** — o que ele promete se confirma no Claude e quase não aparece no
Codex.

Não há comparação em dólar entre Codex e Claude: o rollout do Codex registra
tokens, não custo, e os modelos são de fornecedores diferentes com tabelas
diferentes. Somar ou dividir esses números entre as duas ferramentas daria um
número inventado.

## O que está commitado aqui

O que este braço produziu antes do corte: `web/layout.py`, +331 −70. É uma
tarefa interrompida no meio, não um rebranding pronto — está aqui como
evidência do experimento, não como entrega.

## Como repetir

```
cd C:\Users\vendas12\enzo\cotafrete-benchmark
python run_claude.py claude-skills-atuais      # um de cada vez
python run_claude.py claude-contexto-enxuto
python summarize.py
```

Rode **um braço por vez**. A primeira tentativa disparou os dois em paralelo
enquanto uma terceira sessão trabalhava na mesma conta, e as três dividiram o
mesmo limite — foi o que produziu o 429 aos 3 minutos.

Arquivos brutos preservados em `cotafrete-benchmark/`: `*.jsonl` (stream
completo), `*-meta.json` (comando e horários), `*-truncado-429.patch` (o
diff de cada braço no momento do corte). O `summarize.py` recalcula a tabela
a partir do JSONL e registra o sha256 de cada um.
