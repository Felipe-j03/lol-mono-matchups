# Coletor e agregação mono-champion — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um coletor que identifica jogadores mono-champion nas escadas de alto elo de quatro regiões, baixa e extrai suas partidas, e produz arquivos JSON agregados com a base de cada campeão e a comparação vencedor/perdedor por matchup.

**Architecture:** Pipeline de quatro estágios com retomada em SQLite. Cada estágio lê o que o anterior gravou e marca progresso, de modo que o processo pode ser morto e retomado. A lógica de decisão — pareamento de função, qualificação de mono, agregação — vive em funções puras testadas contra partidas sintéticas; a camada de rede é injetada e nunca tocada nos testes.

**Tech Stack:** Python 3.11+ (tomllib da biblioteca padrão), httpx, sqlite3 (biblioteca padrão), pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-lol-mono-matchups-design.md`

**Escopo deste plano:** estágios 1 a 4 do coletor, agregação e exportação dos JSON. O site estático é um plano separado, a ser escrito depois do go/no-go da Task 8 e contra os JSON reais produzidos pela Task 12.

## Global Constraints

- Python 3.11 ou superior. `tomllib` da biblioteca padrão para configuração; nenhuma dependência de parsing de TOML.
- Dependências de runtime: apenas `httpx`. Testes: `pytest`. Nada mais.
- Limites de requisição: **20 por 1 segundo e 100 por 120 segundos, simultaneamente, por região**. O limitador respeita as duas janelas.
- Fila ranqueada solo: `queue=420`. Nenhuma outra fila entra em nenhuma agregação.
- Critérios de mono, da spec, verbatim: janela de **60** partidas, concentração **>= 0.50**, mínimo **25** partidas absolutas, elo mínimo **MASTER**.
- Pisos de amostra, da spec, verbatim: **30** partidas para um matchup ser listado; **15** vitórias **e** 15 derrotas para exibir comparação entre os grupos.
- Base calculada sobre **todas** as partidas dos mono, vitórias e derrotas juntas.
- Runas, feitiços e itens iniciais agregados como **conjuntos exatos**. Build final agregada **item por item**. Ordem de habilidades pelos **três primeiros pontos**.
- Roteamento da API é duplo: `league-v4` e `champion-mastery-v4` usam host de **plataforma** (`br1`, `kr`, `euw1`, `na1`); `match-v5` usa host **regional** (`americas`, `asia`, `europe`). Um mapa explícito faz a tradução.
- **A chave da API nunca aparece em arquivo exportado, em log ou em mensagem de erro.** Lida de variável de ambiente `RIOT_API_KEY`.
- Toda estrutura exportada carrega `schema_version` e o número de partidas que a sustenta.

## Review Focus

Classes de entrada que a spec implica e que nenhum caminho principal exercita. Cada linha tem seu teste na task indicada.

1. **Resposta 429 com cabeçalho `Retry-After`** — a janela pré-calculada do limitador pode errar; o cliente precisa esperar o tempo indicado e repetir, não propagar erro. (Task 3)
2. **Timeline ausente, 404** — a spec registra que não toda partida tem timeline. A partida continua válida sem dados de timeline; não é descartada. (Tasks 3 e 10)
3. **Partida encerrada antes do minuto 14** — remake ou rendição. Não existe quadro no minuto 14; `gold_at_14` fica ausente e a partida segue contando nas agregações que não dependem dele. (Task 7)
4. **`teamPosition` vazio, repetido ou com menos de cinco posições distintas** — descarte com motivo registrado e contado, nunca atribuição por palpite. (Task 6)
5. **Matchup com zero vitórias ou zero derrotas** — divisão por zero na taxa e na comparação; a comparação fica indisponível e a taxa é calculada sem estourar. (Tasks 11 e 12)

---

### Task 1: Configuração

**Files:**
- Create: `src/lolmono/config.py`
- Create: `config.example.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nada.
- Produces: `Target(champion_id: int, champion_name: str, role: str)` e `Config` congelados, ambos `@dataclass(frozen=True)`. `Config` tem os campos: `regions: tuple[str, ...]`, `targets: tuple[Target, ...]`, `window_games: int`, `min_share: float`, `min_games: int`, `min_tier: str`, `tiers: tuple[str, ...]`, `mastery_top_n: int`, `mastery_max_days: int`, `matchup_min_games: int`, `delta_min_per_side: int`, `ddragon_version: str`. `load_config(path: Path) -> Config`. `ConfigError(Exception)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_loads_example_config_with_spec_defaults():
    cfg = load_config(Path("config.example.toml"))
    assert cfg.window_games == 60
    assert cfg.min_share == 0.50
    assert cfg.min_games == 25
    assert cfg.min_tier == "MASTER"
    assert cfg.matchup_min_games == 30
    assert cfg.delta_min_per_side == 15
    assert cfg.regions == ("br1", "kr", "euw1", "na1")
    assert Target(91, "Talon", "MIDDLE") in cfg.targets
    assert len(cfg.targets) == 5
    assert cfg.tiers == ("CHALLENGER", "GRANDMASTER", "MASTER")

def test_rejects_unknown_role():
    # TOML com role = "SUPPORT" (o valor válido é "UTILITY")
    with pytest.raises(ConfigError, match="role"):
        load_config(tmp_toml(role="SUPPORT"))

def test_rejects_share_outside_unit_interval():
    with pytest.raises(ConfigError, match="min_share"):
        load_config(tmp_toml(min_share=1.5))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL, `ModuleNotFoundError: lolmono.config`

- [ ] **Step 3: Escrever `config.example.toml`**

Os cinco alvos da spec, com os ids de campeão do Data Dragon: Talon 91 MIDDLE, Gragas 79 MIDDLE, Gragas 79 TOP, Jax 24 TOP, Renekton 58 TOP. Regiões `br1`, `kr`, `euw1`, `na1`. Os seis números das Global Constraints. `mastery_top_n = 7`, `mastery_max_days = 30`, `ddragon_version` fixada numa versão concreta.

Confirmar os cinco `champion_id` contra `https://ddragon.leagueoflegends.com/cdn/<versao>/data/en_US/champion.json` antes de gravar, e corrigir TOML e teste juntos se algum divergir.

