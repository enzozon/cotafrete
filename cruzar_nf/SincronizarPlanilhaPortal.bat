@echo off
REM Previa por padrao. --gravar autoriza escrita; --diario limita a janela 12:30-18h.
REM Agendador proprio, como Cadastro Pedidos. Nunca troca SYNC_NF_DADOS.
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
pushd "%~dp0.."
if not exist logs mkdir logs
set "LOGTEMP=logs\sync_planilha_%RANDOM%_%RANDOM%.tmp"
python -m cruzar_nf.sync_planilha_portal %* > "%LOGTEMP%" 2>&1
set ERRO=%errorlevel%
for %%A in ("%LOGTEMP%") do if %%~zA gtr 0 (
    echo ==== %date% %time% ==== >> logs\sync_planilha_portal.log
    type "%LOGTEMP%" >> logs\sync_planilha_portal.log
    type "%LOGTEMP%"
)
del "%LOGTEMP%"
popd
exit /b %ERRO%
