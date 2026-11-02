# Design: análise de matchups a partir de jogadores mono-champion

Data: 2026-11-02
Status: aprovado em brainstorming, pronto para planejamento

## Problema

Um jogador de League of Legends quer saber o que fazer em matchups específicos
dos campeões que joga. Os sites de meta existentes não respondem isso para o
caso dele, por três defeitos que se somam:

1. **Misturam funções.** A build "recomendada" de Talon vem majoritariamente de
   Talon mid; quem joga Talon em outra função recebe conselho de um jogo
   diferente.
2. **Misturam elos.** A mesma página mostra 35% de vitória num matchup no Ouro e
   45% no Esmeralda. O primeiro número mede erro de execução, o segundo mede o
   matchup.
3. **Não filtram o oponente por função.** Pesquisa feita durante o brainstorming
   mostrou o Lolalytics listando Morgana e Ahri entre os campeões que mais
   counteram Jax **no topo**. São picks anormais; a estatística que vem deles não
   ensina nada sobre o jogo real.

A pesquisa também mostrou as fontes se contradizendo entre si e consigo mesmas —
uma página do MetaBot lista Sylas como counter de Talon e, na seção seguinte,
afirma que Talon vai bem contra Sylas. Amostras pequenas (129 partidas no U.GG
para Talon top) produzem oscilações de sete pontos percentuais entre fontes,
apresentadas com a mesma aparência de certeza que amostras de centenas de
milhares.

## Objetivo

Uma aplicação que, para um par campeão/função, mostre o que os jogadores que
**se especializaram** naquele campeão fazem — e, para cada matchup difícil, o
que diferencia quem venceu de quem perdeu.

O recorte é o produto. Não é mais dado que os sites existentes; é dado melhor
delimitado: mono de verdade, função correta, elo alto, matchup separado,
vencedores comparados com perdedores.

## Usuário e escopo

O usuário é um amigo do autor, que joga:

| Campeão  | Função |
|----------|--------|
| Talon    | mid    |
| Gragas   | mid    |
| Gragas   | top    |
| Jax      | top    |
| Renekton | top    |

Matchups que ele relatou como difíceis, usados apenas para validar que o app os
encontra sozinho:

- Talon mid vs **Ekko**
- Jax top e Gragas top vs **Quinn, Gangplank, Renekton**

Esses matchups **não** são configurados no app. O app calcula os piores matchups
a partir dos dados e os ordena. Se Ekko não aparecer no topo da lista de Talon,
isso é resposta: o problema está na execução, não no matchup.

Regiões: BR1, KR, EUW1, NA1.
Elo: Mestre, Grão-Mestre e Challenger. Calibrável para baixo.

## Critério de sucesso

O amigo abre Talon mid vs Ekko e sai com uma decisão concreta que não teria
tirado de um site de meta — e o app diz honestamente "poucos dados" quando for o
caso, em vez de produzir certeza inventada.

## Decisões de design

### Definição de mono-champion

Para um par campeão/função, um jogador se qualifica quando, nas últimas **60**
partidas ranqueadas de fila solo:

- aquele campeão naquela função responde por **>= 50%** das partidas, e
- tem **>= 25** partidas absolutas naquele par.

Os dois critérios juntos são necessários. Só a proporção aceita quem jogou 8 de
12 partidas; só o absoluto aceita o generalista com 30 Talon em 300 partidas.

Terceiro critério, igualmente obrigatório: **elo mínimo**. Mono não quer dizer
bom — existe mono com 45% de vitória, mono por teimosia. Aprender com esse grupo
é aprender os erros dele. O filtro é mono **e** Mestre para cima.

Os três números (janela 60, proporção 50%, mínimo 25) e o elo mínimo ficam em
arquivo de configuração. É esperado ajustá-los após ver dados reais.

### Sem agrupamento por arquétipo

Considerado e descartado. O agrupamento resolveria falta de amostra em matchups
raros fora de função (Talon vs Renekton **mid**). Depois que os matchups
relatados foram reatribuídos aos campeões corretos, todos os matchups de
interesse passaram a ser confrontos padrão com amostra abundante. Agrupar
embaçaria a informação sem ganho.

Fica registrado como saída caso algum matchup específico se mostre raro demais na
prática. Um arquétipo seria implementado como uma lista nomeada de campeões em
configuração, nunca como inferência automática de classe.

### Piso de amostra, obrigatório

Abaixo de um número mínimo de partidas, a tela **não mostra comparação** —
mostra "dados insuficientes" e o número cru. Toda tela do app exibe o tamanho da
amostra, sempre. Sem isso o app apresenta 9 partidas com a mesma aparência de
confiança que 400, e passa a mentir.