`min_tier` é derivado, não digitado: `tiers` é a tupla dos tiers a varrer, e `load_config` a monta a partir de `min_tier` segundo a ordem `CHALLENGER`, `GRANDMASTER`, `MASTER`, `DIAMOND`. `min_tier = "MASTER"` produz os três primeiros. Isso dá um só lugar para afrouxar o elo na recalibragem da Task 9.

- [ ] **Step 4: Implementar `load_config(path: Path) -> Config` em `src/lolmono/config.py`**

Validar: `role` em `{"TOP","JUNGLE","MIDDLE","BOTTOM","UTILITY"}`; `min_share` em `(0, 1]`; inteiros positivos; `regions` não vazio; `targets` sem duplicata de `(champion_id, role)`. Cada falha levanta `ConfigError` cuja mensagem nomeia o campo.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/lolmono/config.py config.example.toml tests/test_config.py
git commit -m "feat: carregamento e validacao de configuracao"
```

---

### Task 2: Limitador de taxa de janela dupla

**Files:**
- Create: `src/lolmono/ratelimit.py`
- Test: `tests/test_ratelimit.py`

**Interfaces:**
- Consumes: nada.
- Produces: `RateLimiter(limits: Sequence[tuple[int, float]], now: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep)`, com `acquire() -> None` e `penalize(seconds: float) -> None`. Construtor de conveniência `riot_limiter(now=..., sleep=...) -> RateLimiter` com `[(20, 1.0), (100, 120.0)]`.

- [ ] **Step 1: Write the failing tests**

Relógio e sono falsos: `sleep` avança o relógio falso e registra a duração.

```python
def test_allows_burst_up_to_shortest_window():
    clock, slept = FakeClock(), []
    rl = riot_limiter(now=clock.now, sleep=clock.advance_recording(slept))
    for _ in range(20):
        rl.acquire()
    assert slept == []

def test_sleeps_when_one_second_window_full():
    # a 21a requisicao espera o bastante para a janela de 1s abrir
    ...
    assert slept and 0 < slept[0] <= 1.0

def test_enforces_two_minute_window_as_well():
    # 100 requisicoes imediatas, a 101a espera perto de 120s mesmo com a
    # janela de 1 segundo livre
    ...
    assert slept[-1] > 100.0

