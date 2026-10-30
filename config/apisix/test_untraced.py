"""Self-check (no stack needed): python config/apisix/test_untraced.py
Gateway health checks carry X-Untraced (otel-mule4-agent >= 0.4.1 skips those requests), and every /api route clears a
client's own X-Untraced (else a caller could hide its requests from tracing)."""
import os, re

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "apisix.yaml"), encoding="utf-8").read()
checks = re.findall(r"\n    checks:\n      active:\n(?:        .*\n)+", src)
assert checks and all('"X-Untraced: health-check"' in c for c in checks), "every active health check sends X-Untraced"
strips = re.findall(r"ipairs\(\{([^}]*'X-Tenant-ID'[^}]*)\}\) do core\.request\.set_header\(ctx, h, nil\)", src)
assert len(strips) == 3 and all("'X-Untraced'" in s for s in strips), strips  # /api/v1/*, /api/*, plugin_config mule-api-auth
print("test_untraced: ok")
