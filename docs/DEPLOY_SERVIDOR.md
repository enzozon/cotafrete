# Subir o Cotafrete no servidor da empresa

O servidor é um **Windows Server 2012 R2**. O Cotafrete **não roda direto
nele** — roda numa máquina virtual Windows dentro dele, no mesmo hardware.

Este documento é o passo a passo dessa instalação.

---

## Por que a máquina virtual, e não direto no servidor

Cinco das seis transportadoras cotam abrindo um navegador de verdade —
inclusive a Jadlog, que apesar de ter API usa o painel (`web/app.py:49`
importa `JadlogPainelAdapter`, não o adapter de API).

O Chromium **110**, de fevereiro de 2023, encerrou o suporte a Windows 7,
8.1, Server 2012 e Server 2012 R2. Não é "sem suporte, mas funciona": o
Google avisou que as páginas simplesmente não carregam. O `requirements.txt`
pede `playwright>=1.45`, que traz Chromium 126.

Voltar o Playwright para a versão 1.29 (dezembro de 2022, último com Chromium
109) faria o navegador abrir — e não resolveria nada:

- A **Generoso** só passa pelo checkpoint da Vercel porque parece um navegador
  atual. A matriz medida em `carriers/base.py:29-36` mostra que qualquer sinal
  de robô devolve "Código 21" ou "Código 29". Um Chromium de quatro anos atrás
  é *mais* suspeito, não menos.
- A **Della Volpe** tem reCAPTCHA v3, com o mesmo problema
  (`carriers/dellavolpe/adapter.py:338-346`).

Ou seja: manter as seis transportadoras exige um Chromium atual, e um Chromium
atual exige Windows 10 ou mais novo. A VM é a forma de ter isso **sem trocar o
servidor da empresa**.

Dois bloqueios menores, na mesma direção: o Python para no 3.12 no Server 2012
R2 (PEP 11), e o `pydantic` 2.x é extensão Rust — o Rust 1.78 também deixou o
Windows 8.1 para trás.

---

## O que é preciso ter antes

| item | por quê |
|---|---|
| Hyper-V habilitado no servidor | é o que roda a VM. Já vem no Server 2012 R2, só ativar a função |
| ~4 GB de RAM e ~60 GB de disco livres | para a VM. Cinco Chromium simultâneos comem memória |
| Licença de Windows para a VM | **Server 2019 ou 2022** se a empresa tiver — é o que o Playwright suporta oficialmente. **Windows 10** também serve: o Chrome mantém suporte a ele até ~2028 |
| O arquivo `.env` de produção | tem as senhas das transportadoras. Não está no Git, tem que ser copiado à mão |

**Windows 11 não dá.** Ele exige TPM virtual, que só existe no Hyper-V a
partir do Server 2016.

---

## 1. Criar o switch de rede — antes da VM

Este é o passo que, se sair errado, deixa tudo instalado e **ninguém consegue
acessar**. A VM precisa de um IP na rede da empresa, e para isso o switch tem
que ser do tipo *externo*, ligado à placa de rede física.

No servidor, Hyper-V Manager → **Virtual Switch Manager** → New → **External**:

- marque a placa de rede que está no cabo da empresa (não o Wi-Fi);
- deixe marcado *"Allow management operating system to share this network
  adapter"* — sem isso o próprio servidor perde a rede.

Switch **Internal** ou **Private** faz a VM enxergar só o servidor. O sistema
sobe, o `Servidor.bat` mostra um IP, e nenhuma máquina da empresa alcança.

---

## 2. Criar a VM

Hyper-V Manager → New → Virtual Machine:

- **Geração 2**;
- 4096 MB de memória, com *Dynamic Memory* desligado (o Chromium oscila muito,
  e a memória dinâmica devolve RAM no meio de uma cotação);
- 2 ou mais processadores virtuais;
- disco de 60 GB;
- conectada ao switch externo do passo 1;
- ISO do Windows escolhido.

Instale o Windows normalmente e aplique as atualizações.

---

## 3. Desligar o modo de sessão avançada

