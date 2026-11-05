# Site estático do lolmono — plano de implementação

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam checkbox (`- [ ]`) para acompanhamento.

**Goal:** Três telas somente leitura, servidas como arquivos estáticos, que leem os JSON de `site/data/` e mostram base, matchups e desvio vencedor-vs-perdedor por par campeão/função.

**Architecture:** Módulos ES puros que recebem JSON já parseado e devolvem **string de HTML**; nenhum deles toca `document`. Só `main.js` toca o DOM, faz `fetch` e resolve a rota por hash — e é a única parte sem teste unitário. Isso é o que permite testar tudo em Deno sem shim de DOM e sem build step.

**Tech Stack:** HTML, CSS e JavaScript puros (ES modules, sem framework e sem passo de build, conforme a spec). Data Dragon como CDN de nomes e ícones, versão fixada. Testes com `deno test` — Deno já está instalado na máquina, roda ES modules nativamente e traz runner e asserções embutidos, então o repositório não ganha `package.json` nem `node_modules`. Deno é dependência **de desenvolvimento**: o site publicado não o usa.

**Spec:** `docs/superpowers/specs/2026-11-02-lol-mono-matchups-design.md` (seções "Site estático" e "Interface"), com a interface de dados definida em `docs/json-contract.md`.

## Global Constraints

- **Sem framework e sem passo de build.** Os mesmos arquivos `.js` são importados pelo navegador e pelos testes. Nada de transpilação, bundler ou `node_modules`.
- **`ddragon_version` vem do `index.json`**, nunca buscada dinamicamente nem escrita no código. Hoje `16.21.1`.
- **A chave da API nunca aparece no site.** O site só lê JSON pré-computado; nenhuma chamada à API da Riot a partir do navegador.
- **Todo número exibido vem acompanhado do seu denominador.** É a regra central da spec e do contrato; nenhuma taxa aparece sozinha na tela.
- **`winner_games` / `loser_games` são os denominadores das divergências** e não são iguais em todos os campos. Renderizar proporção de divergência contra `wins`/`losses` erra a amostra em `starting_items` e `skill_order`.
- **O texto fala em diferença observada, nunca em recomendação causal.** Proibido "use esta runa"; permitido "71% dos vencedores levaram".
- **A navegação de matchup sai só da lista `matchups`.** O site nunca monta a URL de um arquivo de confronto por conta própria: arquivos órfãos de execuções anteriores são sujeira, não dado.
- **UTF-8 declarado no HTML.** Há Riot ID com acento nos dados reais.
- **`site/data/` é versionado**, porque o GitHub Pages serve do repositório.

## Review Focus

1. **Riot ID com caracteres de HTML.** `riot_id` é texto escolhido pelo jogador e chega de terceiros; interpolado em `innerHTML` sem escape, `<img onerror=...>` executa no navegador de quem abrir o site. Toda string de dado vai escapada. (Tarefa 1 define o escape; Tarefa 5 prova no Riot ID.)
2. **Id que o Data Dragon fixado não conhece.** Um patch novo traz item ou runa cujo id não está na versão fixada; a tela deve mostrar o id cru, nunca `undefined` nem quebrar. (Tarefa 2.)
3. **Matchup abaixo do piso.** `below_floor: true` vem com `file: null`; precisa aparecer na seção de dados insuficientes e **não** ser clicável. (Tarefa 5.)
4. **Confronto não comparável.** `comparable: false` zera divergências e anula as quatro médias, mas `wins`, `losses`, `timeline_games` e `games_without_boots` continuam presentes: a tela explica a ausência em vez de ficar vazia. (Tarefa 6.)
5. **Rota inexistente.** Hash digitado à mão ou link velho (`#/kaisa-top`) não pode render tela branca. (Tarefa 3.)

---

## Estrutura de arquivos

