import pytest

from lolmono.riot import PLATFORM_TO_REGIONAL, Mastery, RiotClient, RiotError

KEY = "SECRET-KEY"


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def json(self):
        return self._body


class FakeLimiter:
    def __init__(self):
        self.acquires = 0
        self.penalties = []

    def acquire(self):
        self.acquires += 1

    def penalize(self, seconds):
        self.penalties.append(seconds)


class FakeSend:
    """Responses por URL (lista consumida em ordem; a ultima se repete)."""

    def __init__(self, routes):
        self.routes = routes
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if url not in self.routes:
            return FakeResponse(404)
        queue = self.routes[url]
        return queue.pop(0) if len(queue) > 1 else queue[0]


def make(routes, platform="br1"):
    send = FakeSend(routes)
    limiter = FakeLimiter()
    return RiotClient(platform, limiter, send), send, limiter


def test_platform_to_regional_mapping():
    assert PLATFORM_TO_REGIONAL["br1"] == "americas"
    assert PLATFORM_TO_REGIONAL["kr"] == "asia"
    assert PLATFORM_TO_REGIONAL["euw1"] == "europe"
    assert PLATFORM_TO_REGIONAL["na1"] == "americas"


def test_match_ids_uses_regional_host_and_queue_420():
    url = "https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/PUUID/ids?queue=420&count=60"
    client, send, _ = make({url: [FakeResponse(200, ["BR1_1", "BR1_2"])]})
    assert client.match_ids("PUUID", count=60) == ["BR1_1", "BR1_2"]
    assert "americas.api.riotgames.com" in send.urls[0]
    assert "queue=420" in send.urls[0]
    assert "count=60" in send.urls[0]


def test_regional_host_follows_platform():
    client, send, _ = make({}, platform="kr")
    with pytest.raises(RiotError):
        client.match("KR_1")
    assert send.urls[0].startswith("https://asia.api.riotgames.com/")


LADDER = "https://br1.api.riotgames.com/lol/league/v4/"


def test_ladder_uses_platform_host_and_merges_tiers():
    routes = {
        LADDER + "challengerleagues/by-queue/RANKED_SOLO_5x5": [
            FakeResponse(200, {"entries": [{"puuid": "A"}, {"puuid": "B"}]})
        ],
        LADDER + "grandmasterleagues/by-queue/RANKED_SOLO_5x5": [
            FakeResponse(200, {"entries": [{"puuid": "B"}, {"puuid": "C"}]})
        ],
    }
    client, send, _ = make(routes)
    puuids = client.ladder_puuids(["CHALLENGER", "GRANDMASTER"])
    assert all("br1.api.riotgames.com" in u for u in send.urls)
    assert puuids == ["A", "B", "C"]




def test_ladder_rejects_unknown_tier():
    client, _, _ = make({})
    with pytest.raises(ValueError):
        client.ladder_puuids(["WOOD"])


def test_top_masteries_maps_fields_on_platform_host():
    url = "https://br1.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/P/top?count=3"
    body = [{"championId": 64, "championPoints": 1000, "lastPlayTime": 99, "extra": 1}]
    client, send, _ = make({url: [FakeResponse(200, body)]})
    assert client.top_masteries("P", 3) == [Mastery(64, 1000, 99)]
    assert send.urls == [url]


def test_riot_id_uses_regional_account_endpoint():
    url = "https://americas.api.riotgames.com/riot/account/v1/accounts/by-puuid/P"
    client, _, _ = make({url: [FakeResponse(200, {"gameName": "Nome", "tagLine": "TAG"})]})
    assert client.riot_id("P") == "Nome#TAG"


MATCH = "https://americas.api.riotgames.com/lol/match/v5/matches/"


def test_retries_on_429_honoring_retry_after():
    routes = {
        MATCH + "BR1_1": [
            FakeResponse(429, headers={"Retry-After": "3"}),
            FakeResponse(200, {"ok": True}),
        ]
    }
    client, send, limiter = make(routes)
    assert client.match("BR1_1") == {"ok": True}
    assert limiter.penalties == [3.0]
    assert limiter.acquires == 2
    assert len(send.urls) == 2


def test_429_without_usable_retry_after_falls_back_to_one_second():
    routes = {
        MATCH + "BR1_1": [
            FakeResponse(429),
            FakeResponse(429, headers={"Retry-After": "soon"}),
            FakeResponse(200, {"ok": True}),
        ]
    }
    client, _, limiter = make(routes)
    assert client.match("BR1_1") == {"ok": True}
    assert limiter.penalties == [1.0, 1.0]


def test_gives_up_after_three_429s():
    routes = {MATCH + "BR1_1": [FakeResponse(429, headers={"Retry-After": "1"})]}
    client, send, limiter = make(routes)
    with pytest.raises(RiotError):
        client.match("BR1_1")
    assert len(send.urls) == 3
    assert limiter.acquires == 3


