"""Self-check: python log-archiver/test_archiver.py (no OpenSearch or S3 needed: both faked in memory)."""
import datetime, gzip, json, os, shutil, sys, tempfile, threading, time, urllib.request, zipfile

root = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{root}/data", ARCHIVE_DIR=f"{root}/archive", LOG_ARCHIVER_TOKEN="gw-key",
                  LOG_ARCHIVER_SECRETS_KEY="test-secret")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archiver as a  # noqa: E402
import app  # noqa: E402

os.makedirs(app.DATA, exist_ok=True)
NOW = datetime.datetime(2026, 10, 29, 12, tzinfo=datetime.timezone.utc).timestamp()
TODAY = datetime.date(2026, 10, 29)


def day(n):
    return (TODAY - datetime.timedelta(days=n)).strftime("%Y.%m.%d")


# ---------- fake OpenSearch: the endpoints and query shapes the engine uses ----------

def match(q, d):
    if q is None:
        return True
    (k, v), = q.items()
    if k == "term":
        (f, x), = v.items()
        return d.get(f) == x
    if k == "terms":
        (f, xs), = v.items()
        return d.get(f.replace(".keyword", "")) in xs
    if k == "exists":
        return v["field"] in d
    if k == "match_phrase":
        (f, x), = v.items()
        return x.lower() in str(d.get(f, "")).lower()
    if k in ("wildcard", "prefix"):
        (f, x), = v.items()
        x = x["value"] if isinstance(x, dict) else x
        s, x = str(d.get(f.replace(".keyword", ""), "")).lower(), x.lower()
        return (x.strip("*") in s) if k == "wildcard" else s.startswith(x)
    if k == "bool":
        ok = all(match(c, d) for c in v.get("filter", [])) and not any(match(c, d) for c in v.get("must_not", []))
        if "should" in v:
            ok = ok and sum(match(c, d) for c in v["should"]) >= v.get("minimum_should_match", 1)
        return ok
    raise AssertionError(f"query not faked: {q}")


class FakeOS:
    def __init__(self, indices, disk=lambda os_: 50.0, short_export=False):
        self.idx, self.disk, self.short, self.scrolls, self.calls = indices, disk, short_export, {}, []

    def __call__(self, method, path, body=None, timeout=0):
        self.calls.append((method, path.split("?")[0]))
        p = path.split("?")[0].strip("/").split("/")
        if p[0] == "_cat":
            pats = [x.rstrip("*") for x in p[2].split(",")] if len(p) > 2 else [""]  # no pattern: every index
            # 100 bytes per log: sizes are easy to reason about in the cap tests
            return [{"index": n, "store.size": str(100 * len(d)), "docs.count": str(len(d))}
                    for n, d in self.idx.items() if any(n.startswith(x) for x in pats)]
        if p[0] == "_nodes":
            return {"nodes": {"n": {"fs": {"total": {"total_in_bytes": 100, "available_in_bytes": 100 - self.disk(self)}}}}}
        if p[0] == "_search" and method == "DELETE":
            return {}
        if p[0] == "_search":
            docs = self.scrolls.pop(body["scroll_id"])
            return self.page(docs)
        index = p[0]
        if "*" in index or "," in index:  # multi-index aggregations of the UI views
            pats = [x.rstrip("*") for x in index.split(",")]
            names = [n for n in self.idx if any(n.startswith(x) for x in pats)]
            appsof = lambda ds: [{"key": k, "doc_count": sum(d.get("application", a.NO_APP) == k for d in ds)}  # noqa: E731
                                 for k in sorted({d.get("application", a.NO_APP) for d in ds})]
            if "i" in body["aggs"]:
                return {"aggregations": {"i": {"buckets": [{"key": n, "apps": {"buckets": appsof(self.idx[n])}} for n in names]}}}
            return {"aggregations": {"apps": {"buckets": appsof([d for n in names for d in self.idx[n]])}}}
        docs = self.idx[index]
        if method == "DELETE":
            del self.idx[index]
            return {}
        if p[1] == "_count":
            return {"count": sum(match(body["query"], d) for d in docs)}
        if p[1] == "_forcemerge":
            return {}
        if p[1] == "_delete_by_query":
            keep = [d for d in docs if not match(body["query"], d)]
            self.idx[index] = keep
            return {"deleted": len(docs) - len(keep)}
        if p[1] == "_search" and "aggs" in body:
            counts = {}
            for d in docs:
                k = d.get("application", a.NO_APP)
                counts[k] = counts.get(k, 0) + 1
            return {"aggregations": {"apps": {"buckets": [{"key": k, "doc_count": v} for k, v in counts.items()]}}}
        hits = [d for d in docs if match(body.get("query"), d)]
        if self.short:
            hits = hits[:-1]
        return self.page(hits, body["size"])

    def page(self, docs, size=2):
        sid = str(len(self.scrolls) + 1) + str(time.time())
        self.scrolls[sid] = docs[size:]
        return {"_scroll_id": sid, "hits": {"hits": [{"_source": d} for d in docs[:size]]}}


