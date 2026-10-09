# Mapa do sistema: o que é difícil e onde mexer

Leia este arquivo **antes** de abrir código. Ele existe para que uma mudança
comece no arquivo certo, sem varrer o repositório. Cada seção diz o que quebra
fácil, por que quebra e o que conferir depois de mexer.

Atualize este mapa no mesmo PR quando mudar uma das partes descritas aqui.
Mapa desatualizado custa mais que mapa nenhum.

---

## 1. A empresa e os sistemas

A Ventura Informática vende para grandes compradores, como Vale, Petrobras e
Samarco, por portais de compra: Mercado Eletrônico (ME), Coupa, Ariba, Findes
e o portal da Vale. Quase tudo que se automatiza aqui serve a três
trabalhos: **cotar o frete**, **responder cotações dos portais** e
**acompanhar pedido → nota fiscal**.

| sistema | repositório / local | o que faz | roda onde |
|---|---|---|---|
| **Cotafrete** | este repo, `web/` + `core/` + `carriers/` | um formulário e cotação em várias transportadoras | VM Windows 10 no servidor, `cotafrete.ventura.inf.br` |
| **Mercado Eletrônico** | este repo, `mercado_eletronico/` + `web/me_ui.py` | lê cotações do ME, calcula impostos e prazos, preenche rascunho | VM, junto do Cotafrete |
| **Serviço de NF** | este repo, `cruzar_nf/` | busca NFs no ERP HSE e preenche nos pedidos do Maestro | SERVIDOR2 (Server 2012 R2) |
| **Cadastro de pedidos** | `cruzar_nf/cadastro_pedidos.py` | leva a planilha dos estagiários para o PEDIDOS.json | SERVIDOR2, a cada 10 min |
| **Portal Maestro** | `allan-max/portaismaestro` (`server.js` + `public/*.html`) | painel web com socket.io, onde ficam os robôs dos portais, a fila, os pedidos e a planilha Vale | pm2 "Site-Maestro" + Cloudflare Tunnel, `maestro.ventura.inf.br` |
| **Gerenciador Maestro** | só no servidor: `\\SERVIDOR2\Publico\ALLAN\NUVEM\server2012\novo maestro` (`gerenciador.py`, `planilha_manager.py`, bots) | robôs dos portais e dono do PEDIDOS.json | SERVIDOR2 |

**O gerenciador não está no git.** Outras pessoas o alteram direto no
servidor. Antes de mexer em qualquer integração com ele, compare os arquivos
(data, tamanho e hash) com a última versão vista.

---

## 2. Cotafrete: as quatro armadilhas

### 2.1 O mesmo número em formatos diferentes

O usuário digita centímetros e quilos. Cada site quer um formato, e **errar
não dá erro**: o site cota a carga errada com um preço que parece certo.
A Camilo (SSW) recebe as medidas em **metros**; a Della Volpe exige uma casa
decimal. A tabela completa está no README, seção "A armadilha central".

- **Onde:** em `carriers/<slug>/mapping.py`, que é puro e testado. Nunca no
  formulário nem em `web/`. **Exceção: Jadlog.** Produção usa o painel
  (`carriers/jadlog/painel.py`, `JadlogPainelAdapter`), que formata o peso no
  próprio adapter. O `jadlog/mapping.py` serve a API com token, e o
  `simulador.py` está aposentado. Para saber quem cota de verdade, veja
  `FABRICAS` em `web/app.py`.
- **Depois de mexer:** `pytest tests -k <slug>` e um dry-run com print
  (`teste_real/<slug>/<data>/preenchido.png`).

### 2.2 Seletores

Seletor deduzido de print já quebrou duas vezes sem aviso. Use rótulo ou
placeholder. Use o `name=` medido no recon (`recon/recon_<slug>.py`) só como
último recurso. Nunca use posição.

### 2.3 Preço atrás de um aviso

O site pode mostrar um preço calculado **atrás** de um popup de recusa
("cidade não atendida", "CNPJ não cadastrado"). Esse preço é fantasma. Todo
adapter confere o popup antes de aceitar o preço.

### 2.4 Concorrência e tempo

- `core/retentativa.py`: `NAVEGADORES_SIMULTANEOS = 2` e
  `ESPERA_MAXIMA_S = 300`. Esses números foram medidos na VM com 4 vCPU (veja
  `docs/SERVIDOR.md`). Só mude depois que um vendedor vir o aviso "não
  responderam em 5 minutos".
- Generoso e Della Volpe só passam com **janela visível** (Vercel e
  reCAPTCHA). Headless "funciona" e não envia nada.

### IA na tela do vendedor

