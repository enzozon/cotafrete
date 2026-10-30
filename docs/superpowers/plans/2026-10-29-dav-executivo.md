# DAV Executivo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Entregar as telas executivas DAV do administrador e vendedor, com diagnóstico visível, proteção de dados financeiros e rastreio de correções.

**Architecture:** Manter FastAPI, HTML renderizado no servidor e SQLite. Acrescentar diagnóstico puro em `orcamento/diagnostico.py`, consultas em `core/painel_dav.py` e o controlador administrativo `web/adm_dav.py`; reaproveitar a moldura, componentes, autenticação, conferência e fila existentes. Rejeições e vínculos ficam no mesmo banco, sem alterar o protocolo do robô HSE.

**Tech Stack:** Python da VM, FastAPI, SQLite, HTML/CSS/JavaScript existentes, pytest e TestClient. Sem novas dependências de produção.

**Spec:** `docs/superpowers/specs/2026-10-29-dav-executivo-design.md` — aprovado por Enzo em 29/10/2026. Ler integralmente antes de executar.

## Global Constraints

- Reutilizar o visual executivo da Ventura e a preferência de tema já existente.
- Respeitar `prefers-reduced-motion`, navegação por teclado, foco visível e alvos de toque.
- Não inventar porcentagem, estimativa de conclusão ou etapas de automação que o processador não registra.
- O vendedor vê a existência da pendência financeira; títulos, valores e vencimentos da dívida ficam restritos ao administrador, inclusive em HTML, atualização e cópia de diagnóstico.
- Valores comerciais do próprio orçamento continuam na conferência. PDFs existentes seguem o acesso atual; não sanitizar PDFs.
- Não oferecer repetição automática; resultados incertos exigem conferência no HSE.
- Não guardar o conteúdo integral do arquivo inválido só para alimentar o dashboard.
- Não inferir vínculos históricos por nome de arquivo, cliente ou proximidade de horário.
- Indicadores consultam o período completo, independentemente dos limites/paginação.
- Código de `cruzar_nf/` não faz parte do escopo. Se for inevitável tocá-lo, preservar Python 3.8 e reavaliar o escopo.
- Atualizar `docs/MAPA_DO_SISTEMA.md` junto da mudança de produto. Não copiar ao servidor nem mergear sem autorização correspondente.

## Review Focus

1. Relatório antigo, desconhecido ou financeiro multilinha: não vazar dívida por mensagem alternativa ou resposta de atualização; testes nas tarefas 1 e 7.
2. Reenvio concorrente ou destino já pronto pela deduplicação: preservar uma única geração e vínculo autorizado; testes nas tarefas 2 e 4.
3. Mais de 200 registros, rejeições e reenvios: totais completos sem transformar falha histórica em sucesso; testes na tarefa 3.
4. Duas abas/perfis, sessão expirada ou parâmetro de retorno externo: não elevar acesso nem perder contexto; testes nas tarefas 6 e 7.
5. Consulta interrompida e limite de dia em Brasília: manter última resposta válida, informar desatualização e recortar o dia correto; testes nas tarefas 3 e 7.

## Base de execução e inventário

Este plano é documentação; nenhuma etapa de produto foi executada. O checkout
`cotafrete-dev` está em `main` e não contém DAV. A leitura atual usou o worktree
`C:/Users/vendas12/enzo/cotafrete-sincronizacao`, branch
`fix/dav-busca-produto-longa`, HEAD `382b27c`, sem mudanças locais no momento da leitura.
Essa base mudou desde a descoberta inicial; verificar novamente antes de executar.

Não mudar a branch do worktree de outra atividade. Preparar uma branch
`codex/dav-executivo` em checkout isolado a partir da versão atual que contenha o
DAV e a correção de busca longa. Conferir ancestralidade e dependências com a main
para declarar a base correta do PR, sem incluir acidentalmente trabalho alheio.
Transportar o desenho aprovado e este plano para essa branch como documentação.
Não criar uma implementação DAV alternativa na main que ainda não possui o módulo.