def logs(app_, n, **kw):
    return [dict({"application": app_, "level": "INFO", "message": f"{app_} line {i}"}, **kw) for i in range(n)]


def config(**over):
    c = app.default_config()
    c["logs"].update(retention_days=30, disk_max_percent=80)
    c["traces"]["retention_days"] = 7
    c["targets"].update({"zip": {"type": "local", "folder": "zip", "format": "zip", "retention_days": 0, "max_gb": 0},
                         "s3raw": {"type": "s3", "connection": "aws", "folder": "mule/prod", "format": "raw"}})
    c["connections"] = {"aws": {"endpoint": "", "region": "us-east-1", "bucket": "b", "access_key": "AK",
                                "secret_key_enc": app.fernet().encrypt(b"SK").decode()}}
    # orders: 10 days, to S3 (raw) and a zip folder, only ERRORs or messages with "audit"
    c["apps"]["orders"] = {"retention_days": 10, "targets": ["s3raw", "zip"],
                           "filters": [{"conditions": [{"field": "level", "op": "is", "value": "ERROR"}]},
                                       {"conditions": [{"field": "message", "op": "contains", "value": "audit"}]}]}
    c.update(over)
    return c


uploads = []
def s3_ok(conn, key, path):
    uploads.append((conn["bucket"], conn["secret_key"], key, open(path, "rb").read()))


def fresh_ctx(api, cfg, s3=s3_ok):
    shutil.rmtree(f"{root}/archive", ignore_errors=True)
    uploads.clear()
    return app.Ctx(api, cfg, {}, s3_put=s3, now=lambda: NOW, archive_root=f"{root}/archive", tmp=f"{root}/tmp")


def orders_day():
    return logs("orders", 3) + logs("orders", 2, level="ERROR") + [{"application": "orders", "level": "INFO",
                                                                    "message": "AUDIT refund 42"}]


# ---------- rules ----------
cfg = config()
assert a.effective(cfg, "orders")["retention_days"] == 10 and a.effective(cfg, "shop") == \
    {"retention_days": 30, "targets": ["local"], "filters": [], "max_gb": None}
fq = a.filters_query(cfg["apps"]["orders"]["filters"])
assert [d["message"] for d in orders_day() if match(fq, d)] == ["orders line 0", "orders line 1", "AUDIT refund 42"]
assert a.filters_query([]) is None
q = a.condition_query({"field": "level", "op": "is_not", "value": "DEBUG, TRACE"})
assert match(q, {"level": "INFO"}) and not match(q, {"level": "TRACE"})
assert match(a.condition_query({"field": "loggerName", "op": "starts_with", "value": "org.mule"}), {"loggerName": "org.mule.x"})

# ---------- a pass: per-app retention, partial delete, archive filters, formats ----------
fake = FakeOS({f"mule-logs-{day(40)}": logs("shop", 4) + orders_day(), f"mule-logs-{day(20)}": logs("shop", 2) + orders_day(),
               f"mule-logs-{day(5)}": logs("shop", 1), f"mule-logs-{day(0)}": logs("shop", 9),
               f"logstash-{day(40)}": [{"message": "syslog x"}],
               f"jaeger-span-{day(8)}": [{}], f"jaeger-span-{day(6)}": [{}]})
