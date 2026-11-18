"""robots.txt checks done on the caller's side (RFC 9309).

The loader and the retriever read each site's ``/robots.txt`` directly from the site before
they ask QuanticData for a page, and skip the URLs the rules disallow for ``user_agent``
(``*`` by default). Following RFC 9309: a 4xx robots.txt means no restrictions; a 5xx,
a network error or a redirect loop means the whole site is treated as disallowed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

ROBOTS_TIMEOUT = 15.0


@dataclass(frozen=True)
class Rule:
    allow: bool
    path: str

    def matches(self, target: str) -> bool:
        return _pattern(self.path).match(target) is not None


def _pattern(path: str) -> re.Pattern[str]:
    anchored = path.endswith("$")
    body = path[:-1] if anchored else path
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(regex + ("$" if anchored else ""))


@dataclass
class RobotsRules:
    """The rules of the group that applies to one user agent."""

    rules: list[Rule] = field(default_factory=list)
    disallow_all: bool = False

    def allowed(self, url: str) -> bool:
        if self.disallow_all:
            return False
        parts = urlsplit(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if target == "/robots.txt":
            return True
        best: Rule | None = None
        for rule in self.rules:
            if not rule.path or not rule.matches(target):
                continue
            # Longest match wins; on a tie, allow wins (RFC 9309 section 2.2.2).
            if (
                best is None
                or len(rule.path) > len(best.path)
                or (len(rule.path) == len(best.path) and rule.allow)
            ):
                best = rule
        return best is None or best.allow

    def disallowed_paths(self) -> list[str]:
        """Disallow paths of the group, for use as crawl ``exclude`` patterns."""
        return [r.path for r in self.rules if not r.allow and r.path]


def parse_robots(text: str, user_agent: str = "*") -> RobotsRules:
    """Returns the rules for ``user_agent``: its own group when one names it, else the ``*`` group."""
    groups: list[tuple[list[str], list[Rule]]] = []
    agents: list[str] = []
    rules: list[Rule] = []
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if in_rules:
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(value.lower())
        elif key in ("allow", "disallow"):
            if not agents:
                continue
            in_rules = True
            rules.append(Rule(allow=key == "allow", path=value))
    if agents:
        groups.append((agents, rules))

    wanted = user_agent.lower()
    specific = [r for a, r in groups if any(x != "*" and x in wanted for x in a)]
    chosen = specific or [r for a, r in groups if "*" in a]
    merged = [rule for group in chosen for rule in group]
    return RobotsRules(rules=merged)


def robots_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def _from_response(response: httpx.Response, user_agent: str) -> RobotsRules:
    if response.status_code >= 500:
        return RobotsRules(disallow_all=True)
    if response.status_code >= 400:
        return RobotsRules()
    return parse_robots(response.text, user_agent)


class RobotsChecker:
    """Caches one :class:`RobotsRules` per origin."""

    def __init__(
        self,
        user_agent: str = "*",
        *,
        transport: httpx.BaseTransport | None = None,
        async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.user_agent = user_agent
        self._transport = transport
        self._async_transport = async_transport
        self._cache: dict[str, RobotsRules] = {}

    def rules_for(self, url: str) -> RobotsRules:
        key = robots_url(url)
        if key not in self._cache:
            try:
                with httpx.Client(
                    timeout=ROBOTS_TIMEOUT, follow_redirects=True, transport=self._transport
                ) as http:
                    self._cache[key] = _from_response(http.get(key), self.user_agent)
            except httpx.HTTPError:
                self._cache[key] = RobotsRules(disallow_all=True)
        return self._cache[key]

    async def arules_for(self, url: str) -> RobotsRules:
        key = robots_url(url)
        if key not in self._cache:
            try:
                async with httpx.AsyncClient(
                    timeout=ROBOTS_TIMEOUT, follow_redirects=True, transport=self._async_transport
                ) as http:
                    self._cache[key] = _from_response(await http.get(key), self.user_agent)
            except httpx.HTTPError:
                self._cache[key] = RobotsRules(disallow_all=True)
        return self._cache[key]

    def allowed(self, url: str) -> bool:
        return self.rules_for(url).allowed(url)

    async def aallowed(self, url: str) -> bool:
        return (await self.arules_for(url)).allowed(url)
