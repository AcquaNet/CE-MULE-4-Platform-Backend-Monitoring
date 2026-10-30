"""Log retention engine: the only thing that deletes logs and traces in OpenSearch (no ISM).

One pass (run_pass):
- log indices (mule-logs-*, logstash-*), per day and per app: an app's logs older than its retention are archived to
  its destinations (only the logs matching its archive filters, if any), then deleted (the whole index once every app
  in it is due, else delete_by_query for the due apps);
- size caps: while all log indices together exceed logs.max_gb the oldest day goes; while one app's logs exceed its
  max_gb that app's oldest day goes (an app's size = its share of each index's logs x the index size: an estimate);
- while OpenSearch's disk is above the limit: the oldest day goes (each app archived first), today's never;
- trace indices (jaeger-span-*, jaeger-service-*) older than their retention are deleted (no archive);
- local destinations are trimmed to their own retention and size, then all disk folders together to the archive
  limits (archive.max_gb, archive.disk_max_percent of the archive's own disk), oldest files first.
A log is only deleted after its export is complete (exported count = matching count); a failed upload keeps the logs
for the next pass. Stdlib only; app.py holds the config, the HTTP API and the loop.
"""
import datetime, gzip, hashlib, hmac, json, os, re, shutil, ssl, time, urllib.parse, urllib.request, zipfile

LOGS, TRACES = ("mule-logs-", "logstash-"), ("jaeger-span-", "jaeger-service-")
NO_APP = "(no application)"   # logs without an application field (logstash-*, other senders): global rules
DAY = re.compile(r"(\d{4})[.-](\d{2})[.-](\d{2})$")  # mule-logs-2026.10.29, jaeger-span-2026-10-29
FORMATS = {"raw": ".ndjson", "gzip": ".ndjson.gz", "zip": ".zip"}
# filterable fields (index template in scripts/setup-opensearch.sh): message is text (+ .keyword), the rest keyword
FIELDS = ["level", "message", "loggerName", "tenant_id", "environment", "worker_id", "correlationId", "thread",
          "log_type", "source_host", "tags"]
OPS = ["is", "is_not", "contains", "starts_with"]


# ---------- rules ----------

def day_of(index):
    m = DAY.search(index)
    return datetime.date(*map(int, m.groups())) if m else None


def effective(cfg, app):
    """Retention, destinations and archive filters for one app: its own knobs where set (not None), else global.
    max_gb is the app's own size cap only (None = none; the global max_gb caps all logs together)."""
    own = cfg.get("apps", {}).get(app) or {}
    logs = cfg["logs"]
    pick = lambda k: own[k] if own.get(k) is not None else logs[k]  # noqa: E731
    return {"retention_days": pick("retention_days"), "targets": pick("targets"), "filters": pick("filters"),
            "max_gb": own.get("max_gb")}


def condition_query(c):
    f, op = c["field"], c["op"]
    vals = [v.strip() for v in str(c["value"]).split(",") if v.strip()]
    if op in ("is", "is_not"):
        q = {"terms": {"message.keyword" if f == "message" else f: vals}}
        return q if op == "is" else {"bool": {"must_not": [q]}}
    v = vals[0] if len(vals) == 1 else str(c["value"]).strip()
    if f == "message":
        return {"match_phrase": {"message": v}} if op == "contains" else {"prefix": {"message.keyword": v}}
    if op == "contains":
        return {"wildcard": {f: {"value": f"*{v}*", "case_insensitive": True}}}
    return {"prefix": {f: {"value": v, "case_insensitive": True}}}


def filters_query(filters):
    """Archive filters: a log is archived when it matches ANY rule; a rule matches when ALL its conditions do.
    None/[] = everything."""
    if not filters:
        return None
    return {"bool": {"should": [{"bool": {"filter": [condition_query(c) for c in r["conditions"]]}} for r in filters],
                     "minimum_should_match": 1}}


def app_query(app):
    return {"bool": {"must_not": [{"exists": {"field": "application"}}]}} if app == NO_APP else {"term": {"application": app}}