| arquivo | responsabilidade |
|---|---|
| `site/index.html` | casca: charset, título, container, `<script type="module">` |
| `site/css/style.css` | estilo das três telas; grade de itens e árvore de runas |
| `site/js/format.js` | `escapeHtml`, `pct`, `sample` — usados por todas as telas |
| `site/js/ddragon.js` | carrega e indexa Data Dragon; resolve id → nome e ícone |
| `site/js/route.js` | `parseRoute` e construtores de hash |
| `site/js/screen-choose.js` | Tela 1, do `index.json` |
| `site/js/screen-champion.js` | Tela 2, do arquivo de alvo |
| `site/js/screen-matchup.js` | Tela 3, do arquivo de confronto |
| `site/js/main.js` | `fetch`, cache por `schema_version`, roteamento, escrita no DOM |
| `site/tests/*.test.js` | testes Deno dos módulos puros |
| `deno.json` | tarefa de teste, para o comando ser sempre o mesmo |

Comando de teste do projeto, em todas as tarefas: `deno test site/tests/`

---

### Task 1: Formatação e escape

**Files:**
- Create: `site/js/format.js`, `site/tests/format.test.js`, `deno.json`

**Interfaces:**
- Produces: `escapeHtml(s: string) -> string`; `pct(x: number|null) -> string`; `sample(n: number) -> string`

- [ ] **Step 1: Escrever os testes que falham**

```js
import { assertEquals } from "jsr:@std/assert";
import { escapeHtml, pct, sample } from "../js/format.js";

Deno.test("escapeHtml neutraliza os cinco caracteres perigosos", () => {
  assertEquals(escapeHtml(`<img onerror="x">&'`), "&lt;img onerror=&quot;x&quot;&gt;&amp;&#39;");
});

Deno.test("escapeHtml escapa o & antes dos outros, sem escape duplo", () => {
  assertEquals(escapeHtml("&lt;"), "&amp;lt;");
});

Deno.test("pct arredonda para inteiro e marca ausencia", () => {
  assertEquals(pct(0.5816993464052288), "58%");
  assertEquals(pct(0), "0%");
  assertEquals(pct(null), "—");
});

Deno.test("sample concorda em numero", () => {
  assertEquals(sample(1), "em 1 partida");
  assertEquals(sample(180), "em 180 partidas");
  assertEquals(sample(0), "em 0 partidas");
});
```

- [ ] **Step 2: Rodar para confirmar que falham**

Run: `deno test site/tests/format.test.js`
Expected: FAIL, módulo não encontrado.

- [ ] **Step 3: Implementar os três em `site/js/format.js`**

`escapeHtml` troca `&` primeiro, depois `<`, `>`, `"`, `'` — nessa ordem, ou o teste de escape duplo falha. `pct(null)` devolve travessão porque o contrato anula médias aos pares.

- [ ] **Step 4: Criar `deno.json` com a tarefa de teste**

```json
{ "tasks": { "test": "deno test site/tests/" } }
```

- [ ] **Step 5: Rodar e confirmar que passam**

Run: `deno task test`
Expected: PASS, 4 testes.

- [ ] **Step 6: Commit**

```bash
git add deno.json site/js/format.js site/tests/format.test.js
git commit -m "feat(site): escape de HTML e formatacao de taxa e denominador"
```

---

### Task 2: Data Dragon

**Files:**
- Create: `site/js/ddragon.js`, `site/tests/ddragon.test.js`

**Interfaces:**
- Consumes: nada.
- Produces: `loadDdragon(version: string, fetchFn) -> Promise<Dict>`; `itemName(dict, id) -> string`; `runeName(dict, id) -> string`; `championName(dict, id) -> string`; `championIcon(dict, id) -> string|null`. `Dict` é `{version, items: Map<number,string>, runes: Map<number,string>, champions: Map<number,{name, image}>}`.

`fetchFn` é injetado para que os testes não toquem a rede; `main.js` passa o `fetch` global.

- [ ] **Step 1: Escrever os testes que falham**

