@echo off
REM ======================================================================
REM  Maestro - reinicia o Servico de NF (use depois de atualizar o codigo)
REM
REM  O schtasks /End fecha so o cmd: o python do servico continuava rodando
REM  e cada /Run subia mais um. Este arquivo para a tarefa, encerra TODOS
REM  os servicos de NF que sobraram e inicia um so. Nao interrompe uma
REM  sincronizacao em andamento. Rodar como Administrador.
REM ======================================================================
chcp 65001 >nul
setlocal
set TAREFA=Maestro NF Servico

pushd "%~dp0.."
set DADOS=\SERVIDOR2\Publico\ALLAN\database\sync_nf
if exist ".env" for /f "usebackq tokens=1,* delims==" %%a in (".env") do if /i "%%a"=="SYNC_NF_DADOS" set "DADOS=%%b"
popd

REM sync_nf.trava: sincronizacao de NF; nf_planilha.trava: gravando a NF na planilha
for %%t in (sync_nf.trava nf_planilha.trava) do if exist "%DADOS%\%%t" (
    echo.
    echo  O servico de NF esta trabalhando agora ^(%%t^). Espere terminar e rode de novo.
    echo  ^(Se continuar assim por mais de 2 horas, apague %DADOS%\%%t^)
    exit /b 1
)

echo  Parando a tarefa "%TAREFA%"...
schtasks /End /TN "%TAREFA%" >nul 2>&1

echo  Encerrando os servicos de NF que ficaram rodando...
set FILTRO=not commandline like '%%wmic%%' and not commandline like '%%Reiniciar%%'
wmic process where "commandline like '%%ServicoNF.bat%%' and %FILTRO%" call terminate >nul 2>&1
wmic process where "commandline like '%%cruzar_nf.servico%%' and %FILTRO%" call terminate >nul 2>&1
ping -n 4 127.0.0.1 >nul

wmic process where "commandline like '%%cruzar_nf.servico%%' and %FILTRO%" get processid 2>nul | findstr /r "[0-9]" >nul
if not errorlevel 1 (
    echo  [ERRO] Ainda tem servico de NF rodando. Rode este arquivo como Administrador.
    exit /b 1
)

echo  Iniciando um servico so...
schtasks /Run /TN "%TAREFA%"
