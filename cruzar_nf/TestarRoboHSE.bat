@echo off
REM ======================================================================
REM  Teste do robo do HSE (nao grava nada no Maestro)
REM  Usa HSE_USUARIO e HSE_SENHA do .env da pasta acima desta, exporta as
REM  vendas dos ultimos 2 dias e mostra o resumo do Excel baixado.
REM  Outro periodo: TestarRoboHSE.bat --de 29/09/2026 --ate 01/10/2026
REM ======================================================================
title Teste do robo do HSE
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
python -m cruzar_nf.hse_robo %*
echo.
pause
