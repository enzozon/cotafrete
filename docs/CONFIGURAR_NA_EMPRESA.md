# Deixar o sistema subindo sozinho — roteiro para fazer na empresa

Este é o roteiro de uma sessão só, na frente do servidor. Ao fim dela:

- o servidor liga → a VM sobe → o Windows entra → o Cotafrete abre, sem
  ninguém tocar em nada;
- o site institucional sai da VM e passa a ser servido pela Cloudflare;
- o túnel deixa de ser uma janela que alguém pode congelar com um clique.

Leia o roteiro inteiro antes de começar. A ordem importa: o passo 1 fecha um
buraco de segurança, e os passos seguintes deixam o site no ar por mais
tempo — ou seja, aumentam a exposição desse buraco.

Tempo estimado: 1h30, boa parte esperando propagação de DNS.

---

## Antes de começar

| você vai precisar de | onde |
|---|---|
| acesso ao painel da Cloudflare | `one.dash.cloudflare.com` |
| acesso ao repositório `allan-max/nova-ventura` | GitHub |
| Hyper-V Manager | no servidor (host) |
| a senha do usuário da VM | — |
| `git pull` já feito na VM | `C:\enzo\cotafrete-producao` |

Comece pelo `git pull` na VM: o `Servidor.bat` mudou e o roteiro conta com a
versão nova.

---

## 1. Fechar o acesso ao Cotafrete (Cloudflare Access)

**Faça este passo primeiro.** Hoje `https://cotafrete.ventura.inf.br` está na
internet pública **sem senha nenhuma**: a tela de entrada aceita qualquer
nome digitado e cria a sessão. Ela foi desenhada para a rede local, onde
servia para separar históricos — não para barrar acesso.

E o que está atrás dela é CNPJ de cliente, valor de nota fiscal e os prints
que as transportadoras devolvem.

No painel:

1. **Zero Trust** → **Access** → **Applications** → **Add an application**
2. Tipo: **Self-hosted**
3. Nome: `Cotafrete`, domínio: `cotafrete.ventura.inf.br`
4. Em **Policies**, crie uma política:
   - Nome: `Equipe Ventura`
   - Action: **Allow**
   - Include → **Emails** → liste os e-mails de quem usa o sistema
     (ou **Emails ending in** → `@ventura.inf.br`, se todos tiverem)
5. Em **Login methods**, deixe **One-time PIN** ligado — a pessoa recebe um
   código por e-mail, sem precisar de conta em lugar nenhum.

Teste numa aba anônima: deve pedir e-mail antes de mostrar qualquer coisa.

> O plano gratuito cobre até 50 usuários. Não mexe numa linha do sistema — é
> a Cloudflare barrando antes de a requisição chegar na VM.

### Confira o relógio da VM antes de confiar no Access

O Access trabalha com tokens de validade curta (minutos). Com o relógio fora
do lugar, o token que a Cloudflare emite nasce "expirado" ou "do futuro" para
a VM, e o login passa a falhar de forma intermitente e sem mensagem que
ajude. Na VM da empresa ele estava **4 horas atrasado** em 14/09/2026.

```powershell
Get-TimeZone
Get-Date

Set-TimeZone -Id "E. South America Standard Time"
Set-Service w32time -StartupType Automatic
Start-Service w32time
w32tm /resync /force
```

Se o `resync` reclamar, aponte um servidor explicitamente:

```powershell
w32tm /config /manualpeerlist:"pool.ntp.br,0x8" /syncfromflags:manual /update
Restart-Service w32time
w32tm /resync /force
```

Se mesmo assim voltar errado, o horário está vindo do host pela integração do
Hyper-V — aí quem precisa acertar é o **servidor**, não a VM. De quebra, isso
também deixa os logs legíveis: com o relógio torto, os horários do Visualizador
de Eventos não batem com o que você acabou de fazer.

---

## 2. Mover o site institucional para o Cloudflare Pages

O `nova-ventura` são sete arquivos `.html` e uma imagem. Não tem build, não
tem Python, não tem nada que precise de um servidor de verdade rodando.

Servi-lo por `python -m http.server` dentro da VM, atrás de um túnel, é dar
três voltas para fazer o que a Cloudflare faz direto — e amarra o site
institucional à VM: se ela cair, se o login automático falhar, se alguém
deslogar sem querer, o site cai junto. Não há motivo para isso.

> A própria documentação do Python diz que o `http.server` **não é para
> produção**: implementa só verificações básicas de segurança.

