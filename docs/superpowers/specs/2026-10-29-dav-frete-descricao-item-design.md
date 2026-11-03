# Gerar DAV: frete (CIF/FOB) e descrição por item

Data: 29/10/2026. Aprovado pelo Enzo no chat.

## Planilha v3 (aba ORÇAMENTO)

- **A38 "Frete" / B38**: lista suspensa CIF ou FOB (aba LISTAS, H2:H3). Os
  blocos antigos ITEM 1..27 (só rótulos, ninguém lê) desceram uma linha.
- **R1 "DESCRIÇÃO NO DAV" / R2:R25**: texto livre por item. O nome evita
  confundir com a coluna O (DESCRIÇÃO P/ CADASTRO, só para produto novo).
- B38 e R2:R25 ficam desbloqueadas (a aba é protegida).

## Regras

- Frete marcado: o `#txObservacao` recebe as observações da B26 e, numa linha
  abaixo, `FRETE CIF, PRAZO DE ENTREGA 30 DIAS`. Com 1 dia: `1 DIA`. Sem B26,
  só a linha do frete. Sem frete, nada muda.
- Erros na leitura (bloqueiam antes de tocar no HSE):
  - frete marcado com prazo (B32) vazio ou 0;
  - B38 diferente de CIF/FOB;
  - observações + linha do frete acima de 1024 caracteres;
  - descrição acima de 512 caracteres (maxLength do campo no HSE).
- Quebras de linha da descrição viram um espaço (a caixa do HSE tem uma linha).
- A descrição que o HSE não gravar vira aviso no relatório; o DAV é salvo.
  (Erro obrigaria a esvaziar um rascunho que só a gestora exclui.)

## HSE (lido em 29/10/2026 no DAV 16354, sem gravar)

- `<input type="text" id="dsObsItem_<cdItem>" maxLength="512">`, escondido na
  linha `tr#trItem_<cdItem>`; abre pelo botão `+` (`abreObsItem`) e só existe
  no modo edição, isto é, depois do Incluir.
- `onblur` → `salvarObsItem(this)` → POST `vendaItem.php` com
  `acao=salvarObsItem`, `cdPedido`, `cdPedidoItem`, `dsObsItem`. Sucesso mostra
  o texto em `#divObsItem_<cdItem>`; erro dá `alert('erro ao salvar observacao')`.
- O robô acha a linha nova comparando os `trItem_*` de antes e depois do
  Incluir, clica no `+`, preenche, tira o foco, espera a resposta e confere o
  `divObsItem`.
- Na simulação (`DAV_DRY_RUN=1`) não há Incluir: o relatório mostra a descrição
  que seria gravada.

## Tela /dav

O resumo mostra as Observações já com a linha do frete (o mesmo texto que vai
ao HSE) e uma coluna Descrição na tabela de itens.

## Fora do escopo

O "Exportar planilha base" do Maestro não preenche frete nem descrição; só
passa a usar o modelo novo.