ctx = fresh_ctx(fake, cfg)
a.run_pass(ctx, cfg)
assert f"mule-logs-{day(40)}" not in fake.idx and f"logstash-{day(40)}" not in fake.idx, "every app due: whole index"
assert sorted(d["application"] for d in fake.idx[f"mule-logs-{day(20)}"]) == ["shop", "shop"], "orders (10 d) gone, shop (30 d) kept"
assert f"mule-logs-{day(5)}" in fake.idx and len(fake.idx[f"mule-logs-{day(0)}"]) == 9
assert f"jaeger-span-{day(8)}" not in fake.idx and f"jaeger-span-{day(6)}" in fake.idx, "traces: 7 days"
with gzip.open(f"{root}/archive/local/mule-logs-{day(40)}/shop.ndjson.gz", "rt", encoding="utf-8") as f:
    assert len(f.readlines()) == 4, "shop: no filters, every log, gzip in the default destination"
with gzip.open(f"{root}/archive/local/logstash-{day(40)}/{a.safe(a.NO_APP)}.ndjson.gz", "rt", encoding="utf-8") as f:
    assert json.loads(f.read())["message"] == "syslog x", "logs without application: global rules"
with zipfile.ZipFile(f"{root}/archive/zip/mule-logs-{day(20)}/orders.zip") as z:
    lines = z.read(f"mule-logs-{day(20)}-orders.ndjson").decode().splitlines()
assert len(lines) == 3 and "AUDIT refund 42" in lines[2], "orders: only ERRORs or audit, zipped"
sent = ctx.state["sent"]
assert sent["s3raw"]["files"] == 2 and sent["s3raw"]["logs"] == 6 and sent["local"]["files"] == 2 and     sent["zip"]["bytes"] == sum(os.path.getsize(f"{root}/archive/zip/{d}/orders.zip") for d in os.listdir(f"{root}/archive/zip")), sent
keys = sorted(k for _, _, k, _ in uploads)
assert keys == [f"mule/prod/mule-logs-{day(40)}/orders.ndjson", f"mule/prod/mule-logs-{day(20)}/orders.ndjson"], keys
assert all(b == "b" and sk == "SK" and body.count(b"\n") == 3 for b, sk, _, body in uploads), "raw to S3 with the decrypted key"
assert not os.path.exists(f"{root}/archive/local/mule-logs-{day(40)}/orders.ndjson.gz"), "orders has its own destinations"

# ---------- safety: a short export keeps the logs; a failed upload keeps them and doesn't redo what's done ----------
fake = FakeOS({f"mule-logs-{day(40)}": logs("shop", 3)}, short_export=True)
try:
    a.run_pass(fresh_ctx(fake, cfg), cfg)
    raise AssertionError("short export must raise")
except RuntimeError:
    pass
assert len(fake.idx[f"mule-logs-{day(40)}"]) == 3 and not os.path.exists(f"{root}/archive/local/mule-logs-{day(40)}")

fails = [1]
def s3_flaky(conn, key, path):
    if fails:
        fails.pop()
        raise OSError("S3 down")
    s3_ok(conn, key, path)
fake = FakeOS({f"mule-logs-{day(40)}": orders_day()})
ctx = fresh_ctx(fake, cfg, s3_flaky)
cfg2 = config(); cfg2["apps"]["orders"]["targets"] = ["zip", "s3raw"]  # zip first, then the failing S3
try:
    a.run_pass(ctx, cfg2)
    raise AssertionError("failed upload must raise")
except OSError:
    pass
assert len(fake.idx[f"mule-logs-{day(40)}"]) == 6 and ctx.state["done"][f"mule-logs-{day(40)}"]["orders"] == ["zip"]
zipped = f"{root}/archive/zip/mule-logs-{day(40)}/orders.zip"
t0 = os.path.getmtime(zipped)
time.sleep(0.05)
a.run_pass(ctx, cfg2)
assert f"mule-logs-{day(40)}" not in fake.idx and len(uploads) == 1 and os.path.getmtime(zipped) == t0, "retry: only S3"
assert f"mule-logs-{day(40)}" not in ctx.state["done"], "state forgotten with the index"

# ---------- disk pressure: oldest first (traces before logs of the same day), archived, never today ----------
level = {"v": 90.0}
fake = FakeOS({f"mule-logs-{day(2)}": logs("shop", 2), f"jaeger-span-{day(2)}": [{}], f"mule-logs-{day(1)}": logs("shop", 1),
               f"mule-logs-{day(0)}": logs("shop", 5)}, disk=lambda f: level["v"])
order = []
real_api = fake.__call__
def api(method, path, body=None, timeout=0):
    if method == "DELETE" and not path.startswith("/_search"):
        order.append(path.strip("/"))
        level["v"] -= 6
    return real_api(method, path, body)
