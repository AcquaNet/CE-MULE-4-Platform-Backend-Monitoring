"""Self-check of the "Home" link global rule in apisix.yaml (no stack needed): python config/apisix/test_home_link.py
The page regex appears twice (Lua: which requests go uncompressed; response-rewrite vars: which get the link)."""
import os, re

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "apisix.yaml"), encoding="utf-8").read()
rule = src[src.index("global_rules:"):src.index("plugin_configs:")]
lua = re.search(r"ngx\.re\.find\(ngx\.var\.uri, \[\[(.+?)\]\]", rule).group(1)
var = re.search(r'\["uri", "~~", "(.+?)"\]', rule).group(1)
assert lua == var, (lua, var)
for uri, want in [("/jaeger/", True), ("/jaeger", True), ("/runtime-manager/apps", True), ("/dashboards/app/home", True),
                  ("/grafana/d/x", True), ("/auth/admin/mule/console/", True), ("/auth/realms/mule/account", True),
                  ("/auth/realms/mule/protocol/openid-connect/auth", False),  # sign-in pages: no link
                  ("/", False), ("/api/v1/status", False), ("/otlp/v1/traces", False), ("/dashboardsx", False)]:
    assert bool(re.search(var, uri)) == want, uri
assert 'id=\\"ce-home-link\\"' in rule and "</body>" in rule
print("test_home_link: ok")
