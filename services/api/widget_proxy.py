"""Server-side fetch for dashboard widgets.

The browser never calls the user's external API directly: the key would be
exposed and CORS would block it. Instead the backend proxies the call here,
injecting the sealed auth secret, enforcing the same egress policy as
webhooks (LAN allowed, cloud-metadata blocked), capping size/content-type,
and refusing redirects (a cross-host redirect would dodge the egress check).
Results are cached per widget for its refresh interval so many open tabs do
not hammer the upstream.
"""

from __future__ import annotations

import base64
import json
import time

import httpx

from shared.netpolicy import webhook_target_rejection

_MAX_BYTES = 256 * 1024
_TIMEOUT = 8.0

# widget_id -> (expires_monotonic, result dict)
_cache: dict[str, tuple[float, dict]] = {}


def _apply_auth(headers: dict, params: dict, source: dict, secret: str | None) -> None:
    """Inject the secret into the outbound request per the configured scheme.
    Mutates headers/params in place. No-op when there is no secret."""
    kind = (source.get("auth_kind") or "none").lower()
    if not secret or kind == "none":
        return
    if kind == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif kind == "basic":
        headers["Authorization"] = "Basic " + base64.b64encode(secret.encode("utf-8")).decode("ascii")
    elif kind == "header":
        headers[source.get("auth_name") or "X-API-Key"] = secret
    elif kind == "query":
        params[source.get("auth_name") or "api_key"] = secret


async def fetch_widget_data(source: dict, secret: str | None) -> dict:
    """Fetch the configured URL with auth injected. Returns a JSON-safe dict
    ``{ok, status?, data?, error?}``. Never raises; never echoes the secret."""
    url = (source.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "no URL configured"}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": "only http/https URLs are allowed"}

    rejection = await webhook_target_rejection(url)
    if rejection:
        return {"ok": False, "error": f"blocked: {rejection}"}

    method = (source.get("method") or "GET").upper()
    headers = dict(source.get("headers") or {})
    params = dict(source.get("query") or {})
    _apply_auth(headers, params, source, secret)
    body = source.get("body")
    content = body.encode("utf-8") if isinstance(body, str) and body else None

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=_TIMEOUT) as client:
            resp = await client.request(method, url, headers=headers, params=params, content=content)
    except httpx.TimeoutException:
        return {"ok": False, "error": "upstream timed out"}
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"request failed: {exc}"}

    if resp.is_redirect:
        return {"ok": False, "status": resp.status_code,
                "error": "upstream redirected; redirects are not followed (use the final URL)"}

    raw = resp.content
    if len(raw) > _MAX_BYTES:
        return {"ok": False, "status": resp.status_code, "error": "response too large (>256KB)"}

    ctype = (resp.headers.get("content-type") or "").lower()
    if "json" in ctype:
        try:
            data: object = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            data = raw.decode("utf-8", "replace")
    elif (not ctype) or ctype.startswith(("text/", "application/")):
        data = raw.decode("utf-8", "replace")
    else:
        return {"ok": False, "status": resp.status_code, "error": f"unsupported content-type: {ctype}"}

    return {"ok": resp.status_code < 400, "status": resp.status_code, "data": data}


# NOTE: the cache is keyed by widget_id ALONE. This is safe only because a
# widget is single-owner: dashboard_widgets._owned() rejects any user who is
# not created_by_user_id before get_widget_data ever touches the cache, so a
# widget_id is never served to a second user. If widgets ever become shareable
# across users, this key MUST include the requesting user / auth scope, or one
# user's fetched data will be served to another (see issue #42).
def cache_get(widget_id: str) -> dict | None:
    """Cached result for a widget, or None if absent/expired."""
    entry = _cache.get(widget_id)
    if entry is None:
        return None
    expires, result = entry
    if expires <= time.monotonic():
        _cache.pop(widget_id, None)
        return None
    return result


def cache_put(widget_id: str, result: dict, ttl: float) -> None:
    _cache[widget_id] = (time.monotonic() + max(0.0, ttl), result)


def cache_clear(widget_id: str) -> None:
    _cache.pop(widget_id, None)
