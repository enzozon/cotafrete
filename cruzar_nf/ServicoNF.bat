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

REM pushd (e nao cd /d): funciona tambem quando a tarefa aponta para o caminho de rede
REM (mapeia uma letra temporaria; o cmd nao aceita UNC como pasta atual)
pushd "%~dp0.."

:rodar
python -m cruzar_nf.servico
set CODIGO=%errorlevel%
REM fica no log do servico: um problema que derruba o servico aparece la, nao so na janela
if not exist logs mkdir logs
echo %date% %time% ServicoNF.bat: o servico parou (codigo %CODIGO%); reiniciando em 30 s>> logs\servico_nf.log
echo.
echo  O servico de NF parou (codigo %CODIGO%). Reiniciando em 30 segundos (feche a janela para parar)...
ping -n 31 127.0.0.1 >nul
goto rodar
