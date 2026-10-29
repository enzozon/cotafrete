# DAV: experiência executiva para administração e vendedor

Data: 29/10/2026. Estado: aprovado por Enzo na conversa; não é plano de implementação.

## Intenção e aprovação recebida

Enzo quer tornar a operação de orçamentos DAV compreensível: acompanhar a geração,
encontrar os erros na própria listagem e saber o que fazer depois. As referências
são as telas enviadas pelo usuário e o visual administrativo existente da Ventura.

Na conversa, Enzo aprovou as oito recomendações apresentadas:

1. Cobrir envio, conferência, fila, processamento, resultado, detalhes e histórico,
   para vendedor e administrador.
2. Ter resumo de falhas no `/adm` e diagnóstico completo em `/adm/dav`.
3. Usar o modelo executivo do piloto, temas claro/escuro e animações discretas.
4. Mostrar motivo, etapa conhecida e orientação, com relatório original expansível.
5. Mostrar aviso financeiro ao vendedor, reservando títulos, valores e vencimentos
   da pendência financeira ao administrador.
6. Corrigir pela planilha e reenviar; conferir no HSE primeiro nos casos incertos.
7. Relacionar a tentativa que falhou ao envio posterior que resolveu o problema,
   apenas quando o vínculo puder ser confirmado com segurança.
8. Registrar também rejeições de arquivo/validação, separadas das falhas no HSE.

As definições mais específicas abaixo são escolhas propostas pelo Codex para
completar esse desenho, não decisões que o usuário já tomou individualmente.

## Referências e realidade técnica

- O checkout atual `cotafrete-dev`, em `main`, não contém a funcionalidade DAV.
  O código foi localizado na branch `feat/dav-frete-descricao-item`, no worktree
  `C:/Users/vendas12/enzo/cotafrete-sincronizacao`. Na conferência para o plano,
  esse worktree já estava na branch `fix/dav-busca-produto-longa`, commit `382b27c`.
  A referência anterior registra a descoberta inicial, não a base atual de execução.
  Não trocar branches nem misturar
  alterações dessa outra área durante esta etapa de desenho.
- `web/dav_ui.py` contém envio, conferência, geração, detalhes e PDF.
- `/adm/dav`, em `web/adm.py`, usa hoje a moldura do vendedor. A moldura própria
  de administração já existe em `web/painel_ui.py`, incluindo a sidebar.
- `web/adm_me.py` oferece referência de indicadores, atenção, filtros e histórico.
- `web/layout.py` oferece marca, temas, tipografia e estilos compartilhados.
- Os registros DAV guardam usuário, arquivo, cliente, número, estado, PDF, erro,
  relatório e horários. Algumas falhas estão somente no relatório; o campo
  `erro` não é fonte suficiente para montar o diagnóstico.
- Não existem hoje categorias confiáveis de falha, avisos estruturados, eventos
  detalhados de progresso ou vínculo entre reenvios.
- As listas atuais têm limites de registros. Indicadores devem consultar todo o
  período selecionado, independentemente da paginação.

O piloto é um estudo descartável, com dados fictícios e ações locais. Não deve
ser incorporado como código do produto. A prévia de conferência nele é resumida;
a tela real deve preservar todos os dados hoje disponíveis para revisão.

## Identidade e comportamento visual

Reutilizar o visual executivo da Ventura: azul da marca, superfícies azul-marinho
no escuro, superfícies claras no claro, Segoe local e números alinhados. A sidebar
administrativa ganha o item **Orçamentos DAV**, ativo nas páginas administrativas
do módulo. O vendedor mantém a navegação superior existente.

O modelo executivo é o padrão. A comparação compacta no piloto serve para avaliar
densidade; não obriga a criar uma preferência adicional de densidade no produto.
Reutilizar a preferência de tema já existente, sem outro seletor de tema paralelo.

