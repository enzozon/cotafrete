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

## Pronto
- `mercado_eletronico/regras.py` + `feriados.py`: impostos, fixos, datas,
  leitura dos Campos Adicionais, validação (erros bloqueiam / avisos),
  conferência pós-salvamento.
- `tests/test_me_regras.py`: 68 testes.
- Linha de base da suíte na nuvem: 24 falhas **de ambiente** (cryptography do
  sistema quebrado; testes que pedem janela visível). Na nuvem, instalar
  `playwright==1.56.0` para casar com o Chromium de `/opt/pw-browsers`.

## Recon (23/09/2026) — `recon/recon_me.py`, só leitura
Rodado nas duas contas, sem salvar nem enviar: todo POST ao ME abortado
pela trava de rede, `form.submit` desligado, único clique = "Entrar".
Evidência em `recon_out/me/<conta>/` (fora do Git).

**Login**: `#LoginName`, `#RAWSenha`, `#SubmitAuth`. Com fuso diferente de
America/Sao_Paulo o ME abre um modal de fuso — o contexto do navegador
precisa de `timezone_id="America/Sao_Paulo"`.

**Lista de pendências**: vem de `POST api.web.mercadoe.com/supplier/
transactions/v1/transactions/search` (JSON). Por cotação: `processId`
(número), `company`, `customerName` (comprador), `clientCode`, `dueDate`
(UTC; 00:00Z = 21:00 de Brasília do dia anterior), `answerStatus`,
`statusName`. Valores de `answerStatus`: Não Respondida, Parcialmente
Respondida, Totalmente Respondida, Recusada. Link da resposta:
`/RespostaCotaItem.asp?Cotacao=<n>&SuperCleanPage=`.

**Salvar × enviar** (lido no JavaScript da página, sem clicar):
| Botão | Title no ME | Faz |
|---|---|---|
| Salvar (`MEButton_5`) | "Salvar informações para enviar mais tarde" | `Envia(9)` |
| Confirmar (`MEButton_6`) | "Finalizar a resposta da cotação e enviar ao comprador" | `Envia(1)` — **ENVIA** |
| Recusar (`MEButton_4`/`_8`) | "Recusar todos os itens da cotação" | `Envia(2)` → form `RespRecusa` → `RespCotaGrava.asp` |
| Páginas 1/2, próxima | — | `Envia(11/12/4)` |

Salvar, Confirmar e a paginação fazem POST do **mesmo** form `RespCota`
para a **mesma** URL (`RespostaCotaItem.asp?Cotacao=<n>&FID=`); a única
diferença é o campo oculto `Acao` (9 salva, 1 envia). Logo a trava de rede
não pode ser por URL: tem de ler o corpo do POST e só deixar passar
`Acao=9` (e 11/12/4 se paginar). Salvar exige ao menos um `chkItem_N`
marcado. O form tem `GravaRespTemp=S`: a paginação provavelmente grava o
rascunho da página atual.

**Paginação**: 10 itens por página (`MaxItem`). Página 2 por GET
(`&CurrentPage=2`, `&Pagina=2`) dá "Ocorreu uma falha no sistema" — só se
chega nela pelo POST. Alternativa só leitura: Exportar/Importar abre
`DO/Excel.mvc/PartialExcel/<cot>/<fornecedor>` (GET) com botão Download
= POST `/do/Excel.mvc/DownloadCotacaoExcel` (bloqueado no recon).

**Campos do cabeçalho** (name): `IcoTerms` (FOB), `ObsForn`,
`CondicaoPagamento` (`F060` = 60DDL, já vem), `NomeContato` (já vem),
`NumFoneCota`, `ValidadePropostaAux` (dd/mm/aaaa), `MoedaCot` (`BRL`),
`InscricaoEstadual`, `atrib_CidadeEstado_1_1_0_0` (textarea "* Frete").
Ocultos úteis: `DataLimite`, `DataAtual`, `MaxItem`, `CotacaoID`,
`FornecedorID`, `ObsComp` (observação do comprador).

