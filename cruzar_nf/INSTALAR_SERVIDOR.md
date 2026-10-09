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

---

# Cadastro automático de pedidos (planilha dos estagiários -> portal)

Os pedidos entram **só** na aba PEDIDOS da planilha
`\SERVIDOR2\Publico\PLANILHA DE CONTROLE VALE - ESTAGIARIOS (copia 1).xlsx`.
O `CadastrarPedidos.bat` roda a cada 10 minutos e leva cada linha nova para o
`PEDIDOS.json` (a tela "Pedidos" do portal). Usa a mesma pasta, o mesmo `.env`
e o mesmo jeito seguro de gravar da sincronização de NF. **Não mexe no
`gerenciador.py`, no `planilha_manager.py`, no portal nem na planilha** (a
planilha é só lida, a partir de uma cópia).

## Como funciona

1. Se a planilha não foi salva desde a última rodada, não faz nada (nem log).
2. Copia a planilha e lê a aba PEDIDOS. Vale só o que foi **salvo** no Excel.
3. Linha nova = combinação PEDIDO + RFQ + começo do PRODUTO nunca vista antes.
4. Linha sem CIDADE, PEDIDO, VALOR, PRODUTO ou REQUISITANTE ainda está sendo
   digitada: espera (aparece como `incompletas` no log) e entra quando completar.
5. Se o pedido já está no portal (mesmo PEDIDO ou RFQ e mesmo começo de
   PRODUTO), não grava de novo. Pega cadastro manual e correção de digitação.
6. Grava com backup (`SYNC_NF_DADOS\backups\PEDIDOS antes do cadastro <data>.json`,
   os 30 últimos), confere depois e grava de novo se o gerenciador salvou por cima.
7. Pedido apagado no portal **não volta**: o que já foi visto não é gravado de novo.

## Instalação

1. Copiar `cadastro_pedidos.py`, `maestro.py` e `CadastrarPedidos.bat` para a
   pasta `cruzar_nf` do servidor (a mesma da NF).
2. (Opcional) no `.env`: `CADASTRO_PLANILHA=` se a planilha mudar de lugar.
3. Prévia: `cruzar_nf\CadastrarPedidos.bat --previa` (não grava nada).
4. Primeira rodada: `cruzar_nf\CadastrarPedidos.bat`. **Não cadastra nada**,
   só marca as linhas atuais como já cadastradas (planilha e portal divergem
   em algumas digitações antigas, que assim não viram pedido duplicado).
5. Agendar:

   ```
   schtasks /Create /TN "Maestro Cadastro Pedidos" /TR "\"C:\caminho\sync_nf\cruzar_nf\CadastrarPedidos.bat\"" /SC MINUTE /MO 10 /RU USUARIO /RP *
   ```

## Acompanhar e desfazer

- **Portal**: menu ☰ → "NFs (HSE) e cadastro automático". Mostra a última
  verificação da planilha (vermelho se passar de 30 min ou se deu erro), o
  último cadastro e os pedidos cadastrados. Vem pelo serviço de NF: depois de
  atualizar `maestro.py` e `cadastro_pedidos.py`, reiniciar a tarefa
  "Maestro NF Servico" (`schtasks /End` e `schtasks /Run`).
- Log: `logs\cadastro_pedidos.log` (só rodadas em que algo mudou ou deu erro).
- Estado e histórico: `SYNC_NF_DADOS\cadastro_pedidos.json`.
- `[ERRO] Não consegui abrir a planilha (o Excel estava salvando?)`: normal de
  vez em quando; a próxima rodada tenta de novo.
- Desfazer: pare o gerenciador, copie o backup por cima do `PEDIDOS.json`,
  ligue o gerenciador. Parar: desabilitar a tarefa no Agendador.
- Recomeçar do zero (marcar tudo de novo): apagar `cadastro_pedidos.json`.

---

# Conferência planilha x portal (diária)

Roda sozinha, uma vez por dia, dentro do `CadastrarPedidos.bat` (não precisa
de tarefa nova). Lista o que só está na planilha, o que só está no portal e
NF diferente entre os dois; o resultado (`SYNC_NF_DADOS\conferencia_planilha.json`)
aparece no portal, na janela "NFs do HSE e cadastro automático".

Linhas canceladas de propósito (não devem aparecer como divergência) ficam em
`SYNC_NF_DADOS\conferencia_ignorar.json`:

```
[{"chave": "4101202899|206584|DECIBELIMETRODIGITALMATERIALCA", "motivo": "cancelado (Enzo, 07/10/2026)"}]
```

A chave é PEDIDO|RFQ|começo do PRODUTO, normalizados (sem acento, só letras e números).
Na mão: `python -m cruzar_nf.planilha_portal`.

# NF na planilha dos estagiários (botão do portal)

Botão "Gravar NF na planilha" (e "Só prévia") na mesma janela. Grava a NF do
portal na coluna **N "NF (MAESTRO)"** da aba PEDIDOS. Segurança:

- planilha aberta no Excel -> não grava e avisa (diz quem abriu, se o `~$` for recente);
- só a coluna N muda: o resto do arquivo fica byte a byte igual (confere antes e depois);
- backup antes: `SYNC_NF_DADOS\backups_planilha\PLANILHA antes da NF <data>.xlsx` (30 últimos);
- se a planilha mudar ou for aberta no meio, não troca o arquivo;
- coluna N com outro título -> não grava; linha com NF diferente em mais de um pedido -> pula.

Na mão: `python -m cruzar_nf.nf_planilha` (prévia) e `--gravar`.
Desfazer: com a planilha FECHADA, copiar o backup por cima dela.

Instalação: copiar `nf_planilha.py`, `planilha_portal.py`, `cadastro_pedidos.py`,
`sincronizar.py`, `maestro.py` e `CadastrarPedidos.bat` para `cruzar_nf` e
reiniciar o serviço de NF (`ReiniciarServicoNF.bat`). No portal: `server.js`
(eventos `solicitar_nf_planilha` / `progresso_nf_planilha` / `retorno_nf_planilha`)
e `planilha_vale.html`; o `server.js` novo exige reiniciar o portal.

---

# Sincronização bidirecional (tarefa própria)

Usa o serviço de NF existente para mostrar o estado; não instala outro
serviço permanente. A tela depende também do PR `feat/sync-planilha-portal`
no repositório `portaismaestro`; os nomes dos eventos não mudam.

Antes de produção, Enzo executa os comandos abaixo e cola a saída. Se houver
diferença de código, parar para analisar o diff antes de copiar. Não alterar
`SYNC_NF_DADOS`. A instalação não autoriza merge nem escrita automática no servidor.

## 1. Conferência (PowerShell na máquina de desenvolvimento)

```powershell
$codigoSync = '\\SERVIDOR2\Publico\ALLAN\NUVEM\server2012\sync_nf'
$repoSync = 'C:\Users\vendas12\enzo\cotafrete-sync-planilha'
$arquivosSync = @('arquivo_pedidos.py','cadastro_pedidos.py','maestro.py','nf_planilha.py','planilha_portal.py')
foreach ($nomeSync in $arquivosSync) {
    $remotoSync = Join-Path "$codigoSync\cruzar_nf" $nomeSync
    Get-Item -LiteralPath $remotoSync | Select-Object FullName,Length,LastWriteTimeUtc
    Get-FileHash -Algorithm SHA256 -LiteralPath $remotoSync
    # Abaixo a main é extraída sem conversão de encoding para comparar os bytes.
}
$mainSync = Join-Path $env:TEMP 'maestro-main-conferencia'
New-Item -ItemType Directory -Path $mainSync -Force | Out-Null
git -C $repoSync archive --format=zip --output="$mainSync\main.zip" origin/main cruzar_nf
Expand-Archive -LiteralPath "$mainSync\main.zip" -DestinationPath "$mainSync\extraido" -Force
foreach ($nomeSync in $arquivosSync) {
    $remotoSync = Join-Path "$codigoSync\cruzar_nf" $nomeSync
    $mainArquivoSync = Join-Path "$mainSync\extraido\cruzar_nf" $nomeSync
    [pscustomobject]@{Arquivo=$nomeSync; Servidor=(Get-FileHash -LiteralPath $remotoSync).Hash; Main=(Get-FileHash -LiteralPath $mainArquivoSync).Hash}
    git diff --no-index --ignore-space-at-eol -- $mainArquivoSync $remotoSync
}
$managerSync = '\\SERVIDOR2\Publico\ALLAN\NUVEM\server2012\novo maestro\planilha_manager.py'
Get-Item -LiteralPath $managerSync | Select-Object FullName,Length,LastWriteTimeUtc
Get-FileHash -LiteralPath $managerSync
git diff --no-index --ignore-space-at-eol -- "$repoSync\tests\fixtures\maestro\planilha_manager_servidor_2026-10-01.py" $managerSync
```

