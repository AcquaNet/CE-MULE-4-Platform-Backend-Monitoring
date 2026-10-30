"""Self-check of the "Home" link in apisix.yaml (no stack needed): python config/apisix/test_home_link.py
Global rule home-link: the page regex appears twice (Lua: which requests go uncompressed; response-rewrite vars: which
get the script), the rule inserts <script src="/home-link.js">, and route home-link-js serves that script (run in node
with a minimal DOM stand-in, config/apisix/test_home_link.js, when node is installed)."""
import os, re, shutil, subprocess, tempfile

here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "apisix.yaml"), encoding="utf-8").read()
rule = src[src.index("global_rules:"):src.index("plugin_configs:")]
lua = re.search(r"ngx\.re\.find\(ngx\.var\.uri, \[\[(.+?)\]\]", rule).group(1)
var = re.search(r'\["uri", "~~", "(.+?)"\]', rule).group(1)
assert lua == var, (lua, var)
for uri, want in [("/jaeger/", True), ("/jaeger", True), ("/runtime-manager/apps", True), ("/log-archiver/", True), ("/dashboards/app/home", True),
                  ("/grafana/d/x", True), ("/auth/admin/mule/console/", True), ("/auth/realms/mule/account", True),
                  ("/auth/realms/mule/protocol/openid-connect/auth", False),  # sign-in pages: no link
                  ("/", False), ("/api/v1/status", False), ("/otlp/v1/traces", False), ("/dashboardsx", False),
                  ("/home-link.js", False)]:
    assert bool(re.search(var, uri)) == want, uri
assert r'replace: "<script src=\"/home-link.js\"></script></body>"' in rule, "the rule inserts the script before </body>"

# route home-link-js: public GET (no plugin_config), the script as a mocking response
routes = src[:src.index("global_rules:")]
blk = routes[routes.index("name: home-link-js"):]
blk = blk[:blk.index("\n  - ")]
assert "methods: [GET]" in blk and "plugin_config_id" not in blk, "public static script"
# APISIX's mocking plugin refuses other content types and drops the whole route ("unsupported content type!")
ct = re.search(r'\n\s+content_type: "([^";]+)', blk).group(1)
assert ct in ("application/json", "application/xml", "text/plain", "text/html", "text/xml"), ct
assert 'Content-Type: "application/javascript' in blk, "response_headers must give the script a JS type"
body = blk[blk.index("response_example: |") + len("response_example: |"):]
js = "\n".join(line[10:] for line in body.splitlines()[1:])  # block scalar, 10 spaces of indent
assert "ce-home-link" in js and "documentElement.appendChild" in js

if shutil.which("node"):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js)
    r = subprocess.run(["node", os.path.join(here, "test_home_link.js"), f.name], capture_output=True, text=True,
                       encoding="utf-8")
    os.remove(f.name)
    assert r.returncode == 0, r.stdout + r.stderr
    print(r.stdout.strip())
else:
    print("SKIP home-link.js in node: node not installed")
print("test_home_link: ok")
