import { assert } from "jsr:@std/assert";
import { renderMatchup } from "../js/screen-matchup.js";

const MATCHUP = {
  schema_version: 1,
  champion_id: 91, champion_name: "Talon", role: "MIDDLE",
  opponent_champion_id: 245,
  games: 40, wins: 20, losses: 20, min_per_side: 15,
  comparable: true,
  headline: null,
  winner_gold_at_14: 5200.0, loser_gold_at_14: 4000.0,
  winner_cs_diff_at_14: 8.0, loser_cs_diff_at_14: -6.0,
  timeline_games: {
    gold_at_14: { winners: 20, losers: 20 },
    cs_diff_at_14: { winners: 20, losers: 20 },
    starting_items: { winners: 18, losers: 17 },
    skill_order: { winners: 20, losers: 20 },
  },
  games_without_boots: { winners: 0, losers: 0 },
  divergences: [
    { field: "boots", label: "3020", winner_share: 0.8, loser_share: 0.2,
      gap: 0.6, winner_games: 20, loser_games: 20 },
  ],
};

const DICT = {
  version: "16.21.1",
  items: new Map([[3020, "Sorcerer's Shoes"], [1055, "Doran's Blade"]]),
  runes: new Map([[8347, "Cosmic Insight"]]),
  spells: new Map(),
  champions: new Map([[91, { name: "Talon", image: "Talon.png" }],
                      [245, { name: "Ekko", image: "Ekko.png" }]]),
};

Deno.test("divergencia usa winner_games e loser_games, nao wins e losses", () => {
  const m = { ...MATCHUP, wins: 20, losses: 20, divergences: [
    { field: "starting_items", label: "1055", winner_share: 0.5, loser_share: 0.1,
      gap: 0.4, winner_games: 18, loser_games: 17 }] };
  const html = renderMatchup(m, DICT);
  assert(html.includes("em 18 partidas"));
  assert(html.includes("em 17 partidas"));
});

Deno.test("proporcao de cada lado vem com o denominador do proprio lado", () => {
  const m = { ...MATCHUP, wins: 30, losses: 10, divergences: [
    { field: "rune", label: "8347", winner_share: 0.71, loser_share: 0.3,
      gap: 0.41, winner_games: 28, loser_games: 9 }] };
  const html = renderMatchup(m, DICT);
  // Pina o PAREAMENTO, nao so a presenca: o lado dos vencedores carrega 71%
  // junto de 28, e o dos perdedores 30% junto de 9. Com wins=30 e losses=10 na
  // fixture, usar o denominador errado imprimiria "em 30 partidas" e "em 10
  // partidas" — e so uma assercao por lado, separada, pega isso.
  const trecho = (classe) => {
    const i = html.indexOf(`<span class="lado ${classe}">`);
    return html.slice(i, html.indexOf("</span>", html.indexOf("<small>", i)));
  };
  const venc = trecho("vencedores");
  const perd = trecho("perdedores");
  assert(venc.includes("71%") && venc.includes("em 28 partidas"), venc);
  assert(perd.includes("30%") && perd.includes("em 9 partidas"), perd);
  assert(!venc.includes("em 30 partidas") && !perd.includes("em 10 partidas"));
  assert(html.includes("Cosmic Insight"));
});

Deno.test("frase do topo e montada da divergencia, sem id cru", () => {
  const html = renderMatchup(MATCHUP, DICT);   // divergences[0] e botas 3020
  assert(html.includes("Sorcerer&#39;s Shoes"));
  // O id NAO pode aparecer como texto visivel. A negativa e escopada ao no de
  // texto de proposito: um icone do Data Dragon tem o id na URL
  // (item/3020.png), e proibir "3020" no HTML inteiro reprovaria uma
  // implementacao correta que mostra o icone.
  assert(!html.includes(">3020<"));
  assert(!/>[^<]*\b3020\b[^<]*</.test(html));
});

Deno.test("skill_order chega legivel e nao passa por item nem runa", () => {
  const m = { ...MATCHUP, divergences: [
    { field: "skill_order", label: "Q > W > E", winner_share: 0.9, loser_share: 0.2,
      gap: 0.7, winner_games: 20, loser_games: 20 }] };
  assert(renderMatchup(m, DICT).includes("Q &gt; W &gt; E"));
});

Deno.test("label desconhecido no dicionario cai no id, escapado", () => {
  const m = { ...MATCHUP, divergences: [
    { field: "boots", label: "<b>9</b>", winner_share: 0.9, loser_share: 0.2,
      gap: 0.7, winner_games: 20, loser_games: 20 }] };
  const html = renderMatchup(m, DICT);
  assert(!html.includes("<b>9</b>"));
  assert(html.includes("&lt;b&gt;9&lt;/b&gt;"));
});

