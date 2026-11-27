"""MotoGP Replay Hub Pro - server lokal untuk Termux.

Tugas server:
  1. Mengambil data resmi (musim, event, sesi, klasifikasi, klasemen, sirkuit) dari
     API MotoGP PulseLive, dengan cache memori + disk.
  2. Menyajikan file video milik pengguna dari folder media/.

Struktur media:
  media/<tahun>/<KODE_EVENT>/<kelas>/<SESI>.mp4
  media/<tahun>/<KODE_EVENT>/<kelas>/<SESI>/master.m3u8
  Contoh: media/2026/INA/motogp/RAC.mp4
"""

import hashlib
import json
import logging
import mimetypes
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = Path(os.environ.get("REPLAY_MEDIA_DIR", BASE_DIR / "media")).expanduser()
CACHE_DIR = BASE_DIR / ".cache"
API_BASE = "https://api.motogp.pulselive.com/motogp/v1"

HOST = "127.0.0.1"  # Hanya bisa diakses dari HP ini sendiri.
PORT = int(os.environ.get("PORT", "5000"))

CLASSES = ("motogp", "moto2", "moto3")
VIDEO_EXTENSIONS = (".mp4", ".m4v", ".webm")
PLAYLIST_NAMES = ("master.m3u8", "index.m3u8")
LOGO_FILE = BASE_DIR / "static" / "img" / "logo.png"
# Urutan field foto pembalap yang dicoba. Tukar bila ingin jenis foto lain.
RIDER_PHOTO_ORDER = ("portrait", "profile")
CODE_ALIASES = {"RACE": "RAC", "SPRINT": "SPR", "WARMUP": "WUP"}
UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# Dipakai bila API tidak menyertakan poin pada klasifikasi.
GP_POINTS = (25, 20, 16, 13, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)
SPRINT_POINTS = (12, 9, 7, 6, 5, 4, 3, 2, 1)
CONSTRUCTOR_COLORS = {"ducati": "#B40000", "aprilia": "#5B2BA8", "ktm": "#FF7A1F",
                      "honda": "#E10600", "yamaha": "#0B3A8C"}

mimetypes.add_type("application/vnd.apple.mpegurl", ".m3u8")
mimetypes.add_type("video/mp2t", ".ts")
mimetypes.add_type("video/iso.segment", ".m4s")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("replayhub")

app = Flask(__name__)


class UpstreamError(Exception):
    """API resmi tidak bisa dihubungi dan tidak ada cache yang bisa dipakai."""


def _build_http_session():
    """Membuat sesi HTTP dengan retry otomatis untuk gangguan sementara."""
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"Accept": "application/json", "User-Agent": "ReplayHubPro/1.0"})
    return session


http = _build_http_session()
_memory_cache = {}
_cache_lock = threading.Lock()


def fetch_json(path, params=None, ttl=900):
    """GET ke API resmi dengan cache.

    Jika server sedang down, data lama dari cache tetap dipakai agar aplikasi
    tidak kosong.
    """
    key = hashlib.sha256(json.dumps([path, params], sort_keys=True).encode()).hexdigest()
    cache_file = CACHE_DIR / f"{key}.json"
    now = time.time()

    with _cache_lock:
        entry = _memory_cache.get(key)
    if entry is None:
        try:
            entry = (cache_file.stat().st_mtime, json.loads(cache_file.read_text("utf-8")))
        except (OSError, ValueError):
            entry = None

    if entry and now - entry[0] < ttl:
        return entry[1]

    try:
        response = http.get(f"{API_BASE}{path}", params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        log.warning("Gagal mengambil %s: %s", path, error)
        if entry:
            return entry[1]
        raise UpstreamError(str(error)) from error

    with _cache_lock:
        _memory_cache[key] = (now, data)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data), "utf-8")
    except OSError as error:
        log.warning("Cache disk gagal ditulis: %s", error)
    return data


