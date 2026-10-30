"""Log archiver service: config (rules, per-app knobs, destinations, S3 connections), HTTP API + UI, and the loop that
runs archiver.run_pass. Behind APISIX at /log-archiver/ (admin SSO); the gateway proves itself with X-Gateway-Key.
Config and state live in DATA_DIR (/data, volume log-archiver-data); S3 secret keys are Fernet-encrypted there."""
import base64, collections, copy, datetime, hashlib, hmac, json, os, re, shutil, threading, time, traceback, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

import archiver as a

DATA = os.environ.get("DATA_DIR", "/data")
ARCHIVE = os.environ.get("ARCHIVE_DIR", "/archive")
TOKEN = os.environ.get("LOG_ARCHIVER_TOKEN", "")
KEY = os.environ.get("LOG_ARCHIVER_SECRETS_KEY", "")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
FOLDER = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")
ACTIONS = collections.deque(maxlen=300)
LOCK, WAKE = threading.Lock(), threading.Event()
STATUS = {"running": False, "last": None, "next_at": None, "usage": {}, "disk_percent": None, "archive": None, "logs_bytes": None}


def default_config():
    """First start: the .env seeds (LOGS_RETENTION_DAYS, ...) and one local destination; edited in the UI after."""
    return {"interval_seconds": int(os.environ.get("LOG_ARCHIVE_INTERVAL", "300")),
            "logs": {"retention_days": int(os.environ.get("LOGS_RETENTION_DAYS", "365")),
                     "disk_max_percent": int(os.environ.get("LOGS_DISK_MAX_PERCENT", "80")),
                     "max_gb": float(os.environ.get("LOGS_MAX_GB", "0")),
                     "targets": ["local"], "filters": []},
            "traces": {"retention_days": int(os.environ.get("JAEGER_RETENTION_DAYS", "7"))},
            # archive files on the local disk (all disk-folder destinations together; each also has its own limits)
            "archive": {"max_gb": 0, "disk_max_percent": 0},
            "apps": {},
            "targets": {"local": {"type": "local", "folder": "local", "format": "gzip", "retention_days": 0, "max_gb": 0}},
            "connections": {}}


# ---------- config: validation, storage, secrets ----------

def fernet():
    if not KEY:
        raise ValueError("S3 secret keys need LOG_ARCHIVER_SECRETS_KEY in .env (./install.sh adds it)")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(KEY.encode()).digest()))


def _int(v, lo, hi, what):
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise ValueError(f"{what}: a whole number from {lo} to {hi}")
    return v


def _gb(v, what, allow_zero=True):
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or (v == 0 and not allow_zero):
        raise ValueError(f"{what}: a size in GB, {'0 or more (0 = no limit)' if allow_zero else 'more than 0'}")
    return v


def _filters(rules, what):
    if not isinstance(rules, list):
        raise ValueError(f"{what}: a list of rules")
    for i, r in enumerate(rules):
        conds = r.get("conditions") if isinstance(r, dict) else None
        if not conds or not isinstance(conds, list):
            raise ValueError(f"{what} rule {i + 1}: needs at least one condition")
        for c in conds:
            if c.get("field") not in a.FIELDS or c.get("op") not in a.OPS or not str(c.get("value", "")).strip():
                raise ValueError(f"{what} rule {i + 1}: field one of {a.FIELDS}, op one of {a.OPS}, and a value")
    return [{"conditions": [{"field": c["field"], "op": c["op"], "value": str(c["value"]).strip()}
                            for c in r["conditions"]]} for r in rules]


