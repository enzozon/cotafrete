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

REM ---------------------------------------------------------------------
REM  Porta ocupada e o erro mais provavel no dia a dia: uma janela anterior
REM  foi fechada de um jeito que deixou o python vivo, ou o servidor ja esta
REM  aberto em outra janela. Sem esta checagem o uvicorn morre com
REM  "[Errno 10048] ... apenas uma utilizacao de cada endereco de soquete",
REM  que nao diz a ninguem o que fazer.
REM ---------------------------------------------------------------------
set OCUPADA=
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"TCP.*:8000 .*LISTENING"') do set OCUPADA=%%p

if defined OCUPADA (
    echo.
    echo  A porta 8000 ja esta em uso pelo processo %OCUPADA%.
    echo  Provavelmente o Cotafrete ja esta aberto em outra janela.
    echo.
    choice /c SN /n /m "  Encerrar o processo %OCUPADA% e continuar? (S/N): "
    if errorlevel 2 (
        echo.
        echo  Cancelado. Se o sistema ja estiver aberto, use aquela janela:
        echo      http://localhost:8000
        echo.
        pause
        exit /b 0
    )
    taskkill /F /PID %OCUPADA% >nul 2>&1
    echo  Processo encerrado. Continuando...
    timeout /t 2 /nobreak >nul
)

echo.
echo  Iniciando o Cotafrete...
echo  Endereco: http://localhost:8000
echo.
echo  Para desligar: feche esta janela.
echo.

REM Abre o navegador alguns segundos depois, para o servidor ja estar de pe.
REM ping em vez de timeout: se houver Git Bash ou WSL no PATH, o timeout
REM deles ganha do timeout.exe do Windows e o navegador nunca abre.
start "" /b cmd /c "ping -n 5 127.0.0.1 >nul & start http://localhost:8000"

REM O uvicorn roda em PRIMEIRO PLANO, preso a esta janela: fechar a janela
REM mata o processo junto. Se rodasse em segundo plano, sobreviveria.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m uvicorn web.app:app --port 8000 --log-level warning

REM Se chegou aqui, o servidor caiu sozinho - mostra o motivo antes de sumir.
echo.
echo  O servidor parou.
pause