**Campos do item N** (name → valor da opção):
`Preco{N}` (máx. 12, onblur recalcula), `UnidadeResp{N}` (`UN` = UNIDADE),
`IPI{N}`, `IPIIncluso{N}` (`I` Isento / `S` / `N`), `ICMS{N}`,
`ICMSIncluso{N}` (`I`/`S`), `PIS{N}`, `PISIncluso{N}` (`I`/`S`),
`COFINS{N}`, `COFINSIncluso{N}` (`I`/`S`), `NCM{N}` (máx. 16),
`Prazo{N}` (dias, máx. 4 — o ME calcula `DataEntregaItemAux{N}` sozinho),
`Fabricante{N}` (**máx. 20 caracteres**), `Observacao{N}`,
`OrigMat{N}` (`992` = 0, `994` = 2), `SubstituicaoTributaria{N}` (`N`),
`AliquotaSubstituicaoTributaria{N}`, `ValorSubstituicaoTributaria{N}`,
`BaseCalculo{N}` (já vem 100,00), `BaseCalculoImposto{N}` (`S` = sem IPI),
`chkItem_{N}`, `TipoImposto{N}`. Validações do próprio ME antes de salvar:
impostos ≤ 100; data de entrega > data limite; PIS/COFINS > 0 exigem
"incluso" (só no Confirmar).

**Divergências com o que estava decidido**:
- IE da UNIÃO é **083049428 - ES** (VENTURA: 082582190 - ES). O robô escolhe
  a única IE não vazia do select, não um valor fixo.
- `NomeContato` já vem preenchido e difere por conta ("Eliziane Amorim" ×
  "ELIZIANE AMORIM ROSA BARROS").
- Nada veio pré-preenchido com fundo azul nesta leitura (o azul dos prints
  era provavelmente preenchimento automático do Chrome).

**Detectar enviada**: `answerStatus` do JSON da lista (Parcialmente/
Totalmente Respondida) e a cotação sair de "Oportunidades a Responder".
**Não confirmado**: se um rascunho salvo (`Acao=9`) já muda o
`answerStatus` — só dá para saber salvando uma vez.

### Complemento do recon (sessão nuvem, mesmo dia, mesmas contas)
- **A listagem mora em outro domínio** (`api.web.mercadoe.com`). A trava do
  robô tem que cobrir `*.me.com.br` **e** `*.mercadoe.com`, liberando só o
  POST exato de `.../transactions/search` (leitura). Testes em
  `tests/test_me_recon_trava.py`.
- **Unidade:** o comprador pede `UND` ("Unidades"); a decisão fixa era
  "UNIDADE" (`UN`). O select tem `UN`, `UNI` (Unidade) e `UND` — escolher
  qual casa com o pedido (pergunta ao usuário).
- `Observacao{N}` tem **máx. 100** caracteres (além de Fabricante ≤ 20).
- `Prazo{N}` chama `MotorFrete.calcularDataSimples`, que só **mostra** a data
  quando há `IcotermsItem{N}` com `data-tipo`; o `Envia` copia
  `DataEntregaItemAux{N}` → `DataEntregaItem{N}`. Conferir no teste real se
  o campo de data se preenche sozinho; se não, o robô digita
  `regras.data_entrega`.
- ICMS: o ME chama `ConsistirImpostoICMS(..., 'ES', 'MG', ...)` (acha o
  comprador em MG), mas a função retorna `true` sem bloquear. Vale a nossa
  regra pela UF do "End. entrega" (23039029: ES; 23052403 da UNIÃO: MG).
- Estado em 23/09: VENTURA 23039029 (limite hoje 21:00, 18 itens pelo JS de
  "recusar todos") e 23049227 (25/09); UNIÃO 23052403 (28/09 21:00, 3 itens).
- Nuvem: o Chromium recusava o proxy (`ERR_CERT_AUTHORITY_INVALID`) com o
  NSS vazio. Resolve com `libnss3-tools` +
  `certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n ccr-agent-proxy -i /root/.ccr/agent-proxy-ca.crt`.

## Teste real de Salvar (23/09/2026) — `recon/teste_salvar_me.py`
Autorizado pelo usuário. UNIÃO, cotação 23052403 (3 itens, MG): cabeçalho +
só o item 1, textos "TESTE DO ROBO - NAO ENVIAR", preço 1,00. **Saiu um
único POST, com `Acao=9`; nada foi enviado.** O rascunho continua lá: quem
for responder de verdade tem que corrigir preço/obs antes de Confirmar.

O que o ME exige para o Salvar passar (cada item vira uma regra do robô):
1. `TipoImposto{N}` = `1` (IPI) — sem ele: "Escolha um dos tipos de imposto
   'IPI' ou 'ISS'".
2. `DataEntregaItemAux{N}` preenchida (dd/mm/aaaa). O ME só calcula a data
   pelo `keyup` do Prazo e isso não dispara no headless → o robô digita a
   data de `regras.data_entrega`.
