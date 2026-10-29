import httpx
import pytest

from app.infra.http_client import AccessDenied, FetchError, NotFound, PoliteHttpClient

UA = "investment-agent-test/1.0"


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def sleep(self, s):
        self.slept.append(s)
        self.now += s

    def clock(self):
        return self.now


def client(handler, tmp_path=None, **kw):
    t = FakeTime()
    c = PoliteHttpClient(UA, cache_dir=tmp_path, min_interval_seconds=2.0, client=httpx.Client(transport=httpx.MockTransport(handler)),
                         sleep=t.sleep, clock=t.clock, **kw)  # fmt: skip
    return c, t


def robots_ok(request, body="User-agent: *\nDisallow: /private/"):
    return httpx.Response(200, text=body) if request.url.path == "/robots.txt" else None


def test_sends_honest_user_agent_and_respects_robots():
    seen = []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return robots_ok(request) or httpx.Response(200, content=b"ok")

    c, _ = client(handler)
    assert c.get("https://example.com/data").content == b"ok"
    assert set(seen) == {UA}
    with pytest.raises(AccessDenied, match="robots"):
        c.get("https://example.com/private/x")


def test_rate_limits_per_host():
    c, t = client(lambda r: robots_ok(r) or httpx.Response(200))
    c.get("https://example.com/a")
    c.get("https://example.com/b")
    assert any(s > 0 for s in t.slept)  # second request to the same host waited


def test_403_is_not_retried():
    calls = []

    def handler(request):
        if r := robots_ok(request):
            return r
        calls.append(1)
        return httpx.Response(403)

    c, _ = client(handler)
    with pytest.raises(AccessDenied):
        c.get("https://example.com/x")
    assert len(calls) == 1


def test_transient_errors_retry_then_fail():
    calls = []

    def handler(request):
        if r := robots_ok(request):
            return r
        calls.append(1)
        return httpx.Response(503)

    c, _ = client(handler, max_retries=2)
    with pytest.raises(FetchError):
        c.get("https://example.com/x")
    assert len(calls) == 3


def test_404_and_cache(tmp_path):
    calls = []

    def handler(request):
        if r := robots_ok(request):
            return r
        calls.append(request.url.path)
        return httpx.Response(404) if request.url.path == "/missing" else httpx.Response(200, content=b"v1")

    c, _ = client(handler, tmp_path)
    with pytest.raises(NotFound):
        c.get("https://example.com/missing")
    first = c.get("https://example.com/page", ttl_seconds=3600)
    second = c.get("https://example.com/page", ttl_seconds=3600)
    assert not first.from_cache and second.from_cache and second.content == b"v1"
    assert calls.count("/page") == 1


def test_html_robots_page_means_no_rules():
    c, _ = client(lambda r: httpx.Response(200, text="<html>home</html>") if r.url.path == "/robots.txt"
                  else httpx.Response(200, content=b"x"))  # fmt: skip
    assert c.get("https://example.com/anything").content == b"x"
