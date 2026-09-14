# Braço 3 de 4 — Claude CLI com a configuração atual

Branch: `rebranding/claude-skills-atuais` · base: `806f1ff` · 14/09/2026

Esta branch é **um** dos quatro braços de um teste: a mesma tarefa de
rebranding visual, executada em duas ferramentas (Codex e Claude) × duas
configurações (tudo ligado × ECC e Superpowers desligados, como manda o
`GUIA-CONTEXTO-CODEX-CLAUDE.md`). O objetivo não era a tela bonita: era medir
o que cada configuração cobra pelo mesmo trabalho.

> **Leia isto antes dos números:** nenhum dos quatro braços terminou a tarefa.
> Os dois do Codex morreram com erro de infraestrutura; os dois do Claude
> foram cortados por limite de uso da conta (HTTP 429) aos ~3,2 minutos. O que
> está medido abaixo é **trabalho por tempo e por dinheiro gastos**, não
> "quanto custa concluir o rebranding". Os números são reais e reproduzíveis;
> a conclusão que eles sustentam é mais estreita do que a pergunta original.

## Como o teste foi montado

| controle | valor |
|---|---|
| commit base dos 4 braços | `806f1ff` |
| enunciado | idêntico, `cotafrete-benchmark/prompt.txt` |
| modelo (lado Claude) | `claude-opus-5` nos dois braços |
| sessão | nova por braço (`claude -p`), para o uso de uma não contaminar a outra |
| variável sob teste | **só** os plugins carregados |

O único fator alterado entre os braços 3 e 4 foi
`enabledPlugins: {ecc@ecc: false, superpowers@claude-plugins-official: false}`.
Ponytail, Claude Mem, Obsidian e commit-pt continuaram ligados nos dois — o
guia manda avaliar esses separadamente, e mexer em duas variáveis por vez não
mede nada.

## O que a configuração carrega, antes de qualquer trabalho

Sonda trivial ("responda apenas OK"), sessão nova, mesmo modelo:

| | catálogo carregado | contexto | custo do turno |
|---|---|---|---|
| **config atual (esta branch)** | 346 skills, 73 agentes, 510 comandos | 43.478 tokens | $0,0506 |
| ECC + Superpowers desligados | 43 skills, 5 agentes, 124 comandos | 33.756 tokens | $0,0308 |

Custo fixo por sessão: **−9.722 tokens (−41,8%)** e **−39% no turno trivial**.
Este é o número mais sólido do experimento inteiro, porque não depende de a
tarefa ter terminado.

## Os dois braços do Claude, lado a lado

Ambos cortados pelo mesmo 429, com praticamente o mesmo tempo de parede:

| | **esta branch** (atual) | contexto enxuto |
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

**A configuração enxuta gastou mais dinheiro — e entregou muito mais.** Ela
custou 25% a mais ($4,75 contra $3,81) porque avançou mais: mais turnos, 57%
mais tokens de saída, quatro vezes mais edições. O cache lido é maior pelo
mesmo motivo: a conversa dela cresceu mais.

Normalizando pelo trabalho produzido, a direção se inverte:

| | esta branch | contexto enxuto |
|---|---|---|
| custo por linha entregue | **US$ 0,0508** | **US$ 0,0144** |
| tokens por linha entregue | **48.124** | **15.338** |

**3,5× mais barato por linha de código entregue, com o catálogo reduzido.**

O perfil de ferramentas mostra para onde foi a diferença: este braço gastou
turnos em `Read` (17 contra 7) e em manter uma lista de tarefas
(`TaskCreate`/`TaskUpdate`, 6 chamadas que o outro braço simplesmente não
fez), enquanto o enxuto foi para `Edit` (16 contra 4). Também levou 2 negações
de permissão, que custam turno e não produzem nada.

### O que isso NÃO diz

- Não diz que o rebranding custa $3,81 ou $4,75. Nenhum dos dois terminou.
- Não diz que o resultado visual do braço enxuto é melhor — são 331 linhas
  contra 75, e mais código não é melhor código. A comparação de qualidade
  precisa das corridas completas.
- Não compara Claude com Codex, porque o lado Codex não produziu medição
  nenhuma (ver abaixo).

## Os dois braços do Codex

Não foram tocados por este trabalho, a pedido. Ambos falharam:

| braço | branch | saída | turnos | uso registrado |
|---|---|---|---|---|
| Codex + config atual | `rebranding/skills-atuais` | exit 1 | 0 | nenhum |
| Codex + guia | `rebranding/contexto-enxuto` | exit 1 | 0 | nenhum |

Morreram às 14:11, com 1 segundo de diferença entre si — o de skills após 7
minutos, o enxuto após 2. O stderr do primeiro traz
`failed to record rollout items: thread ... not found`. Como nenhum turno
completou, o campo `usage` ficou nulo nos dois: **não existe número de token do
lado Codex.** Sobrou trabalho parcial não commitado na branch `skills-atuais`.

## O que está commitado aqui

O que este braço produziu antes do corte: `web/layout.py`, +75 −5. É uma
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