| Arquivo | Ação e responsabilidade |
|---|---|
| `core/banco.py` | Migração aditiva de vínculos; registros de rejeição; persistência com proprietário validado |
| `orcamento/diagnostico.py` | Novo: interpretação determinística e projeção segura por perfil |
| `core/painel_dav.py` | Novo: recortes, contagens, histórico, agrupamento e vínculos resolvidos |
| `web/dav_ui.py` | Upload, conferência, correção, histórico e detalhe do vendedor; componentes DAV compartilhados |
| `web/adm_dav.py` | Novo: páginas e atualização administrativas, usando `adm.banco` |
| `web/adm.py` | Remover rota DAV antiga e incluir resumo DAV no painel principal e seu pulso |
| `web/painel_ui.py` | Item DAV na sidebar e marcação ativa, mantendo âncoras existentes |
| `web/layout.py` | Somente estilos DAV compartilhados que faltarem; não refazer o tema global |
| `web/app.py` | Registrar `adm_dav.router`, seguindo a ligação de `adm_me.router` |
| `tests/test_dav_banco.py`, `tests/test_dav_tela.py` | Estender cobertura existente; atualizar expectativas afetadas |
| `tests/test_dav_diagnostico.py`, `tests/test_dav_painel.py`, `tests/test_adm_dav.py` | Novos testes das responsabilidades novas |
| `tests/test_adm_visao_geral.py`, `tests/test_painel_ui.py` | Integração do resumo e navegação |
| `tests/test_dav_atualizacao.py` | Novo: respostas de atualização e cenário interativo de falha/recuperação |
| `docs/MAPA_DO_SISTEMA.md` | Documentar módulo, dados, estados e pontos de segurança |

`orcamento/fila.py`, `orcamento/processador.py`, `orcamento/relatorio.py` e
`orcamento/planilha.py` são referências de contrato, não alvos de reescrita.
Reaproveitar os testes `tests/orcamento/test_fila.py`, `test_processador.py` e
`test_relatorio.py` como regressão, sem chamar HSE real.

## Task 1: Diagnóstico confiável e conteúdo por perfil

**Files:** Create `orcamento/diagnostico.py`, `tests/test_dav_diagnostico.py`.

**Interfaces:** `diagnostico(dav: dict, *, administrador: bool) -> dict` retorna
`categoria`, `titulo`, `motivo`, `etapa`, `orientacao`, `aviso_financeiro`,
`tem_aviso` (`bool | None`), `relatorio_visivel`, `diagnostico_copiavel`,
`salvamento` (`confirmado`, `nao_criado`, `incerto` ou `desconhecido`).
Somente essa projeção segue para HTML, atributos, cópia e respostas de atualização.

- [x] Escrever `test_endereco_e_pendencia_sao_independentes`: relatório com seção de erros de endereço e INFO de dívida gera `categoria == 'endereco'`, `aviso_financeiro is True`; `estado='pronto'` continua pronto, com aviso.
- [x] Escrever `test_erro_existe_so_no_relatorio` e `test_erro_e_relatorio_conciliados`: erro em branco não perde falha da seção Erros; fontes diferentes continuam acessíveis no detalhe administrativo, sem repetir texto idêntico.
- [x] Escrever `test_financeiro_multilinha_nao_vaza` parametrizado: título `DF15653`, valor `1234,56` e vencimento `27/09/2026` não aparecem em nenhum campo da projeção do vendedor; continuam no relatório administrativo. Incluir dívida no campo `erro`, em INFO e em continuação multilinha de seção desconhecida.
- [x] Escrever `test_legado_desconhecido_nao_inventa`: relatório parcial dá `tem_aviso is None`, `etapa is None` e não afirma ausência de aviso; falha genérica sem evidência não afirma “não criado”. `incerto` prevalece sobre palavras “OK” encontradas no texto.
- [x] Escrever `test_numero_persistido_em_erro_exige_conferencia`: `estado='erro'` com `numero='16410'` produz `salvamento == 'incerto'` e orientação para conferir no HSE, sem reenvio. O estado original continua preservado para auditoria e contagens.
- [x] Executar `python -m pytest tests/test_dav_diagnostico.py -q`; confirmar falhas pelos contratos novos.
- [x] Implementar a função: reconhecer o formato de `Relatorio.texto()` e apenas categorias sustentadas por mensagens atuais (endereço, login/indisponibilidade e validação). Para vendedor, reconstruir detalhes com campos permitidos e mensagens reconhecidas; não tentar remover dívida de texto arbitrário por regex e depois expor o restante. Texto não separável recebe orientação genérica; administrador vê o original. `None` não equivale a falso. Não usar IA.
- [x] Executar o arquivo novo e `python -m pytest tests/orcamento/test_relatorio.py -q`; esperar todos aprovados. Commit `feat: interpretar diagnostico DAV por perfil`.

