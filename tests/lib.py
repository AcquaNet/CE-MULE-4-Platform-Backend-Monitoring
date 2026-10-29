# Shared helpers for the live-stack tests (stdlib only; Playwright only where a test imports it).
# Run from anywhere: paths resolve from the repo root. Secrets come from the root .env and are never printed.
import base64, http.cookiejar, json, os, re, ssl, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
ENV = {k: v.strip().strip('"') for k, v in re.findall(r'^([A-Z_][A-Z0-9_]*)=(.*)$', open('.env', encoding='utf-8').read(), re.M)}
PROFILES = set(filter(None, ENV.get('COMPOSE_PROFILES', '').split(',')))
AUTH_ON = ENV.get('GATEWAY_AUTH', 'on') == 'on'
GW = 'https://localhost:9443'
LO = 'http://localhost:9080'            # loopback-only listener: /opensearch and the Keycloak master realm
RM = GW + '/runtime-manager'
CTX = ssl._create_unverified_context()  # the gateway cert is from the local CA; cert checks have their own test

fails = passes = skips = 0
_section = ''


def section(name):
    global _section
    _section = name
    print(f'\n=== {name} ===', flush=True)


def check(name, ok, detail=''):
    """One assertion: prints PASS/FAIL, never raises, so one failure doesn't hide the rest."""
    global fails, passes
    ok = bool(ok)
    fails += not ok
    passes += ok
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'   [{str(detail)[:300]}]'), flush=True)
    return ok


def skip(name, why):
    global skips
    skips += 1
    print(f'SKIP {name}   ({why})', flush=True)


def need(profile):
    """True if the compose profile is enabled in .env (tests of an off profile are skipped)."""
    return profile in PROFILES


def done():
    print(f'\n{passes} passed, {fails} failed, {skips} skipped', flush=True)
    sys.exit(1 if fails else 0)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a):
        return None


class Resp:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    @property
    def text(self):
        return self.body.decode('utf-8', 'replace')

    def json(self):
        return json.loads(self.body)


def http(method, url, body=None, headers=None, auth=None, token=None, follow=False, timeout=60, cookies=None):
    """Plain request. body: dict (JSON), bytes or str. auth: (user, pw) Basic. token: Bearer. Never raises on HTTP errors."""
    h = dict(headers or {})
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
        h.setdefault('Content-Type', 'application/json')
    elif isinstance(body, str):
        body = body.encode()
    if auth:
        h['Authorization'] = 'Basic ' + base64.b64encode(f'{auth[0]}:{auth[1]}'.encode()).decode()
    if token:
        h['Authorization'] = 'Bearer ' + token
    handlers = [urllib.request.HTTPSHandler(context=CTX)]
    if cookies is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(cookies))
    if not follow:
        handlers.append(NoRedirect)
    op = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url if url.startswith('http') else GW + url, data=body, headers=h, method=method)
    try:
        r = op.open(req, timeout=timeout)
        return Resp(r.status, r.headers, r.read())
    except urllib.error.HTTPError as e:
        return Resp(e.code, e.headers, e.read())
    except (urllib.error.URLError, OSError) as e:
        return Resp(0, {}, str(e).encode())


def get(url, **kw):
    return http('GET', url, **kw)


def kc_token(user, pw, client='mule-api-gateway', secret=None, scope='openid'):
    """Token response (dict) from realm mule via the password grant; {} on failure."""
    d = {'grant_type': 'password', 'client_id': client, 'username': user, 'password': pw, 'scope': scope}
    if client == 'mule-api-gateway':
        d['client_secret'] = secret or ENV['MULE_GATEWAY_CLIENT_SECRET']
    elif secret:
        d['client_secret'] = secret
    r = http('POST', '/auth/realms/mule/protocol/openid-connect/token', urllib.parse.urlencode(d),
             {'Content-Type': 'application/x-www-form-urlencoded'})
    return r.json() if r.status == 200 else {}


def admin_token():
    return kc_token('admin', ENV['KEYCLOAK_REALM_ADMIN_PASSWORD']).get('access_token', '')


def dev_token():
    return kc_token('developer', ENV['KEYCLOAK_REALM_DEV_PASSWORD']).get('access_token', '')


RM_AUTH = (ENV.get('RM_USER', 'admin'), ENV.get('RM_PASSWORD', ''))


def rm(method, path, body=None, **kw):
    """Runtime Manager API call with Basic RM_USER/RM_PASSWORD. path: 'api/...'."""
    kw.setdefault('auth', RM_AUTH)
    return http(method, f'{RM}/{path.lstrip("/")}', body, **kw)


def os_api(method, path, body=None, **kw):
    """OpenSearch through the gateway's loopback listener, as admin."""
    kw.setdefault('auth', ('admin', ENV['OPENSEARCH_ADMIN_PASSWORD']))
    return http(method, f'{LO}/opensearch/{path.lstrip("/")}', body, **kw)


def sh(cmd, timeout=600, input=None):
    """Run a command (list or str via bash); returns (code, stdout+stderr)."""
    env = dict(os.environ, MSYS_NO_PATHCONV='1')
    p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout,
                       input=input, env=env, encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def bash(script, timeout=600):
    """Run a bash snippet from the repo root (Git Bash on Windows)."""
    return sh(['bash', '-c', script], timeout=timeout)


def wait(fn, timeout=120, every=2, what=''):
    """Poll fn() until it returns truthy; returns the value or None on timeout."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        time.sleep(every)
    return None


def rm_app(name):
    r = rm('GET', 'api/apps')
    return next((a for a in r.json()['apps'] if a['name'] == name), None) if r.status == 200 else None


def rm_pool(name):
    r = rm('GET', 'api/pools')
    return next((p for p in r.json()['pools'] if p['name'] == name), None) if r.status == 200 else None


def wait_pool_ready(name, timeout=600):
    return wait(lambda: (p := rm_pool(name)) and p['status']['state'] == 'ready'
                and all(w['state'] == 'running' and w.get('health') == 'healthy' for w in p['workers'])
                and len(p['workers']) == p['replicas'] and p, timeout, 5)


def wait_app_started(name, timeout=600):
    return wait(lambda: (a := rm_app(name)) and a['workers'] and all(s == 'STARTED' for s in a['workers'].values()) and a,
                timeout, 5)


def launch(p):
    """Headless browser: the installed Chrome, else Playwright's Chromium (tests/run.sh installs it when needed)."""
    try:
        return p.chromium.launch(channel='chrome', headless=True)
    except Exception:
        return p.chromium.launch(headless=True)


def cleanup_rm(prefix):
    """Delete test apps and pools whose names start with prefix (apps first: a pool with apps can't be deleted)."""
    r = rm('GET', 'api/apps')
    for a in (r.json()['apps'] if r.status == 200 else []):
        if a['name'].startswith(prefix):
            rm('DELETE', f'api/apps/{a["name"]}')
    r = rm('GET', 'api/pools')
    for p in (r.json()['pools'] if r.status == 200 else []):
        if p['name'].startswith(prefix):
            wait(lambda: rm('DELETE', f'api/pools/{p["name"]}').status in (200, 204, 404), 120, 5)
