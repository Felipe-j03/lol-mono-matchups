import { assert } from "jsr:@std/assert";
import { renderChampion } from "../js/screen-champion.js";

const TARGET = {
  schema_version: 1,
  champion_id: 91, champion_name: "Talon", role: "MIDDLE",
  baseline: {
    games: 312, players: 7, group_win_rate: 0.53,
    runes: { keystone: 8112, primary_style: 8100,
             primary_perks: [8112, 8126, 8138, 8135],
             secondary_style: 8000, secondary_perks: [9111, 9104],
             shards: [5008, 5008, 5002] },
    runes_games: 180, runes_win_rate: 0.55,
    spells: [4, 14], spells_games: 290,
    item_frequency: [{ item_id: 3142, games: 250 }, { item_id: 6693, games: 101 }],
    starting_items: [1055, 2003], starting_items_games: 240,
    skill_order: [1, 2, 3], skill_order_games: 230,
  },
  matchups: [
    { opponent_champion_id: 245, games: 40, wins: 20, win_rate: 0.5,
      below_floor: false, file: "talon-middle-vs-245.json" },
    { opponent_champion_id: 238, games: 5, wins: 3, win_rate: 0.6,
      below_floor: true, file: null },
  ],
  reference_players: [
    { riot_id: "Mono#BR1", platform: "br1", games: 40, share: 0.67, win_rate: 0.55 },
  ],
};

const DICT = {
  version: "16.21.1",
  items: new Map([[3142, "Youmuu's Ghostblade"], [6693, "Prowler's Claw"],
                  [1055, "Doran's Blade"], [2003, "Health Potion"]]),
  runes: new Map([[8112, "Electrocute"], [8100, "Domination"], [8000, "Precision"],
                  [8126, "Cheap Shot"], [8138, "Eyeball Collection"], [8135, "Treasure Hunter"],
                  [9111, "Triumph"], [9104, "Legend: Alacrity"]]),
  spells: new Map([[4, "Flash"], [14, "Ignite"]]),
  champions: new Map([[91, { name: "Talon", image: "Talon.png" }],
                      [245, { name: "Ekko", image: "Ekko.png" }],
                      [238, { name: "Zed", image: "Zed.png" }]]),
};

Deno.test("base mostra runas, feiticos e itens com os denominadores de cada um", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes("em 180 partidas"));   // runes_games
  assert(html.includes("em 290 partidas"));   // spells_games
  assert(html.includes("55%"));               // runes_win_rate
  assert(html.includes("53%"));               // group_win_rate
});

Deno.test("itens iniciais e ordem de habilidades trazem o proprio denominador", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes("em 240 partidas"));   // starting_items_games
  assert(html.includes("em 230 partidas"));   // skill_order_games
  assert(html.includes("Doran&#39;s Blade"));
  assert(!html.includes("Doran's Blade"));
  assert(html.includes("Q &gt; W &gt; E"));
});

Deno.test("feiticos aparecem pelo nome, nao pelo id", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes("Flash</span>"));
  assert(html.includes("Ignite</span>"));
  assert(!html.includes("4, 14"));
});

Deno.test("slot de habilidade desconhecido renderiza como o proprio numero", () => {
  const t = { ...TARGET, baseline: { ...TARGET.baseline, skill_order: [1, 5, 4] } };
  assert(renderChampion(t, DICT).includes("Q &gt; 5 &gt; R"));
});

Deno.test("cada item da frequencia traz suas partidas sobre o total", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes("250 de 312 partidas"));
  assert(html.includes("101 de 312 partidas"));
});

Deno.test("fragmentos aparecem pelo nome da tabela, nao pelo id cru", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes("Força Adaptativa"));
  assert(html.includes("Armadura"));
  // nenhuma URL deste HTML carrega esses ids, entao a ausencia vale para o HTML todo
  assert(!/\b5008\b/.test(html));
  assert(!/\b5002\b/.test(html));
});