## Task 2: Persistir rejeições e vínculos sem alterar a fila

**Files:** Modify `core/banco.py` (`ESQUEMA`, `_migrar` e seção DAV); Test `tests/test_dav_banco.py`.

**Interfaces:** Acrescentar `Banco.dav_rejeitar(usuario: str, arquivo: str, motivos: list[str]) -> int`
e `Banco.dav_vincular_correcao(origem_id: int, destino_id: int, usuario: str) -> None`.
Manter assinaturas de `dav_criar`, `dav`, `dav_atualizar`, `dav_ja_gerado` e da fila.
Reforçar `dav_ja_gerado` somente no caso conservador de erro com número HSE já persistido.

- [x] Testar banco antigo sem estrutura nova: inicialização repetida mantém linhas e índices e cria a migração uma única vez.
- [x] Escrever `test_rejeicao_nao_e_tentativa_no_hse`: registro `estado='rejeitado'`, `hash_planilha=''`, `erro` com motivos, cliente/número/PDF vazios; `dav_ja_gerado` e `dav_interromper` nunca o enviam à fila. Hash vazio é reservado à rejeição sem arquivo persistido.
- [x] Escrever `test_vinculo_valida_dono_estado_e_ciclo`: origem/destino de outro dono, autorreferência, ciclo e origem pronta/incerta/fila/gerando são recusados; origem erro/rejeitado para destino próprio é aceita; repetição do vínculo é idempotente.
- [x] Escrever `test_duas_origens_podem_apontar_para_mesmo_pronto`: aceitar DAV existente encontrado pela deduplicação, inclusive com id menor que o da origem, sem duplicá-lo ou mudar o estado antigo.
- [x] Escrever `test_erro_com_numero_nao_autoriza_reenvio`: erro com número HSE persistido é retornado pela deduplicação e recusado como origem de correção, por possível salvamento. A projeção da tarefa 1 informa que exige conferência, sem reclassificar silenciosamente o estado persistido.
- [x] Executar `python -m pytest tests/test_dav_banco.py -q`; verificar as falhas dos métodos novos.
- [x] Reutilizar a tabela `dav` para rejeições, sem criar planilha em disco. Criar tabela `dav_correcao(origem_id INTEGER NOT NULL, destino_id INTEGER NOT NULL, PRIMARY KEY(origem_id, destino_id))` e índice por destino; validar existência, dono e ausência de ciclo dentro da mesma transação. Validar estado da origem: somente erro/rejeitado e sem evidência de salvamento. Recursão com conjunto de ids visitados; rejeitar ciclos, não depender de ordem dos ids. Não modificar `CAMPOS_DAV` para aceitar colunas vindas do cliente. Incluir erro com número HSE na proteção de deduplicação; diagnóstico também prioriza essa evidência sobre sugestões de reenviar.
- [x] Executar testes DAV de banco e fila; esperar todos aprovados. Commit `feat: registrar rejeicoes e correcoes DAV`.

## Task 3: Consultas completas, recortes e resolução de falhas

**Files:** Create `core/painel_dav.py`, `tests/test_dav_painel.py`.

