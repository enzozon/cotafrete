# Graphify: resultado do piloto (08/10/2026)

**Decisão: não adotar agora.** Nas 3 tarefas o Graphify não economizou
tokens. Ele gastou 8% a mais que não usar nada e foi 44% mais lento. Os três
jeitos acharam o lugar certo.

## Como foi medido

- Grafo só de código (AST, sem IA, custo zero): cotafrete + portaismaestro +
  cópia do gerenciador. São 129 arquivos, 2.723 nós e 6.431 ligações, gerados
  em 15 s. Ficou fora do repositório e sem dados de cliente.
- 3 tarefas reais × 3 condições, cada uma com um subagente Explore que só
  localiza:
  - **nada**: grep e leitura;
  - **graphify**: lê o `GRAPH_REPORT.md` e usa `graphify query/explain/path`;
  - **mapa**: lê o `docs/MAPA_DO_SISTEMA.md`.

| tarefa | nada | graphify | mapa |
|---|---|---|---|
| Jadlog: peso com 3 casas | 44,0k · 8 ferr. · 82 s ✔ | 37,9k · 4 · 104 s ✔ | 45,8k · 10 · 84 s ✔ |
| renomear evento `comando_sync_nf_estado` | 37,5k · 4 · 73 s ✔ | 41,8k · 8 · 125 s ✔ | 38,7k · 6 · 79 s ✔ |
| linha da planilha não entrou | 37,6k · 7 · 81 s ✔ | 49,4k · 5 · 109 s ✔ | 41,7k · 4 · 72 s ✔ |
| **total** | **119,1k · 235 s** | **129,1k · 338 s** | **126,2k · 235 s** |

Cerca de 30k de cada coluna é o custo fixo de abrir um subagente. A diferença
real entre os jeitos é pequena e está dentro do ruído de uma rodada só.

## O que se viu

- **O grafo não liga JS e Python pelos eventos socket.io.** `graphify path
  server.js servico.py` não acha caminho. O agente da tarefa do evento
  precisou de grep mesmo assim. Essa é justamente a ligação que mais importa
  no Maestro.
- As buscas vêm com ruído: módulos da biblioteca padrão (`json`, `os`, `re`)
  aparecem entre os nós. O `GRAPH_REPORT.md` tem uns 6k tokens e seria lido em
  toda sessão.
- O código já é bem dividido e os nomes são descritivos. Um grep acha o
  lugar em 4 a 8 passos, então sobra pouco para um grafo cortar.
- **O mapa errou num ponto**: dizia que toda formatação fica no `mapping.py`.
  A Jadlog de produção formata no `painel.py`. Os agentes perceberam e o mapa
  foi corrigido. A lição é manter o mapa curto e conferido, e não confiar nele
  às cegas.

## Quando reavaliar

- Se o código crescer muito (várias vezes o tamanho atual) ou entrar um
  repositório sem estrutura clara.
- Se o Graphify passar a ligar eventos/strings entre linguagens.
- Para refazer: siga o `PROMPT_AVALIACAO_GRAPHIFY.md`. O grafo do piloto
  ficou no scratchpad da sessão. Para desinstalar: `uv tool uninstall graphifyy`.
