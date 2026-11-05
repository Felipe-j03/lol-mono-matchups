import { assertEquals } from "jsr:@std/assert";
import { parseRoute, championHash, matchupHash } from "../js/route.js";

Deno.test("hash vazio e raiz caem na tela de escolha", () => {
  for (const h of ["", "#", "#/"]) assertEquals(parseRoute(h).screen, "choose");
});

Deno.test("rota de campeao e de confronto", () => {
  assertEquals(parseRoute("#/talon-middle"), { screen: "champion", slug: "talon-middle" });
  assertEquals(parseRoute("#/talon-middle/vs/245"),
    { screen: "matchup", slug: "talon-middle", opponentId: 245 });
});

Deno.test("rota malformada e notfound, nunca excecao nem tela vazia", () => {
  for (const h of [
    "#/talon-middle/vs/abc",
    "#/a/b/c/d",
    "#/talon-middle/vs/",
    "#/talon-middle/foo/245",
    "#//vs/245",
  ]) {
    assertEquals(parseRoute(h).screen, "notfound");
  }
});

Deno.test("notfound carrega o hash recebido", () => {
  assertEquals(parseRoute("#/a/b/c/d"), { screen: "notfound", hash: "#/a/b/c/d" });
});

Deno.test("entrada nao textual vira notfound com hash textual, sem excecao", () => {
  for (const h of [undefined, null, 42]) {
    const r = parseRoute(h);
    assertEquals(r.screen, "notfound");
    assertEquals(typeof r.hash, "string");
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