def validate(new, old):
    """A full config from the UI/API -> the config to store; ValueError with a message for the user. Connection
    secret keys are write-only: secret_key null/missing keeps the stored one."""
    if not isinstance(new, dict):
        raise ValueError("config must be an object")
    out = {"interval_seconds": _int(new.get("interval_seconds"), 60, 86400, "interval (seconds)")}
    conns = {}
    for n, c in (new.get("connections") or {}).items():
        if not NAME.match(n):
            raise ValueError(f"connection name {n!r}: lowercase letters, digits, dashes")
        if not c.get("bucket") or not c.get("access_key"):
            raise ValueError(f"connection {n}: bucket and access key are required")
        ep = (c.get("endpoint") or "").strip()
        if ep and not re.match(r"^https?://[^/\s]+/?$", ep):
            raise ValueError(f"connection {n}: endpoint like https://minio.lan:9000 (empty = AWS)")
        enc = (old.get("connections", {}).get(n) or {}).get("secret_key_enc")
        if c.get("secret_key"):
            enc = fernet().encrypt(c["secret_key"].encode()).decode()
        if not enc:
            raise ValueError(f"connection {n}: secret key is required")
        conns[n] = {"endpoint": ep.rstrip("/"), "region": (c.get("region") or "us-east-1").strip(),
                    "bucket": c["bucket"].strip(), "access_key": c["access_key"].strip(), "secret_key_enc": enc}
    targets = {}
    for n, t in (new.get("targets") or {}).items():
        if not NAME.match(n):
            raise ValueError(f"destination name {n!r}: lowercase letters, digits, dashes")
        if t.get("format") not in a.FORMATS:
            raise ValueError(f"destination {n}: format one of {list(a.FORMATS)}")
        folder = (t.get("folder") or "").strip().strip("/")
        if folder and (not FOLDER.match(folder) or ".." in folder.split("/")):
            raise ValueError(f"destination {n}: folder like logs/prod (letters, digits, . _ - and /)")
        if t.get("type") == "local":
            if not folder:
                raise ValueError(f"destination {n}: a local destination needs its own folder")
            mg = t.get("max_gb") or 0
            if not isinstance(mg, (int, float)) or mg < 0:
                raise ValueError(f"destination {n}: max size (GB) 0 or more (0 = no limit)")
            targets[n] = {"type": "local", "folder": folder, "format": t["format"],
                          "retention_days": _int(t.get("retention_days") or 0, 0, 36500, f"destination {n} retention (days)"),
                          "max_gb": mg}
        elif t.get("type") == "s3":
            if t.get("connection") not in conns:
                raise ValueError(f"destination {n}: pick an S3 connection")
            targets[n] = {"type": "s3", "connection": t["connection"], "folder": folder, "format": t["format"]}
        else:
            raise ValueError(f"destination {n}: type local or s3")
    local = [t["folder"] for t in targets.values() if t["type"] == "local"]
    for f in local:  # one folder per local destination: each trims its own files
        if any(o != f and (o + "/").startswith(f + "/") for o in local) or local.count(f) > 1:
            raise ValueError(f"local folder {f}: used by two destinations (or one inside another)")

    def _targets(v, what):
        if not isinstance(v, list) or any(t not in targets for t in v):
            raise ValueError(f"{what}: destinations must be ones defined above")
        return list(dict.fromkeys(v))

    lg = new.get("logs") or {}
    out["logs"] = {"retention_days": _int(lg.get("retention_days"), 1, 36500, "log retention (days)"),
                   "disk_max_percent": _int(lg.get("disk_max_percent"), 50, 94, "disk limit (%)"),
                   "max_gb": _gb(lg.get("max_gb") or 0, "max log size"),
                   "targets": _targets(lg.get("targets", []), "default destinations"),
                   "filters": _filters(lg.get("filters", []), "default archive filters")}
    out["traces"] = {"retention_days": _int((new.get("traces") or {}).get("retention_days"), 1, 3650, "trace retention (days)")}
    ar = new.get("archive") or {}
    pct = ar.get("disk_max_percent") or 0
    if pct and not (isinstance(pct, int) and 50 <= pct <= 99):
        raise ValueError("archive disk limit (%): 0 (off) or 50 to 99")
    out["archive"] = {"max_gb": _gb(ar.get("max_gb") or 0, "max archive size"), "disk_max_percent": pct}
    out["apps"] = {}
    for app, k in (new.get("apps") or {}).items():
        if not app or len(app) > 200:
            raise ValueError(f"app {app!r}: name too long or empty")
        own = {"retention_days": None if k.get("retention_days") is None else _int(k["retention_days"], 1, 36500, f"{app} retention (days)"),
               "targets": None if k.get("targets") is None else _targets(k["targets"], f"{app} destinations"),
               "filters": None if k.get("filters") is None else _filters(k["filters"], f"{app} archive filters"),
               "max_gb": None if k.get("max_gb") is None else _gb(k["max_gb"], f"{app} max size", allow_zero=False)}
        if any(v is not None for v in own.values()):
            out["apps"][app] = own
    out["targets"], out["connections"] = targets, conns
    return out


