"""Runtime Manager node agent: lets the platform's Runtime Manager run Mule pool workers on this server.

HTTPS (self-signed certificate, pinned by the Runtime Manager via its SHA-256 fingerprint) + a bearer
token. It forwards a small allowlist of Docker Engine API calls to the local Docker socket - the same
calls the Runtime Manager makes on its own server - and only for Runtime Manager workers: containers
named mule-* with label rm.pool, images ce-mule-runtime:*. No host mounts, no privileges, no host
network: a stolen token can run Mule workers here, not take over the server.
"""
import hashlib
import hmac
import http.client
import json
import os
import re
import socket
import ssl
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
TOKEN = os.environ.get("NODE_TOKEN", "")
BIND_IP = os.environ.get("NODE_BIND_IP", "")  # worker ports are published on this host IP ("" = all)
CERTS = os.environ.get("NODE_CERTS", "/certs")
PORT = int(os.environ.get("NODE_AGENT_PORT", "7443"))
MAX_BODY = 1024 * 1024 * 1024  # build contexts and app jars
IMAGE = "ce-mule-runtime:"
LABEL = "rm.pool"
NAME_RE = re.compile(r"^mule-[a-z0-9-]{1,80}$")
CREATE_KEYS = {"Image", "Hostname", "Env", "ExposedPorts", "Healthcheck", "HostConfig", "Labels", "NetworkingConfig"}
HOSTCONFIG_KEYS = {"RestartPolicy", "NetworkMode", "PortBindings", "Memory"}
EXEC_KEYS = {"Cmd", "AttachStdout", "AttachStderr"}  # no Privileged/User/Env on exec
BUILD_PARAMS = {"t", "rm", "buildargs"}  # no networkmode=host, remote=<url>, ...

# (method, path regex) the Runtime Manager uses; everything else is 403
ROUTES = [
    ("GET", r"/_ping"), ("GET", r"/info"), ("GET", r"/version"),
    ("GET", r"/containers/json"), ("POST", r"/containers/create"),
    ("GET", r"/containers/(?P<c>[^/]+)/json"), ("POST", r"/containers/(?P<c>[^/]+)/start"),
    ("DELETE", r"/containers/(?P<c>[^/]+)"), ("POST", r"/containers/(?P<c>[^/]+)/exec"),
    ("PUT", r"/containers/(?P<c>[^/]+)/archive"),
    ("POST", r"/exec/[0-9a-f]{64}/start"), ("GET", r"/exec/[0-9a-f]{64}/json"),
    ("GET", r"/images/json"), ("GET", r"/images/(?P<i>.+)/json"), ("DELETE", r"/images/(?P<i>.+)"),
    ("POST", r"/build"),
]


class Forbidden(Exception):
    pass


class _Unix(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCK)


def docker(method, path, body=None, headers=None, timeout=1800):
    c = _Unix("localhost", timeout=timeout)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, r.getheader("Content-Type") or "application/octet-stream", data


def owned(container, version):
    """True for a container the Runtime Manager created (label rm.pool); missing -> let Docker say 404."""
    status, _, data = docker("GET", f"{version}/containers/{quote(container, safe='')}/json")
    if status == 404:
        return True
    return status == 200 and LABEL in (json.loads(data).get("Config", {}).get("Labels") or {})


def check_create(query, body):
    """A Mule worker and nothing more: name, image, label, no mounts/privileges/host network; published
    ports forced onto NODE_BIND_IP."""
    name = query.get("name", [""])[0]
    if not NAME_RE.match(name):
        raise Forbidden("container name must be mule-*")
    cfg = json.loads(body or b"{}")
    extra = set(cfg) - CREATE_KEYS
    if extra:
        raise Forbidden(f"not allowed: {sorted(extra)}")
    if not str(cfg.get("Image", "")).startswith(IMAGE):
        raise Forbidden(f"image must be {IMAGE}*")
    if LABEL not in (cfg.get("Labels") or {}):
        raise Forbidden(f"label {LABEL} required")
    if cfg.get("NetworkingConfig"):
        raise Forbidden("no networks: workers use the default bridge")
    hc = cfg.get("HostConfig") or {}
    extra = set(hc) - HOSTCONFIG_KEYS
    if extra:
        raise Forbidden(f"HostConfig not allowed: {sorted(extra)}")
    if hc.get("NetworkMode", "bridge") not in ("bridge", "default"):
        raise Forbidden("network mode must be bridge")
    for port, binds in (hc.get("PortBindings") or {}).items():
        for b in binds or []:
            b["HostIp"] = BIND_IP
    cfg["HostConfig"] = hc
    return json.dumps(cfg).encode()


