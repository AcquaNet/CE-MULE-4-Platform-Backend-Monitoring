"""Runtime pools: named Mule runtimes (Mule version, Java, heap, JVM options, replicas) that run as
containers mule-<pool>-<n>, created by the Runtime Manager through the Docker Engine API.

Workers are cattle: the desired state is the pool spec (/data/pools.json) plus the apps placed on the
pool, and the Runtime Manager rebuilds a pool's containers and re-places its apps whenever they drift
(new spec, missing container). All worker I/O goes through the Docker API (archive upload + exec), so
no host paths are involved.

Nodes: a pool's workers can run on other servers too (spec "nodes": {"local": 2, "<node>": 3}). Each
node runs the node agent (node/), an HTTPS + token proxy for the same Docker API calls, so everything
here works the same on a node: docker(..., node=...). Worker -> node is remembered in WORKER_NODE, so the
per-worker functions (exec, deploy, logs, remove) need no node argument.
"""
import hashlib
import http.client
import io
import json
import os
import re
import socket
import ssl
import tarfile
import time
import urllib.parse
import urllib.request

DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
BUILD_DIR = os.environ.get("RM_RUNTIME_BUILD_DIR", "/build/mule-runtime")
NETWORKS = [n for n in os.environ.get("RM_NETWORKS", "ce-base-micronet,ce-base-network").split(",") if n]
MULE_REPO = os.environ.get("RM_MULE_REPO", "https://repository.mulesoft.org/nexus/content/repositories/"
                           "releases/org/mule/distributions/mule-standalone")
MULE_HOME = "/opt/mule/mule-standalone"
APP_PORT = 8081
NODE_PORTS = 10  # a remote worker publishes 8081..8090 on its node (per-app routes on other ports stay local-only)
LOCAL = "local"
POOL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}$")
OPT_RE = re.compile(r"^-[A-Za-z0-9:+_.=,/%@-]+$")  # one JVM option; no spaces (args are word-split)
LABEL = "rm.pool"


# ---------- Docker Engine API (unix socket) ----------

class _UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(DOCKER_SOCK)


class _NodeConnection(http.client.HTTPSConnection):
    """HTTPS to a node agent. Its certificate is self-signed: trust is the SHA-256 fingerprint pinned when
    the node was added (no CA), checked right after the handshake."""
    def __init__(self, node, timeout):
        u = urllib.parse.urlparse(node["address"])
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        super().__init__(u.hostname, u.port or 7443, timeout=timeout, context=ctx)
        self.fingerprint = node["fingerprint"].lower().replace("sha256:", "").replace(":", "")

    def connect(self):
        super().connect()
        got = hashlib.sha256(self.sock.getpeercert(binary_form=True)).hexdigest()
        if got != self.fingerprint:
            self.sock.close()
            raise ssl.SSLError(f"node certificate fingerprint mismatch (got sha256:{got})")


WORKER_NODE = {}  # worker container name -> node dict (absent = local Docker)


def docker(method, path, body=None, ctype="application/json", timeout=120, raw=False, node=None):
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    headers = {"Content-Type": ctype} if data is not None else {}
    if node is None:
        conn = _UnixConnection("localhost", timeout=timeout)
    else:
        conn = _NodeConnection(node, timeout)
        headers["Authorization"] = f"Bearer {node['token']}"
    conn.request(method, "/v1.41" + path, body=data, headers=headers)
    r = conn.getresponse()
    out = r.read()
    conn.close()
    if r.status >= 400:
        if r.status == 404:
            raise LookupError(f"docker {path}: not found")
        raise RuntimeError(f"docker {method} {path}: {r.status} {out[:300].decode(errors='replace')}")
    if raw or not out:
        return out
    return json.loads(out) if (r.getheader("Content-Type") or "").startswith("application/json") else out


def docker_ok(node=None):
    try:
        docker("GET", "/_ping", timeout=5, node=node)
        return True
    except Exception:
        return False


def node_info(node, timeout=10):
    """Capacity of a node (or local Docker): what the Nodes page shows."""
    i = docker("GET", "/info", timeout=timeout, node=node)
    return {"docker": i.get("ServerVersion"), "cpus": i.get("NCPU"), "memory_mb": int(i.get("MemTotal", 0) / 2**20),
            "os": i.get("OperatingSystem")}


