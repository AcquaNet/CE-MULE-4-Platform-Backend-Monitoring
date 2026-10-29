"""Self-check of the provisioned Grafana dashboards (no stack needed): python config/grafana/test_dashboards.py"""
import glob, json, os

here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "provisioning", "dashboards")
dash = {os.path.basename(f): json.load(open(f, encoding="utf-8")) for f in glob.glob(os.path.join(here, "*.json"))}
assert dash, "no dashboards"

# Mule JVM: filter by App (label job = the app's service.name) and Worker; every panel honours both
jvm = dash["mule-jvm.json"]
assert [v["name"] for v in jvm["templating"]["list"]] == ["app", "worker"]
assert "$app" in jvm["templating"]["list"][1]["query"]["query"], "Worker list should follow the chosen apps"
exprs = [t["expr"] for p in jvm["panels"] for t in p["targets"]]
assert exprs and all('job=~"$app"' in e and 'worker_id=~"$worker"' in e for e in exprs), exprs
# shared vs dedicated workers: the stat and the two tables lead the dashboard
titles = [p["title"] for p in jvm["panels"]]
assert titles[:3] == ["Shared workers", "Workers of the chosen apps", "Apps on those workers"], titles
shared = jvm["panels"][0]["targets"][0]["expr"]
assert "> 1" in shared and shared.endswith("or vector(0)"), shared  # 0 instead of "No data" when nothing is shared
assert all(p["gridPos"]["y"] >= 7 for p in jvm["panels"][3:]), "charts start below the tables"
print(f"test_dashboards: ok ({len(dash)} dashboards)")
