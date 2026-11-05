import { assert, assertEquals } from "jsr:@std/assert";
import {
  championIcon,
  championName,
  itemName,
  loadDdragon,
  runeName,
} from "../js/ddragon.js";

const PAYLOADS = {
  "item.json": {
    data: {
      "3020": { name: "Sorcerer's Shoes", image: { full: "3020.png" } },
    },
  },
  "champion.json": {
    data: {
      Talon: { key: "91", name: "Talon", image: { full: "Talon.png" } },
    },
  },
  "runesReforged.json": [
    {
      id: 8100,
      name: "Domination",
      slots: [{ runes: [{ id: 8112, name: "Electrocute" }] }],
    },
  ],
};

function fakeFetch(url) {
  const arquivo = Object.keys(PAYLOADS).find((n) => url.endsWith("/" + n));
  return Promise.resolve({
    ok: arquivo !== undefined,
    status: arquivo ? 200 : 404,
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
