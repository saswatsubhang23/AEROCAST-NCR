"""Shared JSON-over-HTTP access for upstream data providers: timeouts, retries on transient failures, typed errors."""

import asyncio
import logging

import httpx

logger = logging.getLogger("app.upstream")

# Worth retrying; any other 4xx is a request problem that retrying cannot fix.
TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class UpstreamError(Exception):
    """The provider could not give us usable data."""


class UpstreamBadRequest(UpstreamError):
    """The provider rejected the request itself (HTTP 400/422); indicates a bug on our side."""


class UpstreamAuthError(UpstreamError):
    """The provider refused our credentials (HTTP 401/403)."""


class UpstreamRateLimitError(UpstreamError):
    """The provider rate limited the request (HTTP 429)."""

    def __init__(self, message: str, retry_after: float = 60.0):
        super().__init__(message)
        self.retry_after = retry_after


class _Transient(Exception):
    def __init__(self, message: str, retry_after: float | None = None, is_rate_limit: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.is_rate_limit = is_rate_limit


async def get_json(
    *,
    provider: str,
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float,
    attempts: int,
    backoff: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict | list:
    attempts = max(1, attempts)
    last: Exception | None = None
    req_headers = {"User-Agent": "AEROCAST/1.0 (Air Quality Intelligence)", **(headers or {})}
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
                response = await client.get(url, params=params, headers=req_headers)
            if response.status_code == 429:
                detail = _reason(response)
                retry_after_hdr = response.headers.get("retry-after")
                retry_after_val: float | None = None
                if retry_after_hdr:
                    try:
                        retry_after_val = float(retry_after_hdr)
                    except ValueError:
                        pass
                if retry_after_val is None and "minute" in detail.lower():
                    retry_after_val = 60.0
                raise _Transient(
                    f"HTTP 429: {detail}" if detail != "unspecified" else "HTTP 429",
                    retry_after=retry_after_val or 60.0,
                    is_rate_limit=True,
                )
            if response.status_code in TRANSIENT_STATUS:
                detail = _reason(response)
                raise _Transient(f"HTTP {response.status_code}: {detail}" if detail != "unspecified" else f"HTTP {response.status_code}")
            if response.status_code in (400, 422):
                raise UpstreamBadRequest(f"{provider} rejected the request: {_reason(response)}")
            if response.status_code in (401, 403):
                raise UpstreamAuthError(f"{provider} refused the credentials (HTTP {response.status_code})")
            response.raise_for_status()
            return response.json()
        except (UpstreamBadRequest, UpstreamAuthError):
            raise
        except (httpx.TimeoutException, httpx.TransportError, _Transient) as exc:
            last = exc
            logger.warning("%s attempt %d/%d failed: %s", provider, attempt, attempts, str(exc) or type(exc).__name__)
            if attempt < attempts:
                wait = backoff * 2 ** (attempt - 1)
                if isinstance(exc, _Transient) and exc.is_rate_limit and exc.retry_after and exc.retry_after <= 5.0:
                    wait = exc.retry_after
                await asyncio.sleep(wait)
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise UpstreamError(f"Unusable response from {provider} ({type(exc).__name__})") from exc
    if isinstance(last, _Transient) and last.is_rate_limit:
        raise UpstreamRateLimitError(
            f"{provider} failed after {attempts} attempts ({last or 'HTTP 429'})",
            retry_after=last.retry_after or 60.0,
        )
    raise UpstreamError(f"{provider} failed after {attempts} attempts ({last or 'unspecified'})")


def _reason(response: httpx.Response) -> str:
    try:
        body = response.json()
        return str(body.get("reason") or body.get("message") or "unspecified")
    except (ValueError, AttributeError):
        return "unspecified"
