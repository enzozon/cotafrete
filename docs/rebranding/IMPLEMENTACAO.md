> **Validação final do coordenador:** 321 testes e 44 combinações visuais aprovados após as correções. Capturas e medições em `qa-comum/`; consumo e metodologia em [README.md](README.md). Os trechos abaixo sobre bloqueios e pendências descrevem etapas anteriores, já verificadas externamente.

# Rebranding Cotafrete / Ventura

Base preservada: `806f1ff`. Implementação de apresentação, sem dependências novas, commits, push ou deploy. README, logos, endpoints, autenticação, cookies, cálculos e integrações preservados.

## Direção e referências

Identidade corporativa em azul Ventura e marinho, títulos amplos, espaçamento mais generoso, superfícies discretas e hierarquia operacional. Os logins recebem uma malha logística SVG original, animada uma única vez por quatro segundos e estática com `prefers-reduced-motion`. As demais telas mantêm cabeçalhos compactos. Fontes locais do sistema, sem CDN.

Referências consultadas na pesquisa desta sessão:

- [Maersk — Logistics Services & Solutions](https://www.maersk.com/logistics-solutions): organização de serviços e comunicação de uma cadeia integrada, inspiração para a composição de rotas.
- [DHL — Supply Chain](https://www.dhl.com/us-en/home/supply-chain.html): hierarquia de informação e apresentação corporativa de logística B2B.

Nenhum código, fotografia ou asset das referências foi copiado; não foram acrescentados clientes ou indicadores comerciais fictícios ao produto.

## Inventário e cobertura

Rotas, renderizadores e chamadores foram inventariados antes das alterações.

| Tela / rota | Renderizador | Tratamento |
| --- | --- | --- |
| Vendedor `/login` | `app.tela_login` → `layout.entrada` | Hero SVG, composição em duas áreas, rótulo de campo, tema |
| Administrador `/adm/entrar` | `adm.tela_de_entrada` → `layout.entrada` | Mesmo hero, formulário de senha e aviso de erro |
| Cotação `/`, repetição `/?repetir=…`, retorno `/voltar`, erros de `/cotar` | `app._render_formulario`, `tela_erro` → `layout.pagina` | Grade de formulário, seções, campos, seleção de transportadoras |
| Resultados `/cotacao/{id}` | `app.ver_cotacao` | Comparação, estados, ações e tabela com rolagem local acessível |
| Ficha dentro dos resultados e detalhe administrativo | `ficha_ui.ficha_da_cotacao` | Grade de dados, hierarquia de rótulos e valores; cálculos intactos |
| Histórico `/historico` | `app.historico` | Tabela com rolagem local, link de cotação acessível por teclado |
| Ajuda `/documentacao` | `app.pagina_documentacao` | Tipografia de leitura, divisões e destaque dos passos |
| E-mail `/email/{id}/{slug}` | `app.preparar_email` | Cabeçalho compacto, ações e área de mensagem |
| Della Volpe `/dellavolpe/{id}` | `app.formulario_dellavolpe` | Instruções, imagens contidas e ampliação por teclado |
| WhatsApp `/whatsapp/{id}/{slug}` | `app.abrir_whatsapp` | Redirecionamento existente preservado; cartões de acesso nos resultados |
| WhatsApp avulso `web/cotacao_whatsapp.html` | HTML legado, sem rota no aplicativo | Grade responsiva, cores, foco e tema conforme sistema |
| Dashboard `/adm` | `adm.painel` → `painel_ui.pagina_painel` | Navegação lateral, cabeçalho, indicadores, filtros, tabelas e gráficos SVG |
| Detalhe `/adm/cotacao/{id}` | `adm.ver_cotacao` → `painel_ui.pagina_painel` | Cabeçalho de ações, preços, respostas, ficha e tempos |
| Cotação ausente / erro | Cascos compartilhados | Mesma identidade, status e mensagens existentes |

Rotas de atualização `/adm/agora`, `/adm/cotacao/{id}/agora`, downloads de evidências, POSTs de autenticação/cotação e saídas permanecem com suas operações existentes. Fragmentos atualizados recebem o mesmo CSS.

## Arquivos alterados

- `web/rebranding.css`: apresentação compartilhada, variantes operacionais e responsividade.
- `web/layout.py`: integração do CSS, SVG original, tema no login, regiões principais, salto de navegação, ampliação por teclado e escopo de estilo do histórico.
- `web/painel_ui.py`: integração visual do painel e região de gráfico acessível.
- `web/app.py`: rótulo do login, link do histórico, foco nas imagens de ajuda e tabela de resultados.
- `web/adm.py`: rótulos acessíveis de senha e busca.
- `web/cotacao_whatsapp.html`: acabamento da página avulsa.
- `docs/rebranding/validar.py` e `.gitignore`: prévia sintética e validação executável, com dados descartáveis em `.runtime/`.

## Validação e ajuste final de largura

- Local: 37 testes existentes de `tests/test_layout.py` passaram; houve aviso de permissão ao gravar cache. Smoke de 11 telas passou com HTTP 200 e pt-BR.
- A suíte completa no sandbox foi interrompida após erros de permissão. Playwright foi bloqueado por `PermissionError` ao criar subprocesso; tentativa de execução ampliada rejeitada. Não foram geradas capturas locais por esse roteiro.
- Coordenador informou **321 testes aprovados** na suíte comum externa.
- Medições externas em `qa-comum/results.json`: **40 combinações** (10 telas × 390/1440px × claro/escuro), todas com HTTP 200, um `main`, nenhum erro JavaScript e nenhuma animação longa com movimento reduzido.
- Antes do ajuste final, somente o detalhe administrativo excedia a janela: **1449/1440px** e **427/390px**, nos dois temas. Resultados e histórico não apresentavam overflow nessas medições.
- Correção: `white-space:nowrap` do melhor preço passou a valer apenas para `td.melhor`, evitando atingir o cartão `.resposta.melhor`; ações do cabeçalho agora permitem quebra e encolhimento; colunas do painel usam mínimo zero e cartões de resposta respeitam a largura disponível. Textos longos podem quebrar. Não se aplicou ocultação global de overflow nem corte de conteúdo.
- **A medição externa posterior ao ajuste de largura está pendente**, por orientação do coordenador. O JSON original não foi alterado; os resultados acima não são alegação de validação do patch final.

## Visualização e verificações reproduzíveis

No worktree atual, em PowerShell:

```powershell
$py = 'C:/Users/vendas12/enzo/cotafrete-dev/.venv/Scripts/python.exe'
& $py docs/rebranding/validar.py --serve
# http://127.0.0.1:8012/login — / — /adm — /cotacao/1 — /adm/cotacao/1
# Página avulsa: /whatsapp-avulso
```

A prévia desativa leitura de `.env` e limpeza de evidências durante a importação, usa apenas banco sintético e bloqueia POSTs e rotas fora da lista de visualização. Não inicia transportadoras nem envia mensagens.

```powershell
& $py docs/rebranding/validar.py --smoke
& $py docs/rebranding/validar.py --tests
& $py docs/rebranding/validar.py --tests tests/test_layout.py -q
& $py docs/rebranding/validar.py --capture
```

`--capture` está preparado para 11 telas em dois tamanhos e dois temas, incluindo login, formulário e dashboard. Grava PNGs em `docs/rebranding/`, verifica overflow, erros de console/JavaScript, foco e movimento reduzido, e produz `validacao-visual.json` ao concluir. Depende de Playwright/Chromium executável fora do bloqueio observado; não instala dependências. A verificação comum do coordenador permanece independente desse roteiro.
