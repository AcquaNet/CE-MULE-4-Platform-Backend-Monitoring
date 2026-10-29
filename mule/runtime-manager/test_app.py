"""Self-check: python test_app.py  (no framework, temp dirs only, Docker faked in memory)."""
import functools
import json
import os
import shutil
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

root = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{root}/data", APISIX_FILE=f"{root}/apisix.yaml", RM_ROUTE_PLUGIN_CONFIG="mule-api-auth",
                  RM_SECRETS_KEY="test-key", WORKER_TZ="UTC", WORKER_OTEL_RESOURCE_ATTRIBUTES="deployment.environment=test",
                  RM_MAVEN_POLL_SECONDS="300")
import app  # noqa: E402
import pools  # noqa: E402

os.makedirs(app.ARTIFACTS)

# ---------- fake Docker: containers with an apps dir and deployment properties ----------
world = {}  # name -> {pool, spec, state, apps: {app: props}}


built = []  # (image, node) builds requested


def fake_create(pool, spec, name, node=None, remote=None):
    cfg = pools.container_config(pool, spec, name, remote)
    world[name] = {"pool": pool, "spec": cfg["Labels"]["rm.spec"], "state": "running", "apps": {}, "cfg": cfg,
                   "node": node["name"] if node else "local"}


pools.containers = lambda pool=None, node=None, timeout=0: sorted(
    ({"name": n, "pool": c["pool"], "spec": c["spec"], "state": c["state"], "health": ""} for n, c in world.items()
     if pool in (None, c["pool"]) and c["node"] == (node["name"] if node else "local")), key=lambda c: c["name"])
pools.create = fake_create
pools.remove = lambda name: world.pop(name, None)
pools.ensure_image = lambda spec, progress=None, node=None: built.append((pools.image_tag(spec), node and node["name"]))
pools.prune_images = lambda keep, node=None: None
pools.node_info = lambda conn, timeout=10: ({"docker": "28", "cpus": 4, "memory_mb": 8192, "os": "fake"}
                                if conn["token"] == "node-secret" else (_ for _ in ()).throw(RuntimeError("401 unauthorized")))
pools.wait_runtime = lambda name, timeout=0: True
pools.deploy_on = lambda w, a, jar, props: world[w]["apps"].__setitem__(a, dict(props, _jar=jar))
pools.undeploy_on = lambda w, a: world[w]["apps"].pop(a, None)
pools.app_states = lambda w: {a: "STARTED" for a in world[w]["apps"]}

open(app.APISIX_FILE, "w").write(
    "routes:\n  - uri: /api/*\n    upstream_id: \"1\"\nupstreams:\n  - id: \"1\"\n    nodes:\n"
    "      # BEGIN runtime-manager pool default\n      \"old:8081\": 100\n      # END runtime-manager pool default\n"
    "    type: roundrobin\n#END\n")

# pool specs: Java must match the Mule version, options are single tokens
assert pools.java_versions("4.4.0") == ["8", "11"] and pools.java_versions("4.12.0") == ["17"]
for bad in ({"mule_version": "4.12.0", "java_version": "8"}, {"mule_version": "4.12.0", "jvm_options": ["-Dx=a b"]},
            {"mule_version": "9.9.9"}, {"mule_version": "4.12.0", "replicas": 99}):
    try:
        pools.validate("p", bad, ["4.12.0", "4.4.0"])
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
spec = pools.validate("default", {"mule_version": "4.12.0", "heap_mb": 1024, "replicas": 2, "jvm_options": ["-XX:+UseG1GC"]})
cfg = pools.container_config("default", spec, "mule-default-1")
env = dict(e.split("=", 1) for e in cfg["Env"])
assert env["MULE_ARGS"] == "-M-XX:+UseG1GC" and env["TZ"] == "UTC"
assert (env["MULE_INIT_HEAP_MB"], env["MULE_MAX_HEAP_MB"]) == ("256", "1024")
assert env["OTEL_RESOURCE_ATTRIBUTES"] == "deployment.environment=test,worker.id=mule-default-1,rm.pool=default"
assert cfg["Labels"]["rm.spec"] == pools.container_config("default", spec, "mule-default-1")["Labels"]["rm.spec"]
assert pools.properties_text({"a.b": "x=1\nü", "k ey": " lead"}) == b"a.b=x=1\\n\\u00fc\nk\\ ey=\\ lead\n"