**Interfaces:** `consultar(con, *, usuario: str | None, dias: int, agora: datetime,
estado: str = '', vendedor: str = '', busca: str = '', pagina: int = 1) -> dict`;
`posicao_na_fila(con, dav_id: int) -> int | None`;
`resolvidas(con, ids: list[int], usuario: str | None) -> dict[int, int]`.
`consultar` devolve `resumo`, `atencao`, `grupos`, `linhas`, `total`, `pagina`,
`paginas`, `vendedores`, `periodo`. Linhas são internas; projetar na tarefa 1 antes de renderizar.

- [x] Escrever `test_periodo_e_paginacao_nao_truncam_totais`: criar 205 registros em banco temporário; limite de página 25, total 205 e 9 páginas, sem depender de `Banco.davs(..., 200)`.
- [x] Escrever `test_contagens_separam_estados`: rascunhos/simulações/rejeições fora de tentativas; `tentativas == criados + falhas + incertos + em_andamento` para estados conhecidos; avisos são subconjunto de criados; rejeições e incertos possuem contadores próprios.
- [x] Escrever `test_fronteira_de_dia_brasilia`: Hoje começa 00:00; 7/30 dias incluem o dia atual e 6/29 dias anteriores, até `agora`. Relógio injetável; não usar janela móvel de 24 h para Hoje. Reaproveitar normalização de `mercado_eletronico.painel.hora_de_brasilia`, mantendo o contrato de timestamps locais do banco.
- [x] Escrever `test_filtro_vendedor_nao_sobrepoe_proprietario`: `usuario='ana'` não expõe Bia mesmo recebendo `vendedor='bia'`; SQL parametrizado para busca e filtros. Buscar somente cliente, usuário, arquivo e número, sem indexar relatório financeiro.
- [x] Escrever `test_resolvida_so_com_descendente_pronto`: cadeia erro → rejeição → fila ainda não resolvida; destino pronto resolve sem mudar estado/contagem históricos; descendente incerto não resolve; sem vínculo explícito não resolve. Um pronto pode resolver mais de uma origem autorizada.
- [x] Escrever `test_avisos_desconhecidos_nao_sao_zero`, `test_estado_novo_visivel` e `test_posicao_usa_toda_fila`: avisos desconhecidos possuem subtotal desconhecido; estado novo consultável e fora de totais que o desconhecem; posição correta além dos primeiros 50 registros.
- [x] Executar `python -m pytest tests/test_dav_painel.py -q`; confirmar falhas esperadas.
- [x] Implementar consultas com conexão fornecida, funções da tarefa 1 e leitura de vínculos da tarefa 2. Resumo/grupos usam período + vendedor + busca; filtro de resultado pagina somente a lista, mantendo o contexto dos totais com legenda explícita. `dias` limitado a 1/7/30, padrão 1; página no mínimo 1 e ajustada à última disponível; sem resultados `paginas=1`. Mapear estado de UI `com_aviso` para pronto com aviso conhecido. `simulado`, `rascunho` e `rejeitado` têm filtros próprios.
- [x] Agrupar apenas categorias reconhecidas; desconhecidos permanecem acessíveis como não classificados. Não somar rejeições como falhas HSE. Resolver vínculos sobre toda a cadeia autorizada, mesmo fora da página/período, sem carregar conteúdo de arquivos.
- [x] Executar os testes novos; esperar todos aprovados. Commit `feat: consultar painel DAV sem truncar historico`.

## Task 4: Integrar o fluxo de correção e registrar rejeições

**Files:** Modify `web/dav_ui.py` (`conferir`, `_erro`, `_ja_gerou`, `_resumo`); Test `tests/test_dav_tela.py`.

**Interfaces:** Acrescentar `origem: int | None` como query do envio e campo Form
de `/dav/conferir`; persistir vínculo na confirmação/rejeição da leitura.
Retornar id da origem em campo oculto validado no servidor, não confiar no HTML.
`gerar(dav_id, ...)` mantém sua confirmação e trava existentes.