1. **Workers & Pages** → **Create** → **Pages** → **Connect to Git**
2. Autorize o GitHub e escolha `allan-max/nova-ventura`
3. Configuração de build:
   - Framework preset: **None**
   - Build command: **deixe vazio**
   - Build output directory: `/`
4. **Save and Deploy**
5. Terminado: **Custom domains** → **Set up a custom domain** →
   `sitenovo.ventura.inf.br`

A Cloudflare ajusta o DNS sozinha. A partir daí, **todo `git push` publica** —
ninguém precisa entrar na VM para atualizar o site.

### Depois que o Pages estiver no ar

- Pare o `.bat` que sobe a porta 8080 e **tire o atalho dele do Startup**
- Remova a regra `sitenovo.ventura.inf.br` do ingress do túnel (passo 3)

---

## 3. Transformar o túnel em serviço do Windows

Hoje o túnel é uma janela de console aberta. Duas consequências ruins: ela
morre junto com o logoff, e **um clique dentro dela congela o processo** — é
o QuickEdit, a mesma armadilha explicada no `DEPLOY_SERVIDOR.md`, e o
`cloudflared` escreve muito.

Como serviço, ele sobe no boot **antes do login** e reinicia sozinho.

### 3a. Migrar o túnel para gerenciado pelo painel (recomendado)

O painel já está sugerindo isso. Aceitar tem uma vantagem concreta aqui:
**você passa a mudar as rotas de qualquer lugar**, sem entrar na VM — que é
exatamente o que faltou quando o problema apareceu e você não estava na
empresa.

E resolve um tropeço da instalação: o serviço roda como `LocalSystem` e
procuraria o `config.yml` em
`C:\Windows\System32\config\systemprofile\.cloudflared\`. Com túnel
gerenciado pelo painel **não há arquivo de configuração** para colocar no
lugar errado.

O que se perde: as rotas deixam de ser um arquivo versionável. Para duas
rotas que mudam raramente, não pesa.

1. **Networks** → **Tunnels** → `tunel-cotafrete` → aceite a migração
2. Em **Published application routes**, deixe **uma** regra:
   `cotafrete.ventura.inf.br` → `http://localhost:8000`
   (a do `sitenovo` sai — agora é o Pages)
3. Copie o **token** do conector

**Onde fica o token:** no próprio túnel, em **Configure** → ambiente
**Windows**. A Cloudflare mostra o comando pronto, e o token é a string longa
(começa com `eyJ`) depois de `service install` — dá para copiar o comando
inteiro. Pela linha de comando, na VM, também serve:

```powershell
cloudflared tunnel token tunel-cotafrete
```

O token é **segredo**: autoriza qualquer máquina a se conectar como esse
túnel. Não cole em chamado, e-mail ou print. E ele só existe depois da
migração — enquanto o túnel for *locally-managed* (com `config.yml` e arquivo
de credenciais), não há token para copiar.

### 3b. Instalar o serviço

Na VM, PowerShell **como administrador**:

```powershell
# Feche a janela do tunel que estiver aberta ANTES disto.
cloudflared service install <COLE-O-TOKEN-AQUI>
Start-Service cloudflared
Get-Service cloudflared
```

Deve aparecer `Running`.

> Escreva **`sc.exe`** nos comandos mais abaixo, nunca `sc`. No PowerShell,
> `sc` é apelido de `Set-Content` — você acha que configurou o serviço e na
> verdade tentou escrever um arquivo.

#### Se a instalação disser que a chave de registro já existe

```
cannot install event logger: SYSTEM\CurrentControlSet\Services\EventLog\
Application\Cloudflared registry key already exists
```

É sobra de uma instalação anterior. O instalador não sobrescreve, para no
meio, e o serviço **não fica registrado** — o `Get-Service` responde *"cannot
find any service"* logo depois de a tela dizer "is installed". Feche o
`services.msc` (ele segura o registro) e refaça limpo:

```powershell
cloudflared service uninstall
Remove-Item "HKLM:\SYSTEM\CurrentControlSet\Services\EventLog\Application\Cloudflared" `
  -Recurse -Force -ErrorAction SilentlyContinue