Entradas e transições curtas; destacar apenas dados que mudaram nas atualizações.
Não repetir animações de todos os cartões a cada consulta. Respeitar
`prefers-reduced-motion`, navegação por teclado, foco visível e alvos de toque.
Cor sempre acompanhada de texto/ícone. Mensagens longas quebram linha; tabelas podem
rolar horizontalmente no celular sem fazer a página inteira transbordar.

## Telas

### Administração: `/adm/dav`

Cabeçalho com título, descrição curta e período. Primeira versão com Hoje,
últimos 7 dias e últimos 30 dias, segundo o horário operacional de Brasília.
Padrão: Hoje. Busca por cliente, vendedor, nome do arquivo ou número do orçamento;
filtro por resultado e por vendedor. Paginação explícita.

Indicadores do período:

- Tentativas de geração enviadas ao HSE: excluem rascunhos, simulações e arquivos
  rejeitados antes da geração. Cada tentativa conta uma vez.
- Criados: registros prontos, incluindo os que têm aviso; explicitar o subconjunto
  com aviso quando disponível.
- Falhas: estado de erro, sem misturar resultados incertos.
- Em andamento: fila e geração, com subtotais quando útil.
- Faixa de atenção própria para resultados incertos e rejeições de planilha.

Não apresentar esses números como clientes únicos, vendas ou orçamentos comerciais
únicos. Reenvios são novas tentativas e a repetição deve ser identificável.
Simulações e conferências são consultáveis pelo filtro, sem contaminar os totais
de produção. Informar o alcance do filtro e não esconder resultados desconhecidos.

Lista com horário, vendedor, cliente, arquivo, orçamento quando existente, resultado,
motivo resumido e ação. Erro visível na linha, não apenas depois de abrir o detalhe.
Aviso resumido em linha separada do erro. Ação PDF somente quando disponível.

Bloco de atenção agrupa falhas por motivo reconhecido, com quantidade e acesso ao
recorte correspondente. Mostrar as últimas ocorrências e se há reenvio confirmado
que resolveu uma delas. Resultados incertos têm tratamento próprio, mais urgente
que um gráfico de frequência. Sem ranking de desempenho dos vendedores.

### Painel principal: `/adm`

Adicionar um resumo compacto e identificado como DAV, sem misturar as estatísticas
de frete: quantidade de falhas, de resultados incertos e de rejeições de planilha
no período apresentado pelo bloco. Link para `/adm/dav` com o recorte equivalente.
Não alterar o significado dos indicadores de frete existentes.

### Vendedor: `/dav`

Upload destacado, modelo v3 para download e limites atuais (.xlsx, até 5 MB).
Arquivo selecionado visível, mensagens de validação próximas ao campo e ação
principal **Conferir planilha**. Evitar cliques repetidos durante o envio.

Histórico pessoal com busca, período, resultado e motivo resumido. Acesso somente
aos próprios registros e PDFs. Incluir rejeições recentes, claramente diferenciadas
das tentativas de geração. Nenhum indicador dos demais vendedores.

### Conferência

Cliente, vendedor, filial, pagamento/parcelamento, prazo, OC, observações e itens
com quantidade, valor unitário e código HSE, preservando o que já existe.
Mostrar local de entrega quando disponível e os avisos reais da leitura.
Destacar dados pendentes e a ação necessária, sem inventar campos ou preenchimentos.
Voltar para corrigir o arquivo ou confirmar a geração. A confirmação existente
continua sendo o limite entre revisar e escrever no HSE.

Sem edição de produtos, preços, endereços ou dados financeiros dentro do site.
Não remover validação, deduplicação ou confirmação atuais para simplificar a tela.

### Fila e processamento

Mostrar **Na fila** ou **Gerando no HSE**, último horário de atualização e os dados
da tentativa. Posição na fila somente se calculada sobre a fila completa.
Não inventar porcentagem, estimativa de conclusão ou etapas de automação que o
processador não registra. Não oferecer cancelamento nesta versão.