- [x] Atualizar os testes `test_conferir_com_erro_lista_erros_sem_botao_nem_linha` e `test_arquivo_errado_nada_criado`: agora existe somente registro rejeitado, sem `/gerar`, arquivo residual ou tarefa disparada. Requisição sem login não cria registro.
- [x] Escrever `test_corrigir_referencia_origem_e_preserva_dono`: enviar arquivo corrigido a partir de erro próprio cria rascunho vinculado; nenhuma escrita no HSE antes de confirmar. Rejeição subsequente também recebe vínculo.
- [x] Escrever `test_origem_forjada_e_incerta_nao_permite_correcao`: origem alheia/inexistente devolve 404; origem incerta, erro com número já salvo ou origem que mudou de estado é recusada sem criar novo rascunho/arquivo/fila. ADM sem sessão do dono não reenvia em seu nome.
- [x] Escrever `test_correcao_deduplicada_vincula_resultado_existente`: destino pronto/fila/gerando/incerto já conhecido pelo hash não cria novo orçamento; origem vincula a destino autorizado, mas só pronto indica resolução.
- [x] Escrever `test_envios_concorrentes_nao_duplicam_geracao`: com clientes de teste e mesmo arquivo, confirmar rascunhos concorrentes mantém o disparo único pela trava/deduplicação atuais.
- [x] Executar `python -m pytest tests/test_dav_tela.py -q`; confirmar somente falhas referentes às mudanças planejadas.
- [x] Implementar registro nos pontos de rejeição já existentes (extensão, tamanho, `ErroPlanilha`, leitura inválida). Normalizar nome com `Path(...).name`, limitar a leitura a `MAX_BYTES + 1`, apagar temporários como hoje. Falha de persistência apresenta que a rejeição não pôde ser registrada, sem afirmar que foi ao HSE e sem enfileirar. Origem validada antes de processar o upload e novamente ao vincular. Corrigida significa nova planilha, não reset de linha antiga.
- [x] Executar testes de tela, banco e fila; esperar todos aprovados. Commit `feat: conectar correcoes ao envio DAV`.

## Task 5: Telas executivas do vendedor e componentes compartilhados

**Files:** Modify `web/dav_ui.py`, `web/layout.py`; Test `tests/test_dav_tela.py`, `tests/test_layout.py`.

**Interfaces:** Em `dav_ui.py`, `tabela_davs(linhas: list[dict], com_vendedor: bool = False, *, administrador: bool = False) -> str`
mantém os argumentos antigos; novos links distinguem `/dav/{id}` de `/adm/dav/{id}`.
Acrescentar `detalhe_dav(dav: dict, *, administrador: bool, retorno: str) -> str`
como fragmento sem moldura, consumindo a projeção da tarefa 1 e nunca o relatório cru no perfil vendedor.
GET `/dav/{dav_id}/conferir` reabre apenas o rascunho do proprietário, lendo
`FILA.planilha(dav_id)` com `ler_planilha` e `_resumo`, sem gerar outra linha ou tarefa.
Arquivo ausente/inválido mostra orientação para corrigir, sem botão Gerar.

