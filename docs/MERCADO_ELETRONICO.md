# Mercado Eletrônico (ME): resposta semiautomática de cotações

Documento de passagem entre sessões. PR: https://github.com/enzozon/cotafrete/pull/32 Contém o pedido original, as decisões
já tomadas, o que está pronto e o que falta. **Leia inteiro antes de mexer.**

## Objetivo
Nova página no CotaFrete que lista **ao vivo** as cotações pendentes do ME
(https://www.me.com.br/supplier/inbox/pendencies/4?CreateDateStart=2026-06-25),
separadas por conta (VENTURA / UNIÃO). O usuário preenche só o que muda; o
sistema calcula impostos e datas, valida (código + IA) e um robô **preenche e
SALVA** a resposta no ME. **O envio final é sempre humano.**

Cotação de referência para o recon (conta VENTURA):
https://www.me.com.br/RespostaCotaItem.asp?Cotacao=23039029&SuperCleanPage=

## ⛔ Regra crítica: o robô NUNCA envia
- Só preenche e SALVA (rascunho). Nunca clica em Enviar/Responder/Finalizar
  nem em nada que submeta a proposta ao comprador. Vale para recon e testes.
- No recon, provar qual botão só salva e qual envia.
- Trava em 3 camadas: lista de seletores/textos proibidos; guarda que
  intercepta todo clique do robô; bloqueio da URL de envio via `page.route`.
  Teste automatizado para cada camada.
- Se NÃO existir "salvar sem enviar": **parar e avisar o usuário.**

## Credenciais e rede
- Variáveis de ambiente: `ME_VENTURA_LOGIN`, `ME_VENTURA_SENHA`,
  `ME_UNIAO_LOGIN`, `ME_UNIAO_SENHA` (no ambiente cloud e no `.env` local).
  Nunca em log, commit, print ou frontend.
- O ambiente cloud precisa liberar `*.me.com.br` em Network access.

## Decisões do usuário (23/09/2026)
| Tema | Decisão |
|---|---|
| Prazo de entrega | dias **corridos** (como o ME conta); se cair em fim de semana/feriado → próximo dia útil |
| Feriados | nacionais + móveis (Carnaval, Sexta Santa, Corpus Christi); **sem** municipais |
| ICMS | origem 0 ou 2: **17% dentro do ES, 12% fora**. A empresa só usa origens 0 e 2; outras bloqueiam |
| Impostos VENTURA | todos menos IPI: PIS 0,65 sim; COFINS 3,00 sim; ICMS sim |
| Impostos UNIÃO | só ICMS: PIS 0 Isento; COFINS 0 Isento |
| IPI | sempre 0 / Isento |
| Fixos da cotação | Tipo frete FOB; Frete "Frete FOB"; Condição 60DDL; Contato Eliziane Amorim; Telefone 2732991664; Moeda Real - Brasil; IE 082582190 - ES. **Iguais nas duas contas** |
| Fixos do item | Unidade UNIDADE; ST NÃO; Alíquota ST 0,00; Valor ST 0,00; Base ICMS 100% sem IPI |
| Validade da proposta | hoje + N dias (usuário informa N) |
| Preço | sempre do usuário |
| Item sem preço | permitido se tiver observação explicando |
| Onde roda | servidor da empresa (VM com Chromium, como as transportadoras) |
| IA de revisão | só alertas (info/atenção/crítico), nunca altera valor; falhou → segue com "revisão IA indisponível" |

**Em aberto:** origem 2 para fora do ES costuma ser 4% (Res. Senado
13/2012), mas o usuário pediu 12%. Implementado 12%; usuário vai confirmar com
a contabilidade. Mudança de uma linha em `aliquota_icms`.

## Campos do usuário (por item)
Preço, Cód. NCM, Prazo (dias), Fabricante/Marca, Observações, Origem (0/2).
Por cotação: validade (dias).

## Achados dos prints (antes do recon)
- UF de destino: no texto "Campos Adicionais" do item, ex.
  `End. entrega: Rodovia do Sol, S/N - Ponta Ubu - Anchieta - ES - 29230-000`.
- O mesmo bloco traz `Origem do Material: 0` e `Data de Remessa: 02.11.2026`
  → alertas de origem divergente e entrega depois da remessa.
- O ME calculou 23/09/2026 + 45 dias = 09/11/2026 (07/11 é sábado).
- NCM, PIS, ST e telefone aparecem pré-preenchidos (fundo azul): sobrescrever
  e conferir depois de salvar.

## Arquitetura escolhida
- **Playwright** (mesmo padrão dos adapters em `carriers/`, navegador de
  `carriers/base.py`), sessão separada por conta.
- Execução em **thread no processo** + status no SQLite (`core/banco.py`),
  como as cotações de frete.
- Listagem **sob demanda + atualização a cada 5–10 min**, com cache. A mesma
  varredura detecta "Enviada" (sumiu das pendências; confirmar no recon).
- Status: Pendente → Salva no ME → Enviada (automático + botão manual) / Erro
  (motivo + print). Destaque para "Salva no ME" parada perto do prazo.
  Histórico: quem preencheu, quando salvou, alertas da IA, prints, envio.
  Filtros por conta e status.
- Pós-salvar: reler a página e comparar campo a campo (`regras.conferir`).
- Modo **dry-run** (preenche sem salvar).
- IA: uma chamada por cotação, API da Anthropic, `claude-opus-5`
  (~US$ 0,08/cotação; Sonnet 5 ~US$ 0,03 se quiser economizar).
- UX: lembrar NCM/marca/origem por código de material; "aplicar a todos";
  copiar do item anterior; prévia em tabela com alertas na linha; contagem
  regressiva até a data limite.

## Recon (23/09/2026) — `recon/recon_me.py`, nas duas contas, só leitura
Nada foi salvo nem enviado. O script só clica no "Entrar" do login; depois
disso a trava de rede aborta todo POST/PUT/PATCH/DELETE para `*.me.com.br` e
`*.mercadoe.com` (única exceção: a busca da listagem, que é leitura) e o
`add_init_script` anula `form.submit`, `__doPostBack` e `window.open`.
Abrir a página de resposta gerou **0** requisições de escrita.
Evidência (fora do Git, tem token e dado do comprador): `recon_out/me/<conta>/`.

    python recon/recon_me.py login --conta ventura      # guarda a sessão
    python recon/recon_me.py pendencias --conta ventura
    python recon/recon_me.py cotacao 23039029 --conta ventura

### Salvar × Confirmar: provado no código da página
| Botão | JS | Tooltip do ME | O que faz |
|---|---|---|---|
| **Salvar** | `Envia(9)` | "Salvar informações para enviar mais tarde" | POST do form `RespCota` com `Acao=9` |
| **Confirmar** | `Envia(1)` | "Finalizar a resposta da cotação e **enviar ao comprador**" | **mesmo** form, **mesma** URL, `Acao=1` |
| Recusar (modal) | `Envia(2)` | "Recusar todos os itens da cotação" | POST do form `RespRecusa` para `RespCotaGrava.asp` |
| Páginas 1/2, › | `Envia(11)`, `Envia(12)`, `Envia(4)` | — | POST do `RespCota` com `Acao` 11/12/4 (+ `GravaRespTemp=S`) |
| Desconto | `Desconto()` | — | POST com `Acao=5` |

**Existe "salvar sem enviar"**, mas Salvar e Confirmar só diferem no campo
oculto `Acao` do mesmo POST (`RespostaCotaItem.asp?Cotacao=N&FID=`). Por isso
a trava do robô não pode olhar só a URL: ela precisa **ler o corpo do POST e
só deixar passar `Acao=9`** (e a paginação, se usada). `Acao=1`, `Acao=2`,
`Acao=5`, `RespCotaGrava.asp` e qualquer outro valor → abortar.
Detalhes do `Envia`:
- Salvar exige **pelo menos um item marcado** (`chkItem_N`), senão `alert`.
- Data de entrega do item tem que ser **depois** da data limite da cotação.
- Validade da proposta ≥ hoje.

### Página de resposta: `RespostaCotaItem.asp?Cotacao=N&SuperCleanPage=`
Um documento só, sem iframe útil (os frames são gif/about:blank). Formulário
ASP clássico `RespCota`. `FornShowCotacao.asp?Cot=N` (o link da listagem)
redireciona para ela enquanto a cotação está aberta.

**Cabeçalho** (`name` → decisão):
`IcoTerms` (select, `FOB`) · `CondicaoPagamento` (`F060` = 60DDL) ·
`NomeContato` · `NumFoneCota` · `ValidadePropostaAux` (dd/mm/aaaa, datepicker;
o JS copia para `ValidadeProposta`) · `MoedaCot` (`BRL` = Real - Brasil) ·
`InscricaoEstadual` · `atrib_CidadeEstado_1_1_0_0` (textarea "* Frete") ·
`ObsForn` (Obs). Ocultos úteis: `DataLimite` (`23/09/2026 21:00`), `MaxItem`
(itens **desta página**), `DataAtual`, `CotacaoID`, `FornecedorID`, `ObsComp`
(texto do comprador).

**Item N** (N = 1..MaxItem na página):
| Campo | `name` | Observação |
|---|---|---|
| marcar item | `chkItem_N` | obrigatório p/ o Salvar |
| Preço unitário | `PrecoN` | onblur recalcula; máx. 12 |
| Unidade | `UnidadeRespN` | 369 opções; "UNIDADE" = `UN`, "Unidades" = `UND` |
| Tipo imposto | `TipoImpostoN` | `0` vazio, `1` IPI, `2` ISS |
| IPI % / incluso | `IPIN` / `IPIInclusoN` | `I` Isento, `S` sim, `N` não |
| ICMS % / incluso | `ICMSN` / `ICMSInclusoN` | `I` Isento, `S` sim |
| Cód. NCM | `NCMN` | máx. 16 |
| Prazo (dias) | `PrazoN` | inteiro |
| Data p/ entrega | `DataEntregaItemAuxN` | dd/mm/aaaa, o ME **não** preenche sozinho |
| Fabricante/Marca | `FabricanteN` (id `fabricanteN`) | **máx. 20** |
| Obs | `ObservacaoN` | **máx. 100** |
| Origem | `OrigMatN` | `992`=0, `993`=1, `994`=2 … `1000`=8 |
| ST / alíquota / valor | `SubstituicaoTributariaN` (`N`=NÃO) / `AliquotaSubstituicaoTributariaN` / `ValorSubstituicaoTributariaN` | |
| PIS / incluso | `PISN` / `PISInclusoN` | `I` isento, `S` sim |
| COFINS / incluso | `COFINSN` / `COFINSInclusoN` | `I` isento, `S` sim |
| Base ICMS % / c/ s/ IPI | `BaseCalculoN` (já vem 100,00) / `BaseCalculoImpostoN` (`S` = sem IPI) | |
| recusar item | `btnNaoResponder_N` | **nunca tocar** |

Texto do item (descrição, "Quantidade: 2,00  Unidade: UND", Observação do
comprador, "Campos Adicionais") está no próprio HTML; anexos aparecem como
contagens `hidden*QtdeAnexos` e links `exibirPopupAnexos(...)`.

- **Paginação:** 10 itens por página. A 23039029 tem 18 itens (2 páginas; total lido do JS de "recusar todos"). A
  página 2 **não abre por GET** (erro "Ocorreu uma falha no sistema"); só por
  `Envia(12)`, que faz POST do formulário com `GravaRespTemp=S`, ou seja,
  grava a página atual como rascunho. Não testado (é escrita).
- O ICMS do ME chama `ConsistirImpostoICMS(..., 'ES', 'MG', ...)` (acha que o
  comprador é MG), mas a função **não bloqueia** (`return true`). A regra
  continua sendo a nossa, pela UF do "End. entrega".
- Nesta cotação NCM/PIS/telefone vieram **vazios**; 60DDL e o nome do
  contato vieram preenchidos. Não dá para contar com pré-preenchimento.

### Listagem e como saber que foi enviada
A tela `/supplier/inbox/pendencies/4` (Oportunidades a Responder) e
`/supplier/inbox/transactions/7` (todas as cotações) pedem os dados por
`POST https://api.web.mercadoe.com/supplier/transactions/v1/transactions/search`
(com o cookie da sessão), corpo:

    {"aggregations":[],"filter":{"term":"","criteria":[
      {"field":{"name":"CreateDateStart","type":"string"},"operator":"equal","value":"2026-06-25"},
      {"field":{"name":"Pendencias","type":"numeric"},"operator":"equal","value":"4"}]},
     "paging":{"page":1,"size":10},"sort":[]}

Cada linha traz `processId` (nº da cotação), `clientCode`/`summary` (título),
`company`, `customerName` (comprador), `dueDate` (UTC: `2026-09-29T00:00Z` =
28/09 21:00 em Brasília), `statusName` (Em andamento / Vencida),
`answerStatus` (**Não Respondida** / **Totalmente Respondida**),
`viewedDate`, `firstDateAnswered`, `lastDateAnswered`, `hits` (total).
→ **Enviada = `answerStatus` ≠ "Não Respondida" + `firstDateAnswered`**, e
ela some de Pendências. **Falta provar** que um *Salvar* não muda
`answerStatus` — só dá para ver salvando de verdade (primeiro teste do robô,
com autorização).

### Estado das contas em 23/09/2026
- VENTURA (fornecedor 4637695): 23039029 (Samarco, limite **hoje 21:00**,
  18 itens, entrega ES) e 23049227 (limite 25/09).
- UNIÃO: 23052403 (Samarco, limite 28/09 21:00, 3 itens, entrega Mariana-**MG**).
- **IE da UNIÃO é outra:** o select só oferece `083049428 - ES` (VENTURA:
  `082582190 - ES`). Nome do contato pré-preenchido na UNIÃO: "ELIZIANE
  AMORIM ROSA BARROS".

### Ambiente (nuvem)
O Chromium não confiava no proxy da nuvem (`ERR_CERT_AUTHORITY_INVALID`): o
NSS de `~/.pki/nssdb` estava vazio. Resolvido importando a CA do proxy:
`certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n ccr-agent-proxy -i /root/.ccr/agent-proxy-ca.crt`
(pacote `libnss3-tools`) e `channel="chromium"`. Contexto com
`timezone_id="America/Sao_Paulo"`, senão o ME abre o modal de fuso horário.

## Pronto
- `mercado_eletronico/regras.py` + `feriados.py`: impostos, fixos, datas,
  leitura dos Campos Adicionais, validação (erros bloqueiam / avisos),
  conferência pós-salvamento.
- `tests/test_me_regras.py`: 68 testes.
- `recon/recon_me.py` + `tests/test_me_recon_trava.py` (16 testes da trava).
- Linha de base da suíte na nuvem: 24 falhas **de ambiente** (cryptography do
  sistema quebrado; testes que pedem janela visível). Na nuvem, instalar
  `playwright==1.56.0` para casar com o Chromium de `/opt/pw-browsers`.

## Próximos passos
1. ~~Recon~~ feito (acima). **Aguardando o usuário** sobre as perguntas do
   recon antes de construir o robô.
2. Robô `mercado_eletronico/robo.py` com trava de envio e dry-run + testes
   contra HTML salvo do recon (sem acessar o ME real nos testes).
3. Banco (tabelas de cotações ME, itens, histórico) + tela nova no `web/`.
4. Revisão por IA.
5. Documentação na aba /documentacao e README.