Ainda no Hyper-V Manager, com a VM selecionada: **View → Enhanced Session** →
desmarcado. Nas configurações do host, em *Hyper-V Settings → Enhanced Session
Mode Policy*, desmarque também.

Com a sessão avançada ligada, a janela de conexão é um RDP disfarçado: fechar
a janela **desconecta a sessão**. Com ela desligada, você está olhando para o
console de vídeo da VM — fechar a janela não muda nada do lado de dentro, a
área de trabalho continua viva.

Isso importa porque a Generoso e a Della Volpe exigem navegador **com janela**
(`headless=False`), e janela precisa de área de trabalho. É o mesmo motivo
pelo qual o Cotafrete não pode virar um serviço do Windows: serviço roda na
Sessão 0, que não tem área de trabalho nenhuma.

---

## 4. Instalar o Cotafrete dentro da VM

Dentro da VM, com o Python instalado (marque *"Add Python to PATH"* no
instalador). **3.13 ou 3.14** — o 3.14 está em produção na VM desde
14/09/2026, e é o mesmo da máquina de desenvolvimento, onde a suíte inteira
passa.

```
git clone <url-do-repositorio> C:\cotafrete-producao
cd C:\cotafrete-producao
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
```

> **`git clone` na VM — nunca copiar a pasta de outra máquina.** Um ambiente
> virtual **não é portátil**: o `.venv\Scripts\python.exe` é um lançador que
> guarda o caminho ABSOLUTO do Python que o criou (veja `.venv\pyvenv.cfg`).
> Copiado para outra máquina, ele procura um caminho que não existe:
>
> ```
> did not find executable at 'C:\Users\<outro-usuario>\...\python.exe':
> The system cannot find the path specified.
> ```
>
> Como o `Servidor.bat` sobe o uvicorn por esse lançador, nada sobe — e a
> mensagem cita um usuário que nem existe na VM, o que manda quem está
> diagnosticando para o lado errado. Aconteceu na instalação de 14/09/2026.
> Se a pasta já veio copiada: apague o `.venv` e refaça os três comandos.

O `-m` não é enfeite: `python.exe -m pip` roda o *módulo* pip. Sem ele
(`python.exe pip install ...`) o Python entende `pip` como nome de ARQUIVO e
responde `can't open file '...\pip'`.

Não tem `.venv\Scripts\activate` de propósito. No Windows o `activate` é um
script do PowerShell, e a política de execução padrão recusa scripts —
"running scripts is disabled on this system". Chamar o `python.exe` da venv
direto passa por cima disso sem mexer em política de segurança do servidor, e
é exatamente o que o `Servidor.bat` faz para subir o uvicorn.

**A pasta precisa se chamar `cotafrete-producao`.** O `Servidor.bat` se recusa
a subir de qualquer outra — é a trava que existe desde 25/08/2026, quando
quatro cotações reais foram parar no banco de desenvolvimento. O que está
ACIMA dela não importa: a instalação da empresa vive em
`C:\enzo\cotafrete-producao`, e a trava se dá por satisfeita porque procura
`cotafrete-producao\` no caminho.

**Os navegadores do Playwright são POR USUÁRIO do Windows.** Eles ficam em
`%USERPROFILE%\AppData\Local\ms-playwright`, e o projeto não define
`PLAYWRIGHT_BROWSERS_PATH` para mudar isso. Ou seja: se o sistema passar a
rodar sob outra conta — e o passo 6 faz exatamente isso —, essa conta precisa
rodar o `playwright install chromium` de novo. Sem isso as transportadoras
falham com *"executable doesn't exist"* numa instalação que, por todo o
resto, parece pronta.

**Antes de mexer no `.venv`, feche o `Servidor.bat`.** Arquivo de biblioteca
carregado por um processo vivo não pode ser apagado, e o Windows relata isso
como *"Access to the path ... is denied"* — o que parece problema de
permissão e é, na verdade, arquivo em uso.

Depois copie o `.env` de produção para dentro de `C:\cotafrete-producao`. Ele
não vem no Git. As chaves esperadas:

```
BRASPRESS_USUARIO      BRASPRESS_SENHA
GENEROSO_USUARIO       GENEROSO_SENHA
JADLOG_PAINEL_USUARIO  JADLOG_PAINEL_SENHA
JADLOG_TOKEN           JADLOG_CONTA        JADLOG_CONTRATO
SSW_DOMINIO            SSW_CPF             SSW_USUARIO   SSW_SENHA
TRANSLOVATO_CNPJ       TRANSLOVATO_USUARIO TRANSLOVATO_SENHA
COTAFRETE_ADM_SENHA
```

Teste antes de seguir: rode `Servidor.bat` e abra `http://localhost:8000`
dentro da própria VM. Faça uma cotação real e confira que as cinco
automáticas respondem.