Toda IA nova segue a regra: a IA sugere, o código confere contra os dados
reais. `core/explicar_erro.py` (frase do erro, sem número),
`core/resposta_cliente.py` (cada preço igual ao do banco) e
`core/busca_historico.py` (só filtros da lista fechada). Nos testes, o que
chama a IA sozinho fica desligado em `tests/conftest.py`.

### Para ligar uma transportadora nova

Siga o roteiro: recon → `mapping.py` → `adapter.py` → fixture tirada do HTML
real → dry-run → envio real com cliente real → ligação em `web/app.py`.
`web/app.py` é a ligação e não a lógica. Ele tem perto de 3.000 linhas.
Procure nele por `AUTOMATICAS`, `FABRICAS`, `NOMES` e `NOTAS`. As listas vêm
de `web/transportadoras.py`. Os testes de consistência travam fábrica e lista
juntas. O `monitorar.py` se atualiza sozinho.

---

## 3. Mercado Eletrônico: nunca salvar sem querer

- **Travas:** `mercado_eletronico/trava.py` intercepta POST, postback e anexo
  e bloqueia o que não for um salvamento pedido. Nada que escreve no ME pode
  passar por fora dela.
- **Rascunho de outra pessoa é intocável.** Em 28/09/2026 um teste apagou o
  rascunho de um colega, e não havia como recuperar. Toda escrita, de salvar
  ou de limpar, confere antes se a cotação tem rascunho alheio. Não encadeie
  duas escritas no mesmo comando.
- A parte pura fica em `regras.py`, `feriados.py`, `mapa.py`, `painel.py`,
  `lista.py` e `pagina.py`, e tem testes. A parte de browser fica em
  `robo.py` e `ponte.py` e é fina de propósito.
- `revisao.py` usa IA (`core/ia.py`) só para gerar **alertas** e
  **exigências do comprador** (cada uma com o trecho conferido no texto) e
  nunca escreve no formulário. `core/resumo_erros.py` só aceita um número como fato
  se ele aparece fora da data.
- Guia completo: `docs/MERCADO_ELETRONICO.md`.

---

## 4. NF e pedidos: escritores concorrentes no JSON e no Excel

O ponto mais frágil da empresa é o **PEDIDOS.json**, porque vários processos
escrevem nele:

```
gerenciador.py / planilha_manager.py   (dono; fora do git)
cruzar_nf/servico.py → sincronizar.py  (preenche NF vazia)
cruzar_nf/cadastro_pedidos.py          (acrescenta pedido novo da planilha)
cruzar_nf/sync_planilha_portal.py     (sincronização diária de campos e novos itens)
```

**Por que não se corrompe:** `cruzar_nf/arquivo_pedidos.py` grava só se a data
e o tamanho não mudaram desde a leitura. Ele escreve num temporário e troca o
arquivo com `os.replace`, depois relê. Se o gerenciador gravou por cima, ele
grava de novo. Isso **depende** de o `planilha_manager.py` recarregar o JSON
quando a data de modificação muda. Se alguém tirar essa recarga do servidor,
o gerenciador volta a sobrescrever as NFs. Confira essa recarga antes de
qualquer mudança no fluxo, pelo hash do arquivo no servidor.

### Peças

| arquivo | papel | o que quebra |
|---|---|---|
| `servico.py` | conecta no portal com `sou_o_sync_nf` + `SYNC_NF_TOKEN` e roda a rodada diária | **uma instância só**, pela trava `servico_nf.instancia`. Desde a #49 a segunda fica de reserva em vez de sair |
| `ServicoNF.bat` | sobe e reinicia o serviço | roda pela tarefa "Maestro NF Servico" (ONSTART, Administrator). `schtasks /End` **não** mata o python |
| `ReiniciarServicoNF.bat` | encerra os que sobraram e sobe de novo | não reinicia enquanto `nf_planilha` grava (trava própria) |
| `hse_robo.py` | Selenium no ERP HSE, com login em duas etapas e um Excel por mês | usa Chrome 109, o último que roda no Server 2012 R2 |
| `sincronizar.py` | exporta, monta a base, cruza, grava e escreve o `sync_nf.json` | base acumulada desde 01/01/2025 em `vendas_hse.json` |
| `cruzar.py` | casa pedido com NF | regra de casamento documentada em `cruzar_nf/README.md` |
| `cadastro_pedidos.py` | planilha → PEDIDOS.json | chave = PEDIDO + RFQ + começo do PRODUTO (30 caracteres). **O que já foi visto não volta**, mesmo se apagado no portal. Linha incompleta fica esperando |
| `nf_planilha.py` | escreve a NF na coluna "NF (MAESTRO)" da planilha | edita o XML do .xlsx de forma cirúrgica. **Planilha aberta = não grava** |
| `planilha_portal.py` | confere planilha × portal todo dia | linhas canceladas ficam em `conferencia_ignorar.json` |
| `sync_planilha_portal.py` | merge de três pontas, prévia padrão; tarefa própria às 12:30 | primeira gravação só inicializa a foto; conflitos, exclusões e histórico antigo não são sobrescritos. PEDIDO/RFQ/PRODUTO exigem revisão |
| `planilha_edicao.py` | atualiza células e acrescenta linhas no XML do Excel | compartilha `nf_planilha.trava` com o gravador de NF; fórmulas e estruturas não suportadas bloqueiam a operação |

