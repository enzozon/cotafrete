# Braço 3 de 4 — Claude CLI com a configuração atual

Branch: `rebranding/claude-skills-atuais` · base: `806f1ff` · 15/09/2026

Um dos quatro braços de um teste: a mesma tarefa de rebranding visual,
executada em duas ferramentas (Codex e Claude) × duas configurações (tudo
ligado × ECC e Superpowers desligados, como manda o
`GUIA-CONTEXTO-CODEX-CLAUDE.md`). O objetivo não era a tela bonita: era medir
o que cada configuração cobra pelo mesmo trabalho.

> **Nenhum braço terminou a tarefa inteira.** Os dois do Claude rodaram ~16
> minutos cada e foram cortados pelo limite de uso da conta (HTTP 429), não
> por erro. O que está medido é **o que cada configuração entrega por um
> orçamento praticamente igual** — não "quanto custa concluir o rebranding".

## Como o teste foi montado

| controle | valor |
|---|---|
| commit base dos 4 braços | `806f1ff` |
| enunciado | idêntico, `cotafrete-benchmark/prompt.txt` |
| modelo | `claude-opus-5` nos dois braços do Claude |
| sessão | nova por braço (`claude -p`), sem contaminação entre elas |
| árvore no início | idêntica ao `806f1ff`, sem este README (ele descreve o outro braço e enviesaria a execução) |
| variável sob teste | **só** os plugins carregados |
| teto de orçamento | o braço 4 rodou com `--max-budget-usd 14.45`, o que o braço 3 gastou, para não levar vantagem por pegar uma janela de uso limpa |

## O que a configuração carrega, antes de qualquer trabalho

Sonda trivial ("responda apenas OK"), sessão nova, mesmo modelo:

| | catálogo carregado | contexto | custo do turno |
|---|---|---|---|
| **config atual (esta branch)** | 346 skills, 73 agentes, 510 comandos | 43.478 tokens | $0,0506 |
| ECC + Superpowers desligados | 43 skills, 5 agentes, 124 comandos | 33.756 tokens | $0,0308 |

**−9.722 tokens de contexto fixo por sessão (−41,8%), −39% no turno trivial.**
Este número é sólido e independe de a tarefa ter terminado. Guarde-o — e leia
a seção seguinte antes de concluir qualquer coisa a partir dele.

## A corrida de verdade, os dois braços lado a lado

| | **esta branch** (atual) | contexto enxuto |
|---|---|---|
| turnos | 133 | 112 |
| duração | 16 min 18 s | 15 min 48 s |
| como terminou | 429 (limite da conta) | 429 (limite da conta) |
| tokens de saída | 99.827 | 75.005 |
| cache gravado | 259.792 | 219.553 |
| cache lido | 18.533.105 | 17.171.994 |
| **total de tokens** | **18.892.724** | **17.466.552** |
| **custo** | **US$ 14,4436** | **US$ 12,7393** |
| arquivos de produção alterados | 4 | 3 |
| linhas de produção | **+1199 −429** | +1023 −224 |
| teste novo | **nenhum** | 277 linhas |
| suíte de testes | 862 passam, 1 erro | 863 passam, **7 erros** |

### O que isso diz

**As duas configurações custam praticamente o mesmo por unidade de trabalho.**

| | esta branch | contexto enxuto |
|---|---|---|
| custo por linha de produção entregue | US$ 0,01205 | US$ 0,01245 |
| custo por turno | US$ 0,1086 | US$ 0,1137 |

Diferença de ~3%, dentro do ruído de uma corrida só. O braço enxuto gastou 12%
menos no total simplesmente porque fez 12% menos: 112 turnos contra 133.

O contexto fixo menor **não** se traduziu em economia proporcional na tarefa
longa, e o motivo está na tabela: numa corrida de 16 minutos o cache lido
chega a 18 milhões de tokens, e ao lado disso os ~10 mil tokens de catálogo
economizados por sessão somem. A economia dos 41,8% é real — ela aparece no
**custo de abrir sessão**, não no custo de trabalhar.

Isso é exatamente o que o próprio guia avisa no fim da seção 6: menos contexto
não implica a mesma redução na cobrança.

