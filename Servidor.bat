@echo off
REM ======================================================================
REM  Cotafrete - SERVIDOR DA REDE
REM
REM  Roda em UMA maquina so. As outras da empresa acessam pelo navegador,
REM  no endereco que aparece abaixo. Ninguem mais precisa instalar nada.
REM
REM  Diferenca para o Cotafrete.bat: aquele escuta so em 127.0.0.1, ou
REM  seja, so a propria maquina enxerga. Este escuta em 0.0.0.0 - TODAS as
REM  placas de rede desta maquina.
REM
REM  ATENCAO: 0.0.0.0 inclui o Wi-Fi. Se esta maquina estiver tambem numa
REM  rede de visitantes, quem estiver nela alcanca o sistema. Nao ha senha.
REM
REM  FECHAR ESTA JANELA DESLIGA O SISTEMA PARA TODO MUNDO.
REM ======================================================================
title Cotafrete SERVIDOR - NAO FECHE (fechar desliga para a empresa toda)

chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

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
REM  Porta ocupada: quase sempre e o proprio Cotafrete ja aberto em outra
REM  janela. Sem esta checagem o uvicorn morre com "[Errno 10048] apenas
REM  uma utilizacao de cada endereco de soquete", que nao diz a ninguem o
REM  que fazer.
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
        echo  Cancelado.
        echo.
        pause
        exit /b 0
    )
    taskkill /F /PID %OCUPADA% >nul 2>&1
    echo  Processo encerrado. Continuando...
    timeout /t 2 /nobreak >nul
)

REM ---------------------------------------------------------------------
REM  Descobre o IP desta maquina na rede, para mostrar na tela. E o endereco
REM  que os funcionarios digitam. Sem isto, alguem teria que rodar ipconfig
REM  e adivinhar qual das linhas e a certa.
REM ---------------------------------------------------------------------
set IP=
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    if not defined IP set IP=%%a
)
set IP=%IP: =%

echo.
echo  ====================================================================
echo   COTAFRETE - servidor da rede
echo  ====================================================================
echo.
if defined IP (
    echo   Os funcionarios acessam por:    http://%IP%:8000
) else (
    echo   [aviso] Nao consegui descobrir o IP. Rode ipconfig e use o
    echo           endereco IPv4 desta maquina, com :8000 no fim.
)
echo   Nesta maquina tambem funciona:  http://localhost:8000
echo.
echo   Para desligar: feche esta janela.
echo  ====================================================================
echo.

REM --host 0.0.0.0 e o que faz a diferenca: sem isso, so esta maquina enxerga.
REM
REM Sem --reload de proposito. O reload reinicia o servidor a cada arquivo
REM salvo, e um reinicio no meio de uma cotacao mata as threads das
REM transportadoras - o cartao fica "cotando..." para sempre. Desenvolvimento
REM se faz na OUTRA pasta.
.venv\Scripts\python.exe -m uvicorn web.app:app --host 0.0.0.0 --port 8000 --log-level warning

echo.
echo  O servidor parou.
pause