---

## 5. Liberar a porta 8000 no firewall da VM

Sem isto o sistema funciona dentro da VM e mais em lugar nenhum. Num
PowerShell como administrador, dentro da VM:

```powershell
New-NetFirewallRule -DisplayName "Cotafrete 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Domain,Private
```

`-Profile Domain,Private` de propósito: não abre a porta se a VM cair numa
rede pública.

---

## 6. Login automático e início automático

O Cotafrete precisa de uma sessão **logada** para ter área de trabalho. Se a
VM reiniciar e parar na tela de login, o sistema fica fora do ar até alguém
digitar a senha.

Dentro da VM:

```
netplwiz
```

Desmarque **"Os usuários devem digitar um nome de usuário e senha"** e
confirme com a senha da conta.

> Havia aqui um método pelo registro (`AutoAdminLogon` + `DefaultPassword`).
> Ele **gravava a senha em texto puro**, legível por qualquer processo da
> máquina. O `netplwiz` chega ao mesmo resultado guardando em segredo do LSA,
> cifrado — use este.

### O PIN impede o login automático

Não existe "PIN automático": o logon automático guarda a **senha** e a digita
no boot. O PIN é o Windows Hello, e enquanto ele estiver configurado o
`netplwiz` não tem efeito — a VM para na tela de login e o sistema fica fora
do ar até alguém digitar algo.

Remova o PIN em Configurações → Contas → **Opções de entrada** → **PIN
(Windows Hello)** → **Remover**. Se aparecer o interruptor *"Exigir entrada
do Windows Hello"*, desligue antes.

Se a caixa do `netplwiz` não aparecer (do Windows 10 2004 em diante ela vem
escondida), rode como administrador e reabra:

```powershell
$k = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device"
Set-ItemProperty $k DevicePasswordLessBuildVersion 0
```

### Use uma conta local dedicada — e por que isso não é preciosismo

Conta **local**, criada só para isso, sem acesso a mais nada da rede, com
senha que não se repete em lugar nenhum.

Na instalação de 14/09/2026 a VM tinha uma conta local **vinculada a uma
conta Microsoft** (aparecia no `Get-LocalUser`, com foto e nome de uma
pessoa na tela de login). Sem a senha da conta Microsoft não era possível
remover o PIN nem trocar a senha — e sem remover o PIN, não havia login
automático. A saída foi criar a conta dedicada.

Para saber com o que você está lidando:

```powershell
whoami                 # MAQUINA\usuario = local
whoami /upn            # devolve e-mail? entao esta ligada a conta Microsoft
dsregcmd /status | Select-String "AzureAdJoined|DomainJoined"
Get-LocalUser | Format-Table Name, Enabled, PasswordExpires
```

Criando a conta (PowerShell **como administrador**):

```powershell
$senha = Read-Host -AsSecureString "Senha da nova conta"
New-LocalUser -Name "cotafrete" -Password $senha -FullName "Cotafrete" `
  -Description "Conta dedicada ao sistema de cotacoes" -PasswordNeverExpires
Add-LocalGroupMember -Group "Users" -Member "cotafrete"