# default pool comes up with 2 workers; the /api/* upstream block follows it
app.save_pools({"default": spec})
app.reconcile("default")
assert sorted(world) == ["mule-default-1", "mule-default-2"] and app.POOL_STATUS["default"]["state"] == "ready"
text = open(app.APISIX_FILE).read()
assert '"mule-default-1:8081": 100' in text and '"old:8081"' not in text and text.count("BEGIN runtime-manager pool") == 1

# upload + properties (one secure): on every pool worker, secure value encrypted at rest and never listed
r = app.deploy("orders", {"pool": "default", "properties": {"db.host": "mysql"}, "secureProperties": {"db.password": "s3cr3t"},
                          "route": {"path": "/api/orders", "port": 8091}}, jar=b"PK orders-1")
assert r["workers"] == ["mule-default-1", "mule-default-2"]
assert world["mule-default-2"]["apps"]["orders"] == {"db.host": "mysql", "db.password": "s3cr3t", "_jar": b"PK orders-1"}
stored = open(f"{app.ARTIFACTS}/orders.json").read()
assert "s3cr3t" not in stored and "db.password" in stored
a = next(x for x in app.list_apps()["apps"] if x["name"] == "orders")
assert a["secure"] == ["db.password"] and a["properties"] == ["db.host"] and "s3cr3t" not in json.dumps(a)
assert a["workers"] == {"mule-default-1": "STARTED", "mule-default-2": "STARTED"} and a["updates"] == "off"
assert app.read_routes() == {"orders": {"path": "/api/orders", "port": 8091}}
for bad in ("/runtime-manager/api", "/auth/realms", "/opensearch"):
    try:
        app.deploy("orders", {"route": {"path": bad}})
        raise AssertionError(bad)
    except ValueError:
        pass
