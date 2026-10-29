"""CE Runtime Manager - CloudHub-style deployment of Mule apps onto runtime pools.

A runtime pool is a named Mule runtime (Mule version, Java, heap, JVM options, replicas) run as
containers mule-<pool>-<n> that this service creates through the Docker API (see pools.py). An app
runs on every worker of its pool; Mule hot-deploys the jar we copy into $MULE_HOME/apps and reads the
app's properties from .mule/<app>/deployment-properties (written first, so a restart applies them).
  /data/pools.json                pool specs (desired state)
  /data/artifacts/<app>.jar       last deployed artifact (re-placed on new/replaced workers)
  /data/artifacts/<app>.json      app state: pool, source (Maven coords), updates, properties
  /data/tokens.json, settings.json  API tokens (hashed), update-check interval
  /data/nodes.json                other servers running the node agent (token encrypted), worker ports
  $MAVEN_SETTINGS                 repos, credentials, mirrors for Maven-sourced apps
  $APISIX_FILE                    per-app routes + per-pool upstream nodes in generated blocks
Sign-in: Keycloak (OIDC code flow + PKCE, realm role RM_OIDC_ROLE) when RM_OIDC_URL/SECRET are set;
Basic RM_USER/RM_PASSWORD and API tokens (Bearer) for scripts and pipelines.
Overview: Jaeger traces + OpenSearch logs.
"""
import base64
import hashlib
import hmac
import http.cookies
import json
import os
import re
import secrets
import shutil
import signal
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse

import pools

DATA = os.environ.get("DATA_DIR", "/data")
ARTIFACTS = os.path.join(DATA, "artifacts")
APISIX_FILE = os.environ.get("APISIX_FILE", "")
PLUGIN_CONFIG_ID = os.environ.get("RM_ROUTE_PLUGIN_CONFIG", "")
REPO_PROTOCOL = os.environ.get("ATINA_REPOSITORY_PROTOCOL", "https")
REPO_URL = os.environ.get("ATINA_REPOSITORY_URL", "")
MAVEN_SETTINGS = os.environ.get("MAVEN_SETTINGS", "")
POLL_SECONDS = int(os.environ.get("RM_MAVEN_POLL_SECONDS", "300"))  # default update-check interval; UI can change it
CLASSIFIER = "mule-application"
MOVING = ("LATEST", "RELEASE")
UPDATE_MODES = ("auto", "notify", "off")
# Default app and default pool, from the root .env
SEED = tuple(os.environ.get(f"MULEAPP_{k}", "") for k in ("GROUP_ID", "ARTIFACT_ID", "VERSION"))
DEFAULT_POOL = {"mule_version": os.environ.get("MULE_VERSION", "4.12.0"), "java_version": os.environ.get("MULE_JAVA_VERSION", "17"),
                "heap_mb": int(os.environ.get("RM_DEFAULT_POOL_HEAP_MB", "1024")),
                "replicas": int(os.environ.get("RM_DEFAULT_POOL_REPLICAS", "2")), "jvm_options": []}
USER = os.environ.get("RM_USER", "admin")
PASSWORD = os.environ.get("RM_PASSWORD", "")
SECRETS_KEY = os.environ.get("RM_SECRETS_KEY", "")
MAX_JAR = 512 * 1024 * 1024
# Keycloak: RM_OIDC_URL is the realm as this container reaches it (token exchange), RM_OIDC_PUBLIC_URL
# the same realm as the browser reaches it (login/logout redirects), RM_PUBLIC_URL this UI for the browser.
OIDC_URL = os.environ.get("RM_OIDC_URL", "").rstrip("/")
OIDC_PUBLIC = os.environ.get("RM_OIDC_PUBLIC_URL", OIDC_URL).rstrip("/")
OIDC_CLIENT = os.environ.get("RM_OIDC_CLIENT_ID", "runtime-manager")
OIDC_SECRET = os.environ.get("RM_OIDC_CLIENT_SECRET", "")
OIDC_ROLE = os.environ.get("RM_OIDC_ROLE", "admin")
PUBLIC_URL = os.environ.get("RM_PUBLIC_URL", "https://localhost:9443/runtime-manager").rstrip("/")
PLATFORM_PREFIXES = {"runtime-manager", "auth", "opensearch", "dashboards", "jaeger", "prometheus", "grafana",
                     "alertmanager", "activemq", "otlp", "sso", "logout"}
HOME = urlparse(PUBLIC_URL).path + "/"  # where the UI lives for the browser, e.g. /runtime-manager/
OIDC = bool(OIDC_URL and OIDC_SECRET) and os.environ.get("GATEWAY_AUTH", "on") != "off"  # off = no Keycloak
SESSION_SECONDS = 8 * 3600
# ponytail: sessions live in memory, a restart signs everyone out; a file/redis store if that matters
SESSIONS, PENDING = {}, {}  # session id -> user; login state -> (pkce verifier, created)
JAEGER_URL = os.environ.get("RM_JAEGER_URL", "").rstrip("/")            # e.g. http://jaeger:16686/jaeger
JAEGER_PUBLIC = os.environ.get("RM_JAEGER_PUBLIC_URL", "").rstrip("/")  # trace links for the browser
OS_URL = os.environ.get("RM_OPENSEARCH_URL", "").rstrip("/")
OS_AUTH = (os.environ.get("OPENSEARCH_USER", "admin"), os.environ.get("OPENSEARCH_PASSWORD", "admin"))
NODE_PORT_BASE = int(os.environ.get("RM_NODE_PORT_BASE", "18000"))  # remote workers: 10 ports each from here
PLATFORM_CA = os.environ.get("RM_PLATFORM_CA", "/platform-ca/ca.crt")    # remote workers trust the gateway with it
OTLP_TOKEN = os.environ.get("OTLP_INGEST_TOKEN", "")                     # remote workers send traces via /otlp
TRACE_LIMIT = 1500  # ponytail: overview samples the newest 1500 traces per window; Jaeger SPM/metrics past that
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PROP_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,200}$")
# ponytail: one global lock for deploys and pool changes; fine for a handful of operators and pipelines
LOCK = threading.Lock()
BEGIN, END = "  # BEGIN runtime-manager (generated, do not edit)", "  # END runtime-manager"


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, data):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(path + ".tmp", path)  # atomic: a crash never leaves half a file


# ---------- Maven (repos, credentials, mirrors from settings.xml) ----------

def _xml(data):
    root = ET.fromstring(data)
    for el in root.iter():
        el.tag = el.tag.rsplit("}", 1)[-1]  # settings.xml is namespaced, metadata usually not
    return root


def _env(s):
    return re.sub(r"\$\{env\.(\w+)\}", lambda m: os.environ.get(m.group(1), ""), (s or "").strip())


def maven_repos():
    """Repos to search, in order: ATINA_REPOSITORY_URL, then the active profiles of settings.xml.
    Mirrors and <servers> credentials are applied the way Maven does."""
    repos = []
    if REPO_URL:
        url = REPO_URL if "://" in REPO_URL else f"{REPO_PROTOCOL}://{REPO_URL}"
        repos.append({"id": "atina", "url": url, "releases": True, "snapshots": True})
    servers, mirrors = {}, []
    if MAVEN_SETTINGS and os.path.exists(MAVEN_SETTINGS):
        root = _xml(open(MAVEN_SETTINGS, "rb").read())
        servers = {s.findtext("id"): (_env(s.findtext("username")), _env(s.findtext("password")))
                   for s in root.findall("servers/server")}
        mirrors = [(m.findtext("mirrorOf") or "", m.findtext("id"), _env(m.findtext("url")))
                   for m in root.findall("mirrors/mirror")]
        active = {a.text.strip() for a in root.findall("activeProfiles/activeProfile")}
        profiles = root.findall("profiles/profile")
        chosen = [p for p in profiles if p.findtext("id") in active] or \
                 [p for p in profiles if p.findtext("activation/activeByDefault") == "true"]
        for p in chosen:
            for r in p.findall("repositories/repository"):
                repos.append({"id": r.findtext("id"), "url": _env(r.findtext("url")),
                              "releases": (r.findtext("releases/enabled") or "true").strip() == "true",
                              "snapshots": (r.findtext("snapshots/enabled") or "true").strip() == "true"})
    # ponytail: mirrorOf handles "*", "external:*", "a,b" and "!id"; <proxies> are not supported
    for r in repos:
        for spec, mid, murl in mirrors:
            ids = [x.strip() for x in spec.split(",")]
            if f"!{r['id']}" not in ids and ({"*", "external:*", r["id"]} & set(ids)):
                r["id"], r["url"] = mid, murl
                break
        r["auth"] = servers.get(r["id"])
    out = {}
    for r in repos:
        # plain http (except loopback) is dropped: a jar fetched over it could be swapped in transit and deployed
        if not _trusted_url(r["url"]):
            continue
        if r["url"] not in out or (r.get("auth") and not out[r["url"]].get("auth")):  # same URL: keep the credentials
            out[r["url"]] = r
    return list(out.values())