Deno.test("divergencias saem na ordem do JSON, sem reordenar", () => {
  const m = { ...MATCHUP, divergences: [
    { field: "rune", label: "8347", winner_share: 0.9, loser_share: 0.2,
      gap: 0.7, winner_games: 20, loser_games: 20 },
    { field: "boots", label: "3020", winner_share: 0.8, loser_share: 0.5,
      gap: 0.3, winner_games: 20, loser_games: 20 }] };
  const html = renderMatchup(m, DICT);
  assert(html.indexOf("Cosmic Insight") < html.indexOf("Sorcerer&#39;s Shoes"));
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
  assert(!html.includes("NaN"));
  assert(html.length > 200);
});

Deno.test("nao comparavel com um lado zerado explica e mostra o timeline", () => {
  const m = { ...MATCHUP, comparable: false, divergences: [], headline: null,
    winner_gold_at_14: null, loser_gold_at_14: null,
    winner_cs_diff_at_14: null, loser_cs_diff_at_14: null,
    games: 22, wins: 22, losses: 0, min_per_side: 15,
    timeline_games: {
      gold_at_14: { winners: 20, losers: 0 }, cs_diff_at_14: { winners: 20, losers: 0 },
      starting_items: { winners: 19, losers: 0 }, skill_order: { winners: 21, losers: 0 } },
    games_without_boots: { winners: 3, losers: 0 } };
  const html = renderMatchup(m, DICT);
  assert(html.includes("Sem partidas suficientes"));
  assert(html.includes("22 partidas de vitória"));
  assert(html.includes("0 partidas de derrota") || html.includes("0 de derrota"));
  assert(html.includes("19"));
  assert(!html.includes("null") && !html.includes("NaN"));
});

Deno.test("comparavel sem divergencia render o headline como resposta", () => {
  const m = { ...MATCHUP, divergences: [], headline: "Vencedores e perdedores fizeram as escolhas de forma igual em botas e runas: nenhuma diferenca passou de 15 pontos percentuais." };
  assert(renderMatchup(m, DICT).includes("nenhuma diferenca passou"));
});

Deno.test("headline com divergencias entra como nota ao lado, nao no lugar delas", () => {
  const m = { ...MATCHUP,
    headline: "Sem partidas suficientes com timeline para comparar: itens iniciais." };
  const html = renderMatchup(m, DICT);
  assert(html.includes("Sem partidas suficientes com timeline"));
  assert(html.includes("Sorcerer&#39;s Shoes"));
});

Deno.test("ponto cego de botas fica visivel", () => {
  const m = { ...MATCHUP, games_without_boots: { winners: 12, losers: 11 } };
  const html = renderMatchup(m, DICT);
  assert(html.includes("12"));
  assert(html.includes("11"));
  assert(html.includes("não significa concordância"));
});

Deno.test("ponto cego imprime cada contagem contra wins e losses", () => {
  const m = { ...MATCHUP, wins: 20, losses: 200,
    games_without_boots: { winners: 12, losers: 11 } };
  const html = renderMatchup(m, DICT);
  assert(html.includes("12 de 20 partidas de vitória"));
  assert(html.includes("11 de 200 partidas de derrota"));
  assert(html.includes("não significa concordância"));
});

Deno.test("ponto cego com confronto nao comparavel traz contagens e denominadores", () => {
  const m = { ...MATCHUP, comparable: false, divergences: [], headline: null,
    winner_gold_at_14: null, loser_gold_at_14: null,
    winner_cs_diff_at_14: null, loser_cs_diff_at_14: null,
    games: 23, wins: 22, losses: 1, min_per_side: 15,
    games_without_boots: { winners: 3, losers: 1 } };
  const html = renderMatchup(m, DICT);
  assert(html.includes("3 de 22 partidas de vitória"));
  assert(html.includes("1 de 1 partida de derrota"));
});

Deno.test("ouro presente com farm nulo renderiza o ouro e declara a ausencia do farm", () => {
  const m = { ...MATCHUP, winner_cs_diff_at_14: null, loser_cs_diff_at_14: null,
    timeline_games: { ...MATCHUP.timeline_games, cs_diff_at_14: { winners: 14, losers: 3 } } };
  const html = renderMatchup(m, DICT);
  assert(html.includes("5200"));
  assert(html.includes("4000"));
  assert(html.includes(
    "Diferença média de farm aos 14 min: sem dado suficiente de timeline, ao menos um dos lados tem menos de 15 partidas com esse valor (vencedores em 14 partidas, perdedores em 3 partidas)",
  ));
  assert(!html.includes("Ouro médio aos 14 min: sem dado"));
  assert(!html.includes("null") && !html.includes("NaN"));
});