def and_query(*qs):
    qs = [q for q in qs if q]
    return qs[0] if len(qs) == 1 else {"bool": {"filter": qs}}


def safe(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


# ---------- OpenSearch ----------

class OpenSearch:
    def __init__(self, url, user, password):
        self.url = url.rstrip("/")
        self.auth = "Basic " + __import__("base64").b64encode(f"{user}:{password}".encode()).decode()
        self.ctx = ssl.create_default_context()  # per-install self-signed node cert (Fluent Bit and Jaeger skip it too)
        self.ctx.check_hostname, self.ctx.verify_mode = False, ssl.CERT_NONE

    def __call__(self, method, path, body=None, timeout=300):
        req = urllib.request.Request(self.url + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as r:
            return json.load(r)


def managed(api, today):
    """Indices this service may delete, oldest first: [(day, kind, name)] with kind log|trace; today's and undated
    ones are left alone."""
    names = [i["index"] for i in api("GET", "/_cat/indices/" + ",".join(p + "*" for p in LOGS + TRACES) + "?format=json&h=index")]
    out = []
    for n in names:
        d = day_of(n)
        if d and d < today and n.startswith(LOGS + TRACES):
            out.append((d, "log" if n.startswith(LOGS) else "trace", n))
    return sorted(out, key=lambda x: (x[0], x[1] == "log", x[2]))  # same day: traces (no archive) go first


def apps_in(api, index):
    r = api("POST", f"/{index}/_search", {"size": 0, "aggs": {"apps": {"terms": {"field": "application", "missing": NO_APP,
                                                                                 "size": 1000}}}})
    return {b["key"]: b["doc_count"] for b in r["aggregations"]["apps"]["buckets"]}


GB = 1024 ** 3


def sizes(api):
    """{index: (bytes, docs)} of the log indices."""
    rows = api("GET", "/_cat/indices/" + ",".join(p + "*" for p in LOGS) + "?format=json&bytes=b&h=index,store.size,docs.count")
    return {r["index"]: (int(r.get("store.size") or 0), int(r.get("docs.count") or 0)) for r in rows}


def app_bytes(size, docs, app_docs):
    """An app's share of an index (OpenSearch reports size per index only): its share of the logs x the index size."""
    return size * app_docs / docs if docs else 0


def disk_percent(api):
    nodes = api("GET", "/_nodes/stats/fs")["nodes"].values()
    return max(100 * (1 - n["fs"]["total"]["available_in_bytes"] / n["fs"]["total"]["total_in_bytes"]) for n in nodes)


def export(api, index, query, path):
    """Matching documents (_source, one JSON per line) to path; returns the count, raises if it falls short."""
    want = api("POST", f"/{index}/_count", {"query": query})["count"]
    n = 0
    r = api("POST", f"/{index}/_search?scroll=5m", {"size": 5000, "sort": ["_doc"], "query": query})
    try:
        with open(path, "w", encoding="utf-8") as f:
            while r["hits"]["hits"]:
                for h in r["hits"]["hits"]:
                    f.write(json.dumps(h["_source"], ensure_ascii=False) + "\n")
                n += len(r["hits"]["hits"])
                r = api("POST", "/_search/scroll", {"scroll": "5m", "scroll_id": r["_scroll_id"]})
    finally:
        try:
            api("DELETE", "/_search/scroll", {"scroll_id": [r["_scroll_id"]]})
        except Exception:
            pass
    if n != want:
        raise RuntimeError(f"{index}: exported {n} of {want} documents, logs kept")
    return n


# ---------- destinations ----------

def encode(src, fmt, dst, entry):
    """src (raw NDJSON) -> dst in fmt (raw | gzip | zip with one entry)."""
    if fmt == "raw":
        shutil.copyfile(src, dst)
    elif fmt == "gzip":
        with open(src, "rb") as i, gzip.open(dst, "wb") as o:
            shutil.copyfileobj(i, o)
    else:
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(src, entry)


def sigv4(method, host, path, amz_date, payload_hash, region, access, secret, service="s3", extra=None):
    """AWS Signature V4 headers for a request without a query string."""
    headers = {"host": host, "x-amz-date": amz_date, **(extra or {})}
    names = sorted(headers)
    canonical = "\n".join([method, urllib.parse.quote(path), "", *(f"{k}:{headers[k].strip()}" for k in names), "",
                           ";".join(names), payload_hash])
    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    key = ("AWS4" + secret).encode()
    for part in (amz_date[:8], region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    sig = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {**headers, "Authorization": f"AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={';'.join(names)}, Signature={sig}"}


def s3_request(conn, method, key, path=None):
    """One S3 request on conn ({endpoint, region, bucket, access_key, secret_key}); path = file to PUT."""
    # ponytail: one PUT, so at most 5 GB per object (one app's day); multipart upload if a day ever gets bigger
    region = conn.get("region") or "us-east-1"
    if conn.get("endpoint"):  # S3-compatible store (MinIO, ...): path-style
        u = urllib.parse.urlsplit(conn["endpoint"])
        host, base, p = u.netloc, f"{u.scheme}://{u.netloc}", f"/{conn['bucket']}/{key}"
    else:
        host = f"{conn['bucket']}.s3.{region}.amazonaws.com"
        base, p = "https://" + host, "/" + key
    amz = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h = sigv4(method, host, p, amz, "UNSIGNED-PAYLOAD", region, conn["access_key"], conn["secret_key"],
              extra={"x-amz-content-sha256": "UNSIGNED-PAYLOAD"})
    h.pop("host")  # urllib sends the same Host
    f = open(path, "rb") if path else None
    try:
        if path:
            h["Content-Length"] = str(os.path.getsize(path))
        req = urllib.request.Request(base + urllib.parse.quote(p), data=f, method=method, headers=h)
        urllib.request.urlopen(req, timeout=900).close()
    finally:
        if f:
            f.close()


def object_name(target, index, app):
    return "/".join(p for p in (target.get("folder", "").strip("/"), index, safe(app) + FORMATS[target["format"]]) if p)


def deliver(ctx, name, target, raw, index, app):
    """Put one app's day (raw NDJSON file) into one destination."""
    entry = f"{index}-{safe(app)}.ndjson"
    rel = object_name(target, index, app)
    if target["type"] == "local":
        dst = os.path.join(ctx.archive_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        encode(raw, target["format"], dst + ".part", entry)
        os.replace(dst + ".part", dst)
        return dst, os.path.getsize(dst)
    tmp = raw + "." + target["format"]
    encode(raw, target["format"], tmp, entry)
    try:
        size = os.path.getsize(tmp)
        ctx.s3_put(ctx.connection(target["connection"]), rel, tmp)
    finally:
        os.remove(tmp)
    return f"s3://{ctx.connection(target['connection'])['bucket']}/{rel}", size


def archive_app(ctx, cfg, index, app):
    """Archive one app's logs of one day to every destination that doesn't have them yet. Returns the documents
    archived (0 when there is nothing to archive)."""
    eff = effective(cfg, app)
    done = set(ctx.state.setdefault("done", {}).setdefault(index, {}).setdefault(app, []))
    todo = [t for t in eff["targets"] if t not in done]
    if not todo:
        return 0
    query = and_query(app_query(app), filters_query(eff["filters"]))
    raw = os.path.join(ctx.tmp, f"{index}-{safe(app)}.ndjson")
    try:
        n = export(ctx.api, index, query, raw)
        for t in todo:
            if n:
                where, size = deliver(ctx, t, cfg["targets"][t], raw, index, app)
                sent = ctx.state.setdefault("sent", {}).setdefault(t, {"files": 0, "bytes": 0, "logs": 0})
                sent["files"] += 1; sent["bytes"] += size; sent["logs"] += n  # noqa: E702 (Usage: what went where, S3 too)
                ctx.log("archived", f"{index} {app}: {n} logs to {t} ({where})")
            ctx.state["done"][index][app].append(t)
            ctx.save_state()
        return n
    finally:
        if os.path.exists(raw):
            os.remove(raw)


def drop_logs(ctx, cfg, index, apps, present, why):
    """Archive then delete these apps' logs of one index (present = every app in it; all of them -> the whole index)."""
    for app in apps:
        archive_app(ctx, cfg, index, app)
    if set(apps) >= set(present):
        ctx.api("DELETE", "/" + index)
        ctx.state.get("done", {}).pop(index, None)
        ctx.log("deleted", f"{index} ({why})")
    else:
        q = {"bool": {"should": [app_query(a) for a in apps], "minimum_should_match": 1}}
        r = ctx.api("POST", f"/{index}/_delete_by_query?refresh=true&conflicts=proceed", {"query": q})
        ctx.api("POST", f"/{index}/_forcemerge?only_expunge_deletes=true")  # give the space back now
        ctx.log("deleted", f"{index}: {r.get('deleted', 0)} logs of {', '.join(sorted(apps))} ({why})")
    ctx.save_state()


def archive_files(ctx, cfg):
    """[[mtime, bytes, path, destination]] of every disk-folder destination, oldest first."""
    out = []
    for name, t in cfg["targets"].items():
        if t["type"] != "local":
            continue
        for d, _, fs in os.walk(os.path.join(ctx.archive_root, t["folder"])):
            for f in fs:
                if not f.endswith(".part"):
                    p = os.path.join(d, f)
                    st = os.stat(p)
                    out.append([st.st_mtime, st.st_size, p, name])
    return sorted(out)


def archive_disk(ctx):
    """Use of the disk the archive is on (not OpenSearch's): (percent used, bytes free)."""
    os.makedirs(ctx.archive_root, exist_ok=True)
    u = shutil.disk_usage(ctx.archive_root)
    return 100 * u.used / u.total, u.free


def trim_archive(ctx, cfg):
    """All disk folders together: archive.max_gb and archive.disk_max_percent (0 = off), oldest files first.
    Returns the archive's space: bytes, files, disk percent and free bytes."""
    lim = cfg.get("archive") or {}
    cap, pct = (lim.get("max_gb") or 0) * GB, lim.get("disk_max_percent") or 0
    files = archive_files(ctx, cfg)
    total = sum(f[1] for f in files)
    used, free = archive_disk(ctx)
    while files and ((cap and total > cap) or (pct and used > pct)):
        f = files.pop(0)
        why = f"archive {total / GB:.1f} GB > {cap / GB:g} GB" if cap and total > cap else f"archive disk {used:.0f}% > {pct}%"
        os.remove(f[2])
        total -= f[1]
        ctx.log("cleaned", f"{f[3]}: {os.path.relpath(f[2], ctx.archive_root)} ({why})")
        used, free = archive_disk(ctx)
    if pct and used > pct:
        ctx.log("warning", f"archive disk {used:.0f}% > {pct}% with no archive files left: something else fills it")
    for name, t in cfg["targets"].items():  # empty day folders
        if t["type"] == "local":
            root = os.path.join(ctx.archive_root, t["folder"])
            for d, sub, fs in sorted(os.walk(root), reverse=True):
                if d != root and not sub and not fs:
                    os.rmdir(d)
    return {"bytes": total, "files": len(files), "disk_percent": used, "free_bytes": free}


def trim_local(ctx, name, target, now):
    """A local destination's own retention (days, by file time) and size limit (GB, oldest files first)."""
    root = os.path.join(ctx.archive_root, target.get("folder", ""))
    files = []
    for d, _, fs in os.walk(root):
        for f in fs:
            if not f.endswith(".part"):
                p = os.path.join(d, f)
                st = os.stat(p)
                files.append([st.st_mtime, st.st_size, p])
    files.sort()
    days, cap = target.get("retention_days") or 0, (target.get("max_gb") or 0) * 1024 ** 3
    total = sum(f[1] for f in files)
    for f in list(files):
        if (days and now - f[0] > days * 86400) or (cap and total > cap):
            os.remove(f[2])
            total -= f[1]
            files.remove(f)
            ctx.log("cleaned", f"{name}: {os.path.relpath(f[2], ctx.archive_root)}")
    for d, sub, fs in sorted(os.walk(root), reverse=True):  # empty day folders
        if d != root and not sub and not fs:
            os.rmdir(d)
    return {"files": len(files), "bytes": total}


def run_pass(ctx, cfg):
    today = datetime.datetime.fromtimestamp(ctx.now(), datetime.timezone.utc).date()  # indices are named by UTC day
    left = managed(ctx.api, today)
    for day, kind, index in list(left):
        age = (today - day).days
        if kind == "trace":
            if age > cfg["traces"]["retention_days"]:
                ctx.api("DELETE", "/" + index)
                ctx.log("deleted", f"{index} (traces older than {cfg['traces']['retention_days']} days)")
                left.remove((day, kind, index))
            continue
        present = apps_in(ctx.api, index)
        due = [a for a in present if age > effective(cfg, a)["retention_days"]]
        if due:
            drop_logs(ctx, cfg, index, due, present, f"older than retention ({age} days)")
            if set(due) >= set(present):
                left.remove((day, kind, index))
    cap = (cfg["logs"].get("max_gb") or 0) * GB  # all logs together
    while cap and (total := sum(b for b, _ in sizes(ctx.api).values())) > cap:
        logs_left = [x for x in left if x[1] == "log"]
        if not logs_left:
            ctx.log("warning", f"logs {total / GB:.1f} GB > {cap / GB:g} GB but only today's indices are left")
            break
        day, kind, index = logs_left[0]
        left.remove(logs_left[0])
        present = apps_in(ctx.api, index)
        drop_logs(ctx, cfg, index, list(present), present, f"logs {total / GB:.1f} GB > {cap / GB:g} GB")
    capped = {a: own["max_gb"] for a, own in cfg.get("apps", {}).items() if own.get("max_gb")}
    for app, gb in sorted(capped.items()):  # one app's logs, across its days
        while True:
            sz, days = sizes(ctx.api), []
            for d, kind, index in left:
                if kind == "log" and index in sz:
                    n = apps_in(ctx.api, index).get(app, 0)
                    if n:
                        days.append((index, app_bytes(*sz[index], n)))
            today_part = sum(app_bytes(b, n, apps_in(ctx.api, i).get(app, 0)) for i, (b, n) in sz.items()
                             if day_of(i) and day_of(i) >= today)
            total = sum(b for _, b in days) + today_part
            if total <= gb * GB:
                break
            if not days:
                ctx.log("warning", f"{app}: {total / GB:.1f} GB > {gb:g} GB but only today's logs are left")
                break
            index = days[0][0]
            present = apps_in(ctx.api, index)
            drop_logs(ctx, cfg, index, [app], present, f"{app} {total / GB:.1f} GB > {gb:g} GB")
            if set(present) <= {app}:
                left = [x for x in left if x[2] != index]
    limit = cfg["logs"]["disk_max_percent"]
    while (used := disk_percent(ctx.api)) > limit:
        if not left:
            ctx.log("warning", f"disk {used:.0f}% > {limit}% but only today's indices are left")
            break
        day, kind, index = left.pop(0)
        why = f"disk {used:.0f}% > {limit}%"
        if kind == "trace":
            ctx.api("DELETE", "/" + index)
            ctx.log("deleted", f"{index} ({why})")
        else:
            present = apps_in(ctx.api, index)
            drop_logs(ctx, cfg, index, list(present), present, why)
    usage = {n: trim_local(ctx, n, t, ctx.now()) for n, t in cfg["targets"].items() if t["type"] == "local"}
    archive = trim_archive(ctx, cfg)
    if archive["files"] != sum(u["files"] for u in usage.values()):  # the global limit removed files: recount
        usage = {n: trim_local(ctx, n, t, ctx.now()) for n, t in cfg["targets"].items() if t["type"] == "local"}
    logs = sum(b for b, _ in sizes(ctx.api).values())
    return {"targets": usage, "archive": archive, "logs_bytes": logs}