def _trusted_url(url):
    u = urlparse(url)
    return u.scheme == "https" or u.hostname in ("localhost", "127.0.0.1")


def _open(repo, path, method="GET"):
    req = urllib.request.Request(repo["url"].rstrip("/") + "/" + path, method=method)
    if repo.get("auth") and _trusted_url(repo["url"]):  # never in cleartext
        # unredirected: urllib would otherwise resend the credentials to whatever host a redirect points at
        req.add_unredirected_header("Authorization", "Basic " + base64.b64encode(":".join(repo["auth"]).encode()).decode())
    return urllib.request.urlopen(req, timeout=120)


def resolve(group, artifact, version):
    """Find the Mule app jar for group:artifact:version. version may be a release, x-SNAPSHOT,
    LATEST or RELEASE. Returns {version, build, repo, path}; build is the exact file version
    (timestamped for snapshots) and is what we compare to detect a new build."""
    if not (group and artifact and version):
        raise ValueError("group, artifact and version are required")
    base = f"{group.replace('.', '/')}/{artifact}"
    errors = []
    # ponytail: first repo that has the artifact wins (no cross-repo metadata merge); fine with one Artifactory
    for repo in maven_repos():
        try:
            v = version
            if v in MOVING:
                with _open(repo, f"{base}/maven-metadata.xml") as r:
                    meta = _xml(r.read())
                v = meta.findtext(f"versioning/{v.lower()}") or [e.text for e in meta.findall("versioning/versions/version")][-1]
            snapshot = v.endswith("-SNAPSHOT")
            if not repo["snapshots" if snapshot else "releases"]:
                continue
            build = v
            if snapshot:
                try:
                    with _open(repo, f"{base}/{v}/maven-metadata.xml") as r:
                        meta = _xml(r.read())
                    vals = [s.findtext("value") for s in meta.findall("versioning/snapshotVersions/snapshotVersion")
                            if s.findtext("classifier") == CLASSIFIER and s.findtext("extension") == "jar"]
                    ts = meta.findtext("versioning/snapshot/timestamp")
                    num = meta.findtext("versioning/snapshot/buildNumber")
                    build = vals[0] if vals else (f"{v[:-len('SNAPSHOT')]}{ts}-{num}" if ts else v)
                except urllib.error.HTTPError as e:
                    if e.code != 404:
                        raise  # 404 = non-unique snapshot: file is <artifact>-<v>-mule-application.jar
            path = f"{base}/{v}/{artifact}-{build}-{CLASSIFIER}.jar"
            try:
                _open(repo, path, "HEAD").close()
            except urllib.error.HTTPError as e:
                if e.code != 405:
                    raise
                _open(repo, path).close()  # some repos refuse HEAD: confirm with GET (body not read)
            return {"version": v, "build": build, "repo": repo, "path": path}
        except (urllib.error.URLError, ET.ParseError, IndexError, OSError) as e:
            errors.append(f"{repo['id']}: {e}")
    raise LookupError(f"{group}:{artifact}:{version} not found in any repository "
                      f"({'; '.join(errors) or 'no repositories configured'})")


def newest_release(group, artifact):
    for repo in maven_repos():
        try:
            with _open(repo, f"{group.replace('.', '/')}/{artifact}/maven-metadata.xml") as r:
                return _xml(r.read()).findtext("versioning/release")
        except (urllib.error.URLError, ET.ParseError, OSError):
            continue
    return None


def download(info, dest):
    with _open(info["repo"], info["path"]) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def check_jar(path):
    with open(path, "rb") as f:
        if f.read(2) != b"PK":
            raise ValueError("not a jar/zip file")


def fetch_jar(name, info):
    dest = os.path.join(ARTIFACTS, f"{name}.jar")
    tmp = dest + ".download"
    try:
        download(info, tmp)
        check_jar(tmp)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def load_meta(name):
    try:
        with open(os.path.join(ARTIFACTS, f"{name}.json"), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_meta(name, meta):
    path = os.path.join(ARTIFACTS, f"{name}.json")
    if not meta:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(meta, f)
    os.replace(path + ".tmp", path)


# ---------- secure properties (encrypted at rest, never returned by the API) ----------

def _fernet():
    if not SECRETS_KEY:
        raise ValueError("secure properties need RM_SECRETS_KEY in the root .env")
    from cryptography.fernet import Fernet  # the one non-stdlib dependency: real crypto for secrets
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRETS_KEY.encode()).digest()))


def encrypt(value):
    return _fernet().encrypt(str(value).encode()).decode()


def decrypt(token):
    return _fernet().decrypt(token.encode()).decode()


def app_properties(m):
    """What Mule gets: plain properties + decrypted secure ones (secure wins on a clash)."""
    props = dict(m.get("properties") or {})
    props.update({k: decrypt(v) for k, v in (m.get("secure") or {}).items()})
    return props


def merge_properties(m, body):
    """body: {"properties": {k: v}, "secureProperties": {k: v | null}} - each map, when given, replaces
    that set; a null secure value keeps the stored one (the UI never sees secure values)."""
    if "properties" in body:
        props = {str(k): str(v) for k, v in (body["properties"] or {}).items()}
        m["properties"] = props
    if "secureProperties" in body:
        old, new = m.get("secure") or {}, {}
        for k, v in (body["secureProperties"] or {}).items():
            if v is None:
                if k not in old:
                    raise ValueError(f"secure property {k} has no stored value")
                new[k] = old[k]
            else:
                new[k] = encrypt(v)
        m["secure"] = new
    bad = [k for k in list(m.get("properties", {})) + list(m.get("secure", {})) if not PROP_KEY_RE.match(k)]
    if bad:
        raise ValueError(f"invalid property name(s) {bad}: letters, digits, '.', '_' and '-'")
    return m


# ---------- settings and API tokens ----------

