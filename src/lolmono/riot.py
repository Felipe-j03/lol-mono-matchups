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
_LEAGUE_TIERS = {
    "CHALLENGER": "challengerleagues",
    "GRANDMASTER": "grandmasterleagues",
}


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
    return urlsplit(url).path


def _retry_after(response: HttpResponse) -> float:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, TypeError, ValueError):
        return DEFAULT_RETRY_AFTER


class RiotClient:
    def __init__(
        self,
        api_key: str,
        platform: str,
        limiter,
        send: Callable[[str], HttpResponse],
    ) -> None:
        # A chave pertence ao transporte (send); o cliente nunca a guarda.
        del api_key
        self._platform_host = f"https://{platform}.api.riotgames.com"
        self._regional_host = f"https://{PLATFORM_TO_REGIONAL[platform]}.api.riotgames.com"
        self._limiter = limiter
        self._send = send

    def _get(self, url: str, *, none_on_404: bool = False) -> object:
        for attempt in range(MAX_ATTEMPTS):
            self._limiter.acquire()
            try:
                response = self._send(url)
            except Exception as exc:
                raise RiotError(f"transport failure ({type(exc).__name__}) for {_path(url)}") from None
            status = response.status_code
            if status == 429:
                self._limiter.penalize(_retry_after(response))
                continue
            if status == 404 and none_on_404:
                return None
            if not 200 <= status < 300:
                raise RiotError(f"HTTP {status} for {_path(url)}")
            return response.json()
        raise RiotError(f"HTTP 429 after {MAX_ATTEMPTS} attempts for {_path(url)}")

    def ladder_puuids(self, tiers: Sequence[str]) -> list[str]:
        seen: dict[str, None] = {}
        for tier in tiers:
            for puuid in self._tier_puuids(tier):
                seen.setdefault(puuid)
        return list(seen)

    def _tier_puuids(self, tier: str) -> list[str]:
        base = f"{self._platform_host}/lol/league/v4"
        if tier in _LEAGUE_TIERS:
            body = self._get(f"{base}/{_LEAGUE_TIERS[tier]}/by-queue/{QUEUE}")
            return [entry["puuid"] for entry in body["entries"]]
        if tier == "MASTER":
            puuids: list[str] = []
            page = 1
            while True:
                entries = self._get(f"{base}/entries/{QUEUE}/MASTER/I?page={page}")
                if not entries:
                    return puuids
                puuids.extend(entry["puuid"] for entry in entries)
                page += 1
        raise ValueError(f"unsupported tier: {tier}")

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
