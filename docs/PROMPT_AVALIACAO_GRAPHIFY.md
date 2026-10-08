# Prompt: vale a pena usar o Graphify nas codebases da Ventura?

Cole o bloco abaixo numa sessão nova do Claude Code, aberta em
`C:\Users\vendas12\enzo\cotafrete-dev`. Ele mede e decide, e só instala ou
liga alguma coisa depois que você aprovar.

---

```text
Objetivo: decidir, com números e não com impressão, se o Graphify
(https://github.com/Graphify-Labs/graphify, pacote PyPI "graphifyy") reduz o
contexto e os tokens que gasto trabalhando nas codebases da Ventura
Informática. Se reduzir, propor como adotar. Se não reduzir, dizer o que
reduz.

CONTEXTO (leia nesta ordem, sem abrir código antes):
1. docs/MAPA_DO_SISTEMA.md: sistemas da empresa, partes complexas, dados.
2. docs/SERVIDOR.md: servidor Windows Server 2012 R2, VM, limites e o fluxo
   "Claude prepara, Enzo executa".
3. ../GUIA-CONTEXTO-CODEX-CLAUDE.md, só as seções 5 e 6.

Codebases em escopo:
- cotafrete-dev (Python/FastAPI): Cotafrete, Mercado Eletrônico, cruzar_nf
  (serviço de NF + cadastro de pedidos).
- ../portaismaestro (Node/socket.io + HTML): portal Maestro, onde estou
  integrando NF, cadastro e planilha agora.
- Fora do git: o gerenciador Maestro em
  \\SERVIDOR2\Publico\ALLAN\NUVEM\server2012\novo maestro. SÓ LEITURA. Copie
  os .py para uma pasta do scratchpad se quiser incluí-los no grafo. Nunca
  escreva no servidor.

O que já se sabe (não refaça):
- Desligar plugins corta o contexto fixo da sessão, mas não o custo de tarefa
  longa (memória "experimento_contexto_enxuto"). Em sessão longa quem domina
  é a leitura de cache. A hipótese a testar é: o Graphify faz o Claude LER
  MENOS ARQUIVOS até a primeira edição certa?
- O Graphify extrai código por AST (tree-sitter), sem LLM e sem custo de
  API. Docs, PDFs e imagens passam por um modelo. As saídas são
  graphify-out/GRAPH_REPORT.md, graph.json e graph.html. A integração
  "graphify claude install" põe uma seção no CLAUDE.md e um hook PreToolUse
  em Glob e Grep.
- O servidor não roda o Graphify. Tudo isto acontece só nesta máquina.

REGRAS DURAS:
- Rode o Graphify FORA do repositório: copie o código para o scratchpad e
  rode lá. Nada de graphify-out, hook ou edição de CLAUDE.md no repo nesta
  fase.
- Dados de cliente NUNCA entram no grafo nem em passe semântico: PEDIDOS.json,
  vendas_hse.json, sync_nf.json, *.db, *.xlsx, .env, logs, runs/,
  recon_out/, teste_real/, tests/fixtures/, imagens. Crie um .graphifyignore
  (ou exclua na cópia) e mostre a lista de arquivos que entraram ANTES de
  rodar.
- Fase 1 só com código (AST, sem chave de API). Docs .md só com aprovação
  minha, porque gastam tokens no passe semântico.
- Não instale nada globalmente sem me perguntar. Prefira
  "uv tool install graphifyy" e diga como desinstalar.

FASES (pare ao fim de cada uma e me mostre o resultado):

Fase 0: linha de base (sem Graphify)
- Escolha 3 tarefas REAIS e representativas, pela minha história no git e
  pela memória:
  a) mudar a formatação de um campo de uma transportadora (carriers/);
  b) entender e mudar um evento socket entre portal e cruzar_nf
     (server.js ↔ maestro.py/servico.py);
  c) diagnosticar "linha da planilha não entrou no portal"
     (cadastro_pedidos.py + estado).
- Para cada uma, rode um subagente Explore SEM Graphify que só LOCALIZE os
  arquivos e as funções a mudar, sem editar. Anote o resultado e a
  contagem de tokens/ferramentas que o subagente reportar.

Fase 1: piloto do Graphify só com código, no scratchpad
- Instale, gere o grafo de cotafrete-dev + portaismaestro (+ gerenciador, se
  copiado) e anote tempo, tamanho do GRAPH_REPORT.md em tokens e as god
  nodes.
- Confira a qualidade: o grafo liga server.js ↔ cruzar_nf pelos NOMES de
  evento socket.io? (A suspeita é que não, porque AST liga import e chamada,
  não string.) E web/app.py ↔ carriers/*?
- Repita as 3 tarefas da Fase 0 com um subagente que lê PRIMEIRO o
  GRAPH_REPORT.md e usa "graphify query/path/explain". Compare: arquivos
  lidos, tokens, acertou ou não.

Fase 2: comparar com a alternativa barata
- Repita as 3 tarefas com um subagente que lê PRIMEIRO só o
  docs/MAPA_DO_SISTEMA.md (mapa escrito à mão, sem dependência).
- Tabela final: sem nada × Graphify × mapa manual × Graphify + mapa.

Fase 3: decisão
- Adote o Graphify só se, nas 3 tarefas, ele cortar ≥ 20% dos tokens até
  localizar o código certo em relação ao mapa manual, sem errar mais.
- Se adotar: proponha o modo (nudge padrão, nunca --strict de início), onde
  fica o graphify-out (.gitignore), como atualizar (graphify hook install ou
  "graphify update ." depois do git pull) e o custo fixo que a seção no
  CLAUDE.md acrescenta a toda sessão.
- Se não adotar: liste o que reduziria os tokens de verdade, com a economia
  estimada de cada um.

ENTREGA: um relatório curto em português com a tabela de números, a decisão,
os riscos e os próximos passos. Linguagem simples, porque vou mostrar para a
equipe.
```