3. Item não respondido = **totalmente vazio**. O ME já traz
   `BaseCalculo{N}=100,00` e trata isso como item começado ("Base de cálculo
   preenchida… informe o Preço"): o robô limpa a Base dos itens sem preço.
   Isso volta a 100,00 a cada recarga.
4. `chkItem_{N}` marcado nos itens respondidos.
5. Um `confirm` "Você verificou todas as informações digitadas?" — aceitar
   só esse texto e só durante o clique no Salvar; qualquer outro confirm é
   cancelado.
6. Campos de dinheiro: preencher o valor inteiro (`fill`) e disparar o blur.
   Digitar tecla a tecla passa pela máscara e desloca os dígitos.
7. O name do "* Frete" tem espaço no fim (`atrib_CidadeEstado_1_1_0_0 `).

**Depois de salvar**: relida a página, os 31 campos voltaram exatamente
como enviados (`regras.conferir` serve). Na lista, a cotação continua
**"Não Respondida" / "Em andamento"** — o rascunho NÃO muda o
`answerStatus`. Consequência: "Salva no ME" é estado nosso (banco), e
"Enviada" = `answerStatus` Parcialmente/Totalmente Respondida.

Decisões do usuário (23/09): IE da UNIÃO 083049428 - ES confirmada; nome do
contato fica como o ME traz em cada conta; o robô pode salvar a página 1
para ir à página 2 (é salvamento, `Acao=12`, nunca envio).

### Cópias das cotações reais (23/09/2026) — `recon/copia_cotacoes_me.py`
As 3 pendentes foram copiadas antes de fechar, para testar robô e tela sem o
ME: `tests/fixtures/me_real/` (HTML de cada página de itens com o token
trocado por `TOKEN`, print em JPEG e o JSON da listagem de cada conta).
VENTURA 23039029 (p1: itens 10–100, p2: 110–180) e 23049227 (1 item);
UNIÃO 23052403 (3 itens). Para a página 2 o script fez o único POST
liberado, troca de página (`Acao=12`, autorizado pelo usuário); depois
disso a lista continuou **Não Respondida**, então o rascunho temporário da
paginação não muda o `answerStatus`. Testes: `tests/test_me_copia.py`.
**Atenção:** a cópia da UNIÃO 23052403 foi tirada logo depois do teste real
de Salvar: ela mostra a página **com o rascunho salvo** (item 1 "TESTE DO
ROBO - NAO ENVIAR", preço 1,00) — serve para testar a releitura/conferência.
As duas da VENTURA estão limpas.

## Robô (23/09/2026) — sessão local
Módulos (camadas puras testadas sem navegador; robô testado offline com as
cópias reais de `tests/fixtures/me_real` e uma página falsa com os botões do ME):
- `trava.py` — as 3 camadas: `botao_e_salvar` (title exato do Salvar),
  `JS_TRAVA_FORM` (form.submit só RespCota com Acao 9/4/11–19),
  `motivo_bloqueio` (rede: todo POST aos dois domínios do ME morre fora disso),
  `confirm_aceito` (só "Você verificou…", só durante Salvar/paginar).
- `lista.py` — `ler_busca(json) -> list[CotacaoPendente]` (numero, empresa,
  comprador, codigo, data_limite em Brasília, status_resposta, `.enviada`,
  `.recusada`, `.link`).
- `mapa.py` — regras → nomes/códigos do ME; `plano_pagina` limpa a Base dos
  itens sem resposta e leva a justificativa de item sem preço para a obs geral.
- `robo.py` — `salvar_cotacao(conta, numero, itens, validade_dias, dry_run=True,
  obs_geral="") -> ResultadoRobo(ok, salvo, dry_run, divergencias, avisos,
  prints, erro, posts_liberados, bloqueios)`. Lê a UF/origem/remessa de cada
  item na página; pagina gravando (autorizado); reabre e confere depois de
  salvar. Prints e sessão em `runs/me/<conta>/` (fora do Git).

**Provas no ME real (UNIÃO 23052403, valores "TESTE DO ROBO")**: dry-run →
ok, 0 divergências, 0 POST; salvar → 1 POST `Acao=9`, reaberta e conferida,
0 divergências. Suíte: 1337 passam; 2 falhas de Della Volpe
(`test_dellavolpe_automatica`, `test_dellavolpe_caixa`) já falhavam no
commit anterior ao ME (e7ef26b) — dependem do `.env` desta máquina.

**Pendente**: item sem preço hoje fica vazio e a justificativa vai para a
observação geral. O ME tem "Deseja Recusar o Item?" com justificativa por
item — não testado; decidir com o usuário se o robô deve usar isso.

## Banco e tela nova (sessão nuvem, 23/09/2026)
Tela **/me** (link "Mercado Eletrônico" no menu), em `web/me_ui.py`:
- **Lista**: as cotações das duas contas, filtros por conta e status, data
  limite com contagem regressiva, "itens c/ preço", destaque vermelho
  faltando < 24 h — e o alerta mais importante, "Salva no ME mas NÃO
  enviada — fecha em …". Varredura do ME a cada 7 min (thread no lifespan,
  só se houver ME_*_LOGIN/SENHA) + botão "Atualizar agora". Leitura que
  falha não mexe em nada (aparece "Falha ao ler VENTURA: …").
- **Cotação /me/{id}**: "Ler itens do ME" (todas as páginas) → por item a
  descrição, quantidade/unidade, UF de entrega, origem e remessa pedidas e
  o texto do comprador; o usuário preenche preço, NCM, prazo, marca (20),
  obs (100), origem (0/2) e a validade. "Guardar e conferir" mostra, na
  linha, o que o robô vai digitar (ICMS/PIS/COFINS, data de entrega) e os
  erros/avisos de `regras`. "Salvar no ME" e "Testar sem salvar" (dry-run)
  só saem sem erro. Atalhos: marca/origem/prazo do 1º em todos, copiar do
  item anterior, NCM/marca/origem lembrados por código de material.
  **Não existe botão de enviar**; "Marcar como enviada" só grava no banco.
- **Status** (`mercado_eletronico/painel.py`): Pendente → Salvando → Salva
  no ME / Erro; Enviada quando o ME diz Parcial/Totalmente Respondida ou a
  cotação some das pendências antes do prazo; Vencida se some depois;
  Recusada. Enviada/Recusada são finais. Rascunho salvo sobrevive às
  varreduras (o ME continua "Não Respondida").
- **Banco** (`core/banco.py`): `me_cotacao`, `me_item` (o que veio do ME
  separado do que o usuário digitou — reler não apaga), `me_historico`,
  `me_material`. Dois cliques em "Salvar no ME" não soltam dois robôs
  (`me_trocar_status`).
- `mercado_eletronico/pagina.py` lê o HTML da página de resposta (itens,
  quantidade, unidade, Campos Adicionais), testado nas cópias reais.

**Ligação com o ME** (`me_ui.FONTE`, `LEITOR`, `ROBO`, trocáveis nos testes):
`mercado_eletronico/ponte.py` — `pendencias(conta)` (captura o JSON da busca
e passa por `lista.ler_busca`) e `ler_paginas(conta, numero)` (HTML de cada
página de itens), os dois dentro de `robo.Sessao`, com as travas do robô —
e `robo.salvar_cotacao(Conta, numero, itens, validade_dias, dry_run=...)`.
Provado no ME real às 19:25 de 23/09: as duas listas e a leitura de 23049227
e 23052403 (só leitura, nenhum POST).

Cuidado aprendido: sem sessão o ME carrega a lista e só depois manda para o
login por JavaScript, e `networkidle` nunca chega (o chat mantém a rede
ocupada). A ponte espera a resposta da busca; se não vier e a página estiver
no login, loga e tenta de novo.

**23039029 foi enviada** (ME: Totalmente Respondida, `lastDateAnswered`
17:39 de Brasília — fora do sistema). O `firstDateAnswered` dela é 16:45,
exatamente a troca de página da cópia (`Acao=12`, rascunho temporário): o ME
guarda a data do PRIMEIRO rascunho como "primeira resposta" quando a cotação
é enviada. Logo, a hora do envio é `lastDateAnswered`, não o `first`. Logo
depois da troca de página a lista ainda dizia "Não Respondida", sem datas.

Testes: `test_me_pagina.py`, `test_me_painel.py`, `test_me_banco.py`,
`test_me_tela.py` (tela de ponta a ponta com a lista e as páginas reais e
um robô falso).

## Revisão por IA (sessão nuvem, 24/09/2026)
`mercado_eletronico/revisao.py`, botão **Revisar com IA** na cotação.
- Uma chamada por cotação: `claude-opus-5`, thinking adaptativo, saída em
  JSON com esquema fixo (`alertas: [{item, nivel, mensagem}]`, níveis
  critico/atencao/info) e `fallbacks: "default"` (beta
  `server-side-fallback-2026-07-01`): se o classificador recusar, o servidor
  refaz no modelo recomendado.
- Vai para a IA: o pedido do comprador (descrição, quantidade, texto do item,
  Campos Adicionais, **texto geral do comprador** — agora guardado em
  `me_cotacao.obs_comprador`), o preenchimento, o que `regras` calculou e os
  erros/avisos do código, como fato. Nada de credencial.
- Procura o que o código não vê: marca pedida × oferecida ("não serão aceitas
  similares"), "ENTREGAR EM BSB" × End. entrega ES, NCM × produto, preço fora
  de escala, unidade/quantidade, prazo × remessa.
- **Só alertas, nunca altera valor.** Falhou (sem chave, rede, recusa, JSON
  ruim) → "Revisão IA indisponível: motivo" e o Salvar continua liberado.
- Alertas por item aparecem na linha do item; os da cotação no quadro
  "Revisão por IA". Mudou o preenchimento depois → "revise de novo"
  (assinatura do preenchimento em `revisao_assinatura`).
- **Falta a chave:** `ANTHROPIC_API_KEY` não existe no ambiente da nuvem nem
  foi testada contra a API real — testes com cliente falso
  (`tests/test_me_revisao.py`). Pôr a chave no `.env` do servidor.

## Documentação
Seção "Mercado Eletrônico: responder cotações" na aba **/documentacao**
(`me_ui.secao_documentacao`, números lidos das constantes), README (rotas,
chaves do `.env`, arquitetura) e `docs/DEPLOY_SERVIDOR.md` (chaves).

## Item sem preço → "Recusar item" do ME (24/09/2026)
Decisão do usuário: item que não será cotado é **recusado no ME** ("Deseja
Recusar o Item? Clique Aqui"), com a observação do usuário como justificativa
(`txtJustificativaRecusa_N`, até 200 caracteres). Antes ia para a obs geral.
- Na página, recusar é só JavaScript (`HabilitarRecusa(N)`): alterna o botão,
  limpa e deixa readonly os campos do item e mostra a justificativa. **Não sai
  requisição nenhuma**; a recusa vai no MESMO POST do Salvar (`Acao=9`).
- O robô (`robo.ajustar_recusas`) chama essa função — não clica num botão com
  "Recusar" no texto — e só quando o estado é o oposto do desejado (chamar de
  novo desfaz). Faz isso ANTES de digitar: `fill` em campo readonly quebra.
  Item que ganhou preço num rascunho antes recusado é "des-recusado".
- **Perigo documentado no JS do ME:** se todos os itens da cotação forem
  recusados, o Salvar pergunta "Você está recusando todos os itens…" e, se
  aceito, vira **recusa da cotação** (`RespCotaGrava.asp`, vai ao comprador).
  Três barreiras: `mapa` não monta plano com todos os itens da página
  recusados; a trava cancela esse confirm; a rede bloqueia `RespCotaGrava.asp`.
- **Provado no ME real (UNIÃO 23052403, texto "TESTE DO ROBO - NAO ENVIAR"):**
  dry-run → item 20 recusado pelo `HabilitarRecusa` real, 0 POST; Salvar → 1
  POST `Acao=9`, 0 divergências, e ao reabrir o item 20 **continuava recusado
  com a justificativa** (o rascunho guarda a recusa); a lista seguiu "Não
  Respondida". Depois a recusa de teste foi **desfeita** (mais 1 POST
  `Acao=9`): a cotação voltou ao rascunho anterior (só o item 10 com os
  valores de teste da sessão local).
- Aprendido no desfazer manual: item vazio precisa de `BaseCalculo` vazio (o ME
  traz 100,00 e exige preço, marcando o campo em vermelho, SEM alert). O robô
  já faz isso; script avulso tem de fazer igual.

## Próximos passos
1. ~~Recon~~, ~~teste de Salvar~~ e ~~robô~~ (acima).
2. ~~Robô com trava de envio e dry-run~~ feito (sessão local).
3. ~~Banco + tela nova~~ feito, ligado ao robô por `ponte.py` e `robo.salvar_cotacao`.
4. ~~Revisão por IA~~ feito (falta a chave `ANTHROPIC_API_KEY` no servidor).
5. ~~Documentação na aba /documentacao e README~~ feito.

**Em aberto:** (a) ICMS de origem 2 fora do ES (12% × 4%), com a
contabilidade; (b) ~~item sem preço~~ → "Recusar item" (acima); (c) primeiro "Salvar no ME" pela TELA contra o ME
real (o robô já foi provado sozinho; a tela, com robô falso).