```js
Deno.test("loadDdragon indexa item, runa e campeao por id numerico", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  assertEquals(itemName(dict, 3020), "Sorcerer's Shoes");
  assertEquals(runeName(dict, 8112), "Electrocute");
  assertEquals(championName(dict, 91), "Talon");
});

Deno.test("id desconhecido devolve o id cru, nunca undefined", () => {
  const dict = { version: "16.21.1", items: new Map(), runes: new Map(), champions: new Map() };
  assertEquals(itemName(dict, 9999), "9999");
  assertEquals(runeName(dict, 9999), "9999");
  assertEquals(championName(dict, 9999), "9999");
  assertEquals(championIcon(dict, 9999), null);
});

Deno.test("loadDdragon usa a versao recebida nas tres URLs", async () => {
  const vistas = [];
  await loadDdragon("16.21.1", (u) => { vistas.push(u); return fakeFetch(u); });
  assert(vistas.every((u) => u.includes("/16.21.1/")));
  assertEquals(vistas.length, 3);
});
```

`fakeFetch` devolve payloads mínimos no formato do Data Dragon: `item.json` e `champion.json` têm `data` com chave string e campo `name` (campeão traz `key` com o id numérico em string), e `runesReforged.json` é uma lista de árvores com `slots[].runes[]` de `{id, name}`.

- [ ] **Step 2: Rodar para confirmar que falham**

Run: `deno test site/tests/ddragon.test.js`
Expected: FAIL.

- [ ] **Step 3: Implementar em `site/js/ddragon.js`**

Busca `item.json`, `champion.json` e `runesReforged.json` em `https://ddragon.leagueoflegends.com/cdn/<version>/data/en_US/`. Item usa a chave do objeto `data` como id; campeão usa o campo `key`; runa exige descer `slots[].runes[]`. Os quatro resolvedores caem para `String(id)` — `championIcon` para `null` — quando o id não está no mapa.

- [ ] **Step 4: Rodar e confirmar que passam**

Run: `deno task test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add site/js/ddragon.js site/tests/ddragon.test.js
git commit -m "feat(site): carga e indexacao do Data Dragon com queda para id cru"
```

---

### Task 3: Rotas

**Files:**
- Create: `site/js/route.js`, `site/tests/route.test.js`

**Interfaces:**
- Produces: `parseRoute(hash: string) -> {screen: "choose"} | {screen: "champion", slug} | {screen: "matchup", slug, opponentId} | {screen: "notfound", hash}`; `championHash(slug) -> string`; `matchupHash(slug, opponentId) -> string`

- [ ] **Step 1: Escrever os testes que falham**

```js
Deno.test("hash vazio e raiz caem na tela de escolha", () => {
  for (const h of ["", "#", "#/"]) assertEquals(parseRoute(h).screen, "choose");
});

Deno.test("rota de campeao e de confronto", () => {
  assertEquals(parseRoute("#/talon-middle"), { screen: "champion", slug: "talon-middle" });
  assertEquals(parseRoute("#/talon-middle/vs/245"),
    { screen: "matchup", slug: "talon-middle", opponentId: 245 });
});

Deno.test("rota malformada e notfound, nunca excecao nem tela vazia", () => {
  for (const h of ["#/talon-middle/vs/abc", "#/a/b/c/d", "#/talon-middle/vs/"]) {
    assertEquals(parseRoute(h).screen, "notfound");
  }
});

Deno.test("construtores produzem exatamente o formato que as telas escrevem", () => {
  // As strings literais abaixo sao o contrato com a Tarefa 5, que afirma
  // href="#/talon-middle/vs/245" direto. Um round-trip com o parser passaria
  // com qualquer formato inventado aqui e quebraria aquela tarefa.
  assertEquals(championHash("talon-middle"), "#/talon-middle");
  assertEquals(matchupHash("talon-middle", 245), "#/talon-middle/vs/245");
});

Deno.test("construtores casam com o parser", () => {
  assertEquals(parseRoute(championHash("jax-top")).slug, "jax-top");
  const r = parseRoute(matchupHash("jax-top", 58));
  assertEquals([r.slug, r.opponentId], ["jax-top", 58]);
});
```

- [ ] **Step 2: Rodar para confirmar que falham**

Run: `deno test site/tests/route.test.js` — Expected: FAIL.