def public(cfg):
    """The config for the API: connection secrets reduced to secret_key_set."""
    c = copy.deepcopy(cfg)
    for conn in c["connections"].values():
        conn["secret_key_set"] = bool(conn.pop("secret_key_enc", None))
    return c


def _load(name, default):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default()


def _save(name, obj):
    p = os.path.join(DATA, name)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.chmod(p + ".tmp", 0o600)
    os.replace(p + ".tmp", p)


CONFIG, STATE = None, None


class Ctx:
    """What the engine needs: OpenSearch, the clock, state, S3 and the action log."""
    def __init__(self, api, cfg, state, s3_put=None, now=time.time, archive_root=ARCHIVE, tmp=None):
        self.api, self.cfg, self.state, self.now, self.archive_root = api, cfg, state, now, archive_root
        self.tmp = tmp or os.path.join(DATA, "tmp")
        os.makedirs(self.tmp, exist_ok=True)
        self.s3_put = s3_put or (lambda conn, key, path: a.s3_request(conn, "PUT", key, path))

    def connection(self, name):
        c = dict(self.cfg["connections"][name])
        c["secret_key"] = fernet().decrypt(c.pop("secret_key_enc").encode()).decode()
        return c

    def save_state(self):
        _save("state.json", self.state)

    def log(self, kind, detail):
        ACTIONS.appendleft({"time": time.time(), "kind": kind, "detail": detail})
        print(time.strftime("%Y-%m-%d %H:%M:%S"), kind, detail, flush=True)


def one_pass(api):
    """A pass under the lock (loop and Run now never overlap)."""
    with LOCK:
        STATUS["running"] = True
        start = time.time()
        ctx = Ctx(api, CONFIG, STATE)
        try:
            r = a.run_pass(ctx, CONFIG)
            STATUS.update(usage=r["targets"], archive=r["archive"], logs_bytes=r["logs_bytes"])
            STATUS["disk_percent"] = a.disk_percent(api)
            STATUS["last"] = {"start": start, "end": time.time(), "ok": True}
        except Exception as e:  # logged, retried next pass; logs whose archive failed stay
            ctx.log("error", f"{type(e).__name__}: {e}")
            STATUS["last"] = {"start": start, "end": time.time(), "ok": False, "error": f"{type(e).__name__}: {e}"}
            traceback.print_exc()
        finally:
            STATUS["running"] = False


def remove_ism(api):
    """This service owns retention: drop the ISM policies the old setup-retention-policy.sh created, if any."""
    for p in ("mule-logs-retention", "logstash-retention", "jaeger-retention"):
        try:
            api("DELETE", f"/_plugins/_ism/policies/{p}")
            print("removed ISM policy", p, flush=True)
        except urllib.error.HTTPError:
            pass


def loop(api):
    while True:
        try:
            remove_ism(api)
            break
        except Exception as e:  # OpenSearch still starting
            print("waiting for OpenSearch:", e, flush=True)
            time.sleep(10)
    while True:
        one_pass(api)
        STATUS["next_at"] = time.time() + CONFIG["interval_seconds"]
        WAKE.wait(CONFIG["interval_seconds"])
        WAKE.clear()


# ---------- views ----------

