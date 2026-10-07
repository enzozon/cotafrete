@echo off
REM ======================================================================
REM  Cruzamento de NF - PEDIDOS.json x comparar.json
REM  Duplo clique: le os dois arquivos da pasta cruzar_nf\entrada e grava
REM  PEDIDOS_ATUALIZADO.json + RELATORIO_NF.md + RELATORIO_NF.json ali mesmo.
REM
REM  Outra pasta: CruzarNF.bat --pasta C:\planilhas
REM  O PEDIDOS.json original nunca e alterado.
REM ======================================================================
title Cruzamento de NF

chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

if "%~1"=="" (
    if not exist "cruzar_nf\entrada" mkdir "cruzar_nf\entrada"
    "%PY%" -m cruzar_nf --pasta cruzar_nf\entrada
) else (
    "%PY%" -m cruzar_nf %*
)

echo.
pause