O valor do piso fica em configuração. Sugestão inicial: 30 partidas para listar
um matchup, e 15 vitórias mais 15 derrotas para exibir a comparação entre os dois
grupos.

### Pré-computação

A agregação não pode acontecer enquanto o usuário espera. A API da Riot não
permite buscar jogadores por campeão: identificar mono exige varrer as escadas de
ranking e calcular concentração por jogador, o que são milhares de requisições. O
sistema tem duas metades independentes: um **coletor** que o autor roda, e uma
**interface** que apenas lê resultado pronto.

O usuário vê dados do dia anterior, não de agora. Para estudo de matchup isso é
irrelevante.

### Duas camadas: base e desvio

Para cada campeão/função, uma **base**: a configuração mais comum entre os mono —
runas completas com fragmentos, itens iniciais, build, ordem de habilidades,
feitiços. É o "todo jogo começa assim".

A base é calculada sobre **todas** as partidas dos mono, vitórias e derrotas
juntas, porque ela descreve o que o grupo faz por padrão e não o que ganha. A
taxa de vitória da base aparece ao lado dela, como informação, não como critério
de seleção. Calcular a base só sobre vitórias produziria uma configuração
inflada, que parece recomendação sem ter sido testada contra alternativa.

Runas, feitiços e itens iniciais são tratados como **conjuntos completos**: o
conjunto exato mais frequente, porque são escolhas feitas de uma vez, antes da
partida. A build final é tratada **item por item**, pela frequência de cada item
individual, porque o conjunto exato de seis itens é quase sempre único e a
configuração "mais comum" apareceria uma ou duas vezes. A ordem de habilidades é
tratada pelos três primeiros pontos, não pela sequência completa.

Para cada matchup, apenas o **desvio** em relação a essa base. Uma escolha onde
vencedores e perdedores concordam não aparece, porque não é lição. Mostrar só a
diferença é mais acionável que mostrar duas builds completas e deixar o usuário
comparar.

### Site estático

O dado é pré-computado e somente leitura. Ninguém escreve nada pela interface.
Isso torna site estático a resposta certa: o coletor produz arquivos JSON
agregados, publicados em hospedagem estática gratuita (GitHub Pages). O amigo
abre um endereço no navegador, computador ou celular. Sem servidor, sem banco no
ar, sem custo recorrente, sem instalação.

Isso também resolve a distribuição: sem ela, o autor teria que mandar capturas de
tela por mensagem, o que não é um app.

**A chave da API nunca sai da máquina do autor.** Ela vive no coletor. O site
publicado contém apenas números calculados. Chamar a API da Riot diretamente do
navegador exporia a chave a qualquer um que abrisse o inspetor.

Aplicativo desktop foi descartado: empacotamento, distribuição e atualização sem
ganho, já que o app não precisa de dado ao vivo.

## Arquitetura

### Coletor (Python)

Quatro estágios, nesta ordem. A ordem minimiza desperdício: o estágio caro só
recebe quem passou pelos baratos.

**Estágio 1 — escadas.** Por região, buscar as entradas de Challenger,
Grão-Mestre e Mestre da fila solo. Poucas requisições. Produz lista de
candidatos.

**Estágio 2 — peneira por maestria.** Por candidato, uma requisição ao endpoint
de maestria de campeão, pedindo os campeões de maior pontuação. Produz, para cada
jogador, quais campeões ele acumulou mais pontos e quando jogou cada um pela
última vez.

Isso **não prova mono**: pontos de maestria são acumulados pela vida inteira do
jogador, não dizem a função, e não dizem a concentração recente. Serve apenas
como peneira — fica na lista quem tem um dos campeões-alvo entre os primeiros em
pontuação **e** o jogou recentemente. Elimina a esmagadora maioria dos candidatos
e deixa uma lista curta de suspeitos.

O caminho que a spec descrevia antes — calcular concentração a partir dos
identificadores das últimas partidas — é impossível: aquele endpoint devolve
somente os identificadores, sem campeão e sem função.

**Estágio 3 — partidas e confirmação de mono.** Para cada suspeito, buscar os
identificadores das últimas 60 partidas ranqueadas de fila solo e baixar o
conteúdo de cada uma. Só aqui aparecem campeão, função e, portanto, a
concentração real. O jogador é confirmado ou descartado contra os critérios de
mono.

De cada partida, extrair: campeão, função detectada, oponente da mesma função no
time adversário, resultado, itens finais, runas completas com fragmentos,
feitiços, campeões dos dois times.