- [x] Escrever testes de envio/conferência: modelo v3, 5 MB, arquivo selecionado, mensagens junto ao campo e todos os campos atuais de `_resumo` preservados, incluindo quantidades/valores/códigos e avisos.
- [x] Escrever `test_reabrir_rascunho_preserva_confirmacao`: GET de conferência própria reexibe dados sem novo registro/disparo; outro proprietário recebe 404; arquivo que sumiu não oferece gerar e não é recriado silenciosamente.
- [x] Escrever `test_resultados_distintos_e_acoes_seguras`: todos os estados reais e rejeitado têm rótulo; erro sem prova não afirma “não criado”; incerto com/sem número não apresenta repetir/corrigir/gerar; PDF somente quando o registro tem PDF; simulação informa nada salvo.
- [x] Escrever `test_detalhe_vendedor_nao_embute_relatorio_privado`: dívida não aparece nem em atributos, bloco oculto, script, relatório expandido ou texto copiável; nome/erro malicioso é escapado; preços comerciais da conferência permanecem.
- [x] Executar os testes alterados; confirmar falhas referentes às novas telas.
- [x] Montar upload, conferência e histórico pessoal usando a moldura atual do vendedor e consultas da tarefa 3. Oferecer busca, período e resultado com formulário GET e paginação utilizáveis sem JavaScript. Rascunho próprio encontrado no histórico volta à conferência; não precisa reenviar nem criar nova linha para apenas revisar.
- [x] Montar detalhes com motivo, orientação, aviso financeiro genérico, horários reais e relatório permitido expansível. Usar CSS existente; acrescentar somente seletores escopados `.dav-*` para layout que faltar. Sem preferência nova de densidade, dependências, porcentagem fictícia ou timeline inventada.
- [x] Verificar `python -m pytest tests/test_dav_tela.py tests/test_layout.py -q`; esperar aprovação. Commit `feat: renovar experiencia DAV do vendedor`.

## Task 6: Painel DAV administrativo e resumo no painel principal

**Files:** Create `web/adm_dav.py`, `tests/test_adm_dav.py`; Modify `web/adm.py`, `web/app.py`, `web/painel_ui.py`, `tests/test_adm_visao_geral.py`, `tests/test_painel_ui.py`.

**Interfaces:** `adm_dav.router` prefix `/adm/dav`; GET `''` e `/{dav_id}`;
GET `/{dav_id}/pdf` reaproveita a validação de acesso/caminho atual de PDF.
O controlador usa `adm.banco`, `adm._exigir_montado()` e `adm.autorizado()`.
`pagina_painel(..., base='/adm', ativo='dav')` ganha keyword opcional `ativo: str = ''`,
encaminhada a `_lateral`, sem quebrar chamadas existentes. DAV ativo recebe `aria-current='page'`.

- [x] Escrever `test_porta_admin_em_todas_rotas`: sem configuração responde 404; sem cookie válido redireciona login; vendedor sem ADM não acessa lista/detalhe/PDF nem por id forjado.
- [x] Escrever `test_adm_dav_sidebar_e_links`: item Orçamentos DAV na sidebar, ativo no módulo; links Visão geral/Movimento/Histórico voltam a `/adm#...`; listagem e detalhe usam moldura administrativa.
- [x] Escrever `test_admin_ve_relatorio_completo_sem_html_executavel`: dívida preservada e escapada; origem/reenvio são navegáveis; admin possui somente consulta, sem geração em nome alheio.
- [x] Escrever `test_retorno_preserva_recorte_sem_open_redirect`: período, vendedor, busca, estado e página sobrevivem ao detalhe e volta. Construir retorno por parâmetros reconhecidos e `urlencode`; não aceitar URL arbitrária nem refletir `javascript:`/domínio externo.
- [x] Escrever `test_resumo_dav_nao_altera_totais_frete`: `/adm` mostra falhas/incertos/rejeições DAV em bloco próprio; totais de frete inalterados; bloco rotula Hoje e links usam `dias=1` e resultado correspondente.
- [x] Executar testes novos/afetados; confirmar falhas esperadas.
- [x] Registrar router novo; remover somente a rota antiga `adm.todos_os_davs`, evitando dois handlers para `/adm/dav`. Reaproveitar componentes da tarefa 5, números/cartões/cores de `painel_ui` e filtros da tarefa 3. ADM mantém relatório completo; não passar `administrador=True` por parâmetro recebido do navegador.
- [x] Preservar links antigos `/dav/{id}`: quando acesso exclusivamente administrativo, redirecionar para detalhe administrativo; com sessão de vendedor, rota `/dav` entrega projeção de vendedor. `/dav/{id}/pdf` conserva autorização de proprietário/ADM e restrição ao diretório de PDFs; `/adm/dav/{id}/pdf` exige sempre ADM. Registrar rotas fixas antes dos parâmetros dinâmicos.
- [x] Executar `python -m pytest tests/test_adm_dav.py tests/test_dav_tela.py tests/test_painel_ui.py tests/test_adm_visao_geral.py -q`; esperar aprovação. Commit `feat: integrar DAV ao painel administrativo`.