Cadastro, NF e sincronização bidirecional compartilham `sync_nf.trava`.
A sincronização adquire depois `nf_planilha.trava`, sempre nessa ordem; não
segura travas entre tentativas do Agendador. O gerenciador externo não usa
essas travas: continua necessária a verificação otimista e a recarga dele.
Os temporários do JSON têm nomes exclusivos. Uma edição concorrente de um
campo não é sobrescrita por uma repetição cega.

A foto (`sync_planilha_portal.json`) guarda a base comum por campo, as duas
pontas observadas, chaves conhecidas, exclusões e operações pendentes antes
da escrita. Não apagar nem reinicializar esse arquivo para resolver erro.
O relatório próprio é entregue pelo evento de estado existente; o portal
precisa também do PR do painel. NF continua com os escritores antigos.
Datas americanas do JSON legado são identificadas por comparação com o
Excel e o formato fica guardado por item; dados inválidos são pendências.

### Configuração (o `.env` fica na pasta `sync_nf`, não no repo)

`SYNC_NF_DADOS=\\SERVIDOR2\Publico\ALLAN\database\sync_nf` guarda o
`vendas_hse.json`, o `sync_nf.json`, o `cadastro_pedidos.json` e o estado da
conferência. **Nunca aponte para outra pasta**: ela já foi trocada por engano
uma vez, ao suspeitarem que causava um erro.

### Sintomas já vistos

| sintoma | causa real |
|---|---|
| "cadastro parou" | planilha aberta no Excel sem salvar. O `~$` pode ser velho, não confie nele |
| linha apagada e redigitada não entra | a deduplicação do `cadastro_pedidos.json` já a marcou como vista |
| serviço "rodando" em loop | processo órfão segurando a trava, e o código de saída 3 se perdia na tarefa |
| "Consultando o robô..." infinito no portal | serviço desconectado ou recusado pelo token |

---

## 5. Portal Maestro: contrato de eventos

O `server.js` só repassa eventos socket.io entre o navegador (`sou_frontend`),
os robôs (`sou_o_robo`) e o serviço de NF (`sou_o_sync_nf`). **O contrato é o
nome do evento**, uma string que liga JS e Python sem import nenhum. Renomear
de um lado quebra o outro sem aviso.

Eventos da integração de NF e cadastro:

- portal → serviço: `solicitar_sync_nf*`, aceitos só de socket logado;
- serviço ↔ `maestro.py`: `comando_sync_nf_estado` e `comando_sync_nf`;
- serviço/robô → portal: progresso, resultado e `planilha_atualizada`;
- token comparado em tempo constante. Token errado ou ausente faz o portal
  recusar e desconectar.

Para mudar um evento: `grep -n "<nome>"` em `server.js`, `public/*.html`,
`cruzar_nf/` **e** no `gerenciador.py` do servidor.

O `server.js` **não lê `.env`**: o dotenv foi tirado em 02/10. O token vem de
`setx /M`, depois `pm2 restart --update-env` e `pm2 save`.

---

## 6. Onde ficam os dados (não leia inteiro, filtre)

São arquivos grandes de dados e não de código. Abrir inteiro gasta contexto à
toa. Use `python -c`, `jq` ou `grep` para extrair o pedido ou a linha que
interessa.

| arquivo | o que é |
|---|---|
| `cotafrete.db` | SQLite em WAL. Backup só por `core/backup.py`, nunca por cópia crua |
| `PEDIDOS.json` | pedidos do Maestro (servidor, `Banco-de-dados\`) |
| `vendas_hse.json` | base de vendas do HSE desde 2025 |
| `logs\servico_nf.log`, `logs\diag_nf.txt` | leia só o final: `tail -n 200` ou `Get-Content -Tail 200` |
| `tests/fixtures/*.html` | HTML real dos sites. Não abra para entender código |
| `runs/`, `recon_out/`, `teste_real/` | saídas de execução. Ignore |
