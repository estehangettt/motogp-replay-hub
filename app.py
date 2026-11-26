"""MotoGP Replay Hub Pro local backend.

PulseLive data is read-only. The media proxy only forwards explicitly permitted
HTTP(S) media hosts and does not bypass upstream authentication or HTTP 403.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
import time
from functools import wraps
from threading import Lock
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
PULSELIVE_BASE = os.getenv(
    "PULSELIVE_BASE_URL", "https://api.motogp.pulselive.com/motogp/v1"
).rstrip("/")
PULSELIVE_TIMEOUT = max(3, int(os.getenv("PULSELIVE_TIMEOUT", "15")))
SCRAPER_TIMEOUT = max(3, int(os.getenv("SCRAPER_TIMEOUT", "15")))
MOTOMUNDO_BASE = os.getenv("MOTOMUNDO_BASE_URL", "https://motomundo.net/")
MAX_CACHE_SECONDS = 300
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("motogp-hub")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["JSON_SORT_KEYS"] = False

SESSION = requests.Session()
retry = Retry(
    total=2,
    connect=2,
    read=1,
    backoff_factor=0.35,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD"]),
)
adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}
PULSELIVE_HEADERS = {
    **DEFAULT_HEADERS,
    "Origin": "https://www.motogp.com",
    "Referer": "https://www.motogp.com/",
}

_cache: dict[str, tuple[float, object]] = {}
_cache_lock = Lock()


def cached(seconds: int = 60):
    """Cache successful JSON-producing GET route results for a short period."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{request.path}?{request.query_string.decode('utf-8', 'ignore')}"
            now = time.time()
            with _cache_lock:
                item = _cache.get(key)
                if item and item[0] > now:
                    return jsonify(item[1])
            result = func(*args, **kwargs)
            if isinstance(result, tuple):
                return result
            payload = result.get_json(silent=True) if hasattr(result, "get_json") else None
            if payload is not None and getattr(result, "status_code", 200) == 200:
                with _cache_lock:
                    _cache[key] = (now + seconds, payload)
            return result
        return wrapper
    return decorator


def pulselive_get(path: str, params: dict | None = None):
    """Request a PulseLive resource with timeout and structured errors."""
    url = f"{PULSELIVE_BASE}/{path.lstrip('/')}"
    try:
        response = SESSION.get(
            url, params=params, headers=PULSELIVE_HEADERS, timeout=PULSELIVE_TIMEOUT
        )
        response.raise_for_status()
        return response.json(), None
    except requests.Timeout:
        logger.warning("PulseLive timeout: %s", url)
        return None, "PulseLive request timed out"
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        logger.warning("PulseLive HTTP error %s: %s", status, url)
        return None, f"PulseLive returned HTTP {status}"
    except (requests.RequestException, ValueError) as exc:
        logger.exception("PulseLive request failed: %s", exc)
        return None, "Unable to read PulseLive response"


def valid_http_url(value: str) -> bool:
    """Accept only absolute HTTP(S) URLs without credentials."""
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def host_is_public(host: str) -> bool:
    """Reject localhost, private, reserved and link-local destinations."""
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                return False
        return bool(addresses)
    except (OSError, ValueError):
        return False