def indices_view(api, cfg, now=None):
    """Every managed index with docs, size, apps and what is due."""
    today = datetime.datetime.fromtimestamp(now or time.time(), datetime.timezone.utc).date()
    cat = api("GET", "/_cat/indices/" + ",".join(p + "*" for p in a.LOGS + a.TRACES) + "?format=json&bytes=b&h=index,docs.count,store.size")
    agg = api("POST", "/" + ",".join(p + "*" for p in a.LOGS) + "/_search?ignore_unavailable=true&allow_no_indices=true",
              {"size": 0, "aggs": {"i": {"terms": {"field": "_index", "size": 2000},
                                         "aggs": {"apps": {"terms": {"field": "application", "missing": a.NO_APP, "size": 200}}}}}})
    apps = {b["key"]: {x["key"]: x["doc_count"] for x in b["apps"]["buckets"]} for b in agg.get("aggregations", {}).get("i", {}).get("buckets", [])}
    out = []
    for i in cat:
        d = a.day_of(i["index"])
        if not d:
            continue
        age = (today - d).days
        log = i["index"].startswith(a.LOGS)
        row = {"index": i["index"], "day": d.isoformat(), "age_days": age, "kind": "log" if log else "trace",
               "docs": int(i.get("docs.count") or 0), "bytes": int(i.get("store.size") or 0)}
        if log:
            size, docs = int(i.get("store.size") or 0), int(i.get("docs.count") or 0)
            row["apps"] = [{"app": k, "docs": v, "bytes": int(a.app_bytes(size, docs, v)),
                            "retention_days": a.effective(cfg, k)["retention_days"],
                            "due": age > a.effective(cfg, k)["retention_days"] and age > 0} for k, v in sorted(apps.get(i["index"], {}).items())]
        else:
            row["due"] = age > cfg["traces"]["retention_days"]
        out.append(row)
    return sorted(out, key=lambda r: (r["day"], r["index"]), reverse=True)


def apps_view(api, cfg):
    """Apps seen in the logs plus apps with knobs, each with its effective settings and estimated size."""
    seen, size = {}, {}
    try:
        for i in indices_view(api, cfg):
            for x in i.get("apps", []):
                seen[x["app"]] = seen.get(x["app"], 0) + x["docs"]
                size[x["app"]] = size.get(x["app"], 0) + x["bytes"]
    except Exception:
        pass
    names = sorted(set(seen) | set(cfg["apps"]))
    return [{"app": n, "docs": seen.get(n, 0), "bytes": size.get(n, 0), "own": cfg["apps"].get(n), "effective": a.effective(cfg, n)}
            for n in names]


