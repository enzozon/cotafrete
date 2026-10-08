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
- Testes: `python -m pytest tests -q` (ou `-k <assunto>`).
