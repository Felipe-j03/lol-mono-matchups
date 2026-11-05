import { assert } from "jsr:@std/assert";
import { renderChoose } from "../js/screen-choose.js";

const INDEX = {
  schema_version: 1,
  ddragon_version: "16.21.1",
  collected_from: "2025-10-01",
  collected_through: "2025-11-02",
  targets: [
    { champion_id: 91, champion_name: "Talon", role: "MIDDLE",
      has_data: true, file: "talon-middle.json", players: 7, games: 312 },
    { champion_id: 79, champion_name: "Gragas", role: "TOP",
      has_data: false, file: null, players: 0, games: 0 },
  ],
};

const DICT = {
  version: "16.21.1",
  items: new Map(),
  runes: new Map(),
  champions: new Map([[91, { name: "Talon", image: "Talon.png" }]]),
};

Deno.test("um cartao por alvo, com monos e partidas", () => {
  const html = renderChoose(INDEX, DICT);
  assert(html.includes("Talon"));
  assert(html.includes("7 monos"));
  assert(html.includes("312 partidas"));
  assert(html.includes("Gragas"));
});

Deno.test("o retrato vem do Data Dragon", () => {
  const html = renderChoose(INDEX, DICT);
  assert(html.includes("/cdn/16.21.1/img/champion/Talon.png"));
});

Deno.test("alvo com dado e link para o slug do arquivo", () => {
  const html = renderChoose({ ...INDEX, targets: [INDEX.targets[0]] }, DICT);
  assert(html.includes('href="#/talon-middle"'));
});

Deno.test("o slug vem do file do indice, nao do nome do campeao", () => {
  const kaisa = { champion_id: 145, champion_name: "Kai'Sa", role: "BOTTOM",
    has_data: true, file: "kaisa-bottom.json", players: 1, games: 1 };
  const html = renderChoose({ ...INDEX, targets: [kaisa] }, DICT);
  assert(html.includes('href="#/kaisa-bottom"'));
  assert(html.includes("1 mono "));
  assert(html.includes("em 1 partida"));
  assert(!html.includes("1 monos"));
});

Deno.test("alvo sem dado nao e clicavel e diz que nao tem dado", () => {
  // indice com UM alvo so, has_data: false, para a ausencia de href ser inequivoca
  const html = renderChoose({ ...INDEX, targets: [INDEX.targets[1]] }, DICT);
  assert(!html.includes("href"));
  assert(!html.includes("<a"));
  assert(html.includes("Sem dados"));
});

Deno.test("a janela de coleta aparece na tela, com a nota de patches", () => {
  const html = renderChoose(INDEX, DICT);
  assert(html.includes("2025-10-01"));
  assert(html.includes("2025-11-02"));
  assert(html.includes("Quanto mais larga a janela, mais patches"));
  assert(!html.includes("janela larga"));
});

Deno.test("a janela mostra o numero de dias, contando as duas pontas", () => {
  // 2025-10-01 a 2025-11-02: 32 dias de diferenca, 33 dias cobertos.
  assert(renderChoose(INDEX, DICT).includes("Janela de 33 dias (2025-10-01 a 2025-11-02)"));
  const umDia = { ...INDEX, collected_from: "2025-11-02", collected_through: "2025-11-02" };
  assert(renderChoose(umDia, DICT).includes("Janela de 1 dia (2025-11-02 a 2025-11-02)"));
  // atravessa 29/02 de ano bissexto
  const bissexto = { ...INDEX, collected_from: "2024-02-28", collected_through: "2024-03-01" };
  assert(renderChoose(bissexto, DICT).includes("Janela de 3 dias"));
});

Deno.test("janela nula nao imprime null", () => {
  const html = renderChoose({ ...INDEX, collected_from: null, collected_through: null }, DICT);
  assert(!html.includes("null"));
  assert(html.includes("Sem partidas agregadas"));
});

Deno.test("strings interpoladas passam pelo escape", () => {
  const evil = { champion_id: 1, champion_name: "<b>x</b>", role: "TOP",
    has_data: false, file: null, players: 0, games: 0 };
  const html = renderChoose({ ...INDEX, targets: [evil] }, DICT);
  assert(!html.includes("<b>"));
  assert(html.includes("&lt;b&gt;x&lt;/b&gt;"));
});

Deno.test("campeao desconhecido ao Data Dragon renderiza sem imagem", () => {
  const html = renderChoose({ ...INDEX, targets: [INDEX.targets[1]] }, DICT);
  assert(!html.includes("<img"));
  assert(!html.includes("undefined"));
});