# a pasta foi criada por OUTRO usuario; sem isto a conta nova nao escreve nela
# (ajuste o caminho — na empresa e C:\enzo\cotafrete-producao)
icacls "C:\cotafrete-producao" /grant "cotafrete:(OI)(CI)M" /T
```

`-PasswordNeverExpires` não é preguiça: a política padrão expira a senha em
42 dias, e no dia em que isso acontecer o login automático para — o sistema
some do ar parecendo mais um "está ligado e não abre".

Depois entre na conta nova, **recuse configurar PIN**, rode o
`playwright install chromium` (os navegadores são por usuário, ver passo 4) e
teste o `Servidor.bat` à mão antes de automatizar. Por fim, apague o atalho
do Startup da conta antiga: duas contas tentando subir o servidor deixam
você sem saber qual instância está no ar.

Não apague a conta antiga — ela é a porta de entrada administrativa da VM.

Depois, um **atalho** do `Servidor.bat` na pasta de inicialização
(`Win+R` → `shell:startup`), com o parâmetro do modo desatendido:

```
C:\cotafrete-producao\Servidor.bat /auto
```

**Atalho, e não cópia:** a trava da pasta de produção olha de onde o arquivo
foi aberto, e uma cópia no Startup está fora dela. E o `/auto` importa — sem
ele, se a porta 8000 já estiver ocupada, o arquivo pergunta se deve encerrar
o processo e fica esperando uma tecla que ninguém vai apertar no boot.

E no servidor (host), nas configurações da VM → **Automatic Start Action** →
*Always start this virtual machine automatically*. Assim, quando o servidor
liga: sobe a VM, a VM loga sozinha, o `Servidor.bat` abre.

> **Publicando na internet?** Se o sistema vai sair da rede local — por túnel
> da Cloudflare ou qualquer outro caminho — siga o
> [`CONFIGURAR_NA_EMPRESA.md`](CONFIGURAR_NA_EMPRESA.md). Ele cobre o túnel
> como serviço e o Cloudflare Access na frente do sistema.
>
> **O login do vendedor já pede senha** (desde 16/09/2026). Mas ele protege o
> caminho, não a máquina: o `Servidor.bat` escuta em `0.0.0.0`, então quem
> estiver na mesma rede alcança a porta 8000 direto. O Access continua sendo
> o que impede a internet inteira de sequer chegar na tela de login.

---

## 7. Descobrir o endereço e avisar a equipe

Com o `Servidor.bat` aberto, a janela mostra o IP. É o endereço que a equipe
digita:

```
http://<ip-da-vm>:8000
```

Peça ao pessoal de rede um **IP fixo** (ou uma reserva no DHCP) para a VM. Se
o IP mudar, o endereço quebra para todo mundo de uma vez.

---

## Operação do dia a dia

| situação | o que fazer |
|---|---|
| Sistema fora do ar | abra a VM pelo Hyper-V Manager e veja se o `Servidor.bat` está aberto. Se não, dê duplo clique nele |
| Reiniciar o sistema | feche a janela do `Servidor.bat` e abra de novo |
| Atualizar o código | **sozinho**, até 5 minutos depois do merge na `main` (ver [Atualização automática](#atualização-automática)). À mão, se a tarefa estiver desligada: feche o `Servidor.bat`, `git checkout main`, `git pull`, `pip install -r requirements.txt`, abra de novo |
| Ver as atualizações | `log\atualizar.log`, na pasta de produção |
| Ver quem está cotando | `Monitor.bat`, dentro da VM. Abre o banco em somente leitura, pode ficar aberto o dia todo |
| Ver o que o servidor falou | `log\servidor.log`, na pasta de produção. O da execução anterior fica em `log\servidor-anterior.log` |

**Nunca feche a janela do `Servidor.bat` durante o expediente** — ela é o
sistema. Fechar desliga para a empresa inteira.

---

## Atualização automática

Depois de cada merge na `main`, a pasta de produção se atualiza sozinha, em
até 5 minutos. Quem faz é o `atualizar.py`, rodado pelo Agendador de
Tarefas do Windows. Ele só age quando o GitHub tem commit novo, e nessa hora:

1. espera as cotações em andamento terminarem, para não matar nenhuma no
   meio;
2. fecha a janela do `Servidor.bat`;
3. faz o `git checkout main` e o `git pull`;
4. roda o `pip install -r requirements.txt` e o `playwright install
   chromium`, **só** se o `requirements.txt` mudou;
5. abre o `Servidor.bat` de novo, numa janela nova, e espera a tela de login
   responder;
6. se ela não responder em 90 s, volta para a versão anterior e abre de novo.
   A versão com defeito não é tentada outra vez; o próximo merge libera.

O servidor fica fora do ar uns 10 segundos, ou mais quando há `pip`. Quem
estiver com a tela aberta só precisa recarregar.

Ele **não** atualiza e só avisa no log quando:

- há arquivo versionado alterado à mão na pasta de produção;
- a pasta tem commit que o GitHub não tem;
- o GitHub não responde.

**Ligar, uma vez só**, logado na conta que sobe o servidor (a do login
automático): dê duplo clique em `Instalar-atualizacao.bat`, na pasta
`cotafrete-producao`. Ele cria a tarefa "Cotafrete - atualizar sozinho".
Para testar na hora, sem esperar os 5 minutos:

```
.venv\Scripts\python.exe atualizar.py
```

Desligar: `.venv\Scripts\python.exe atualizar.py --remover`.

O `git pull` da tarefa usa a mesma senha do GitHub que o `git pull` à mão já
usa, guardada no Windows. Se ela vencer, a tarefa não abre janela pedindo
senha: registra "Não consegui falar com o GitHub" no `log\atualizar.log`, e
basta dar um `git pull` à mão uma vez para renovar.

---

## O clique que congela o servidor (QuickEdit)

Este é o defeito que fazia o sistema ficar **"ligado mas sem abrir"**: a
janela do `Servidor.bat` aberta, a porta respondendo no `netstat`, e nenhuma
página carregando para ninguém.

**O que acontece.** O console do Windows vem de fábrica com o *QuickEdit*
ligado. Com ele, um clique dentro da janela já coloca o console em modo de
seleção — aquele retângulo que aparece ao arrastar o mouse para copiar texto.
Enquanto o console está nesse modo, **qualquer escrita na tela fica parada**,
esperando um Enter ou um Esc que ninguém sabe que precisa dar.

E não para só a escrita: para o **processo inteiro**. O servidor continua
vivo, a porta continua `LISTENING`, o Gerenciador de Tarefas mostra o Python
rodando — e nenhuma requisição é respondida.

**Por que era intermitente.** O servidor roda com `--log-level warning`, ou
seja, quase não escreve nada. O clique *arma* a armadilha; ela só dispara na
escrita seguinte, que pode vir horas depois, quando alguma transportadora
falhar. Por isso nunca batia com "alguém mexeu na janela agora" — e por isso
procurar no lugar óbvio (rede, firewall, IP) nunca achava nada.

**Como está resolvido.** A saída do servidor vai para `log\servidor.log` em
vez da tela. Sem escrita na tela não há o que travar: a janela pode ser
clicada à vontade. Isso vale sozinho e não depende de ninguém configurar nada
na máquina.

**O cinto a mais (opcional, 30 segundos).** Vale desligar o QuickEdit da VM
de qualquer forma, porque ele também congela o `Monitor.bat`:

1. Botão direito na **barra de título** da janela do `Servidor.bat` →
   **Propriedades**.
2. Na aba **Opções**, desmarque **Modo de edição rápida**.
3. **OK**. Vale para as janelas abertas daí em diante.

Para aplicar de uma vez ao usuário da VM, num Prompt de Comando:

```
reg add "HKCU\Console" /v QuickEdit /t REG_DWORD /d 0 /f
```

O `Servidor.bat` **não** faz isso sozinho de propósito: é uma configuração do
usuário do Windows, vale só para janelas abertas depois de mudada, e um
lançador não deve mexer nisso pelas costas de quem usa a máquina.

---

## O que ainda está em aberto

- **A VM não recebe atualização de segurança** se for Windows 10 — o suporte
  terminou em outubro de 2025. O Chrome continua funcionando até ~2028. Se a
  empresa tiver licença de Server 2019 ou 2022, prefira, que continua
  recebendo correções.