sc.exe delete cloudflared
cloudflared service install <TOKEN>
Start-Service Cloudflared
```

Essa chave é só o registro do `cloudflared` como fonte de eventos; apagá-la
não afeta nada, e o instalador a recria. Se o `sc.exe delete` disser *"marked
for deletion"*, reinicie a VM antes de reinstalar.

### 3b-bis. O serviço sobe à mão mas não sobe no boot

Este é o segundo tropeço, e ele **não dá erro nenhum na instalação**: depois
de reiniciar, o `Get-Service` mostra `Stopped`; você inicia à mão e funciona.

No log de Sistema aparece o motivo:

```
Id 7009 — A timeout was reached (45000 milliseconds) while waiting for the
Cloudflared service to connect.
```

O `cloudflared` só avisa ao Windows "estou pronto" depois de alcançar a borda
da Cloudflare. No boot a rede ainda está subindo, ele fica tentando, passa
dos 45 segundos que o Gerenciador de Serviços espera, e o Windows desiste e o
deixa parado. Como `Automatic` não repete, ele fica parado o dia inteiro.

```powershell
sc.exe config cloudflared start= delayed-auto
sc.exe failure cloudflared reset= 86400 actions= restart/5000/restart/10000/restart/30000
```

O **espaço depois do `=` é obrigatório** (`start= delayed-auto`).

O primeiro comando faz o serviço subir depois da rede. O segundo manda o
Windows reerguê-lo se cair (5s, 10s, 30s) — é o que cumpre a promessa de
"reinicia sozinho"; sem ele, um tropeço deixa o túnel fora do ar até alguém
perceber. Confira com `sc.exe qc cloudflared`, que deve mostrar
`START_TYPE : 2  AUTO_START (DELAYED)`.

Medido em 14/09/2026: com `delayed-auto` o serviço volta `Running` sozinho
depois do reboot — demora um pouco mais para aparecer, que é justamente o
atraso fazendo efeito.

#### Como olhar os logs sem se enganar

```powershell
# tudo que o cloudflared escreveu (NAO use -MaxEvents: ele corta antes de filtrar)
Get-WinEvent -FilterHashtable @{
    LogName='Application'; ProviderName='Cloudflared'; StartTime=(Get-Date).AddDays(-2)
} | Sort-Object TimeCreated | Format-List TimeCreated, Id, Message

