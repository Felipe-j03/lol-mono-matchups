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
  const dias = diasDaJanela(de, ate);
  return `Janela de ${dias} ${dias === 1 ? "dia" : "dias"} ` +
    `(${escapeHtml(de)} a ${escapeHtml(ate)}). ` +
    "Quanto mais larga a janela, mais patches entram na mesma base.";
}

// Dias de calendario cobertos, contando o primeiro e o ultimo (mesmo dia = 1).
// Datas YYYY-MM-DD em UTC, como o contrato define.
function diasDaJanela(de, ate) {
  const DIA_MS = 24 * 60 * 60 * 1000;
  return Math.round((Date.parse(ate) - Date.parse(de)) / DIA_MS) + 1;
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
