# Conferência do DAV com o HSE antes do Gerar

Data: 03/11/2026. Origem: revisão dos DAVs 35 a 65 em produção.

## Problema

Das 10 falhas entre os DAVs 35 e 65, 8 só apareceram depois do Gerar, e o HSE
nunca estava fora do ar:

| Motivo | DAVs |
|---|---|
| Desconto acima de 15% sobre a tabela | 49, 56, 60 |
| Cliente (código/CNPJ) não encontrado | 39, 44, 46 |
| Local de entrega não bate com o cadastro | 35, 50 |
| Produto novo sem NCM/GRUPO/MARCA ou descrição > 100 | 53 |

Hoje a conferência (`POST /dav/conferir`) só lê a planilha. O vendedor descobre o
erro um ou dois minutos depois do Gerar, corrige e reenvia.

Junto vem um erro de texto: quando o resultado é "ERRO na validação com o HSE
(nada foi criado)", o `orcamento/diagnostico.py` classifica o salvamento como
`desconhecido` e manda "Consulte o responsável pelo robô antes de reenviar". O
vendedor fica com medo de reenviar algo que não foi gravado.

## Decisões (com o usuário)

1. A conferência consulta o HSE, sempre em modo só leitura.
2. Erro certo bloqueia o Gerar. HSE sem resposta não bloqueia: só avisa.
3. Preço da planilha acima de 2x o preço de tabela gera aviso amarelo, sem bloquear.
4. A tela mostra o que o HSE encontrou: cliente, endereço, vendedor e cada item.
5. A conferência usa um navegador próprio. O HSE aceita o mesmo usuário em duas
   sessões ao mesmo tempo (confirmado pelo usuário).

## Fluxo

1. O vendedor envia a planilha. `ler_planilha` roda como hoje. Erro de
   preenchimento volta na hora, sem DAV.
2. Planilha válida: o DAV é criado em `rascunho` com `conferencia = "conferindo"`
   e entra na fila de conferência. A página `/dav/{id}` atualiza a cada 5 s,
   como já faz com `fila` e `gerando`.
3. A conferência roda `gerar(...)` com `dry_run=True`, a simulação que já existe
   e para antes do Incluir. Durante a conferência, o `page.route` bloqueia toda
   chamada de gravação ao HSE (o mesmo padrão de `HseSoLeitura` da simulação em
   massa). Assim, um clique que escape não chega a gravar nada.
4. O resultado vai para o DAV: `conferencia` vira `ok`, `erros` ou
   `nao_conferido`, e `conferencia_relatorio` guarda em JSON o relatório da simulação
   e o que o HSE encontrou (cliente, endereço, vendedor, itens, avisos e erros).
5. A tela de conferência mostra:
   - cliente (código e razão social), endereço de entrega completo e vendedor;
   - para cada item: código, descrição no HSE, preço da tabela e preço da planilha;
   - avisos em amarelo e erros em vermelho;
   - **Gerar** só quando `conferencia` é `ok` ou `nao_conferido`; com `erros`, o
     botão "Enviar planilha corrigida" (volta a `/dav`).
6. `POST /dav/{id}/gerar` recusa um rascunho com `conferencia` em `conferindo`
   ou `erros`. Isso vale também para quem chamar a rota direto, sem a tela.
7. A geração continua conferindo tudo de novo antes de salvar, porque o HSE pode
   mudar entre a conferência e o Gerar.

## O que bloqueia e o que avisa

Bloqueia (`conferencia = "erros"`): toda linha `ERRO:` do relatório da simulação.
Hoje a simulação já produz estas:

- cliente não encontrado pelo código, CNPJ ou CPF;
- local de entrega sem endereço correspondente (a mensagem lista os endereços
  com o número de cada um);
- vendedor que não está no HSE;
- desconto acima do máximo sobre a tabela;
- produto novo sem NCM, GRUPO ou MARCA, ou com a descrição de cadastro acima de
  100 caracteres;
- código de produto inexistente.

Avisa, sem bloquear:

