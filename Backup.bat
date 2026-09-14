@echo off
REM ======================================================================
REM  Cotafrete - Backup do banco
REM
REM  Duplo clique para fazer uma copia agora. Tambem e o que o Agendador de
REM  Tarefas do Windows chama todo dia - ver docs\CONFIGURAR_NA_EMPRESA.md.
REM
REM  NAO precisa parar o servidor. A copia usa a API de backup do SQLite,
REM  que se entende com quem esta escrevendo e le atraves do WAL. Copiar o
REM  arquivo na mao NAO serve: em WAL o .db sozinho esta atrasado, e a copia
REM  sai sem as cotacoes mais recentes - sem erro nenhum, so descoberto no
REM  dia de restaurar. Ver core\backup.py.
REM
REM  ONDE A COPIA CAI: na variavel COTAFRETE_BACKUP_DIR, se existir; senao
REM  em backup\, aqui do lado. O certo e apontar para FORA da VM (um
REM  compartilhamento de rede, um disco externo) - copia no mesmo disco nao
REM  protege contra o disco morrer. O proprio script avisa quando e o caso.
REM ======================================================================
title Cotafrete - Backup

REM 65001 = UTF-8, mesmo motivo do Monitor.bat: o console abre em codepage
REM 850 e acento vira caixinha.
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

echo.
echo  ====================================================================
echo   COTAFRETE - copia de seguranca do banco
echo  ====================================================================
echo.

.venv\Scripts\python.exe -m core.backup
set RESULTADO=%ERRORLEVEL%

echo.
if %RESULTADO% NEQ 0 (
    echo  ####################################################################
    echo   O BACKUP FALHOU. O historico continua sem copia de hoje.
    echo  ####################################################################
) else (
    echo   Backup concluido.
)
echo.

REM /auto: sem pausa, para o Agendador de Tarefas nao deixar uma janela
REM aberta esperando tecla que ninguem vai apertar. No duplo clique a pausa
REM fica, senao a janela some antes de alguem ler o resultado.
if /i "%~1"=="/auto" exit /b %RESULTADO%
pause
exit /b %RESULTADO%