As partidas dos confirmados são exatamente as que o projeto precisava coletar de
qualquer forma, então não há desperdício nelas. O desperdício se limita às
partidas dos suspeitos que não se confirmam, e é o preço da peneira ser
aproximada. Partidas de jogador não confirmado são marcadas como tal e não entram
em nenhuma agregação.

**Estágio 4 — timeline.** Uma requisição adicional por partida, **apenas das
partidas de jogadores confirmados** no estágio 3. Processar na chegada, extrair e
**descartar o cru**: ouro aos 14 minutos, itens iniciais,
ordem de compra, ordem de habilidades, abates e mortes antes dos 10 minutos,
diferença de farm. Só os quadros até o minuto 15 interessam.

Guardado ficam centenas de bytes por partida em vez de alguns megabytes. O cru
comprimido de algumas centenas de partidas é mantido para conferir a extração.

Uma partida pode envolver dois jogadores rastreados. A deduplicação por
identificador de partida é obrigatória nos estágios 3 e 4.

### Limites de requisição

Chave pessoal: **20 requisições por segundo e 100 por 2 minutos**, aplicadas
**por região**. A chave de produção (500 por 10 segundos, 30 mil por 10 minutos)
exige inscrever o projeto e aprovação da Riot, e não é necessária para uso
privado — chave pessoal não pode ser usada em produto de consumo público, o que
não se aplica aqui.

Como o limite é por região, as quatro regiões rodam em paralelo com orçamentos
independentes. O tempo total é o da região mais lenta.

Estimativa a verificar na prática, a 50 requisições por minuto por região: o
estágio 2 é uma requisição por candidato e domina em contagem, 1 a 1,5 hora por
região. Os estágios 3 e 4 dependem de quantos suspeitos a peneira deixar passar —
se forem algumas dezenas por região, somam 1,5 a 2 horas. Total aproximado de 3
horas com as quatro regiões em paralelo.

**A severidade da peneira é o parâmetro de custo mais sensível do projeto.**
Peneira frouxa infla o estágio 3, que é o caro. Peneira apertada perde mono de
verdade. Ela fica em configuração e deve ser calibrada contra dados de uma região
antes de rodar as quatro.

**O gargalo é o limite da Riot, não a máquina.** O script passa a maior parte do
tempo esperando a próxima janela liberar. Processador rápido não acelera a
coleta; banda e disco importam apenas para os timelines.

O limitador de taxa respeita as duas janelas simultaneamente, a de 1 segundo e a
de 2 minutos.

### Persistência e retomada

SQLite, arquivo único. O coletor **salva progresso a cada passo** e pode ser
interrompido e retomado sem recomeçar. Isso não é refinamento: a coleta leva
horas, a chave estoura limite, a rede cai.

### Agregação

Três cálculos produzem todas as telas:

1. **Base por campeão/função.** Configuração mais comum entre as partidas dos
   mono, com a taxa de vitória dela, quantos mono a usam, e a taxa de vitória
   média do grupo de referência.
2. **Matchups ordenados.** Agrupar as partidas dos mono pelo campeão oponente da
   mesma função, calcular taxa de vitória, descartar os abaixo do piso de
   amostra, ordenar do pior para o melhor.
3. **Desvio por matchup.** Separar vitórias de derrotas, comparar as
   distribuições, emitir apenas onde divergem.

Saída: arquivos JSON por campeão/função e por matchup.

### Interface (HTML, CSS e JavaScript puros)

Sem framework. São três telas somente leitura, sem estado. Um framework
adicionaria passo de build, árvore de dependências e manutenção de segurança sem
resolver nada. Se o app ganhar filtros e estado, a decisão é revisitada.

Ícones, retratos e nomes vêm do **Data Dragon**, o CDN oficial e gratuito da
Riot — a mesma fonte que os sites de meta usam. A versão do Data Dragon é fixada
em configuração, não buscada dinamicamente, para que uma troca de patch não
quebre a página sozinha.

Convenções visuais da categoria (grade de itens, árvore de runas desenhada como
no jogo, linha de matchup com retrato e porcentagem) são adotadas. Dados e marcas
de terceiros não.

**Tela 1 — escolha.** Cinco cartões, um por par campeão/função, cada um
mostrando quantos mono e quantas partidas o sustentam.

**Tela 2 — campeão.** A base no topo, com taxa de vitória da configuração,
número de mono que a usam e taxa de vitória média do grupo de referência.
Abaixo, a lista de matchups do pior para o melhor, com taxa de vitória e número
de partidas por linha. Matchups abaixo do piso aparecem em seção separada,
marcados como dados insuficientes.

