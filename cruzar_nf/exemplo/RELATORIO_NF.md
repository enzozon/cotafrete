# Relatório do cruzamento de NF

Gerado em 2026-09-29T19:22:41.
- **PEDIDOS:** `cruzar_nf/exemplo/PEDIDOS.json`
- **comparar:** `cruzar_nf/exemplo/comparar.json`
- **gerado:** `cruzar_nf/exemplo/PEDIDOS_ATUALIZADO.json`

## Resumo

|  | quantidade |
|---|---|
| Pedidos na planilha (PEDIDOS.json) | 10 |
| Ordens de compra distintas na planilha | 8 |
| Linhas no ERP (comparar.json) | 10 |
| Ordens de compra distintas no ERP | 8 |
| **Bateram (1 NF)** | 5 |
| **Mais de uma NF** | 2 |
| **No ERP, mas sem NF** | 1 |
| **Na planilha, não no ERP** | 1 |
| **No ERP, não na planilha** | 1 |
| Pedido vazio/inválido na planilha | 1 |
| Pedido repetido na planilha | 1 |
| Mesma NF para várias OCs | 1 |
| NF da planilha trocada pela do ERP | 1 |
| Valor da planilha ≠ valor do ERP | 1 |
| Linhas do ERP sem ordem de compra | 1 |
| Pedidos com NF preenchida | 70,0% |

Tipos de lançamento no ERP (das linhas com OC): VEN: 9.

## Mais de uma NF (2)

A OC foi faturada em mais de uma nota. No arquivo novo vão todas, separadas por ` / `.

| # | pedido | NFs | valor | requisitante | cidade | produto |
|---|---|---|---|---|---|---|
| 2 | 4101141500 | 15020 / 15031 | R$ 3.200,00 | CARLOS | ITABIRA - MG | BATERIA INTELIGENTE DJI MATRICE 30 |
| 7 | 4101141500 | 15020 / 15031 | R$ 3.200,00 | CARLOS | ITABIRA - MG | BATERIA INTELIGENTE DJI MATRICE 30 (linha repetida) |

## No ERP, mas sem NF (1)

A venda existe no ERP, mas ainda não foi faturada (NF vazia ou 0).

| # | pedido | valor | requisitante | cidade | produto |
|---|---|---|---|---|---|
| 3 | 4101141501 | R$ 980,50 | ANA | MARIANA - MG | CARREGADOR PORTATIL 100W |

## Na planilha, mas não no ERP (1)

Nenhuma linha do comparar.json tem esta ordem de compra.

| # | pedido | valor | requisitante | cidade | produto |
|---|---|---|---|---|---|
| 4 | 4101141502 | R$ 450,00 | JOAO | VITORIA - ES | CABO USB-C 2M |

## No ERP, mas não na planilha (1)

| OC | NFs | linhas | emissão | total líq. | cliente |
|---|---|---|---|---|---|
| 4101141599 | 15060 | 1 | 26/12/2025 | R$ 5.100,00 | MINA DE CAPANEMA/VALE S.A. |

## Divergência de valor (1)

VALOR da planilha comparado com a soma do Total Líq. das vendas da OC (tolerância de R$ 0,05).

| # | pedido | NF | planilha | ERP | diferença |
|---|---|---|---|---|---|
| 5 | 4101141503 | 15040 | R$ 1.200,00 | R$ 1.350,00 | R$ 150,00 |

## Mesma NF para várias OCs (1)

| NF | OCs | dessas, na planilha |
|---|---|---|
| 15050 | 4101141505, 4101141506 | 4101141505, 4101141506 |

## Pedido repetido na planilha (1)

| OC | vezes | posições |
|---|---|---|
| 4101141500 | 2 | 2, 7 |

## NF da planilha trocada (1)

O pedido já tinha NF e o ERP diz outra. Vale a do ERP.

| # | pedido | NF antes | NF agora |
|---|---|---|---|
| 6 | 4101141504 | 14000 | 15045 |

## Pedido vazio ou inválido (1)

| # | PEDIDO | requisitante | produto |
|---|---|---|---|
| 8 | - | LUCAS | ITEM SEM PEDIDO |

## Bateram (5)

| # | pedido | NF | valor | requisitante | cidade |
|---|---|---|---|---|---|
| 1 | 4101141499 | 15016 | R$ 1.740,00 | MICHELI | OURO PRETO - MG |
| 5 | 4101141503 | 15040 | R$ 1.200,00 | PAULA | CONGONHAS - MG |
| 6 | 4101141504 | 15045 | R$ 600,00 | RAFAEL | SAO LUIS - MA |
| 9 | 4101141505 | 15050 | R$ 720,00 | BRUNA | CANAA DOS CARAJAS - PA |
| 10 | 4101141506 | 15050 | R$ 280,00 | BRUNA | CANAA DOS CARAJAS - PA |
