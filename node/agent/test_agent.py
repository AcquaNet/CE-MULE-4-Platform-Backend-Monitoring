"""Self-check: python test_agent.py (no Docker needed)."""
import json
from urllib.parse import parse_qs

import agent

agent.BIND_IP = "10.0.0.21"
agent.owned = lambda c, v: c.startswith("mule-")  # stand-in for the label check against Docker


def allowed(method, path, query="", body=None):
    try:
        return agent.authorize(method, path, parse_qs(query, keep_blank_values=True), body)
    except agent.Forbidden:
        return None


worker = {"Image": "ce-mule-runtime:4.12.0-java17-abc", "Labels": {"rm.pool": "default", "rm.spec": "x"},
          "Env": ["A=1"], "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}, "NetworkMode": "bridge",
                                         "PortBindings": {"8081/tcp": [{"HostPort": "18000"}]}}, "NetworkingConfig": {}}

# a Runtime Manager worker: allowed, ports pinned to the node's bind IP
path, body = allowed("POST", "/v1.41/containers/create", "name=mule-default-node-b-1", json.dumps(worker).encode())
assert path.startswith("/v1.41/containers/create?name=mule-default-node-b-1")
assert json.loads(body)["HostConfig"]["PortBindings"]["8081/tcp"][0]["HostIp"] == "10.0.0.21"

# anything else is refused
for bad_name, cfg in (("evil", worker),
                      ("mule-x", {**worker, "Image": "alpine"}),
                      ("mule-x", {**worker, "Labels": {}}),
                      ("mule-x", {**worker, "HostConfig": {**worker["HostConfig"], "Binds": ["/:/host"]}}),
                      ("mule-x", {**worker, "HostConfig": {**worker["HostConfig"], "Privileged": True}}),
                      ("mule-x", {**worker, "HostConfig": {**worker["HostConfig"], "NetworkMode": "host"}}),
                      ("mule-x", {**worker, "NetworkingConfig": {"EndpointsConfig": {"x": {}}}}),
                      ("mule-x", {**worker, "Volumes": {"/x": {}}})):
    assert allowed("POST", "/v1.41/containers/create", f"name={bad_name}", json.dumps(cfg).encode()) is None, cfg

# per-container calls only for Runtime Manager workers
assert allowed("POST", "/v1.41/containers/mule-default-1/exec")
assert allowed("PUT", "/v1.41/containers/mule-default-1/archive", "path=/opt")
assert allowed("DELETE", "/v1.41/containers/mule-default-1", "force=1")
assert allowed("POST", "/v1.41/containers/postgres/exec") is None
assert allowed("POST", "/v1.41/containers/mule-default-1/exec", body=b'{"Cmd": ["ls"], "AttachStdout": true}')
assert allowed("POST", "/v1.41/containers/mule-default-1/exec", body=b'{"Cmd": ["sh"], "Privileged": true}') is None
assert allowed("DELETE", "/v1.41/containers/apisix") is None
assert allowed("POST", "/v1.41/exec/" + "a" * 64 + "/start")

# images: runtime images only; listings are always filtered to Runtime Manager things
assert allowed("GET", "/v1.41/images/ce-mule-runtime%3A4.12.0-java17-abc/json")
assert allowed("DELETE", "/v1.41/images/alpine%3Alatest") is None
assert allowed("POST", "/v1.41/build", "t=ce-mule-runtime:4.12.0-java17-abc")
assert allowed("POST", "/v1.41/build", "t=evil:latest") is None
assert allowed("POST", "/v1.41/build", "t=ce-mule-runtime:x&rm=1&buildargs=%7B%7D")
assert allowed("POST", "/v1.41/build", "t=ce-mule-runtime:x&networkmode=host") is None
assert allowed("POST", "/v1.41/build", "t=ce-mule-runtime:x&t=ce-rm-node-agent:1.0") is None
assert allowed("POST", "/v1.41/build", "t=ce-mule-runtime:x&remote=http://evil/") is None
path, _ = allowed("GET", "/v1.41/containers/json", "all=1&filters=" + json.dumps({"label": ["other"]}))
assert json.loads(parse_qs(path.split("?", 1)[1])["filters"][0]) == {"label": ["rm.pool"]}
path, _ = allowed("GET", "/v1.41/images/json")
assert "ce-mule-runtime" in parse_qs(path.split("?", 1)[1])["filters"][0]

# not in the allowlist at all
for method, p in (("POST", "/v1.41/containers/mule-x/attach"), ("GET", "/v1.41/secrets"), ("POST", "/v1.41/swarm/init"),
                  ("POST", "/v1.41/networks/create"), ("POST", "/v1.41/images/create")):
    assert allowed(method, p) is None, p
print("ok")