def test_penalize_blocks_until_retry_after_elapses():
    rl.penalize(5.0)
    rl.acquire()
    assert slept[-1] == pytest.approx(5.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ratelimit.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implementar `RateLimiter` em `src/lolmono/ratelimit.py`**

Uma `deque` de instantes por janela. `acquire` descarta os instantes fora de cada janela, e se alguma estiver cheia dorme até o instante mais antigo dela expirar, repetindo a checagem depois de dormir. `penalize` grava um instante até o qual `acquire` dorme antes de qualquer outra avaliação. Sem threads; o coletor é sequencial por região.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ratelimit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lolmono/ratelimit.py tests/test_ratelimit.py
git commit -m "feat: limitador de taxa de janela dupla"
```

---

### Task 3: Cliente da API da Riot

**Files:**
- Create: `src/lolmono/riot.py`
- Test: `tests/test_riot.py`

**Interfaces:**
- Consumes: `RateLimiter` (Task 2).
- Produces: `Mastery(champion_id: int, points: int, last_play_ms: int)` congelado. `RiotClient(api_key: str, platform: str, limiter: RateLimiter, send: Callable[[str], HttpResponse])` com `ladder_puuids(tiers: Sequence[str]) -> list[str]`, `top_masteries(puuid: str, count: int) -> list[Mastery]`, `match_ids(puuid: str, count: int, queue: int = 420) -> list[str]`, `match(match_id: str) -> dict`, `timeline(match_id: str) -> dict | None`, `riot_id(puuid: str) -> str` devolvendo `"Nome#TAG"`. `PLATFORM_TO_REGIONAL: dict[str, str]`. `RiotError(Exception)`.

`send` recebe uma URL completa e devolve um objeto com `status_code: int`, `headers: Mapping[str, str]` e `json() -> object`. Nos testes é uma função que consulta um dicionário; em produção é um `httpx.Client` embrulhado que injeta o cabeçalho `X-Riot-Token`.

- [ ] **Step 1: Write the failing tests**

```python
def test_platform_to_regional_mapping():
    assert PLATFORM_TO_REGIONAL["br1"] == "americas"
    assert PLATFORM_TO_REGIONAL["kr"] == "asia"
    assert PLATFORM_TO_REGIONAL["euw1"] == "europe"
    assert PLATFORM_TO_REGIONAL["na1"] == "americas"

def test_match_ids_uses_regional_host_and_queue_420():
    # fake send registra as URLs pedidas
    client.match_ids("PUUID", count=60)
    assert "americas.api.riotgames.com" in urls[0]
    assert "queue=420" in urls[0]
    assert "count=60" in urls[0]

def test_ladder_uses_platform_host_and_merges_tiers():
    puuids = client.ladder_puuids(["CHALLENGER", "GRANDMASTER"])
    assert all("br1.api.riotgames.com" in u for u in urls)
    assert puuids == ["A", "B", "C"]   # sem duplicata, ordem preservada

def test_retries_on_429_honoring_retry_after():
    # primeira resposta 429 com Retry-After: 3, segunda 200
    result = client.match("BR1_1")
    assert result == {"ok": True}
    assert limiter.penalties == [3.0]

def test_timeline_returns_none_on_404():
    assert client.timeline("BR1_missing") is None

def test_raises_on_403():
    with pytest.raises(RiotError):
        client.match("BR1_forbidden")

def test_api_key_never_appears_in_error_message():
    try:
        client.match("BR1_forbidden")
    except RiotError as exc:
        assert "SECRET-KEY" not in str(exc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_riot.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implementar `RiotClient` em `src/lolmono/riot.py`**

Cada método chama `limiter.acquire()` antes de `send`. Em `429`, chamar `limiter.penalize(float(headers["Retry-After"]))` e repetir, até três tentativas, então `RiotError`. Em `404`, `timeline` e `match` devolvem `None`/levantam conforme a assinatura; os demais códigos fora de `2xx` levantam `RiotError` com a URL **sem** o host e sem nenhum cabeçalho. `ladder_puuids` concatena as entradas dos tiers na ordem recebida, preservando a primeira ocorrência de cada `puuid`.

Para `MASTER`, as entradas vêm paginadas: seguir as páginas até uma vazia.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_riot.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lolmono/riot.py tests/test_riot.py
git commit -m "feat: cliente da API da Riot com roteamento duplo e retry em 429"
```

---

### Task 4: Esquema e progresso em SQLite

**Files:**
- Create: `src/lolmono/db.py`
- Create: `src/lolmono/rows.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nada.
- Produces: em `rows.py`, congelados: `RunePage(keystone: int, primary_style: int, primary_perks: tuple[int, ...], secondary_style: int, secondary_perks: tuple[int, ...], shards: tuple[int, int, int])`; `MatchRow(match_id: str, platform: str, puuid: str, champion_id: int, role: str, opponent_champion_id: int, opponent_puuid: str, win: bool, items: tuple[int, ...], runes: RunePage, spells: tuple[int, int])`; `TimelineRow(match_id: str, puuid: str, gold_at_14: int | None, cs_diff_at_14: int | None, starting_items: tuple[int, ...], item_order: tuple[int, ...], skill_order: tuple[int, int, int], deaths_before_10: int, kills_before_10: int)`.

Em `db.py`, `Database(path: Path)` com: `init_schema()`, `add_candidates(platform, puuids)`, `pending_candidates(platform) -> list[str]`, `mark_screened(platform, puuid, suspect: bool)`, `pending_suspects(platform) -> list[str]`, `confirm_player(platform, puuid, riot_id, champion_id, role, games, share)`, `reject_player(platform, puuid)`, `insert_match(row: MatchRow)`, `match_exists(match_id, puuid) -> bool`, `record_discard(match_id, reason)`, `discard_counts() -> dict[str, int]`, `insert_timeline(row: TimelineRow)`, `matches_awaiting_timeline() -> list[tuple[str, str, str]]`, `confirmed_matches(champion_id, role) -> list[MatchRow]`, `timelines_for(match_ids) -> dict[tuple[str, str], TimelineRow]`, `confirmed_player_count(champion_id, role) -> int`, `confirmed_group_win_rate(champion_id, role) -> float`, `confirmed_players(champion_id, role) -> list[PlayerRow]`, `table_names() -> list[str]`.

`PlayerRow(platform: str, puuid: str, riot_id: str, champion_id: int, role: str, games: int, share: float, win_rate: float)` congelado, em `rows.py`. É a lista de referência que a Tela 2 da spec mostra; `puuid` não é exportado, só `riot_id` e `platform`.

- [ ] **Step 1: Write the failing tests**

```python
def test_init_schema_is_idempotent():
    db.init_schema(); db.init_schema()
    tables = db.table_names()
    assert {"candidate", "player", "match", "timeline", "discard"} <= set(tables)

def test_candidate_lifecycle_tracks_progress():
    db.add_candidates("br1", ["A", "B"])
    assert set(db.pending_candidates("br1")) == {"A", "B"}
    db.mark_screened("br1", "A", suspect=True)
    assert db.pending_candidates("br1") == ["B"]
    assert db.pending_suspects("br1") == ["A"]

def test_add_candidates_is_idempotent_on_rerun():
    db.add_candidates("br1", ["A"]); db.add_candidates("br1", ["A"])
    assert db.pending_candidates("br1") == ["A"]

def test_match_roundtrip_preserves_runes_and_items():
    db.insert_match(row)
    assert db.confirmed_matches(row.champion_id, row.role) == []   # jogador nao confirmado
    db.confirm_player("br1", row.puuid, "Mono#BR1", row.champion_id, row.role, 30, 0.6)
    assert db.confirmed_matches(row.champion_id, row.role) == [row]

def test_confirmed_players_exposes_reference_list_without_puuid_leak():
    db.insert_match(row)
    db.confirm_player("br1", row.puuid, "Mono#BR1", row.champion_id, row.role, 30, 0.6)
    players = db.confirmed_players(row.champion_id, row.role)
    assert [p.riot_id for p in players] == ["Mono#BR1"]
    assert players[0].platform == "br1"
    assert players[0].win_rate == 1.0   # calculado das partidas gravadas

def test_discard_counts_group_by_reason():
    db.record_discard("BR1_1", "unpaired_lanes")
    db.record_discard("BR1_2", "unpaired_lanes")
    db.record_discard("BR1_3", "missing_position")
    assert db.discard_counts() == {"unpaired_lanes": 2, "missing_position": 1}

def test_matches_awaiting_timeline_excludes_already_extracted():
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implementar `rows.py` e `Database` em `src/lolmono/db.py`**

Tabelas: `candidate(platform, puuid, screened, suspect)` com chave composta; `player(platform, puuid, champion_id, role, games, share, confirmed)`; `match(match_id, platform, puuid, ...)` com chave composta `(match_id, puuid)` porque duas contas rastreadas podem aparecer na mesma partida; `timeline(match_id, puuid, ...)`; `discard(match_id, reason)`.

`items`, `spells`, e os campos de `RunePage` serializados como JSON em coluna de texto; a desserialização reconstrói as dataclasses com tuplas, para que a comparação de igualdade dos testes funcione. `confirmed_matches` só devolve partidas cujo jogador está confirmado para aquele par campeão/função. `PRAGMA journal_mode=WAL` e `commit` por lote, para que uma interrupção não perca mais que o lote corrente.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lolmono/db.py src/lolmono/rows.py tests/test_db.py
git commit -m "feat: esquema sqlite com retomada de progresso"
```

---

### Task 5: Peneira por maestria

**Files:**
- Create: `src/lolmono/screen.py`
- Test: `tests/test_screen.py`

**Interfaces:**
- Consumes: `Mastery` (Task 3), `Config`, `Target` (Task 1).
- Produces: `is_suspect(masteries: Sequence[Mastery], targets: Sequence[Target], top_n: int, max_days: int, now_ms: int) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
def test_suspect_when_target_champion_is_top_and_recent():
    masteries = [Mastery(TALON, 500_000, now_ms - days(3))]
    assert is_suspect(masteries, targets, top_n=7, max_days=30, now_ms=now_ms)

def test_not_suspect_when_target_not_played_recently():
    masteries = [Mastery(TALON, 500_000, now_ms - days(400))]
    assert not is_suspect(masteries, targets, top_n=7, max_days=30, now_ms=now_ms)

def test_not_suspect_when_no_target_champion_present():
    masteries = [Mastery(ZED, 900_000, now_ms)]
    assert not is_suspect(masteries, targets, top_n=7, max_days=30, now_ms=now_ms)

def test_only_the_first_top_n_entries_count():
    # alvo na oitava posicao por pontos, top_n=7
    assert not is_suspect(masteries, targets, top_n=7, max_days=30, now_ms=now_ms)

def test_role_is_not_considered_at_this_stage():
    # a maestria nao traz funcao; um unico alvo com aquele champion_id basta,
    # qualquer que seja a role configurada
    masteries = [Mastery(GRAGAS, 400_000, now_ms)]
    assert is_suspect(masteries, [Target(GRAGAS, "Gragas", "TOP")], 7, 30, now_ms)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_screen.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implementar `is_suspect` em `src/lolmono/screen.py`**

Ordenar por pontos decrescentes, cortar em `top_n`, e devolver verdadeiro se algum desses tiver `champion_id` de algum alvo e `last_play_ms` dentro de `max_days`. Função pura; não conhece rede nem banco.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_screen.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lolmono/screen.py tests/test_screen.py
git commit -m "feat: peneira de suspeitos por maestria"
```

---

### Task 6: Pareamento de funções e extração de partida

**Files:**
- Create: `src/lolmono/matchparse.py`
- Create: `tests/fixtures/match_clean.json`
- Create: `tests/fixtures/match_unpaired.json`
- Test: `tests/test_matchparse.py`

**Interfaces:**
- Consumes: `MatchRow`, `RunePage` (Task 4).
- Produces: `DiscardMatch(Exception)` com atributo `reason: str`. `pair_lanes(participants: Sequence[dict]) -> dict[str, tuple[dict, dict]]`, que levanta `DiscardMatch` quando as dez posições não formam cinco pares limpos. `extract_match(match_json: dict, puuid: str) -> MatchRow`, que levanta `DiscardMatch`.

Motivos de descarte, exatos: `"missing_position"`, `"unpaired_lanes"`, `"wrong_queue"`, `"puuid_absent"`.

- [ ] **Step 1: Write the failing tests**

Fixtures montadas à mão, dez participantes, campos mínimos.

```python
def test_pair_lanes_returns_five_pairs():
    pairs = pair_lanes(clean["info"]["participants"])
    assert set(pairs) == {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}

def test_empty_team_position_is_discarded():
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(participants_with_blank_position)
    assert exc.value.reason == "missing_position"

def test_duplicated_position_in_one_team_is_discarded():
    # dois MIDDLE no time 100, nenhum JUNGLE
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(participants_with_two_middles)
    assert exc.value.reason == "unpaired_lanes"

def test_extract_match_identifies_opponent_in_same_position():
    row = extract_match(clean, puuid="TALON_PLAYER")
    assert row.role == "MIDDLE"
    assert row.opponent_champion_id == EKKO
    assert row.opponent_puuid == "EKKO_PLAYER"
    assert row.win is True

def test_extract_match_keeps_full_rune_page():
    row = extract_match(clean, puuid="TALON_PLAYER")
    assert row.runes.keystone == 8112
    assert len(row.runes.primary_perks) == 4
    assert len(row.runes.shards) == 3

def test_non_ranked_solo_queue_is_discarded():
    with pytest.raises(DiscardMatch) as exc:
        extract_match(aram, puuid="X")
    assert exc.value.reason == "wrong_queue"

def test_puuid_not_in_match_is_discarded():
    with pytest.raises(DiscardMatch) as exc:
        extract_match(clean, puuid="STRANGER")
    assert exc.value.reason == "puuid_absent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_matchparse.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implementar `pair_lanes` e `extract_match` em `src/lolmono/matchparse.py`**

`pair_lanes`: agrupar por `teamId` e `teamPosition`; qualquer posição vazia é `missing_position`; se cada time não tiver exatamente as cinco posições distintas, `unpaired_lanes`. Nunca inferir posição a partir de outro campo.

`extract_match`: checar `info.queueId == 420`, localizar o participante pelo `puuid`, tirar o oponente do par da mesma posição no outro time, e montar `MatchRow`. Itens: os sete slots `item0`..`item6`, descartando zeros e o slot de visão. Runas: `perks.styles[0]` para a árvore primária com seus quatro `selections`, `styles[1]` para a secundária, e `perks.statPerks` para os três fragmentos.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_matchparse.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lolmono/matchparse.py tests/test_matchparse.py tests/fixtures/
git commit -m "feat: pareamento de funcoes e extracao de partida com descarte explicito"
```

---

### Task 7: Extração de timeline

**Files:**
- Create: `src/lolmono/timelineparse.py`
- Create: `tests/fixtures/timeline_full.json`
- Create: `tests/fixtures/timeline_remake.json`
- Test: `tests/test_timelineparse.py`

**Interfaces:**
- Consumes: `TimelineRow` (Task 4).
- Produces: `extract_timeline(timeline_json: dict, puuid: str, opponent_puuid: str) -> TimelineRow`.

- [ ] **Step 1: Write the failing tests**

```python
def test_extracts_gold_and_cs_difference_at_minute_14():
    row = extract_timeline(full, "ME", "THEM")
    assert row.gold_at_14 == 5200
    assert row.cs_diff_at_14 == 12

def test_extracts_starting_items_from_first_purchases():
    assert row.starting_items == (1055, 2003, 2003)

def test_item_order_lists_purchases_in_sequence_ignoring_sales():
    assert row.item_order == (1055, 3134, 6692)

def test_skill_order_is_first_three_points():
    assert row.skill_order == (1, 3, 1)

def test_counts_deaths_and_kills_before_minute_10():
    assert row.deaths_before_10 == 2
    assert row.kills_before_10 == 1

def test_match_ending_before_minute_14_has_no_gold_or_cs():
    row = extract_timeline(remake, "ME", "THEM")
    assert row.gold_at_14 is None
    assert row.cs_diff_at_14 is None
    assert row.deaths_before_10 == 0   # os outros campos seguem preenchidos
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_timelineparse.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implementar `extract_timeline` em `src/lolmono/timelineparse.py`**

`participantId` é o índice de `metadata.participants` mais um, para os dois puuids. Quadros em `info.frames`; o do minuto 14 é o de maior `timestamp` menor ou igual a `14 * 60_000`, e se não existir quadro a partir do minuto 14 os dois campos ficam `None`. Ouro: `participantFrames[id].totalGold`. Farm: `minionsKilled` mais `jungleMinionsKilled`, diferença entre jogador e oponente.

Eventos em `frames[].events`: `ITEM_PURCHASED` para itens, com os anteriores ao primeiro `timestamp` positivo de jogo contando como iniciais; `ITEM_SOLD` e `ITEM_UNDO` removem o item correspondente da ordem; `SKILL_LEVEL_UP` com `levelUpType == "NORMAL"` para a ordem de habilidades, cortada em três; `CHAMPION_KILL` antes de `10 * 60_000` para abates e mortes.

Só os quadros até o minuto 15 são percorridos; o resto é ignorado sem ser desserializado em estrutura própria.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_timelineparse.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lolmono/timelineparse.py tests/test_timelineparse.py tests/fixtures/
git commit -m "feat: extracao de timeline com descarte do cru"
```

---

### Task 8: Estágios 1 e 2 do coletor, com relatório de peneira

**Files:**
- Create: `src/lolmono/collect.py`
- Create: `src/lolmono/__main__.py`
- Test: `tests/test_collect_screening.py`

**Interfaces:**
- Consumes: `RiotClient` (3), `Database` (4), `is_suspect` (5), `Config` (1).
- Produces: `collect_ladder(client, db, cfg, platform) -> int` devolvendo quantos candidatos novos, varrendo `cfg.tiers`. `screen_candidates(client, db, cfg, platform, now_ms) -> ScreenReport`, com `ScreenReport(screened: int, suspects: int)` congelado. CLI `python -m lolmono ladder --platform br1` e `python -m lolmono screen --platform br1`.

- [ ] **Step 1: Write the failing tests**

Cliente falso que devolve respostas de dicionário; banco em arquivo temporário.

```python
def test_collect_ladder_stores_candidates_once():
    assert collect_ladder(fake, db, cfg, "br1") == 3
    assert collect_ladder(fake, db, cfg, "br1") == 0

def test_screen_marks_suspects_and_rejects():
    report = screen_candidates(fake, db, cfg, "br1", now_ms)
    assert report.screened == 3
    assert report.suspects == 1
    assert db.pending_suspects("br1") == ["MONO"]

def test_screening_resumes_without_rescreening():
    screen_candidates(fake, db, cfg, "br1", now_ms)
    assert screen_candidates(fake, db, cfg, "br1", now_ms).screened == 0

def test_screening_uses_one_request_per_candidate():
    screen_candidates(fake, db, cfg, "br1", now_ms)
    assert fake.mastery_calls == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_collect_screening.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implementar `collect_ladder` e `screen_candidates` em `src/lolmono/collect.py`, com o CLI em `src/lolmono/__main__.py`**

`screen_candidates` itera `db.pending_candidates(platform)`, chama `client.top_masteries(puuid, cfg.mastery_top_n)`, aplica `is_suspect`, grava com `db.mark_screened`, e faz commit a cada lote de 50. A chave vem de `RIOT_API_KEY`; ausente, o CLI sai com mensagem e código 2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_collect_screening.py -v`
Expected: PASS

- [ ] **Step 5: Rodar a peneira de verdade numa região e registrar o resultado**

Run: `RIOT_API_KEY=... python -m lolmono ladder --platform br1 && RIOT_API_KEY=... python -m lolmono screen --platform br1`
Expected: imprime candidatos e suspeitos. Anotar os dois números: eles calibram `mastery_top_n` e `mastery_max_days` antes de gastar o estágio caro. Suspeitos acima de uns poucos por cento dos candidatos indica peneira frouxa.

- [ ] **Step 6: Commit**

```bash
git add src/lolmono/collect.py src/lolmono/__main__.py tests/test_collect_screening.py
git commit -m "feat: estagios de escada e peneira com relatorio"
```

---

### Task 9: Estágio 3 e confirmação de mono — go/no-go

**Files:**
- Modify: `src/lolmono/collect.py`
- Create: `src/lolmono/mono.py`
- Test: `tests/test_mono.py`
- Test: `tests/test_collect_matches.py`

**Interfaces:**
- Consumes: `extract_match`, `DiscardMatch` (6), `Database` (4), `RiotClient` (3), `Config` (1).
- Produces: `qualify(rows: Sequence[MatchRow], targets, window_games, min_share, min_games) -> tuple[Target, int, float] | None` em `mono.py`. `collect_matches(client, db, cfg, platform) -> MatchReport` em `collect.py`, com `MatchReport(players: int, confirmed: int, matches: int, discarded: dict[str, int])`. CLI `python -m lolmono matches --platform br1`.

- [ ] **Step 1: Write the failing tests**

```python
def test_qualifies_when_share_and_absolute_minimum_are_met():
    rows = [talon_mid()] * 30 + [other()] * 30
    assert qualify(rows, targets, 60, 0.50, 25) == (TALON_MID, 30, 0.5)

def test_rejects_high_share_with_too_few_absolute_games():
    rows = [talon_mid()] * 8 + [other()] * 4      # 67%, mas 8 partidas
    assert qualify(rows, targets, 60, 0.50, 25) is None

def test_rejects_enough_absolute_games_with_low_share():
    # 25 na janela de 60 satisfaz o minimo absoluto, mas 0.4167 < 0.50
    rows = [talon_mid()] * 25 + [other()] * 35
    assert qualify(rows, targets, 60, 0.50, 25) is None

def test_same_champion_in_two_roles_counts_separately():
    rows = [gragas_top()] * 26 + [gragas_mid()] * 26
    # nenhum dos dois pares atinge 50% isolado
    assert qualify(rows, targets, 60, 0.50, 25) is None

def test_only_the_window_most_recent_games_count():
    # 25 Talon antigos fora da janela de 60 nao contam
    ...

def test_collect_matches_confirms_and_rejects_players():
    report = collect_matches(fake, db, cfg, "br1")
    assert report.confirmed == 1
    assert db.confirmed_matches(TALON, "MIDDLE")

def test_discarded_matches_are_counted_not_raised():
    report = collect_matches(fake, db, cfg, "br1")
    assert report.discarded["unpaired_lanes"] == 1

def test_rejected_player_matches_are_excluded_from_aggregation():
    collect_matches(fake, db, cfg, "br1")
    assert db.confirmed_matches(ZED, "MIDDLE") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mono.py tests/test_collect_matches.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implementar `qualify` em `src/lolmono/mono.py` e `collect_matches` em `collect.py`**

`qualify` recebe as partidas já na ordem mais recente primeiro, corta em `window_games`, conta por `(champion_id, role)`, e devolve o primeiro alvo que satisfaça **as duas** condições. Empate entre dois alvos não é possível com `min_share >= 0.5`; se `min_share` for configurado abaixo de 0.5, devolver o de maior contagem.

`collect_matches` itera `db.pending_suspects(platform)`, busca `match_ids(puuid, cfg.window_games)`, e para cada identificador ainda não gravado chama `client.match` e `extract_match`. `DiscardMatch` vira `db.record_discard` e segue. Ao fim do jogador, `qualify` sobre as linhas extraídas decide entre `db.confirm_player` e `db.reject_player`. Só no caminho da confirmação, uma chamada a `client.riot_id(puuid)` busca o nome a gravar — é uma requisição por confirmado, algumas dezenas no total, e os rejeitados não custam nada. O commit acontece por jogador, para que a retomada nunca deixe um jogador meio processado.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mono.py tests/test_collect_matches.py -v`
Expected: PASS

- [ ] **Step 5: GO/NO-GO — rodar numa região e decidir**

Run: `RIOT_API_KEY=... python -m lolmono matches --platform br1`
Expected: imprime jogadores processados, confirmados por par, partidas gravadas e descartes por motivo.

**Esta é a etapa que decide o projeto.** Registrar os confirmados por par e extrapolar para quatro regiões. Se o número projetado por par ficar na casa de dezenas, seguir. Se ficar em poucas unidades, parar e recalibrar por configuração — `min_tier` mais baixo, `min_share` menor, `window_games` maior, peneira mais frouxa — antes de qualquer task seguinte.

Conferir também a taxa de descarte. Acima de uns 10%, investigar `pair_lanes` contra partidas reais antes de prosseguir: descarte alto em silêncio é o modo de falha que a spec nomeia como mais perigoso.

- [ ] **Step 6: Commit**

```bash
git add src/lolmono/mono.py src/lolmono/collect.py tests/test_mono.py tests/test_collect_matches.py
git commit -m "feat: confirmacao de mono sobre partidas reais"
```

---

### Task 10: Estágio 4 do coletor

**Files:**
- Modify: `src/lolmono/collect.py`
- Test: `tests/test_collect_timelines.py`

**Interfaces:**
- Consumes: `extract_timeline` (7), `Database` (4), `RiotClient` (3).
- Produces: `collect_timelines(client, db, platform, raw_sample_dir: Path | None = None) -> TimelineReport`, com `TimelineReport(requested: int, extracted: int, missing: int)`. CLI `python -m lolmono timelines --platform br1`.

- [ ] **Step 1: Write the failing tests**

```python
def test_only_confirmed_matches_get_timelines():
    report = collect_timelines(fake, db, "br1")
    assert fake.timeline_calls == ["BR1_confirmed"]

def test_missing_timeline_is_counted_not_fatal():
    report = collect_timelines(fake, db, "br1")   # cliente devolve None
    assert report.missing == 1 and report.extracted == 0

def test_resumes_without_refetching_extracted_timelines():
    collect_timelines(fake, db, "br1")
    assert collect_timelines(fake, db, "br1").requested == 0

def test_raw_sample_is_written_when_directory_given(tmp_path):
    collect_timelines(fake, db, "br1", raw_sample_dir=tmp_path)
    assert list(tmp_path.glob("*.json.gz"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_collect_timelines.py -v`
Expected: FAIL, `AttributeError: collect_timelines`

- [ ] **Step 3: Implementar `collect_timelines` em `src/lolmono/collect.py`**

Itera `db.matches_awaiting_timeline()`, que devolve `(match_id, puuid, opponent_puuid)` só de jogadores confirmados. `client.timeline` devolvendo `None` conta em `missing` e grava o par para não ser pedido de novo. Quando `raw_sample_dir` é dado, gravar o JSON cru comprimido das primeiras 200 partidas e só delas; o resto é descartado após a extração.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_collect_timelines.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lolmono/collect.py tests/test_collect_timelines.py
git commit -m "feat: coleta de timelines dos confirmados"
```

---

### Task 11: Agregação — base e ranking de matchups

**Files:**
- Create: `src/lolmono/aggregate.py`
- Test: `tests/test_aggregate_baseline.py`
- Test: `tests/test_aggregate_matchups.py`

**Interfaces:**
- Consumes: `MatchRow`, `TimelineRow`, `RunePage` (4).
- Produces: congelados `Baseline(games: int, players: int, win_rate: float, group_win_rate: float, runes: RunePage, runes_games: int, spells: tuple[int, int], spells_games: int, item_frequency: tuple[tuple[int, int], ...], starting_items: tuple[int, ...] | None, starting_items_games: int, skill_order: tuple[int, int, int] | None, skill_order_games: int)` e `MatchupSummary(opponent_champion_id: int, games: int, wins: int, win_rate: float, below_floor: bool)`.

Os dois campos opcionais vêm de timeline e ficam `None` quando nenhuma partida do grupo tiver timeline extraída; suas contagens ficam `0`. `compute_baseline(rows, timelines, players: int, group_win_rate: float) -> Baseline`. `rank_matchups(rows, min_games: int) -> list[MatchupSummary]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_baseline_uses_wins_and_losses_together():
    # 3 partidas com pagina A, 2 das quais derrotas; 2 com pagina B, ambas vitorias
    base = compute_baseline(rows, timelines, players=2, group_win_rate=0.5)
    assert base.runes == PAGE_A          # mais jogada, nao mais vitoriosa
    assert base.runes_games == 3

def test_baseline_reports_win_rate_of_its_own_configuration():
    assert base.win_rate == pytest.approx(1 / 3)

def test_build_is_aggregated_item_by_item_in_descending_count():
    assert base.item_frequency[0] == (3078, 4)

def test_starting_items_use_exact_set():
    assert base.starting_items == (1055, 2003, 2003)

def test_skill_order_uses_first_three_points():
    assert base.skill_order == (1, 3, 1)

def test_baseline_ignores_rows_without_timeline_for_timeline_fields():
    # nenhuma timeline disponivel
    base = compute_baseline(rows, {}, players=1, group_win_rate=0.5)
    assert base.skill_order is None and base.starting_items is None

def test_matchups_sorted_worst_first():
    ranked = rank_matchups(rows, min_games=30)
    assert [m.opponent_champion_id for m in ranked] == [EKKO, SYLAS]

def test_matchups_below_floor_are_flagged_and_sorted_last():
    ranked = rank_matchups(rows, min_games=30)
    assert ranked[-1].below_floor is True
    assert all(not m.below_floor for m in ranked[:-1])

def test_matchup_with_zero_wins_does_not_raise():
    ranked = rank_matchups(all_losses_vs_ekko, min_games=1)
    assert ranked[0].win_rate == 0.0

def test_matchup_with_zero_games_is_absent_not_zero():
    assert all(m.games > 0 for m in rank_matchups(rows, min_games=1))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_aggregate_baseline.py tests/test_aggregate_matchups.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implementar `compute_baseline` e `rank_matchups` em `src/lolmono/aggregate.py`**

`compute_baseline`: `Counter` sobre o conjunto exato de runas, de feitiços, de itens iniciais e dos três primeiros pontos de habilidade, tomando o mais comum e sua contagem; `Counter` sobre itens individuais para `item_frequency`, ordenado por contagem decrescente e, no empate, por `item_id`. `win_rate` é a taxa das partidas que usaram a configuração de runas escolhida, não a do grupo todo. Campos que vêm de timeline ficam `None` quando nenhuma linha tiver timeline.

`rank_matchups`: agrupar por `opponent_champion_id`, calcular taxa, marcar `below_floor` quando `games < min_games`, e ordenar com os acima do piso primeiro por taxa crescente, depois os abaixo do piso por partidas decrescente.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_aggregate_baseline.py tests/test_aggregate_matchups.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lolmono/aggregate.py tests/test_aggregate_baseline.py tests/test_aggregate_matchups.py
git commit -m "feat: base por campeao e ranking de matchups"
```

---

### Task 12: Comparação vencedor/perdedor e exportação JSON

**Files:**
- Modify: `src/lolmono/aggregate.py`
- Create: `src/lolmono/export.py`
- Modify: `src/lolmono/__main__.py`
- Test: `tests/test_aggregate_compare.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `Baseline`, `MatchupSummary` (11), `Database` e `PlayerRow` (4), `Config` (1).
- Produces: congelados `Divergence(field: str, label: str, winner_share: float, loser_share: float, gap: float)` e `MatchupDetail(opponent_champion_id, wins, losses, comparable: bool, divergences: tuple[Divergence, ...], winner_gold_at_14: float | None, loser_gold_at_14: float | None, headline: str | None)`. `compare_matchup(rows, timelines, opponent_champion_id, min_per_side) -> MatchupDetail`. `export_all(db, cfg, out_dir: Path) -> None` em `export.py`. CLI `python -m lolmono export --out site/data`.

`field` assume `"boots"`, `"rune"`, `"starting_items"` ou `"skill_order"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_comparison_unavailable_below_fifteen_per_side():
    detail = compare_matchup(rows_14_wins_20_losses, tl, EKKO, min_per_side=15)
    assert detail.comparable is False and detail.divergences == ()
    assert detail.wins == 14 and detail.losses == 20

def test_zero_losses_is_not_comparable_and_does_not_raise():
    detail = compare_matchup(all_wins, tl, EKKO, min_per_side=15)
    assert detail.comparable is False

def test_reports_boot_divergence_with_both_shares():
    detail = compare_matchup(rows, tl, EKKO, min_per_side=15)
    boots = next(d for d in detail.divergences if d.field == "boots")
    assert boots.winner_share == pytest.approx(0.8)
    assert boots.loser_share == pytest.approx(0.2)

def test_choices_shared_by_both_groups_are_omitted():
    assert all(d.gap > 0 for d in detail.divergences)
    assert not any(d.label == "Flash" for d in detail.divergences)

def test_divergences_sorted_by_gap_descending():
    gaps = [d.gap for d in detail.divergences]
    assert gaps == sorted(gaps, reverse=True)

def test_identical_groups_produce_no_divergence_and_say_so():
    detail = compare_matchup(identical_rows, tl, EKKO, min_per_side=15)
    assert detail.divergences == ()
    assert detail.comparable is True
    assert "igual" in detail.headline

def test_gold_at_14_averages_skip_rows_without_the_field():
    detail = compare_matchup(rows_with_one_remake, tl, EKKO, min_per_side=15)
    assert detail.winner_gold_at_14 == pytest.approx(5200.0)

def test_export_writes_index_and_per_target_files(tmp_path):
    export_all(db, cfg, tmp_path)
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["schema_version"] == 1
    assert len(index["targets"]) == 5
    assert (tmp_path / "talon-middle.json").exists()

def test_exported_files_never_contain_the_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("RIOT_API_KEY", "SECRET-KEY")
    export_all(db, cfg, tmp_path)
    for path in tmp_path.rglob("*.json"):
        assert "SECRET-KEY" not in path.read_text()

def test_exports_reference_player_list_with_name_and_region(tmp_path):
    export_all(db, cfg, tmp_path)
    data = json.loads((tmp_path / "talon-middle.json").read_text())
    assert data["reference_players"][0]["riot_id"] == "Mono#BR1"
    assert data["reference_players"][0]["platform"] == "br1"
    assert "win_rate" in data["reference_players"][0]

def test_exported_files_never_contain_puuids(tmp_path):
    export_all(db, cfg, tmp_path)
    for path in tmp_path.rglob("*.json"):
        assert KNOWN_PUUID not in path.read_text()

def test_every_exported_object_carries_its_sample_size(tmp_path):
    export_all(db, cfg, tmp_path)
    data = json.loads((tmp_path / "talon-middle.json").read_text())
    assert data["baseline"]["games"] > 0
    assert all("games" in m for m in data["matchups"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_aggregate_compare.py tests/test_export.py -v`
Expected: FAIL, `ImportError: compare_matchup`

- [ ] **Step 3: Implementar `compare_matchup` em `aggregate.py` e `export_all` em `src/lolmono/export.py`**

`compare_matchup`: separar por `win`, e se qualquer lado tiver menos que `min_per_side`, devolver `comparable=False` com as contagens e nada mais. Caso contrário, para cada campo comparável calcular a participação de cada opção nos dois grupos, e emitir `Divergence` onde `abs(winner_share - loser_share)` exceder um limiar de 0.15, com `gap` sendo essa diferença. Botas vêm dos `items` cruzados com uma constante `BOOT_ITEM_IDS` no módulo. Runas comparadas perk por perk, não página inteira, para que a divergência aponte a escolha e não o conjunto. `headline` é a maior divergência em texto, ou uma frase dizendo que os grupos não diferiram.

`export_all`: um `index.json` com `schema_version`, `ddragon_version` e a lista de alvos com contagem de mono e de partidas; um arquivo por alvo com a base, o ranking de matchups e `reference_players` vindo de `db.confirmed_players`; e um arquivo por matchup acima do piso com o detalhe. `puuid` nunca é serializado, em nenhum arquivo. Nomes de arquivo em minúsculas, `<campeao>-<role>.json`. Nenhum campo lê variável de ambiente.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_aggregate_compare.py tests/test_export.py -v`
Expected: PASS

- [ ] **Step 5: Conferência externa contra os sites públicos**

Run: `python -m lolmono export --out site/data` e abrir `site/data/<alvo>.json`
Expected: a taxa de vitória geral de cada alvo na casa dos 48 a 55%. Comparar com U.GG ou Lolalytics para o mesmo campeão e função. Divergência grande — 62% nosso contra 50% deles — indica bug na coleta ou no pareamento, e precisa ser investigada antes de qualquer uso dos dados. Diferença de poucos pontos é esperada: a população é só mono de elo alto.

- [ ] **Step 6: Commit**

```bash
git add src/lolmono/aggregate.py src/lolmono/export.py src/lolmono/__main__.py tests/test_aggregate_compare.py tests/test_export.py
git commit -m "feat: comparacao vencedor/perdedor e exportacao json"
```

---

## Depois deste plano

A coleta completa nas quatro regiões roda com os estágios já implementados, uma região por vez ou em paralelo. Com os JSON em mão, escrever o plano do site estático contra o contrato real que a Task 12 produziu — não contra um contrato imaginado agora.
