# O servidor: por que é diferente e como trabalhamos nele

Resumo para qualquer pessoa ou IA que vá mexer em produção. A instalação
passo a passo está em `DEPLOY_SERVIDOR.md` e `CONFIGURAR_NA_EMPRESA.md`.

## A máquina

| | |
|---|---|
| Servidor | **SERVIDOR2**, Windows Server **2012 R2**, Xeon E3-1270 v2 (4 núcleos / 8 lógicos), 32 GB |
| Dentro dele | VM Windows 10, 4 vCPU, 8 GB, com o Cotafrete e o ME em `C:\enzo\cotafrete-producao` |
| Direto no 2012 R2 | gerenciador Maestro, serviço de NF, cadastro de pedidos e pasta pública `\\SERVIDOR2\Publico\ALLAN\...` |
| Portal Maestro | pm2 "Site-Maestro" em `C:\Users\Administrator\Desktop\maestro\portaismaestro`, com Cloudflare Tunnel |

## Os limites que um sistema antigo impõe

1. **Chromium atual não roda no 2012 R2.** O suporte acabou na versão 110
   (fev/2023). Por isso o Cotafrete, que precisa de navegador moderno para
   as transportadoras, mora na VM. O robô HSE do serviço de NF usa
   **Chrome 109 com Selenium**, o último que funciona ali.
2. **Python antigo direto no servidor.** O código que roda no 2012 R2
   (`cruzar_nf/`) é mantido **compatível com 3.8**: sem `match`, sem
   `list[str]` em tempo de execução sem `from __future__ import annotations`,
   sem `str.removeprefix` etc. Na VM roda 3.14. Antes de subir código que use
   recurso novo, confira a versão com `python --version` no servidor.
3. **Ferramentas de desenvolvimento não vão para o servidor.** Isso inclui o
   Graphify, que pede Python 3.10 ou mais novo. Elas rodam na máquina de
   desenvolvimento.
4. **CPU apertada.** São 4 núcleos físicos para tudo. Com 1 vCPU a VM chegou
   a derrubar cotações. Não suba vCPU além de 4 e não aumente
   `NAVEGADORES_SIMULTANEOS` sem medir antes.
5. **Tarefas agendadas enganam.** `schtasks /End` não mata o python filho, e
   o código de saída nem sempre chega ao `.bat`. Daí vêm os processos órfãos.
   Use sempre os `.bat` de reinício, que encerram o que sobrou.
6. **Clique na janela do console congela o processo (QuickEdit).** Já está
   desligado na VM. Confira se ele voltar.

## Quem faz o quê: o Claude prepara, o Enzo executa

O Claude **não** escreve no servidor por conta própria. O modo automático
bloqueia cópia para `\\SERVIDOR2` e merge sem pedido explícito, e tem que ser
assim: o servidor é produção compartilhada e outras pessoas mexem nele.

O fluxo de toda mudança em produção:

1. **Conferir antes.** O Claude lista data, tamanho e hash dos arquivos do
   servidor e compara com a `main`. Se alguém mudou algo no servidor, ele
   mostra o diff e para.
2. **Preparar.** O código vai por PR. Mergear e copiar para o servidor só
   com pedido explícito. Os arquivos a copiar ficam no scratchpad.
3. **Entregar o comando pronto.** O Claude escreve o comando exato, já com
   backup, para o Enzo rodar com `!` no prompt. Exemplo:
   ```
   ! D='//SERVIDOR2/Publico/ALLAN/NUVEM/server2012/sync_nf'; mkdir -p "$D/backup_codigo/AAAA-MM-DD" && cp "$D"/cruzar_nf/servico.py "$D/backup_codigo/AAAA-MM-DD/" && cp cruzar_nf/servico.py "$D/cruzar_nf/" && echo COPIADO
   ```
4. **O que só roda no servidor** (como admin, na sessão RDP): o Enzo executa
   e cola a saída. Exemplos são `ReiniciarServicoNF.bat` e
   `pm2 restart Site-Maestro --update-env && pm2 save`.
5. **Verificar depois.** O Claude lê só o final do log
   (`logs\servico_nf.log`), confere o hash de novo e diz se terminou ou o que
   falta.

### Regras que já custaram caro

- **Nunca** trocar `SYNC_NF_DADOS` de pasta.
- Antes de reiniciar o serviço de NF, conferir se ninguém está gravando: a
  trava do `nf_planilha` e a sessão de cadastro. Duas sessões do Claude
  podem estar mexendo juntas. Combine antes e nunca mexa no arquivo da outra
  sessão.
- No Cotafrete de produção, antes de reiniciar, conferir no banco se há
  cotação em `validando`, `enviando` ou `solicitacao_enviada`.
- Backup do banco só por `Backup.bat` (`core/backup.py`). Cópia crua do `.db`
  em WAL sai atrasada e sem dar erro.

## Atualização

- **Cotafrete (VM):** depois de instalado o `Instalar-atualizacao.bat`, se
  atualiza sozinho a cada merge na `main`.
- **Serviço de NF / cadastro (2012 R2):** copiar à mão com o fluxo acima e
  depois rodar `ReiniciarServicoNF.bat` como admin.
- **Portal Maestro:** `git pull`, `pm2 restart Site-Maestro --update-env` e
  `pm2 save` na máquina do pm2.
- **Gerenciador Maestro:** fora do git. Quem o altera faz isso direto no
  servidor. Conferir antes de integrar.
