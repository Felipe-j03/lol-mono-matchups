# lolmono — coletor e agregação

Coletor de partidas de League of Legends que encontra jogadores **mono** de um
par campeão/função em elo alto, baixa as partidas deles e compara o que os
vencedores de cada confronto fizeram com o que os perdedores fizeram.

O desenho está em
[`docs/superpowers/specs/2026-11-02-lol-mono-matchups-design.md`](docs/superpowers/specs/2026-11-02-lol-mono-matchups-design.md)
e é a autoridade sobre qualquer coisa escrita aqui. O contrato dos JSON que o
site estático lê está em [`docs/json-contract.md`](docs/json-contract.md).

O princípio que atravessa o projeto: **todo número mostrado diz em quantas
partidas se apoia, e dado ausente é relatado como ausente, nunca inventado.**
O pior resultado possível não é quebrar: é estar silenciosamente errado.

## Instalação

Python 3.11 ou mais novo (desenvolvido em 3.13).

```sh
python -m pip install -e .
cp config.example.toml config.toml
export RIOT_API_KEY=RGAPI-...        # no Windows: $env:RIOT_API_KEY = "RGAPI-..."
```

O `pip install -e .` não é opcional: sem ele `python -m lolmono` falha com
"No module named lolmono". A chave fica só na variável de ambiente, nunca em
arquivo — e nunca sai desta máquina, porque o site publicado contém apenas
números já calculados.

Confira a instalação com um comando que não gasta requisição nenhuma:

```sh
python -m lolmono --help
```

## Configuração

`config.toml` (copiado de `config.example.toml`) traz os parâmetros que a spec
manda calibrar contra dados reais, e não contra intuição:

| Campo | O que faz |
|---|---|
| `regions` | plataformas a varrer (`br1`, `kr`, `euw1`, `na1`) |
| `window_games`, `min_share`, `min_games` | o critério de mono (janela 60, 50%, 25 partidas) |
| `min_tier` | elo mínimo; os tiers saem na ordem CHALLENGER, GRANDMASTER, MASTER, DIAMOND |
| `mastery_top_n`, `mastery_max_days` | a severidade da peneira do estágio 2 |
| `matchup_min_games`, `delta_min_per_side` | os pisos de amostra para listar um confronto e para comparar os dois lados |
| `ddragon_version` | versão fixada do Data Dragon |
| `[[targets]]` | os pares campeão/função |

**A severidade da peneira é o parâmetro de custo mais sensível do projeto.**
Peneira frouxa infla o estágio 3, que é o caro; peneira apertada perde mono de
verdade. Calibre contra uma região antes de rodar as quatro.

Ao mudar `ddragon_version`, regenere a lista de botas usada na comparação:

```sh
python tools/derive_boot_items.py 16.21.1
```

e cole a saída em `BOOT_ITEM_IDS`, em `src/lolmono/aggregate.py`. Uma lista de
botas velha não dá erro: ela faz a comparação de botas não ver nada. O que
protege nesse meio-tempo é o campo `games_without_boots` de cada arquivo de
confronto, que conta as partidas cuja build final não tinha botas reconhecidas —
e, quando metade ou menos das partidas de algum dos lados tem botas
reconhecidas, as botas deixam de contar como campo comparado e a tela diz isso
em vez de afirmar que os dois grupos escolheram igual.

A regra da derivação não é só a tag `"Boots"`: ela inclui também os itens cuja
árvore de construção chega em 1001 ou 2422, e exige `maps["11"]` (Summoner's
Rift). Sem a parte da árvore, 3172 (Gunmetal Greaves) fica de fora — é uma
melhoria de nível 3 feita a partir das Berserker's Greaves que a Riot **não**
marca como botas, e é onde as botas de um main de Jax top terminam. Não estreite
a regra de volta para a tag.

## Os quatro comandos, nesta ordem

Por região. Cada estágio só recebe quem passou pelo anterior.

```sh
python -m lolmono ladder    --platform br1
python -m lolmono screen    --platform br1
python -m lolmono matches   --platform br1
python -m lolmono timelines --platform br1
```

1. **`ladder`** — as contas de Challenger, Grão-Mestre e Mestre da fila solo.
   Poucas requisições.
2. **`screen`** — uma requisição de maestria por candidato. Elimina a maioria e
   deixa uma lista curta de suspeitos. Domina em contagem de requisições.
3. **`matches`** — as últimas 60 partidas ranqueadas de cada suspeito, de onde
   saem campeão, função e portanto a concentração real. É o estágio caro.
4. **`timelines`** — uma requisição por partida de confirmado. Extrai os números
   do early game e descarta o JSON cru.

Depois, a agregação (não usa a API nem a chave):

```sh
python -m lolmono export --out site/data
```

E, a qualquer momento, o estado da coleta — também sem a chave:

```sh
python -m lolmono status
```