ctx = fresh_ctx(api, cfg)
a.run_pass(ctx, cfg)
assert order == [f"jaeger-span-{day(2)}", f"mule-logs-{day(2)}"], order  # 90 -> 84 -> 78 < 80
assert os.path.exists(f"{root}/archive/local/mule-logs-{day(2)}/shop.ndjson.gz"), "archived before the disk delete"
level["v"] = 99.0
fake2 = FakeOS({f"mule-logs-{day(0)}": logs("shop", 5)}, disk=lambda f: 99.0)
ctx = fresh_ctx(fake2, cfg)
a.run_pass(ctx, cfg)
assert f"mule-logs-{day(0)}" in fake2.idx and any(x["kind"] == "warning" for x in app.ACTIONS), "today is never deleted"

# ---------- size caps: all logs together (logs.max_gb), one app's logs (apps.<app>.max_gb); today never goes ----------
GB = a.GB
fake = FakeOS({f"mule-logs-{day(3)}": logs("shop", 4) + logs("orders", 4), f"mule-logs-{day(2)}": logs("shop", 4),
               f"mule-logs-{day(1)}": logs("shop", 2) + logs("orders", 6), f"mule-logs-{day(0)}": logs("shop", 3)})
cap = config(); cap["logs"]["max_gb"] = 2000 / GB   # 23 logs = 2300 bytes > 2000: the oldest day (800 bytes) goes
cap["apps"]["orders"].update(retention_days=None, filters=None)
ctx = fresh_ctx(fake, cap)
r = a.run_pass(ctx, cap)
assert f"mule-logs-{day(3)}" not in fake.idx and f"mule-logs-{day(2)}" in fake.idx, sorted(fake.idx)
assert os.path.exists(f"{root}/archive/local/mule-logs-{day(3)}/shop.ndjson.gz"), "capped day archived first"
assert r["logs_bytes"] == 1500 and r["archive"]["files"] >= 1, r
fake = FakeOS({f"mule-logs-{day(3)}": logs("shop", 4) + logs("orders", 4), f"mule-logs-{day(1)}": logs("shop", 2) + logs("orders", 6),
               f"mule-logs-{day(0)}": logs("orders", 2)})
per = config(); per["apps"]["orders"] = {"retention_days": None, "targets": ["zip"], "filters": None, "max_gb": 900 / GB}
ctx = fresh_ctx(fake, per)
a.run_pass(ctx, per)   # orders: 400 + 600 + 200 (today) = 1200 > 900: its day(3) share goes, shop's logs that day stay
assert sorted(d["application"] for d in fake.idx[f"mule-logs-{day(3)}"]) == ["shop"] * 4, fake.idx[f"mule-logs-{day(3)}"]
assert sum(d["application"] == "orders" for d in fake.idx[f"mule-logs-{day(1)}"]) == 6, "800 <= 900: stop"
assert os.path.exists(f"{root}/archive/zip/mule-logs-{day(3)}/orders.zip")
fake = FakeOS({f"mule-logs-{day(0)}": logs("orders", 20)})
ctx = fresh_ctx(fake, per)
app.ACTIONS.clear()
a.run_pass(ctx, per)
assert len(fake.idx[f"mule-logs-{day(0)}"]) == 20 and any("only today's" in x["detail"] for x in app.ACTIONS)

# ---------- archive space (all disk folders together): archive.max_gb and the archive disk's own % ----------
ctx = fresh_ctx(FakeOS({}), cfg)
for i, (folder, age) in enumerate([("local", 30), ("zip", 20), ("local", 10), ("zip", 1)]):
    pth = f"{root}/archive/{folder}/d{i}/f.gz"
    os.makedirs(os.path.dirname(pth), exist_ok=True)
    open(pth, "wb").write(b"x" * 1000)
    os.utime(pth, (NOW - age * 86400,) * 2)
lim = config(); lim["archive"] = {"max_gb": 2500 / GB, "disk_max_percent": 0}
u = a.trim_archive(ctx, lim)
assert u["files"] == 2 and u["bytes"] == 2000 and not os.path.exists(f"{root}/archive/local/d0")     and not os.path.exists(f"{root}/archive/zip/d1"), "the two oldest files, across both folders"
real_disk, real_remove = a.archive_disk, os.remove
pct = {"v": 93.0}
a.archive_disk = lambda c: (pct["v"], 0)
def drop_pct(path):  # each removed file frees 2% of the (fake) archive disk
    real_remove(path); pct["v"] -= 2