- [ ] **Step 3: Implementar em `site/js/route.js`**

`opponentId` só é aceito se casar `/^\d+$/`; qualquer outra forma é `notfound`. O slug não é validado contra o índice aqui — isso é trabalho de `main.js`, que tem o `index.json`.

- [ ] **Step 4: Rodar e confirmar que passam** — Run: `deno task test` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add site/js/route.js site/tests/route.test.js
git commit -m "feat(site): roteamento por hash com rota invalida explicita"
```

---

### Task 4: Tela 1 — escolha

**Files:**
- Create: `site/js/screen-choose.js`, `site/tests/screen-choose.test.js`

**Interfaces:**
- Consumes: `format.js`, `route.js`, `ddragon.js`.
- Produces: `renderChoose(index, dict) -> string`

- [ ] **Step 1: Escrever os testes que falham**

```js
Deno.test("um cartao por alvo, com monos e partidas", () => {
  const html = renderChoose(INDEX, DICT);
  assert(html.includes("Talon"));
  assert(html.includes("7 monos"));
  assert(html.includes("312 partidas"));
});

Deno.test("alvo sem dado nao e clicavel e diz que nao tem dado", () => {
  // indice com UM alvo so, has_data: false, para a ausencia de href ser inequivoca
  const html = renderChoose({ ...INDEX, targets: [INDEX.targets[1]] }, DICT);
  assert(!html.includes("href"));
  assert(html.includes("Sem dados"));
});

Deno.test("a janela de coleta aparece na tela", () => {
  assert(renderChoose(INDEX, DICT).includes("2025-10-01"));
  assert(renderChoose(INDEX, DICT).includes("2025-11-02"));
});

Deno.test("janela nula nao imprime null", () => {
  const html = renderChoose({ ...INDEX, collected_from: null, collected_through: null }, DICT);
  assert(!html.includes("null"));
});
```

`INDEX` é o `index.json` do contrato, com um alvo `has_data: true` e um `has_data: false`.

- [ ] **Step 2: Rodar para confirmar que falham** — Expected: FAIL.

- [ ] **Step 3: Implementar `renderChoose` em `site/js/screen-choose.js`**

Cartão com retrato do Data Dragon, nome do campeão, função, contagem de monos e de partidas. `has_data: false` render sem `<a>`. A janela de coleta vai no rodapé da tela, com a nota de que janela larga mistura patches.

- [ ] **Step 4: Rodar e confirmar que passam** — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add site/js/screen-choose.js site/tests/screen-choose.test.js
git commit -m "feat(site): tela de escolha com alvo sem dado nao clicavel"
```

---

### Task 5: Tela 2 — campeão

**Files:**
- Create: `site/js/screen-champion.js`, `site/tests/screen-champion.test.js`

**Interfaces:**
- Consumes: `escapeHtml`, `pct`, `sample` de `format.js`; `championHash`, `matchupHash` de `route.js`; `itemName`, `runeName`, `championName`, `championIcon` de `ddragon.js`.
- Produces: `renderChampion(target, dict) -> string`

- [ ] **Step 1: Escrever os testes que falham**

```js
Deno.test("base mostra runas, feiticos e itens com os denominadores de cada um", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes("em 180 partidas"));   // runes_games
  assert(html.includes("em 290 partidas"));   // spells_games
  assert(html.includes("55%"));               // runes_win_rate
  assert(html.includes("53%"));               // group_win_rate
});

Deno.test("matchups do pior para o melhor, acima do piso sao clicaveis", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes('href="#/talon-middle/vs/245"'));
});

Deno.test("matchup abaixo do piso aparece em secao propria e sem link", () => {
  // alvo cujos matchups sao TODOS below_floor, para a ausencia de link ser inequivoca
  const t = { ...TARGET, matchups: [TARGET.matchups[1]] };
  const html = renderChampion(t, DICT);
  assert(html.includes("Dados insuficientes"));
  assert(html.includes("5 partidas"));
  assert(!html.includes("/vs/"));
});

Deno.test("Riot ID com HTML sai escapado", () => {
  const t = { ...TARGET, reference_players: [
    { riot_id: '<img onerror="x">#BR1', platform: "br1", games: 40, share: 0.67, win_rate: 0.55 }] };
  const html = renderChampion(t, DICT);
  assert(!html.includes("<img onerror"));
  assert(html.includes("&lt;img onerror"));
});

Deno.test("share do jogador de referencia aparece como proporcao do que ele jogou", () => {
  assert(renderChampion(TARGET, DICT).includes("67%"));
});
```