> **Onde a economia do guia vale de fato:** muitas sessões curtas. Dez perguntas
> rápidas por dia custam dez vezes o contexto fixo — e aí os −41,8% aparecem
> inteiros. Uma tarefa longa por dia dilui a diferença até o irrelevante.

### A diferença que apareceu foi de qualidade, não de preço

O enunciado pedia: *"Deixe uma verificação executável para o comportamento
visual novo que realmente importe."*

- **Esta branch não escreveu teste nenhum.** Entregou 1199 linhas de produção e
  ignorou o requisito.
- **O braço enxuto escreveu um teste — que não roda.** As 277 linhas de
  `tests/test_rebranding_visual.py` chamam `Banco.salvar_resultado()` com um
  argumento posicional a mais do que a assinatura aceita; os 7 erros da suíte
  dele saem todos daí.

Nenhum dos dois cumpriu o requisito. Um ignorou, o outro entregou quebrado.

O erro único desta branch **não** é regressão: é o `test_braspress_dom.py`, que
passa isolado (21 testes, todos verdes) e falha na suíte cheia por dependência
de ordem. Já existia antes do rebranding.

### O que isso NÃO diz

- Não diz quanto custa o rebranding: nenhum braço terminou.
- Não diz que um resultado visual é melhor. Mais linhas não é melhor código, e
  a comparação visual exige as corridas completas.
- **Uma corrida por braço.** Sem repetição, uma diferença de 3% não sustenta
  conclusão nenhuma.
- A medição anterior, de uma corrida cortada aos 3 minutos, sugeria que o guia
  era 3,5× mais barato por linha. **Aquilo era artefato do truncamento** e não
  se sustentou em 16 minutos. Fica registrado como aviso: medir configuração de
  agente com corrida curta engana.

## Os dois braços do Codex

Não foram tocados, a pedido. Números lidos do rollout das threads
(`codex_usage.py`), acumulando a primeira corrida e a retomada das 18:04:

| | Codex + config atual | Codex + guia |
|---|---|---|
| resultado final | **exit 0** | exit 1 |
| total de tokens | 2.427.804 | 1.757.641 |
| entrada (em cache) | 2.409.372 (2.211.328) | 1.744.400 (1.562.240) |
| saída | 18.432 (2.222 de raciocínio) | 13.241 (1.869) |
| contexto da 1ª requisição | 25.689 | 23.552 |
| arquivos alterados | 6 (+59 −18) | 5 (+64 −19) |
| CSS novo | 113 linhas | 148 linhas |

**O guia não rende igual nas duas ferramentas:** no Codex, desligar os plugins
mexeu quase nada no contexto inicial — 25.689 → 23.552 tokens, só **−8,3%**,
contra os −41,8% do Claude. O arnês tem uma `tentativa-invalida-*` registrada e
uma rotina `--diagnose --skills-filter` no `run_experiment.py`, sinal de que
fazer a desativação valer ali deu trabalho. Confirme que pegou antes de
concluir qualquer coisa sobre o Codex.

Não há comparação em dólar entre Codex e Claude: o rollout do Codex registra
tokens, não custo, e são fornecedores com tabelas diferentes.

## O que está commitado aqui

O que este braço produziu nos 16 minutos: `web/layout.py`, `web/painel_ui.py`,
`web/app.py`, `web/adm.py` — +1199 −429. Tarefa interrompida, não entrega
pronta: faltaram `docs/rebranding/IMPLEMENTACAO.md`, as capturas e a passada de
testes que o enunciado pedia.

## Como repetir

```
cd C:\Users\vendas12\enzo\cotafrete-benchmark
python run_claude.py claude-skills-atuais      # um de cada vez
python run_claude.py claude-contexto-enxuto
python summarize.py
```

**Um braço por vez, e ninguém mais usando a conta.** A primeira tentativa
disparou os dois em paralelo enquanto uma terceira sessão trabalhava, e as três
dividiram o mesmo limite: morreram aos 3 minutos.

Brutos em `cotafrete-benchmark/`: `claude-*.jsonl` (a corrida boa),
`claude-*-429.jsonl` e `*-truncado-429.patch` (a tentativa cortada aos 3 min),
`*-meta.json`. O `summarize.py` refaz a tabela e registra o sha256 de cada
arquivo.