Um link lista os mono usados como referência, com nome, região e taxa de vitória,
para que o usuário possa procurar as partidas ou a live do jogador em outro
lugar. O app não recria o op.gg; só diz quem olhar.

**Tela 3 — matchup.** Vencedores e perdedores lado a lado, mostrando apenas o
que difere: botas, runas discordantes, itens iniciais, ordem de habilidades
quando divergir, e o ouro aos 14 minutos dos dois grupos. No topo, uma frase
resumindo a maior diferença encontrada. Tamanho das duas amostras sempre visível.
Se os dois grupos fizeram tudo igual, a tela diz isso — e isso aponta para
execução.

Sem login e sem contas vinculadas.

## Limitações reconhecidas

**Correlação não é causa.** Se 71% dos vencedores levaram determinada runa, não
está provado que a runa fez vencer; pode ser que quem a escolhe seja quem já
entendeu o matchup. O app não tem como separar isso, então o texto das telas fala
em diferença observada, nunca em recomendação causal.

**Taxa de vitória por matchup mede a partida inteira**, não só a rota. O ouro aos
14 minutos e a diferença de farm mitigam isso: permitem distinguir derrota na
rota de derrota no jogo tardio.

**Dados do dia anterior**, não ao vivo. Aceito.

## Verificação

O risco deste projeto não é quebrar — é **estar silenciosamente errado**. Um app
que mostra números plausíveis e falsos é pior que nenhum app, porque o usuário
treina baseado em mentira e nunca desconfia.

**Detecção de função** é o ponto mais frágil. O campo de posição da Riot vem às
vezes vazio ou errado, principalmente em partidas com troca de rota. Sem
tratamento, Gragas jungle contamina a estatística de Gragas top em silêncio.
Regra: toda partida em que as dez posições não formarem cinco pares limpos é
**descartada e contada** num registro. Taxa de descarte alta é sinal para
investigar, não para ignorar.

**Pareamento de oponente** segue a mesma regra: oponente é quem ocupa a mesma
posição no time adversário; se não houver exatamente um, a partida não entra.

**Cálculos** — concentração de mono, taxa de vitória por matchup, comparação
vencedor contra perdedor — escritos com teste antes do código, sobre partidas de
mentira montadas à mão com resposta conhecida. São contas simples, e é por isso
que um erro passa desapercebido.

**Conferência externa.** Comparar a taxa de vitória geral calculada com a dos
sites públicos. Não vai bater exato, porque a população é outra (só mono de elo
alto). Mas divergência grande — 62% nosso contra 50% deles — indica bug, e
aparece em minutos.

**Piso de amostra** tem teste próprio.

## Ordem de construção

1. Cliente da API com limitador de taxa, buscando as escadas de uma região e
   imprimindo jogadores. Valida a parte mais chata.
2. Peneira por maestria em uma região, com relatório de quantos suspeitos ela
   produz por par. Calibra a severidade antes de gastar o estágio caro.
3. **Confirmação de mono em dados reais, numa região só.** Esta etapa é o
   go/no-go do projeto: dos suspeitos, quantos se confirmam como mono de cada
   par? Se a proporção extrapolada para as quatro regiões der algo como 60 por
   par, segue. Se der 4, a premissa é recalibrada por configuração — elo mais
   baixo, concentração menor, janela maior, peneira mais frouxa. Vem antes de
   qualquer linha de interface, porque é a única coisa capaz de matar o projeto, e
   custa uma noite de script descobrir.
4. Coleta completa nas quatro regiões, com timelines, extração e descarte do cru.
4. Agregação produzindo os JSON.
5. Site.

Cada etapa termina em algo observável e conferível. Em nenhum momento há dias de
código não verificado acumulados.

## Pendências a confirmar com o usuário final

- Talon é mid (confirmado pelo autor). Os matchups relatados contra Renekton,
  Gangplank e Quinn pertencem provavelmente a Jax top e Gragas top, não a Talon.
  **Confirmar com o amigo.**
- Se existe mono-Gragas suficiente em mid e em top separadamente. Só os dados da
  etapa 2 respondem.
- O elo do próprio amigo, que informa se Mestre para cima é a referência certa ou
  se vale descer.

## Próxima melhoria, se houver segunda versão

Nada estético. A maior adição de valor seria aprofundar a fase de rotas com os
dados de timeline já coletados: desempenho aos 10 e aos 14 minutos cruzado com o
resultado do matchup, para responder onde o matchup se decide.