def as_number(value):
    """API sering mengirim angka sebagai string; ubah dengan aman."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def safe_url(value):
    """Encode URL aset (sebagian nama file mengandung spasi). Hanya https."""
    if not isinstance(value, str) or not value.startswith("https://"):
        return None
    return quote(value, safe=":/?&=%@#+,;~-._")


def normalize_circuit(circuit):
    """Meratakan objek circuit dari Broadcast API menjadi bentuk untuk widget."""
    circuit = circuit or {}
    track = circuit.get("track") or {}
    assets = track.get("assets") or {}
    length = track.get("lenght_units") or {}  # 'lenght' memang ejaan dari API.
    descriptions = {
        item.get("language"): item.get("description")
        for item in circuit.get("circuit_descriptions") or []
    }
    left = as_number(track.get("left_corners"))
    right = as_number(track.get("right_corners"))
    return {
        "name": circuit.get("name"),
        "address": circuit.get("address") or None,
        "country": circuit.get("country") or None,
        "built": circuit.get("constructed") or None,
        "capacity": as_number(circuit.get("capacity")),
        "length_km": as_number(length.get("kiloMeters")),
        "length_mi": as_number(length.get("miles")),
        "width_m": as_number(track.get("width")),
        "straight_m": as_number(track.get("longest_straight")),
        "left": left,
        "right": right,
        "corners": left + right if left is not None and right is not None else None,
        "layout_svg": safe_url((assets.get("info") or {}).get("path")),
        "layout_png": safe_url((assets.get("simple") or {}).get("path")),
        "about": descriptions.get("id") or descriptions.get("en"),
    }


def normalize_event(event):
    """Mengubah event mentah menjadi bentuk ringkas untuk frontend."""
    assets = {}
    for asset in event.get("assets") or []:
        assets.setdefault(asset.get("type"), safe_url(asset.get("path")))
    return {
        "id": event.get("id"),
        "short": str(event.get("shortname") or "").upper(),
        "name": event.get("sponsored_name") or event.get("name"),
        "date_start": event.get("date_start"),
        "date_end": event.get("date_end"),
        "flag": assets.get("FLAG"),
        "image": assets.get("BACKGROUND") or assets.get("TOP"),
        "circuit": normalize_circuit(event.get("circuit")),
    }


def raw_gp_events(year):
    """Daftar event berjenis GP pada satu musim, urut tanggal."""
    data = fetch_json("/events", {"seasonYear": year}, ttl=3600)
    events = [e for e in data if isinstance(e, dict) and e.get("kind") == "GP"]
    return sorted(events, key=lambda e: e.get("date_start") or "")


def find_results_event(year, broadcast):
    """Mencocokkan event Broadcast API dengan event di Results API."""
    seasons = fetch_json("/results/seasons", ttl=86400)
    season = next((s for s in seasons if s.get("year") == year), None)
    if not season:
        return None
    events = fetch_json("/results/events", {"seasonUuid": season["id"]}, ttl=3600)
    ids = {broadcast.get("id"), broadcast.get("toad_api_uuid")} - {None}
    short = str(broadcast.get("shortname") or "").upper()
    end = str(broadcast.get("date_end") or "")[:10]

    matchers = (
        lambda e: e.get("toad_api_uuid") in ids,
        lambda e: not e.get("test") and str(e.get("short_name") or "").upper() == short,
        lambda e: not e.get("test") and end and str(e.get("date_end") or "")[:10] == end,
    )
    for matches in matchers:
        found = next((e for e in events if matches(e)), None)
        if found:
            return found
    return None


def session_code(session):
    """Kode sesi untuk nama file, misalnya FP1, Q2, SPR, RAC."""
    kind = re.sub(r"[^A-Z]", "", str(session.get("type") or "").upper())
    number = session.get("number")
    return f"{kind}{number}" if number else kind


def normalize_name(value):
    """Nama tanpa spasi/simbol untuk pencocokan (misal 'MotoGP™' -> 'motogp')."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def find_category(categories, category):
    """Memilih kelas dari daftar kategori Results API."""
    return next((c for c in categories if normalize_name(c.get("name")) == category), None)


