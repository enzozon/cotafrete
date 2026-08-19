@echo off
REM ======================================================================
REM  Cotafrete - Monitor
REM  Duplo clique para acompanhar quem esta cotando e o que deu certo.
REM
REM  Abre o banco em SOMENTE LEITURA: pode ficar aberto o dia inteiro sem
REM  atrapalhar quem esta usando o sistema. Fechar esta janela nao desliga
REM  o Cotafrete - so para de olhar.
REM ======================================================================
title Cotafrete - Monitor

REM 65001 = UTF-8. O console do Windows abre em codepage 850, onde acento e
REM os separadores da tabela viram caixinha. PYTHONUTF8 sozinho nao resolve:
REM ele arruma a saida do Python, nao o que o console sabe desenhar.
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  [ERRO] Ambiente nao instalado nesta pasta.
    echo         Falta .venv\Scripts\python.exe
    echo.
    pause
    exit /b 1
)

REM %* repassa o que vier na linha de comando: Monitor.bat --dias 7
.venv\Scripts\python.exe monitorar.py %*

echo.
echo  O monitor parou.
pause