`status` imprime candidatos, triados e suspeitos por plataforma, os
**confirmados por par campeão/função** (o go/no-go da spec é por par: 60
confirmados que são todos Talon mid não respondem se existe mono de Gragas top)
e a **taxa de descarte acumulada** por motivo. Descarte alto é sinal para
investigar, não para ignorar.

## Rodando as quatro regiões em paralelo

O limite da Riot (20 requisições por segundo, 100 por 2 minutos) é **por
região**, então as quatro regiões têm orçamentos independentes e o tempo total é
o da região mais lenta. Um processo por região, cada um com seu `--platform`:

```sh
for p in br1 kr euw1 na1; do
  python -m lolmono matches --platform "$p" &
done
wait
```

Os quatro processos escrevem no mesmo arquivo SQLite. As transações são curtas
e por lote, e a conexão espera até 30s por um lock, mas se mesmo assim aparecer
`database is locked` o comando sai com código 1 explicando o que fazer: o
progresso já gravado ficou, basta reexecutar aquela região.

## A chave de desenvolvimento expira em 24 horas

Uma coleta completa nas quatro regiões leva horas e **dura mais que uma chave de
desenvolvimento**. Isso não é um detalhe: é a razão de a retomada ser
estruturalmente importante.

Todos os estágios são retomáveis. O progresso é gravado por lote (peneira), por
jogador (partidas) ou por lote de partidas (timelines), e nenhuma requisição
acontece com uma transação aberta. Quando a chave vence, o comando sai com
código 1, diz que o progresso foi mantido, e basta renovar a chave e rodar o
mesmo comando de novo: ele continua de onde parou, sem repetir nada que já foi
pago.

## A amostra crua, para conferir a extração

`timelines` guarda o JSON cru comprimido das primeiras 200 timelines em
`<pasta do banco>/raw-timelines/`, **por padrão**. Essa amostra é a única
conferência que o projeto tem sobre a própria extração: é com ela que se checa,
depois, se `gold_at_14` ou a ordem de habilidades saíram certos de um payload
real. Para mandá-la para outro lugar, `--raw-sample-dir <pasta>`; para não
guardar nada, `--no-raw-sample` — e aí não haverá payload nenhum para conferir.

## Recuperação: apagar o banco e recomeçar

**Apagar o arquivo do banco e recomeçar a coleta é a recuperação prevista**, não
um último recurso embaraçoso. Use quando:

- o comando recusar o banco com `banco incompativel (...)`. São duas recusas
  possíveis e as duas são deliberadas: um banco criado com `timeline.skill_order
  NOT NULL` (partidas curtas seriam descartadas em silêncio e pedidas de novo a
  cada execução), e um banco cujo `match` não tem `game_created` (as partidas
  gravadas não têm data, então uma segunda coleta misturaria dois patches numa
  mesma base sem nenhuma marca). Não existe migração para nenhum dos dois:
  datar uma partida exige baixá-la outra vez.
- o banco tiver sido criado antes dessas correções, mesmo que ainda não tenha
  sido recusado.

```sh
rm data/lolmono.sqlite data/lolmono.sqlite-wal data/lolmono.sqlite-shm
```

O custo é reexecutar a coleta, que é caro em tempo e não em dinheiro. O custo de
não apagar é uma base silenciosamente errada, que é o pior resultado que este
projeto pode produzir.

Há uma terceira recuperação, menor: se o parser de timeline for consertado,
apagar as linhas de `timeline_missing` com `reason = 'parse_error'` devolve
aquelas partidas para a fila sem apagar mais nada.

## Quando a extração quebra de verdade

Os estágios 3 e 4 têm disjuntor: 20 payloads seguidos que o nosso parser não
consegue ler abortam a coleta com código 1 e **sem gravar veredito** para esses
jogadores ou partidas. Eles continuam na fila, para depois de o parser ser
conferido. O que já tinha sido extraído com sucesso foi gravado.

Isso existe porque o estrago silencioso seria pior que o aborto: sem o
disjuntor, um formato novo da Riot faria todo suspeito varrido receber o
veredito "rejeitado", e a fila de suspeitos exclui quem já tem veredito —
consertar o parser não os devolveria, e a recuperação seria apagar o banco e
repagar o estágio caro.

## Testes

```sh
python -m pytest
```

Os cálculos que sustentam os números do produto (concentração de mono, taxa de
vitória por confronto, comparação vencedor contra perdedor) são escritos com
teste antes do código, sobre partidas de mentira com resposta conhecida. São
contas simples, e é exatamente por isso que um erro nelas passa desapercebido.

## Conferência externa

Depois da primeira coleta real, compare a taxa de vitória geral calculada com a
de um site público. Não vai bater exato — a população é outra, só mono de elo
alto. Mas divergência grande (62% nosso contra 50% deles) indica bug, e aparece
em minutos.