Revisar a recarga pelo mtime e os pontos que chamam `iniciar()` antes de salvar.
Hashes diferentes apenas por CRLF precisam também de análise, não de cópia cega.

## 2–3. Backup e cópia (só após conferência aprovada)

```powershell
$backupSync = Join-Path $codigoSync ('backup_codigo\sync_planilha_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backupSync | Out-Null
$travasSync = '\\SERVIDOR2\Publico\ALLAN\database\sync_nf'
if ((Test-Path "$travasSync\sync_nf.trava") -or (Test-Path "$travasSync\nf_planilha.trava")) { throw 'Rotina trabalhando: aguardar.' }
foreach ($nomeSync in $arquivosSync) { Copy-Item -LiteralPath (Join-Path "$codigoSync\cruzar_nf" $nomeSync) -Destination $backupSync }
Copy-Item -LiteralPath '\\SERVIDOR2\Publico\PLANILHA DE CONTROLE VALE - ESTAGIARIOS (copia 1).xlsx' -Destination "$backupSync\PLANILHA.xlsx"
Copy-Item -LiteralPath '\\SERVIDOR2\Publico\ALLAN\database\Banco-de-dados\PEDIDOS.json' -Destination "$backupSync\PEDIDOS.json"
foreach ($estadoSync in @('cadastro_pedidos.json','sync_planilha_portal.json','conferencia_planilha.json')) {
    if (Test-Path "$travasSync\$estadoSync") { Copy-Item -LiteralPath "$travasSync\$estadoSync" -Destination $backupSync }
}
$copiarSync = $arquivosSync + @('sync_planilha_portal.py','planilha_edicao.py','SincronizarPlanilhaPortal.bat')
foreach ($nomeSync in $copiarSync) { Copy-Item -LiteralPath (Join-Path "$repoSync\cruzar_nf" $nomeSync) -Destination "$codigoSync\cruzar_nf" }
```

Fazer a cópia numa janela sem execução do cadastro e NF; desabilitar
temporariamente as tarefas existentes e reabilitá-las depois. Conferir os
hashes finais. No RDP como administrador, reiniciar pelo `ReiniciarServicoNF.bat`.
Atualizar o portal pelo seu PR e reiniciar o pm2 com o fluxo habitual.

## 4. Prévia no servidor

```bat
cd /d "C:\caminho\sync_nf"
cruzar_nf\SincronizarPlanilhaPortal.bat
```

Colar a saída antes de continuar. Nenhum arquivo de dados ou estado é gravado.
Conferir primeiro em cópias e abrir o Excel para validar visualmente.

## 5. Foto inicial e agendamento (prompt administrador no servidor)

```bat
cruzar_nf\SincronizarPlanilhaPortal.bat --gravar
schtasks /Create /TN "Maestro Sync Planilha Portal" /TR "\"C:\caminho\sync_nf\cruzar_nf\SincronizarPlanilhaPortal.bat\" --gravar --diario" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 12:30 /RI 10 /DU 05:30 /RU USUARIO /RP *
```

Substituir caminho e usuário reais antes de executar. A primeira gravação
só registra a foto; não copia pedidos antigos. Não apagar a foto depois.
Não usar `/K`: não interromper um Python no meio da gravação.

## 6. Dia seguinte

```powershell
Get-Content -LiteralPath "$codigoSync\logs\sync_planilha_portal.log" -Tail 100
```

No painel: data da última rodada, alterações realizadas, conflitos,
ambiguidades, exclusões preservadas e adiamento por Excel aberto. Até 18h
o Agendador tenta de novo; depois aguarda o próximo dia útil. Edições não
salvas no Excel só entram depois que a pessoa salvar.

## 7. Desfazer

```bat
schtasks /Change /TN "Maestro Sync Planilha Portal" /DISABLE
```

Esperar as travas sumirem. Restaurar o código do backup e reiniciar o
serviço pelo arquivo de reinício. Não restaurar Excel/JSON indiscriminadamente:
pode haver edições humanas posteriores. Para restaurar dados, fechar o Excel,
parar todos os escritores e comparar com o backup antes. Preservar a foto,
o cadastro e as operações pendentes para análise; não apagar estado para retentar.