def authorize(method, path, query, body):
    """Returns the (possibly rewritten) path + body, or raises Forbidden."""
    m = re.match(r"^(/v1\.\d+)?(/.*)$", path)
    version, rest = (m.group(1) or ""), m.group(2)
    for meth, pattern in ROUTES:
        g = re.fullmatch(pattern, rest)
        if meth == method and g:
            break
    else:
        raise Forbidden(f"{method} {rest} is not allowed")
    groups = g.groupdict()
    if groups.get("c") is not None and not owned(unquote(groups["c"]), version):
        raise Forbidden("not a Runtime Manager worker")
    if groups.get("i") is not None and not unquote(groups["i"]).startswith(IMAGE):
        raise Forbidden(f"only {IMAGE}* images")
    if rest == "/containers/json":  # only ever list Runtime Manager workers
        filters = json.loads(query.get("filters", ["{}"])[0] or "{}")
        labels = [lb for lb in filters.get("label", []) if lb == LABEL or lb.startswith(LABEL + "=")] or [LABEL]
        filters["label"] = labels
        query["filters"] = [json.dumps(filters)]
    if rest == "/images/json":
        query["filters"] = [json.dumps({"reference": ["ce-mule-runtime"]})]
    if rest == "/build":
        if not query.get("t", [""])[0].startswith(IMAGE):
            raise Forbidden(f"builds must be tagged {IMAGE}*")
        if set(query) - BUILD_PARAMS:
            raise Forbidden(f"build parameters not allowed: {sorted(set(query) - BUILD_PARAMS)}")
        if any(len(v) > 1 for v in query.values()):  # Docker applies every t=: a 2nd tag could overwrite any image
            raise Forbidden("build parameters may appear once")
    if rest.endswith("/exec") and set(json.loads(body or b"{}")) - EXEC_KEYS:
        raise Forbidden(f"exec may only set {sorted(EXEC_KEYS)}")
    if rest == "/containers/create":
        body = check_create(query, body)
    return f"{version}{rest}?{urlencode(query, doseq=True)}" if query else f"{version}{rest}", body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stdout.write("%s %s\n" % (self.address_string(), fmt % args))

    def reply(self, code, ctype, data):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self):
        auth = self.headers.get("Authorization", "")
        if not (TOKEN and hmac.compare_digest(auth, f"Bearer {TOKEN}")):
            return self.reply(401, "application/json", b'{"message": "bad node token"}')
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self.reply(413, "application/json", b'{"message": "too large"}')
        body = self.rfile.read(length) if length else None
        u = urlparse(self.path)
        try:
            path, body = authorize(self.command, u.path, parse_qs(u.query, keep_blank_values=True), body)
        except Forbidden as e:
            return self.reply(403, "application/json", json.dumps({"message": str(e)}).encode())
        except ValueError as e:
            return self.reply(400, "application/json", json.dumps({"message": str(e)}).encode())
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")} if body is not None else {}
        status, ctype, data = docker(self.command, path, body, headers)
        self.reply(status, ctype, data)

    do_GET = do_POST = do_PUT = do_DELETE = handle_any


def ensure_cert():
    """Self-signed certificate on first start; the Runtime Manager pins its fingerprint (no CA needed)."""
    crt, key = os.path.join(CERTS, "agent.crt"), os.path.join(CERTS, "agent.key")
    if not (os.path.exists(crt) and os.path.exists(key)):
        os.makedirs(CERTS, exist_ok=True)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
                        "-subj", "/CN=rm-node-agent", "-keyout", key, "-out", crt], check=True, capture_output=True)
        os.chmod(key, 0o600)
    der = ssl.PEM_cert_to_DER_cert(open(crt).read())
    return crt, key, "sha256:" + hashlib.sha256(der).hexdigest()


if __name__ == "__main__":
    if len(TOKEN) < 16:
        raise SystemExit("NODE_TOKEN must be set (16+ characters): run node/install-node.sh")
    crt, key, fp = ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f"node agent on :{PORT}, worker ports bound to {BIND_IP or 'all host IPs'}", flush=True)
    print(f"NODE-FINGERPRINT {fp}", flush=True)
    srv.serve_forever()
