#!/bin/bash
# The whole test suite. Run from anywhere, with the platform up (./install.sh).
#   tests/run.sh            everything (~30 min: the Runtime Manager suites create pools and deploy apps)
#   tests/run.sh unit       self-tests only (no running stack needed, seconds)
#   tests/run.sh stack|api|ui|home   one live suite
# Output of each suite: tests/out/<suite>.log. Exit code 1 if any suite failed.
set -u
cd "$(dirname "$0")/.."
mkdir -p tests/out
export PYTHONIOENCODING=utf-8

# Python with Playwright for the browser suites (tests/.venv, created on first use)
if [ -x tests/.venv/Scripts/python ]; then PY=tests/.venv/Scripts/python; else PY=tests/.venv/bin/python; fi
browser_python() {
  if [ ! -x "$PY" ]; then
    "$SYS_PY" -m venv tests/.venv || return 1
    if [ -x tests/.venv/Scripts/python ]; then PY=tests/.venv/Scripts/python; else PY=tests/.venv/bin/python; fi
    "$PY" -m pip install -q -r tests/requirements.txt || return 1
  fi
  # installed Chrome is used when present; otherwise Playwright's own Chromium
  "$PY" -c "from playwright.sync_api import sync_playwright as s
with s() as p:
    try: p.chromium.launch(channel='chrome').close()
    except Exception: p.chromium.launch().close()" 2>/dev/null || "$PY" -m playwright install --with-deps chromium
}
SYS_PY=$(for p in python3 python; do "$p" -c "" 2>/dev/null && { echo "$p"; break; }; done)  # python3 may be a Windows Store stub

failed=()
run() {  # name, command...
  local name=$1; shift
  printf '\n\033[1m### %s\033[0m  (tests/out/%s.log)\n' "$name" "$name"
  if "$@" 2>&1 | tee "tests/out/$name.log" | grep -E '^(FAIL|SKIP|===)|passed, .* failed'; [ "${PIPESTATUS[0]}" -eq 0 ]; then
    printf '\033[32m%s: OK\033[0m\n' "$name"
  else
    printf '\033[31m%s: FAILED\033[0m\n' "$name"; failed+=("$name")
  fi
}

unit() {
  run unit-runtime-manager "$SYS_PY" mule/runtime-manager/test_app.py
  run unit-node-agent "$SYS_PY" node/agent/test_agent.py
  run unit-log-archiver "$SYS_PY" log-archiver/test_archiver.py
  run unit-generate-secrets bash config/scripts/setup/test_generate_secrets.sh
  run unit-apisix-home-link "$SYS_PY" config/apisix/test_home_link.py
  run unit-apisix-untraced "$SYS_PY" config/apisix/test_untraced.py
  run unit-grafana-dashboards "$SYS_PY" config/grafana/test_dashboards.py
  if command -v mvn >/dev/null; then run unit-otel-agent mvn -q -f otel-mule4-agent/pom.xml test; else echo "SKIP unit-otel-agent: no mvn"; fi
  run unit-compose bash -c 'docker compose --profile "*" config -q && for p in db mq logging tracing monitoring alerting opensearch-monitoring auth; do docker compose --profile "$p" config -q || exit 1; done && echo "compose files valid"'
  run unit-shell-syntax bash -c 'rc=0; while IFS= read -r f; do bash -n "$f" || rc=1; done < <(git ls-files "*.sh"); [ $rc = 0 ] && echo "all scripts parse"; exit $rc'
}

what=${1:-all}
case $what in
  unit) unit ;;
  stack) run stack "$SYS_PY" tests/test_stack.py ;;
  api) run rm-api "$SYS_PY" tests/test_rm_api.py ;;
  ui) browser_python && run rm-ui "$PY" tests/test_rm_ui.py ;;
  home) browser_python && run home-ui "$PY" tests/test_home_ui.py ;;
  all)
    unit
    run stack "$SYS_PY" tests/test_stack.py
    run rm-api "$SYS_PY" tests/test_rm_api.py
    browser_python || failed+=("playwright-setup")
    run home-ui "$PY" tests/test_home_ui.py
    run rm-ui "$PY" tests/test_rm_ui.py ;;
  *) echo "usage: tests/run.sh [all|unit|stack|api|ui|home]"; exit 2 ;;
esac

echo
if [ ${#failed[@]} -eq 0 ]; then printf '\033[32mALL SUITES PASSED\033[0m\n'; else printf '\033[31mFAILED: %s\033[0m\n' "${failed[*]}"; exit 1; fi