Atualizar o conteúdo mantendo filtros e foco. Proposta: aproveitar a cadência
atual de aproximadamente 5 segundos, sem recarregar a página inteira. Ao perder
atualização, mostrar que os dados podem estar desatualizados; preservar a última
resposta válida e oferecer nova consulta. Não disparar outro orçamento ao atualizar.

### Resultado e detalhe

| Resultado real | Apresentação | Ação principal |
|---|---|---|
| `rascunho` | Conferência pendente | Conferir antes de gerar |
| `fila` | Na fila | Acompanhar |
| `gerando` | Gerando no HSE | Acompanhar |
| `pronto` | DAV criado; com aviso se houver | Baixar PDF disponível |
| `erro` | Falha registrada; motivo real | Corrigir a planilha quando aplicável |
| `incerto` | Confira no HSE; o orçamento pode existir | Conferir no HSE antes de novo envio |
| `simulado` | Simulação; nada salvo | Consultar resultado da simulação |
| rejeição prévia | Planilha não aceita; não enviada ao HSE | Corrigir o arquivo |

**Pronto:** número do orçamento, PDF, resumo de cliente/itens quando disponível,
avisos separados e detalhes do processamento conhecidos. Sem transformar relato
textual incompleto em linha do tempo supostamente medida.

**Erro:** motivo em linguagem direta, trecho que o sustenta, etapa apenas se
conhecida, orientação e relatório expansível. Não afirmar genericamente “não foi
criado” se o registro não comprovar isso. Exemplo confirmado nos prints: endereço
de entrega não encontrado, separadamente do aviso de pendência financeira.
Botão de copiar diagnóstico com conteúdo permitido ao perfil.

**Incerto:** mensagem explícita de que o orçamento pode existir; mostrar o número
se conhecido e orientar a busca no HSE. Sem botão de repetir, gerar de novo ou
reenvio associado nessa tela. A mudança visual não resolve nem oculta a incerteza.

O administrador abre detalhes com a moldura administrativa e retorno ao recorte
de origem. O vendedor abre com a moldura e o retorno próprios. As URLs técnicas
para isso ficam para o planejamento, preservando links existentes e suas permissões.

## Diagnóstico e dados financeiros

Adotar interpretação determinística dos campos e relatórios reais. Guardar a
mensagem original administrativa e apresentar resumo compreensível com categoria
somente quando reconhecida. Sem classificação ou correção automática por IA.

Priorizar o campo de erro e a seção de erros do relatório, conciliando ambos sem
perder informações. Um aviso de “cliente bloqueado/pendência financeira” pode
coexistir com orçamento pronto: ele não determina que a criação falhou.
Mensagem desconhecida recebe motivo disponível ou “Motivo não identificado;
consulte os detalhes”, nunca causa fabricada.

O vendedor vê a existência da pendência financeira e orientação para consultar
o financeiro; não vê títulos, valores ou vencimentos da dívida. Isso também vale
para relatório expansível, diagnóstico copiado, busca, respostas de atualização
e HTML entregue. A restrição deve acontecer no servidor, não com conteúdo oculto
na tela. Se não for possível separar um trecho financeiro com segurança, omitir
esse trecho para o vendedor e informar a restrição. O administrador autorizado
mantém acesso ao relatório completo, com escape de conteúdo.

Valores comerciais do próprio orçamento continuam na conferência. A restrição
de valores refere-se à dívida/pendência financeira, não ao preço dos produtos.
PDFs comerciais existentes seguem o acesso atual do proprietário/administrador;
não há alteração ou sanitização de PDFs nesta proposta.

Para registros antigos, extrair o que o relatório permitir com segurança. Ausência
de dados estruturados não equivale a ausência de avisos ou sucesso. Quando não
for possível determinar a existência de aviso, não exibir uma contagem falsa de zero.

## Rejeições e relação entre tentativas