def exec_in(container, cmd, timeout=60):
    """Run cmd in the container; returns (exit code, stdout+stderr)."""
    node = WORKER_NODE.get(container)
    e = docker("POST", f"/containers/{container}/exec", {"Cmd": cmd, "AttachStdout": True, "AttachStderr": True}, node=node)
    stream = docker("POST", f"/exec/{e['Id']}/start", {"Detach": False, "Tty": False}, timeout=timeout, raw=True, node=node)
    out, i = b"", 0
    while i + 8 <= len(stream):  # multiplexed stream: [stream, 0, 0, 0, size(4)] + payload per frame
        n = int.from_bytes(stream[i + 4:i + 8], "big")
        out += stream[i + 8:i + 8 + n]
        i += 8 + n
    return docker("GET", f"/exec/{e['Id']}/json", node=node)["ExitCode"], out.decode(errors="replace")


def put_files(container, files, dest=MULE_HOME):
    """files: {relative path: bytes} -> extracted under dest inside the container."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), int(time.time()), 0o644
            t.addfile(info, io.BytesIO(data))
    docker("PUT", f"/containers/{container}/archive?path={urllib.parse.quote(dest)}", buf.getvalue(), "application/x-tar",
           node=WORKER_NODE.get(container))


# ---------- Mule versions ----------

_versions = {"at": 0, "list": [], "release": None}


def mule_versions():
    """CE standalone versions published by MuleSoft (newest first), cached for an hour."""
    if time.time() - _versions["at"] > 3600:
        with urllib.request.urlopen(f"{MULE_REPO}/maven-metadata.xml", timeout=20) as r:
            xml = r.read().decode()
        vs = [v for v in re.findall(r"<version>(4\.\d+\.\d+)</version>", xml)]
        _versions.update(at=time.time(), list=sorted(set(vs), key=vkey, reverse=True),
                         release=(re.findall(r"<release>([^<]+)</release>", xml) or [None])[0])
    return _versions["list"]


def vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def java_versions(mule_version):
    """Java versions a Mule CE release runs on."""
    v = vkey(mule_version)[:2]
    return ["17"] if v >= (4, 9) else ["8", "11", "17"] if v >= (4, 5) else ["8", "11"]


# ---------- pool specs ----------

def validate(name, body, known_versions=None):
    if not POOL_RE.match(name or ""):
        raise ValueError("pool name must be lowercase letters, digits and dashes (max 30)")
    mule = str(body.get("mule_version", "")).strip()
    if known_versions is not None and mule not in known_versions:
        raise ValueError(f"unknown Mule CE version {mule!r}")
    java = str(body.get("java_version") or java_versions(mule)[-1])
    if java not in java_versions(mule):
        raise ValueError(f"Mule {mule} runs on Java {', '.join(java_versions(mule))}, not {java}")
    heap = int(body.get("heap_mb", 1024))
    if not 256 <= heap <= 65536:
        raise ValueError("heap_mb must be between 256 and 65536")
    # workers per node; "replicas" alone = that many on the local Docker
    nodes = body.get("nodes")
    if nodes is None:
        nodes = {LOCAL: body.get("replicas", 1)}
    if not isinstance(nodes, dict):
        raise ValueError('nodes must be {"local": 2, "<node>": 1, ...}')
    nodes = {str(k): int(v) for k, v in nodes.items() if int(v) > 0}
    for n, c in nodes.items():
        if not POOL_RE.match(n):
            raise ValueError(f"bad node name {n!r}")
        if c > 20:
            raise ValueError(f"at most 20 workers per node ({n}: {c})")
    opts = [o.strip() for o in body.get("jvm_options", []) if o.strip()]
    bad = [o for o in opts if not OPT_RE.match(o)]
    if bad:
        raise ValueError(f"invalid JVM option(s) {bad}: one option per entry, starting with '-', no spaces")
    return {"mule_version": mule, "java_version": java, "heap_mb": heap, "nodes": nodes,
            "replicas": sum(nodes.values()), "jvm_options": opts}


_context = {}


def context_hash():
    """Hash of the runtime build context (mule/docker_mulesoft): part of the image tag, so editing the
    Dockerfile/scripts/wrapper config builds a new image and rolls the workers instead of reusing a stale one."""
    if "hash" not in _context:
        h = hashlib.sha256()
        for root, dirs, files in os.walk(BUILD_DIR):
            dirs.sort()
            for f in sorted(files):
                path = os.path.join(root, f)
                h.update(os.path.relpath(path, BUILD_DIR).replace(os.sep, "/").encode())
                with open(path, "rb") as fh:
                    h.update(fh.read().replace(b"\r\n", b"\n"))
        _context["hash"] = h.hexdigest()[:10]
    return _context["hash"]


def image_tag(spec):
    return f"ce-mule-runtime:{spec['mule_version']}-java{spec['java_version']}-{context_hash()}"


def prune_images(keep, node=None):
    """Remove runtime images no pool uses any more (old versions, old build contexts). In-use ones fail
    to delete and are kept."""
    f = urllib.parse.quote(json.dumps({"reference": ["ce-mule-runtime"]}))
    for img in docker("GET", f"/images/json?filters={f}", node=node):
        for tag in img.get("RepoTags") or []:
            if tag not in keep:
                try:
                    docker("DELETE", f"/images/{urllib.parse.quote(tag, safe='')}", node=node)
                except Exception:
                    pass


def worker_names(pool, spec):
    """[(container name, node name)]: local workers mule-<pool>-<n>, node workers mule-<pool>-<node>-<n>
    (names stay put when another node's count changes)."""
    nodes = spec.get("nodes") or {LOCAL: spec.get("replicas", 0)}
    out = [(f"mule-{pool}-{i}", LOCAL) for i in range(1, nodes.get(LOCAL, 0) + 1)]
    for n in sorted(k for k in nodes if k != LOCAL):
        out += [(f"mule-{pool}-{n}-{i}", n) for i in range(1, nodes[n] + 1)]
    return out


def worker_env():
    """WORKER_<NAME> variables of the Runtime Manager become <NAME> in every worker (compose keeps them)."""
    return {k[len("WORKER_"):]: v for k, v in os.environ.items() if k.startswith("WORKER_") and v != ""}


def metrics_on():
    """Prometheus runs (monitoring or alerting profile in COMPOSE_PROFILES): workers push JVM metrics to it.
    ponytail: reads .env's COMPOSE_PROFILES, so a `--profile monitoring` on the command line alone isn't seen."""
    profiles = {p.strip() for p in os.environ.get("RM_COMPOSE_PROFILES", "").split(",")}
    return bool(profiles & {"monitoring", "alerting", "*"})


def container_config(pool, spec, name, remote=None):
    """remote (worker on a node): {"port": first host port, "gateway": host the node reaches the platform at,
    "ca": platform CA PEM, "otlp_token": ...}. Such a worker publishes 8081..8090 on the node and sends logs
    and traces through the gateway (9100, /otlp) instead of the internal log-ingest/jaeger names."""
    args = ["-M" + o for o in spec["jvm_options"]]
    env = worker_env()
    if not metrics_on():  # nothing would take them: don't post metrics into the void every interval
        env["OTEL_METRICS_EXPORTER"] = "none"
    attrs = ",".join(filter(None, [env.get("OTEL_RESOURCE_ATTRIBUTES", ""), f"worker.id={name}", f"rm.pool={pool}"]))
    if remote:
        gw = remote["gateway"]
        args += [f"-M-Dlogs.host={gw}", "-M-Dlogs.port=9100"]
        env.update(OTEL_EXPORTER_OTLP_ENDPOINT=f"https://{gw}:9443/otlp", OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf",
                   OTEL_EXPORTER_OTLP_HEADERS=f"x-otlp-token={remote['otlp_token']}")
        # metrics too through the gateway (/otlp/v1/metrics -> Prometheus), not the internal prometheus name
        env.pop("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", None)
        env.pop("OTEL_EXPORTER_OTLP_METRICS_PROTOCOL", None)
        if remote.get("ca"):
            env["PLATFORM_CA_PEM"] = remote["ca"]  # mule-start.sh adds it to the JVM truststore
    # heap via the wrapper's own settings (wrapper-platform.conf): -M-Xmx would lose to them. Start small,
    # the JVM commits heap as it needs it (an idle app uses ~300 MB), capped at heap_mb.
    env.update(MULE_ARGS=" ".join(args), MULE_INIT_HEAP_MB=str(min(256, spec["heap_mb"])),
               MULE_MAX_HEAP_MB=str(spec["heap_mb"]), WORKER_ID=name, OTEL_RESOURCE_ATTRIBUTES=attrs)
    cfg = {
        "Image": image_tag(spec), "Hostname": name,
        "Env": [f"{k}={v}" for k, v in sorted(env.items())],
        "ExposedPorts": {f"{APP_PORT}/tcp": {}},
        "Healthcheck": {"Test": ["CMD-SHELL", f"grep -q 'Mule is up and kicking' {MULE_HOME}/logs/mule.log || exit 1"],
                        "Interval": 30 * 10**9, "Timeout": 10 * 10**9, "Retries": 50, "StartPeriod": 480 * 10**9},
        "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}, "NetworkMode": NETWORKS[0] if NETWORKS else "bridge"},
        "NetworkingConfig": {"EndpointsConfig": {NETWORKS[0]: {"Aliases": [name]}}} if NETWORKS else {},
    }
    if remote:  # default bridge on the node; apps reachable as <node address>:<port .. port+9>
        ports = range(APP_PORT, APP_PORT + NODE_PORTS)
        cfg["ExposedPorts"] = {f"{p}/tcp": {} for p in ports}
        cfg["HostConfig"] = {"RestartPolicy": {"Name": "unless-stopped"}, "NetworkMode": "bridge",
                             "PortBindings": {f"{p}/tcp": [{"HostPort": str(remote["port"] + p - APP_PORT)}] for p in ports}}
        cfg["NetworkingConfig"] = {}
    digest = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]
    cfg["Labels"] = {LABEL: pool, "rm.spec": digest}
    return cfg