- [ ] **Step 2: Rodar para confirmar que falham** — Expected: FAIL.

- [ ] **Step 3: Implementar `renderChampion` em `site/js/screen-champion.js`**

Base no topo; a lista de matchups na ordem em que o JSON entrega, com os `below_floor` numa seção separada. `reference_players` fica atrás de uma revelação (`<details><summary>`), que é o "link" que a spec pede, com Riot ID, região, partidas, share e taxa de vitória — toda string passando por `escapeHtml`. Links de matchup só via `matchupHash` e só quando `file` não é nulo.

- [ ] **Step 4: Rodar e confirmar que passam** — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add site/js/screen-champion.js site/tests/screen-champion.test.js
git commit -m "feat(site): tela de campeao com piso de amostra e Riot ID escapado"
```

---

### Task 6: Tela 3 — matchup

**Files:**
- Create: `site/js/screen-matchup.js`, `site/tests/screen-matchup.test.js`

**Interfaces:**
- Consumes: `escapeHtml`, `pct`, `sample` de `format.js`; `itemName`, `runeName`, `championName` de `ddragon.js`. **Não** usa `route.js`: esta tela é folha.
- Produces: `renderMatchup(matchup, dict) -> string`

- [ ] **Step 1: Escrever os testes que falham**

```js
Deno.test("divergencia usa winner_games e loser_games, nao wins e losses", () => {
  const m = { ...MATCHUP, wins: 20, losses: 20, divergences: [
    { field: "starting_items", label: "1055", winner_share: 0.5, loser_share: 0.1,
      gap: 0.4, winner_games: 18, loser_games: 17 }] };
  const html = renderMatchup(m, DICT);
  assert(html.includes("18"));
  assert(html.includes("17"));
});

Deno.test("frase do topo e montada da divergencia, sem id cru", () => {
  const html = renderMatchup(MATCHUP, DICT);   // divergences[0] e botas 3020
  assert(html.includes("Sorcerer's Shoes"));
  // O id NAO pode aparecer como texto visivel. A negativa e escopada ao no de
  // texto de proposito: um icone do Data Dragon tem o id na URL
  // (item/3020.png), e proibir "3020" no HTML inteiro reprovaria uma
  // implementacao correta que mostra o icone.
  assert(!html.includes(">3020<"));
});

Deno.test("nao comparavel explica a ausencia e mantem os numeros", () => {
  const m = { ...MATCHUP, comparable: false, divergences: [], headline: null,
    winner_gold_at_14: null, loser_gold_at_14: null,
    winner_cs_diff_at_14: null, loser_cs_diff_at_14: null,
    games: 32, wins: 14, losses: 18, min_per_side: 15 };
  const html = renderMatchup(m, DICT);
  assert(html.includes("14"));
  assert(html.includes("18"));
  assert(html.includes("15"));
  assert(!html.includes("null"));
  assert(html.length > 200);
});

Deno.test("comparavel sem divergencia render o headline como resposta", () => {
  const m = { ...MATCHUP, divergences: [], headline: "Vencedores e perdedores fizeram as escolhas de forma igual em botas e runas: nenhuma diferenca passou de 15 pontos percentuais." };
  assert(renderMatchup(m, DICT).includes("nenhuma diferenca passou"));
});

Deno.test("ponto cego de botas fica visivel", () => {
  const m = { ...MATCHUP, games_without_boots: { winners: 12, losers: 11 } };
  const html = renderMatchup(m, DICT);
  assert(html.includes("12"));
  assert(html.includes("11"));
});

