@echo off
REM ======================================================================
REM  Maestro - Servico de NF (HSE -> PEDIDOS.json)
REM  Fica na pasta cruzar_nf, ao lado do gerenciador.py. Le o .env da pasta
REM  do gerenciador (SYNC_NF_TOKEN, HSE_USUARIO, HSE_SENHA...).
REM
REM  Nao mexe no gerenciador: os dois rodam juntos. Fechar esta janela para
REM  o servico; ele volta sozinho se cair (espera 30 s e reinicia).
REM ======================================================================
title Maestro - Servico de NF
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0.."

:rodar
python -m cruzar_nf.servico
echo.
echo  O servico de NF parou. Reiniciando em 30 segundos (feche a janela para parar)...
timeout /t 30 /nobreak >nul
goto rodar
