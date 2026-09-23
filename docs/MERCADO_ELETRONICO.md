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

## Próximos passos
1. Recon (sem salvar nem enviar): campos e seletores, iframes/postbacks,
   botão salvar × enviar, observações e anexos do comprador, lista de
   pendências (número, comprador, data limite, itens, link), como detectar
   cotação enviada. Scripts em `recon/`, no padrão dos existentes.
2. Robô `mercado_eletronico/robo.py` com trava de envio e dry-run + testes
   contra HTML salvo do recon (sem acessar o ME real nos testes).
3. Banco (tabelas de cotações ME, itens, histórico) + tela nova no `web/`.
4. Revisão por IA.
5. Documentação na aba /documentacao e README.