def settings():
    return {"check_minutes": max(0, POLL_SECONDS // 60), **read_json(os.path.join(DATA, "settings.json"), {})}


def token_list():
    return read_json(os.path.join(DATA, "tokens.json"), [])


def create_token(name):
    """Returns the token once; only its SHA-256 is stored."""
    raw = "rm_" + secrets.token_urlsafe(32)
    tokens = token_list()
    tokens.append({"id": secrets.token_hex(6), "name": name, "hash": hashlib.sha256(raw.encode()).hexdigest(),
                   "created": now(), "last_used": None})
    write_json(os.path.join(DATA, "tokens.json"), tokens)
    return raw, tokens[-1]


def token_user(raw):
    h = hashlib.sha256(raw.encode()).hexdigest()
    tokens = token_list()
    for t in tokens:
        if hmac.compare_digest(t["hash"], h):
            if (t.get("last_used") or "")[:16] != now()[:16]:  # at most one write a minute
                t["last_used"] = now()
                write_json(os.path.join(DATA, "tokens.json"), tokens)
            return {"user": f"token:{t['name']}", "name": t["name"], "auth": "token"}
    return None


# ---------- nodes (other servers running node/ agent) ----------

NODE_STATUS = {}  # node -> {"ok": bool, "error": str|None, "info": {...}, "checked": ts, "at": epoch}
NODE_TIMEOUT = 5     # seconds per call when listing a node (a dead node must not stall the UI/API)
NODE_RETRY = 30      # a node that just failed is skipped this long, then tried again


def node_down(name):
    st = NODE_STATUS.get(name) or {}
    return st.get("ok") is False and time.time() - st.get("at", 0) < NODE_RETRY


def mark_node(name, ok, error=None, info=None):
    prev = NODE_STATUS.get(name) or {}
    NODE_STATUS[name] = {"ok": ok, "error": error, "info": info or prev.get("info"), "checked": now(), "at": time.time()}


def load_nodes():
    return read_json(os.path.join(DATA, "nodes.json"), {})


def save_nodes(n):
    write_json(os.path.join(DATA, "nodes.json"), n)


def node_conn(name):
    """None = the local Docker; else what pools.docker() needs to reach that node's agent."""
    if name in (None, pools.LOCAL):
        return None
    n = load_nodes().get(name)
    if not n:
        raise LookupError(f"node {name!r} is not registered")
    return {"name": name, "address": n["address"], "fingerprint": n["fingerprint"], "token": decrypt(n["token"])}


def check_node(name):
    if not node_down(name):
        try:
            mark_node(name, True, info=pools.node_info(node_conn(name), timeout=NODE_TIMEOUT))
        except Exception as e:
            mark_node(name, False, error=str(e))
    return NODE_STATUS[name]


def all_containers(pool=None):
    """Workers on the local Docker and on every node ([{..., "node"}]). An unreachable node is skipped
    (its error shows on the Nodes page); remembers worker -> node for the per-worker calls."""
    out = [dict(c, node=pools.LOCAL) for c in pools.containers(pool)]
    local = {c["name"] for c in out}
    for n in local:  # found locally: drop a stale node mapping (it would send this worker's calls to a node)
        pools.WORKER_NODE.pop(n, None)
    for name in load_nodes():
        if node_down(name):
            continue
        try:
            conn = node_conn(name)
            cs = pools.containers(pool, node=conn, timeout=NODE_TIMEOUT)
            if not (NODE_STATUS.get(name) or {}).get("ok"):
                mark_node(name, True)
        except Exception as e:
            mark_node(name, False, error=str(e))
            continue
        for c in cs:
            if c["name"] in local:  # a node on this same Docker also lists the local workers: they stay local
                continue
            pools.WORKER_NODE[c["name"]] = conn
            out.append(dict(c, node=name))
    return out


def remote_cfg(node, worker):
    """Port block + gateway settings for a worker on a node (ports allocated once per worker, kept)."""
    nodes = load_nodes()
    ports = nodes[node].setdefault("ports", {})
    if worker not in ports:
        used, port = set(ports.values()), NODE_PORT_BASE
        while port in used:
            port += pools.NODE_PORTS
        if port + pools.NODE_PORTS > NODE_PORT_BASE + 1000:  # install-node.sh firewalls exactly base..base+999
            raise ValueError(f"node {node} is full: 100 workers max (ports {NODE_PORT_BASE}-{NODE_PORT_BASE + 999})")
        ports[worker] = port
        save_nodes(nodes)
    ca = open(PLATFORM_CA, encoding="ascii").read() if os.path.exists(PLATFORM_CA) else ""
    return {"port": ports[worker], "gateway": nodes[node]["gateway"], "ca": ca, "otlp_token": OTLP_TOKEN}


def release_port(worker):
    nodes = load_nodes()
    for n in nodes.values():
        if n.get("ports", {}).pop(worker, None) is not None:
            save_nodes(nodes)
            return


def endpoint(worker, port):
    """host:port APISIX uses for an app on a worker: name:port inside, node-address:mapped port on a node."""
    for n in load_nodes().values():
        base = n.get("ports", {}).get(worker)
        if base is not None:
            if not pools.APP_PORT <= port < pools.APP_PORT + pools.NODE_PORTS:
                return None  # only 8081..8090 are published on nodes
            return f"{urlparse(n['address']).hostname}:{base + port - pools.APP_PORT}"
    return f"{worker}:{port}"


def node_list():
    nodes, cs = load_nodes(), all_containers()
    return [{"name": n, "address": v["address"], "fingerprint": v["fingerprint"], "gateway": v["gateway"],
             "status": check_node(n) if not node_down(n) and not (NODE_STATUS.get(n) or {}).get("ok") else NODE_STATUS[n],
             "workers": [c for c in cs if c["node"] == n],
             "pools": sorted(p for p, sp in load_pools().items() if n in (sp.get("nodes") or {}))}
            for n, v in sorted(nodes.items())]


def put_node(name, body):
    if not pools.POOL_RE.match(name or "") or name == pools.LOCAL:
        raise ValueError("node name: lowercase letters, digits and dashes (max 30), not 'local'")
    nodes = load_nodes()
    old = nodes.get(name, {})
    address = str(body.get("address") or old.get("address") or "").strip().rstrip("/")
    if not re.match(r"^https://[A-Za-z0-9.\-]+(:\d+)?$", address):
        raise ValueError("address must look like https://<host>:7443 (printed by node/install-node.sh)")
    fingerprint = str(body.get("fingerprint") or old.get("fingerprint") or "").strip().lower()
    hexfp = fingerprint.removeprefix("sha256:").replace(":", "")
    if not re.match(r"^[0-9a-f]{64}$", hexfp):
        raise ValueError("fingerprint must be the sha256 printed by install-node.sh")
    fingerprint = "sha256:" + hexfp
    gateway = str(body.get("gateway") or old.get("gateway") or "").strip()
    if not re.match(r"^[A-Za-z0-9.\-]+$", gateway):
        raise ValueError("gateway: the host/IP this node's workers reach the platform's APISIX at (in its certificate)")
    token = body.get("token")
    # a new address/fingerprint needs the token again: never send the stored one to an endpoint not yet proven
    if not token and (not old or address != old["address"] or fingerprint != old["fingerprint"]):
        raise ValueError("token is required (printed by install-node.sh)")
    rec = {**old, "address": address, "fingerprint": fingerprint, "gateway": gateway,
           "token": encrypt(token) if token else old["token"]}
    conn = {"name": name, "address": address, "fingerprint": fingerprint, "token": token or decrypt(old["token"])}
    try:
        info = pools.node_info(conn)  # prove address, token and fingerprint before saving
    except Exception as e:
        raise ValueError(f"cannot reach the node agent: {e}")
    nodes[name] = rec
    save_nodes(nodes)
    NODE_STATUS[name] = {"ok": True, "error": None, "info": info, "checked": now()}
    return {k: v for k, v in rec.items() if k not in ("token", "ports")} | {"name": name, "info": info}


def delete_node(name):
    used = [p for p, sp in load_pools().items() if name in (sp.get("nodes") or {})]
    if used:
        raise ValueError(f"node {name} still runs workers of pool(s) {', '.join(used)}; move them first")
    nodes = load_nodes()
    if nodes.pop(name, None) is None:
        raise LookupError(f"no node {name}")
    save_nodes(nodes)
    NODE_STATUS.pop(name, None)


# ---------- runtime pools ----------

POOL_STATUS = {}  # pool -> {"state", "message", "since"}
_queue, _queue_cv = [], threading.Condition()


def load_pools():
    return read_json(os.path.join(DATA, "pools.json"), {})


def save_pools(p):
    write_json(os.path.join(DATA, "pools.json"), p)


def set_status(pool, state, message=""):
    POOL_STATUS[pool] = {"state": state, "message": message, "since": now()}
    print(f"pool {pool}: {state} {message}", flush=True)


def enqueue(pool):
    with _queue_cv:
        if pool not in _queue:
            _queue.append(pool)
        _queue_cv.notify()
    if POOL_STATUS.get(pool, {}).get("state") != "working":
        set_status(pool, "pending", "waiting to apply changes")


def reconcile_forever():
    while True:
        with _queue_cv:
            while not _queue:
                _queue_cv.wait()
            pool = _queue.pop(0)
        try:
            reconcile(pool)
        except Exception as e:  # shown on the pool card; "Retry" re-queues it
            set_status(pool, "error", str(e))


def running_workers(pool):
    return [c["name"] for c in all_containers(pool) if c["state"] == "running"]


def reconcile(pool):
    """Make the pool's containers match its spec, one worker at a time (rolling): replace a worker
    whose spec changed or that is not running, deploy the pool's apps on it, wait for them, next."""
    spec = load_pools().get(pool)
    existing = {c["name"]: c for c in all_containers(pool)}
    set_status(pool, "working", "checking workers")
    if spec is None:  # pool deleted
        for name in existing:
            pools.remove(name)
            release_port(name)
        POOL_STATUS.pop(pool, None)
        write_routes()
        return
    names = pools.worker_names(pool, spec)
    conns = {n: node_conn(n) for n in sorted({node for _, node in names})}  # LookupError: node not registered
    # an unreachable node is left exactly as it is (its workers may well still be serving): no rebuild,
    # no replacement; the pool is retried once the node can answer again
    down = {n for n, conn in conns.items() if conn and not check_node(n)["ok"]}
    for n, conn in conns.items():  # every node builds its own runtime image (context sent over the API)
        if n not in down:
            pools.ensure_image(spec, lambda m: set_status(pool, "working", m), node=conn)
    fresh = set()  # workers (re)created in this pass: they already got their apps
    for i, (name, node) in enumerate(names, 1):
        if node in down:
            existing.pop(name, None)
            continue
        remote = remote_cfg(node, name) if conns[node] else None
        want = pools.container_config(pool, spec, name, remote)["Labels"]["rm.spec"]
        c = existing.pop(name, None)
        if c and c["spec"] == want and c["state"] == "running" and c["node"] == node:
            continue
        if c and c["node"] != node:
            pools.remove(name)  # moved to another node
        set_status(pool, "working", f"{'replacing' if c else 'starting'} {name}{'' if node == pools.LOCAL else ' on ' + node} ({i}/{len(names)})")
        pools.create(pool, spec, name, node=conns[node], remote=remote)
        fresh.add(name)
        if not pools.wait_runtime(name):
            raise RuntimeError(f"{name}: Mule did not start within 7 minutes (see its runtime log)")
        apps = [(a, m) for a, m in all_meta() if m.get("pool") == pool and os.path.exists(jar_path(a))
                and name in app_targets(a, m)]
        set_status(pool, "working", f"deploying {len(apps)} app(s) on {name}")
        with LOCK:
            for app, m in apps:
                pools.deploy_on(name, app, read_jar(app), app_properties(m))
        end = time.time() + 300  # keep capacity during a rolling update: wait until this worker serves
        while apps and time.time() < end:
            states = pools.app_states(name)
            if all(states.get(a) in ("STARTED", "FAILED") for a, _ in apps):
                break
            time.sleep(3)
    for name in existing:  # scaled in
        set_status(pool, "working", f"removing {name}")
        pools.remove(name)
        release_port(name)
    # placement after a scale in/out: deploy only where an app is newly assigned (and not just deployed on a
    # fresh worker), undeploy where it no longer is; copies that stay put are not restarted
    for app, m in all_meta():
        if m.get("pool") != pool or not os.path.exists(jar_path(app)):
            continue
        targets, before = app_targets(app, m), m.get("placed") or []
        if targets == before:
            continue
        set_status(pool, "working", f"re-placing {app}")
        with LOCK:
            jar, props = read_jar(app), app_properties(m)
            for w in targets:
                if w not in before and w not in fresh:
                    pools.deploy_on(w, app, jar, props)
            running = set(running_workers(pool))  # removed workers took their copies with them
            for w in before:
                if w not in targets and w in running:
                    pools.undeploy_on(w, app)
            m["placed"] = targets
            save_meta(app, m)
    write_routes()
    keep = {pools.image_tag(s) for s in load_pools().values()}
    for conn in [None] + [c for c in conns.values() if c]:  # disk: drop runtime images no pool uses
        try:
            pools.prune_images(keep, node=conn)
        except Exception as e:
            print(f"image prune skipped: {e}", flush=True)
    if down:
        threading.Timer(NODE_RETRY, enqueue, [pool]).start()
    set_status(pool, "ready", f"{len(names)} worker(s) on Mule {spec['mule_version']} / Java {spec['java_version']}"
               + (f" (node {', '.join(sorted(down))} unreachable: left as is, retrying)" if down else ""))


def ensure_default_pool():
    if not load_pools():
        save_pools({"default": pools.validate("default", DEFAULT_POOL)})


def pool_list():
    specs = load_pools()
    cs = all_containers()
    apps = all_meta()
    return [{"name": n, **s, "workers": [c for c in cs if c["pool"] == n],
             "apps": sorted(a for a, m in apps if m.get("pool") == n),
             "status": POOL_STATUS.get(n, {"state": "ready", "message": "", "since": None})}
            for n, s in sorted(specs.items())]


# ---------- apps ----------

def jar_path(name):
    return os.path.join(ARTIFACTS, f"{name}.jar")


def read_jar(name):
    with open(jar_path(name), "rb") as f:
        return f.read()


def all_meta():
    return [(f[:-5], load_meta(f[:-5])) for f in sorted(os.listdir(ARTIFACTS)) if f.endswith(".json")]


def pool_workers(pool):
    spec = load_pools().get(pool)
    return [name for name, _ in pools.worker_names(pool, spec)] if spec else []


def app_targets(name, m):
    """The pool workers an app runs on. m["workers"]: unset = all of them; a count = that many, the
    least-loaded ones at first and then kept (m["placed"]) so a redeploy doesn't move the app; a list =
    exactly those workers (fine tuning)."""
    names = pool_workers(m.get("pool"))
    want = m.get("workers")
    if isinstance(want, list):
        return [w for w in names if w in want]
    if isinstance(want, int) and want < len(names):
        keep = [w for w in m.get("placed") or [] if w in names][:want]
        load = dict.fromkeys(names, 0)
        for other, om in all_meta():
            if other != name and om.get("pool") == m["pool"]:
                for w in om.get("placed") or names:
                    if w in load:
                        load[w] += 1
        extra = sorted((w for w in names if w not in keep), key=lambda w: (load[w], names.index(w)))
        return sorted(keep + extra[:want - len(keep)], key=names.index)
    return names


def parse_workers(want, pool):
    """API value -> stored value: None/"all" = all, int/"2" = count, list/"a,b" = those workers."""
    if want is None or want == "all" or want == []:
        return None
    if isinstance(want, bool):
        raise ValueError("workers must be all, a count or a list of worker names")
    if isinstance(want, int) or (isinstance(want, str) and want.isdigit()):
        if int(want) < 1:
            raise ValueError("workers count must be at least 1")
        return int(want)
    if isinstance(want, str):
        want = [w.strip() for w in want.split(",") if w.strip()]
    if not isinstance(want, list):
        raise ValueError("workers must be all, a count or a list of worker names")
    names = pool_workers(pool)
    bad = [w for w in want if w not in names]
    if bad:
        raise ValueError(f"{bad} not in pool {pool} (workers: {names})")
    return sorted(set(want), key=names.index)


_states = {}  # worker -> (time, {app: state}); ponytail: 3 s cache so the 5 s UI poll doesn't exec per request


def worker_states(worker):
    t, s = _states.get(worker, (0, {}))
    node = pools.WORKER_NODE.get(worker)
    if node and node_down(node["name"]):
        return s  # last known; no exec against a node that is down
    if time.time() - t > 3:
        try:
            s = pools.app_states(worker)
        except Exception:
            s = {}
        _states[worker] = (time.time(), s)
    return s


def list_apps():
    specs = load_pools()
    run = {}
    for c in all_containers():
        if c["state"] == "running":
            run.setdefault(c["pool"], []).append(c["name"])
    routes = read_routes()
    out = []
    for name, m in all_meta():
        targets = app_targets(name, m) if m.get("pool") in specs else []
        ws = [w for w in run.get(m.get("pool"), []) if w in targets]
        maven = {k: m.get(k) for k in ("group", "artifact", "version", "build", "available", "checked", "error", "updated")} \
            if m.get("artifact") else None
        out.append({
            "name": name, "pool": m.get("pool"),
            "runtime": {k: specs[m["pool"]][k] for k in ("mule_version", "java_version")} if m.get("pool") in specs else None,
            "workers": {w: worker_states(w).get(name, "DEPLOYING") for w in ws},
            "placement": m.get("workers"), "targets": targets,
            "route": routes.get(name), "maven": maven, "updates": m.get("updates", "notify"),
            "deployed": m.get("deployed"),
            "properties": sorted(m.get("properties") or {}), "secure": sorted(m.get("secure") or {}),
        })
    return {"pools": sorted(specs), "apps": out, "routing": bool(APISIX_FILE)}


def place(name, m):
    """Deploy (or redeploy, applying properties) the app on its workers (app_targets) and undeploy it
    everywhere else; remembers the placement. Caller holds LOCK."""
    jar, props = read_jar(name), app_properties(m)
    m["placed"] = targets = app_targets(name, m)
    save_meta(name, m)
    for c in all_containers():
        if c["state"] != "running":
            continue
        if c["name"] in targets:
            pools.deploy_on(c["name"], name, jar, props)
        else:
            pools.undeploy_on(c["name"], name)
        _states.pop(c["name"], None)


def deploy(name, body, jar=None):
    """One call for UI and pipelines. body keys (all optional on redeploy): pool, group, artifact,
    version, updates (auto|notify|off), properties, secureProperties, route {path, port} or null.
    jar: uploaded bytes (else Maven coords, else the stored jar is re-placed)."""
    if not NAME_RE.match(name):
        raise ValueError("app name must match " + NAME_RE.pattern)
    m = load_meta(name)
    pool = body.get("pool") or m.get("pool") or "default"
    if pool not in load_pools():
        raise ValueError(f"unknown pool {pool!r}; pools: {sorted(load_pools())}")
    workers = parse_workers(body["workers"], pool) if "workers" in body else m.get("workers")
    if pool != m.get("pool") and "workers" not in body and isinstance(workers, list):
        workers = None  # specific workers of the old pool mean nothing on the new one
    # only these restart the app; update mode and route alone are just saved
    restart = bool(jar is not None or body.get("artifact") or pool != m.get("pool") or workers != m.get("workers")
                   or "properties" in body or "secureProperties" in body or body.get("restart"))
    updates = body.get("updates") or m.get("updates")
    if updates and updates not in UPDATE_MODES:
        raise ValueError(f"updates must be one of {UPDATE_MODES}")
    route = None  # validated before anything is saved
    if (body.get("route") or {}).get("path"):
        r = body["route"]
        route = {"path": str(r["path"]).rstrip("/"), "port": int(r.get("port") or pools.APP_PORT)}
        if not 1 <= route["port"] <= 65535:
            raise ValueError("route port must be 1-65535")
        if not re.match(r"^/[A-Za-z0-9/_-]+$", route["path"]):
            raise ValueError("route path must look like /orders")
        if route["path"] == "/api":  # /api/* is the default app's route; /api/<name> is fine (longer match wins)
            raise ValueError("route path /api is the default app's; use /api/<name>")
        if route["path"].split("/")[1] in PLATFORM_PREFIXES:  # an app must not capture the gateway's own routes
            raise ValueError(f"route path can't start with /{route['path'].split('/')[1]} (platform route)")
    m = merge_properties(dict(m), body)
    if jar is not None:
        if jar[:2] != b"PK":
            raise ValueError("not a jar/zip file")
        tmp = jar_path(name) + ".upload"
        with open(tmp, "wb") as f:
            f.write(jar)
        os.replace(tmp, jar_path(name))
        for k in ("group", "artifact", "version", "build", "available", "checked", "error"):
            m.pop(k, None)  # uploaded by hand: nothing to track in Maven
        updates = "off"
    elif body.get("artifact"):
        info = resolve(body.get("group", ""), body["artifact"], body.get("version", ""))
        fetch_jar(name, info)
        m.update(group=body["group"], artifact=body["artifact"], version=body["version"], build=info["build"],
                 available=None, error=None)
        updates = updates or ("auto" if body["version"] in MOVING or body["version"].endswith("-SNAPSHOT") else "notify")
    elif not os.path.exists(jar_path(name)):
        raise ValueError("no jar uploaded, no Maven coordinates and nothing stored for this app")
    m.update(pool=pool, updates=updates or "notify", workers=workers)
    if restart:
        m["deployed"] = now()
    with LOCK:
        save_meta(name, m)
        if restart:
            place(name, m)
        routes = read_routes()  # always rewritten: the route's upstream follows the app's pool
        if "route" in body:
            if route:
                routes[name] = route
            else:
                routes.pop(name, None)
        write_routes(routes)
    targets = app_targets(name, m)
    return {"deployed": name, "pool": pool, "workers": [w for w in running_workers(pool) if w in targets]}


def delete_app(name):
    with LOCK:
        for c in all_containers():
            if c["state"] == "running":
                pools.undeploy_on(c["name"], name)
                _states.pop(c["name"], None)
        for p in (jar_path(name), os.path.join(ARTIFACTS, f"{name}.json")):
            if os.path.exists(p):
                os.remove(p)
        routes = read_routes()
        routes.pop(name, None)
        write_routes(routes)


# ---------- Maven updates ----------

def check_app(name, apply=None):
    """Look for a newer build (moving versions) or newer release (pinned versions). Deploys it when
    the app's update mode is auto (or apply=True). Caller holds LOCK."""
    m = load_meta(name)
    if not m.get("artifact"):
        return m
    try:
        info = resolve(m["group"], m["artifact"], m["version"])
        available = None
        if info["build"] != m.get("build"):
            available = {"version": m["version"], "build": info["build"]}
        elif m["version"] not in MOVING and not m["version"].endswith("-SNAPSHOT"):
            newest = newest_release(m["group"], m["artifact"])
            if newest and pools.vkey(newest) > pools.vkey(m["version"]):
                available = {"version": newest, "build": newest}
        m.update(available=available, error=None)
        if available and (apply if apply is not None else m.get("updates") == "auto"):
            if available["version"] != m["version"]:
                info = resolve(m["group"], m["artifact"], available["version"])
            fetch_jar(name, info)
            m.update(version=available["version"], build=info["build"], available=None, updated=now(), deployed=now())
            save_meta(name, m)
            place(name, m)
    except Exception as e:  # keep going for other apps; the error is shown in the UI
        m["error"] = str(e)
    m["checked"] = now()
    save_meta(name, m)
    return m


def seed():
    """Keep the default app MULEAPP_GROUP_ID:ARTIFACT_ID:VERSION deployed on the default pool.
    First start -> deploy it. MULEAPP_VERSION changed in .env -> that version. Same .env as last time
    -> nothing here; update checks pull new builds."""
    group, artifact, version = SEED
    if not (group and artifact and version):
        return
    name = re.sub(r"[^a-z0-9-]", "-", artifact.lower())
    if load_meta(name).get("seed") == version:
        return
    deploy(name, {"group": group, "artifact": artifact, "version": version})
    with LOCK:
        save_meta(name, {**load_meta(name), "seed": version})
    print(f"seeded {name} {version}", flush=True)


def poll_forever():
    """Seed + update check on startup, then every check_minutes (0 = only the Check button)."""
    while True:
        try:
            seed()
        except Exception as e:  # repo down at boot: retried on the next pass
            print(f"seed {':'.join(SEED)} failed: {e}", flush=True)
        for name, m in all_meta():
            if m.get("artifact") and m.get("updates", "notify") != "off":
                # ponytail: checks run under the global deploy lock; per-app locks if repos get slow
                with LOCK:
                    check_app(name)
        minutes = settings()["check_minutes"]
        time.sleep(minutes * 60 if minutes > 0 else 60)
        while settings()["check_minutes"] <= 0:  # checks paused: look again in a minute
            time.sleep(60)


# ---------- APISIX standalone routes (generated blocks inside apisix.yaml) ----------
# Per-app routes: block YAML inside the BEGIN/END block under routes: (APISIX's tinyyaml can't parse nested
# flow-style JSON), each preceded by a "# rm-route {json}" comment that is our own record of the route.
# Pool nodes: any upstream may hold "# BEGIN runtime-manager pool <name>" ... "# END ..." in its nodes:,
# which is rewritten with that pool's workers (the /api/* upstream follows the default pool).

def read_routes():
    if not APISIX_FILE:
        return {}
    text = open(APISIX_FILE, encoding="utf-8").read()
    if BEGIN not in text:
        return {}
    block = text.split(BEGIN, 1)[1].split(END, 1)[0]
    routes = {}
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("# rm-route "):
            r = json.loads(line[len("# rm-route "):])
            routes[r["app"]] = {"path": r["path"], "port": r["port"]}
    return routes


def nodes_of(workers, port=pools.APP_PORT):
    return {e: 100 for e in (endpoint(w, port) for w in workers) if e}


def route_yaml(name, r, workers):
    q = json.dumps  # a JSON string is a valid double-quoted YAML scalar
    lines = [f"  # rm-route {json.dumps({'app': name, 'path': r['path'], 'port': r['port']})}",
             f"  - id: {q('rm-' + name)}", f"    name: {q('rm-' + name)}", f"    uri: {q(r['path'] + '/*')}",
             "    upstream:", "      type: roundrobin", "      scheme: http", "      nodes:"]
    lines += [f"        {q(n)}: {w}" for n, w in nodes_of(workers, r["port"]).items()]
    # strip the route prefix: /orders/api/x reaches the app as /api/x (CloudHub-style app root)
    lines += ["    plugins:", "      proxy-rewrite:", "        regex_uri:",
              f"          - {q('^' + re.escape(r['path']) + '/(.*)')}", f"          - {q('/$1')}"]
    if PLUGIN_CONFIG_ID:
        lines.append(f"    plugin_config_id: {q(PLUGIN_CONFIG_ID)}")
    return lines


def render(text, routes, app_workers):
    """app_workers: {app: [workers]}. Also fills node blocks in any upstream:
    "# BEGIN runtime-manager pool <name>" (all of a pool's workers) or "... app <name>" (an app's workers)."""
    lines = [BEGIN]
    for n, r in sorted(routes.items()):
        if app_workers.get(n):
            lines += route_yaml(n, r, app_workers[n])
        else:  # app gone or its pool has no workers: keep the record, no route
            lines.append(f"  # rm-route {json.dumps({'app': n, 'path': r['path'], 'port': r['port']})}")
    lines.append(END)
    block = "\n".join(lines)
    if BEGIN in text:
        head, rest = text.split(BEGIN, 1)
        text = head + block + rest.split(END, 1)[1]
    else:
        new = re.sub(r"(?m)^routes:\n", lambda m: m.group(0) + block + "\n", text, count=1)
        if new == text:
            raise ValueError(f"no top-level 'routes:' in {APISIX_FILE}")
        text = new

    def nodes(m):
        indent, kind, name = m.group(1), m.group(2), m.group(3)
        found = nodes_of(pool_workers(name) if kind == "pool" else app_workers.get(name, []))
        # nothing to point at: keep one unreachable node, an upstream with no nodes is invalid for APISIX
        body = "".join(f'{indent}"{n}": {w}\n' for n, w in (found or {f"mule-{name}-1:{pools.APP_PORT}": 100}).items())
        return f"{indent}# BEGIN runtime-manager {kind} {name} (generated)\n{body}{indent}# END runtime-manager {kind} {name}\n"
    return re.sub(r"(?m)^( *)# BEGIN runtime-manager (pool|app) ([a-z0-9-]+).*\n(?:.*\n)*?\1# END runtime-manager \2 \3.*\n",
                  nodes, text)


def write_routes(routes=None):
    """Rewrite the generated blocks; config/apisix/start.sh re-renders and APISIX hot-reloads."""
    if not APISIX_FILE:
        return
    routes = read_routes() if routes is None else routes
    text = open(APISIX_FILE, encoding="utf-8").read()
    new = render(text, routes, {n: app_targets(n, m) for n, m in all_meta() if m.get("pool")})
    if new != text:
        # atomic replace so APISIX's start.sh (polls this folder) never renders a half-written file
        with open(APISIX_FILE + ".tmp", "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
        os.replace(APISIX_FILE + ".tmp", APISIX_FILE)


# ---------- Overview: Jaeger traces + OpenSearch logs ----------

def _json(url, data=None, auth=None, insecure=False, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(":".join(auth).encode()).decode())
    # ponytail: OpenSearch's demo cert is self-signed, so its TLS is unverified (internal network only)
    ctx = ssl._create_unverified_context() if insecure else None
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read())


def _pct(sorted_vals, p):
    return sorted_vals[min(len(sorted_vals) - 1, int(p * len(sorted_vals)))] if sorted_vals else None


def _attrs(lst):
    """OTLP JSON attributes -> {key: value} (intValue comes as a string)."""
    out = {}
    for a in lst or []:
        v = a.get("value", {})
        for k in ("stringValue", "boolValue", "doubleValue"):
            if k in v:
                out[a["key"]] = v[k]
        if "intValue" in v:
            out[a["key"]] = int(v["intValue"])
    return out


def v3_traces(result):
    """Jaeger /api/v3/traces (OTLP JSON resourceSpans) -> the legacy /api/traces shape summarize() reads:
    [{traceID, spans: [{references, tags, processID, startTime, duration (us), operationName}], processes}]."""
    traces = {}
    for i, rs in enumerate(result.get("resourceSpans") or []):
        pid = f"p{i}"
        ptags = [{"key": k, "value": v} for k, v in _attrs(rs.get("resource", {}).get("attributes")).items()]
        for ss in rs.get("scopeSpans") or []:
            for s in ss.get("spans") or []:
                t = traces.setdefault(s["traceId"], {"traceID": s["traceId"], "spans": [], "processes": {}})
                t["processes"][pid] = {"tags": ptags}
                tags = [{"key": k, "value": v} for k, v in _attrs(s.get("attributes")).items()]
                if s.get("status", {}).get("code") in (2, "STATUS_CODE_ERROR"):
                    tags.append({"key": "otel.status_code", "value": "ERROR"})
                start = int(s["startTimeUnixNano"]) // 1000
                t["spans"].append({"references": [{"spanID": s["parentSpanId"]}] if s.get("parentSpanId") else [],
                                   "tags": tags, "processID": pid, "startTime": start,
                                   "duration": int(s["endTimeUnixNano"]) // 1000 - start, "operationName": s["name"]})
    return list(traces.values())


def summarize(traces, minutes, now_us, buckets=30):
    """Jaeger traces -> request stats from each trace's root span (the agent tags it with http.* and
    tenant.id, the process with worker.id). Durations in ms."""
    reqs = []
    for t in traces:
        roots = [s for s in t.get("spans", []) if not s.get("references")]
        if not roots:
            continue
        s = roots[0]
        tags = {x["key"]: x["value"] for x in s.get("tags", [])}
        ptags = {x["key"]: x["value"] for x in t.get("processes", {}).get(s.get("processID"), {}).get("tags", [])}
        status = int(tags.get("http.status_code") or 0)
        error = tags.get("otel.status_code") == "ERROR" or tags.get("error") is True or status >= 500
        endpoint = f"{tags['http.method']} {tags.get('http.target', '')}" if tags.get("http.method") else s["operationName"]
        reqs.append({"trace": t["traceID"], "start": s["startTime"], "ms": s["duration"] / 1000, "status": status,
                     "error": error, "endpoint": endpoint, "tenant": tags.get("tenant.id") or "-",
                     "worker": ptags.get("worker.id", "-"), "version": ptags.get("service.version", "-")})

    def stats(rs):
        d = sorted(r["ms"] for r in rs)
        errs = sum(r["error"] for r in rs)
        return {"count": len(rs), "errors": errs, "error_rate": errs / len(rs) if rs else 0,
                "p50": _pct(d, .5), "p95": _pct(d, .95), "p99": _pct(d, .99),
                "avg": sum(d) / len(d) if d else None}

    def group(key, top):
        g = {}
        for r in reqs:
            g.setdefault(r[key], []).append(r)
        return sorted(({key: k, **stats(v)} for k, v in g.items()), key=lambda x: -x["count"])[:top]

    start_us, width = now_us - minutes * 60_000_000, minutes * 60_000_000 / buckets
    series = []
    for i in range(buckets):
        b = [r for r in reqs if start_us + i * width <= r["start"] < start_us + (i + 1) * width]
        st = stats(b)
        series.append({"t": int((start_us + i * width) / 1000), "count": st["count"], "errors": st["errors"], "p95": st["p95"]})
    total = stats(reqs)
    total["rpm"] = total["count"] / minutes
    slow = total["p95"] or 0
    notable = sorted((r for r in reqs if r["error"] or r["ms"] >= slow), key=lambda r: -r["start"])[:15]
    return {"total": total, "series": series, "bucket_ms": int(width / 1000), "endpoints": group("endpoint", 20),
            "workers": group("worker", 20), "tenants": group("tenant", 10), "notable": notable,
            "truncated": len(traces) >= TRACE_LIMIT}


def app_traces(name, minutes):
    if not JAEGER_URL:
        return {"state": "disabled"}
    now_us = int(time.time() * 1_000_000)
    iso = lambda us: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(us / 1_000_000))  # noqa: E731
    q = urlencode({"query.service_name": name, "query.start_time_min": iso(now_us - minutes * 60_000_000),
                   "query.start_time_max": iso(now_us), "query.num_traces": TRACE_LIMIT})
    try:  # Jaeger v2 serves only API v3 (OTLP JSON); a window without traces answers 404
        data = v3_traces(_json(f"{JAEGER_URL}/api/v3/traces?{q}", timeout=30).get("result") or {})
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return {"state": "unreachable", "error": str(e)}
        data = []
    except Exception as e:  # tracing profile off, or Jaeger still starting
        return {"state": "unreachable", "error": str(e)}
    return {"state": "ok", "link": JAEGER_PUBLIC, **summarize(data, minutes, now_us)}


def app_logs(name, minutes):
    if not OS_URL:
        return {"state": "disabled"}
    where = {"bool": {"filter": [{"term": {"application": name}},
                                 {"range": {"@timestamp": {"gte": f"now-{minutes}m"}}}]}}
    body = {"size": 0, "query": where,
            "aggs": {"levels": {"terms": {"field": "level"}}, "workers": {"terms": {"field": "worker_id"}},
                     "problems": {"filter": {"terms": {"level": ["ERROR", "WARN"]}},
                                  "aggs": {"latest": {"top_hits": {"size": 15, "sort": [{"@timestamp": "desc"}],
                                           "_source": ["@timestamp", "level", "message", "worker_id", "tenant_id", "loggerName"]}}}}}}
    try:
        r = _json(f"{OS_URL}/mule-logs-*/_search", body, auth=OS_AUTH, insecure=True)
    except Exception as e:  # logging profile off
        return {"state": "unreachable", "error": str(e)}
    a = r.get("aggregations", {})
    buckets = lambda k: {b["key"]: b["doc_count"] for b in a.get(k, {}).get("buckets", [])}  # noqa: E731
    problems = [h["_source"] for h in a.get("problems", {}).get("latest", {}).get("hits", {}).get("hits", [])]
    for p in problems:
        p["brief"] = brief(p.get("message"))
    return {"state": "ok", "total": r["hits"]["total"]["value"], "levels": buckets("levels"), "workers": buckets("workers"),
            "problems": problems}


def brief(msg):
    """One line for a log message: Mule error banners become 'ERROR:TYPE: message'."""
    msg = msg or ""
    kv = dict(re.findall(r"(?m)^(Message|Error type)\s*:\s*(.+)$", msg))
    if kv:
        return f"{kv.get('Error type', '').strip()}: {kv.get('Message', '').strip()}".strip(": ")
    lines = [ln.strip() for ln in msg.splitlines() if ln.strip() and not set(ln.strip()) <= set("*-=+ ")]
    return lines[0][:300] if lines else msg[:300]


def overview(name, minutes):
    app = next((a for a in list_apps()["apps"] if a["name"] == name), None)
    return {"app": app, "minutes": minutes, "traces": app_traces(name, minutes), "logs": app_logs(name, minutes)}


# ---------- Sign-in: Keycloak OIDC (authorization code + PKCE) ----------

def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt_claims(token):
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def login_url():
    """Start a login: remember state + PKCE verifier, send the browser to Keycloak."""
    now = time.time()
    for k in [k for k, (_, t) in PENDING.items() if now - t > 600]:
        PENDING.pop(k, None)
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    PENDING[state] = (verifier, now)
    q = urlencode({"client_id": OIDC_CLIENT, "response_type": "code", "scope": "openid profile email",
                   "redirect_uri": f"{PUBLIC_URL}/callback", "state": state, "code_challenge_method": "S256",
                   "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest())})
    return state, f"{OIDC_PUBLIC}/protocol/openid-connect/auth?{q}"


def user_from_tokens(tokens):
    """Tokens come straight from Keycloak's token endpoint (client secret + PKCE, back channel), which is
    what OIDC allows instead of checking signatures. Returns the session user, or raises PermissionError."""
    c = jwt_claims(tokens["access_token"])
    roles = c.get("realm_access", {}).get("roles", [])
    who = c.get("preferred_username") or c.get("sub")
    if OIDC_ROLE not in roles:
        raise PermissionError(f"{who} is signed in but lacks the '{OIDC_ROLE}' role")
    return {"user": who, "name": c.get("name") or who, "email": c.get("email"), "auth": "keycloak",
            "id_token": tokens.get("id_token"), "exp": time.time() + SESSION_SECONDS}


def finish_login(state, code):
    pending = PENDING.pop(state or "", None)
    if not pending or time.time() - pending[1] > 600:
        raise PermissionError("login expired or was not started here, please sign in again")
    body = urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": f"{PUBLIC_URL}/callback",
                      "client_id": OIDC_CLIENT, "client_secret": OIDC_SECRET, "code_verifier": pending[0]}).encode()
    req = urllib.request.Request(f"{OIDC_URL}/protocol/openid-connect/token", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            tokens = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise PermissionError(f"Keycloak refused the login: {e.read()[:200].decode(errors='replace')}")
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = user_from_tokens(tokens)
    return sid


def logout_url(session):
    q = {"post_logout_redirect_uri": f"{PUBLIC_URL}/", "client_id": OIDC_CLIENT}
    if session and session.get("id_token"):
        q["id_token_hint"] = session["id_token"]
    return f"{OIDC_PUBLIC}/protocol/openid-connect/logout?{urlencode(q)}"


# ---------- HTTP ----------

def page(name):
    return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name), "rb").read()


def runtime_versions():
    vs = pools.mule_versions()
    return {"versions": vs, "release": pools._versions["release"], "java": {v: pools.java_versions(v) for v in vs}}


class Handler(BaseHTTPRequestHandler):
    def cookie(self, key):
        c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return c[key].value if key in c else None

    def session(self):
        sid = self.cookie("rm_session") or ""
        s = SESSIONS.get(sid)
        if s and s["exp"] < time.time():
            SESSIONS.pop(sid, None)
            return None
        return s

    def current_user(self):
        """Browser: Keycloak session cookie (SameSite=Lax, so other sites can't send it with a PUT/POST/
        DELETE). Scripts: Basic RM_USER/RM_PASSWORD. Pipelines: Authorization: Bearer <API token>."""
        s = self.session()
        if s:
            return s
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return token_user(auth[7:].strip())
        expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        if PASSWORD and hmac.compare_digest(auth, expected):
            return {"user": USER, "name": USER, "auth": "basic"}
        return None

    def authorized(self):
        if self.current_user():
            return True
        if OIDC:  # no Basic challenge: the browser would pop a password box instead of our sign-in page
            self.reply(401, {"error": "sign in required"})
        else:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="runtime-manager"')
            self.end_headers()
        return False

    def set_cookie(self, key, value, max_age):
        secure = "; Secure" if PUBLIC_URL.startswith("https") else ""
        self.send_header("Set-Cookie", f"{key}={value}; Path={HOME}; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}")

    def redirect(self, url, cookies=()):
        self.send_response(302)
        self.send_header("Location", url)
        for c in cookies:
            self.set_cookie(*c)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def reply(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def route(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        return parts, q

    def body(self, limit=MAX_JAR):
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise OverflowError("request too large")
        data, remaining = [], length
        while remaining:
            chunk = self.rfile.read(min(remaining, 1 << 20))
            if not chunk:
                raise IOError("upload truncated")
            data.append(chunk)
            remaining -= len(chunk)
        return b"".join(data)

    def json_body(self):
        raw = self.body(1 << 20)
        return json.loads(raw) if raw.strip() else {}

    def auth_routes(self, parts, q):
        """/login, /callback, /logout and the sign-in page. True if handled."""
        if parts == ["login"] and OIDC:
            state, url = login_url()
            self.redirect(url, [("rm_state", state, 600)])
        elif parts == ["callback"] and OIDC:
            try:
                if q.get("error"):
                    raise PermissionError(q.get("error_description") or q["error"])
                if not q.get("state") or q.get("state") != self.cookie("rm_state"):
                    raise PermissionError("login state mismatch, please sign in again")
                sid = finish_login(q["state"], q.get("code", ""))
                self.redirect(HOME, [("rm_state", "", 0), ("rm_session", sid, SESSION_SECONDS)])
            except PermissionError as e:
                self.redirect(HOME + "?error=" + quote(str(e)), [("rm_state", "", 0)])
        elif parts == ["logout"]:
            s = SESSIONS.pop(self.cookie("rm_session") or "", None)
            self.redirect(logout_url(s) if OIDC else HOME, [("rm_session", "", 0)])
        elif not parts and not self.current_user():
            if not OIDC:
                return False  # Basic challenge
            self.reply(200, page("login.html"), "text/html; charset=utf-8")
        else:
            return False
        return True

    def handle_api(self, method):
        parts, q = self.route()
        if method == "GET" and self.auth_routes(parts, q):
            return
        # API docs are public (no secrets in them; every call they describe still needs auth)
        if method == "GET" and parts == ["api", "openapi.json"]:
            return self.reply(200, page("openapi.json"), "application/json")
        if method == "GET" and parts == ["api", "docs"]:
            return self.reply(200, page("docs.html"), "text/html; charset=utf-8")
        if not self.authorized():
            return
        try:
            out = self.dispatch(method, parts, q)
        except LookupError as e:
            return self.reply(404, {"error": str(e)})
        except PermissionError as e:
            return self.reply(403, {"error": str(e)})
        except (ValueError, OverflowError, json.JSONDecodeError) as e:
            return self.reply(400, {"error": str(e)})
        except Exception as e:
            print(f"{method} {self.path} failed: {e!r}", flush=True)
            return self.reply(500, {"error": str(e)})
        if isinstance(out, tuple):
            self.reply(200, *out)
        else:
            self.reply(200, out)

    def do_GET(self):
        self.handle_api("GET")

    def do_PUT(self):
        self.handle_api("PUT")

    def do_POST(self):
        self.handle_api("POST")

    def do_DELETE(self):
        self.handle_api("DELETE")

    def dispatch(self, method, parts, q):
        user = self.current_user()
        key = (method, *parts[:2], *(["*"] if len(parts) > 2 else []), *parts[3:])
        name = parts[2] if len(parts) > 2 else None
        if name and parts[1] in ("apps", "pools", "nodes") and not NAME_RE.match(name):
            raise ValueError("bad name")

        if method == "GET" and not parts:
            return page("index.html"), "text/html; charset=utf-8"
        if key == ("GET", "api", "me"):
            return {"user": user["user"], "name": user["name"], "email": user.get("email"), "auth": user["auth"],
                    "logout": OIDC and user["auth"] == "keycloak", "jaeger": JAEGER_PUBLIC, "secure": bool(SECRETS_KEY)}

        # apps
        if key == ("GET", "api", "apps"):
            return list_apps()
        if key == ("PUT", "api", "apps", "*"):
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            body = self.json_body() if ctype == "application/json" else {}
            jar = None if ctype == "application/json" else (self.body() or None)
            for k in ("pool", "group", "artifact", "version", "updates", "workers"):  # query params work too (curl -T app.jar)
                if q.get(k):
                    body.setdefault(k, q[k])
            if "path" in q:
                body["route"] = {"path": q["path"], "port": q.get("port")} if q["path"] else None
            return deploy(name, body, jar)
        if key == ("DELETE", "api", "apps", "*"):
            if not load_meta(name):
                raise LookupError(f"no app {name}")
            delete_app(name)
            return {"deleted": name}
        if key == ("GET", "api", "apps", "*", "properties"):
            m = load_meta(name)
            if not m:
                raise LookupError(f"no app {name}")
            return {"properties": m.get("properties") or {}, "secure": sorted(m.get("secure") or {})}
        if key == ("PUT", "api", "apps", "*", "properties"):
            m = load_meta(name)
            if not m:
                raise LookupError(f"no app {name}")
            m = merge_properties(m, self.json_body())
            with LOCK:
                save_meta(name, m)
                if q.get("restart", "1") != "0":
                    place(name, m)  # redeploy: Mule reads the new properties on deploy
            return {"properties": m.get("properties") or {}, "secure": sorted(m.get("secure") or {}),
                    "restarted": q.get("restart", "1") != "0"}
        if key == ("POST", "api", "apps", "*", "restart"):
            m = load_meta(name)
            if not m:
                raise LookupError(f"no app {name}")
            with LOCK:
                place(name, m)
            return {"restarted": name, "workers": [w for w in running_workers(m["pool"]) if w in app_targets(name, m)]}
        if key == ("POST", "api", "apps", "*", "check"):
            if not load_meta(name).get("artifact"):
                raise ValueError("app was not deployed from Maven")
            with LOCK:
                m = check_app(name)
            return {k: m.get(k) for k in ("version", "build", "available", "updates", "checked", "error", "updated")}
        if key == ("GET", "api", "apps", "*", "overview"):
            minutes = int(q["minutes"]) if q.get("minutes", "").isdigit() else 60
            return overview(name, max(5, min(minutes, 24 * 60)))
        if key == ("GET", "api", "apps", "*", "log"):
            w = q.get("worker", "")
            if not any(c["name"] == w for c in all_containers()):
                raise ValueError("unknown worker")
            size = int(q["bytes"]) if q.get("bytes", "").isdigit() else 64 * 1024
            return pools.read_log(w, name, q.get("source", "app"), max(1024, min(size, 8 << 20))).encode(),                 "text/plain; charset=utf-8"

        # pools
        if key == ("GET", "api", "pools"):
            return {"pools": pool_list(), "docker": True}
        if method == "GET" and parts == ["api", "runtime", "versions"]:
            return runtime_versions()
        if key == ("PUT", "api", "pools", "*"):
            body = self.json_body()
            try:
                known = pools.mule_versions()
            except Exception:  # MuleSoft repo unreachable: trust the given version, the image build will tell
                known = None
            spec = pools.validate(name, body, known)
            unknown = sorted(set(spec["nodes"]) - {pools.LOCAL} - set(load_nodes()))
            if unknown:
                raise ValueError(f"unknown node(s) {unknown}; add them under Runtime pools > Nodes first")
            with LOCK:
                specs = load_pools()
                specs[name] = spec
                save_pools(specs)
            enqueue(name)
            return {"pool": name, **spec}
        if key == ("DELETE", "api", "pools", "*"):
            apps = [a for a, m in all_meta() if m.get("pool") == name]
            if apps:
                raise ValueError(f"pool {name} still runs {', '.join(apps)}; move or delete them first")
            with LOCK:
                specs = load_pools()
                if specs.pop(name, None) is None:
                    raise LookupError(f"no pool {name}")
                save_pools(specs)
            enqueue(name)
            return {"deleted": name}
        if key == ("POST", "api", "pools", "*", "reconcile"):
            if name not in load_pools():
                raise LookupError(f"no pool {name}")
            enqueue(name)
            return {"queued": name}

        # nodes
        if key == ("GET", "api", "nodes"):
            return {"nodes": node_list()}
        if key == ("PUT", "api", "nodes", "*"):
            return put_node(name, self.json_body())
        if key == ("DELETE", "api", "nodes", "*"):
            delete_node(name)
            return {"deleted": name}

        # settings and tokens (tokens can deploy, not mint more tokens)
        if key == ("GET", "api", "settings"):
            return settings()
        if key == ("PUT", "api", "settings"):
            minutes = int(self.json_body().get("check_minutes", settings()["check_minutes"]))
            if not 0 <= minutes <= 7 * 24 * 60:
                raise ValueError("check_minutes must be between 0 (off) and 10080")
            write_json(os.path.join(DATA, "settings.json"), {"check_minutes": minutes})
            return settings()
        if parts[:2] == ["api", "tokens"] and user["auth"] == "token":
            raise PermissionError("API tokens cannot manage tokens")
        if key == ("GET", "api", "tokens"):
            return {"tokens": [{k: v for k, v in t.items() if k != "hash"} for t in token_list()]}
        if key == ("POST", "api", "tokens"):
            label = str(self.json_body().get("name", "")).strip()[:60]
            if not label:
                raise ValueError("give the token a name, e.g. the pipeline that uses it")
            raw, t = create_token(label)
            return {"token": raw, **{k: v for k, v in t.items() if k != "hash"}}
        if key == ("DELETE", "api", "tokens", "*"):
            tokens = token_list()
            if not any(t["id"] == name for t in tokens):
                raise LookupError("no such token")
            write_json(os.path.join(DATA, "tokens.json"), [t for t in tokens if t["id"] != name])
            return {"deleted": name}
        raise LookupError("not found")


def shutdown(*_):
    """docker compose down/stop: take the local pool workers with us (they're recreated on start), so the
    project's networks can be removed. Workers on nodes keep running (other servers, own lifecycle).
    ponytail: restarting the Runtime Manager restarts all local workers."""
    for c in pools.containers():
        pools.remove(c["name"])
    sys.exit(0)


if __name__ == "__main__":
    if not PASSWORD:
        raise SystemExit("RM_PASSWORD must be set")
    os.makedirs(ARTIFACTS, exist_ok=True)
    if not pools.docker_ok():
        raise SystemExit(f"Docker API not reachable at {pools.DOCKER_SOCK}: mount /var/run/docker.sock")
    ensure_default_pool()
    signal.signal(signal.SIGTERM, shutdown)
    threading.Thread(target=reconcile_forever, daemon=True).start()
    for p in load_pools():
        enqueue(p)
    threading.Thread(target=poll_forever, daemon=True).start()
    port = int(os.environ.get("PORT", "8080"))
    print(f"Runtime manager on :{port}, pools: {sorted(load_pools())}, routing: {APISIX_FILE or 'disabled'}, "
          f"maven repos: {[r['id'] for r in maven_repos()]}, update check every {settings()['check_minutes']} min, "
          f"sign-in: {'keycloak ' + OIDC_PUBLIC + ' role ' + OIDC_ROLE if OIDC else 'basic'}, "
          f"secure properties: {'on' if SECRETS_KEY else 'off (set RM_SECRETS_KEY)'}, "
          f"traces: {JAEGER_URL or 'off'}, logs: {OS_URL or 'off'}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