# e o que o Gerenciador de Servicos disse — e aqui que aparece falha de partida
Get-WinEvent -FilterHashtable @{
    LogName='System'; StartTime=(Get-Date).AddDays(-2)
    Id=7000,7001,7009,7011,7023,7024,7031,7034
} | Format-List TimeCreated, Id, Message
```

Filtrar com `-MaxEvents 20 | Where-Object {...}` engana: ele pega os 20 mais
recentes do log INTEIRO e só depois filtra, então os registros do boot ficam
de fora e parece que o serviço nunca tentou subir.

### 3c. Aposentar o .bat do túnel

**Apague o atalho do `.bat` do túnel do Startup.** Este passo não é opcional:
rodar o `.bat` com o serviço instalado cria **dois conectores** para o mesmo
túnel, e a Cloudflare aceita isso — ela balanceia as requisições entre os
dois. O sintoma é o pior possível: funciona às vezes, sem erro claro.

Confira em **Tunnels** → `tunel-cotafrete` → aba **Connectors**: tem de
aparecer **uma linha só**.

---

## 4. Login automático da VM

O Cotafrete **precisa** de área de trabalho: o adaptador do Generoso abre o
Chromium com janela de verdade, porque o portal está atrás de um checkpoint
que reprova navegador automatizado. Serviço do Windows e Agendador "sem
logon" rodam na sessão 0, sem tela — não servem para ele.

Ou seja: aqui o login automático é requisito, não comodidade.

> **Antes de tudo: remova o PIN.** Não existe "PIN automático" — o logon
> automático guarda a **senha** e a digita no boot; o PIN é o Windows Hello e
> **impede** o processo. Enquanto houver PIN, o `netplwiz` não tem efeito e a
> VM continua parando na tela de login. Configurações → Contas → **Opções de
> entrada** → **PIN (Windows Hello)** → **Remover**.
>
> **Se a conta estiver vinculada a uma conta Microsoft**, remover o PIN e
> trocar a senha exigem a senha dessa conta Microsoft. Sem ela, o caminho é
> criar uma conta **local dedicada** — foi o que a instalação de 14/09/2026
> precisou fazer. A receita completa (criar a conta, permissão na pasta,
> reinstalar os navegadores do Playwright para o novo usuário) está no
> [`DEPLOY_SERVIDOR.md`](DEPLOY_SERVIDOR.md), no passo do login automático.

Use o `netplwiz`, e **não** o registro:

```
netplwiz
```

Desmarque **"Os usuários devem digitar um nome de usuário e senha"** e
confirme com a senha da conta.

> **Se a caixa não aparecer** (do Windows 10 2004 em diante ela vem
> escondida), rode isto como administrador e abra o `netplwiz` de novo:
> ```powershell
> $k = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device"
> Set-ItemProperty $k DevicePasswordLessBuildVersion 0
> ```

**Por que o `netplwiz` e não o registro:** o método do registro
(`AutoAdminLogon` + `DefaultPassword`) grava a senha **em texto puro**,
legível por qualquer processo da máquina. O `netplwiz` guarda em segredo do
LSA, cifrado. Mesmo resultado, sem a senha exposta.

De qualquer forma: use uma conta **local**, criada só para isso, sem acesso a
mais nada da rede, com senha que não se repete em lugar nenhum.

---

## 5. O atalho do Cotafrete no Startup

O `Servidor.bat` ganhou **modo desatendido**. Use-o no atalho, senão o boot
pode travar — o porquê está logo abaixo.

1. `Win+R` → `shell:startup`
2. Botão direito → **Novo** → **Atalho**
3. No destino, com o `/auto` no fim — **use o caminho real da instalação**,
   que na empresa é `C:\enzo\cotafrete-producao`:
   ```
   C:\enzo\cotafrete-producao\Servidor.bat /auto
   ```
4. Nome: `Cotafrete`

> A trava de pasta continua satisfeita com esse caminho: ela procura
> `cotafrete-producao\` **dentro** do caminho, então o que vem antes não
> importa — só o nome da pasta.

> **Atalho, não cópia.** Copiar o `.bat` para a pasta do Startup é o que fazia
> aparecer *"esta não é a pasta de produção"*: a trava olha de onde o arquivo
> foi aberto, e uma cópia no Startup está, literalmente, fora da pasta de
> produção. Ela existe desde 25/08, quando o servidor subiu da pasta de
> desenvolvimento e quatro cotações reais foram para o banco errado.

**O que o `/auto` muda:** com a porta 8000 ocupada, o arquivo normalmente
**pergunta** se deve encerrar o processo — e espera uma tecla. No boot não há
ninguém para apertá-la: a janela fica parada com a pergunta e o servidor
nunca sobe. De fora, isso é mais um caso de *"está ligado e não abre"*,
indistinguível dos outros.

Com `/auto` ele não pergunta e **não encerra nada**: porta ocupada no boot
quer dizer que o Cotafrete já está no ar, e derrubá-lo para subir outro igual
tiraria a empresa do ar para chegar onde já estava.

---

## 6. A VM subindo com o servidor

No **host** (não na VM), PowerShell como administrador:

```powershell
Set-VM -Name "<nome-da-VM>" -AutomaticStartAction Start -AutomaticStartDelay 60
```

O atraso de 60s dá tempo de a rede do host subir antes da VM.

---

## 7. Desligar o QuickEdit na VM

A saída do `Servidor.bat` já vai para arquivo, então ele está protegido. Mas
o `Monitor.bat` continua escrevendo na tela e congela com um clique — fechar
essa janela não derruba ninguém, mas dá um susto desnecessário.

Num Prompt de Comando na VM:

```
reg add "HKCU\Console" /v QuickEdit /t REG_DWORD /d 0 /f
```

Vale para as janelas abertas daí em diante.

---

## 8. Backup do banco, todo dia

Todo o histórico da empresa — quem cotou, para onde, por quanto, o que cada
transportadora respondeu — vive num arquivo só: `cotafrete.db`. Se a VM se
perder, não há de onde tirar de volta.

**Não copie o arquivo na mão.** O banco roda em WAL (`journal_mode = WAL`), e
nesse modo o que acabou de ser gravado ainda está no `cotafrete.db-wal`. Um
`copy cotafrete.db` com o servidor no ar produz um arquivo que **abre
normalmente e parece íntegro**, só que sem as cotações recentes. É a pior
forma de falhar: silenciosa, e descoberta só no dia de restaurar.

O `Backup.bat` faz o certo — usa a API de backup online do SQLite, que lê
através do WAL, se entende com quem está escrevendo e entrega um arquivo
consistente. **Não precisa parar o servidor.**

### 8a. Escolher onde a cópia cai

Fora da VM. Cópia no mesmo disco não protege contra o que mais acontece: o
disco ou a VM se perderem. Num Prompt de Comando **como administrador**, na
VM:

```
setx /M COTAFRETE_BACKUP_DIR "\\SERVIDOR\backups\cotafrete"
```

Troque pelo compartilhamento real. Se não configurar nada, a cópia cai em
`C:\enzo\cotafrete-producao\backup\` e o próprio script avisa, toda vez, que ela
está na mesma máquina do banco.

O `/M` grava para a máquina inteira, não só para o usuário logado — o
Agendador roda com o ambiente dele, não com o seu. Feche e reabra o Prompt
depois, que `setx` não vale na janela onde foi digitado.

### 8b. Testar à mão, uma vez

Duplo clique no `Backup.bat`. Deve sair algo assim:

```
  Copia:    \\SERVIDOR\backups\cotafrete\cotafrete-20260914-2200.db
  Conteudo: 412 cotacoes, 0.4 MB
