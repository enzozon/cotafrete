@echo off
REM ======================================================================
REM  Cotafrete - Ventura
REM  Duplo clique aqui para abrir o sistema.
REM
REM  FECHAR ESTA JANELA DESLIGA O SERVIDOR. E de proposito: sem isso o
REM  python fica rodando escondido, segurando a porta 8000, e o proximo
REM  duplo clique falha com "endereco ja em uso" sem dizer o porque.
REM ======================================================================
title Cotafrete - NAO FECHE (fechar desliga o sistema)
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  [ERRO] Ambiente nao instalado nesta pasta.
    echo         Falta .venv\Scripts\python.exe
    echo.
    echo  Rode uma vez, neste diretorio:
    echo      python -m venv .venv
    echo      .venv\Scripts\activate
    echo      pip install -r requirements.txt
    echo      python -m playwright install chromium
    echo.
    pause
    exit /b 1
)

echo.
echo  Iniciando o Cotafrete...
echo  Endereco: http://localhost:8000
echo.
echo  Para desligar: feche esta janela.
echo.

REM Abre o navegador alguns segundos depois, para o servidor ja estar de pe.
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8000"

REM O uvicorn roda em PRIMEIRO PLANO, preso a esta janela: fechar a janela
REM mata o processo junto. Se rodasse em segundo plano, sobreviveria.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m uvicorn web.app:app --port 8000 --log-level warning

REM Se chegou aqui, o servidor caiu sozinho - mostra o motivo antes de sumir.
echo.
echo  O servidor parou.
pause
