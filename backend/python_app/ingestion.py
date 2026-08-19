from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests


class SourceBlockedError(RuntimeError):
    code = "SOURCE_BLOCKED"


class SourceSchemaError(RuntimeError):
    code = "SCHEMA_CHANGE"


class EmptySourceError(RuntimeError):
    code = "EMPTY_SOURCE_RESPONSE"


@dataclass
class Job:
    source_id: str
    title: str
    company: str
    location: str
    tags: list[str]
    source_url: str
    ingested_at: str


@dataclass
class ParseResult:
    jobs: list[Job]
    fetched: int
    rejected: int
    rejection_reasons: list[str]


@dataclass
class FetchResult:
    jobs: list[Job]
    fetched: int
    parsed: int
    rejected: int
    rejection_reasons: list[str]
    duplicate_count: int
    retry_count: int


def normalize_job(raw: dict[str, Any], now: str) -> Job | None:
    if not isinstance(raw, dict) or not raw.get("id") or not raw.get("position") or not raw.get("company"):
        return None
    tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    clean_tags = list(dict.fromkeys(str(tag).strip() for tag in tags if str(tag).strip()))
    return Job(
        source_id=str(raw["id"]),
        title=str(raw["position"]).strip(),
        company=str(raw["company"]).strip(),
        location=str(raw.get("location") or "Remote").strip(),
        tags=clean_tags,
        source_url=str(raw.get("url") or f"https://remoteok.com/remote-jobs/{raw['id']}"),
        ingested_at=now,
    )


def parse_remoteok_detailed(payload: Any, now: str) -> ParseResult:
    if not isinstance(payload, list):
        raise SourceSchemaError("RemoteOK response was not a list")
    jobs: list[Job] = []
    reasons: list[str] = []
    for index, item in enumerate(payload):
        job = normalize_job(item, now)
        if job is None:
            reasons.append(f"record_{index}: missing id, position, or company")
        else:
            jobs.append(job)
    return ParseResult(jobs=jobs, fetched=len(payload), rejected=len(reasons), rejection_reasons=reasons)


def parse_remoteok(payload: Any, now: str) -> list[Job]:
    return parse_remoteok_detailed(payload, now).jobs


def deduplicate(jobs: list[Job]) -> list[Job]:
    seen: set[str] = set()
    result: list[Job] = []
    for job in jobs:
        if job.source_id not in seen:
            seen.add(job.source_id)
            result.append(job)
    return result


def with_retry(operation: Callable[[], Any], attempts: int = 3, base_delay: float = 0.25, sleep: Callable[[float], None] = time.sleep, on_retry: Callable[[int], None] | None = None) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except SourceBlockedError:
            raise
        except Exception as error:  # noqa: BLE001
            last_error = error
            if attempt < attempts - 1:
                if on_retry:
                    on_retry(attempt + 1)
                sleep(base_delay * (2**attempt))
    raise last_error or RuntimeError("operation failed")


def fetch_remoteok_detailed(pacing_seconds: float = 0.35, sleep: Callable[[float], None] = time.sleep) -> FetchResult:
    sleep(pacing_seconds)
    retry_count = 0
    headers = {
        "User-Agent": random.choice([
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123 Safari/537.36",
        ]),
        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
        "Referer": "https://remoteok.com/",
    }

    def request() -> Any:
        nonlocal retry_count
        response = requests.get("https://remoteok.com/api", headers=headers, timeout=12)
        if response.status_code in {403, 407}:
            raise SourceBlockedError(f"Source refused the request with HTTP {response.status_code}")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                sleep(min(float(retry_after), 10.0))
            response.raise_for_status()
        response.raise_for_status()
        return response.json()

    def mark_retry(_attempt: int) -> None:
        nonlocal retry_count
        retry_count += 1

    payload = with_retry(request, attempts=3, base_delay=0.4, sleep=sleep, on_retry=mark_retry)
    parse = parse_remoteok_detailed(payload, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if not parse.jobs and not parse.rejected:
        raise EmptySourceError("Source returned zero job listings")
    unique = deduplicate(parse.jobs)
    return FetchResult(unique, parse.fetched, len(parse.jobs), parse.rejected, parse.rejection_reasons, len(parse.jobs) - len(unique), retry_count)


def fetch_remoteok(pacing_seconds: float = 0.35) -> list[Job]:
    return fetch_remoteok_detailed(pacing_seconds).jobs


class SandboxSource:
    """Deterministic failure source for tests; it never calls a third party."""

    def __init__(self, mode: str, responses: list[Any] | None = None):
        self.mode = mode
        self.responses = list(responses or [])
        self.calls = 0

    def fetch(self) -> Any:
        self.calls += 1
        if self.mode == "RATE_LIMIT":
            if self.calls < 3:
                response = requests.Response()
                response.status_code = 429
                raise requests.HTTPError("429 rate limited", response=response)
            return [ {"id": "sandbox-1", "position": "Test role", "company": "Sandbox"} ]
        if self.mode == "SERVER_ERROR":
            if self.calls < 2:
                raise requests.HTTPError("500 server error")
            return [{"id": "sandbox-1", "position": "Test role", "company": "Sandbox"}]
        if self.mode == "TIMEOUT":
            raise requests.Timeout("sandbox timeout")
        if self.mode == "EMPTY":
            return []
        if self.mode == "MALFORMED":
            return [{"id": "good", "position": "Good", "company": "Sandbox"}, {"id": "bad"}]
        if self.mode in {"BLOCKED", "CAPTCHA"}:
            raise SourceBlockedError("sandbox source blocked")
        if self.mode == "SCHEMA_CHANGE":
            return {"unexpected": "shape"}
        return self.responses or [{"id": "sandbox-1", "position": "Test role", "company": "Sandbox"}]