def parse_date(value):
    """Tanggal ISO dari API menjadi datetime ber-zona waktu, atau None."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def event_results(year, event, category, refresh):
    """Klasifikasi Sprint dan Race satu event.

    Mengembalikan (daftar (jenis, baris), jumlah sesi yang gagal dimuat).
    Event lama di-cache lama karena hasilnya sudah final.
    """
    now = datetime.now(timezone.utc)
    end = parse_date(event.get("date_end"))
    recent = end is None or now - end < timedelta(days=7)
    ttl = (0 if refresh else 1800) if recent else 30 * 86400
    results, missing = [], 0
    try:
        categories = fetch_json("/results/categories", {"eventUuid": event["id"]}, ttl=ttl)
        match = find_category(categories, category)
        if not match:
            return results, missing
        sessions = fetch_json("/results/sessions",
                              {"eventUuid": event["id"], "categoryUuid": match["id"]}, ttl=ttl)
    except UpstreamError:
        return results, 1

    for kind in ("SPR", "RAC"):
        # Balapan yang diulang bisa punya >1 sesi; pakai yang terakhir berisi hasil.
        candidates = sorted(
            (s for s in sessions
             if str(s.get("type")).upper() == kind
             and (parse_date(s.get("date")) or now) <= now),
            key=lambda s: s.get("date") or "", reverse=True)
        failed = False
        for session in candidates:
            try:
                data = fetch_json(f"/results/session/{session['id']}/classification",
                                  {"seasonYear": year, "test": "false"}, ttl=ttl)
            except UpstreamError:
                failed = True
                continue
            if data.get("classification"):
                results.append((kind, data["classification"]))
                failed = False
                break
        missing += int(failed)
    return results, missing


def collect_rounds(year, season_id, category, refresh):
    """Semua hasil Sprint/Race musim ini, urut per seri."""
    events = fetch_json("/results/events", {"seasonUuid": season_id},
                        ttl=0 if refresh else 3600)
    now = datetime.now(timezone.utc)
    held = sorted(
        (e for e in events
         if not e.get("test") and (parse_date(e.get("date_start")) or now) <= now),
        key=lambda e: e.get("date_start") or "")
    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(lambda e: event_results(year, e, category, refresh), held))
    rounds = [(str(e.get("short_name") or "").upper(), results)
              for e, (results, _) in zip(held, outcomes) if results]
    return rounds, sum(missing for _, missing in outcomes)


def row_points(row, kind, year):
    """Poin dari API; bila tidak ada, dihitung dari tabel poin modern."""
    points = as_number(row.get("points"))
    if points is not None:
        return points
    table = SPRINT_POINTS if kind == "SPR" else GP_POINTS
    position = row.get("position")
    if year >= 1993 and isinstance(position, int) and 1 <= position <= len(table):
        return table[position - 1]
    return 0


def tally(rounds, year, group):
    """Menjumlahkan poin, menang, podium per rider / team / constructor.

    Konstruktor hanya mendapat poin dari pembalap terbaiknya di tiap sesi;
    tim mendapat poin dari semua pembalapnya.
    """
    table = {}
    for index, (_, results) in enumerate(rounds):
        for kind, rows in results:
            best = {}
            for row in rows:
                rider = row.get("rider") or {}
                team = (row.get("team") or {}).get("name")
                maker = (row.get("constructor") or {}).get("name")
                name = {"riders": rider.get("full_name"), "teams": team,
                        "constructors": maker}[group]
                if not name:
                    continue
                entry = table.setdefault(name, {
                    "name": name, "points": 0, "w": 0, "pod": 0, "sw": 0,
                    "rounds": [0] * len(rounds), "team": team, "constructor": maker,
                    "rider_id": rider.get("legacy_id"), "number": rider.get("number")})
                entry["team"], entry["constructor"] = team, maker
                position = row.get("position")
                entry.setdefault("sessions", set()).add((index, kind))
                if kind == "RAC":
                    entry["w"] += position == 1
                    entry["pod"] += position in (1, 2, 3)
                else:
                    entry["sw"] += position == 1
                points = row_points(row, kind, year)
                best[name] = max(best.get(name, 0), points) if group == "constructors" \
                    else best.get(name, 0) + points
            for name, points in best.items():
                table[name]["points"] += points
                table[name]["rounds"][index] += points
    return merge_renamed_teams(table) if group == "teams" else table


def name_tokens(value):
    return set(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def merge_renamed_teams(table):
    """Menggabungkan tim yang berganti nama sponsor di tengah musim.

    Syarat: konstruktor sama, nama yang satu bagian dari yang lain, dan keduanya
    tidak pernah tampil di sesi yang sama (tim berbeda akan tampil bersamaan).
    """
    merged = []
    for entry in sorted(table.values(), key=lambda e: max(e["sessions"])):
        tokens = name_tokens(entry["name"])
        target = next(
            (m for m in merged
             if m["constructor"] == entry["constructor"]
             and not m["sessions"] & entry["sessions"]
             and (tokens <= name_tokens(m["name"]) or name_tokens(m["name"]) <= tokens)),
            None)
        if not target:
            merged.append(entry)
            continue
        # Nama yang dipakai adalah yang paling baru.
        target["name"] = target["team"] = entry["name"]
        for key in ("points", "w", "pod", "sw"):
            target[key] += entry[key]
        target["rounds"] = [a + b for a, b in zip(target["rounds"], entry["rounds"])]
        target["sessions"] |= entry["sessions"]
    return {entry["name"]: entry for entry in merged}


def rider_photo(rider, year):
    """URL foto pembalap untuk musim tertentu dari objek rider Broadcast API."""
    steps = [s for s in rider.get("career") or [] if s.get("season") == year]
    current = rider.get("current_career_step") or {}
    if current.get("season") in (None, year):
        steps.append(current)
    for step in steps:
        pictures = step.get("pictures") or {}
        for key in RIDER_PHOTO_ORDER:
            value = pictures.get(key)
            url = safe_url(value.get("main") if isinstance(value, dict) else value)
            if url:
                return url
    return None


def team_directory(year, category):
    """Warna, foto motor, dan pembalap tiap tim dari Broadcast API.

    Broadcast API punya ID kategori sendiri, berbeda dari Results API.
    """
    try:
        categories = fetch_json("/categories", {"seasonYear": year}, ttl=86400)
        match = find_category(categories, category)
        if not match:
            return []
        teams = fetch_json("/teams", {"categoryUuid": match["id"], "seasonYear": year},
                           ttl=86400)
        directory = []
        for team in teams:
            color = str(team.get("color"))
            riders = [r for r in team.get("riders") or [] if isinstance(r, dict)]
            directory.append({
                "name": team.get("name"),
                "color": color if HEX_COLOR_RE.match(color) else None,
                "picture": safe_url(team.get("picture")),
                "constructor": (team.get("constructor") or {}).get("name"),
                "riders": riders,
                "rider_ids": {r.get("legacy_id") for r in riders} - {None},
            })
        return directory
    except (UpstreamError, AttributeError, TypeError, KeyError) as error:
        log.warning("Data tim tidak tersedia: %s", error)
        return []


def find_team(directory, name=None, rider_id=None):
    """Mencari tim lewat nama persis, pembalap, lalu kemiripan nama."""
    wanted = normalize_name(name)
    tokens = name_tokens(name)
    for matches in (
            lambda t: bool(wanted) and normalize_name(t["name"]) == wanted,
            lambda t: rider_id is not None and rider_id in t["rider_ids"],
            lambda t: bool(tokens) and bool(name_tokens(t["name"]))
            and (tokens <= name_tokens(t["name"]) or name_tokens(t["name"]) <= tokens)):
        found = next((t for t in directory if matches(t)), None)
        if found:
            return found
    return {}


def constructor_team(directory, constructor):
    """Tim yang mewakili satu pabrikan; tim pabrikan (nama memuat merek) diutamakan."""
    wanted = normalize_name(constructor)
    teams = [t for t in directory
             if normalize_name(t["constructor"]) == wanted and t["picture"]]
    teams = teams or [t for t in directory
                      if wanted in normalize_name(t["name"]) and t["picture"]]
    return next((t for t in teams if wanted in normalize_name(t["name"])),
                teams[0] if teams else {})


def rider_photos(year, directory, riders):
    """Foto pembalap, diindeks per legacy_id.

    Sumber berurutan: daftar tim, daftar rider musim berjalan, lalu detail per rider
    (untuk pengganti dan musim lama).
    """
    photos = {}

    def collect(items):
        for item in items:
            url = rider_photo(item, year)
            if url and item.get("legacy_id"):
                photos.setdefault(item["legacy_id"], url)

    try:
        collect(r for team in directory for r in team["riders"])
        if any(r.get("legacy_id") not in photos for r in riders):
            collect(fetch_json("/riders", ttl=86400))
    except (UpstreamError, AttributeError, TypeError) as error:
        log.warning("Daftar rider tidak tersedia: %s", error)

    def detail(rider):
        try:
            data = fetch_json(f"/riders/{rider['riders_api_uuid']}", ttl=7 * 86400)
            return rider.get("legacy_id"), rider_photo(data, year)
        except (UpstreamError, AttributeError, TypeError) as error:
            log.warning("Foto %s tidak tersedia: %s", rider.get("full_name"), error)
            return rider.get("legacy_id"), None

    missing = [r for r in riders if r.get("legacy_id") not in photos
               and UUID_RE.match(str(r.get("riders_api_uuid")))]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for legacy_id, url in pool.map(detail, missing):
            if url:
                photos[legacy_id] = url
    return photos


def pick_color(team, constructor):
    return (team.get("color")
            or CONSTRUCTOR_COLORS.get(normalize_name(constructor)) or "#52525B")


def build_standings(year, category, group, with_chart, refresh):
    """Menyusun tabel klasemen dan (opsional) data grafik poin kumulatif."""
    seasons = fetch_json("/results/seasons", ttl=86400)
    season = next((s for s in seasons if s.get("year") == year), None)
    if not season:
        abort(404, description="Musim tidak ditemukan")
    categories = fetch_json("/results/categories", {"seasonUuid": season["id"]}, ttl=86400)
    match = find_category(categories, category)
    if not match:
        abort(404, description="Kelas tidak ada pada musim ini")

    official = []
    if group == "riders":
        data = fetch_json("/results/standings",
                          {"seasonUuid": season["id"], "categoryUuid": match["id"]},
                          ttl=0 if refresh else 900)
        official = data.get("classification") or []
    has_counts = bool(official) and all(
        key in official[0] for key in ("race_wins", "podiums", "sprint_wins"))

    rounds, missing = [], 0
    if with_chart or group != "riders" or not has_counts:
        rounds, missing = collect_rounds(year, season["id"], category, refresh)
    computed = tally(rounds, year, group)
    directory = team_directory(year, category)

    entries = []
    if group == "riders":
        photos = rider_photos(year, directory, [i.get("rider") or {} for i in official])
        for item in official:
            rider = item.get("rider") or {}
            name = rider.get("full_name")
            mine = computed.get(name, {})
            team = (item.get("team") or {}).get("name")
            maker = (item.get("constructor") or {}).get("name")
            entries.append({
                "position": item.get("position"), "name": name,
                "number": rider.get("number") or mine.get("number"),
                "sub": " · ".join(filter(None, (team, maker))),
                "color": pick_color(find_team(directory, team, rider.get("legacy_id")), maker),
                "image": photos.get(rider.get("legacy_id")),
                "points": as_number(item.get("points")) or 0,
                "w": item["race_wins"] if has_counts else mine.get("w"),
                "pod": item["podiums"] if has_counts else mine.get("pod"),
                "sw": item["sprint_wins"] if has_counts else mine.get("sw"),
            })
    else:
        ranked = sorted(computed.values(),
                        key=lambda e: (-e["points"], -e["w"], -e["pod"], e["name"]))
        for position, item in enumerate(ranked, 1):
            if group == "teams":
                team = find_team(directory, item["name"], item["rider_id"])
            else:
                team = constructor_team(directory, item["constructor"])
            entries.append({
                "position": position, "name": item["name"], "number": None,
                "sub": item["constructor"] if group == "teams" else "",
                "color": pick_color(team, item["constructor"]),
                "image": team.get("picture"),
                "points": item["points"], "w": item["w"], "pod": item["pod"],
                "sw": item["sw"],
            })

    leader = entries[0]["points"] if entries else 0
    for entry in entries:
        entry["diff"] = entry["points"] - leader

    series = []
    if with_chart:
        for entry in entries[:5]:
            per_round = computed.get(entry["name"], {}).get("rounds", [0] * len(rounds))
            total, values = 0, []
            for points in per_round:
                total += points
                values.append(total)
            series.append({"name": entry["name"], "number": entry["number"],
                           "values": values})

    notes = []
    if missing:
        notes.append(f"{missing} sesi gagal dimuat, angka hitungan belum lengkap. "
                     "Tekan muat ulang.")
    if group != "riders":
        notes.append("Dihitung dari klasifikasi resmi; penalti klasemen tidak termasuk.")
    elif with_chart:
        notes.append("Grafik dihitung per seri; bisa sedikit beda dari tabel resmi.")
    return {"rows": entries, "rounds": [code for code, _ in rounds],
            "series": series, "note": " ".join(notes)}


def media_url(path):
    """URL lokal untuk file di dalam MEDIA_DIR."""
    return "/media/" + quote(path.relative_to(MEDIA_DIR).as_posix())


def scan_library():
    """Memindai folder media dan mengembalikan semua video yang dikenali."""
    items = []
    if not MEDIA_DIR.is_dir():
        return items
    try:
        for entry in sorted(MEDIA_DIR.glob("*/*/*/*")):
            year, event, category, name = entry.relative_to(MEDIA_DIR).parts
            if not year.isdigit() or category.lower() not in CLASSES:
                continue
            video = None
            code = None
            if entry.is_dir():
                video = next((entry / p for p in PLAYLIST_NAMES if (entry / p).is_file()), None)
                code = name
            elif entry.suffix.lower() in VIDEO_EXTENSIONS:
                video, code = entry, entry.stem
            if video:
                code = code.upper()
                items.append({
                    "year": int(year),
                    "event": event.upper(),
                    "class": category.lower(),
                    "code": CODE_ALIASES.get(code, code),
                    "url": media_url(video),
                })
    except OSError as error:
        log.error("Folder media tidak bisa dibaca: %s", error)
    return items


def read_year():
    """Validasi parameter ?year=."""
    year = request.args.get("year", type=int)
    if year is None or not 1949 <= year <= 2100:
        abort(400, description="Parameter year tidak valid")
    return year


@app.errorhandler(UpstreamError)
def handle_upstream(_error):
    return jsonify(error="Server data MotoGP tidak bisa dihubungi. Coba lagi."), 502


@app.errorhandler(400)
@app.errorhandler(404)
def handle_client_error(error):
    return jsonify(error=error.description), error.code


@app.errorhandler(Exception)
def handle_unexpected(error):
    code = getattr(error, "code", None)
    if isinstance(code, int):
        return jsonify(error=str(error)), code
    log.exception("Kesalahan tak terduga")
    return jsonify(error="Terjadi kesalahan di server lokal."), 500


@app.route("/")
def home():
    return render_template("index.html", has_logo=LOGO_FILE.is_file())


@app.route("/api/seasons")
def api_seasons():
    seasons = fetch_json("/results/seasons", ttl=86400)
    result = [{"year": s["year"], "current": bool(s.get("current"))}
              for s in seasons if s.get("year")]
    return jsonify(sorted(result, key=lambda s: s["year"], reverse=True))


@app.route("/api/events")
def api_events():
    return jsonify([normalize_event(e) for e in raw_gp_events(read_year())])


@app.route("/api/sessions")
def api_sessions():
    """Sesi satu event + kelas, digabung dengan video lokal yang tersedia."""
    year = read_year()
    event_id = request.args.get("event", "")
    category = request.args.get("class", "motogp")
    if not UUID_RE.match(event_id) or category not in CLASSES:
        abort(400, description="Parameter event atau class tidak valid")

    broadcast = next((e for e in raw_gp_events(year) if e.get("id") == event_id), None)
    if not broadcast:
        abort(404, description="Event tidak ditemukan")
    short = str(broadcast.get("shortname") or "").upper()
    local = {i["code"]: i["url"] for i in scan_library()
             if (i["year"], i["event"], i["class"]) == (year, short, category)}

    sessions, warning = [], None
    try:
        event = find_results_event(year, broadcast)
        if event:
            categories = fetch_json("/results/categories", {"eventUuid": event["id"]}, ttl=3600)
            match = find_category(categories, category)
            if match:
                raw = fetch_json("/results/sessions",
                                 {"eventUuid": event["id"], "categoryUuid": match["id"]}, ttl=600)
                for item in sorted(raw, key=lambda s: s.get("date") or ""):
                    code = session_code(item)
                    sessions.append({"id": item.get("id"), "code": code,
                                     "date": item.get("date"), "video": local.get(code)})
    except UpstreamError:
        warning = "Daftar sesi resmi gagal dimuat. Hanya video lokal yang ditampilkan."

    known = {s["code"] for s in sessions}
    sessions += [{"id": None, "code": code, "date": None, "video": url}
                 for code, url in local.items() if code not in known]
    return jsonify(sessions=sessions, warning=warning,
                   folder=f"media/{year}/{short}/{category}")


@app.route("/api/classification")
def api_classification():
    session_id = request.args.get("session", "")
    if not UUID_RE.match(session_id):
        abort(400, description="Parameter session tidak valid")
    data = fetch_json(f"/results/session/{session_id}/classification",
                      {"seasonYear": read_year(), "test": "false"}, ttl=600)
    rows = []
    for row in data.get("classification") or []:
        rider = row.get("rider") or {}
        rows.append({
            "position": row.get("position"),
            "rider": rider.get("full_name"),
            "number": rider.get("number"),
            "team": (row.get("team") or {}).get("name"),
            "time": row.get("time") or (row.get("best_lap") or {}).get("time"),
            "gap": (row.get("gap") or {}).get("first"),
        })
    return jsonify(rows)


@app.route("/api/standings")
def api_standings():
    category = request.args.get("class", "motogp")
    group = request.args.get("type", "riders")
    if category not in CLASSES or group not in ("riders", "teams", "constructors"):
        abort(400, description="Parameter class atau type tidak valid")
    return jsonify(build_standings(read_year(), category, group,
                                   request.args.get("chart") == "1",
                                   request.args.get("refresh") == "1"))


@app.route("/api/library")
def api_library():
    return jsonify(scan_library())


@app.route("/media/<path:filename>")
def media(filename):
    """Menyajikan video lokal. conditional=True mendukung Range (seek)."""
    if not filename.lower().endswith(VIDEO_EXTENSIONS + (".m3u8", ".ts", ".m4s", ".aac", ".vtt")):
        abort(404, description="Jenis file tidak didukung")
    return send_from_directory(MEDIA_DIR, filename, conditional=True)


if __name__ == "__main__":
    try:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        log.error("Tidak bisa membuat folder media %s: %s", MEDIA_DIR, error)
    log.info("Server jalan di http://%s:%s  |  media: %s", HOST, PORT, MEDIA_DIR)
    app.run(host=HOST, port=PORT, threaded=True)
