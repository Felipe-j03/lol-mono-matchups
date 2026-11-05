// Casca do site: unico modulo que toca DOM, fetch, location e sessionStorage.
// As telas (screen-*.js) so devolvem strings de HTML.
//
// Regra central: todo arquivo de dados e buscado pelo nome que o proprio JSON
// informa (targets[].file, matchups[].file), nunca por nome montado. Execucoes
// antigas do exportador deixam arquivos orfaos de confrontos que cairam abaixo
// do piso; a lista `matchups` e o indice de quais arquivos sao reais.

import { loadDdragon } from "./ddragon.js";
import { escapeHtml } from "./format.js";
import { championHash, parseRoute } from "./route.js";
import { renderChampion } from "./screen-champion.js";
import { renderChoose } from "./screen-choose.js";
import { renderMatchup } from "./screen-matchup.js";

const app = document.getElementById("app");
const PREFIXO_CACHE = "lolmono:";

// --- cache em sessionStorage -------------------------------------------------
// Qualquer acesso pode lancar (modo privado, cota, armazenamento desligado):
// cache e conveniencia e nunca pode derrubar a pagina.

function lerCache(file, schemaVersion) {
  try {
    const bruto = sessionStorage.getItem(PREFIXO_CACHE + file);
    if (bruto == null) return null;
    const entrada = JSON.parse(bruto);
    if (entrada == null || entrada.schema_version !== schemaVersion) {
      sessionStorage.removeItem(PREFIXO_CACHE + file);
      return null;
    }
    return entrada.data;
  } catch {
    return null;
  }
}

function gravarCache(file, data) {
  try {
    sessionStorage.setItem(
      PREFIXO_CACHE + file,
      JSON.stringify({ schema_version: data.schema_version, data }),
    );
  } catch {
    // sem cache, segue buscando na rede
  }
}

// --- dados -------------------------------------------------------------------

async function buscarJson(file) {
  const resposta = await fetch(`data/${file}`);
  if (!resposta.ok) {
    throw new Error(`data/${file} respondeu ${resposta.status}`);
  }
  return resposta.json();
}

// O index nunca vai ao cache: ele diz qual schema_version esperar dos demais.
async function carregarArquivo(file, schemaVersion) {
  const guardado = lerCache(file, schemaVersion);
  if (guardado != null) return guardado;
  const data = await buscarJson(file);
  gravarCache(file, data);
  return data;
}

let basePromise = null;
function carregarBase() {
  if (basePromise == null) {
    const tentativa = (async () => {
      const index = await buscarJson("index.json");
      const dict = await loadDdragon(index.ddragon_version, fetch);
      return { index, dict };
    })();
    // Falha nao fica memorizada: o proximo hashchange ou recarga tenta de novo.
    tentativa.catch(() => {
      if (basePromise === tentativa) basePromise = null;
    });
    basePromise = tentativa;
  }
  return basePromise;
}

// O slug e o nome do arquivo do alvo sem ".json", como nas telas.
function acharAlvo(index, slug) {
  return index.targets.find(
    (t) => t.has_data && t.file != null && t.file.replace(/\.json$/, "") === slug,
  );
}

// --- desenho -----------------------------------------------------------------

function desenhar(html) {
  app.innerHTML = html;
  globalThis.scrollTo(0, 0);
}

function aviso(texto) {
  return `<p class="warning" role="alert">${escapeHtml(texto)}</p>`;
}

function telaDeEscolha({ index, dict }, textoAviso) {
  desenhar((textoAviso ? aviso(textoAviso) : "") + renderChoose(index, dict));
}

function voltar(href, rotulo) {
  return `<nav class="back"><a href="${escapeHtml(href)}">← ${escapeHtml(rotulo)}</a></nav>`;
}

let geracao = 0;

async function mostrar() {
  const minha = ++geracao;
  const atual = () => minha === geracao;
  app.innerHTML = `<p class="status">Carregando…</p>`;

  try {
    const base = await carregarBase();
    if (!atual()) return;
    const { index, dict } = base;
    const rota = parseRoute(location.hash);

    if (rota.screen === "choose") return telaDeEscolha(base);
    if (rota.screen === "notfound") {
      return telaDeEscolha(base, `Endereço não reconhecido: ${rota.hash}`);
    }

    const alvo = acharAlvo(index, rota.slug);
    if (alvo == null) {
      return telaDeEscolha(base, `Não há dados para "${rota.slug}".`);
    }
    const dadosDoAlvo = await carregarArquivo(alvo.file, index.schema_version);
    if (!atual()) return;

    if (rota.screen === "champion") {
      return desenhar(voltar("#/", "Campeões") + renderChampion(dadosDoAlvo, dict));
    }

    // matchup: o arquivo vem da lista `matchups` do alvo; abaixo do piso nao tem arquivo.
    const item = dadosDoAlvo.matchups.find(
      (m) => m.opponent_champion_id === rota.opponentId && !m.below_floor && m.file != null,
    );
    if (item == null) {
      return desenhar(
        voltar("#/", "Campeões") +
          aviso("Não há página de confronto para esse oponente (poucas partidas ou inexistente).") +
          renderChampion(dadosDoAlvo, dict),
      );
    }
    const confronto = await carregarArquivo(item.file, index.schema_version);
    if (!atual()) return;
    desenhar(
      voltar(championHash(rota.slug), dadosDoAlvo.champion_name) +
        renderMatchup(confronto, dict),
    );
  } catch (erro) {
    if (!atual()) return;
    app.innerHTML = `<section class="erro">
  <p class="warning" role="alert">Não foi possível carregar os dados: ${
      escapeHtml(String(erro?.message ?? erro))
    }</p>
  <p>Recarregue a página para tentar de novo.</p>
</section>`;
  }
}

globalThis.addEventListener("hashchange", mostrar);
mostrar();