Deno.test("farm presente com ouro nulo renderiza o farm e declara a ausencia do ouro", () => {
  const m = { ...MATCHUP, winner_gold_at_14: null, loser_gold_at_14: null,
    timeline_games: { ...MATCHUP.timeline_games, gold_at_14: { winners: 9, losers: 1 } } };
  const html = renderMatchup(m, DICT);
  assert(html.includes("+8") && html.includes("-6"));
  assert(html.includes(
    "Ouro médio aos 14 min: sem dado suficiente de timeline, ao menos um dos lados tem menos de 15 partidas com esse valor (vencedores em 9 partidas, perdedores em 1 partida)",
  ));
  assert(!html.includes("Diferença média de farm aos 14 min: sem dado"));
  assert(!html.includes("null") && !html.includes("NaN"));
});

Deno.test("sem ponto cego de botas nao ha aviso de ponto cego", () => {
  assert(!renderMatchup(MATCHUP, DICT).includes("não significa concordância"));
});

Deno.test("ouro e farm presentes aparecem com denominador", () => {
  const html = renderMatchup(MATCHUP, DICT);
  assert(html.includes("5200"));
  assert(html.includes("4000"));
  assert(html.includes("+8"));
  assert(html.includes("-6"));
  assert(html.includes("em 20 partidas"));
});

Deno.test("ouro aos 14 nulo nao imprime numero nem zero", () => {
  const m = { ...MATCHUP, winner_gold_at_14: null, loser_gold_at_14: null,
    winner_cs_diff_at_14: null, loser_cs_diff_at_14: null,
    timeline_games: { ...MATCHUP.timeline_games, gold_at_14: { winners: 0, losers: 0 } } };
  const html = renderMatchup(m, DICT);
  assert(!html.includes("null"));
  assert(!html.includes("NaN"));
  assert(!html.includes("5200"));
  assert(html.includes("Ouro médio aos 14 min: sem dado suficiente de timeline"));
  assert(html.includes("Diferença média de farm aos 14 min: sem dado suficiente de timeline"));
  // o piso citado vem de min_per_side, nao de um valor fixo
  const h17 = renderMatchup({ ...m, min_per_side: 17 }, DICT);
  assert(h17.split("tem menos de 17 partidas com esse valor").length - 1 === 2);
});

Deno.test("texto fala de diferenca observada, nunca de recomendacao", () => {
  const html = renderMatchup(MATCHUP, DICT);
  assert(!/\b(use|recomend|deve|melhor escolha)/i.test(html));
  assert(html.includes("Diferença observada entre os grupos, não prova de causa"));
  assert(html.includes("vencedores"));
});

const CDN = "https://ddragon.leagueoflegends.com/cdn";
const ICONES = {
  itemImages: new Map([[3020, "3020.png"], [1055, "1055.png"]]),
  runeIcons: new Map([[8347, "perk-images/Styles/Inspiration/CosmicInsight/CosmicInsight.png"]]),
};
const div = (field, label) => ({ field, label, winner_share: 0.8, loser_share: 0.2,
  gap: 0.6, winner_games: 20, loser_games: 20 });

Deno.test("icone da divergencia: boots e starting_items pelo item, versionado", () => {
  for (const [f, label] of [["boots", "3020"], ["starting_items", "1055"]]) {
    const html = renderMatchup({ ...MATCHUP, divergences: [div(f, label)] }, { ...DICT, ...ICONES });
    assert(html.includes(`src="${CDN}/16.21.1/img/item/${label}.png"`), f);
  }
});

Deno.test("icone da divergencia: rune pelo icone de runa, sem versao", () => {
  const html = renderMatchup({ ...MATCHUP, divergences: [div("rune", "8347")] }, { ...DICT, ...ICONES });
  assert(html.includes(`src="${CDN}/img/perk-images/Styles/Inspiration/CosmicInsight/CosmicInsight.png"`));
  assert(!html.includes("16.21.1/img/perk-images"));
  assert(html.includes("Cosmic Insight"));
});

Deno.test("skill_order nao tem icone", () => {
  const html = renderMatchup({ ...MATCHUP, divergences: [div("skill_order", "Q > W > E")] }, { ...DICT, ...ICONES });
  assert(!html.includes("<img"));
  assert(html.includes("Q &gt; W &gt; E"));
});

Deno.test("divergencia sem icone no dict ainda mostra o nome", () => {
  const html = renderMatchup(MATCHUP, DICT);
  assert(html.includes("Sorcerer&#39;s Shoes"));
  assert(!html.includes("<img"));
});

Deno.test("divergencia com icone mantem o nome e alt em todo <img>", () => {
  const html = renderMatchup(MATCHUP, { ...DICT, ...ICONES });
  assert(html.includes("Sorcerer&#39;s Shoes"));
  const imgs = html.match(/<img\b[^>]*>/g) ?? [];
  assert(imgs.length > 0);
  assert(imgs.every((t) => /\balt="/.test(t)));
});
