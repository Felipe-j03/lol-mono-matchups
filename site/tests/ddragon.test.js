import { assert, assertEquals, assertRejects } from "jsr:@std/assert";
import {
  championIcon,
  championName,
  itemIcon,
  itemName,
  loadDdragon,
  runeIcon,
  runeName,
  shardName,
  spellIcon,
  itemGold,
  spellName,
} from "../js/ddragon.js";

const PAYLOADS = {
  "item.json": {
    data: {
      "3020": { name: "Sorcerer's Shoes", image: { full: "3020.png" }, gold: { total: 1100 } },
    },
  },
  "champion.json": {
    data: {
      Talon: { key: "91", name: "Talon", image: { full: "Talon.png" } },
    },
  },
  "summoner.json": {
    data: {
      SummonerFlash: { key: "4", name: "Flash", image: { full: "SummonerFlash.png" } },
    },
  },
  "runesReforged.json": [
    {
      id: 8100,
      name: "Domination",
      icon: "perk-images/Styles/7200_Domination.png",
      slots: [{
        runes: [{
          id: 8112,
          name: "Electrocute",
          icon: "perk-images/Styles/Domination/Electrocute/Electrocute.png",
        }],
      }],
    },
  ],
};

function fakeFetch(url) {
  const arquivo = Object.keys(PAYLOADS).find((n) => url.endsWith("/" + n));
  if (arquivo === undefined) return Promise.resolve({ ok: false, status: 404 });
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(PAYLOADS[arquivo]),
  });
}

Deno.test("loadDdragon indexa item, runa e campeao por id numerico", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  assertEquals(itemName(dict, 3020), "Sorcerer's Shoes");
  assertEquals(runeName(dict, 8112), "Electrocute");
  assertEquals(championName(dict, 91), "Talon");
});

Deno.test("runeName resolve tambem o id da arvore de runas", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  assertEquals(runeName(dict, 8100), "Domination");
});

Deno.test("championIcon monta a URL do icone com a versao", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  assertEquals(
    championIcon(dict, 91),
    "https://ddragon.leagueoflegends.com/cdn/16.21.1/img/champion/Talon.png",
  );
});

Deno.test("id desconhecido devolve o id cru, nunca undefined", () => {
  const dict = { version: "16.21.1", items: new Map(), runes: new Map(), champions: new Map(), spells: new Map() };
  assertEquals(spellName(dict, 9999), "9999");
  assertEquals(itemName(dict, 9999), "9999");
  assertEquals(runeName(dict, 9999), "9999");
  assertEquals(championName(dict, 9999), "9999");
  assertEquals(championIcon(dict, 9999), null);
});

Deno.test("loadDdragon usa a versao recebida nas quatro URLs", async () => {
  const vistas = [];
  await loadDdragon("16.21.1", (u) => { vistas.push(u); return fakeFetch(u); });
  assert(vistas.every((u) => u.includes("/16.21.1/")));
  assertEquals(vistas.length, 4);
});

Deno.test("loadDdragon rejeita com o status quando a CDN nao responde ok", async () => {
  await assertRejects(
    () => loadDdragon("0.0.0", () => Promise.resolve({ ok: false, status: 404 })),
    Error,
    "404",
  );
});

Deno.test("fragmento de atributo resolve para o nome, sem magnitude", () => {
  assertEquals(shardName(5008), "Força Adaptativa");
  assertEquals(shardName(5002), "Armadura");
  assert(!/\d/.test(shardName(5003)));
});

Deno.test("id de fragmento desconhecido devolve o id cru", () => {
  assertEquals(shardName(5099), "5099");
});

Deno.test("spellName resolve a chave textual do summoner.json por id numerico", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  assertEquals(spellName(dict, 4), "Flash");
});

Deno.test("runeName resolve fragmento de atributo pela tabela de fragmentos", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  assert(!dict.runes.has(5001));
  assertEquals(runeName(dict, 5001), "Vida escalando por nível");
  assertEquals(runeName(dict, 5001), shardName(5001));
});

const IMG = "https://ddragon.leagueoflegends.com/cdn";

Deno.test("itemIcon usa a versao e image.full; id desconhecido devolve null", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  assertEquals(itemIcon(dict, 3020), `${IMG}/16.21.1/img/item/3020.png`);
  assertEquals(itemIcon(dict, 9999), null);
});

Deno.test("spellIcon usa a versao e image.full; id desconhecido devolve null", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  assertEquals(spellIcon(dict, 4), `${IMG}/16.21.1/img/spell/SummonerFlash.png`);
  assertEquals(spellIcon(dict, 9999), null);
});

Deno.test("runeIcon NAO leva a versao, para runa e para arvore", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  const runa = runeIcon(dict, 8112);
  const arvore = runeIcon(dict, 8100);
  assertEquals(runa, `${IMG}/img/perk-images/Styles/Domination/Electrocute/Electrocute.png`);
  assertEquals(arvore, `${IMG}/img/perk-images/Styles/7200_Domination.png`);
  assert(!runa.includes("16.21.1"));
  assert(!arvore.includes("16.21.1"));
  assert(itemIcon(dict, 3020).includes("16.21.1"));
  assertEquals(runeIcon(dict, 9999), null);
});

Deno.test("fragmento de atributo nao tem icone: runeIcon devolve null", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  assertEquals(runeIcon(dict, 5008), null);
});

Deno.test("icone com dict sem os indices novos devolve null, nao quebra", () => {
  const dict = { version: "1", items: new Map(), runes: new Map(), champions: new Map(), spells: new Map() };
  assertEquals(itemIcon(dict, 1), null);
  assertEquals(spellIcon(dict, 1), null);
  assertEquals(runeIcon(dict, 1), null);
});

Deno.test("loadDdragon pede os dados em pt_BR e em nenhum outro idioma", async () => {
  const vistas = [];
  await loadDdragon("16.21.1", (u) => { vistas.push(u); return fakeFetch(u); });
  assert(vistas.every((u) => u.includes("/data/pt_BR/")));
  assert(!vistas.some((u) => u.includes("en_US")));
});

Deno.test("itemGold devolve o custo total, e null para id desconhecido", async () => {
  const dict = await loadDdragon("16.21.1", fakeFetch);
  assertEquals(itemGold(dict, 3020), 1100);
  assertEquals(itemGold(dict, 9999), null);
});