def containers(pool=None, node=None, timeout=120):
    """Worker containers the Runtime Manager owns on one Docker: [{name, pool, spec, state, health}]."""
    f = {"label": [f"{LABEL}={pool}" if pool else LABEL]}
    out = []
    for c in docker("GET", "/containers/json?all=1&filters=" + urllib.parse.quote(json.dumps(f)), node=node, timeout=timeout):
        health = (c.get("Status") or "")
        out.append({"name": c["Names"][0].lstrip("/"), "pool": c["Labels"].get(LABEL), "spec": c["Labels"].get("rm.spec"),
                    "state": c["State"],
                    "health": "healthy" if "(healthy)" in health else "starting" if "health: starting" in health
                    else "unhealthy" if "(unhealthy)" in health else ""})
    return sorted(out, key=lambda c: c["name"])


def ensure_image(spec, progress=lambda s: None, node=None):
    """Build the runtime image on that Docker if it's missing (a node builds its own: the context is sent
    over the API, Mule is downloaded there)."""
    tag = image_tag(spec)
    try:
        docker("GET", f"/images/{urllib.parse.quote(tag, safe='')}/json", node=node)
        return tag
    except LookupError:
        pass
    progress(f"building runtime image {tag}{' on ' + node['name'] if node else ''} (downloads Mule {spec['mule_version']})")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        t.add(BUILD_DIR, arcname=".")
    q = urllib.parse.urlencode({"t": tag, "rm": "1", "buildargs": json.dumps(
        {"MULE_VERSION": spec["mule_version"], "JAVA_VERSION": spec["java_version"]})})
    out = docker("POST", f"/build?{q}", buf.getvalue(), "application/x-tar", timeout=1800, raw=True, node=node)
    for line in out.decode(errors="replace").splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if j.get("error"):
            raise RuntimeError(f"image build failed: {j['error'].strip()}")
    return tag


