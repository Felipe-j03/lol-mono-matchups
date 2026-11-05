// Tela 3: matchup. Recebe o JSON do confronto ja lido e devolve HTML.
// Modulo puro: sem DOM, sem I/O. Tela folha: nao linka para lugar nenhum.
//
// Mostra so onde vencedores e perdedores divergiram. Cada divergencia traz os
// proprios denominadores (winner_games / loser_games), que NAO sao wins/losses:
// boots e rune contam todas as partidas do lado, starting_items e skill_order
// so as que tinham timeline utilizavel.

import { championName, itemName, runeName } from "./ddragon.js";
import { escapeHtml, pct, sample } from "./format.js";

function partidas(n) {
  return n === 1 ? "partida" : "partidas";
}

// boots e starting_items chegam como id de item, rune como id de runa e
// skill_order ja legivel. Id sem nome no dicionario cai no proprio id.
function rotulo(div, dict) {
  const id = Number(div.label);
  if (!Number.isInteger(id)) return div.label; // nunca imprime NaN
  switch (div.field) {
    case "boots":
    case "starting_items":
      return itemName(dict, id);
    case "rune":
      return runeName(dict, id);
    default:
      return div.label;
  }
}

const CAMPO = {
  boots: "botas",
  starting_items: "itens iniciais",
  rune: "runa",
  skill_order: "ordem de habilidades",
};

function nomeDoCampo(field) {
  return CAMPO[field] ?? field;
}

function verbo(field) {
  return field === "skill_order" ? "seguiram a ordem" : "levaram";
}

function proporcao(share, lado, n) {
  return `${pct(share)} dos ${lado} (${sample(n)})`;
}

function fraseDoTopo(div, dict) {
  const nome = escapeHtml(rotulo(div, dict));
  const campo = escapeHtml(nomeDoCampo(div.field));
  const venc = proporcao(div.winner_share, "vencedores", div.winner_games);
  const perd = proporcao(div.loser_share, "perdedores", div.loser_games);
  return `<p class="topo">Maior diferença observada, em ${campo}: ${venc} ${
    verbo(div.field)
  } ${nome}, contra ${perd}. É uma diferença entre os grupos, não prova de que a escolha causou o resultado.</p>`;
}

function colunas(div, dict) {
  const nome = escapeHtml(rotulo(div, dict));
  const campo = escapeHtml(nomeDoCampo(div.field));
  return `<li class="divergencia">
  <h3>${campo}: ${nome}</h3>
  <div class="lado-a-lado">
    <div class="vencedores"><strong>Vencedores</strong> ${pct(div.winner_share)} <small>${
    sample(div.winner_games)
  }</small></div>
    <div class="perdedores"><strong>Perdedores</strong> ${pct(div.loser_share)} <small>${
    sample(div.loser_games)
  }</small></div>
  </div>
</li>`;
}

function divergencias(m, dict) {
  if (!m.divergences.length) return "";
  return `<section class="divergencias">
<h2>Onde vencedores e perdedores divergiram</h2>
<ul>${m.divergences.map((d) => colunas(d, dict)).join("")}</ul>
</section>`;
}

function placar(m) {
  return `<p class="placar">${m.games} ${partidas(m.games)}: ${m.wins} ${
    partidas(m.wins)
  } de vitória e ${m.losses} de derrota. Piso por lado para comparar: ${m.min_per_side} ${
    partidas(m.min_per_side)
  }.</p>`;
}

function semComparacao(m) {
  return `<section class="sem-comparacao">
<p>Sem partidas suficientes para comparar: é preciso ao menos ${m.min_per_side} ${
    partidas(m.min_per_side)
  } de cada lado, e este confronto tem ${m.wins} ${partidas(m.wins)} de vitória e ${m.losses} de derrota. Nenhuma diferença foi calculada, então a ausência de divergências aqui não diz que os grupos agiram igual.</p>
</section>`;
}

function sinal(n) {
  const r = Math.round(n);
  return r > 0 ? `+${r}` : String(r);
}

// As quatro medias sao nulas em pares: ouro e diferenca de farm existem para
// os dois lados ou para nenhum.
function numerosAos14(m) {
  const tg = m.timeline_games;
  const ouro = m.winner_gold_at_14 != null && m.loser_gold_at_14 != null;
  const farm = m.winner_cs_diff_at_14 != null && m.loser_cs_diff_at_14 != null;
  if (!ouro && !farm) {
    return `<p class="sem-dado">Ouro e diferença de farm aos 14 minutos: sem dado suficiente de timeline para os dois lados.</p>`;
  }
  const linhas = [];
  if (ouro) {
    linhas.push(
      `<li>Ouro médio aos 14 min: vencedores ${Math.round(m.winner_gold_at_14)} (${
        sample(tg.gold_at_14.winners)
      }), perdedores ${Math.round(m.loser_gold_at_14)} (${sample(tg.gold_at_14.losers)})</li>`,
    );
  }
  if (farm) {
    linhas.push(
      `<li>Diferença média de farm aos 14 min: vencedores ${
        sinal(m.winner_cs_diff_at_14)
      } (${sample(tg.cs_diff_at_14.winners)}), perdedores ${
        sinal(m.loser_cs_diff_at_14)
      } (${sample(tg.cs_diff_at_14.losers)})</li>`,
    );
  }
  return `<ul class="aos-14">${linhas.join("")}</ul>`;
}

const CAMPOS_TIMELINE = [
  ["gold_at_14", "ouro aos 14 min"],
  ["cs_diff_at_14", "farm aos 14 min"],
  ["starting_items", "itens iniciais"],
  ["skill_order", "ordem de habilidades"],
];

// Aparece tambem quando nao ha comparacao: e o que explica a ausencia.
function timeline(m) {
  const itens = CAMPOS_TIMELINE.map(([k, nome]) =>
    `<li>${nome}: ${m.timeline_games[k].winners} de vitória, ${
      m.timeline_games[k].losers
    } de derrota</li>`
  ).join("");
  return `<section class="timeline">
<h2>Partidas com timeline utilizável</h2>
${m.comparable ? numerosAos14(m) : ""}
<ul>${itens}</ul>
</section>`;
}

// O tamanho do ponto cego. Alto, ele impede ler "sem divergencia de botas"
// como concordancia.
function pontoCego(m) {
  const { winners, losers } = m.games_without_boots;
  if (!winners && !losers) return "";
  return `<p class="ponto-cego">Partidas sem botas reconhecidas: ${winners} de vitória e ${losers} de derrota. Quando esse número é alto, a falta de diferença em botas não significa concordância entre os grupos.</p>`;
}

function nota(m) {
  return m.headline ? `<p class="nota">${escapeHtml(m.headline)}</p>` : "";
}

export function renderMatchup(m, dict) {
  const oponente = escapeHtml(championName(dict, m.opponent_champion_id));
  const corpo = m.comparable
    ? `${m.divergences.length ? fraseDoTopo(m.divergences[0], dict) : ""}${nota(m)}${
      divergencias(m, dict)
    }`
    : semComparacao(m);
  return `<article class="matchup">
<h1>${escapeHtml(m.champion_name)} contra ${oponente}</h1>
${placar(m)}
${corpo}
${pontoCego(m)}
${timeline(m)}
</article>`;
}