## Task 7: Atualização discreta com falhas visíveis

**Files:** Modify `web/dav_ui.py`, `web/adm_dav.py`, `web/adm.py`; Create `tests/test_dav_atualizacao.py`.

**Interfaces:** GET `/dav/agora` (histórico pessoal), `/dav/{dav_id}/agora`
(detalhe pessoal/legado autorizado), `/adm/dav/agora` e `/adm/dav/{dav_id}/agora`.
Respostas autenticadas `{v, atualizado_em, fragmentos}`; `v` identifica o conteúdo
do recorte, não apenas quantidade ou maior id. 204 quando cliente já tem a versão.
Respostas/HTML privados usam `Cache-Control: no-store`. Falha retorna erro não 200 com zeros.

- [x] Escrever testes de contrato: dono recebe somente sua projeção; ADM recebe original; sessão expirada responde 401 na API, configuração ADM ausente 404; redirecionamento de login não é tratado como fragmento válido.
- [x] Escrever `test_mesma_contagem_com_novo_erro_muda_versao`: alterar erro/relatório/vínculo mantendo ids/total muda `v`; filtro distinto não reaproveita versão errada. Incluir rascunho→fila, aviso novo e origem resolvida.
- [x] Escrever `test_versao_inclui_janela_do_periodo`: mudança da meia-noite expira versão mesmo sem nova gravação; `/adm` também detecta mudança DAV sem nova cotação de frete.
- [x] Executar os testes novos; confirmar falhas pelos endpoints ainda ausentes.
- [x] Implementar APIs reaproveitando as mesmas consultas e renderização das páginas completas. Digest do conteúdo projetado e recorte; não enviar relatório cru junto com fragmento sanitizado. Calcular por dados do banco, nunca lendo planilhas/PDFs para o pulso. Adicionar bloco DAV ao pulso existente do `/adm` sem alterar o significado dos fragmentos de frete.
- [x] Implementar pulso a cada 5 segundos, sem sobreposição de pedidos. Na listagem sem dados novos, 204 não reanima nada; no terminal pronto/erro/incerto/simulado/rejeitado, detalhe para de consultar. Busca usa GET completo ao aplicar filtros; o pulso herda a URL validada. Não substituir controles que contêm foco nem fechar `<details>` abertos.
- [x] Realizar teste interativo local com dados sintéticos: página 2 filtrada mantém seleção/rolagem enquanto outro registro muda; interrupção de resposta exibe “Não foi possível atualizar” com último horário e mantém últimos dados; “Atualizar agora” recupera; 401 mostra sessão expirada e interrompe pulso. Conferir que nenhuma requisição POST de geração ocorreu. Usar navegador disponível e documentar resultado, sem criar teste que apenas procura strings JavaScript.
- [x] Executar `python -m pytest tests/test_dav_atualizacao.py tests/test_adm_script.py tests/test_adm_tela.py -q`; esperar aprovação. Commit `feat: atualizar telas DAV preservando contexto`.

## Task 8: Documentação, regressão e entrega revisável

**Files:** Modify `docs/MAPA_DO_SISTEMA.md`; preservar desenho e este plano na branch de implementação.

**Interfaces:** Nenhuma nova interface de produto. Entrega: diff, evidência de testes e prévia revisável das telas reais.

