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
