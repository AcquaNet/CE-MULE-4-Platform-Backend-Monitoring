"""Self-check of archiver.py (no OpenSearch needed): python config/log-archiver/test_archiver.py"""
import datetime, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archiver as a

D = datetime.date
today = D(2026, 10, 29)
names = ["mule-logs-2026.10.29", "mule-logs-2025.10.28", "mule-logs-2025.10.29", "logstash-2026.01.01",
         "jaeger-span-2026-09-28", "jaeger-span-2026-09-29", "jaeger-service-2026-10-28", ".kibana_1", "mule-logs-x"]
c = a.managed(names, today)
assert [n for _, _, n in c] == ["mule-logs-2025.10.28", "mule-logs-2025.10.29", "logstash-2026.01.01",
                                "jaeger-span-2026-09-28", "jaeger-span-2026-09-29", "jaeger-service-2026-10-28"], c
assert all(is_log == n.startswith(a.LOGS) for _, is_log, n in c)
# defaults: logs 365 days, traces 30; today's index, undated and foreign ones never show up
assert [n for _, _, n in a.expired(c, today)] == ["mule-logs-2025.10.28", "jaeger-span-2026-09-28"], a.expired(c, today)
# same day: the trace index (not archived) goes first
assert [n for _, _, n in a.managed(["mule-logs-2026.10.01", "jaeger-span-2026-10-01"], today)] == \
    ["jaeger-span-2026-10-01", "mule-logs-2026.10.01"]

# SigV4: AWS test suite vector get-vanilla
h = a.sigv4("GET", "example.amazonaws.com", "/", "20150830T123600Z",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "us-east-1",
            "AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", service="service")
assert h["Authorization"] == ("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
                              "SignedHeaders=host;x-amz-date, "
                              "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"), h

# archive: every scroll page lands in the gzip; a count mismatch leaves no archive and raises (the index is kept)
import gzip, json, tempfile
a.ARCHIVE = tempfile.mkdtemp()
def fake(count, pages):
    calls = iter(pages)
    def api(method, path, body=None):
        if path.endswith("/_count"):
            return {"count": count}
        if method == "DELETE":
            return {}
        return {"_scroll_id": "s", "hits": {"hits": [{"_source": s} for s in next(calls, [])]}}
    return api
a.api = fake(3, [[{"m": 1}, {"m": "é"}], [{"m": 3}]])
a.archive("mule-logs-2025.01.01")
with gzip.open(os.path.join(a.ARCHIVE, "mule-logs-2025.01.01.ndjson.gz"), "rt", encoding="utf-8") as f:
    assert [json.loads(l) for l in f] == [{"m": 1}, {"m": "é"}, {"m": 3}]
a.api = fake(5, [[{"m": 1}]])
try:
    a.archive("mule-logs-2025.01.02")
    raise AssertionError("short export must raise")
except RuntimeError:
    pass
assert os.listdir(a.ARCHIVE) == ["mule-logs-2025.01.01.ndjson.gz"], os.listdir(a.ARCHIVE)
print("test_archiver: ok")