os.remove = drop_pct
lim["archive"] = {"max_gb": 0, "disk_max_percent": 92}
try:
    u = a.trim_archive(ctx, lim)
finally:
    os.remove, a.archive_disk = real_remove, real_disk
assert u["files"] == 1 and os.path.exists(f"{root}/archive/zip/d3/f.gz"), "93% -> 91%: one file (the oldest) goes"
assert "disk_percent" in a.trim_archive(ctx, config()) and a.trim_archive(ctx, config())["files"] == 1, "no limits: nothing goes"

# ---------- local destination: own retention (days) and size (GB) ----------
t = {"type": "local", "folder": "keep", "format": "gzip", "retention_days": 30, "max_gb": 0}
base = f"{root}/archive/keep"
for i, age in enumerate([40, 20, 10, 1]):
    p = f"{base}/d{i}/x.gz"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(b"x" * 400)
    os.utime(p, (NOW - age * 86400,) * 2)
ctx = fresh_ctx.__wrapped__ if hasattr(fresh_ctx, "__wrapped__") else None
ctx = app.Ctx(None, cfg, {}, now=lambda: NOW, archive_root=f"{root}/archive", tmp=f"{root}/tmp")
u = a.trim_local(ctx, "keep", t, NOW)
assert u == {"files": 3, "bytes": 1200} and not os.path.exists(f"{base}/d0"), "40-day file and its folder gone"
u = a.trim_local(ctx, "keep", dict(t, retention_days=0, max_gb=900 / 1024 ** 3), NOW)
assert u == {"files": 2, "bytes": 800} and os.path.exists(f"{base}/d3/x.gz"), "size cap: oldest file goes first"

# ---------- S3 signing: AWS test suite vector get-vanilla ----------
h = a.sigv4("GET", "example.amazonaws.com", "/", "20150830T123600Z",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "us-east-1",
            "AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", service="service")
assert h["Authorization"].endswith("Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"), h

# ---------- config validation, write-only secrets ----------
pub = app.public(cfg)
assert pub["connections"]["aws"] == {"endpoint": "", "region": "us-east-1", "bucket": "b", "access_key": "AK", "secret_key_set": True}
kept = app.validate(json.loads(json.dumps(pub)), cfg)  # the UI sends back what it got: no secret -> the stored one stays
assert kept["connections"]["aws"]["secret_key_enc"] == cfg["connections"]["aws"]["secret_key_enc"]
new = json.loads(json.dumps(pub)); new["connections"]["aws"]["secret_key"] = "NEW"
assert app.fernet().decrypt(app.validate(new, cfg)["connections"]["aws"]["secret_key_enc"].encode()) == b"NEW"
def bad(mutate, word):
    c = json.loads(json.dumps(pub)); mutate(c)
    try:
        app.validate(c, cfg)
    except ValueError as e:
        assert word in str(e), (word, e)
        return
    raise AssertionError(f"accepted: {word}")
bad(lambda c: c["logs"].update(retention_days=0), "log retention")
bad(lambda c: c["logs"].update(disk_max_percent=97), "disk limit")
bad(lambda c: c["logs"].update(targets=["nope"]), "destinations")
bad(lambda c: c["apps"]["orders"].update(targets=["gone"]), "orders destinations")
bad(lambda c: c["targets"].update(x={"type": "local", "folder": "../etc", "format": "zip"}), "folder")
bad(lambda c: c["targets"].update(x={"type": "local", "folder": "zip/sub", "format": "zip"}), "used by two")
bad(lambda c: c["targets"].update(x={"type": "s3", "connection": "nope", "folder": "", "format": "raw"}), "S3 connection")
bad(lambda c: c["targets"]["zip"].update(format="rar"), "format")
bad(lambda c: c["connections"].update(new={"bucket": "b", "access_key": "k"}), "secret key is required")
bad(lambda c: c["apps"]["orders"].update(filters=[{"conditions": [{"field": "password", "op": "is", "value": "x"}]}]), "field one of")
bad(lambda c: c["apps"]["orders"].update(filters=[{"conditions": []}]), "at least one condition")
bad(lambda c: c.update(interval_seconds=5), "interval")
bad(lambda c: c["logs"].update(max_gb=-1), "max log size")
bad(lambda c: c["apps"]["orders"].update(max_gb=0), "orders max size")
bad(lambda c: c.update(archive={"max_gb": 0, "disk_max_percent": 30}), "archive disk limit")
bad(lambda c: c.update(archive={"max_gb": "big", "disk_max_percent": 0}), "max archive size")
ok = json.loads(json.dumps(pub)); ok["logs"]["max_gb"] = 50; ok["apps"]["orders"]["max_gb"] = 2.5
ok["archive"] = {"max_gb": 100, "disk_max_percent": 90}
v = app.validate(ok, cfg)
assert (v["logs"]["max_gb"], v["apps"]["orders"]["max_gb"], v["archive"]) == (50, 2.5, {"max_gb": 100, "disk_max_percent": 90})
assert "shop" not in app.validate(dict(json.loads(json.dumps(pub)), apps={"shop": {"retention_days": None}}), cfg)["apps"], \
    "an app with no knobs set isn't stored"

