"""Log retention for OpenSearch, one pass every LOG_ARCHIVE_INTERVAL seconds:
- log indices (mule-logs-*, logstash-*) older than LOGS_RETENTION_DAYS, and the oldest ones while OpenSearch's disk
  is above LOGS_DISK_MAX_PERCENT, are exported to /archive/<index>.ndjson.gz (one _source per line), then deleted;
- trace indices (jaeger-span-*, jaeger-service-*) older than JAEGER_RETENTION_DAYS are deleted (no archive);
- with LOG_ARCHIVE_S3_BUCKET set, archives are uploaded to S3 and removed locally once uploaded.
Today's indices are never touched, and a log index is only deleted after its archive is complete. Stdlib only."""
import base64, datetime, glob, gzip, hashlib, hmac, json, os, re, ssl, time, urllib.parse, urllib.request

OS = os.environ.get("OPENSEARCH_URL", "https://opensearch:9200")
AUTH = "Basic " + base64.b64encode(f"admin:{os.environ.get('OPENSEARCH_PASSWORD', '')}".encode()).decode()
ARCHIVE = os.environ.get("ARCHIVE_DIR", "/archive")
LOG_DAYS = int(os.environ.get("LOGS_RETENTION_DAYS", "365"))
TRACE_DAYS = int(os.environ.get("JAEGER_RETENTION_DAYS", "30"))
DISK_MAX = float(os.environ.get("LOGS_DISK_MAX_PERCENT", "80"))  # below OpenSearch's 85% low watermark
INTERVAL = int(os.environ.get("LOG_ARCHIVE_INTERVAL", "300"))
S3 = {k: os.environ.get(f"LOG_ARCHIVE_S3_{k}", "") for k in ("BUCKET", "REGION", "ENDPOINT", "PREFIX", "ACCESS_KEY", "SECRET_KEY")}
HEARTBEAT = "/tmp/heartbeat"
LOGS, TRACES = ("mule-logs-", "logstash-"), ("jaeger-span-", "jaeger-service-")
DAY = re.compile(r"(\d{4})[.-](\d{2})[.-](\d{2})$")  # mule-logs-2026.10.29, jaeger-span-2026-10-29
CTX = ssl.create_default_context()  # OpenSearch has a per-install self-signed node cert (Fluent Bit and Jaeger skip it too)
CTX.check_hostname, CTX.verify_mode = False, ssl.CERT_NONE


def log(msg):
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def api(method, path, body=None):
    req = urllib.request.Request(OS + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=CTX, timeout=300) as r:
        return json.load(r)


def managed(names, today):
    """Indices this service may delete, oldest first: [(day, archive?, name)]. Today's and undated ones are left alone."""
    out = []
    for n in names:
        m = DAY.search(n)
        if m and n.startswith(LOGS + TRACES):
            d = datetime.date(*map(int, m.groups()))
            if d < today:
                out.append((d, n.startswith(LOGS), n))
    return sorted(out)  # same day: traces (not archived) go before logs


def expired(candidates, today):
    return [c for c in candidates if (today - c[0]).days > (LOG_DAYS if c[1] else TRACE_DAYS)]


def disk_percent():
    nodes = api("GET", "/_nodes/stats/fs")["nodes"].values()
    return max(100 * (1 - n["fs"]["total"]["available_in_bytes"] / n["fs"]["total"]["total_in_bytes"]) for n in nodes)


def archive(index):
    path = os.path.join(ARCHIVE, index + ".ndjson.gz")
    if os.path.exists(path):  # an earlier pass archived it and then failed to delete the index
        return
    want, n, part = api("GET", f"/{index}/_count")["count"], 0, path + ".part"
    r = api("POST", f"/{index}/_search?scroll=5m", {"size": 5000, "sort": ["_doc"]})
    try:
        with gzip.open(part, "wt", encoding="utf-8") as f:
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
        os.remove(part)
        raise RuntimeError(f"{index}: exported {n} of {want} documents, index kept")
    os.replace(part, path)
    log(f"archived {index}: {n} documents, {os.path.getsize(path)} bytes")


def drop(index, is_log, why):
    if is_log:
        archive(index)
    api("DELETE", "/" + index)
    log(f"deleted {index} ({why})")


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


def upload(path):
    # ponytail: one PUT, so at most 5 GB per archive (one day of logs); multipart upload if a day ever gets bigger
    key = "/".join(p for p in (S3["PREFIX"].strip("/"), os.path.basename(path)) if p)
    region = S3["REGION"] or "us-east-1"
    if S3["ENDPOINT"]:  # S3-compatible store (MinIO, ...): path-style
        u = urllib.parse.urlsplit(S3["ENDPOINT"])
        host, base, p = u.netloc, f"{u.scheme}://{u.netloc}", f"/{S3['BUCKET']}/{key}"
    else:
        host = f"{S3['BUCKET']}.s3.{region}.amazonaws.com"
        base, p = "https://" + host, "/" + key
    amz = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h = sigv4("PUT", host, p, amz, "UNSIGNED-PAYLOAD", region, S3["ACCESS_KEY"], S3["SECRET_KEY"],
              extra={"x-amz-content-sha256": "UNSIGNED-PAYLOAD"})
    h.pop("host")  # urllib sends the same Host
    with open(path, "rb") as f:
        req = urllib.request.Request(base + urllib.parse.quote(p), data=f, method="PUT",
                                     headers={**h, "Content-Length": str(os.path.getsize(path))})
        urllib.request.urlopen(req, timeout=900).close()
    os.remove(path)
    log(f"uploaded {os.path.basename(path)} to s3://{S3['BUCKET']}/{key}")


def run_pass():
    today = datetime.datetime.now(datetime.timezone.utc).date()  # Fluent Bit and Jaeger name indices by UTC day
    names = [i["index"] for i in api("GET", "/_cat/indices/" + ",".join(p + "*" for p in LOGS + TRACES) + "?format=json&h=index")]
    open(HEARTBEAT, "w").close()  # OpenSearch answers and the loop runs (the healthcheck reads its age)
    left = managed(names, today)
    for c in expired(left, today):
        drop(c[2], c[1], f"older than {LOG_DAYS if c[1] else TRACE_DAYS} days")
        left.remove(c)
    while (used := disk_percent()) > DISK_MAX:
        if not left:
            log(f"disk {used:.0f}% > {DISK_MAX:.0f}% but only today's indices are left")
            break
        c = left.pop(0)
        drop(c[2], c[1], f"disk {used:.0f}% > {DISK_MAX:.0f}%")
    if S3["BUCKET"]:
        for path in sorted(glob.glob(os.path.join(ARCHIVE, "*.ndjson.gz"))):
            upload(path)


if __name__ == "__main__":
    os.makedirs(ARCHIVE, exist_ok=True)
    log(f"logs {LOG_DAYS} days (archived to {ARCHIVE}{', s3://' + S3['BUCKET'] if S3['BUCKET'] else ''}), "
        f"traces {TRACE_DAYS} days, disk limit {DISK_MAX:.0f}%, every {INTERVAL}s")
    while True:
        try:
            run_pass()
        except Exception as e:  # logged, retried next pass; an index whose archive failed stays
            log(f"ERROR {type(e).__name__}: {e}")
        time.sleep(INTERVAL)
