@echo off
REM ======================================================================
REM  Maestro - grava as NFs do HSE no PEDIDOS.json (Agendador: 3x por dia)
REM
REM  SincronizarNF.bat                          grava (rodada normal)
REM  SincronizarNF.bat --previa                 so mostra o que gravaria
REM  SincronizarNF.bat --previa --de 01/01/2025 primeira carga, sem gravar
REM
REM  Le o .env desta pasta (HSE_USUARIO, HSE_SENHA, SYNC_NF_DADOS...).
REM  Pode rodar com o gerenciador ligado. Log em logs\sync_nf.log.
REM ======================================================================
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

pushd "%~dp0.."
if not exist logs mkdir logs

set GRAVAR=--gravar
if /i "%~1"=="--previa" (
    set GRAVAR=
    shift
)

echo ==== %date% %time% ==== >> logs\sync_nf.log
python -m cruzar_nf.sincronizar --robo %GRAVAR% %1 %2 %3 %4 >> logs\sync_nf.log 2>&1
set ERRO=%errorlevel%
if not "%ERRO%"=="0" echo  [ERRO] veja logs\sync_nf.log
popd
exit /b %ERRO%
