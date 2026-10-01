# Sincronização de NF no Maestro — serviço separado (caminho B)

O `gerenciador.py` do Maestro **não muda**. A sincronização roda num processo
à parte, o **serviço de NF** (`cruzar_nf/servico.py`), ao lado dele no servidor.

```
portal (Render)                         servidor da empresa
 planilha_vale.html ─► server.js ◄──── gerenciador.py   (sem mudança)
   ☰ Sincronizar NFs     │  ▲
                         ▼  │ sou_o_sync_nf + SYNC_NF_TOKEN
                     servico.py ── robô HSE (Selenium) ── vendas_hse.json
                         │
                         └─► PEDIDOS.json (gravação concorrente segura)
                                 └─► planilha_manager recarrega sozinho
```

## Por que funciona sem mexer no gerenciador

O `planilha_manager.py` do servidor (versão de 01/10/2026) **recarrega o
PEDIDOS.json no `iniciar()` quando a data de modificação muda**, e todo ponto
do gerenciador que grava chama `iniciar()` antes. O serviço grava com
`ArquivoPedidosConcorrente` (`arquivo_pedidos.py`):

1. grava só se o arquivo não mudou desde a leitura (data + tamanho);
2. grava num temporário e troca de uma vez (`os.replace`);
3. espera e relê: se o gerenciador salvou por cima, grava de novo — a
   sincronização só preenche NF vazia, refazer não estraga nada;
4. JSON pego no meio de uma gravação do gerenciador: lê de novo.

Risco que sobra: o gerenciador gravar exatamente entre a última conferência e
a troca do arquivo (microssegundos). Em 50 rodadas do teste de concorrência
(robô adicionando 30 pedidos durante a sincronização) nenhum pedido se perdeu.

**Se o `planilha_manager.py` perder a recarga pela data de modificação**, o
caminho B deixa de ser seguro: o gerenciador sobrescreveria as NFs com a
memória dele. Nesse caso volte para o caminho A (`maestro.registrar` dentro do
gerenciador, 2 linhas) ou devolva a recarga ao `planilha_manager`.

## Peças

| arquivo | papel |
|---|---|
| `servico.py` | conecta no portal, identifica-se com token, comandos do portal, rodada diária 07:30, reconexão |
| `ServicoNF.bat` | sobe o serviço e reinicia se cair |
| `arquivo_pedidos.py` | gravação concorrente segura do PEDIDOS.json |
| `maestro.py` | `aplicar_nfs` e `registrar(sio)` (comandos `comando_sync_nf_estado` / `comando_sync_nf`) |
| `sincronizar.py` | rodada: exporta → base → cruza → grava → `sync_nf.json` |
| `hse_robo.py` | Selenium (Chrome 109): login, Venda (pedido), filtros, Excel |
| `vendas_excel.py` / `base_vendas.py` | Excel do HSE (HTML .xls ou .xlsx) e base acumulada |

## Portal (`allan-max/portaismaestro`)

- `server.js`: `sou_o_sync_nf` + `SYNC_NF_TOKEN` (comparação em tempo
  constante; errado ou ausente = recusado e desconectado); `solicitar_sync_nf*`
  vão para o serviço (só de sockets logados); progresso/resultado só do
  serviço; `planilha_atualizada` aceito do robô ou do serviço.
- `planilha_vale.html`: ☰ → **Sincronizar NFs (HSE)** e coluna **NF**.

## Configuração

Render: `SYNC_NF_TOKEN=<senha longa>`.
`.env` do servidor (mesma pasta do gerenciador): `SYNC_NF_TOKEN` (igual),
`HSE_USUARIO`, `HSE_SENHA`, `HSE_HEADLESS=1`; opcionais `SYNC_NF_DADOS`,
`SYNC_NF_BACKUPS`, `SYNC_NF_HORARIO`, `SYNC_NF_LOG`, `SYNC_NF_EXCEL`
(sincronizar com um Excel baixado à mão, sem o robô).

## Testes

- `pytest tests/test_cruzar_nf.py tests/test_vendas_excel.py tests/test_sincronizar.py tests/test_arquivo_pedidos.py tests/test_servico.py ...`
- Roteamento contra o `server.js` real (15 cenários: token, login, impostor,
  serviço caído) e ponta a ponta com o `servico.py` real e o Excel de
  01/01/2025–29/09/2026 sobre uma cópia do PEDIDOS.json: 481 NFs gravadas,
  backup, estado, segunda rodada sem regravar.