def host_is_allowed(url: str) -> bool:
    """Require a public host and, when configured, an explicit host allowlist."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or not host_is_public(host):
        return False
    configured = [
        value.strip().lower().rstrip(".")
        for value in os.getenv("HLS_ALLOWED_HOSTS", "").split(",")
        if value.strip()
    ]
    if configured and not any(host == item or host.endswith("." + item) for item in configured):
        return False
    return True


def scrape_motomundo(category_url: str) -> list[dict]:
    """Extract session labels and iframe URLs from a public category page.

    This intentionally does not unpack obfuscated JavaScript or defeat embed
    access controls. Only ordinary iframe references are collected.
    """
    if not valid_http_url(category_url):
        raise ValueError("URL kategori tidak valid.")
    parsed = urlparse(category_url)
    if parsed.hostname not in ("motomundo.net", "www.motomundo.net"):
        raise ValueError("Scraper hanya menerima halaman kategori motomundo.net.")
    response = SESSION.get(
        category_url, headers={**DEFAULT_HEADERS, "Referer": MOTOMUNDO_BASE},
        timeout=SCRAPER_TIMEOUT,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for details in soup.find_all("details"):
        summary = details.find("summary")
        if not summary:
            continue
        title = summary.get_text(" ", strip=True)
        iframe = next(
            (frame for frame in details.find_all("iframe")
             if frame.get("data-src") or frame.get("src")),
            None,
        )
        if not iframe:
            continue
        embed = iframe.get("data-src") or iframe.get("src")
        embed_url = urljoin(category_url, embed.strip())
        if not valid_http_url(embed_url):
            continue
        parts = title.split(" - ", 1)
        category = parts[0].strip().upper() if len(parts) == 2 else "LAINNYA"
        session_name = parts[1].split("|", 1)[0].strip().upper() if len(parts) == 2 else title.upper()
        results.append({
            "kelas": category,
            "sesi": session_name,
            "judul_lengkap": title,
            "url": embed_url,
        })
    return results


def find_direct_hls(embed_url: str) -> str | None:
    """Find a plainly exposed HLS URL; no JavaScript unpacking is performed."""
    if not valid_http_url(embed_url):
        raise ValueError("URL embed tidak valid.")
    if not host_is_allowed(embed_url):
        raise ValueError("Host embed tidak diizinkan atau bukan host publik.")
    response = SESSION.get(
        embed_url, headers={**DEFAULT_HEADERS, "Referer": MOTOMUNDO_BASE},
        timeout=SCRAPER_TIMEOUT,
    )
    response.raise_for_status()
    html = response.text[:2_000_000]
    matches = re.findall(
        r"""https?://[^\s"'<>\\\\]+?\.m3u8(?:\?[^\s"'<>\\\\]*)?""",
        html,
        flags=re.IGNORECASE,
    )
    for candidate in matches:
        candidate = candidate.rstrip("),;]")
        if valid_http_url(candidate) and host_is_allowed(candidate):
            return candidate
    return None


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "MotoGP Replay Hub Pro"})


@app.get("/api/motogp/seasons")
@cached(300)
def api_seasons():
    data, error = pulselive_get("results/seasons")
    if error:
        return jsonify({"error": error}), 502
    return jsonify(data if isinstance(data, list) else data.get("data", []))


@app.get("/api/motogp/events")
@cached(120)
def api_events():
    year = request.args.get("seasonYear", type=int)
    if not year or year < 1949 or year > 2100:
        return jsonify({"error": "seasonYear tidak valid"}), 400
    data, error = pulselive_get("events", {"seasonYear": year})
    if error:
        return jsonify({"error": error}), 502
    events = data if isinstance(data, list) else data.get("data", [])
    events = [
        event for event in events
        if isinstance(event, dict)
        and event.get("kind", "GP") == "GP"
        and isinstance(event.get("circuit"), dict)
        and event["circuit"].get("name")
    ]
    events.sort(key=lambda item: item.get("date_start") or "")
    return jsonify(events)


@app.get("/api/motogp/event/<event_id>")
@cached(180)
def api_event_detail(event_id):
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", event_id):
        return jsonify({"error": "event id tidak valid"}), 400
    data, error = pulselive_get(f"events/{event_id}")
    if error:
        return jsonify({"error": error}), 502
    return jsonify(data)


@app.get("/api/katalog")
def api_katalog():
    category_url = request.args.get("url", "").strip()
    if not category_url:
        return jsonify({"error": "Parameter url wajib diisi"}), 400
    try:
        return jsonify(scrape_motomundo(category_url))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        return jsonify({"error": f"Halaman sumber mengembalikan HTTP {status}"}), 502
    except requests.RequestException:
        logger.exception("Scraper network error")
        return jsonify({"error": "Tidak dapat menghubungi halaman sumber"}), 502
    except Exception:
        logger.exception("Unexpected scraper error")
        return jsonify({"error": "Gagal memproses katalog"}), 500