def remove(name):
    try:
        docker("DELETE", f"/containers/{name}?force=1", timeout=60, node=WORKER_NODE.get(name))
    except LookupError:
        pass


def create(pool, spec, name, node=None, remote=None):
    cfg = container_config(pool, spec, name, remote)
    if node is not None:
        WORKER_NODE[name] = node
    remove(name)
    docker("POST", f"/containers/create?name={name}", cfg, node=node)
    if node is None:
        for net in NETWORKS[1:]:
            docker("POST", f"/networks/{net}/connect", {"Container": name})
    docker("POST", f"/containers/{name}/start", node=node)


def wait_runtime(name, timeout=420):
    """Until Mule's container has started (deployments can begin)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            code, _ = exec_in(name, ["grep", "-q", "Mule is up and kicking", f"{MULE_HOME}/logs/mule.log"], timeout=10)
            if code == 0:
                return True
        except (RuntimeError, LookupError, OSError):
            pass
        time.sleep(3)
    return False


# ---------- apps on a worker ----------

def properties_text(props):
    """java.util.Properties format (ISO-8859-1 with \\uXXXX escapes)."""
    def esc(s, key):
        out = []
        for ch in str(s):
            if ch == "\\":
                out.append("\\\\")
            elif ch in "\n\r\t\f":
                out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t", "\f": "\\f"}[ch])
            elif key and ch in " =:#!":
                out.append("\\" + ch)
            elif ord(ch) > 126 or ord(ch) < 32:
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
        s = "".join(out)
        return s if key or not s.startswith(" ") else "\\" + s
    return "".join(f"{esc(k, True)}={esc(v, False)}\n" for k, v in sorted(props.items())).encode("ascii")


def deploy_on(worker, app, jar, props):
    """Properties first (Mule reads .mule/<app>/deployment-properties on deploy), then the jar under a
    name Mule ignores, renamed in one step so the deployer never sees a partial jar."""
    put_files(worker, {f".mule/{app}/deployment-properties/deployment.properties": properties_text(props),
                       f"apps/.{app}.jar.part": jar})
    code, out = exec_in(worker, ["mv", "-f", f"{MULE_HOME}/apps/.{app}.jar.part", f"{MULE_HOME}/apps/{app}.jar"])
    if code:
        raise RuntimeError(f"{worker}: {out.strip()}")


def undeploy_on(worker, app):
    exec_in(worker, ["rm", "-f", f"{MULE_HOME}/apps/{app}.jar", f"{MULE_HOME}/apps/{app}-anchor.txt"])


def app_states(worker):
    """{app: STARTED|DEPLOYING|FAILED}. Anchor = started, jar = waiting to deploy. An exploded dir without
    an anchor is either mid-deploy or failed: Mule's log decides (its last "Started app" / "Failed to deploy"
    line for that app), so a deploy in progress is never reported as FAILED."""
    script = (f"ls -1 -p {MULE_HOME}/apps; echo '--log--'; "
              f"grep -hoE \"Started app '[^']+'|Failed to deploy artifact .[^]' ]+\" {MULE_HOME}/logs/mule.log 2>/dev/null | tail -n 200")
    code, out = exec_in(worker, ["sh", "-c", script], timeout=15)
    if code and "--log--" not in out:
        return {}
    listing, _, log = out.partition("--log--")
    last = {}  # app -> last deployment outcome in mule.log
    for line in log.splitlines():
        m = re.match(r"Started app '([^']+)'", line) or re.match(r"Failed to deploy artifact .([^\]' ]+)", line)
        if m:
            last[m.group(1)] = "STARTED" if line.startswith("Started") else "FAILED"
    files = set(listing.split())
    states = {}
    for f in files:
        if f.endswith("-anchor.txt"):
            states[f[:-len("-anchor.txt")]] = "STARTED"
    for f in files:
        if f.endswith(".jar") and not f.startswith("."):
            states.setdefault(f[:-4], "DEPLOYING")
        elif f.endswith("/") and f[:-1] not in states and f[:-1] != "default":
            states[f[:-1]] = "FAILED" if last.get(f[:-1]) == "FAILED" else "DEPLOYING"
    return states


def read_log(worker, app, source="app", limit=64 * 1024):
    files = ["mule.log"] if source == "runtime" else [f"mule-app-{app}.log", f"{app.replace('-', '')}.log", f"{app}.log"]
    script = "for f in " + " ".join(files) + f"; do [ -f {MULE_HOME}/logs/$f ] && exec tail -c {limit} {MULE_HOME}/logs/$f; done; " \
             f"echo '(no log yet: looked for {', '.join(files)})'"
    return exec_in(worker, ["sh", "-c", script], timeout=20)[1]
