# Cruzamento de NF

Acha a nota fiscal de cada pedido da planilha da Vale cruzando dois arquivos
pela **ordem de compra**:

| arquivo | de onde vem | campo da OC | o que se usa dele |
|---|---|---|---|
| `PEDIDOS.json` | planilha de pedidos (portal Maestro) | `PEDIDO` | tudo; ganha a `NF` |
| `comparar.json` | exportação de vendas do ERP | `Ordem Compra` | `NF`, `Total Líq.`, `Tipo` |

Resultado:

- **`PEDIDOS_ATUALIZADO.json`**: o `PEDIDOS.json` inteiro, na mesma ordem e
  com os mesmos campos, mais `"NF": "15016"` no fim de cada pedido. O
  `PEDIDOS.json` original **não é alterado**.
- **`RELATORIO_NF.md`**: o relatório para ler.
- **`RELATORIO_NF.json`**: o mesmo relatório para o portal (ou outro programa) ler.

## Como rodar (manual)

No Windows, coloque `PEDIDOS.json` e `comparar.json` em `cruzar_nf\entrada\`
e dê duplo clique em **`CruzarNF.bat`** (na raiz do projeto). Os três
arquivos saem na mesma pasta.

Pela linha de comando, da raiz do projeto:

```
python -m cruzar_nf --pasta C:\planilhas
python -m cruzar_nf --pedidos A.json --comparar B.json --saida C.json
```

Só usa a biblioteca padrão do Python (3.10+): não precisa instalar nada.

Para ver funcionando com dados fictícios: `python -m cruzar_nf --pasta cruzar_nf/exemplo`
(a pasta `exemplo/` já tem a saída de uma rodada).

## Regras

**Como a OC é comparada.** Só os dígitos: `4101141499`, `"4101141499"`,
`" 4101141499 "` e `4101141499.0` (célula numérica do Excel) são a mesma OC.
OC vazia ou `0` não cruza com nada.

**Nomes de campo.** Espaço no fim, maiúscula e acento não importam: `"VALOR "`,
`"VALOR"` e `"valor"` são o mesmo campo; `"Total Líq."` e `"Total Liq."` também.
A planilha tem `"VALOR "` e `"REQUISITANTE "` com espaço no fim, e isso muda
quando alguém edita o cabeçalho.

**Que NF vai para o arquivo novo.**

| situação no ERP | `NF` gravada | seção do relatório |
|---|---|---|
| 1 NF | `"15016"` | Bateram |
| mais de uma NF | `"15020 / 15031"` | Mais de uma NF |
| OC existe, NF vazia ou 0 | mantém a que o pedido já tinha, senão `""` | No ERP, mas sem NF |
| OC não existe | mantém a que o pedido já tinha, senão `""` | Na planilha, não no ERP |

A NF é gravada sempre como texto, como no exemplo da planilha. Se o pedido já
tinha uma NF e o ERP traz outra, vale a do ERP, e o caso aparece em "NF da
planilha trocada".

## O que o relatório traz

- **Resumo** com todas as contagens e o percentual de pedidos com NF.
- **Mais de uma NF**: OCs faturadas em mais de uma nota.
- **No ERP, mas sem NF**: venda lançada e ainda não faturada.
- **Na planilha, não no ERP**: nenhuma venda com essa OC.
- **No ERP, não na planilha**: vendas com OC que a planilha não tem, com NF, cliente e total.
- **Divergência de valor**: `VALOR` da planilha contra a soma do `Total Líq.`
  de todas as vendas da OC (tolerância de R$ 0,05).
- **Mesma NF para várias OCs**: uma nota atendendo mais de um pedido.
- **Pedido repetido na planilha**: a mesma OC em mais de uma linha.
- **NF da planilha trocada**: a NF antiga e a nova.
- **Pedido vazio ou inválido**: linha da planilha sem número de pedido.
- **Linhas do ERP sem ordem de compra** e os **tipos de lançamento** (`VEN`...) encontrados.
- **Bateram**: a lista de tudo que deu certo.

As contagens por status são por **linha da planilha** (um pedido repetido
conta duas vezes). As contagens do ERP são por **OC distinta**.

## Portal Maestro

Como ligar isto na tela da planilha do portal: [INTEGRACAO_MAESTRO.md](INTEGRACAO_MAESTRO.md).

## Sincronização da planilha com o portal

`python -m cruzar_nf.sync_planilha_portal` é somente prévia: não grava dados,
estado, relatórios nem travas. `--gravar` autoriza a rodada. A primeira
rodada gravando registra a foto atual, sem alterar Excel nem PEDIDOS.json.
O cadastro de dez em dez minutos continua funcionando.

Após a foto, itens novos podem entrar nas duas pontas. Campos CIDADE,
FRETE, VALOR, DATA DE ENTREGA, FATURAMENTO, STATUS, DAV, REQUISITANTE e
EMAIL REQUSITAN podem ser editados em qualquer ponta. Um campo alterado
somente de um lado é propagado; conflito bloqueia o item inteiro. Diferenças
anteriores à foto aguardam correção humana. PEDIDO, RFQ e PRODUTO não são
corrigidos automaticamente; NF continua com as rotinas existentes.

Histórico antigo de um lado só não é importado. Exclusões não são
propagadas nem desfeitas. Ignorados e pareamentos ambíguos não são escritos.
Fórmulas ou mesclagens em campos sincronizáveis, linha modelo com fórmula e tabela com
total exigem revisão. Ao editar um e-mail, seu hyperlink antigo é retirado;
os links das demais células são preservados. Datas legadas americanas são reconhecidas quando
conferem com o Excel; pedidos novos seguem a convenção brasileira do cadastro.

O Excel é editado no XML, com estilos existentes, conferência das células
não autorizadas, backup, temporário na mesma pasta e troca final. Aberto
no Excel ou alterado no meio: adia; a foto não avança. O estado guarda a
operação pendente para retomar sem duplicar após uma interrupção.

`SincronizarPlanilhaPortal.bat --gravar --diario` é a tarefa própria:
dias úteis, de 12:30 até 18:00, repetida a cada dez minutos pelo Windows.
Uma rodada concluída não roda novamente naquele dia; adiamentos tentam
novamente. Logs: `logs/sync_planilha_portal.log`. A foto e o relatório
ficam no mesmo `SYNC_NF_DADOS`, que não deve ser alterado.

Instalação, validação e rollback: [INSTALAR_SERVIDOR.md](INSTALAR_SERVIDOR.md).