assert '"mule-default-2:8091": 100' in open(app.APISIX_FILE).read()
assert '- "^/api/orders/(.*)"' in open(app.APISIX_FILE).read()
# keep the secure value (null), change the plain one
m = app.merge_properties(app.load_meta("orders"), {"properties": {"db.host": "db2"}, "secureProperties": {"db.password": None}})
assert app.app_properties(m) == {"db.host": "db2", "db.password": "s3cr3t"}
for bad in ({"secureProperties": {"nope": None}}, {"properties": {"bad key": "x"}}):
    try:
        app.merge_properties(app.load_meta("orders"), bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass

# change the runtime: every worker is replaced (rolling) and gets the apps back with their properties
app.save_pools({"default": {**spec, "heap_mb": 2048}})
before = {n: c["spec"] for n, c in world.items()}
app.reconcile("default")
assert all(world[n]["spec"] != before[n] for n in before) and world["mule-default-1"]["apps"]["orders"]["db.password"] == "s3cr3t"
# scale in to 1 worker; a second pool on another Mule version takes the app; the old pool lets it go
app.save_pools({"default": {**spec, "heap_mb": 2048, "replicas": 1, "nodes": {"local": 1}},
                "legacy": pools.validate("legacy", {"mule_version": "4.4.0", "java_version": "8", "replicas": 1})})
app.reconcile("default")
app.reconcile("legacy")
assert sorted(world) == ["mule-default-1", "mule-legacy-1"] and world["mule-legacy-1"]["cfg"]["Image"].startswith("ce-mule-runtime:4.4.0-java8-")
app.deploy("orders", {"pool": "legacy"})
assert "orders" in world["mule-legacy-1"]["apps"] and "orders" not in world["mule-default-1"]["apps"]
assert '"mule-legacy-1:8091": 100' in open(app.APISIX_FILE).read()
try:
    app.deploy("orders", {"pool": "nope"})
    raise AssertionError("unknown pool accepted")
except ValueError:
    pass

# per-app workers: a count spreads apps over the least-loaded workers and stays put; a list pins them
app.save_pools({"default": {**spec, "heap_mb": 2048, "replicas": 3, "nodes": {"local": 3}}, "legacy": app.load_pools()["legacy"]})
app.reconcile("default")
jar = b"PK x"
app.deploy("a1", {"pool": "default", "workers": 1}, jar=jar)
app.deploy("a2", {"pool": "default", "workers": 1}, jar=jar)
app.deploy("a3", {"pool": "default", "workers": "2"}, jar=jar)
where = lambda a: sorted(n for n, c in world.items() if a in c["apps"])  # noqa: E731
assert where("a1") == ["mule-default-1"] and where("a2") == ["mule-default-2"], (where("a1"), where("a2"))
assert where("a3") == ["mule-default-1", "mule-default-3"] or len(where("a3")) == 2
before = where("a3")
app.deploy("a3", {"properties": {"x": "1"}})  # redeploy keeps its workers
assert where("a3") == before
app.deploy("a1", {"workers": ["mule-default-3"]})
assert where("a1") == ["mule-default-3"]
a = next(x for x in app.list_apps()["apps"] if x["name"] == "a1")
assert a["placement"] == ["mule-default-3"] and list(a["workers"]) == ["mule-default-3"]
for bad in ({"workers": ["mule-nope-1"]}, {"workers": 0}, {"workers": True}):
    try:
        app.deploy("a1", bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
# scale the pool in to 1: the 2-worker app keeps what it can, the pinned one keeps nothing it can't have
app.save_pools({"default": {**spec, "heap_mb": 2048, "replicas": 1, "nodes": {"local": 1}}, "legacy": app.load_pools()["legacy"]})
app.reconcile("default")
assert where("a3") == ["mule-default-1"] and where("a2") == ["mule-default-1"] and where("a1") == []
# gateway: an "app" node block follows that app's workers
open(app.APISIX_FILE, "a").write("    nodes:\n      # BEGIN runtime-manager app a3\n      # END runtime-manager app a3\n")
app.write_routes()
assert '"mule-default-1:8081": 100\n      # END runtime-manager app a3' in open(app.APISIX_FILE).read()
for x in ("a1", "a2", "a3"):
    app.delete_app(x)

# ---------- nodes: a pool spread over the local Docker and another server ----------
FP = "ab" * 32
for bad in ({"address": "http://x:7443", "token": "node-secret", "fingerprint": FP, "gateway": "gw"},
            {"address": "https://nodeb:7443", "token": "node-secret", "fingerprint": "nope", "gateway": "gw"},
            {"address": "https://nodeb:7443", "token": "wrong", "fingerprint": FP, "gateway": "gw"}):
    try:
        app.put_node("node-b", bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
r = app.put_node("node-b", {"address": "https://nodeb.lan:7443", "token": "node-secret", "fingerprint": "sha256:" + FP, "gateway": "platform.lan"})
assert app.load_nodes()["node-b"]["fingerprint"] == "sha256:" + FP  # as install-node.sh prints it
assert r["info"]["memory_mb"] == 8192 and "node-secret" not in open(f"{root}/data/nodes.json").read()
spread = pools.validate("spread", {"mule_version": "4.12.0", "nodes": {"local": 1, "node-b": 2}})
assert spread["replicas"] == 3 and pools.worker_names("spread", spread) == [
    ("mule-spread-1", "local"), ("mule-spread-node-b-1", "node-b"), ("mule-spread-node-b-2", "node-b")]
app.save_pools({**app.load_pools(), "spread": spread})
os.makedirs(os.path.dirname(app.PLATFORM_CA), exist_ok=True) if os.path.dirname(app.PLATFORM_CA).startswith(root) else None
app.reconcile("spread")
assert ("ce-mule-runtime:4.12.0-java17-" + pools.context_hash(), "node-b") in built  # the node builds its own image
assert world["mule-spread-1"]["node"] == "local" and world["mule-spread-node-b-2"]["node"] == "node-b"
cfg = world["mule-spread-node-b-2"]["cfg"]
env = dict(e.split("=", 1) for e in cfg["Env"])
assert cfg["HostConfig"]["PortBindings"]["8081/tcp"] == [{"HostPort": "18010"}] and cfg["NetworkingConfig"] == {}
assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://platform.lan:9443/otlp" and "-M-Dlogs.host=platform.lan" in env["MULE_ARGS"]
assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in dict(e.split("=", 1) for e in world["mule-spread-1"]["cfg"]["Env"])
app.deploy("spreadapp", {"pool": "spread", "route": {"path": "/spread", "port": 8082}}, jar=b"PK spread")
assert sorted(n for n, c in world.items() if "spreadapp" in c["apps"]) == ["mule-spread-1", "mule-spread-node-b-1", "mule-spread-node-b-2"]
text = open(app.APISIX_FILE).read()
assert '"mule-spread-1:8082": 100' in text and '"nodeb.lan:18001": 100' in text and '"nodeb.lan:18011": 100' in text
assert app.endpoint("mule-spread-node-b-1", 9000) is None  # only 8081..8090 are published on nodes
# a node that stops answering: marked down, then skipped (no new calls) for NODE_RETRY seconds
real_containers, hits = pools.containers, []
def flaky(pool=None, node=None, timeout=0):
    if node:
        hits.append(1)
        raise TimeoutError("timed out")
    return real_containers(pool)
pools.containers = flaky
app.all_containers(); app.all_containers()
assert len(hits) == 1 and app.node_down("node-b") and app.NODE_STATUS["node-b"]["error"] == "timed out"
pools.containers = real_containers
app.NODE_STATUS["node-b"]["at"] = 0  # retry window over: back to normal on the next listing
app.all_containers()
assert not app.node_down("node-b") and app.NODE_STATUS["node-b"]["ok"]
# a node on the platform's own Docker also lists the local workers: they must stay local (and a stale mapping heals)
pools.containers = lambda pool=None, node=None, timeout=0: real_containers(pool) + (real_containers(pool) if node else [])
pools.WORKER_NODE["mule-spread-1"] = {"name": "node-b"}
app.all_containers()
assert "mule-spread-1" not in pools.WORKER_NODE and pools.WORKER_NODE["mule-spread-node-b-1"]["name"] == "node-b"
pools.containers = real_containers

# a rollout while the node is down leaves that node's workers alone (no rebuild, no replacement)
before = {n: c["spec"] for n, c in world.items() if c["node"] == "node-b"}
app.mark_node("node-b", False, error="down")
real_info = pools.node_info
pools.node_info = lambda conn, timeout=10: (_ for _ in ()).throw(TimeoutError("down"))
app.save_pools({**app.load_pools(), "spread": {**app.load_pools()["spread"], "heap_mb": 2048}})
built.clear()
app.reconcile("spread")
assert {n: c["spec"] for n, c in world.items() if c["node"] == "node-b"} == before and not [b for b in built if b[1] == "node-b"]
assert "node-b unreachable" in app.POOL_STATUS["spread"]["message"]
assert world["mule-spread-1"]["cfg"]["Env"] != []  and dict(e.split("=", 1) for e in world["mule-spread-1"]["cfg"]["Env"])["MULE_MAX_HEAP_MB"] == "2048"
pools.node_info = real_info
app.NODE_STATUS.pop("node-b")
app.reconcile("spread")  # back: the node's workers get the new spec too
assert dict(e.split("=", 1) for e in world["mule-spread-node-b-1"]["cfg"]["Env"])["MULE_MAX_HEAP_MB"] == "2048"

# scale out: only the new worker gets the app; the copies already running are not redeployed (restarted)
calls = []
real_deploy = pools.deploy_on
pools.deploy_on = lambda w, a, jar, props: (calls.append((w, a)), real_deploy(w, a, jar, props))
app.save_pools({**app.load_pools(), "spread": pools.validate("spread", {"mule_version": "4.12.0", "heap_mb": 2048, "nodes": {"local": 2, "node-b": 2}})})
app.reconcile("spread")
pools.deploy_on = real_deploy
assert [c for c in calls if c[1] == "spreadapp"] == [("mule-spread-2", "spreadapp")], calls
app.save_pools({**app.load_pools(), "spread": pools.validate("spread", {"mule_version": "4.12.0", "heap_mb": 2048, "nodes": {"local": 1, "node-b": 2}})})
app.reconcile("spread")
try:
    app.delete_node("node-b")
    raise AssertionError("deleted a node in use")
except ValueError:
    pass
# scale the node part in: its worker goes, its port block is freed
app.save_pools({**app.load_pools(), "spread": pools.validate("spread", {"mule_version": "4.12.0", "nodes": {"local": 1, "node-b": 1}})})
app.reconcile("spread")
assert "mule-spread-node-b-2" not in world and list(app.load_nodes()["node-b"]["ports"]) == ["mule-spread-node-b-1"]
app.delete_app("spreadapp")
p2 = app.load_pools()
p2.pop("spread")
app.save_pools(p2)
app.reconcile("spread")
assert not any(c["pool"] == "spread" for c in world.values())
app.delete_node("node-b")
assert app.load_nodes() == {}

# API tokens: only the hash is stored; a good token authenticates
raw, t = app.create_token("ci")
assert raw.startswith("rm_") and raw not in open(f"{root}/data/tokens.json").read()
assert app.token_user(raw)["name"] == "ci" and app.token_user("rm_wrong") is None

# ---------- Maven: settings.xml repos + credentials, RELEASE/SNAPSHOT, update modes ----------
repo_dir = f"{root}/repo"
G = "com/acme/shop"


def put(path, data):
    os.makedirs(os.path.dirname(f"{repo_dir}/{path}"), exist_ok=True)
    open(f"{repo_dir}/{path}", "wb").write(data if isinstance(data, bytes) else data.encode())


def release_meta(release):
    put(f"secure/{G}/maven-metadata.xml", f"<metadata><versioning><release>{release}</release>"
        f"<latest>1.1.0-SNAPSHOT</latest></versioning></metadata>")


def snapshot_meta(n):
    put(f"secure/{G}/1.1.0-SNAPSHOT/maven-metadata.xml",
        "<metadata><versioning><snapshot><timestamp>20261009.120000</timestamp><buildNumber>%d</buildNumber></snapshot>"
        "<snapshotVersions><snapshotVersion><classifier>mule-application</classifier><extension>jar</extension>"
        "<value>1.1.0-20261009.120000-%d</value></snapshotVersion></snapshotVersions></versioning></metadata>" % (n, n))
    put(f"secure/{G}/1.1.0-SNAPSHOT/shop-1.1.0-20261009.120000-{n}-mule-application.jar", b"PK snap %d" % n)


release_meta("1.0.0")
put(f"secure/{G}/1.0.0/shop-1.0.0-mule-application.jar", b"PK v1.0.0")
snapshot_meta(3)


class Repo(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_head(self):  # /secure/ needs the credentials from settings.xml <servers>
        if self.path.startswith("/secure/") and self.headers.get("Authorization") != "Basic ZGV2OnMzY3JldA==":
            self.send_error(401)
            return None
        return super().send_head()


srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Repo, directory=repo_dir))
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ["REPO_PASS"] = "s3cret"
settings = f"""<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
  <servers><server><id>acme</id><username>dev</username><password>${{env.REPO_PASS}}</password></server></servers>
  <profiles><profile><id>p</id><repositories>
    <repository><id>central</id><url>{base}/central</url></repository>
    <repository><id>acme</id><url>{base}/secure</url><snapshots><enabled>true</enabled></snapshots></repository>
  </repositories></profile></profiles>
  <activeProfiles><activeProfile>p</activeProfile></activeProfiles>
</settings>"""
app.MAVEN_SETTINGS = f"{root}/settings.xml"
open(app.MAVEN_SETTINGS, "w").write(settings)

repos = app.maven_repos()
assert [r["id"] for r in repos] == ["central", "acme"] and repos[1]["auth"] == ("dev", "s3cret"), repos
info = app.resolve("com.acme", "shop", "RELEASE")
# credentials only over https (or loopback): a remote http:// repo gets no Authorization header
sent = []
real_urlopen, app.urllib.request.urlopen = app.urllib.request.urlopen, lambda req, timeout: sent.append(req) or 1
app._open({"url": "http://repo.example.com/x", "auth": ("dev", "s3cret")}, "a")
app._open({"url": "https://repo.example.com/x", "auth": ("dev", "s3cret")}, "a")
app.urllib.request.urlopen = real_urlopen
assert [r.has_header("Authorization") for r in sent] == [False, True], sent
# plain-http repos are not searched at all; a duplicate URL keeps the entry that has credentials
open(app.MAVEN_SETTINGS, "w").write(settings.replace("</repositories>",
    '<repository><id>plain</id><url>http://repo.example.com/m2</url></repository>'
    f'<repository><id>acme2</id><url>{base}/secure</url></repository></repositories>'))
assert [r["id"] for r in app.maven_repos()] == ["central", "acme"], app.maven_repos()
open(app.MAVEN_SETTINGS, "w").write(settings)
assert (info["version"], info["build"], info["repo"]["id"]) == ("1.0.0", "1.0.0", "acme"), info
assert app.resolve("com.acme", "shop", "1.1.0-SNAPSHOT")["build"] == "1.1.0-20261009.120000-3"
try:
    app.resolve("com.acme", "shop", "9.9.9")
    raise AssertionError("missing version must fail")
except LookupError:
    pass

# pinned 1.0.0 deploys with updates=notify; a newer release only shows as available until mode is auto
app.deploy("shop", {"pool": "default", "group": "com.acme", "artifact": "shop", "version": "1.0.0"})
assert app.load_meta("shop")["updates"] == "notify" and world["mule-default-1"]["apps"]["shop"]["_jar"] == b"PK v1.0.0"
release_meta("1.0.1")
put(f"secure/{G}/1.0.1/shop-1.0.1-mule-application.jar", b"PK v1.0.1")
m = app.check_app("shop")
assert m["available"] == {"version": "1.0.1", "build": "1.0.1"} and m["version"] == "1.0.0", m
app.deploy("shop", {"updates": "auto"})
m = app.check_app("shop")
assert (m["version"], m["available"]) == ("1.0.1", None) and world["mule-default-1"]["apps"]["shop"]["_jar"] == b"PK v1.0.1"
try:
    app.deploy("shop", {"updates": "sometimes"})
    raise AssertionError("bad update mode accepted")
except ValueError:
    pass
# moving version: SNAPSHOT defaults to auto and picks up a new timestamped build
app.deploy("snap", {"pool": "default", "group": "com.acme", "artifact": "shop", "version": "1.1.0-SNAPSHOT"})
assert app.load_meta("snap")["updates"] == "auto"
snapshot_meta(4)
assert app.check_app("snap")["build"] == "1.1.0-20261009.120000-4" and world["mule-default-1"]["apps"]["snap"]["_jar"] == b"PK snap 4"

# mirrors: mirrorOf="*,!acme" redirects central but leaves acme alone
open(app.MAVEN_SETTINGS, "w").write(settings.replace(
    "<profiles>", f"<mirrors><mirror><id>m</id><mirrorOf>*,!acme</mirrorOf><url>{base}/mirror</url></mirror></mirrors><profiles>"))
assert [(r["id"], r["url"].rsplit("/", 1)[1]) for r in app.maven_repos()] == [("m", "mirror"), ("acme", "secure")]
open(app.MAVEN_SETTINGS, "w").write(settings)

# seed: MULEAPP_* lands on the default pool once; a changed MULEAPP_VERSION redeploys
app.SEED = ("com.acme", "shop", "1.0.0")
app.delete_app("shop")
app.seed()
assert app.load_meta("shop")["seed"] == "1.0.0" and "shop" in world["mule-default-1"]["apps"]
world["mule-default-1"]["apps"].pop("shop")
app.seed()  # same .env: nothing
assert "shop" not in world["mule-default-1"]["apps"]
app.SEED = ("com.acme", "shop", "1.0.1")
app.seed()
assert world["mule-default-1"]["apps"]["shop"]["_jar"] == b"PK v1.0.1"

# delete: undeployed everywhere, route and state gone
app.delete_app("orders")
assert all("orders" not in c["apps"] for c in world.values()) and "rm-orders" not in open(app.APISIX_FILE).read()
srv.shutdown()

# ---------- app_states parses Mule's apps dir ----------
import importlib  # noqa: E402
importlib.reload(pools)  # the real app_states, over a faked exec
pools.exec_in = lambda c, cmd, timeout=0: (0, "a/\na-anchor.txt\nb.jar\nc/\ndefault/\n.d.jar.part\ne/\n--log--\n"
                                                "Started app 'c'\nFailed to deploy artifact 'c'\nFailed to deploy artifact [e]\nStarted app 'e'\n")
# c: dir, no anchor, last log line a failure -> FAILED; e: failed earlier, started since -> still deploying
assert pools.app_states("w") == {"a": "STARTED", "b": "DEPLOYING", "c": "FAILED", "e": "DEPLOYING"}, pools.app_states("w")
pools.exec_in = lambda c, cmd, timeout=0: (0, "x/\n--log--\n")
assert pools.app_states("w") == {"x": "DEPLOYING"}  # mid-deploy: no anchor yet, nothing in the log

# ---------- overview: root spans -> totals, error rate, per-endpoint/worker/tenant, time buckets ----------
now = 1_000_000_000_000_000


def trace(i, ms, status, worker, tenant=None, path="/api/v1/status"):
    tags = [{"key": "http.method", "value": "GET"}, {"key": "http.target", "value": path},
            {"key": "http.status_code", "value": status}] + ([{"key": "tenant.id", "value": tenant}] if tenant else [])
    if status >= 500:
        tags.append({"key": "otel.status_code", "value": "ERROR"})
    return {"traceID": f"t{i}", "processes": {"p1": {"tags": [{"key": "worker.id", "value": worker}]}},
            "spans": [{"spanID": "a", "processID": "p1", "operationName": "main", "startTime": now - (i + 1) * 60_000_000,
                       "duration": ms * 1000, "tags": tags, "references": []},
                      {"spanID": "b", "processID": "p1", "operationName": "child", "startTime": now, "duration": 1,
                       "tags": [], "references": [{"refType": "CHILD_OF", "spanID": "a"}]}]}


ts = [trace(i, 10 + i, 200, "worker-1", "acme") for i in range(8)] + \
     [trace(8, 500, 500, "worker-2", path="/api/v1/nope"), trace(9, 20, 404, "worker-2")]
o = app.summarize(ts, 60, now)
t = o["total"]
assert (t["count"], t["errors"]) == (10, 1) and abs(t["error_rate"] - 0.1) < 1e-9 and t["p99"] == 500, t
assert o["endpoints"][0]["endpoint"] == "GET /api/v1/status" and o["endpoints"][0]["count"] == 9
assert {w["worker"]: w["count"] for w in o["workers"]} == {"worker-1": 8, "worker-2": 2}
assert o["tenants"][0]["tenant"] == "acme" and o["tenants"][0]["count"] == 8
assert sum(b["count"] for b in o["series"]) == 10 and len(o["series"]) == 30
assert any(n["trace"] == "t8" for n in o["notable"])
# Jaeger v2 API v3 (OTLP JSON) -> same summary: root span = no parentSpanId, int attrs as strings, resource = worker
attr = lambda k, v: {"key": k, "value": {"intValue": str(v)} if isinstance(v, int) else {"stringValue": v}}  # noqa: E731
v3 = {"resourceSpans": [{"resource": {"attributes": [attr("worker.id", "mule-default-1"), attr("service.version", "1.0.17")]},
       "scopeSpans": [{"spans": [
           {"traceId": "x1", "spanId": "a", "name": "main", "startTimeUnixNano": str((now - 60_000_000) * 1000),
            "endTimeUnixNano": str((now - 60_000_000 + 7000) * 1000), "status": {"code": 2},
            "attributes": [attr("http.method", "GET"), attr("http.target", "/api/v1/x"), attr("http.status_code", 503)]},
           {"traceId": "x1", "spanId": "b", "parentSpanId": "a", "name": "child", "startTimeUnixNano": str(now * 1000),
            "endTimeUnixNano": str(now * 1000), "attributes": []}]}]}]}
o = app.summarize(app.v3_traces(v3), 60, now)
r = o["notable"][0]
assert o["total"]["count"] == 1 and o["total"]["errors"] == 1, o["total"]
assert (r["endpoint"], r["status"], r["ms"], r["worker"], r["version"]) == ("GET /api/v1/x", 503, 7, "mule-default-1", "1.0.17"), r
banner = "*" * 40 + "\nMessage               : /v1/nope\nElement : x\nError type            : APIKIT:NOT_FOUND\n" + "-" * 40
assert app.brief(banner) == "APIKIT:NOT_FOUND: /v1/nope" and app.brief("****\n\nplain line\nmore") == "plain line"

# ---------- sign-in: realm role required; login state is single-use ----------
tok = lambda c: "x." + app._b64url(json.dumps(c).encode()) + ".y"  # noqa: E731
u = app.user_from_tokens({"access_token": tok({"preferred_username": "ana", "realm_access": {"roles": ["admin"]}})})
assert u["user"] == "ana" and u["auth"] == "keycloak"
try:
    app.user_from_tokens({"access_token": tok({"preferred_username": "bob", "realm_access": {"roles": ["user"]}})})
    raise AssertionError("role must be required")
except PermissionError as e:
    assert "bob" in str(e)
state, url = app.login_url()
assert "code_challenge=" in url and f"state={state}" in url and state in app.PENDING
try:
    app.finish_login("forged", "code")
    raise AssertionError("unknown state must fail")
except PermissionError:
    pass

# ---------- openapi.json documents exactly the routes dispatch() serves ----------
import re  # noqa: E402

here = os.path.dirname(os.path.abspath(__file__))
spec = json.load(open(os.path.join(here, "openapi.json"), encoding="utf-8"))
documented = {(m.upper(), *[("*" if p.startswith("{") else p) for p in path.strip("/").split("/")])
              for path, item in spec["paths"].items() for m in item if m in ("get", "put", "post", "delete")}
src = open(os.path.join(here, "app.py"), encoding="utf-8").read()
routed = {tuple(re.findall(r'"([^"]+)"', k)) for k in re.findall(r'key == (\([^)]*\))', src)}
routed |= {("GET", *re.findall(r'"([^"]+)"', k)) for k in re.findall(r'method == "GET" and parts == (\[[^\]]*\])', src)}
routed -= {("GET", "api", "openapi.json"), ("GET", "api", "docs")}  # the docs themselves
assert documented == routed, f"undocumented: {routed - documented}, not routed: {documented - routed}"
for path, item in spec["paths"].items():  # every $ref resolves
    for r in re.findall(r'"\$ref": "#/([^"]+)"', json.dumps(item)):
        node = spec
        for k in r.split("/"):
            node = node[k]

shutil.rmtree(root)
print("ok")
