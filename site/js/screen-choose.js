// Tela 1: escolha do alvo. Recebe o index.json ja lido e devolve HTML.
// Modulo puro: sem DOM, sem I/O.

import { championIcon } from "./ddragon.js";
import { escapeHtml, sample } from "./format.js";
import { championHash } from "./route.js";

// O slug pertence ao exportador: vem do nome do arquivo, nunca de champion_name.
function slugDoArquivo(file) {
  return file.replace(/\.json$/, "");
}

function monos(n) {
  return `${n} ${n === 1 ? "mono" : "monos"}`;
}

function retrato(alvo, dict) {
  const url = championIcon(dict, alvo.champion_id);
  if (url == null) return "";
  return `<img class="portrait" src="${escapeHtml(url)}" alt="" width="64" height="64">`;
}

function cartao(alvo, dict) {
  const nome = escapeHtml(alvo.champion_name);
  const corpo = `${retrato(alvo, dict)}
    <span class="name">${nome}</span>
    <span class="role">${escapeHtml(alvo.role)}</span>
    <span class="count">${
    alvo.has_data
      ? escapeHtml(`${monos(alvo.players)} ${sample(alvo.games)}`)
      : "Sem dados"
  }</span>`;

  if (!alvo.has_data) {
    return `<li class="card card-empty">${corpo}</li>`;
  }
  const href = escapeHtml(championHash(slugDoArquivo(alvo.file)));
  return `<li class="card"><a href="${href}">${corpo}</a></li>`;
}

function janela(index) {
  const { collected_from: de, collected_through: ate } = index;
  if (de == null || ate == null) return "Sem partidas agregadas.";
  return `Partidas de ${escapeHtml(de)} a ${escapeHtml(ate)}. ` +
    "Uma janela larga mistura patches na mesma base.";
}

export function renderChoose(index, dict) {
  return `<section class="choose">
  <h1>Escolha um campeão</h1>
  <ul class="cards">
    ${index.targets.map((alvo) => cartao(alvo, dict)).join("\n    ")}
  </ul>
  <footer class="window">${janela(index)}</footer>
</section>`;
}
