# Cotafrete / Ventura: instruções para o Claude

Antes de abrir código, leia:
- `docs/MAPA_DO_SISTEMA.md`: sistemas, partes frágeis e onde mexer.
- `docs/SERVIDOR.md`: produção. O Claude prepara e o Enzo executa no
  servidor.

Regras:
- Código em `cruzar_nf/` roda no Server 2012 R2 e precisa ser compatível com
  Python 3.8.
- Não leia arquivos de dados inteiros (PEDIDOS.json, vendas_hse.json, logs,
  tests/fixtures). Filtre o trecho que importa.
- Mudou uma parte descrita no mapa? Atualize o mapa no mesmo PR.
- Testes no dia a dia: `python -m pytest tests -q -m "not navegador"`.
  Mexeu numa transportadora: isso e `-k <transportadora>`. A marcação
  `navegador` (playwright/uvicorn) é automática, pelo `tests/conftest.py`.
- Suíte completa (`python -m pytest tests -q`): sempre em segundo plano
  (run_in_background), nunca dividida em partes. Leva mais que os 10 min do
  comando em primeiro plano.
- Em paralelo: `pip install pytest-xdist` e `python -m pytest tests -q -n 4`.
  A CI (`.github/workflows/testes.yml`) roda assim em Windows/3.14, e o
  `cruzar_nf` em série no 3.8; o merge na `main` só libera com ela verde.