# ---------- HTTP: only the gateway (X-Gateway-Key) gets in; /health is open ----------
app.CONFIG, app.STATE = cfg, {}
app.Handler.api = FakeOS({f"mule-logs-{day(3)}": logs("shop", 2) + orders_day()})
srv = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}"
def call(path, method="GET", body=None, key="gw-key"):
    req = urllib.request.Request(url + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"X-Gateway-Key": key} if key else {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
assert call("/health", key=None)[0] == 200
assert call("/api/status", key=None)[0] == 401 and call("/api/status", key="wrong")[0] == 401 and call("/", key=None)[0] == 401
st, body = call("/api/config")
assert st == 200 and b"secret_key_enc" not in body and b"SK" not in body and json.loads(body)["config"]["connections"]["aws"]["secret_key_set"]
st, body = call("/api/config", "PUT", dict(json.loads(body)["config"], interval_seconds=1))
assert st == 400 and b"interval" in body
st, body = call("/api/indices")
rows = json.loads(body)["indices"]
assert st == 200 and {r["app"]: r["retention_days"] for r in rows[0]["apps"]} == {"orders": 10, "shop": 30}
st, body = call("/api/apps")
got = {x["app"]: x["bytes"] for x in json.loads(body)["apps"]}
assert st == 200 and got == {"orders": 600, "shop": 200}, got   # 100 bytes per log: each app's share of the index
assert call("/", key="gw-key")[0] == 200

# ---------- usage: what fills each disk, per app and per day, growth, destinations ----------
app.Handler.api = FakeOS({f"mule-logs-{day(n)}": logs("shop", 10) + logs("orders", 30) for n in range(0, 9)}
                         | {f"jaeger-span-{day(1)}": [{}] * 5, ".kibana_1": [{}] * 3}, disk=lambda f: 40.0)  # 100-byte disk: 40 used
app.STATE = {"sent": {"s3raw": {"files": 4, "bytes": 9000, "logs": 120}}}
st, body = call("/api/usage")
u = json.loads(body)
o = u["opensearch"]
assert st == 200 and (o["total"], o["used"], o["free"]) == (100, 40, 60), o
assert o["parts"] == {"logs": 36000, "traces": 500, "opensearch": 300, "other": 0}, o["parts"]  # indices > fake disk: other clamps to 0
assert o["growth_per_day"] == 4000 + 500 / 7 and o["log_growth_per_day"] == 4000, o
assert o["days_to_disk_limit"] == 0, "already past the (tiny) limit"
assert [(x["app"], x["bytes"], x["logs"], x["days"]) for x in u["apps"]] == [("orders", 27000, 270, 9), ("shop", 9000, 90, 9)], u["apps"]
assert [d["day"] for d in u["days"]][-1] == TODAY.isoformat() and u["days"][-2]["traces"] == 500 and u["days"][0]["log_count"] == 40
t = {x["name"]: x for x in u["targets"]}
assert t["s3raw"]["sent"]["bytes"] == 9000 and t["s3raw"]["on_disk"] is None and t["local"]["on_disk"] is not None
a_ = u["archive"]
assert a_["total"] > 0 and a_["archive_bytes"] == sum(x["on_disk"]["bytes"] for x in u["targets"] if x["on_disk"]), a_
srv.shutdown()
print("test_archiver: ok")
