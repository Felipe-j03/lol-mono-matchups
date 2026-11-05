// Tela 2: campeao. Recebe o JSON do alvo ja lido e devolve HTML.
// Modulo puro: sem DOM, sem I/O.
//
// O nome do alvo vem do proprio JSON (champion_name); o dos oponentes vem do
// Data Dragon, porque o arquivo so traz opponent_champion_id.

import {
  championIcon,
  championName,
  itemName,
  runeName,
  shardName,
} from "./ddragon.js";
import { escapeHtml, pct, sample } from "./format.js";
import { matchupHash } from "./route.js";

const TECLAS = { 1: "Q", 2: "W", 3: "E", 4: "R" };

function lista(nomes) {
  return nomes.map(escapeHtml).join(", ");
}

function ordemDeHabilidades(ordem) {
  return ordem.map((n) => TECLAS[n] ?? String(n)).join(" > ");
}

function paginaDeRunas(runas, dict) {
  const nomes = (ids) => lista(ids.map((id) => runeName(dict, id)));
  return `<dl class="runes">
      <dt>Runa-chave</dt><dd>${escapeHtml(runeName(dict, runas.keystone))}</dd>
      <dt>${escapeHtml(runeName(dict, runas.primary_style))}</dt><dd>${nomes(runas.primary_perks)}</dd>
      <dt>${escapeHtml(runeName(dict, runas.secondary_style))}</dt><dd>${nomes(runas.secondary_perks)}</dd>
      <dt>Fragmentos</dt><dd>${lista(runas.shards.map(shardName))}</dd>
    </dl>`;
}

function base(b, dict) {
  const itens = b.item_frequency.map((i) =>
    `<li>${escapeHtml(itemName(dict, i.item_id))} <span class="n">${i.games} de ${b.games} partidas</span></li>`
  ).join("\n      ");
  return `<section class="baseline">
    <h2>O que os monos fazem por padrão</h2>
    <p class="note">Cada bloco é a configuração mais frequente entre as partidas do grupo,
    vitórias e derrotas juntas: descreve o que se faz por padrão, não o que ganha.
    Taxa de vitória do grupo: ${pct(b.group_win_rate)} ${sample(b.games)}.</p>
    <h3>Runas <span class="n">${sample(b.runes_games)}</span></h3>
    ${paginaDeRunas(b.runes, dict)}
    <p class="aside">Taxa de vitória dessa página exata: ${pct(b.runes_win_rate)} ${sample(b.runes_games)}.
    É informação ao lado; não foi o critério que a escolheu.</p>
    <h3>Feitiços <span class="n">${sample(b.spells_games)}</span></h3>
    <p>${lista(b.spells.map(String))}</p>
    <h3>Itens finais, um a um</h3>
    <ul class="items">
      ${itens}
    </ul>
    <h3>Itens iniciais <span class="n">${sample(b.starting_items_games)}</span></h3>
    <p>${lista(b.starting_items.map((id) => itemName(dict, id)))}</p>
    <h3>Ordem de habilidades <span class="n">${sample(b.skill_order_games)}</span></h3>
    <p>${escapeHtml(ordemDeHabilidades(b.skill_order))}</p>
  </section>`;
}

// O slug pertence ao exportador: sai do nome do arquivo do confronto.
function slugDoConfronto(file) {
  return file.replace(/-vs-\d+\.json$/, "");
}

function nomeDoOponente(m, dict) {
  const id = m.opponent_champion_id;
  const url = championIcon(dict, id);
  const icone = url == null
    ? ""
    : `<img class="portrait" src="${escapeHtml(url)}" alt="" width="32" height="32"> `;
  return `${icone}<span class="name">${escapeHtml(championName(dict, id))}</span>`;
}

function resumoDoConfronto(m) {
  return `${pct(m.win_rate)} de vitórias ${sample(m.games)}`;
}

function confronto(m, dict) {
  const corpo = `${nomeDoOponente(m, dict)} <span class="n">${resumoDoConfronto(m)}</span>`;
  if (m.below_floor || m.file == null) return `<li class="matchup">${corpo}</li>`;
  const href = escapeHtml(matchupHash(slugDoConfronto(m.file), m.opponent_champion_id));
  return `<li class="matchup"><a href="${href}">${corpo}</a></li>`;
}

// Ordem do JSON: o exportador ja pos o pior primeiro e os abaixo do piso depois.
function confrontos(matchups, dict) {
  const acima = matchups.filter((m) => !m.below_floor);
  const abaixo = matchups.filter((m) => m.below_floor);
  const secaoAbaixo = abaixo.length === 0 ? "" : `
    <h3>Dados insuficientes</h3>
    <p class="note">Poucas partidas para comparar: sem página de confronto.</p>
    <ul class="matchups matchups-below-floor">
      ${abaixo.map((m) => confronto(m, dict)).join("\n      ")}
    </ul>`;
  return `<section class="matchups-section">
    <h2>Confrontos, do pior para o melhor</h2>
    <ul class="matchups">
      ${acima.map((m) => confronto(m, dict)).join("\n      ")}
    </ul>${secaoAbaixo}
  </section>`;
}

function jogadores(players) {
  const linhas = players.map((p) =>
    `<li>${escapeHtml(p.riot_id)} <span class="n">${escapeHtml(p.platform)}: ` +
    `${p.games} partidas, ${pct(p.share)} do que jogou foi este campeão, ` +
    `${pct(p.win_rate)} de vitórias</span></li>`
  ).join("\n      ");
  return `<details class="reference-players">
    <summary>Jogadores de referência (${players.length})</summary>
    <ul>
      ${linhas}
    </ul>
  </details>`;
}

export function renderChampion(target, dict) {
  return `<section class="champion">
  <h1>${escapeHtml(target.champion_name)} <span class="role">${escapeHtml(target.role)}</span></h1>
  ${base(target.baseline, dict)}
  ${confrontos(target.matchups, dict)}
  ${jogadores(target.reference_players)}
</section>`;
}