- **Preço acima de 2x a tabela.** Exemplo de texto: "Item 3: R$ 450,00 está
  3,2× acima da tabela (R$ 140,00) do código 12345 – PRODUTO X; confira se o
  código está certo". A verificação é nova e fica em `processador.py`, ao lado de
  `conferir_desconto`. O limite é a constante `PRECO_ACIMA_TABELA = 2`.
- **Produto achado pela descrição**, e não pelo código: o texto já existe no
  relatório.
- **Aviso financeiro do HSE.** Para o vendedor sai só "consulte o financeiro",
  pela regra do `diagnostico.py`.

## Fila de conferência

- `orcamento/conferencia.py`: uma thread trabalhadora, uma conferência por vez,
  separada de `FilaDav`. Ela pega uma vaga de `VAGA_NAVEGADOR` (limite atual de
  2 navegadores na máquina, dividido com o frete e o ME). Se as vagas estiverem
  ocupadas, ela espera; o limite não aumenta.
- Tempo máximo: 120 s (`LIMITE_CONFERENCIA_S`). Estourou, ou deu
  `HseIndisponivel`, vira `nao_conferido` com o aviso "Não consegui conferir com o
  HSE agora; o robô confere de novo ao gerar".
- Na partida do servidor, o rascunho que ficou em `conferindo` passa para
  `nao_conferido`, com a mesma ideia de `dav_interromper`.
- Um rascunho com `conferencia` vazia é um DAV antigo, de antes da mudança. Ele
  segue o fluxo de hoje e o Gerar fica liberado.

## Banco

A tabela `dav` ganha duas colunas: `conferencia TEXT` e `conferencia_relatorio
TEXT`. A migração é um `ALTER TABLE ... ADD COLUMN`, como as anteriores. As duas
entram em `CAMPOS_DAV`. O texto passa por `_sem_segredo`, como o `relatorio`.

## Painel do admin

O detalhe `/adm/dav/{id}` mostra o resultado da conferência e o relatório dela. O
rascunho com `erros` aparece em "Precisa de atenção", como as planilhas rejeitadas.

## Correção junto: "nada foi criado"

Em `diagnostico.py`, um resultado com "nada foi criado" passa a ser salvamento
`nao_criado`. A orientação fica "Nada foi criado no HSE. Corrija a planilha e
envie de novo". O caso entra em `test_dav_diagnostico.py` com o texto real do
DAV 49.

## Fora desta spec

- Planilha à prova de erro, mapa VALE, teste de fumaça diário e regressão: cada
  um terá sua própria spec.
- Branch `fix/dav-local-numero-e-retentativa` (`8041565`): vira uma PR própria,
  antes desta, depois de atualizada com a `main`.

## Testes

- **Unidade (`hse_falso.py`):** um teste por bloqueio e por aviso, com as
  mensagens reais dos DAVs 35, 39, 49, 50, 53, 56 e 60. A regra de 2x é testada
  na fronteira (2,0× não avisa; 2,01× avisa).
- **Tela (`tests/test_dav_tela.py`):**
  - o Gerar some com `erros` e aparece com `ok` e com `nao_conferido`;
  - o POST de gerar é recusado em `conferindo` e em `erros`;
  - o texto financeiro não aparece para o vendedor.
- **Fila:**
  - um reinício no meio vira `nao_conferido`;
  - `HseIndisponivel` vira `nao_conferido`;
  - a conferência e a geração rodam ao mesmo tempo sem uma travar a outra.
- **Segurança:** com a conferência em andamento, um POST de gravação disparado de
  propósito é abortado pela rota.
- **Real, só leitura:** antes da PR, rodar a conferência contra o HSE de produção
  com as planilhas dos DAVs 35 a 65:
  - as que falharam precisam ser bloqueadas pelo mesmo motivo;
  - as que deram certo precisam passar.

## Ordem de entrega

1. PR da branch `8041565`, atualizada com a `main`.
2. PR da correção "nada foi criado".
3. PR desta conferência.

Cada PR só entra depois da CI verde e do merge da anterior. Depois da 3ª, entram
a atualização do `docs/MAPA_DO_SISTEMA.md` e o texto do Guia do Vendedor (número
na B30 e a tela nova), entregue ao usuário para colar.
