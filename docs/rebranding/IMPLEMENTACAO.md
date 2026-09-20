> **Validação final do coordenador:** 321 testes e 44 combinações visuais aprovados após as correções. Capturas e medições em `qa-comum/`; consumo e metodologia em [README.md](README.md). Os trechos abaixo sobre bloqueios e pendências descrevem etapas anteriores, já verificadas externamente.

# Cotafrete / Ventura — rebranding visual

Base preservada: `806f1ff6ca882235d9f12ed6fa543c6862a1ce43`. Sem commit, push, deploy, instalação de dependências ou alteração de configuração global. README original preservado.

## Direção visual

Editorial industrial, com azul Ventura, superfícies neutras claras e a paleta escura existente. A mudança inclui composição, escala tipográfica, densidade, alinhamento, navegação e acabamento, além das cores. Fontes locais: Segoe UI Variable/Segoe UI e Bahnschrift, com fallback sem download. As imagens Ventura e das transportadoras permanecem originais.

As entradas combinam uma área de apresentação marinha com formulário em superfície do tema escolhido. O SVG original representa conexões e volumes; não representa uma rota real ou indicador de desempenho. Traçado e volumes animam uma vez por 2,8 segundos. No celular, a apresentação se torna compacta. As telas operacionais não recebem hero grande.

Formulário em duas colunas no desktop, grupos de carga com largura integral, rótulos maiores e campos espaçados. Resultados mantêm comparação tabular e semântica dos estados; no celular, a tabela tem rolagem local e preserva inclusive a explicação dos valores. A ficha distingue rota, documentos e carga. Ajuda recebe ritmo de leitura e separação de seções; e-mail e Della Volpe usam o mesmo sistema de superfícies, cabeçalhos compactos e ações.

O dashboard recebeu navegação lateral refinada, navegação móvel que quebra linhas, cabeçalho com período explícito, indicadores agrupados com divisórias, gráficos com espaço próprio e tabelas com cabeçalhos destacados. Filtros, busca, detalhe de cotação e cartões de resposta seguem a mesma hierarquia. Os dados e cálculos dos gráficos não foram modificados.

## Referências reais consultadas

Consultadas na web em 14/09/2026, antes da implementação:

- [Flexport Platform](https://www.flexport.com/products/flexport-platform/): apresentação de uma plataforma logística unificada, seguida de visibilidade, controle e análise. Orientou a separação entre apresentação e trabalho operacional.
- [Flexport](https://www.flexport.com/): referência adicional de posicionamento corporativo para logística.
- [DHL Global Forwarding — portal digital](https://go.freightforwarding.dhl.com/Welcome-l-Unlock-True-Logistic-Value): jornada logística centralizada e comunicação B2B orientada à tarefa.
- [DHL Group — Global Forwarding](https://group.dhl.com/en/about-us/corporate-divisions/global-forwarding-freight.html): contexto multimodal e corporativo da referência.

Pesquisa via busca e leitura das páginas; não foi feita inspeção visual por screenshot dessas referências. Nenhum código, imagem, número comercial, cliente ou asset proprietário dessas empresas foi copiado. O SVG foi desenhado nesta implementação.

## Inventário anterior à edição e cobertura

Os renderizadores foram inventariados antes de editar. As três estruturas principais são `layout.entrada`, `layout.pagina` e `painel_ui.pagina_painel`. A ficha é compartilhada por `ficha_ui.ficha_da_cotacao`.

| Tela / rota | Renderizador | Tratamento |
| --- | --- | --- |
| GET `/login` | `app.tela_login` → `entrada` | Hero SVG, layout dividido, tema, rótulo associado ao campo, foco e salto ao formulário |
| GET `/adm/entrar` | `adm.tela_de_entrada` → `entrada` | Mesma direção, conteúdo administrativo e estado de senha inválida preservados |
| GET `/`, POST `/voltar` | `formulario`, `_render_formulario` | Cabeçalho compacto, formulário reorganizado, campos, tipo de frete e seleção de transportadoras preservados |
| POST `/cotar`, erros de validação | `cotar`, `tela_erro` | Estrutura e alertas compartilhados; validação, execução e redirecionamento intactos |
| GET `/cotacao/{id}` | `app.ver_cotacao`, `_linha_resultado` | Comparação de preços, estados, mensagens, imagens e ações preservados; rolagem acessível |
| Ficha dentro do resultado e detalhe adm | `ficha_da_cotacao`, `dado`, `parte` | Grupos contrastantes e valores mais legíveis, sem mudar formatação ou contas |
| GET `/historico` | `app.historico` | Tabela refinada com rolagem local e link real por cotação para teclado |
| GET `/documentacao` | `documentacao`, `pagina_documentacao` | Cabeçalho compacto, largura de leitura, etapas e seções |
| GET `/email/{id}/{slug}` | `preparar_email` | Texto pronto, destinatário, copiar e voltar; superfícies e tipografia revistas |
| GET `/dellavolpe/{id}` | `formulario_dellavolpe` | Instruções, bookmarklet e imagens existentes preservados; acabamento do fluxo assistido |
| GET `/whatsapp/{id}/{slug}` | `abrir_whatsapp` | É redirecionamento, sem página HTML própria. Cards de acesso no resultado recebem o novo desenho |
| `web/cotacao_whatsapp.html` | HTML/JS independente, sem rota FastAPI | Cabeçalho Cotafrete/Ventura, formulário, cards, responsividade, foco e tema pelo sistema operacional |
| GET `/adm` | `adm.painel`, `painel_ui.*` | Navegação, cabeçalhos, indicadores, períodos, filtros, tabelas, ranking, roscas e gráfico deliberadamente tratados |
| GET `/adm/cotacao/{id}` | `adm.ver_cotacao` | Estrutura administrativa, ficha, respostas, tempos, evidências e acessos preservados |

Endpoints operacionais preservados: POST `/login`, GET `/sair`, POST `/adm/entrar`, GET `/adm/sair`, GET `/adm/agora`, GET `/adm/cotacao/{id}/agora`, GET `/cotacao/{id}/evidencias.zip` e GET `/adm/cotacao/{id}/evidencias.zip`. Montagens `/marca`, `/logos` e `/ajuda` inalteradas. Endpoints auxiliares automáticos de FastAPI não foram redesenhados.

## Acessibilidade e movimento

- Rótulos associados nos dois logins e nome acessível para busca administrativa.
- Links de salto ao conteúdo, foco visível, link de cotação no histórico e regiões roláveis acessíveis ao teclado.
- Temas existentes preservados; entradas passam a oferecer o botão e a persistência de tema. O HTML WhatsApp avulso acompanha `prefers-color-scheme`.
- SVG decorativo oculto de tecnologias assistivas. Hero finito; brilho de espera limitado a duas execuções e spinner a cinco; ponto ao vivo administrativo estático. Os estados textuais continuam presentes.
- `prefers-reduced-motion` permanece global, inclusive no painel, e também está no HTML avulso.
- Não se esconde overflow do documento para mascarar problemas. Tabelas e gráficos podem rolar em seus próprios contêineres.

## Arquivos alterados

- `web/rebranding.css`: sistema visual compartilhado, entradas, vendedor e utilitários.
- `web/rebranding_painel.css`: desenho específico do dashboard e detalhe.
- `web/layout.py`: carregamento CSS, hero original, estruturas semânticas, tema da entrada e navegação ativa.
- `web/painel_ui.py`: carregamento CSS administrativo e regiões semânticas.
- `web/app.py`: rótulo de login, link por teclado no histórico e contêineres de rolagem.
- `web/adm.py`: rótulos acessíveis e regiões de tabela.
- `web/cotacao_whatsapp.html`: acabamento do documento independente.
- `docs/rebranding/validar.py`, `testes.ps1`, este documento e 11 HTMLs sintéticos gerados.
- `.gitignore`: exclusão dos bancos sintéticos temporários e diretórios transitórios do pytest; nenhum dado de teste deve entrar na entrega.

## Validação executada e limitações

1. `pytest tests/test_layout.py tests/test_painel_ui.py -q -p no:cacheprovider`: **100 testes passaram**. Incluem os testes existentes de contraste dos tokens, escaping, identidade, tema, movimento, componentes e gráficos. Nenhum teste existente foi enfraquecido ou editado.
2. `python docs/rebranding/validar.py --html-only`: **11 telas renderizadas com sucesso**, usando banco sintético exclusivo, sem ler `.env`, sem limpeza real de evidências e sem transportadoras. O script exige HTTP 200 em cada rota renderizada.
3. **321 testes da suíte comum externa passaram**, conforme informado pelo coordenador, antes do ajuste final de largura. As tentativas locais ampliadas haviam sido bloqueadas por permissões do sandbox Windows.
4. O QA externo em `qa-comum/results.json` registra **40 combinações de 10 telas × 2 larguras × 2 temas**, todas com HTTP 200, sem erros JavaScript nem animações longas com movimento reduzido. Antes do ajuste final, resultado e histórico mediam 836px e 774px no viewport de 390px; detalhe administrativo media 1453px em 1440px e 425px em 390px, nos dois temas. O JSON foi preservado. Playwright local permaneceu bloqueado pelo sandbox.
5. `git diff --check` sem erros de whitespace; avisos de conversão LF/CRLF do Git são do ambiente.

Ajuste final de largura: `.wrap` recebe largura explícita e mínimo zero para conter a largura intrínseca das tabelas nos respectivos contêineres roláveis. O cartão `.resposta.melhor` deixa de herdar o `nowrap` da célula de preço; textos longos podem quebrar, colunas da grade podem encolher e ações do cabeçalho podem mudar de linha. Nenhum `overflow` global foi ocultado e nenhum conteúdo foi cortado. **A nova medição externa de largura está pendente**; não foram repetidos Playwright nem a suíte completa no sandbox após esse ajuste.

O script `validar.py` permanece disponível para 44 combinações, incluindo o HTML WhatsApp avulso: verifica console, overflow, contraste de elementos centrais, foco, tema e movimento reduzido; gera JSON e capturas. O coordenador executará novamente o QA comum. Os HTMLs sintéticos podem ser regenerados com `--html-only`.

## Visualização local segura

Na raiz deste worktree, com o Python disponibilizado (nenhuma instalação):

```powershell
& C:/Users/vendas12/enzo/cotafrete-dev/.venv/Scripts/python.exe docs/rebranding/validar.py --serve
```

Abra `http://127.0.0.1:8765`. A prévia lista todos os HTMLs sintéticos e serve somente esses documentos e os assets existentes. Não recebe POST, não cota nem envia mensagens. Links de operação não devem ser usados como fluxo real nessa prévia. Ctrl+C encerra. Para apenas regenerar HTML, use `--html-only`; para capturas e verificações, execute sem argumento, em ambiente que permita iniciar Playwright.

Para a suíte pertinente seguida da verificação visual:

```powershell
powershell -ExecutionPolicy Bypass -File docs/rebranding/testes.ps1
```

Dados de execução ficam em `.tmp-rebranding/`; são sintéticos. Os HTMLs usam caminhos de assets a partir da raiz: use a prévia acima, não duplo clique no arquivo. O HTML WhatsApp legado pode conter URLs de imagens externas; a validação intercepta toda rede externa e não abre WhatsApp. Não foram iniciados adaptadores, e-mail ou WhatsApp reais.
