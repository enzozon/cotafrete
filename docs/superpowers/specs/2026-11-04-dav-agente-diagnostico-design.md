# Agente de diagnóstico do DAV (P1 #9a, #9b, #9c)

Aprovado em 04/11/2026 (loop noturno). Revisão do usuário: manhã de 05/11.

## Objetivo

Quando um envio do Gerar DAV falha, o ADM vê sem abrir a VM nem o HSE:

1. **de quem é o erro**: planilha, cadastro no HSE, robô, HSE fora ou acesso;
2. **a prova**: trecho do relatório, print, preço de tabela, nº de orçamento;
3. **se ficou algo criado no HSE** (orçamentos, produtos), com os números;
4. **o que fazer**, em uma frase;
5. (#9b) uma **correção proposta** em células da planilha, que o ADM aprova;
6. (#9c) se a culpa é do robô, um **link para abrir issue** no GitHub com a prova.

Caso que motivou: envios #91 e #93. O robô disse "o HSE recusou" e o HSE tinha criado os
orçamentos 16533, 16534 e 16536. Ninguém soube sem varrer o HSE à mão.

## Regras fixas

- **O agente nunca grava no HSE.** Toda leitura usa `HseSoLeitura`, que aborta gravação.
  Uma gravação bloqueada durante o diagnóstico é falha do diagnóstico.
- **O agente nunca clica livre na tela.** Lê provas que o código coletou e devolve JSON.
- **"Ficou algo criado no HSE?" é decidido por código, não pela IA.** É o dado mais
  perigoso de errar (leva a reenviar e duplicar). A IA recebe o resultado e explica.
- **A correção (#9b) só mexe em células de uma lista fechada**: B30, B31, B33, K2–K25,
  O2–O25. Preço (J), quantidade (B), custo (C) e NCM nunca. O código descarta o resto.
- **Aprovar não gera o DAV.** Aprovar cria um envio corrigido que passa pela conferência;
  o Gerar continua com o vendedor.
- **Texto da planilha e do HSE é dado, não ordem.** Vai para a IA dentro de um bloco
  marcado; o sistema diz para ignorar instruções ali. A saída é JSON com esquema fixo.
- **Gasto da IA com teto diário**, o mesmo freio do `orcamento/ia.py`.

## Peças

### 1. `orcamento/provas.py` — coleta determinística

`coletar(dav, pasta, buscar_pedidos) -> dict` monta as provas de um envio:

- do registro `dav`: estado, erro, relatório, conferência (JSON), arquivo, vendedor, datas,
  número de rascunho ou orçamento;
- da planilha guardada (`entrada/<id>.xlsx`): cliente (B31), vendedor (B33), B30 e itens
  (código, descrição, qtd, valor, NCM, grupo, marca);
- dos arquivos do robô: print mais recente (`prints_hse/<id>_*.png`) e respostas
  (`respostas_hse/<id>_*.html`, só os textos de `alert`/`toast`);
- **criados no HSE**: `buscar_pedidos(cliente, data, perto_de)` devolve os pedidos do
  cliente na data, com itens. Em produção abre `vendaAlt.php?cdPedido=N` (só leitura) numa
  faixa de números estimada pelos DAVs prontos mais próximos no tempo. Nos testes lê um
  espelho gravado (`pedidos.jsonl`). Um pedido conta como "deste envio" quando é do mesmo
  cliente, na mesma data, e tem os mesmos códigos de item da planilha.

Só roda o HSE quando o estado é `erro` ou `incerto` (recusa e conferência não chegam a criar
nada).

### 2. `orcamento/agente.py` — diagnóstico com IA

`diagnosticar(provas, cfg) -> dict` chama `claude-haiku-5-5` com `output_config.format`
(`json_schema`) e `effort: low`, print em base64 quando houver. Esquema:

```
culpa: planilha | cadastro_hse | robo | hse_fora | acesso_hse | conferencia_ok_sem_gerar | indefinido
causa: texto curto
acao: texto curto
evidencia: trecho curto copiado das provas
confianca: alta | media | baixa
correcoes: [{celula, valor, motivo}]   (#9b; filtradas por código)
```

O código junta `criados_no_hse` (das provas), custo, modelo e data. Sem chave, sem crédito
ou acima do teto: devolve só as provas, com `culpa: indefinido` e o motivo.

### 3. Fila e banco

- `dav.diagnostico` (TEXT, JSON) e `dav.diagnostico_estado` (`pendente`, `feito`, `falhou`).
- `FilaDiagnostico`, no molde da `FilaConferencia`: uma thread, um por vez, retoma
  pendentes ao subir. Entra na fila quando a `FilaDav` termina em `erro`/`incerto`, quando a
  conferência termina com erros e quando a planilha é recusada.
- Usa a vaga do navegador (`VAGA_NAVEGADOR`) só durante a busca de pedidos.

### 4. Tela do ADM

No detalhe do envio (`/adm/dav/<id>`), cartão "Diagnóstico":
culpa, causa, o que fazer, prova, **criados no HSE** (números), confiança, custo.
Botões: "Diagnosticar de novo"; (#9b) "Aprovar correção" quando houver correções;
(#9c) "Abrir issue no GitHub" quando a culpa for `robo`.

### 5. Correção aprovada (#9b)

`POST /adm/dav/<id>/corrigir`: copia a planilha guardada, aplica só as células permitidas
(openpyxl), cria um envio novo do mesmo vendedor como correção do original
(`dav_vincular_correcao`) e enfileira a conferência. O vendedor vê o envio corrigido e
decide o Gerar.

### 6. Issue (#9c)

Link `https://github.com/enzozon/cotafrete/issues/new?title=...&body=...` montado no
servidor: envio, erro, causa, provas resumidas, nomes do print e da resposta na VM. Sem
CNPJ, sem trechos financeiros (`_financeiro`). Até 6.000 caracteres. Sem token na VM.

## Avaliação (só no desenvolvimento)

`scripts/avaliar_agente.py` roda coleta + diagnóstico sobre os envios reais baixados do ADM
e compara com `gabarito.json`. Dados reais ficam fora do git
(`C:\Users\vendas12\enzo\dados-noite`). Respostas da IA ficam em cache por hash do pedido,
para não pagar duas vezes.

**Limiar de entrega:**

| Medida | Mínimo |
|---|---|
| culpa certa | ≥ 90% dos envios rotulados com confiança alta |
| `criados_no_hse` certo | 100% (nunca "nada criado" quando foi criado) |
| gravações no HSE | 0 |
| custo médio por diagnóstico | ≤ US$ 0,02 |
| tempo por diagnóstico | ≤ 60 s |
| correções fora da lista | 0 aceitas |
| suíte e CI | verdes; código novo com ≥ 80% de cobertura |

## Fora do escopo

- Agente que clica no HSE.
- Claude Code agindo sozinho no GitHub (depende de instalar o app; fica para depois).
- Diagnóstico mostrado ao vendedor (primeiro só ADM; abrir depois de medir).