Deno.test("runas aparecem pelo nome do Data Dragon", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes("Electrocute"));
  assert(html.includes("Domination"));
  assert(html.includes("Triumph"));
});

Deno.test("taxa da pagina de runas nao e apresentada como criterio de escolha", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes("mais frequente"));
  assert(!/recomend|use esta|melhor runa/i.test(html));
});

Deno.test("matchups do pior para o melhor, acima do piso sao clicaveis", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes('href="#/talon-middle/vs/245"'));
  assert(html.includes("Ekko"));
  assert(html.includes("em 40 partidas"));
});

Deno.test("matchups seguem a ordem do JSON, sem reordenar", () => {
  const a = { ...TARGET.matchups[0], opponent_champion_id: 245, win_rate: 0.9, games: 50 };
  const b = { ...TARGET.matchups[0], opponent_champion_id: 238, win_rate: 0.1, games: 20,
              file: "talon-middle-vs-238.json" };
  const html = renderChampion({ ...TARGET, matchups: [a, b] }, DICT);
  assert(html.indexOf("Ekko") < html.indexOf("Zed"));
});

Deno.test("matchup abaixo do piso aparece em secao propria e sem link", () => {
  // alvo cujos matchups sao TODOS below_floor, para a ausencia de link ser inequivoca
  const t = { ...TARGET, matchups: [TARGET.matchups[1]] };
  const html = renderChampion(t, DICT);
  assert(html.includes("Dados insuficientes"));
  assert(html.includes("5 partidas"));
  assert(html.includes("Zed"));
  assert(!html.includes("/vs/"));
  // sem confronto acima do piso, o ranking nao fica vazio: a ausencia e explicada
  assert(!/<ul class="matchups">/.test(html));
  assert(html.includes("Nenhum confronto atingiu o piso de partidas, então nenhum ganhou página própria."));
});

Deno.test("com confronto acima do piso nao ha aviso de ranking vazio", () => {
  assert(!renderChampion(TARGET, DICT).includes("Nenhum confronto atingiu o piso"));
});

Deno.test("o slug do link vem do file do confronto, nao do nome do campeao", () => {
  const m = { ...TARGET.matchups[0], file: "kaisa-bottom-vs-245.json" };
  const html = renderChampion({ ...TARGET, champion_name: "Kai'Sa", matchups: [m] }, DICT);
  assert(html.includes('href="#/kaisa-bottom/vs/245"'));
});

