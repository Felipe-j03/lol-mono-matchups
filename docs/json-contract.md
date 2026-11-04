# Contrato dos JSON exportados (`schema_version` 1)

O que `python -m lolmono export --out site/data` escreve, e o que o site
estático pode supor. Esta é a interface entre as duas metades do projeto.

## Regras que valem para todo arquivo

- **Diretório plano.** Nomes em minúsculas; do nome do campeão sobram só
  `[a-z0-9]` (então "Kai'Sa" vira `kaisa`).
- **Nenhum `puuid`.** É identificador permanente de conta e o site não tem uso
  para ele. Jogadores de referência trazem só o Riot ID.
- **Todo objeto que afirma uma taxa ou uma escolha diz em quantas partidas ela
  se apoia.** Essa é a regra central da spec, e é por isso que denominadores
  aparecem repetidos em vez de serem deduzidos.
- **Todo arquivo traz `schema_version`.** O site busca os arquivos de alvo e de
  confronto direto e os guarda em cache um a um, então a versão por arquivo é
  como ele percebe que um arquivo em cache ficou velho.
- **Saída determinística.** Chaves em ordem fixa, nenhum timestamp, UTF-8 com
  fim de linha Unix. Reexecutar sobre o mesmo banco não muda um byte (a janela
  de coleta é um par de datas calculado das próprias partidas, não do relógio).
- Um alvo sem nenhuma partida confirmada aparece no índice com
  `has_data: false` e não ganha arquivo próprio.

## `index.json`

```json
{
  "schema_version": 1,
  "ddragon_version": "16.21.1",
  "collected_from": "2025-10-01",
  "collected_through": "2025-11-02",
  "targets": [
    { "champion_id": 91, "champion_name": "Talon", "role": "MIDDLE",
      "has_data": true, "file": "talon-middle.json",
      "players": 7, "games": 312 },
    { "champion_id": 79, "champion_name": "Gragas", "role": "TOP",
      "has_data": false, "file": null, "players": 0, "games": 0 }
  ]
}
```

Sempre uma entrada por alvo configurado, na ordem da configuração.

`collected_from` / `collected_through` são as datas UTC (`YYYY-MM-DD`) da partida
mais antiga e da mais nova **efetivamente agregadas**, ou `null` quando nada foi
agregado. São datas e não timestamps de propósito: o dia é a resolução em que
uma janela de patch é lida, e manter datas é o que deixa a exportação idêntica
byte a byte entre duas execuções do mesmo dia. Uma janela larga aqui significa
que a base mistura patches — o site deve mostrá-la.

## `<campeão>-<função>.json`

Escrito só quando `has_data` é verdadeiro.

```json
{
  "schema_version": 1,
  "champion_id": 91, "champion_name": "Talon", "role": "MIDDLE",
  "baseline": {
    "games": 312, "players": 7, "group_win_rate": 0.53,
    "runes": { "keystone": 8112, "primary_style": 8100,
               "primary_perks": [8112, 8126, 8138, 8135],
               "secondary_style": 8000, "secondary_perks": [9111, 9104],
               "shards": [5008, 5008, 5002] },
    "runes_games": 180, "runes_win_rate": 0.55,
    "spells": [4, 14], "spells_games": 290,
    "item_frequency": [ { "item_id": 3142, "games": 250 } ],
    "starting_items": [1055, 2003], "starting_items_games": 240,
    "skill_order": [1, 2, 3], "skill_order_games": 230
  },
  "matchups": [
    { "opponent_champion_id": 245, "games": 40, "wins": 20, "win_rate": 0.5,
      "below_floor": false, "file": "talon-middle-vs-245.json" },
    { "opponent_champion_id": 238, "games": 5, "wins": 3, "win_rate": 0.6,
      "below_floor": true, "file": null }
  ],
  "reference_players": [
    { "riot_id": "Mono#BR1", "platform": "br1", "games": 40, "share": 0.67,
      "win_rate": 0.55 }
  ]
}
```