Deno.test("ouro aos 14 nulo nao imprime numero nem zero", () => {
  const m = { ...MATCHUP, winner_gold_at_14: null, loser_gold_at_14: null,
    timeline_games: { ...MATCHUP.timeline_games, gold_at_14: { winners: 0, losers: 0 } } };
  const html = renderMatchup(m, DICT);
  assert(!html.includes("null"));
  assert(!/\b0 de ouro\b/.test(html));
});
```

- [ ] **Step 2: Rodar para confirmar que falham** — Expected: FAIL.

- [ ] **Step 3: Implementar `renderMatchup` em `site/js/screen-matchup.js`**

Vencedores e perdedores lado a lado, só o que difere. Cada divergência resolve `label` pelo Data Dragon conforme o `field` (`boots` e `starting_items` por item, `rune` por runa, `skill_order` já legível) e imprime as duas proporções com `winner_games` / `loser_games`. A frase do topo é montada de `divergences[0]`; o `headline`, quando não nulo, entra como nota ao lado — nunca em lugar das divergências. Texto sempre em diferença observada.

- [ ] **Step 4: Rodar e confirmar que passam** — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add site/js/screen-matchup.js site/tests/screen-matchup.test.js
git commit -m "feat(site): tela de matchup com denominadores por campo e ausencia explicada"
```

---

### Task 7: Casca, estilo e ligação

**Files:**
- Create: `site/index.html`, `site/css/style.css`, `site/js/main.js`
- Modify: `.gitignore` (garantir que `site/data/` **não** está ignorado)

**Interfaces:**
- Consumes: todos os módulos anteriores.

- [ ] **Step 1: Escrever `site/index.html`**

`<!doctype html>`, `<meta charset="utf-8">`, `<meta name="viewport">` (a spec promete celular), um `<main id="app">` e `<script type="module" src="js/main.js">`. Nenhum dado embutido.

- [ ] **Step 2: Implementar `main.js`**

Carrega `index.json`, deriva `ddragon_version` dele e chama `loadDdragon` com o `fetch` global. A cada `hashchange` e na carga, `parseRoute` decide a tela; `champion` e `matchup` buscam o arquivo pelo nome que o **JSON** informa (`targets[].file` e `matchups[].file`), nunca por nome montado. Slug fora do índice e `notfound` renderizam a tela de escolha com um aviso. Cache por arquivo em `sessionStorage`, invalidado quando o `schema_version` lido difere do guardado.

- [ ] **Step 3: Escrever `site/css/style.css`**

Grade de itens, árvore de runas e linha de matchup com retrato e porcentagem, conforme as convenções da categoria que a spec adota. Legível em telefone.

- [ ] **Step 4: Rodar a suíte inteira**

Run: `deno task test`
Expected: PASS, todos os testes das tarefas 1 a 6.

- [ ] **Step 5: Verificar no navegador**

Primeiro povoar `site/data/`, que nasce vazio nesta worktree: `python -m lolmono export --out site/data` (não usa a API nem a chave; lê o banco de `data/lolmono.sqlite`). Se o banco não existir aqui, copie-o do checkout principal.

Então servir `site/` (`python -m http.server -d site 8000`) e conferir: a tela de escolha lista os cinco pares; um par com dado abre a Tela 2; um matchup acima do piso abre a Tela 3; `#/kaisa-top` não deixa a tela branca; e um Riot ID com acento aparece correto (prova do charset).

- [ ] **Step 6: Commit**

```bash
git add site/index.html site/css/style.css site/js/main.js .gitignore
git commit -m "feat(site): casca, estilo e ligacao das tres telas"
```

---

## Fora deste plano

- **Publicação no GitHub Pages.** Depende de repositório remoto e é configuração, não código.
- **`collected_from` como mínimo extremo.** Medido em 05/11: 85% das partidas estão nos últimos 30 dias, mas duas partidas de julho fazem o índice anunciar uma janela de três meses e meio, subvendendo o dado. A correção é no exportador (publicar a distribuição, não só o mínimo), não no site. O site, por ora, mostra a janela como o contrato manda.