def usage_view(api, cfg, state, archive_root=ARCHIVE, now=None):
    """Where the space goes: OpenSearch's disk (logs, traces, OpenSearch's own indices, other files, free), the archive's
    disk (archive files per disk folder, other files, free), logs per app and per day, what was sent to each destination
    (S3 included) and how long until the limits at the recent growth."""
    today = datetime.datetime.fromtimestamp(now or time.time(), datetime.timezone.utc).date()
    node = next(iter(api("GET", "/_nodes/stats/fs")["nodes"].values()))["fs"]["total"]
    disk_total, disk_free = node["total_in_bytes"], node["available_in_bytes"]
    rows = api("GET", "/_cat/indices?format=json&bytes=b&expand_wildcards=all&h=index,store.size,docs.count")
    kind = lambda n: "logs" if n.startswith(a.LOGS) else "traces" if n.startswith(a.TRACES) else "opensearch"  # noqa: E731
    parts = {"logs": 0, "traces": 0, "opensearch": 0}
    days = {}
    for r in rows:
        b, k = int(r.get("store.size") or 0), kind(r["index"])
        parts[k] += b
        d = a.day_of(r["index"]) if k != "opensearch" else None
        if d:
            row = days.setdefault(d.isoformat(), {"day": d.isoformat(), "logs": 0, "traces": 0, "log_count": 0})
            row[k] += b
            if k == "logs":
                row["log_count"] += int(r.get("docs.count") or 0)
    used = disk_total - disk_free
    parts["other"] = max(0, used - sum(parts.values()))  # not OpenSearch indices: translog, the OS, other volumes
    apps = {}
    for i in indices_view(api, cfg, now):
        for x in i.get("apps", []):
            e = apps.setdefault(x["app"], {"app": x["app"], "bytes": 0, "logs": 0, "days": 0})
            e["bytes"] += x["bytes"]; e["logs"] += x["docs"]; e["days"] += 1  # noqa: E702
    # growth: the last 7 complete days (today is still filling up)
    recent = [days[(today - datetime.timedelta(days=n)).isoformat()] for n in range(1, 8)
              if (today - datetime.timedelta(days=n)).isoformat() in days]
    per_day = sum(r["logs"] + r["traces"] for r in recent) / len(recent) if recent else 0
    log_per_day = sum(r["logs"] for r in recent) / len(recent) if recent else 0
    until = lambda room, rate: round(room / rate, 1) if rate > 0 and room > 0 else (0 if room <= 0 else None)  # noqa: E731
    limit_bytes = disk_total * cfg["logs"]["disk_max_percent"] / 100
    cap = (cfg["logs"].get("max_gb") or 0) * a.GB
    ctx = Ctx(None, cfg, state, archive_root=archive_root)
    files = a.archive_files(ctx, cfg)
    pct, afree = a.archive_disk(ctx)
    au = shutil.disk_usage(archive_root)
    by_target = {}
    for f in files:
        t = by_target.setdefault(f[3], {"files": 0, "bytes": 0})
        t["files"] += 1; t["bytes"] += f[1]  # noqa: E702
    abytes = sum(f[1] for f in files)
    targets = [{"name": n, "type": t["type"], "format": t["format"], "on_disk": by_target.get(n, {"files": 0, "bytes": 0}) if t["type"] == "local" else None,
                "sent": (state.get("sent") or {}).get(n, {"files": 0, "bytes": 0, "logs": 0}),
                "max_gb": t.get("max_gb") if t["type"] == "local" else None}
               for n, t in cfg["targets"].items()]
    return {
        "opensearch": {"total": disk_total, "free": disk_free, "used": used, "parts": parts,
                       "limit_percent": cfg["logs"]["disk_max_percent"], "max_log_gb": cfg["logs"].get("max_gb") or 0,
                       "growth_per_day": per_day, "log_growth_per_day": log_per_day,
                       "days_to_disk_limit": until(limit_bytes - used, per_day),
                       "days_to_log_cap": until(cap - parts["logs"], log_per_day) if cap else None},
        "archive": {"total": au.total, "free": afree, "used": au.used, "archive_bytes": abytes, "files": len(files),
                    "other": max(0, au.used - abytes), "max_gb": (cfg.get("archive") or {}).get("max_gb") or 0,
                    "limit_percent": (cfg.get("archive") or {}).get("disk_max_percent") or 0, "percent": pct},
        "apps": sorted(apps.values(), key=lambda e: -e["bytes"]),
        "days": sorted(days.values(), key=lambda r: r["day"]),
        "targets": targets,
    }