- [ ] Atualizar o mapa com arquivos, estados (incluindo rejeitado), tabela de vínculos, projeção financeira, contagens, consultas e risco de duplicidade em `incerto`. Documentar que o estado financeiro do HSE não bloqueia automaticamente a criação DAV pela interface.
- [ ] Executar `python -m pytest tests/test_dav_banco.py tests/test_dav_diagnostico.py tests/test_dav_painel.py tests/test_dav_tela.py tests/test_adm_dav.py tests/test_dav_atualizacao.py tests/orcamento/test_fila.py tests/orcamento/test_processador.py tests/orcamento/test_relatorio.py tests/test_adm_visao_geral.py tests/test_painel_ui.py tests/test_layout.py -q`; esperar aprovação. Depois executar uma vez `python -m pytest tests -q`. Em falha, corrigir e repetir o conjunto afetado antes da conclusão; registrar limitações reais do ambiente.
- [ ] Verificar migração duas vezes sobre banco sintético antigo e conferir que geração, retomada, relatórios, PDFs e vínculos antigos permanecem íntegros. Nunca usar cópia crua de banco produtivo WAL; backup real só por `core/backup.py`.
- [ ] Inspecionar telas reais com dados sintéticos em desktop (1440 px) e celular (390 e 320 px), claro/escuro, teclado e redução de movimento: erro longo, sem dados, filtro vazio, rejeição, rascunho, fila, pronto com aviso e incerto. Conferir quebra de texto, tabelas, foco, controles e ausência de animação repetitiva. Salvar capturas das telas principais para revisão.
- [ ] Executar `git diff --check` e conferir que o diff não inclui dados, relatórios/PDFs reais, segredos, `.superpowers/brainstorm`, mudanças alheias ou código do piloto.
- [ ] Commit `docs: mapear painel e seguranca DAV`. Preparar PR contra a base confirmada, informando dependência do DAV existente/correção de busca longa, migração aditiva, resultados dos testes e capturas. Se criar PR, anexá-lo à conversa pela ferramenta do app. Sem merge ou escrita em produção nesta entrega.

## Riscos e decisões de implementação

- Projeção financeira é parte de segurança: preferir omissão explícita de um trecho desconhecido à exposição de relatório livre. Isso reduz detalhes disponíveis ao vendedor em formatos antigos não reconhecidos; ADM mantém acesso completo.
- `rejeitado` reutiliza a tabela DAV, mas não é geração. Rever todos os leitores dos estados, não apenas as telas novas; fila mantém a lista atual e deduplicação acrescenta a proteção conservadora para erro com número persistido. Os testes antigos que afirmavam “nenhuma linha” mudam para “nenhuma geração ou arquivo persistido”.
- Vínculos são associação explícita, não reprocessamento. Resolução não altera os resultados antigos; pode apontar a um resultado pronto fora do período mostrado.
- O período usa data da submissão (`criado_em`), não data da conclusão. Uma tentativa de ontem concluída hoje aparece no período que inclui ontem; legenda informa isso. Indicadores não medem faturamento nem clientes únicos.
- O plano não exige detalhar etapas dentro do robô ou estruturar todo o relatório em banco. O diagnóstico lê o formato atual, mantém estado como fonte primária e preserva original para ADM. Uma evolução do formato exige novos casos de teste antes de expor conteúdo ao vendedor.

## Cobertura do desenho e entrega

Identidade/temas/acessibilidade → tarefas 5, 6 e 8; todos os estados → 1 e 5;
privacidade → 1, 5, 6 e 7; registros rejeitados/vínculos → 2 e 4;
contagens/histórico completo/agrupamentos → 3; sidebar e `/adm` → 6;
acompanhamento sem recarga → 7; mapa, testes e evidências → 8.

Plano revisado pelo próprio autor contra o desenho aprovado, incluindo consistência
das interfaces e os cinco pontos de Review Focus. Execução ainda depende da revisão
do plano e da escolha do método pelo usuário. Recomendação: execução nativa com
uma revisão independente ao final, pois as tarefas compartilham consultas,
permissões e renderização; o maior risco é a coerência entre essas interfaces.


## Resultado da execução — 30/10/2026

Etapas 1–7 concluídas, revisão independente concluída e correções verificadas. A etapa 8 está registrada em docs/superpowers/validation/2026-10-30-dav-executivo.md: suíte completa com 2.463 testes aprovados, conferência das telas e limitações declaradas. Produção não alterada. Método nativo com subagentes para revisão e validação, autorizado por Enzo.