- A base cobre **todas** as partidas do grupo, vitórias e derrotas juntas:
  descreve o que o grupo faz por padrão, não o que ganha. `runes_win_rate` é a
  taxa de vitória daquela página exata, informação ao lado da base e nunca o
  critério que a escolheu.
- `runes`, `spells` e `starting_items` são **conjuntos completos** (a combinação
  exata mais frequente, porque são escolhas feitas de uma vez antes da partida).
  `item_frequency` é **item por item**, do mais frequente para o menos, porque o
  conjunto exato de seis itens é quase sempre único. `skill_order` são os três
  primeiros pontos.
- `matchups` vem do pior para o melhor; os abaixo do piso vêm depois, por número
  de partidas decrescente, com `below_floor: true` e `file: null`.
- **A lista `matchups` é o índice dos arquivos de confronto.** O site navega a
  partir dela e nunca abre um arquivo que o ranking não lista: execuções
  anteriores podem ter deixado arquivos órfãos de confrontos que caíram abaixo do
  piso, e eles são sujeira, não dado servido.
- Em `reference_players`, `games` são as partidas na janela de coleta e `share` a
  proporção do campeão nessas partidas. `share` conta as partidas **descartadas**
  no denominador: é a proporção sobre o que o jogador jogou, não sobre o que o
  nosso extrator conseguiu ler.

## `<campeão>-<função>-vs-<id do oponente>.json`

Escrito só para confrontos em ou acima de `matchup_min_games`.

```json
{
  "schema_version": 1,
  "champion_id": 91, "champion_name": "Talon", "role": "MIDDLE",
  "opponent_champion_id": 245,
  "games": 40, "wins": 20, "losses": 20, "min_per_side": 15,
  "comparable": true,
  "headline": null,
  "winner_gold_at_14": 5200.0, "loser_gold_at_14": 4000.0,
  "winner_cs_diff_at_14": 8.0, "loser_cs_diff_at_14": -6.0,
  "timeline_games": {
    "gold_at_14":     { "winners": 20, "losers": 20 },
    "cs_diff_at_14":  { "winners": 20, "losers": 20 },
    "starting_items": { "winners": 18, "losers": 17 },
    "skill_order":    { "winners": 20, "losers": 20 }
  },
  "games_without_boots": { "winners": 0, "losers": 0 },
  "divergences": [
    { "field": "boots", "label": "3020",
      "winner_share": 0.8, "loser_share": 0.2, "gap": 0.6,
      "winner_games": 20, "loser_games": 20 }
  ]
}
```

### `divergences`

Só o que **difere**: uma escolha em que os dois grupos concordam não aparece,
porque não é lição. Uma diferença entra quando passa de `gap > 0.15`
(estritamente maior). A lista vem por `gap` decrescente e, em empate, com a
opção que os **vencedores** tomaram mais vezes primeiro.

- `field`: `boots`, `rune`, `starting_items` ou `skill_order`.
- `label`: para `boots`, `rune` e `starting_items` é o id do item ou da runa
  (`"3020"`, `"8347"`), e o site resolve o nome pelo Data Dragon da versão no
  índice. Para `skill_order` já vem legível (`"Q > W > E"`).
- `winner_games` / `loser_games`: **os denominadores daquelas duas proporções**,
  e eles não são os mesmos em todos os campos. `boots` e `rune` são proporções
  sobre todas as partidas do lado; `starting_items` e `skill_order` são
  proporções sobre as partidas daquele lado **que tinham timeline utilizável**.
  Renderizar "80% dos vencedores" contra `wins` erraria a amostra em dois dos
  quatro campos — use sempre estes dois números.

`divergences[0]` é carga pesada: **é dele que o site monta a frase do topo da
tela**, a que resume a maior diferença encontrada. Ele tem `field`, `label` e as
duas proporções com os respectivos denominadores; o `headline` nunca a escreve.