def test_connection(cfg, name, put=a.s3_request):
    """Write and delete a small object in the connection's bucket."""
    ctx = Ctx(None, cfg, {}, tmp=os.path.join(DATA, "tmp"))
    conn = ctx.connection(name)
    p = os.path.join(ctx.tmp, "connection-test.txt")
    with open(p, "w") as f:
        f.write("log-archiver connection test\n")
    key = f"log-archiver-test-{int(time.time())}.txt"
    try:
        put(conn, "PUT", key, p)
        put(conn, "DELETE", key)
    finally:
        os.remove(p)
    return {"ok": True, "detail": f"wrote and deleted s3://{conn['bucket']}/{key}"}


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    api = None

    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"null")

    def authorized(self):
        # only the gateway knows the key (it sets the header after its admin SSO check; clients' own is replaced)
        return bool(TOKEN) and hmac.compare_digest(self.headers.get("X-Gateway-Key", ""), TOKEN)

    def route(self, method):
        global CONFIG
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            return self.send(200, {"ok": True})
        if not self.authorized():
            return self.send(401, {"error": "only through the gateway: https://<host>:9443/log-archiver/"})
        try:
            if method == "GET" and path in ("/", "/index.html"):
                return self.send(200, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"), "rb").read(),
                                 "text/html; charset=utf-8")
            if method == "GET" and path == "/api/status":
                return self.send(200, {**STATUS, "actions": list(ACTIONS)[:100], "secrets": bool(KEY), "now": time.time()})
            if method == "GET" and path == "/api/config":
                return self.send(200, {"config": public(CONFIG), "fields": a.FIELDS, "ops": a.OPS, "formats": list(a.FORMATS)})
            if method == "PUT" and path == "/api/config":
                new = validate(self.body(), CONFIG)
                with LOCK:
                    CONFIG = new
                    _save("config.json", CONFIG)
                WAKE.set()  # apply now
                return self.send(200, {"config": public(CONFIG)})
            if method == "POST" and path == "/api/run":
                WAKE.set()
                return self.send(202, {"queued": True})
            if method == "GET" and path == "/api/indices":
                return self.send(200, {"indices": indices_view(self.api, CONFIG)})
            if method == "GET" and path == "/api/usage":
                return self.send(200, usage_view(self.api, CONFIG, STATE))
            if method == "GET" and path == "/api/apps":
                return self.send(200, {"apps": apps_view(self.api, CONFIG)})
            m = re.match(r"^/api/connections/([a-z0-9-]+)/test$", path)
            if method == "POST" and m:
                if m.group(1) not in CONFIG["connections"]:
                    return self.send(404, {"error": "no such connection (save it first)"})
                try:
                    return self.send(200, test_connection(CONFIG, m.group(1)))
                except urllib.error.HTTPError as e:
                    return self.send(200, {"ok": False, "detail": f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"})
                except Exception as e:
                    return self.send(200, {"ok": False, "detail": f"{type(e).__name__}: {e}"})
            return self.send(404, {"error": "not found"})
        except ValueError as e:
            return self.send(400, {"error": str(e)})
        except (InvalidToken, json.JSONDecodeError) as e:
            return self.send(400, {"error": f"{type(e).__name__}: {e}"})
        except Exception as e:
            traceback.print_exc()
            return self.send(502 if isinstance(e, (urllib.error.URLError, OSError)) else 500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        self.route("GET")

    def do_PUT(self):
        self.route("PUT")

    def do_POST(self):
        self.route("POST")


def main():
    global CONFIG, STATE
    os.makedirs(DATA, exist_ok=True)
    CONFIG = _load("config.json", default_config)
    for k, v in default_config().items():  # settings added since this config was saved
        CONFIG.setdefault(k, v)
    CONFIG["logs"].setdefault("max_gb", 0)
    STATE = _load("state.json", dict)
    if not os.path.exists(os.path.join(DATA, "config.json")):
        _save("config.json", CONFIG)
    api = a.OpenSearch(os.environ.get("OPENSEARCH_URL", "https://opensearch:9200"), "admin", os.environ.get("OPENSEARCH_PASSWORD", ""))
    Handler.api = api
    if not TOKEN:
        print("WARNING: LOG_ARCHIVER_TOKEN is empty: the UI/API refuse every request (./install.sh adds it to .env)", flush=True)
    threading.Thread(target=loop, args=(api,), daemon=True).start()
    print(f"log-archiver on :8080, logs {CONFIG['logs']['retention_days']} days, disk limit {CONFIG['logs']['disk_max_percent']}%, "
          f"traces {CONFIG['traces']['retention_days']} days, every {CONFIG['interval_seconds']}s", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
