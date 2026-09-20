# Execute na raiz do worktree. Não instala dependências nem inicia integrações.
$ErrorActionPreference = 'Stop'
$env:PYTHON_DOTENV_DISABLED = '1'
$pythonRebranding = 'C:/Users/vendas12/enzo/cotafrete-dev/.venv/Scripts/python.exe'
$tempRebranding = Join-Path (Get-Location) ('.tmp-rebranding/suite-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force (Split-Path $tempRebranding) | Out-Null
& $pythonRebranding docs/rebranding/validar.py --tests tests/test_layout.py tests/test_painel_ui.py tests/test_adm_tela.py tests/test_adm_acesso.py tests/test_adm_cotacao.py tests/test_adm_script.py tests/test_web_cotacao.py tests/test_ficha.py tests/test_documentacao.py tests/test_dellavolpe_assistida.py tests/test_filtro.py tests/test_tipo_frete.py -q -p no:cacheprovider --basetemp=$tempRebranding
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonRebranding docs/rebranding/validar.py
exit $LASTEXITCODE