### `headline`

Texto livre, em português, para o jogador. **Nunca nomeia uma escolha**: ids não
são nomes e o site teria que interpretar prosa para resolvê-los. Ele diz só o
que `divergences` não consegue dizer, e pode juntar até três frases:

1. **Não houve divergência** (com `comparable: true`): "Vencedores e perdedores
   fizeram as escolhas de forma igual ...: nenhuma diferença passou de 15 pontos
   percentuais." A afirmação é **escopada aos campos efetivamente comparados**:
   "neste confronto" só quando os quatro foram comparados, e "em botas e runas"
   (ou a lista que for) quando algum não foi. Dizer "fizeram tudo igual, então é
   execução" sem ter olhado itens iniciais seria inventar certeza.
2. **Campos sem timeline suficiente**: "Sem partidas suficientes com timeline
   para comparar: itens iniciais e ordem de habilidades." Só os saltados são
   nomeados.
3. **Botas não reconhecidas**: "Poucas partidas terminaram com um item de botas
   reconhecido, então as botas não foram comparadas." Acontece quando o patch
   trouxe um id de botas que `BOOT_ITEM_IDS` não conhece e metade ou menos das
   partidas de algum dos lados terminou com botas reconhecidas (ver
   `games_without_boots` abaixo).

`headline` é `null` quando o confronto não é comparável, e também quando há
divergências e todos os campos foram comparados — nesse caso não há nada a
acrescentar. Quando há divergências **e** frases 2 ou 3, renderize o `headline`
como nota ao lado das divergências, não em lugar delas.

### Pisos de amostra e ausências

- `comparable: false` (menos de `min_per_side` partidas num dos lados, zero
  incluído) ⇒ `divergences: []`, `headline: null`, as quatro médias `null`.
  `wins`, `losses`, `timeline_games` e `games_without_boots` continuam
  presentes: a ausência é explicada, não escondida.
- `comparable: true` com `divergences: []` é uma resposta de verdade ("não
  diferiram nos campos comparados"): renderize o `headline`.
- `timeline_games` conta partidas com valor **utilizável** (ouro não nulo,
  itens iniciais não vazios, ordem de habilidades não nula), não partidas. São
  esses números que a tela imprime ao lado do ouro e das divergências de timeline.
- As médias de ouro e de diferença de farm são `null` a menos que os **dois**
  lados tenham ao menos `min_per_side` partidas com aquele valor; cada par é ou
  todo presente ou todo nulo. A diferença de farm existe porque a taxa de vitória
  mede a partida inteira: ela e o ouro aos 14 são o que distingue derrota na rota
  de derrota no jogo tardio.
- `games_without_boots` são as partidas de cada lado cuja build final não tinha
  nenhum item de botas reconhecido — normalmente um id de botas mais novo que o
  `BOOT_ITEM_IDS` do coletor. **As botas só são comparadas quando MAIS DA METADE
  das partidas de CADA lado terminou com botas reconhecidas**; abaixo disso o
  campo não é comparado, nenhuma divergência de botas é emitida e o `headline`
  traz a frase "Poucas partidas terminaram com um item de botas reconhecido,
  então as botas não foram comparadas". Uma partida isolada com botas conhecidas
  entre vinte não é evidência de que as botas do confronto foram comparadas.
  Os dois números são exportados nos dois casos, comparação feita ou não: é por
  eles que o site vê o tamanho do ponto cego. Se um deles for alto, a ausência
  de divergência de botas não significa concordância.

## Texto das telas

Correlação não é causa. Se 71% dos vencedores levaram uma runa, não está provado
que a runa fez vencer; pode ser que quem a escolhe seja quem já entendeu o
confronto. O texto das telas fala em **diferença observada**, nunca em
recomendação causal — e o tamanho das duas amostras fica sempre visível.
