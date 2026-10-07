@echo off
REM ======================================================================
REM  Maestro - leva os pedidos novos da planilha dos estagiarios para o
REM  portal (PEDIDOS.json). Agendador: a cada 10 minutos.
REM
REM  CadastrarPedidos.bat           grava (rodada normal)
REM  CadastrarPedidos.bat --previa  so mostra o que cadastraria
REM
REM  A primeira rodada com gravacao nao cadastra nada: so marca o que ja
REM  esta na planilha. Le o .env desta pasta (SYNC_NF_DADOS, SYNC_NF_PEDIDOS,
REM  CADASTRO_PLANILHA). Pode rodar com o gerenciador ligado.
REM  Log em logs\cadastro_pedidos.log (rodada sem mudanca nao escreve nada).
REM ======================================================================
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

pushd "%~dp0.."
if not exist logs mkdir logs

set GRAVAR=--gravar
if /i "%~1"=="--previa" set GRAVAR=

python -m cruzar_nf.cadastro_pedidos %GRAVAR% > logs\cadastro_pedidos.tmp 2>&1
set ERRO=%errorlevel%
for %%A in (logs\cadastro_pedidos.tmp) do if %%~zA gtr 0 (
    echo ==== %date% %time% ==== >> logs\cadastro_pedidos.log
    type logs\cadastro_pedidos.tmp >> logs\cadastro_pedidos.log
    type logs\cadastro_pedidos.tmp
)
del logs\cadastro_pedidos.tmp
if not "%ERRO%"=="0" echo  [ERRO] veja logs\cadastro_pedidos.log
popd
exit /b %ERRO%
