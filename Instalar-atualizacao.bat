@echo off
REM ======================================================================
REM  Cotafrete - LIGAR A ATUALIZACAO AUTOMATICA (rodar UMA vez, na VM)
REM
REM  Cria no Agendador de Tarefas do Windows a tarefa "Cotafrete -
REM  atualizar sozinho". A cada 5 minutos ela roda o atualizar.py desta
REM  pasta: se a main do GitHub tiver commit novo, espera as cotacoes em
REM  andamento terminarem, fecha o servidor, faz o git pull, o pip install
REM  (se o requirements.txt mudou) e abre o Servidor.bat de novo. Se ele nao
REM  subir, volta sozinho para a versao anterior.
REM
REM  Rode logado na conta que sobe o servidor (a do login automatico): a
REM  tarefa roda nessa conta, na area de trabalho dela - a Generoso e a
REM  Della Volpe precisam de navegador com janela.
REM
REM  O que acontecer fica em log\atualizar.log.
REM  Para desligar:  .venv\Scripts\python.exe atualizar.py --remover
REM ======================================================================
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  [ERRO] Falta .venv\Scripts\python.exe nesta pasta.
    echo.
    pause
    exit /b 1
)

.venv\Scripts\python.exe atualizar.py --instalar
echo.
pause