```

O número de cotações é a prova de que o WAL entrou. Se aparecer o aviso
`ATENCAO: a copia esta na MESMA maquina`, o passo 8a não pegou.

### 8c. Agendar

Agendador de Tarefas → **Criar Tarefa** (não "Tarefa Básica", que não tem as
opções abaixo):

| aba | campo | valor |
|---|---|---|
| Geral | Nome | `Cotafrete - Backup` |
| Geral | — | **Executar estando o usuário conectado ou não** |
| Geral | — | marcar **Executar com privilégios mais altos** |
| Disparadores | Novo → Diariamente | `22:00` |
| Ações | Programa | `C:\enzo\cotafrete-producao\Backup.bat` |
| Ações | Argumentos | `/auto` |
| Ações | Iniciar em | `C:\enzo\cotafrete-producao` |
| Condições | — | **desmarcar** "Iniciar a tarefa somente se o computador estiver ligado na energia" |

Três detalhes que quebram a tarefa se passarem batido:

- **`/auto`** tira o `pause` do fim. Sem ele a janela fica aberta esperando
  uma tecla que ninguém vai apertar — e a tarefa fica "em execução" para
  sempre, sem rodar no dia seguinte.
- **Iniciar em** precisa estar preenchido. O `.bat` se vira sozinho (`cd /d
  "%~dp0"`), mas o Agendador reclama de ação sem pasta de trabalho.
- **Executar estando o usuário conectado ou não** exige a senha da conta e faz
  a tarefa rodar sem sessão gráfica. É o que se quer: o backup não depende de
  ninguém estar logado.

Depois de criar, clique com o botão direito → **Executar**, e confira em
*Resultado da última execução*: `0x0` é sucesso. Qualquer outra coisa,
o motivo está na janela do `Backup.bat` rodado à mão.

### 8d. O que guardar, e restaurar

A faxina mantém as **14 cópias mais novas** e apaga o resto, para o backup não
virar o motivo de o disco encher. Só apaga arquivos com o nome que ela mesma
gera (`cotafrete-AAAAMMDD-HHMM.db`) — qualquer outra coisa na pasta fica.

Restaurar é copiar a cópia por cima do `cotafrete.db`, **com o servidor
parado**, e apagar o `cotafrete.db-wal` e o `cotafrete.db-shm` que estiverem
do lado — senão o SQLite tenta aplicar um WAL antigo sobre um banco novo.

---

## 9. Conferir tudo

Reinicie o servidor inteiro. Deve dar certo sem ninguém tocar em nada.

| conferir | como | esperado |
|---|---|---|
| a VM subiu sozinha | Hyper-V Manager | `Running` |
| o Windows entrou sozinho | console da VM | área de trabalho, sem tela de senha |
| o Cotafrete abriu | janela `Cotafrete SERVIDOR` | aberta |
| o túnel está de pé | `Get-Service cloudflared` | `Running` |
| **um** conector | painel → Tunnels → Connectors | uma linha só |
| o Cotafrete responde | `https://cotafrete.ventura.inf.br` | pede e-mail, depois abre |
| o site responde | `https://sitenovo.ventura.inf.br` | abre — mesmo com a VM desligada |
| o log existe | `C:\cotafrete-producao\log\servidor.log` | com as mensagens de partida |

**Se o Cotafrete não abrir:** o motivo está em `log\servidor.log`. A janela
também mostra o fim do log quando o servidor para.

---

## Como fica depois de tudo

| peça | onde roda | sobrevive a quê |
|---|---|---|
| site institucional | Cloudflare Pages | a VM pode estar desligada |
| túnel | serviço do Windows, na VM | logoff, clique na janela, queda do processo |
| Cotafrete | sessão gráfica da VM | reinício do servidor |

A VM passa a ter **uma** responsabilidade. E é a única coisa que depende do
login automático — porque é a única que precisa de navegador com janela.

---

## O que continua em aberto

- A pasta `runs\` continua sem cópia. O banco já tem (passo 8); as evidências
  não. Elas expiram em 30 dias sozinhas, então o que se perde é limitado —
  mas é o print que prova o preço para o cliente.
- O `Monitor.bat` ainda escreve na tela. O passo 7 contorna; o conserto de
  verdade é mandar a saída dele para arquivo, como o `Servidor.bat` já faz.