Deno.test("abaixo do piso fica sob o titulo da secao e so ele perde o link", () => {
  const html = renderChampion(TARGET, DICT);
  const ekko = html.indexOf("Ekko");
  const titulo = html.indexOf("Dados insuficientes");
  const zed = html.indexOf("Zed");
  assert(ekko !== -1 && ekko < titulo && titulo < zed);
  assert(html.includes('href="#/talon-middle/vs/245"'));
  assert(!html.includes("/vs/238"));
  assert((html.match(/href="#\//g) ?? []).length === 1);
});

Deno.test("abaixo do piso mostra so a contagem, sem taxa de vitoria", () => {
  const t = { ...TARGET, matchups: [TARGET.matchups[1]] };  // Zed, win_rate 0.6
  const html = renderChampion(t, DICT);
  assert(html.includes("em 5 partidas"));
  assert(!html.includes("60%"));
});

Deno.test("a cor da taxa segue o valor, e 50% conta como bom", () => {
  // A cor e so reforco de um numero ja escrito, mas e logica: trocar >= por >,
  // ou inverter as classes, pintaria de vermelho um confronto favoravel e
  // ninguem notaria, porque o texto continuaria certo.
  const com = (wr) => renderChampion(
    { ...TARGET, matchups: [{ ...TARGET.matchups[0], win_rate: wr }] },
    DICT,
  );
  assert(com(0.62).includes('class="wr wr-bom"'));
  assert(com(0.38).includes('class="wr wr-ruim"'));
  assert(com(0.5).includes('class="wr wr-bom"'));      // a borda exata
  assert(com(0.49).includes('class="wr wr-ruim"'));
  // e o numero continua escrito, com ou sem cor
  assert(com(0.38).includes("38%"));
});

Deno.test("itens iniciais e habilidades nulos (timeline nao coletada) nao derrubam a tela", () => {
  for (const [campo, jogos] of [["starting_items", "starting_items_games"],
                                ["skill_order", "skill_order_games"]]) {
    const t = { ...TARGET, baseline: { ...TARGET.baseline, [campo]: null, [jogos]: 0 } };
    const html = renderChampion(t, DICT);
    assert(html.includes("Sem dado"), campo);
    assert(html.includes("em 0 partidas"), campo);
    assert(!html.includes("null"), campo);
    assert(!html.includes("undefined"), campo);
  }
});

Deno.test("uma partida aparece no singular", () => {
  const b = { ...TARGET.baseline, games: 1, item_frequency: [{ item_id: 3142, games: 1 }] };
  const players = [{ ...TARGET.reference_players[0], games: 1 }];
  const html = renderChampion({ ...TARGET, baseline: b, reference_players: players }, DICT);
  assert(html.includes("1 de 1 partida<"));
  assert(html.includes("1 partida,"));
  assert(!html.includes("1 partidas"));
});

Deno.test("sem matchup abaixo do piso nao ha secao de dados insuficientes", () => {
  const t = { ...TARGET, matchups: [TARGET.matchups[0]] };
  assert(!renderChampion(t, DICT).includes("Dados insuficientes"));
});

Deno.test("jogadores de referencia ficam atras de um details", () => {
  const html = renderChampion(TARGET, DICT);
  const d = html.indexOf("<details class=\"reference-players\"");
  assert(d !== -1);
  assert(html.includes("<summary"));
  assert(html.indexOf("Mono#BR1") > d);
  assert(html.indexOf("Mono#BR1") < html.indexOf("</details>", d));
  assert(html.includes("br1"));
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

Deno.test("o nome do alvo vem do JSON e o do oponente do Data Dragon", () => {
  const dict = { ...DICT, champions: new Map([[245, { name: "Ekko", image: "Ekko.png" }]]) };
  const html = renderChampion(TARGET, dict);
  assert(html.includes("<h1>Talon"));
  assert(html.includes("Ekko"));
  // oponente fora do dict: cai para o id, nunca undefined
  assert(html.includes("238"));
  assert(!html.includes("undefined"));
});

function comItens(freq, games = 1000) {
  const b = { ...TARGET.baseline, games, item_frequency: freq };
  return renderChampion({ ...TARGET, baseline: b }, DICT);
}
const linhasDeItem = (html) => (html.match(/ de \d+ partidas<\/span><\/li>/g) ?? []).length;
const itens = (n, games, desde = 1) =>
  Array.from({ length: n }, (_, k) => ({ item_id: 1000 + desde + k, games }));

Deno.test("itens: o titulo diz inventario ao fim, nao build pronta", () => {
  // O dado e o conteudo dos seis espacos quando o jogo acabou, e no exportado real
  // ele traz componente nao evoluido (Espada Longa, Picareta) entre os mais
  // frequentes. Chamar isso de "itens finais" promete build montada e faz quem
  // compara com um site de meta achar que o numero esta errado — o numero esta
  // certo, o rotulo e que prometia demais.
  const html = renderChampion(TARGET, DICT);
  assert(html.includes("Itens no inventário ao fim da partida"));
  assert(!html.includes("Itens finais"));
  assert(html.includes("não a build completa"));
});

Deno.test("itens: o teto de 12 corta mesmo quando todos passam do piso de 5%", () => {
  const html = comItens(itens(20, 100));   // 20 itens a 10%: so o teto separa
  assert(linhasDeItem(html) === 12);
  assert(html.includes("Mostrando 12 de 20 itens"));
  assert(html.includes("5% das 1000 partidas"));
});

Deno.test("itens: o piso de 5% corta mesmo quando a lista e menor que o teto", () => {
  const freq = [...itens(3, 200), ...itens(30, 10, 100)];   // 3 acima, 30 a 1%: so o piso separa
  const html = comItens(freq);
  assert(linhasDeItem(html) === 3);
  assert(html.includes("Mostrando 3 de 33 itens"));
});

Deno.test("itens: exatamente 5% entra, logo abaixo nao", () => {
  const html = comItens([{ item_id: 1001, games: 50 }, { item_id: 1002, games: 49 }]);
  assert(linhasDeItem(html) === 1);
  assert(html.includes("50 de 1000 partidas"));
  assert(!html.includes("49 de 1000"));
});

Deno.test("itens: sem corte nao ha aviso de truncamento", () => {
  assert(!renderChampion(TARGET, DICT).includes("Mostrando"));
});

Deno.test("abaixo do piso: lista dentro de details cujo summary traz a contagem", () => {
  const muitos = Array.from({ length: 80 }, (_, k) => ({
    opponent_champion_id: 5000 + k, games: 3, wins: 1, win_rate: 0.33,
    below_floor: true, file: null,
  }));
  const html = renderChampion({ ...TARGET, matchups: [TARGET.matchups[0], ...muitos] }, DICT);
  const d = html.indexOf("<details class=\"matchups-below-floor-details\">");
  assert(d !== -1);
  assert(html.includes("<summary>80 confrontos com poucas partidas</summary>"));
  assert(html.indexOf("matchups-below-floor\"", d) > d);
  assert(html.indexOf("</details>", d) > html.indexOf("matchups-below-floor\"", d));
  assert(html.indexOf("Ekko") < d);   // os confrontos acima do piso ficam fora do details
});

Deno.test("abaixo do piso: um unico confronto fica no singular", () => {
  const t = { ...TARGET, matchups: [TARGET.matchups[1]] };
  assert(renderChampion(t, DICT).includes("<summary>1 confronto com poucas partidas</summary>"));
});

const ICONES = {
  itemImages: new Map([[3142, "3142.png"], [1055, "1055.png"]]),
  spellImages: new Map([[4, "SummonerFlash.png"]]),
  runeIcons: new Map([
    [8112, "perk-images/Styles/Domination/Electrocute/Electrocute.png"],
    [8100, "perk-images/Styles/7200_Domination.png"],
  ]),
};
const CDN = "https://ddragon.leagueoflegends.com/cdn";

Deno.test("icones: item e feitico versionados, runa e arvore sem versao", () => {
  const html = renderChampion(TARGET, { ...DICT, ...ICONES });
  assert(html.includes(`src="${CDN}/16.21.1/img/item/3142.png"`));
  assert(html.includes(`src="${CDN}/16.21.1/img/item/1055.png"`));
  assert(html.includes(`src="${CDN}/16.21.1/img/spell/SummonerFlash.png"`));
  assert(html.includes(`src="${CDN}/img/perk-images/Styles/Domination/Electrocute/Electrocute.png"`));
  assert(html.includes(`src="${CDN}/img/perk-images/Styles/7200_Domination.png"`));
  assert(!html.includes("16.21.1/img/perk-images"));
});

Deno.test("icones: o nome continua em texto e todo <img> tem alt", () => {
  const html = renderChampion(TARGET, { ...DICT, ...ICONES });
  assert(html.includes("Youmuu&#39;s Ghostblade"));
  assert(html.includes("Flash"));
  assert(html.includes("Electrocute"));
  assert(html.includes("Domination"));
  const imgs = html.match(/<img\b[^>]*>/g) ?? [];
  assert(imgs.length > 0);
  assert(imgs.every((t) => /\balt="/.test(t)));
});

Deno.test("sem icone no dict o nome ainda renderiza, sem <img> de item, runa ou feitico", () => {
  const html = renderChampion(TARGET, DICT);
  assert(html.includes("Youmuu&#39;s Ghostblade"));
  assert(html.includes("Electrocute"));
  assert(html.includes("Flash"));
  assert(!html.includes("/img/item/"));
  assert(!html.includes("/img/spell/"));
  assert(!html.includes("perk-images"));
});

Deno.test("icone so de alguns itens: o item sem icone mantem o nome", () => {
  const dict = { ...DICT, ...ICONES, itemImages: new Map([[3142, "3142.png"]]) };
  const html = renderChampion(TARGET, dict);
  assert(html.includes("/img/item/3142.png"));
  assert(!html.includes("/img/item/6693.png"));
  assert(html.includes("Prowler&#39;s Claw"));
});

Deno.test("fragmentos ficam so com nome, sem imagem", () => {
  const html = renderChampion(TARGET, { ...DICT, ...ICONES });
  assert(!html.includes("StatMods"));
  assert(html.includes("Força Adaptativa"));
});

Deno.test("URL do icone passa por escapeHtml", () => {
  const dict = { ...DICT, itemImages: new Map([[3142, '"><script>x</script>.png']]) };
  const html = renderChampion(TARGET, dict);
  assert(!html.includes("<script>"));
});

// Dicionario com preco: o DICT geral nao tem, de proposito, para nao mexer na
// ordem que os testes antigos observam.
const DICT_COM_PRECO = {
  ...DICT,
  items: new Map([[1, "Espada Longa"], [2, "Botas"], [3, "Item Caro"], [4, "Barato Raro"]]),
  itemGold: new Map([[1, 350], [2, 900], [3, 3000], [4, 100]]),
};

const alvoComItens = (freq) => ({
  ...TARGET,
  baseline: { ...TARGET.baseline, games: 1000, item_frequency: freq },
});

Deno.test("itens saem do mais barato ao mais caro, nao na ordem de frequencia", () => {
  // Entram por frequencia nesta ordem: Caro (500), Espada (300), Botas (200).
  const html = renderChampion(
    alvoComItens([{ item_id: 3, games: 500 }, { item_id: 1, games: 300 }, { item_id: 2, games: 200 }]),
    DICT_COM_PRECO,
  );
  const pos = (n) => html.indexOf(n);
  assert(pos("Espada Longa") < pos("Botas"));      // 350 < 900
  assert(pos("Botas") < pos("Item Caro"));         // 900 < 3000
  // e o mais frequente NAO e o primeiro, que e o ponto
  assert(pos("Item Caro") > pos("Espada Longa"));
});

Deno.test("a selecao continua por frequencia: ordenar antes de cortar seria bug", () => {
  // O teto e 12. Monto 15 itens acima do piso de 5%: doze caros e muito
  // jogados, e tres baratissimos jogados menos (mas ainda acima do piso).
  //
  // Correto: o corte pega os 12 mais JOGADOS (os caros) e so entao ordena por
  // preco. Bug: ordenar os 15 por preco e entao cortar 12 traz os tres baratos
  // e joga fora tres itens que as pessoas de fato usam.
  //
  // A fixture precisa de mais de 12 itens, senao o teto nunca entra em acao e
  // o teste passa com as duas implementacoes.
  const caros = Array.from({ length: 12 }, (_, k) => ({ item_id: 100 + k, games: 500 }));
  const baratos = [{ item_id: 200, games: 60 }, { item_id: 201, games: 60 }, { item_id: 202, games: 60 }];
  const dict = {
    ...DICT,
    items: new Map([
      ...caros.map((c, k) => [c.item_id, `Caro ${k}`]),
      [200, "Barato A"], [201, "Barato B"], [202, "Barato C"],
    ]),
    itemGold: new Map([
      ...caros.map((c) => [c.item_id, 3000]),
      [200, 100], [201, 100], [202, 100],
    ]),
  };
  const html = renderChampion(alvoComItens([...caros, ...baratos]), dict);
  assert(html.includes("Caro 0"));
  assert(html.includes("Caro 11"));
  for (const n of ["Barato A", "Barato B", "Barato C"]) assert(!html.includes(n));
});
