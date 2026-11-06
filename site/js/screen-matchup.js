// Tela 3: matchup. Recebe o JSON do confronto ja lido e devolve HTML.
// Modulo puro: sem DOM, sem I/O. Tela folha: nao linka para lugar nenhum.
//
// Mostra so onde vencedores e perdedores divergiram. Cada divergencia traz os
// proprios denominadores (winner_games / loser_games), que NAO sao wins/losses:
// boots e rune contam todas as partidas do lado, starting_items e skill_order
// so as que tinham timeline utilizavel.

import { championName, itemIcon, itemName, runeIcon, runeName } from "./ddragon.js";
import { escapeHtml, iconImg, pct, sample } from "./format.js";

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

// Mesmo despacho de rotulo(): so boots, starting_items e rune tem icone.
function iconeDoRotulo(div, dict) {
  const id = Number(div.label);
  if (!Number.isInteger(id)) return "";
  switch (div.field) {
    case "boots":
    case "starting_items":
      return iconImg(itemIcon(dict, id), "icon icon-item");
    case "rune":
      return iconImg(runeIcon(dict, id), "icon icon-rune");
    default:
      return "";
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



// A frase do topo NAO repete a primeira linha da lista: ela diz o campo e o
// tamanho, e a lista mostra qual escolha foi. Antes dizia as duas coisas e o
// leitor lia o mesmo fato duas vezes seguidas.
function fraseDoTopo(div, dict) {
  const nome = escapeHtml(rotulo(div, dict));
  const campo = escapeHtml(nomeDoCampo(div.field));
  const lado = div.winner_share > div.loser_share ? "vencedores" : "perdedores";
  return `<p class="topo">A maior diferença está em <strong>${campo}</strong>: ${
    pontos(div)
  } a mais entre os ${lado}, em <strong>${nome}</strong>.</p>
<p class="ressalva">Diferença observada entre os grupos, não prova de causa.</p>`;
}

// A diferenca em pontos percentuais, que e o que o leitor calculava de cabeca
// comparando os dois numeros linha a linha.
function pontos(div) {
  return `${Math.round(Math.abs(div.winner_share - div.loser_share) * 100)} pontos`;
}

// Barra de proporcao. Largura e a propria proporcao, entao a comparacao e
// visual antes de ser numerica. NUNCA e a unica pista: o percentual e o
// denominador seguem escritos ao lado, para leitor de tela, para quem nao
// distingue as cores e para quando o CSS nao carrega.
function barra(share, classe) {
  const largura = Math.round(share * 100);
  return `<span class="barra ${classe}"><span class="preenche" style="width:${largura}%"></span></span>`;
}

function linhaDivergencia(div, dict) {
  const nome = escapeHtml(rotulo(div, dict));
  return `<li class="divergencia">
    <span class="rotulo">${iconeDoRotulo(div, dict)}${nome} <strong class="pontos">${
    pontos(div)
  }</strong></span>
    <span class="lado vencedores">${barra(div.winner_share, "boa")} <span class="valor">${
    pct(div.winner_share)
  }</span> <small>${sample(div.winner_games)}</small></span>
    <span class="lado perdedores">${barra(div.loser_share, "ruim")} <span class="valor">${
    pct(div.loser_share)
  }</span> <small>${sample(div.loser_games)}</small></span>
  </li>`;
}

const ORDEM_CAMPOS = ["rune", "boots", "starting_items", "skill_order"];

// Dentro de uma coluna: agrupado por campo, e por tamanho da diferenca dentro
// de cada grupo. Sem isso a lista intercala runa, bota e habilidade, e quem
// quer olhar so as runas varre tudo.
function grupos(divs, dict) {
  return ORDEM_CAMPOS
    .map((campo) => [campo, divs.filter((d) => d.field === campo)])
    .filter(([, ds]) => ds.length)
    .map(([campo, ds]) =>
      `<h4>${escapeHtml(nomeDoCampo(campo))}</h4>
      <ul class="divergencias-lista">${
        ds.toSorted((a, b) => b.gap - a.gap).map((d) => linhaDivergencia(d, dict)).join("")
      }</ul>`
    ).join("");
}

function coluna(titulo, classe, divs, dict) {
  if (!divs.length) {
    return `<div class="coluna-divergencia ${classe}">
      <h3>${titulo}</h3><p class="sem-dado">Nada acima do limiar deste lado.</p>
    </div>`;
  }
  return `<div class="coluna-divergencia ${classe}">
    <h3>${titulo} <span class="n">${divs.length}</span></h3>
    ${grupos(divs, dict)}
  </div>`;
}

// Um jogador pesa 100/N pontos numa proporcao. Quando isso se aproxima do
// limiar de 15 que define uma diferenca aqui, a lista cresce por causa do
// tamanho da amostra e nao do confronto — medido: mediana de 13 divergencias
// com 8-9 partidas por lado, contra 4,5 com 25 ou mais. Dizer isso na tela e
// o oposto de recomendar: e avisar que aqui ha pouco a concluir.
const LIMIAR_PONTOS = 15;

function confiabilidade(m) {
  const menor = Math.min(m.wins, m.losses);
  if (!menor) return "";
  const peso = Math.round(100 / menor);
  if (peso * 2 <= LIMIAR_PONTOS) return "";
  return `<p class="ponto-cego">Amostra pequena: com ${menor} ${
    partidas(menor)
  } do lado menor, um único jogador muda uma proporção em ${peso} pontos — perto dos ${LIMIAR_PONTOS} que definem uma diferença aqui. Confrontos com poucas partidas mostram mais diferenças, e isso vem do tamanho da amostra, não do confronto.</p>`;
}

// A DIRECAO e o eixo principal, nao o campo: a pergunta de quem abre e "o que
// quem ganhou fez diferente", e com duas colunas isso se le de relance em vez
// de sair de comparar dois numeros dezoito vezes.
function divergencias(m, dict) {
  if (!m.divergences.length) return "";
  const vencedores = m.divergences.filter((d) => d.winner_share > d.loser_share);
  const perdedores = m.divergences.filter((d) => d.winner_share <= d.loser_share);
  return `<section class="divergencias">
<h2>Onde vencedores e perdedores divergiram</h2>
${confiabilidade(m)}
<div class="duas-colunas">
  ${coluna("Mais entre os vencedores", "col-venc", vencedores, dict)}
  ${coluna("Mais entre os perdedores", "col-perd", perdedores, dict)}
</div>
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

// As quatro medias sao nulas em pares (ouro, farm), e cada par tem o seu
// contador em timeline_games. Cada metrica declara a propria ausencia: a falta
// de uma nao pode ser coberta pela presenca da outra.
function numerosAos14(m) {
  const tg = m.timeline_games;
  const ouro = m.winner_gold_at_14 != null && m.loser_gold_at_14 != null;
  const farm = m.winner_cs_diff_at_14 != null && m.loser_cs_diff_at_14 != null;
  const semDado = (rotulo, c) =>
    `<li class="sem-dado">${rotulo}: sem dado suficiente de timeline, ao menos um dos lados tem menos de ${m.min_per_side} ${
      partidas(m.min_per_side)
    } com esse valor (vencedores ${
      sample(c.winners)
    }, perdedores ${sample(c.losers)})</li>`;
  const linhas = [
    ouro
      ? `<li>Ouro médio aos 14 min: vencedores ${Math.round(m.winner_gold_at_14)} (${
        sample(tg.gold_at_14.winners)
      }), perdedores ${Math.round(m.loser_gold_at_14)} (${sample(tg.gold_at_14.losers)})</li>`
      : semDado("Ouro médio aos 14 min", tg.gold_at_14),
    farm
      ? `<li>Diferença média de farm aos 14 min: vencedores ${
        sinal(m.winner_cs_diff_at_14)
      } (${sample(tg.cs_diff_at_14.winners)}), perdedores ${
        sinal(m.loser_cs_diff_at_14)
      } (${sample(tg.cs_diff_at_14.losers)})</li>`
      : semDado("Diferença média de farm aos 14 min", tg.cs_diff_at_14),
  ];
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
  // Botas sao proporcao sobre todas as partidas do lado: o denominador e wins/losses.
  return `<p class="ponto-cego">Partidas sem botas reconhecidas: ${winners} de ${m.wins} ${
    partidas(m.wins)
  } de vitória e ${losers} de ${m.losses} ${
    partidas(m.losses)
  } de derrota. Quando esse número é alto, a falta de diferença em botas não significa concordância entre os grupos.</p>`;
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
