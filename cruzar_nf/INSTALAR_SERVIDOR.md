# Sincronização de NF no servidor do Maestro

Grava a NF de cada pedido do `PEDIDOS.json` do Maestro no campo
**`Nº NOTA FISCAL`**, a partir das vendas do HSE. Roda sozinha 3 vezes por dia
pelo Agendador de Tarefas do Windows. **Não mexe no `gerenciador.py`, no
`planilha_manager.py` nem no portal.**

## Como funciona

1. O robô entra no HSE (Venda (pedido)) e baixa um Excel por mês do período
   (com período grande o HSE não lista as vendas e o Excel vem vazio).
   Se algum mês tiver no Excel um número de vendas diferente da tela, a rodada
   para **sem gravar nada**.
2. As vendas vão para a base acumulada (`vendas_hse.json`).
3. Cruza pela ordem de compra e grava a NF **só onde o campo está vazio**.
   Mais de uma NF: `"15020 / 15031"`. Grava mesmo com diferença de valor
   (a diferença fica no relatório).
4. A gravação é segura com o gerenciador ligado: confere se o arquivo mudou
   entre ler e gravar, grava num temporário e troca de uma vez, relê depois
   para ver se o gerenciador não gravou por cima, e garante que a data do
   arquivo avança (é assim que o gerenciador percebe a mudança e recarrega).
5. Antes de gravar, guarda um backup do `PEDIDOS.json` (os 30 últimos).

## Instalação

1. Copiar a pasta `cruzar_nf` para uma pasta própria no servidor, por exemplo
   `\\SERVIDOR2\Publico\ALLAN\NUVEM\server2012\sync_nf\cruzar_nf`.
2. Criar `sync_nf\.env` (mesmo Python do gerenciador: já tem selenium e dotenv):

   ```
   HSE_USUARIO=...
   HSE_SENHA=...
   HSE_HEADLESS=1
   SYNC_NF_DADOS=\\SERVIDOR2\Publico\ALLAN\database\sync_nf
   SYNC_NF_PEDIDOS=\\SERVIDOR2\Publico\ALLAN\database\Banco-de-dados\PEDIDOS.json
   ```

   `HSE_HEADLESS=1` é necessário quando a tarefa roda sem ninguém logado.
3. Primeira carga, só prévia (não grava):
   `cruzar_nf\SincronizarNF.bat --previa --de 01/01/2025`
   Conferir em `logs\sync_nf.log` e em `SYNC_NF_DADOS\cruzamento_nf\RELATORIO_NF_ultimo.json`.
4. Primeira gravação, acompanhada: `cruzar_nf\SincronizarNF.bat --de 01/01/2025`.
5. Agendar (prompt de comando como administrador; troque o caminho e o usuário):

   ```
   schtasks /Create /TN "Maestro NF 08h00" /TR "\"C:\caminho\sync_nf\cruzar_nf\SincronizarNF.bat\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 08:00 /RU USUARIO /RP *
   schtasks /Create /TN "Maestro NF 12h30" /TR "\"C:\caminho\sync_nf\cruzar_nf\SincronizarNF.bat\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 12:30 /RU USUARIO /RP *
   schtasks /Create /TN "Maestro NF 17h30" /TR "\"C:\caminho\sync_nf\cruzar_nf\SincronizarNF.bat\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 17:30 /RU USUARIO /RP *
   ```

   Nas rodadas agendadas o período é automático: da última sincronização
   menos 10 dias até hoje (pega NF emitida depois e OC corrigida depois).

## Se der erro

- **Login**: o robô preenche usuário e senha, escolhe a empresa e a filial
  (VENTURA MATRIZ) na 2ª etapa e clica em Entrar de novo. "O HSE não aceitou
  o login" = conferir `HSE_USUARIO` e `HSE_SENHA`.
- **Sem janela (`HSE_HEADLESS=1`)**: usa o `--headless=new` do Chrome (109 ou
  mais novo). Testado com o Chrome desta máquina; se no servidor travar no
  login ou no download, rodar a prévia com `HSE_HEADLESS=0` e um usuário
  logado no servidor, e agendar a tarefa "somente quando o usuário estiver
  conectado".
- **"a tela do HSE mostrou N vendas e o Excel trouxe M"**: a rodada parou sem
  gravar; a próxima tenta de novo.

## Desfazer

Os backups ficam em `SYNC_NF_DADOS\backups\PEDIDOS antes da NF <data>.json`.
Para voltar, pare o gerenciador, copie o backup por cima do `PEDIDOS.json` e
ligue o gerenciador de novo. Para parar a sincronização: desabilitar as três
tarefas no Agendador.