Registrar rejeições autenticadas na validação de extensão, tamanho, leitura e
estrutura da planilha, com data, proprietário, nome seguro do arquivo e motivo.
Não guardar o conteúdo integral do arquivo inválido só para alimentar o dashboard.
Sem cliente conhecido, mostrar “Cliente não identificado”. Não criar registros
para requisições não autenticadas nem prometer rastrear rejeições de infraestrutura
que ocorram antes de a aplicação receber a requisição.

Rejeições têm natureza própria; não fingir que o robô foi executado. Os registros
novos passam a ser acompanhados após a entrega; não fabricar histórico retroativo.

Proposta mínima de vínculo seguro: **Enviar planilha corrigida**, a partir de
uma tentativa com erro ou rejeição, abre um envio que referencia explicitamente
a tentativa anterior. Validar no servidor o proprietário da origem. Um ADM pode
consultar todos os vínculos, mas não assume a identidade do vendedor para reenviar.
Cada geração nova continua passando pela conferência e pela deduplicação.

Uma falha só recebe indicação **Resolvida por novo envio** quando o descendente
explicitamente vinculado ficar pronto. Em conferência, fila, erro ou incerto,
não marcar resolvida. Se a nova planilha já corresponder a DAV pronto e a
deduplicação o identificar, mostrar esse resultado existente, sem gerar duplicado.
Associar esse resultado à origem somente quando o proprietário coincidir e o
vínculo tiver sido informado pelo fluxo de correção.

Preservar estados, relatórios e contagens históricas: “resolvida” é contexto,
não troca do erro antigo para sucesso. Reenvios antigos sem referência explícita
ficam sem vínculo; não inferir por nome de arquivo, cliente ou proximidade de horário.
Uma cadeia de correções pode ter mais de uma falha até chegar a um DAV pronto.

## Estados de interface e limites

Prever primeira utilização sem dados, nenhum resultado para o filtro, consulta
em andamento, falha de atualização, sessão expirada e registro/PDF inexistente.
Não exibir zero quando a consulta falhou. Estados ou mensagens não reconhecidos
continuam visíveis, com diagnóstico limitado ao que se sabe.

Não fazem parte desta proposta: alterar regras comerciais ou o robô HSE, escolher
endereços automaticamente, repetir geração automaticamente, criar notificações
por e-mail/WhatsApp, exportações novas, classificação por IA, ranking de vendedor,
editor de planilha no site ou redesenhar telas fora do módulo DAV e do resumo no ADM.

Não instalar dependências para o piloto nem levar o piloto para produção.
Reaproveitar componentes e lógica existentes na implementação futura.

## Critérios de aceitação do desenho

- DAV acessível pela sidebar administrativa, com aparência consistente.
- Erros compreensíveis no dashboard, antes de abrir o relatório.
- Avisos, falhas, simulações e resultados incertos sem confusão entre si.
- Etapas reais e dados existentes preservados durante a conferência e a geração.
- Dados financeiros restritos em toda resposta ao vendedor, incluindo históricos.
- Contagens completas por período e histórico paginado, sem distorcer reenvios.
- Rejeições anteriores ao HSE visíveis separadamente.
- Vínculo explícito de correção, sem deduzir relações ou incentivar duplicidade.
- Teclado, leitura no celular, contraste, foco e redução de movimento atendidos.
- Durante atualização, preservar contexto e deixar falhas de consulta evidentes.

## Decisões deixadas para o planejamento

Após aprovação deste desenho: escolher a base Git que contém o DAV, confirmar o
estado atualizado da branch, definir dados/migrações aditivas, consultas, rotas,
componentes reaproveitados e testes significativos. Tratar o documento como
contrato de comportamento, não como instrução para reimplementar componentes.

Atualizar `docs/MAPA_DO_SISTEMA.md` junto da mudança de produto. Validar permissões,
renderização segura, interpretação de relatórios, contagens, rejeições e deduplicação.
Código de `cruzar_nf/` não faz parte do escopo. Preparar mudanças por PR; produção
e merge seguem `docs/SERVIDOR.md` e dependem da autorização correspondente.
