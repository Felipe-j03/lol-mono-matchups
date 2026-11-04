"""Cliente da API da Riot: unico modulo do projeto que conhece HTTP.

Dois tipos de host: plataforma (league-v4, champion-mastery-v4) e regional
(match-v5, account-v1). Usar o host errado devolve 404.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

PLATFORM_TO_REGIONAL: dict[str, str] = {
    "br1": "americas",
    "na1": "americas",
    "kr": "asia",
    "euw1": "europe",
}

QUEUE = "RANKED_SOLO_5x5"
MAX_ATTEMPTS = 3
DEFAULT_RETRY_AFTER = 1.0
# Backoff before retrying a 5xx or a transport failure, in seconds, one entry per
# retry. A 503 or a reset connection is routine over a collection that runs for
# hours; without a retry it would end an unattended overnight run on the spot.
# Resumability protects the data, not the night.
TRANSIENT_BACKOFF = (1.0, 4.0)
_LEAGUE_TIERS = {
    "CHALLENGER": "challengerleagues",
    "GRANDMASTER": "grandmasterleagues",
    "MASTER": "masterleagues",
}
_DIVISIONS = ("I", "II", "III", "IV")
# A Riot puuid is 78 characters; no other path segment this project builds comes
# close (the longest is "champion-masteries", 18, and a match id is about 15).
_PUUID_MIN_LENGTH = 40


class RiotError(Exception):
    pass


class HttpResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def json(self) -> object: ...


@dataclass(frozen=True)
class Mastery:
    champion_id: int
    points: int
    last_play_ms: int


def _path(url: str) -> str:
    """The URL's path, with any puuid segment redacted.

    The host carries the API key's header and the query carries nothing useful,
    so an error message quotes the path only. The mastery, match-ids and account
    paths embed a puuid, which is a permanent account identifier, and the CLI
    prints these messages: a long opaque segment is replaced by a marker.
    """
    return "/".join(
        "<puuid>" if len(segment) >= _PUUID_MIN_LENGTH else segment
        for segment in urlsplit(url).path.split("/")
    )


def _retry_after(response: HttpResponse) -> float:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, TypeError, ValueError):
        return DEFAULT_RETRY_AFTER


class RiotClient:
    def __init__(
        self,
        platform: str,
        limiter,
        send: Callable[[str], HttpResponse],
    ) -> None:
        self._platform_host = f"https://{platform}.api.riotgames.com"
        self._regional_host = f"https://{PLATFORM_TO_REGIONAL[platform]}.api.riotgames.com"
        self._limiter = limiter
        self._send = send

    def _get(self, url: str, *, none_on_404: bool = False) -> object:
        """GET with retries. 429 and transient failures are retried; 4xx is not.

        A 429 waits the server's Retry-After, up to ``MAX_ATTEMPTS`` tries. A 5xx
        and a transport failure (reset connection, timeout, DNS) each wait
        ``TRANSIENT_BACKOFF`` and are retried once per entry: they are the
        routine weather of a run that lasts hours, and the limiter's penalty is
        reused as the sleep, so the backoff also protects the rate budget. Any
        other non-2xx is our bug or an expired key and is raised at once.
        """
        throttled = 0
        transient = 0

        def wait_or_stop() -> bool:
            """Back off for one more try, or say that the retries are spent."""
            nonlocal transient
            if transient >= len(TRANSIENT_BACKOFF):
                return False
            self._limiter.penalize(TRANSIENT_BACKOFF[transient])
            transient += 1
            return True

        while True:
            self._limiter.acquire()
            try:
                response = self._send(url)
            except Exception as exc:
                # The exception is never chained: its message can carry the URL
                # and therefore the API key's header.
                trouble = f"transport failure ({type(exc).__name__})"
                if wait_or_stop():
                    continue
                raise RiotError(f"{trouble} for {_path(url)}") from None
            status = response.status_code
            if status == 429:
                throttled += 1
                if throttled >= MAX_ATTEMPTS:
                    raise RiotError(
                        f"HTTP 429 after {MAX_ATTEMPTS} attempts for {_path(url)}"
                    )
                self._limiter.penalize(_retry_after(response))
                continue
            if status == 404 and none_on_404:
                return None
            if 500 <= status < 600:
                trouble = f"HTTP {status}"
                if wait_or_stop():
                    continue
                raise RiotError(f"{trouble} for {_path(url)}")
            if not 200 <= status < 300:
                raise RiotError(f"HTTP {status} for {_path(url)}")
            return response.json()

    def ladder_puuids(self, tiers: Sequence[str]) -> list[str]:
        seen: dict[str, None] = {}
        for tier in tiers:
            for puuid in self._tier_puuids(tier):
                seen.setdefault(puuid)
        return list(seen)

    def _tier_puuids(self, tier: str) -> list[str]:
        base = f"{self._platform_host}/lol/league/v4"
        if tier in _LEAGUE_TIERS:
            # Apex: uma liga unica, sem paginacao. O corpo tem que ser um objeto
            # com "entries": sem a checagem, uma mudanca de esquema subiria como
            # KeyError ou TypeError cru -- e esta e a chamada que abre a coleta.
            url = f"{base}/{_LEAGUE_TIERS[tier]}/by-queue/{QUEUE}"
            body = self._get(url)
            if not isinstance(body, dict) or not isinstance(body.get("entries"), list):
                raise RiotError(
                    f"tier {tier}: body is not an object with a list 'entries' "
                    f"(got {type(body).__name__}) for {_path(url)}"
                )
            entries = body["entries"]
        elif tier == "DIAMOND":
            entries = []
            for division in _DIVISIONS:
                page = 1
                while True:
                    url = f"{base}/entries/{QUEUE}/DIAMOND/{division}?page={page}"
                    batch = self._get(url)
                    if not batch:
                        break
                    if not isinstance(batch, list):
                        raise RiotError(
                            f"tier {tier}: page is not a list "
                            f"(got {type(batch).__name__}) for {_path(url)}"
                        )
                    entries.extend(batch)
                    page += 1
        else:
            raise ValueError(f"unsupported tier: {tier}")
        puuids = [self._entry_puuid(entry, tier) for entry in entries]
        if not puuids:
            raise RiotError(f"tier {tier} returned no entries (schema or endpoint changed?)")
        return puuids

    @staticmethod
    def _entry_puuid(entry: dict, tier: str) -> str:
        if not isinstance(entry, dict):
            raise RiotError(
                f"ladder entry in tier {tier} is not an object "
                f"(got {type(entry).__name__})"
            )
        try:
            return entry["puuid"]
        except KeyError:
            raise RiotError(f"ladder entry in tier {tier} is missing field 'puuid'") from None

    def top_masteries(self, puuid: str, count: int) -> list[Mastery]:
        url = (
            f"{self._platform_host}/lol/champion-mastery/v4/champion-masteries"
            f"/by-puuid/{puuid}/top?count={count}"
        )
        return [
            Mastery(item["championId"], item["championPoints"], item["lastPlayTime"])
            for item in self._get(url)
        ]

    def match_ids(self, puuid: str, count: int, queue: int = 420) -> list[str]:
        url = (
            f"{self._regional_host}/lol/match/v5/matches/by-puuid/{puuid}/ids"
            f"?queue={queue}&count={count}"
        )
        return self._get(url)

    def match(self, match_id: str) -> dict:
        return self._get(f"{self._regional_host}/lol/match/v5/matches/{match_id}")

    def timeline(self, match_id: str) -> dict | None:
        return self._get(
            f"{self._regional_host}/lol/match/v5/matches/{match_id}/timeline",
            none_on_404=True,
        )

    def riot_id(self, puuid: str) -> str:
        body = self._get(f"{self._regional_host}/riot/account/v1/accounts/by-puuid/{puuid}")
        return f"{body['gameName']}#{body['tagLine']}"


def httpx_sender(api_key: str) -> Callable[[str], HttpResponse]:
    import httpx

    client = httpx.Client(headers={"X-Riot-Token": api_key}, timeout=30.0)

    def send(url: str) -> HttpResponse:
        return client.get(url)

    return send