@app.get("/get_stream")
def get_stream():
    embed_url = request.args.get("url", "").strip()
    if not embed_url:
        return jsonify({"error": "URL embed wajib diisi"}), 400
    try:
        stream_url = find_direct_hls(embed_url)
        if not stream_url:
            return jsonify({
                "error": "URL HLS tidak ditemukan sebagai tautan langsung. Embed mungkin memakai proteksi atau resolver khusus."
            }), 404
        return jsonify({"m3u8": stream_url})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        return jsonify({"error": f"Server sumber menolak permintaan (HTTP {status})."}), 502
    except requests.RequestException:
        logger.exception("Stream resolver network error")
        return jsonify({"error": "Gagal menghubungi server embed"}), 502


@app.get("/proxy")
def proxy():
    """Proxy authorized HLS playlists/segments without bypassing access controls."""
    media_url = request.args.get("url", "").strip()
    if not valid_http_url(media_url) or not host_is_allowed(media_url):
        return jsonify({"error": "URL media tidak valid atau host tidak diizinkan"}), 400

    headers = {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Accept": "*/*",
    }
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]
    if request.headers.get("Origin"):
        headers["Origin"] = request.headers["Origin"]

    upstream = None
    try:
        upstream = SESSION.get(
            media_url, headers=headers, stream=True, timeout=(8, 30), allow_redirects=True
        )
        if upstream.status_code not in (200, 206):
            status = upstream.status_code
            upstream.close()
            return jsonify({"error": f"Upstream returned HTTP {status}; access was not bypassed."}), status
        if not host_is_allowed(upstream.url):
            upstream.close()
            return jsonify({"error": "Redirect ke host yang tidak diizinkan"}), 400

        content_type = upstream.headers.get("Content-Type", "application/octet-stream")
        is_playlist = (
            ".m3u8" in urlparse(upstream.url).path.lower()
            or "mpegurl" in content_type.lower()
        )
        if is_playlist:
            raw = upstream.content
            if len(raw) > MAX_RESPONSE_BYTES:
                upstream.close()
                return jsonify({"error": "Playlist terlalu besar"}), 413
            text = raw.decode("utf-8", errors="replace")
            rewritten = []
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped:
                    rewritten.append(line)
                elif stripped.startswith("#"):
                    def replace_uri(match):
                        absolute = urljoin(upstream.url, match.group(1))
                        if not host_is_allowed(absolute):
                            return match.group(0)
                        return f'URI="/proxy?url={quote(absolute, safe="")}"'
                    line = re.sub(r'URI="([^"]+)"', replace_uri, line)
                    rewritten.append(line)
                else:
                    absolute = urljoin(upstream.url, stripped)
                    if host_is_allowed(absolute):
                        rewritten.append(f"/proxy?url={quote(absolute, safe='')}")
                    else:
                        rewritten.append(stripped)
            upstream.close()
            return Response(
                "\n".join(rewritten) + "\n",
                content_type="application/vnd.apple.mpegurl",
                headers={"Cache-Control": "no-store"},
            )

        response_headers = {}
        for key in ("Content-Length", "Content-Range", "Accept-Ranges"):
            if key in upstream.headers:
                response_headers[key] = upstream.headers[key]

        def generate():
            try:
                total = 0
                for chunk in upstream.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        total += len(chunk)
                        if total > MAX_RESPONSE_BYTES:
                            logger.warning("Proxy response exceeded configured byte limit")
                            break
                        yield chunk
            finally:
                upstream.close()

        return Response(
            stream_with_context(generate()),
            status=upstream.status_code,
            content_type=content_type,
            headers=response_headers,
        )
    except requests.Timeout:
        if upstream is not None:
            upstream.close()
        return jsonify({"error": "Media server timeout"}), 504
    except requests.RequestException:
        if upstream is not None:
            upstream.close()
        logger.exception("Media proxy request failed")
        return jsonify({"error": "Media server request failed"}), 502


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/") or request.path in ("/proxy", "/get_stream"):
        return jsonify({"error": "Endpoint tidak ditemukan"}), 404
    return "Not Found", 404


@app.errorhandler(500)
def internal_error(_error):
    logger.exception("Unhandled server error")
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    logger.info("MotoGP Replay Hub Pro running at http://%s:%s", host, port)
    app.run(host=host, port=port, debug=debug, threaded=True)