def test_every_send_is_preceded_by_acquire():
    order = []

    class Lim(FakeLimiter):
        def acquire(self):
            order.append("acquire")

    def send(url):
        order.append("send")
        return FakeResponse(200, {})

    RiotClient("br1", Lim(), send).match("X")
    assert order == ["acquire", "send"]


def test_timeline_returns_none_on_404():
    client, _, _ = make({})
    assert client.timeline("BR1_missing") is None


def test_timeline_returns_body():
    routes = {MATCH + "BR1_1/timeline": [FakeResponse(200, {"info": {}})]}
    client, _, _ = make(routes)
    assert client.timeline("BR1_1") == {"info": {}}


def test_match_404_is_an_error():
    client, _, _ = make({})
    with pytest.raises(RiotError):
        client.match("BR1_missing")


def test_raises_on_403():
    routes = {MATCH + "BR1_forbidden": [FakeResponse(403)]}
    client, _, _ = make(routes)
    with pytest.raises(RiotError):
        client.match("BR1_forbidden")


def test_api_key_never_appears_in_error_message():
    routes = {MATCH + "BR1_forbidden": [FakeResponse(403, headers={"X-Riot-Token": KEY})]}
    client, _, _ = make(routes)
    with pytest.raises(RiotError) as info:
        client.match("BR1_forbidden")
    text = str(info.value)
    assert KEY not in text
    assert "riotgames.com" not in text
    assert "https" not in text
    assert "403" in text
    assert "/lol/match/v5/matches/BR1_forbidden" in text


def test_error_message_drops_query_string():
    url = MATCH + "by-puuid/P/ids?queue=420&count=5"
    client, _, _ = make({url: [FakeResponse(500)]})
    with pytest.raises(RiotError) as info:
        client.match_ids("P", 5)
    assert "queue" not in str(info.value)
    assert "500" in str(info.value)


def test_transport_exception_is_wrapped_without_leaking():
    def send(url):
        raise RuntimeError(f"boom {url} header X-Riot-Token={KEY}")

    client = RiotClient("br1", FakeLimiter(), send)
    with pytest.raises(RiotError) as info:
        client.match("BR1_1")
    assert KEY not in str(info.value)
    assert "riotgames.com" not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


@pytest.mark.parametrize(
    "tier,path",
    [
        ("CHALLENGER", "challengerleagues"),
        ("GRANDMASTER", "grandmasterleagues"),
        ("MASTER", "masterleagues"),
    ],
)
def test_apex_tier_uses_dedicated_unpaginated_platform_url(tier, path):
    url = f"https://br1.api.riotgames.com/lol/league/v4/{path}/by-queue/RANKED_SOLO_5x5"
    client, send, _ = make({url: [FakeResponse(200, {"entries": [{"puuid": "A"}]})]})
    assert client.ladder_puuids([tier]) == ["A"]
    assert send.urls == [url]


def test_diamond_walks_four_divisions_and_stops_on_empty_page():
    base = LADDER + "entries/RANKED_SOLO_5x5/DIAMOND/"
    routes = {
        base + "I?page=1": [FakeResponse(200, [{"puuid": "A"}])],
        base + "I?page=2": [FakeResponse(200, [{"puuid": "B"}])],
        base + "I?page=3": [FakeResponse(200, [])],
        base + "II?page=1": [FakeResponse(200, [{"puuid": "C"}])],
        base + "II?page=2": [FakeResponse(200, [])],
        base + "III?page=1": [FakeResponse(200, [])],
        base + "IV?page=1": [FakeResponse(200, [{"puuid": "A"}, {"puuid": "D"}])],
        base + "IV?page=2": [FakeResponse(200, [])],
    }
    client, send, _ = make(routes)
    assert client.ladder_puuids(["DIAMOND"]) == ["A", "B", "C", "D"]
    assert len(send.urls) == 8


def test_missing_puuid_raises_naming_the_field():
    url = LADDER + "challengerleagues/by-queue/RANKED_SOLO_5x5"
    client, _, _ = make({url: [FakeResponse(200, {"entries": [{"summonerId": "x"}]})]})
    with pytest.raises(RiotError, match="puuid"):
        client.ladder_puuids(["CHALLENGER"])


def test_tier_with_zero_entries_raises():
    url = LADDER + "masterleagues/by-queue/RANKED_SOLO_5x5"
    client, _, _ = make({url: [FakeResponse(200, {"entries": []})]})
    with pytest.raises(RiotError, match="MASTER"):
        client.ladder_puuids(["MASTER"])


def test_diamond_with_no_entries_in_any_division_raises():
    client, _, _ = make(
        {LADDER + f"entries/RANKED_SOLO_5x5/DIAMOND/{d}?page=1": [FakeResponse(200, [])] for d in ("I", "II", "III", "IV")}
    )
    with pytest.raises(RiotError, match="DIAMOND"):
        client.ladder_puuids(["DIAMOND"])
