# Runtime Manager REST API against the LIVE stack: every route in openapi.json, its parameters and error
# paths, and the real side effects (worker containers, files inside workers, APISIX routes, gateway traffic).
# Complements mule/runtime-manager/test_app.py (in-process, fake Docker/Maven).
# Resources are prefixed t-api- and cleaned up at start and end. Run: python tests/test_rm_api.py
import sys, os; sys.path.insert(0, os.path.dirname(__file__)); from lib import *  # noqa: E401,E702,F403
import hashlib, html, json, re, secrets, shutil, tempfile, time, urllib.parse, zipfile  # noqa: E401
import http.cookiejar as cookiejar  # (not 'import http.cookiejar': that would shadow lib's http())
from datetime import datetime


class Stop(Exception):
    pass

T0 = time.time()
P = 't-api-'
POOL, NPOOL, NODE = 't-api-pool', 't-api-npool', 't-api-node'
MVN, JAR, BAD = 't-api-mvn', 't-api-jar', 't-api-bad'
W1, W2 = f'mule-{POOL}-1', f'mule-{POOL}-2'
NW = f'mule-{NPOOL}-{NODE}-1'
AGENT, AGENT_IMG = 't-api-node-agent', 't-api-node-agent:test'
# The node gets its own Docker daemon (docker-in-docker): an agent on the platform's Docker would list the
# platform's own workers as node workers and the RM would route them through the node from then on (see report).
DIND, DIND_VOL, DIND_IMG = 't-api-dind', 't-api-dind-run', 'mirror.gcr.io/library/docker:27-dind'
MULE = '/opt/mule/mule-standalone'
APPS = MULE + '/apps'
RMC = 'ce-base-runtime-manager'
JVM = ['-XX:+UseG1GC', '-XX:MaxGCPauseMillis=150', '-Dt.api.marker=yes']
SECRET, SECRET2 = 'tapi' + secrets.token_hex(12), 'tapi' + secrets.token_hex(12)
GHOST = 't-api-ghost'


# ---------- helpers ----------

def dexec(container, cmd, timeout=120):
    return sh(['docker', 'exec', container, 'sh', '-c', cmd], timeout=timeout)


def inspect(container):
    code, out = sh(['docker', 'inspect', container])
    return json.loads(out)[0] if code == 0 else None


def env_of(c):
    return dict(e.split('=', 1) for e in (c or {}).get('Config', {}).get('Env', []))


def ddocker(*args, timeout=600):
    return sh(['docker', 'exec', DIND, 'docker', *args], timeout=timeout)


def dinspect(container):
    code, out = ddocker('inspect', container, timeout=60)
    return json.loads(out)[0] if code == 0 else None


def local_workers_reachable():
    """Every running local rm.pool container is reached by the RM directly (its log endpoint execs in it)."""
    names = sh(['docker', 'ps', '--filter', 'label=rm.pool', '--format', '{{.Names}}'])[1].split()
    bad = {}
    for w in names:
        r = rm('GET', f'api/apps/x/log?worker={w}&source=runtime&bytes=1024')
        if r.status != 200:
            bad[w] = short(r)
    return names, bad


def exists(container):
    return sh(['docker', 'inspect', '--format', '{{.Id}}', container])[0] == 0


def short(r):
    return f'{r.status} {r.text[:200]}'


def err(r):
    try:
        return r.json().get('error', '')
    except Exception:
        return ''


def wclock(w):
    code, out = dexec(w, 'date +%s')
    return int(out.strip()) if code == 0 else int(time.time())


def anchor_mtime(w, app):
    code, out = dexec(w, f'stat -c %Y {APPS}/{app}-anchor.txt 2>/dev/null')
    return int(out.strip()) if code == 0 and out.strip().isdigit() else None


def apps_dir(w):
    return set(dexec(w, f'ls -1 {APPS}')[1].split())


def wait_fresh(app, workers, since, timeout=420):
    """The app was (re)deployed on every worker after `since` (container clock): anchor rewritten."""
    return wait(lambda: all((m := anchor_mtime(w, app)) and m >= since for w in workers), timeout, 5)


def deploy_props(w, app):
    return dexec(w, f'cat {MULE}/.mule/{app}/deployment-properties/deployment.properties')[1]


def apisix():
    return open('config/apisix/apisix.yaml', encoding='utf-8').read()


def rm_block(app):
    """The generated APISIX route lines of an app (from its '# rm-route' record to the next record/END)."""
    text = apisix()
    m = re.search(r'  # rm-route \{"app": "%s".*?(?=\n  # rm-route |\n  # END runtime-manager)' % re.escape(app), text, re.S)
    return m.group(0) if m else ''


def gw_status(path, token=None):
    return http('GET', path, token=token, timeout=20)


def app_up(path, version=None):
    def f():
        r = gw_status(path, admin_token())
        return r.status == 200 and (version is None or r.json().get('version') == version) and r
    return f


def rm_meta(app):
    code, out = sh(['docker', 'exec', RMC, 'cat', f'/data/artifacts/{app}.json'])
    try:
        return json.loads(out) if code == 0 else None
    except ValueError:
        return None


def rm_nodes_file():
    code, out = sh(['docker', 'exec', RMC, 'cat', '/data/nodes.json'])
    try:
        return json.loads(out) if code == 0 else {}
    except ValueError:
        return {}


def jcmd(w, what):
    return dexec(w, "p=$(jcmd -l | grep -i MuleContainerBootstrap | cut -d' ' -f1); jcmd $p " + what, 60)[1]


def pool_entry(name):
    return rm_pool(name)


def cleanup():
    cleanup_rm(P)
    wait(lambda: not any(p['name'].startswith(P) for p in rm('GET', 'api/pools').json()['pools']), 300, 5)
    wait(lambda: not sh(['docker', 'ps', '-aq', '--filter', 'name=mule-t-api-'])[1].strip(), 240, 5)
    left = sh(['docker', 'ps', '-aq', '--filter', 'name=mule-t-api-'])[1].split()
    if left:
        sh(['docker', 'rm', '-f', *left])
    r = rm('GET', 'api/nodes')
    for n in (r.json()['nodes'] if r.status == 200 else []):
        if n['name'].startswith(P):
            rm('DELETE', f'api/nodes/{n["name"]}')
    r = rm('GET', 'api/tokens')
    for t in (r.json()['tokens'] if r.status == 200 else []):
        if t['name'].startswith(P):
            rm('DELETE', f'api/tokens/{t["id"]}')
    sh(['docker', 'rm', '-f', AGENT])
    sh(['docker', 'rm', '-f', '-v', DIND])
    sh(['docker', 'volume', 'rm', '-f', DIND_VOL])


def patched_jar():
    """A real Mule app jar whose HTTP listener port comes from the property http.port (the stock app hard-codes
    8081, so two apps on one worker would clash), default 8093. Test fixture only, written to a temp dir."""
    src = 'git/CE-MULE-4-Platform-Backend-Mule/target/ce-mule-base-1.0.20-mule-application.jar'
    tmpdir = tempfile.mkdtemp(prefix='t-api-')
    if not os.path.exists(src):
        src = os.path.join(tmpdir, 'orig.jar')
        sh(['docker', 'cp', f'{RMC}:/data/artifacts/ce-mule-base.jar', src])
    out = os.path.join(tmpdir, 't-api-jar.jar')
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zo:
        for item in zi.infolist():
            data = zi.read(item.filename)
            if item.filename == 'global-config.xml':
                data = data.replace(b'port="8081"', b'port="${http.port}"')
            elif item.filename == 'config/local-docker.properties':
                data = re.sub(rb'(?m)^http\.port=.*$', b'http.port=8093', data)
            zo.writestr(item, data)
    data = open(out, 'rb').read()
    return data, tmpdir


def kc_login(user, pw):
    """Browser sign-in: /login -> Keycloak form -> /callback. Returns (cookie jar, callback response, login resp)."""
    jar = cookiejar.CookieJar()
    r = http('GET', RM + '/login', cookies=jar)
    loc = r.headers.get('Location', '') if r.status == 302 else ''
    if not loc:
        return jar, r, r
    r2 = http('GET', loc, cookies=jar)
    m = re.search(r'<form[^>]*action="([^"]+)"', r2.text)
    if not m:
        return jar, r2, r
    r3 = http('POST', html.unescape(m.group(1)), urllib.parse.urlencode({'username': user, 'password': pw, 'credentialId': ''}),
              {'Content-Type': 'application/x-www-form-urlencoded'}, cookies=jar)
    cb = r3.headers.get('Location', '') if r3.status == 302 else ''
    if not cb.startswith(RM + '/callback'):
        return jar, r3, r
    return jar, http('GET', cb, cookies=jar), r


# ---------- run ----------

orig_settings = rm('GET', 'api/settings').json() if rm('GET', 'api/settings').status == 200 else {'check_minutes': 5}
jar_tmp = None
section('Cleanup (start)')
cleanup()
check('no t-api- pools/apps left from an earlier run', not any(a['name'].startswith(P) for a in rm('GET', 'api/apps').json()['apps']))
spec = json.loads(get(RM + '/api/openapi.json').body or b'{}')
token = token_id = None
try:
    # ======================================================================
    section('Public docs')
    r = get(RM + '/api/openapi.json')
    check('GET /api/openapi.json without auth: 200 JSON', r.status == 200 and 'openapi' in r.json() and r.json().get('paths'), short(r))
    check('openapi servers are relative', all(not s.get('url', '').startswith('http') for s in spec.get('servers', [])), spec.get('servers'))
    r = get(RM + '/api/docs')
    check('GET /api/docs without auth: 200 HTML', r.status == 200 and 'text/html' in r.headers.get('Content-Type', ''), short(r))

    # every documented route with placeholder names (no side effects: each one ends in a 4xx or a read)
    SUB = {'{app}': GHOST, '{pool}': GHOST, '{node}': GHOST, '{id}': 'ffffffffffff'}
    routes = []
    for path, ops in spec.get('paths', {}).items():
        for meth in ops:
            if meth in ('get', 'put', 'post', 'delete'):
                p = path
                for k, v in SUB.items():
                    p = p.replace(k, v)
                routes.append((meth.upper(), p.lstrip('/'), path))
    check('openapi documents >= 23 operations', len(routes) >= 23, len(routes))

    section('Precondition: the RM reaches every local worker directly')
    names, bad = local_workers_reachable()
    check(f'RM execs into all {len(names)} local pool workers (none routed through a node)', not bad, bad)
    if bad:
        raise Stop('local workers are routed through a node (stale worker->node map, see report): every deploy/undeploy '
                   'touches all workers and fails; restart the Runtime Manager and rerun')

    # ======================================================================
    section('Auth: every API route refuses missing/wrong credentials')
    akc, dkc = admin_token(), dev_token()
    check('Keycloak tokens for admin and developer obtained', akc and dkc)
    bad = {'none': {}, 'wrong Basic password': {'auth': (RM_AUTH[0], RM_AUTH[1] + 'x')},
           'wrong Basic user': {'auth': ('nobody', RM_AUTH[1])},
           'Keycloak bearer (realm admin)': {'token': akc}, 'Keycloak bearer (developer)': {'token': dkc},
           'unknown rm_ token': {'token': 'rm_' + secrets.token_urlsafe(32)}}
    for label, kw in bad.items():
        res = [(m, p, http(m, f'{RM}/{p}', {} if m in ('PUT', 'POST') else None, **kw)) for m, p, _ in routes + [('GET', 'api/nope', '')]]
        wrong = [(m, p, r.status) for m, p, r in res if r.status != 401]
        check(f'{label}: 401 on all {len(res)} API routes', not wrong, wrong[:5])
    r = get(RM + '/api/apps')
    check('401 is JSON "sign in required" with no Basic challenge (Keycloak sign-in on)',
          r.status == 401 and err(r) == 'sign in required' and 'WWW-Authenticate' not in r.headers, short(r))
    r = rm('GET', 'api/me')
    me = r.json() if r.status == 200 else {}
    check('Basic RM_USER: GET /api/me 200, auth=basic, no logout link',
          me.get('auth') == 'basic' and me.get('user') == RM_AUTH[0] and me.get('logout') is False, short(r))
    check('/api/me shape: user,name,email,auth,logout,jaeger,secure', set(me) == {'user', 'name', 'email', 'auth', 'logout', 'jaeger', 'secure'}
          and me.get('secure') is True and me.get('jaeger', '').endswith('/jaeger'), me)

    section('Routing: every documented operation is served, unknown paths 404')
    for m, p, doc in routes:
        r = rm(m, p, {} if m in ('PUT', 'POST') else None)
        check(f'{m} {doc} is routed ({r.status})', r.status not in (0, 405, 501) and not (r.status == 404 and err(r) == 'not found'), short(r))
    for m, p in [('GET', 'api/nope'), ('GET', 'api'), ('POST', 'api/apps'), ('GET', f'api/apps/{GHOST}/nope'),
                 ('DELETE', 'api/settings'), ('GET', 'api/pools/x/y/z')]:
        r = rm(m, p, {} if m in ('PUT', 'POST') else None)
        check(f'{m} /{p}: 404 not found', r.status == 404 and err(r) == 'not found', short(r))
    r = rm('PATCH', 'api/apps')
    check('unsupported method PATCH: 501 (not served)', r.status == 501, short(r))
    for p in ['api/apps/Bad_Name', 'api/pools/UPPER', 'api/nodes/a_b']:
        r = rm('GET' if 'apps' in p else 'DELETE', p + ('/properties' if 'apps' in p else ''))
        check(f'bad resource name /{p}: 400 bad name', r.status == 400 and err(r) == 'bad name', short(r))

    # ======================================================================
    section('Browser session (Keycloak code flow + PKCE)')
    r = get(RM + '/')
    check('GET /runtime-manager/ signed out: sign-in page (200 HTML)', r.status == 200 and 'text/html' in r.headers.get('Content-Type', ''), short(r))
    jar, cb, login = kc_login('admin', ENV['KEYCLOAK_REALM_ADMIN_PASSWORD'])
    loc = login.headers.get('Location', '') if login.status == 302 else ''
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))
    check('/login redirects to the realm mule authorize endpoint',
          loc.startswith(GW + '/auth/realms/mule/protocol/openid-connect/auth'), short(login))
    check('authorize request: client runtime-manager, code flow, PKCE S256, state, callback',
          q.get('client_id') == 'runtime-manager' and q.get('response_type') == 'code' and q.get('code_challenge_method') == 'S256'
          and q.get('code_challenge') and q.get('state') and q.get('redirect_uri') == RM + '/callback', q)
    sc = login.headers.get('Set-Cookie', '') if login.status == 302 else ''
    check('rm_state cookie: HttpOnly, SameSite=Lax, Secure, Path=/runtime-manager/',
          sc.startswith('rm_state=') and all(x in sc for x in ('HttpOnly', 'SameSite=Lax', 'Secure', 'Path=/runtime-manager/')), sc[:40])
    check('callback (admin) redirects home with an rm_session cookie',
          cb.status == 302 and cb.headers.get('Location') == '/runtime-manager/' and any(c.name == 'rm_session' for c in jar), short(cb))
    r = http('GET', RM + '/api/me', cookies=jar)
    sme = r.json() if r.status == 200 else {}
    check('/api/me with session: auth=keycloak, user admin, logout link', sme.get('auth') == 'keycloak' and sme.get('user') == 'admin'
          and sme.get('logout') is True, short(r))
    r = http('GET', RM + '/api/pools', cookies=jar)
    check('session works on the API (GET /api/pools 200)', r.status == 200, short(r))
    r = http('GET', RM + '/', cookies=jar)
    check('GET / with session: the app page (not the sign-in page)', r.status == 200 and r.body != get(RM + '/').body, short(r))
    r = http('GET', RM + '/logout', cookies=jar)
    lo = r.headers.get('Location', '')
    check('/logout: redirect to Keycloak end-session with id_token_hint, cookie cleared',
          r.status == 302 and '/auth/realms/mule/protocol/openid-connect/logout' in lo and 'id_token_hint=' in lo
          and 'rm_session=;' in (r.headers.get('Set-Cookie') or '').replace('rm_session="";', 'rm_session=;'), lo[:120])
    r = http('GET', RM + '/api/me', cookies=jar)
    check('after logout the session is gone (401)', r.status == 401, short(r))
    djar, dcb, _ = kc_login('developer', ENV['KEYCLOAK_REALM_DEV_PASSWORD'])
    check('developer (no realm role admin) is refused at callback (redirect ?error=..., no session)',
          dcb.status == 302 and '?error=' in dcb.headers.get('Location', '') and 'admin' in urllib.parse.unquote(dcb.headers.get('Location', ''))
          and not any(c.name == 'rm_session' and c.value for c in djar), short(dcb))
    check('developer: /api/me 401', http('GET', RM + '/api/me', cookies=djar).status == 401)
    r = get(RM + '/callback?state=bogus&code=x')
    check('callback with a state that was not started here: redirect ?error=, no session',
          r.status == 302 and '?error=' in r.headers.get('Location', '') and 'rm_session' not in (r.headers.get('Set-Cookie') or ''), short(r))

    # ======================================================================
    section('API tokens')
    for body, why in [({}, 'missing'), ({'name': ''}, 'empty'), ({'name': '   '}, 'blank')]:
        r = rm('POST', 'api/tokens', body)
        check(f'POST /api/tokens name {why}: 400', r.status == 400, short(r))
    r = rm('POST', 'api/tokens', {'name': P + 'long-' + 'x' * 100})
    check('token name is cut to 60 characters', r.status == 200 and len(r.json().get('name', '')) == 60, short(r))
    r = rm('POST', 'api/tokens', {'name': P + 'pipeline'})
    t = r.json() if r.status == 200 else {}
    token, token_id = t.get('token', ''), t.get('id')
    check('POST /api/tokens: rm_ token returned once, id/name/created, last_used null, no hash',
          token.startswith('rm_') and token_id and t.get('name') == P + 'pipeline' and t.get('created') and t.get('last_used') is None
          and 'hash' not in t, {k: v for k, v in t.items() if k != 'token'})
    r = rm('GET', 'api/tokens')
    lst = r.json().get('tokens', []) if r.status == 200 else []
    mine = next((x for x in lst if x['id'] == token_id), {})
    check('GET /api/tokens lists it without hash or token value', mine and all('hash' not in x and 'token' not in x for x in lst), short(r))
    code, tj = sh(['docker', 'exec', RMC, 'cat', '/data/tokens.json'])
    check('tokens.json stores only the SHA-256 (raw token not at rest)',
          token and token not in tj and hashlib.sha256(token.encode()).hexdigest() in tj, 'raw token found or hash missing')
    for p in ['api/me', 'api/apps', 'api/pools', 'api/nodes', 'api/settings', 'api/runtime/versions', f'api/apps/{GHOST}/overview']:
        r = http('GET', f'{RM}/{p}', token=token)
        check(f'token Bearer: GET /{p} 200', r.status == 200, short(r))
    r = http('GET', f'{RM}/api/me', token=token)
    check('/api/me with token: auth=token, user token:<name>, no logout', r.status == 200 and r.json()['auth'] == 'token'
          and r.json()['user'] == f'token:{P}pipeline' and r.json()['logout'] is False, short(r))
    r = http('POST', f'{RM}/api/pools/{GHOST}/reconcile', token=token)
    check('token Bearer can call write routes (POST reconcile of unknown pool -> 404, not 401)', r.status == 404, short(r))
    for m, p in [('GET', 'api/tokens'), ('POST', 'api/tokens'), ('DELETE', f'api/tokens/{token_id}')]:
        r = http(m, f'{RM}/{p}', {'name': P + 'minted'} if m == 'POST' else None, token=token)
        check(f'token cannot manage tokens: {m} /{p} 403', r.status == 403, short(r))
    mine = next((x for x in rm('GET', 'api/tokens').json()['tokens'] if x['id'] == token_id), {})
    check('last_used is set after the token was used', bool(mine.get('last_used')), mine)
    check('the token is still there (its own DELETE was refused)', bool(mine))

    # ======================================================================
    section('Settings')
    r = rm('GET', 'api/settings')
    check('GET /api/settings: {check_minutes: int}', r.status == 200 and isinstance(r.json().get('check_minutes'), int), short(r))
    for v in [-1, 10081, 'abc']:
        r = rm('PUT', 'api/settings', {'check_minutes': v})
        check(f'PUT /api/settings check_minutes={v!r}: 400', r.status == 400, short(r))
    check('settings unchanged after the refused values', rm('GET', 'api/settings').json() == orig_settings)
    # 0 (lowest valid) and a normal value; 10080 is valid too but would make the update poller sleep a week if
    # it read the value in that instant, so the upper bound is only checked via 10081 above
    for v in [0, 7]:
        r = rm('PUT', 'api/settings', {'check_minutes': v})
        check(f'PUT /api/settings check_minutes={v}: 200, stored', r.status == 200 and r.json()['check_minutes'] == v
              and rm('GET', 'api/settings').json()['check_minutes'] == v, short(r))
    r = rm('PUT', 'api/settings', orig_settings)
    check('settings restored', r.status == 200 and rm('GET', 'api/settings').json() == orig_settings, short(r))

    # ======================================================================
    section('Runtime versions')
    r = rm('GET', 'api/runtime/versions')
    rv = r.json() if r.status == 200 else {}
    versions_ok = bool(rv.get('versions'))
    check('GET /api/runtime/versions: versions newest first, release, java per version',
          versions_ok and '4.12.0' in rv['versions'] and rv['versions'] == sorted(rv['versions'], key=lambda v: tuple(map(int, v.split('.'))), reverse=True)
          and rv.get('release') and rv['java'].get('4.12.0') == ['17'] and rv['java'].get('4.4.0') == ['8', '11']
          and rv['java'].get('4.6.0') == ['8', '11', '17'], short(r))

    # ======================================================================
    section('Pools: validation (nothing saved)')
    base = {'mule_version': '4.12.0', 'java_version': '17', 'heap_mb': 512, 'replicas': 1, 'jvm_options': JVM}
    cases = [
        ('Upper_Case', base, 'bad name'), (P + 'x' * 30, base, 'name longer than 30'),
        (P + 'v', {**base, 'mule_version': '4.99.0'}, 'unknown Mule version'),
        (P + 'v', {**base, 'java_version': '8'}, 'Java 8 on Mule 4.12'),
        (P + 'v', {**base, 'mule_version': '4.4.0', 'java_version': '17'}, 'Java 17 on Mule 4.4'),
        (P + 'v', {**base, 'heap_mb': 255}, 'heap 255'), (P + 'v', {**base, 'heap_mb': 65537}, 'heap 65537'),
        (P + 'v', {**base, 'heap_mb': 'lots'}, 'heap not a number'),
        (P + 'v', {**base, 'jvm_options': ['-Xss1m -Xmx9g']}, 'JVM option with a space'),
        (P + 'v', {**base, 'jvm_options': ['Xss1m']}, 'JVM option without dash'),
        (P + 'v', {**base, 'jvm_options': ['-Dx=$(id)']}, 'JVM option with shell chars'),
        (P + 'v', {**base, 'nodes': [1]}, 'nodes not a map'),
        (P + 'v', {**base, 'nodes': {'Bad_Node': 1}}, 'bad node name'),
        (P + 'v', {**base, 'nodes': {'local': 21}}, '21 workers on a node'),
        (P + 'v', {**base, 'nodes': {'local': 1, P + 'ghost-node': 1}}, 'unregistered node'),
        (P + 'v', {**base, 'replicas': 'two'}, 'replicas not a number'),
    ]
    if not versions_ok:
        cases = [c for c in cases if 'unknown Mule' not in c[2]]
        skip('unknown Mule version refused', 'MuleSoft repo unreachable: RM trusts any version then')
    for name, body, why in cases:
        r = rm('PUT', f'api/pools/{name}', body)
        check(f'PUT pool, {why}: 400', r.status == 400, short(r))
    check('no t-api-v pool saved', not rm_pool(P + 'v'))

    # ======================================================================
    section('Pools: create t-api-pool (4.12.0 / Java 17, 1 worker, heap 512)')
    r = rm('PUT', f'api/pools/{POOL}', {**base, 'nodes': {'local': 1}, 'replicas': 3})
    pj = r.json() if r.status == 200 else {}
    check('PUT /api/pools/t-api-pool: 200 with the normalized spec (nodes wins over replicas)',
          pj.get('pool') == POOL and pj.get('nodes') == {'local': 1} and pj.get('replicas') == 1 and pj.get('heap_mb') == 512
          and pj.get('jvm_options') == JVM and pj.get('java_version') == '17', short(r))
    p = rm_pool(POOL)
    check('pool listed right away with a status', p and p['status']['state'] in ('pending', 'working', 'ready'), p and p['status'])
    p = wait_pool_ready(POOL, 600)
    check('pool ready, 1 worker running+healthy', p and [w['name'] for w in p['workers']] == [W1], p and p['status'])
    if not p:
        raise Stop('pool did not become ready')
    check('GET /api/pools shape: name, spec, workers[], apps[], status', all(k in p for k in
          ('name', 'mule_version', 'java_version', 'heap_mb', 'nodes', 'replicas', 'jvm_options', 'workers', 'apps', 'status'))
          and set(p['workers'][0]) >= {'name', 'pool', 'spec', 'state', 'health', 'node'} and p['workers'][0]['node'] == 'local')
    c1 = inspect(W1)
    e = env_of(c1)
    check('worker labels: rm.pool=t-api-pool, rm.spec = the API spec hash',
          c1['Config']['Labels'].get('rm.pool') == POOL and c1['Config']['Labels'].get('rm.spec') == p['workers'][0]['spec'])
    check('worker image ce-mule-runtime:4.12.0-java17-*', c1['Config']['Image'].startswith('ce-mule-runtime:4.12.0-java17-'), c1['Config']['Image'])
    check('worker env: MULE_ARGS carries the JVM options as -M args', e.get('MULE_ARGS') == ' '.join('-M' + o for o in JVM), e.get('MULE_ARGS'))
    check('worker env: heap 256 initial / 512 max, WORKER_ID', e.get('MULE_INIT_HEAP_MB') == '256' and e.get('MULE_MAX_HEAP_MB') == '512'
          and e.get('WORKER_ID') == W1)
    check('worker env: OTEL_* (jaeger, worker.id, rm.pool)', e.get('OTEL_EXPORTER_OTLP_ENDPOINT') == 'http://jaeger:4317'
          and f'worker.id={W1}' in e.get('OTEL_RESOURCE_ATTRIBUTES', '') and f'rm.pool={POOL}' in e.get('OTEL_RESOURCE_ATTRIBUTES', '')
          and e.get('OTEL_TRACES_EXPORTER') == 'otlp', {k: v for k, v in e.items() if k.startswith('OTEL_') and 'HEADERS' not in k})
    check('worker on ce-base-micronet + ce-base-network, healthcheck set, restart unless-stopped',
          set(c1['NetworkSettings']['Networks']) >= {'ce-base-micronet', 'ce-base-network'} and c1['Config'].get('Healthcheck')
          and c1['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped')
    flags = jcmd(W1, 'VM.flags')
    check('jcmd VM.flags: MaxHeapSize = 512 MB', '-XX:MaxHeapSize=536870912' in flags, flags[:200])
    check('jcmd VM.flags: JVM options applied (UseG1GC, MaxGCPauseMillis=150)', '+UseG1GC' in flags and 'MaxGCPauseMillis=150' in flags, flags[:200])
    check('jcmd VM.system_properties: -Dt.api.marker=yes', 't.api.marker=yes' in jcmd(W1, 'VM.system_properties'))

    id1 = c1['Id']
    r = rm('POST', f'api/pools/{POOL}/reconcile')
    check('POST /api/pools/t-api-pool/reconcile: queued', r.status == 200 and r.json() == {'queued': POOL}, short(r))
    time.sleep(3)
    check('after reconcile: ready again, unchanged worker not replaced', wait_pool_ready(POOL, 300) and inspect(W1)['Id'] == id1)
    r = rm('POST', f'api/pools/{GHOST}/reconcile')
    check('reconcile unknown pool: 404', r.status == 404, short(r))

    # ======================================================================
    section('Apps: validation errors (nothing half-deployed)')
    def nothing_left(name):
        code, out = sh(['docker', 'exec', RMC, 'sh', '-c', f'ls /data/artifacts/{name}.* 2>/dev/null'])
        return not rm_app(name) and not out.strip() and f'"app": "{name}"' not in apisix()
    good_route = {'path': '/' + BAD, 'port': 8081}
    cases = [
        ('Bad_App', {'pool': POOL}, 'bad name', 400),
        ('a' * 64, {'pool': POOL}, '64-char name', 400),
        (BAD, {'pool': P + 'no-such-pool', 'group': 'com.acqua', 'artifact': 'ce-mule-base', 'version': '1.0.19'}, 'unknown pool', 400),
        (BAD, {'pool': POOL, 'route': {'path': '/auth/x'}}, 'route /auth/x (platform)', 400),
        (BAD, {'pool': POOL, 'route': {'path': '/runtime-manager'}}, 'route /runtime-manager (platform)', 400),
        (BAD, {'pool': POOL, 'route': {'path': '/jaeger/x'}}, 'route /jaeger/x (platform)', 400),
        (BAD, {'pool': POOL, 'route': {'path': 'orders'}}, 'route without leading slash', 400),
        (BAD, {'pool': POOL, 'route': {'path': '/a b'}}, 'route with a space', 400),
        (BAD, {'pool': POOL, 'route': {'path': '/' + BAD, 'port': 'http'}}, 'route port not a number', 400),
        (BAD, {'pool': POOL, 'updates': 'sometimes', 'route': good_route}, 'updates mode unknown', 400),
        (BAD, {'pool': POOL, 'workers': 0}, 'workers 0', 400),
        (BAD, {'pool': POOL, 'workers': True}, 'workers true', 400),
        (BAD, {'pool': POOL, 'workers': {'a': 1}}, 'workers a map', 400),
        (BAD, {'pool': POOL, 'workers': ['mule-nope-1']}, 'workers not in the pool', 400),
        (BAD, {'pool': POOL, 'properties': {'bad key': 'x'}}, 'property name with a space', 400),
        (BAD, {'pool': POOL, 'secureProperties': {'s': None}}, 'secure null without a stored value', 400),
        (BAD, {'pool': POOL}, 'no jar, no Maven coordinates', 400),
        (BAD, {'pool': POOL, 'group': 'com.acqua', 'artifact': 'ce-mule-base'}, 'Maven artifact without version', 400),
    ]
    for name, body, why, want in cases:
        r = rm('PUT', f'api/apps/{name}', body)
        check(f'PUT app, {why}: {want}', r.status == want, short(r))
    for body, why in [({'pool': POOL, 'group': 'com.acqua', 'artifact': 't-api-does-not-exist', 'version': '1.0.0'}, 'unknown artifact'),
                      ({'pool': POOL, 'group': 'com.acqua', 'artifact': 'ce-mule-base', 'version': '0.0.1'}, 'unknown version')]:
        r = rm('PUT', f'api/apps/{BAD}', body)
        check(f'PUT app, Maven {why}: error with "not found in any repository"', r.status in (400, 404) and 'not found in any repository' in err(r), short(r))
        documented = set(spec['paths']['/api/apps/{app}']['put'].get('responses', {}))
        check(f'PUT app, Maven {why}: status {r.status} documented in openapi ({sorted(documented)})', str(r.status) in documented, short(r))
    r = rm('PUT', f'api/apps/{BAD}?pool={POOL}', b'this is not a jar', headers={'Content-Type': 'application/java-archive'})
    check('PUT app with a non-jar body: 400 not a jar', r.status == 400 and 'jar' in err(r), short(r))
    # route rules that would hijack gateway traffic / produce an invalid upstream; probed on an app with no jar:
    # if the route is validated the error names it, else the request only fails later on "no jar uploaded"
    for path in ('/api', '/sso', '/logout'):  # the gateway's own routes (/api/* = default app); /api/<name> stays allowed
        r = rm('PUT', f'api/apps/{BAD}', {'pool': POOL, 'route': {'path': path}})
        check(f'route {path} refused (gateway route)', r.status == 400 and 'no jar' not in err(r), short(r))
    r = rm('PUT', f'api/apps/{BAD}', {'pool': POOL, 'route': {'path': '/api/orders'}})
    check('route /api/orders passes route validation (longer prefix, allowed)', r.status == 400 and 'no jar' in err(r), short(r))
    for port in (70000, -5):
        r = rm('PUT', f'api/apps/{BAD}', {'pool': POOL, 'route': {'path': '/' + BAD, 'port': port}})
        check(f'route port {port} refused (out of 1..65535)', r.status == 400 and 'no jar' not in err(r), short(r))
    check('nothing left of t-api-bad (no app, no stored files, no route)', nothing_left(BAD))
    check('nothing left of Bad_App', not rm_app('Bad_App'))

    # ======================================================================
    section('Apps: deploy t-api-mvn from Maven (pinned 1.0.19, notify, properties, secure, route)')
    # the app hard-codes its HTTP listener to 8081 (global-config.xml), so http.port is only a plain property here
    # and the route points at 8081; the property-driven port is exercised with t-api-jar below
    body = {'pool': POOL, 'group': 'com.acqua', 'artifact': 'ce-mule-base', 'version': '1.0.19', 'updates': 'notify',
            'properties': {'http.port': '8091', 't.plain': 'hello'}, 'secureProperties': {'t.secret': SECRET},
            'route': {'path': '/' + MVN, 'port': 8081}}
    r = rm('PUT', f'api/apps/{MVN}', body, timeout=300)
    check('PUT /api/apps/t-api-mvn: 200 deployed on the pool worker', r.status == 200 and r.json() == {'deployed': MVN, 'pool': POOL, 'workers': [W1]}, short(r))
    check('SECRET not echoed in the response', SECRET not in r.text)
    a = wait_app_started(MVN, 420)
    check('t-api-mvn STARTED on mule-t-api-pool-1', a and a['workers'] == {W1: 'STARTED'}, a and a['workers'])
    a = rm_app(MVN) or {}
    check('GET /api/apps entry: pool, runtime, targets, placement, route, updates, property names',
          a.get('pool') == POOL and a.get('runtime') == {'mule_version': '4.12.0', 'java_version': '17'} and a.get('targets') == [W1]
          and a.get('placement') is None and a.get('route') == {'path': '/' + MVN, 'port': 8081} and a.get('updates') == 'notify'
          and a.get('deployed') and a.get('properties') == ['http.port', 't.plain'] and a.get('secure') == ['t.secret'], a)
    mv = a.get('maven') or {}
    check('GET /api/apps maven info: coords, build 1.0.19, nothing available yet', mv.get('group') == 'com.acqua'
          and mv.get('artifact') == 'ce-mule-base' and mv.get('version') == '1.0.19' and mv.get('build') == '1.0.19' and not mv.get('error'), mv)
    la = rm('GET', 'api/apps').json()
    check('GET /api/apps top level: pools includes t-api-pool, routing true', POOL in la['pools'] and la['routing'] is True)
    check('GET /api/apps never contains the secure value', SECRET not in rm('GET', 'api/apps').text)
    blk = rm_block(MVN)
    check('apisix.yaml: rm-route record + route rm-t-api-mvn, uri /t-api-mvn/*, node mule-t-api-pool-1:8081, mule-api-auth',
          f'"app": "{MVN}"' in blk and f'id: "rm-{MVN}"' in blk and f'uri: "/{MVN}/*"' in blk and f'"{W1}:8081": 100' in blk
          and 'plugin_config_id: "mule-api-auth"' in blk and 'regex_uri' in blk, blk[:400])
    r = wait(app_up(f'/{MVN}/api/v1/status', '1.0.19'), 90, 3)
    check('gateway /t-api-mvn/api/v1/status with a mule-api-gateway token: 200, version 1.0.19 (prefix stripped)', r, r and short(r))
    r = gw_status(f'/{MVN}/api/v1/status')
    check('gateway /t-api-mvn/... without a token: 401', r.status == 401, short(r))
    props = deploy_props(W1, MVN)
    check('worker deployment.properties: plain properties', 'http.port=8091' in props and 't.plain=hello' in props, 'missing')
    check('worker deployment.properties: secure value decrypted for Mule', f't.secret={SECRET}' in props, 'secure value missing (not printed)')
    # -s: other suites' temp files (e.g. *.jar.download) may vanish mid-scan; what counts is that no file matches
    code, out = sh(['docker', 'exec', RMC, 'grep', '-rlsF', SECRET, '/data'])
    check('RM /data has no plaintext copy of the secure value', code != 0 and not out.strip(), out.strip()[:200])
    meta = rm_meta(MVN) or {}
    check('stored app state: secure value Fernet-encrypted', str((meta.get('secure') or {}).get('t.secret', '')).startswith('gAAAA'))
    r = rm('DELETE', f'api/pools/{POOL}')
    check('DELETE pool while an app runs on it: 400 "still runs"', r.status == 400 and MVN in err(r), short(r))
    check('pool still there after the refused delete', rm_pool(POOL) is not None)

    # ---------- properties ----------
    section('Apps: properties')
    r = rm('GET', f'api/apps/{MVN}/properties')
    check('GET properties: plain values + secure names only', r.status == 200 and r.json() == {
          'properties': {'http.port': '8091', 't.plain': 'hello'}, 'secure': ['t.secret']} and SECRET not in r.text, short(r))
    before = anchor_mtime(W1, MVN)
    r = rm('PUT', f'api/apps/{MVN}/properties?restart=0', {'properties': {'http.port': '8091', 't.new': 'v2'}})
    check('PUT properties ?restart=0: replaces the plain set, restarted=false',
          r.status == 200 and r.json() == {'properties': {'http.port': '8091', 't.new': 'v2'}, 'secure': ['t.secret'], 'restarted': False}, short(r))
    time.sleep(8)
    props = deploy_props(W1, MVN)
    check('?restart=0: worker untouched (old properties file, same anchor)', 't.plain=hello' in props and 't.new' not in props
          and anchor_mtime(W1, MVN) == before)
    for b, why in [({'secureProperties': {'t.nope': None}}, 'null for an unknown secure name'), ({'properties': {'a=b': '1'}}, 'bad name')]:
        r = rm('PUT', f'api/apps/{MVN}/properties', b)
        check(f'PUT properties, {why}: 400', r.status == 400, short(r))
    check('refused PUTs changed nothing', rm('GET', f'api/apps/{MVN}/properties').json() ==
          {'properties': {'http.port': '8091', 't.new': 'v2'}, 'secure': ['t.secret']})
    r = rm('PUT', f'api/apps/{GHOST}/properties', {'properties': {}})
    check('PUT properties of unknown app: 404', r.status == 404, short(r))
    r = rm('GET', f'api/apps/{GHOST}/properties')
    check('GET properties of unknown app: 404', r.status == 404, short(r))
    t0 = wclock(W1)
    r = rm('PUT', f'api/apps/{MVN}/properties', {'secureProperties': {'t.secret': None, 't.secret2': SECRET2}}, timeout=300)
    check('PUT secureProperties (null keeps, new added): restarted, names only',
          r.status == 200 and r.json() == {'properties': {'http.port': '8091', 't.new': 'v2'}, 'secure': ['t.secret', 't.secret2'],
                                           'restarted': True} and SECRET2 not in r.text, short(r))
    check('redeployed on the worker (anchor rewritten)', wait_fresh(MVN, [W1], t0))
    props = deploy_props(W1, MVN)
    check('worker file now: t.new, no t.plain, kept secure value and new secure value',
          't.new=v2' in props and 't.plain' not in props and f't.secret={SECRET}' in props and f't.secret2={SECRET2}' in props, 'mismatch (not printed)')
    check('gateway still serves t-api-mvn after the properties restart', wait(app_up(f'/{MVN}/api/v1/status'), 120, 3))

    # ---------- update check / modes ----------
    section('Apps: Maven update check and modes')
    r = rm('POST', f'api/apps/{MVN}/check', timeout=120)
    cj = r.json() if r.status == 200 else {}
    check('POST check (notify): 1.0.20 available, still 1.0.19', cj.get('version') == '1.0.19' and cj.get('available') == {'version': '1.0.20', 'build': '1.0.20'}
          and cj.get('updates') == 'notify' and cj.get('checked') and not cj.get('error'), short(r))
    time.sleep(5)
    r = gw_status(f'/{MVN}/api/v1/status', admin_token())
    check('notify mode did not deploy: gateway still 1.0.19', r.status == 200 and r.json().get('version') == '1.0.19', short(r))
    check('GET /api/apps shows maven.available 1.0.20', (rm_app(MVN)['maven'] or {}).get('available', {}).get('version') == '1.0.20')
    before = anchor_mtime(W1, MVN)
    r = rm('PUT', f'api/apps/{MVN}', {'updates': 'auto'})
    check('PUT {updates: auto}: 200, saved without a redeploy', r.status == 200 and rm_app(MVN)['updates'] == 'auto', short(r))
    time.sleep(8)
    check('updates change alone did not restart the app (same anchor)', anchor_mtime(W1, MVN) == before)
    t0 = wclock(W1)
    r = rm('POST', f'api/apps/{MVN}/check', timeout=300)
    cj = r.json() if r.status == 200 else {}
    check('POST check (auto): 1.0.20 deployed, nothing available, updated set', cj.get('version') == '1.0.20' and cj.get('build') == '1.0.20'
          and cj.get('available') is None and cj.get('updated'), short(r))
    check('auto update redeployed the worker', wait_fresh(MVN, [W1], t0))
    r = wait(app_up(f'/{MVN}/api/v1/status', '1.0.20'), 180, 3)
    check('gateway now serves 1.0.20', r, 'still old version')
    check('properties survived the update', f't.secret2={SECRET2}' in deploy_props(W1, MVN) and 't.new=v2' in deploy_props(W1, MVN))
    r = rm('PUT', f'api/apps/{MVN}', {'updates': 'off'})
    check('PUT {updates: off}: saved', r.status == 200 and rm_app(MVN)['updates'] == 'off', short(r))
    r = rm('PUT', f'api/apps/{MVN}', {'updates': 'often'})
    check('PUT {updates: often}: 400', r.status == 400, short(r))

    # ---------- restart ----------
    t0 = wclock(W1)
    r = rm('POST', f'api/apps/{MVN}/restart', timeout=300)
    check('POST restart: restarted on its workers', r.status == 200 and r.json() == {'restarted': MVN, 'workers': [W1]}, short(r))
    check('restart redeployed (anchor rewritten)', wait_fresh(MVN, [W1], t0))
    check('gateway serves after restart', wait(app_up(f'/{MVN}/api/v1/status'), 120, 3))
    r = rm('POST', f'api/apps/{GHOST}/restart')
    check('POST restart unknown app: 404', r.status == 404, short(r))
    r = rm('POST', f'api/apps/{GHOST}/check')
    check('POST check unknown app: 400 (not from Maven)', r.status == 400, short(r))

    # ---------- overview + logs ----------
    section('Apps: overview and log')
    tok = admin_token()
    for _ in range(12):
        gw_status(f'/{MVN}/api/v1/status', tok)
    ov = wait(lambda: (r := rm('GET', f'api/apps/{MVN}/overview?minutes=15', timeout=60)).status == 200
              and r.json()['traces'].get('total', {}).get('count', 0) > 0 and r.json(), 180, 10) or {}
    tr, lg = ov.get('traces', {}), ov.get('logs', {})
    check('overview?minutes=15: app, minutes, traces state ok with requests', ov.get('minutes') == 15 and (ov.get('app') or {}).get('name') == MVN
          and tr.get('state') == 'ok' and tr['total']['count'] > 0, {k: (v if k != 'app' else '...') for k, v in ov.items() if k != 'traces'})
    check('overview traces shape: total stats, 30 series buckets, endpoints, workers, tenants, notable, truncated',
          tr and set(tr['total']) >= {'count', 'errors', 'error_rate', 'p50', 'p95', 'p99', 'avg', 'rpm'} and len(tr['series']) == 30
          and tr['bucket_ms'] == 30000 and all(k in tr for k in ('endpoints', 'workers', 'tenants', 'notable', 'truncated', 'link')))
    check('overview traces per worker: mule-t-api-pool-1 counted', any(w['worker'] == W1 and w['count'] > 0 for w in tr.get('workers', [])), tr.get('workers'))
    check('overview endpoints include GET .../api/v1/status', any('/api/v1/status' in e['endpoint'] for e in tr.get('endpoints', [])), tr.get('endpoints'))
    check('overview logs: state ok, total/levels/workers/problems', lg.get('state') == 'ok' and all(k in lg for k in ('total', 'levels', 'workers', 'problems')), lg)
    r = rm('GET', f'api/apps/{MVN}/overview?minutes=60')
    check('overview?minutes=60: 30 buckets of 2 min', r.status == 200 and r.json()['minutes'] == 60 and r.json()['traces']['bucket_ms'] == 120000, short(r))
    for qv, want in [('1', 5), ('99999', 1440), ('abc', 60), ('', 60)]:
        r = rm('GET', f'api/apps/{MVN}/overview?minutes={qv}')
        check(f'overview minutes={qv!r} -> {want}', r.status == 200 and r.json()['minutes'] == want, short(r))
    # per-worker log counts: the default app (read-only) logs under its own name, so its worker counts show up
    r = rm('GET', 'api/apps/ce-mule-base/overview?minutes=1440', timeout=60)
    check('overview logs per worker for ce-mule-base (read-only): counts by worker_id',
          r.status == 200 and r.json()['logs'].get('state') == 'ok' and isinstance(r.json()['logs'].get('workers'), dict), short(r))
    # note: the ce-mule-base artifact hard-codes application=ce-mule-base and logs/cemulebase.log in its log4j2.xml,
    # so a copy deployed under another name logs as ce-mule-base (see report); checked below as what the RM finds
    r = rm('GET', f'api/apps/{MVN}/log?worker={W1}&source=runtime&bytes=8388608')
    check('log source=runtime: text/plain mule.log of the worker', r.status == 200 and r.headers.get('Content-Type', '').startswith('text/plain')
          and 'Mule is up and kicking' in r.text, short(r))
    r = rm('GET', f'api/apps/{MVN}/log?worker={W1}&source=runtime&bytes=10')
    check('log bytes=10 clamped to 1024', r.status == 200 and len(r.body) == 1024, len(r.body))
    r = rm('GET', f'api/apps/{MVN}/log?worker={W1}&source=runtime&bytes=99999999999')
    check('log bytes=huge clamped to 8 MB', r.status == 200 and 1024 < len(r.body) <= 8 << 20, len(r.body))
    r = rm('GET', f'api/apps/{MVN}/log?worker={W1}&source=runtime&bytes=abc')
    check('log bytes=abc -> default 64 KB', r.status == 200 and len(r.body) <= 64 * 1024, len(r.body))
    r = rm('GET', f'api/apps/{MVN}/log?worker={W1}&source=app')
    check('log source=app: 200 text (app log, or the files it looked for)', r.status == 200 and (
          'looked for mule-app-t-api-mvn.log, tapimvn.log, t-api-mvn.log' in r.text or len(r.body) > 0), short(r))
    r = rm('GET', 'api/apps/ce-mule-base/log?worker=mule-default-1&source=app&bytes=4096')
    check('log source=app for ce-mule-base on mule-default-1 (read-only): its app log', r.status == 200 and 'no log yet' not in r.text and len(r.body) > 100, short(r))
    for qs, why in [('worker=mule-nope-9', 'unknown worker'), ('', 'no worker')]:
        r = rm('GET', f'api/apps/{MVN}/log?{qs}')
        check(f'log {why}: 400', r.status == 400 and 'unknown worker' in err(r), short(r))

    # ======================================================================
    section('Pools: scale out to 2 (existing worker kept, new one gets the apps)')
    r = rm('PUT', f'api/pools/{POOL}', {'mule_version': '4.12.0', 'heap_mb': 512, 'replicas': 2, 'jvm_options': JVM})
    check('PUT pool replicas 2, java omitted -> defaults to 17', r.status == 200 and r.json()['replicas'] == 2 and r.json()['java_version'] == '17'
          and r.json()['nodes'] == {'local': 2}, short(r))
    p = wait_pool_ready(POOL, 600)
    check('pool ready with 2 healthy workers', p and [w['name'] for w in p['workers']] == [W1, W2], p and p['status'])
    check('scale out did not replace mule-t-api-pool-1', inspect(W1)['Id'] == id1)
    a = wait_app_started(MVN, 300)
    check('t-api-mvn (workers all) STARTED on both workers', a and a['workers'] == {W1: 'STARTED', W2: 'STARTED'}, a and a['workers'])
    blk = rm_block(MVN)
    check('apisix route nodes follow: both workers', f'"{W1}:8081": 100' in blk and f'"{W2}:8081": 100' in blk, blk[:400])
    check('new worker got the properties incl. secure', f't.secret={SECRET}' in deploy_props(W2, MVN))

    # ======================================================================
    section('Apps: jar upload t-api-jar (API token, query params, workers=1)')
    data, jar_tmp = patched_jar()
    r = http('PUT', f'{RM}/api/apps/{JAR}?pool={POOL}&path=/{JAR}&port=8092&workers=1', data, {'Content-Type': 'application/java-archive'},
             token=token, timeout=300)
    check('PUT jar body with Bearer API token: 200 placed on 1 worker (least loaded = first)',
          r.status == 200 and r.json() == {'deployed': JAR, 'pool': POOL, 'workers': [W1]}, short(r))
    a = wait_app_started(JAR, 420)
    check('t-api-jar STARTED on mule-t-api-pool-1 only', a and a['workers'] == {W1: 'STARTED'} and a['placement'] == 1 and a['targets'] == [W1], a)
    check('jar app: no Maven info, updates off', a and a['maven'] is None and a['updates'] == 'off', a)
    check('worker 2 has no t-api-jar', not {f'{JAR}.jar', f'{JAR}-anchor.txt'} & apps_dir(W2))
    check('stored placement: placed = [w1]', (rm_meta(JAR) or {}).get('placed') == [W1])
    code, _ = sh(['docker', 'exec', RMC, 'test', '-f', f'/data/artifacts/{JAR}.jar'])
    check('uploaded jar stored in /data/artifacts', code == 0)
    blk = rm_block(JAR)
    check('apisix route for t-api-jar: port 8092 on its one worker', f'"{W1}:8092": 100' in blk and f'"{W2}:8092"' not in blk, blk[:300])
    r = wait(lambda: (x := gw_status(f'/{JAR}/api/v1/status', admin_token())).status != 404 and x, 30, 2) or gw_status(f'/{JAR}/api/v1/status', admin_token())
    check('before http.port is set the app listens on its default (8093): route on 8092 fails', r.status in (502, 503, 504), short(r))
    t0 = wclock(W1)
    r = rm('PUT', f'api/apps/{JAR}/properties', {'properties': {'http.port': '8092'}}, timeout=300)
    check('PUT properties http.port=8092: restarted', r.status == 200 and r.json()['restarted'] is True, short(r))
    check('t-api-jar redeployed on its worker', wait_fresh(JAR, [W1], t0))
    r = wait(app_up(f'/{JAR}/api/v1/status', '1.0.20'), 120, 3)
    check('gateway /t-api-jar/api/v1/status: 200 via port 8092 (property applied)', r, 'no 200')
    r = rm('POST', f'api/apps/{JAR}/check')
    check('POST check on an uploaded jar: 400 not from Maven', r.status == 400 and 'Maven' in err(r), short(r))

    section('Apps: worker placement (pinned list, all, count keeps placement)')
    t0 = wclock(W2)
    r = rm('PUT', f'api/apps/{JAR}', {'workers': [W2]}, timeout=300)
    check('PUT workers [w2]: moved', r.status == 200 and r.json()['workers'] == [W2], short(r))
    check('pinned: deployed on w2', wait_fresh(JAR, [W2], t0))
    check('pinned: jar + anchor removed from w1', wait(lambda: not {f'{JAR}.jar', f'{JAR}-anchor.txt'} & apps_dir(W1), 60, 3))
    a = rm_app(JAR)
    check('placement [w2], targets [w2]', a['placement'] == [W2] and a['targets'] == [W2], a)
    check('route follows: only w2:8092', wait(lambda: f'"{W2}:8092": 100' in rm_block(JAR) and f'"{W1}:8092"' not in rm_block(JAR), 30, 2))
    check('gateway serves t-api-jar from w2', wait(app_up(f'/{JAR}/api/v1/status'), 120, 3))
    t0 = wclock(W1)
    r = rm('PUT', f'api/apps/{JAR}', {'workers': 'all'}, timeout=300)
    check('PUT workers "all": on both', r.status == 200 and r.json()['workers'] == [W1, W2], short(r))
    check('all: deployed on w1 too', wait_fresh(JAR, [W1], t0))
    a = rm_app(JAR)
    check('placement null, targets both', a['placement'] is None and a['targets'] == [W1, W2], a)
    r = rm('PUT', f'api/apps/{JAR}', {'workers': W2}, timeout=300)  # "a,b" string form
    check('PUT workers "<name>" (string list form): pinned to w2', r.status == 200 and rm_app(JAR)['placement'] == [W2], short(r))
    check('string pin: removed from w1', wait(lambda: f'{JAR}-anchor.txt' not in apps_dir(W1), 60, 3))
    before = anchor_mtime(W2, JAR)
    r = rm('PUT', f'api/apps/{JAR}', {'workers': 1}, timeout=300)
    a = rm_app(JAR)
    check('PUT workers 1 after the pin: placement kept on w2 (count keeps the current worker)',
          r.status == 200 and a['placement'] == 1 and a['targets'] == [W2] and (rm_meta(JAR) or {}).get('placed') == [W2], a)
    check('count keeps placement: w1 still has no t-api-jar', not {f'{JAR}.jar', f'{JAR}-anchor.txt'} & apps_dir(W1))
    check('t-api-jar STARTED on w2', wait(lambda: (anchor_mtime(W2, JAR) or 0) >= (before or 0) and rm_app(JAR)['workers'] == {W2: 'STARTED'}, 300, 5))

    # ======================================================================
    section('Pools: change heap -> rolling replace of both workers')
    ids = {w: inspect(w)['Id'] for w in (W1, W2)}
    r = rm('PUT', f'api/pools/{POOL}', {'mule_version': '4.12.0', 'java_version': '17', 'heap_mb': 768, 'replicas': 2, 'jvm_options': JVM})
    check('PUT pool heap 768: 200', r.status == 200 and r.json()['heap_mb'] == 768, short(r))
    samples, msgs, end = [], set(), time.time() + 900
    tok, tok_at = admin_token(), time.time()
    while time.time() < end:
        if time.time() - tok_at > 200:
            tok, tok_at = admin_token(), time.time()
        samples.append(gw_status(f'/{MVN}/api/v1/status', tok).status)
        pe = rm_pool(POOL) or {}
        msgs.add(pe.get('status', {}).get('message', ''))
        if pe.get('status', {}).get('state') == 'ready' and all(inspect(w) and inspect(w)['Id'] != ids[w] for w in (W1, W2)):
            break
        time.sleep(2)
    p = wait_pool_ready(POOL, 300)
    check('pool ready after the heap change, both healthy', p and len(p['workers']) == 2, p and p['status'])
    new = {w: inspect(w) for w in (W1, W2)}
    check('both workers replaced', all(new[w]['Id'] != ids[w] for w in (W1, W2)))
    check('rolling: status reported "replacing <worker> (i/2)" one at a time', any(f'replacing {W1} (1/2)' in m for m in msgs)
          and any(f'replacing {W2} (2/2)' in m for m in msgs), sorted(msgs)[:6])
    ct = {w: datetime.fromisoformat(new[w]['Created'][:19]) for w in (W1, W2)}
    check('rolling: w2 created only after w1 was up (>= 20 s later)', (ct[W2] - ct[W1]).total_seconds() >= 20, ct)
    ok = sum(s == 200 for s in samples)
    print(f'     gateway during the rollout: {ok}/{len(samples)} requests 200 ({sorted(set(samples))})')
    check('rolling: t-api-mvn kept answering during the rollout (>= 80% of requests 200)', samples and ok / len(samples) >= 0.8,
          f'{ok}/{len(samples)} statuses {sorted(set(samples))}')
    for w in (W1, W2):
        check(f'{w}: MaxHeapSize 768 MB (jcmd), env 768', '-XX:MaxHeapSize=805306368' in jcmd(w, 'VM.flags') and env_of(new[w]).get('MULE_MAX_HEAP_MB') == '768')
    a = wait_app_started(MVN, 300)
    check('t-api-mvn back on both workers', a and a['workers'] == {W1: 'STARTED', W2: 'STARTED'}, a and a['workers'])
    a = wait_app_started(JAR, 300)
    check('t-api-jar (count 1) back on w2 only', a and a['workers'] == {W2: 'STARTED'}, a and a['workers'])
    check('t-api-jar not put on w1 by the rollout', not {f'{JAR}.jar', f'{JAR}-anchor.txt'} & apps_dir(W1))

    section('Pools: scale in to 1 -> count app re-placed')
    id1 = inspect(W1)['Id']
    t0 = wclock(W1)
    r = rm('PUT', f'api/pools/{POOL}', {'mule_version': '4.12.0', 'java_version': '17', 'heap_mb': 768, 'replicas': 1, 'jvm_options': JVM})
    check('PUT pool replicas 1: 200', r.status == 200, short(r))
    check('w2 removed', wait(lambda: not exists(W2), 300, 5))
    p = wait_pool_ready(POOL, 300)
    check('pool ready with 1 worker, w1 not replaced', p and len(p['workers']) == 1 and inspect(W1)['Id'] == id1)
    check('t-api-jar (count 1) re-placed onto w1', wait_fresh(JAR, [W1], t0))
    check('stored placed = [w1], placement still 1', wait(lambda: (rm_meta(JAR) or {}).get('placed') == [W1], 60, 3) and rm_app(JAR)['placement'] == 1)
    check('t-api-mvn not redeployed on w1 by the scale in', (anchor_mtime(W1, MVN) or 0) < t0)
    check('routes follow: both apps on w1 only', wait(lambda: f'"{W1}:8092": 100' in rm_block(JAR) and f'"{W2}:' not in rm_block(JAR)
                                                      and f'"{W2}:' not in rm_block(MVN), 60, 3))
    check('gateway serves both apps', wait(app_up(f'/{JAR}/api/v1/status'), 120, 3) and wait(app_up(f'/{MVN}/api/v1/status'), 60, 3))

    # ======================================================================
    section('API token revoke')
    r = rm('DELETE', f'api/tokens/{token_id}')
    check('DELETE /api/tokens/<id> (Basic): 200', r.status == 200 and r.json() == {'deleted': token_id}, short(r))
    r = http('GET', f'{RM}/api/apps', token=token)
    check('revoked token: 401', r.status == 401, short(r))
    r = rm('DELETE', f'api/tokens/{token_id}')
    check('DELETE revoked token again: 404', r.status == 404, short(r))
    token_id = None

    # ======================================================================
    section('Apps: delete')
    for app, port in ((MVN, 8081), (JAR, 8092)):
        r = rm('DELETE', f'api/apps/{app}', timeout=120)
        check(f'DELETE /api/apps/{app}: 200', r.status == 200 and r.json() == {'deleted': app}, short(r))
        check(f'{app}: jar + anchor gone from the worker', not {f'{app}.jar', f'{app}-anchor.txt'} & apps_dir(W1))
        code, out = sh(['docker', 'exec', RMC, 'sh', '-c', f'ls /data/artifacts/{app}.* 2>/dev/null'])
        check(f'{app}: stored jar + state removed', not out.strip(), out)
        check(f'{app}: route gone from apisix.yaml', f'"app": "{app}"' not in apisix() and f'rm-{app}' not in apisix())
        check(f'{app}: not listed', rm_app(app) is None)
        r = wait(lambda: (x := gw_status(f'/{app}/api/v1/status', admin_token())).status == 404 and x, 60, 3)
        check(f'{app}: gateway 404 now', r, 'still routed')
        r = rm('DELETE', f'api/apps/{app}')
        check(f'DELETE {app} again: 404', r.status == 404, short(r))
    check('Mule undeployed both (no app dirs left on w1)', wait(lambda: not {MVN, JAR} & set(x.rstrip('/') for x in apps_dir(W1)), 120, 5))

    section('Pools: delete')
    r = rm('DELETE', f'api/pools/{POOL}')
    check('DELETE /api/pools/t-api-pool (no apps): 200', r.status == 200 and r.json() == {'deleted': POOL}, short(r))
    check('worker container removed', wait(lambda: not exists(W1), 300, 5))
    check('pool not listed', rm_pool(POOL) is None)
    r = rm('DELETE', f'api/pools/{POOL}')
    check('DELETE pool again: 404', r.status == 404, short(r))
    check('runtime image kept (the default pool uses it)', sh(['docker', 'image', 'inspect', c1['Config']['Image']])[0] == 0)

    # ======================================================================
    section('Nodes: validation (nothing saved)')
    r = rm('GET', 'api/nodes')
    check('GET /api/nodes: {nodes: [...]} with name/address/fingerprint/gateway/status/workers/pools',
          r.status == 200 and all(set(n) >= {'name', 'address', 'fingerprint', 'gateway', 'status', 'workers', 'pools'} for n in r.json()['nodes'])
          and all('token' not in n for n in r.json()['nodes']), short(r))
    fp0 = 'sha256:' + '0' * 64
    good = {'address': 'https://t-api-nowhere:7443', 'fingerprint': fp0, 'gateway': '172.42.0.20', 'token': 'x' * 32}
    cases = [('local', good, 'name local'), (P + 'n' * 30, good, 'name too long'),
             (NODE, {**good, 'address': ''}, 'missing address'), (NODE, {**good, 'address': 'http://t-api-x:7443'}, 'http address'),
             (NODE, {**good, 'address': 'https://x/path'}, 'address with a path'),
             (NODE, {**good, 'fingerprint': 'sha256:abc'}, 'short fingerprint'), (NODE, {**good, 'fingerprint': ''}, 'missing fingerprint'),
             (NODE, {**good, 'gateway': ''}, 'missing gateway'), (NODE, {**good, 'gateway': 'bad host!'}, 'bad gateway'),
             (NODE, {k: v for k, v in good.items() if k != 'token'}, 'missing token'),
             (NODE, good, 'unreachable address')]
    for name, body, why in cases:
        r = rm('PUT', f'api/nodes/{name}', body, timeout=60)
        check(f'PUT node, {why}: 400', r.status == 400, short(r))
    r = rm('PUT', f'api/nodes/{NODE}', good, timeout=60)
    check('unreachable node error says it cannot reach the agent', 'cannot reach the node agent' in err(r), short(r))
    check('nothing saved', not any(n['name'] == NODE for n in rm('GET', 'api/nodes').json()['nodes']))
    r = rm('DELETE', f'api/nodes/{GHOST}')
    check('DELETE unknown node: 404', r.status == 404, short(r))

    section('Nodes: a real node agent')
    code, out = sh(['docker', 'build', '-q', '-t', AGENT_IMG, 'node/agent'], timeout=600)
    check('node agent image built', code == 0, out[-300:])
    node_token = secrets.token_hex(16)
    code, out = sh(['docker', 'run', '-d', '--privileged', '--name', DIND, '--network', 'ce-base-micronet', '-e', 'DOCKER_TLS_CERTDIR=',
                    '-v', f'{DIND_VOL}:/var/run', DIND_IMG])
    check('separate Docker daemon for the node started (dind)', code == 0 and wait(lambda: ddocker('info', timeout=30)[0] == 0, 120, 3), out[-300:])
    code, out = sh(['docker', 'run', '-d', '--name', AGENT, '--network', 'ce-base-micronet', '-e', f'NODE_TOKEN={node_token}',
                    '-e', 'DOCKER_SOCK=/dind/docker.sock', '-v', f'{DIND_VOL}:/dind', AGENT_IMG])
    check('node agent container started (on the dind socket)', code == 0, out[-300:])
    fp = wait(lambda: (m := re.search(r'NODE-FINGERPRINT (sha256:[0-9a-f]{64})', sh(['docker', 'logs', AGENT])[1])) and m.group(1), 60, 2)
    check('agent printed its NODE-FINGERPRINT', fp)
    reg = {'address': f'https://{AGENT}:7443', 'fingerprint': fp or fp0, 'gateway': '172.42.0.20', 'token': node_token}
    r = rm('PUT', f'api/nodes/{NODE}', {**reg, 'token': 'y' * 32}, timeout=60)
    check('register with a wrong token: 400 (agent says 401)', r.status == 400 and '401' in err(r), short(r))
    r = rm('PUT', f'api/nodes/{NODE}', {**reg, 'fingerprint': fp0}, timeout=60)
    check('register with a wrong fingerprint: 400 fingerprint mismatch', r.status == 400 and 'fingerprint mismatch' in err(r), short(r))
    check('nothing saved after the refused registrations', NODE not in rm_nodes_file())
    r = rm('PUT', f'api/nodes/{NODE}', {**reg, 'fingerprint': fp.replace('sha256:', '').upper() if fp else fp0}, timeout=60)
    nj = r.json() if r.status == 200 else {}
    check('register (fingerprint given as bare uppercase hex): 200 with docker info', nj.get('name') == NODE and nj.get('fingerprint') == fp
          and nj.get('address') == reg['address'] and (nj.get('info') or {}).get('docker') and (nj.get('info') or {}).get('cpus')
          and 'token' not in nj, short(r))
    nf = rm_nodes_file().get(NODE, {})
    check('nodes.json: token encrypted at rest', nf and node_token not in json.dumps(nf) and str(nf.get('token', '')).startswith('gAAAA'))
    n = next((x for x in rm('GET', 'api/nodes').json()['nodes'] if x['name'] == NODE), {})
    check('GET /api/nodes: t-api-node reachable', n.get('status', {}).get('ok') is True and n['status'].get('info', {}).get('docker'), n.get('status'))
    r = rm('PUT', f'api/nodes/{NODE}', {'gateway': 'localhost'}, timeout=60)
    check('edit gateway only (no token: stored one reused for the same address/fingerprint): 200', r.status == 200 and r.json()['gateway'] == 'localhost', short(r))
    r = rm('PUT', f'api/nodes/{NODE}', {'address': 'https://127.0.0.1:7443'}, timeout=60)
    check('edit address without a token: 400 token is required', r.status == 400 and 'token is required' in err(r), short(r))
    r = rm('PUT', f'api/nodes/{NODE}', {'gateway': '172.42.0.20', 'address': reg['address'] + '/'}, timeout=60)
    check('edit back (address trailing slash normalized): 200', r.status == 200 and r.json()['gateway'] == '172.42.0.20'
          and r.json()['address'] == reg['address'], short(r))

    section('Nodes: pool with a worker on the node')
    r = rm('PUT', f'api/pools/{NPOOL}', {'mule_version': '4.12.0', 'java_version': '17', 'heap_mb': 512, 'nodes': {'local': 0, NODE: 1}})
    check('PUT pool nodes {local: 0, t-api-node: 1}: zero dropped, replicas 1', r.status == 200 and r.json()['nodes'] == {NODE: 1}
          and r.json()['replicas'] == 1, short(r))

    def npool_ready():
        pe = rm_pool(NPOOL)
        ws = [w for w in (pe or {}).get('workers', []) if w['node'] == NODE]
        return pe and pe['status']['state'] == 'ready' and ws and ws[0]['name'] == NW and ws[0]['state'] == 'running' \
            and ws[0]['health'] == 'healthy' and pe
    t_np = time.time()
    pe = wait(npool_ready, 600, 5)
    print(f'     node pool ready after {int(time.time() - t_np)} s')
    if pe:
        check('node worker mule-t-api-npool-t-api-node-1 running + healthy, pool ready', True)
    else:
        st = (rm_pool(NPOOL) or {}).get('status', {})
        if 'building runtime image' in st.get('message', ''):
            skip('node worker healthy', f'runtime image build through the agent still running after 10 min ({st})')
        else:
            check('node worker mule-t-api-npool-t-api-node-1 running + healthy, pool ready', False, st)
    cn = dinspect(NW)
    en = env_of(cn)
    port = rm_nodes_file().get(NODE, {}).get('ports', {}).get(NW)
    check('node worker port block allocated from 18000', isinstance(port, int) and 18000 <= port < 19000 and (port - 18000) % 10 == 0, port)
    check('node worker: bridge network, 8081..8090 published from its port block', cn and cn['HostConfig']['NetworkMode'] == 'bridge'
          and cn['HostConfig']['PortBindings'].get('8081/tcp', [{}])[0].get('HostPort') == str(port)
          and cn['HostConfig']['PortBindings'].get('8090/tcp', [{}])[0].get('HostPort') == str((port or 0) + 9))
    check('node worker: traces via the gateway /otlp with x-otlp-token, platform CA, logs to gateway:9100',
          en.get('OTEL_EXPORTER_OTLP_ENDPOINT') == 'https://172.42.0.20:9443/otlp' and en.get('OTEL_EXPORTER_OTLP_PROTOCOL') == 'http/protobuf'
          and en.get('OTEL_EXPORTER_OTLP_HEADERS', '').startswith('x-otlp-token=') and 'BEGIN CERTIFICATE' in en.get('PLATFORM_CA_PEM', '')
          and '-M-Dlogs.host=172.42.0.20' in en.get('MULE_ARGS', '') and '-M-Dlogs.port=9100' in en.get('MULE_ARGS', ''))
    check('node worker labels rm.pool=t-api-npool', cn and cn['Config']['Labels'].get('rm.pool') == NPOOL)
    n = next((x for x in rm('GET', 'api/nodes').json()['nodes'] if x['name'] == NODE), {})
    check('GET /api/nodes: t-api-node lists the worker and the pool', n.get('pools') == [NPOOL] and any(w['name'] == NW for w in n.get('workers', [])), n.get('pools'))
    r = rm('DELETE', f'api/nodes/{NODE}')
    check('DELETE node while a pool uses it: 400', r.status == 400 and NPOOL in err(r), short(r))
    r = rm('DELETE', f'api/pools/{NPOOL}')
    check('DELETE node pool: 200', r.status == 200, short(r))
    check('node worker removed', wait(lambda: ddocker('inspect', NW, timeout=30)[0] != 0, 300, 5))
    check('node worker port block released', wait(lambda: NW not in rm_nodes_file().get(NODE, {}).get('ports', {}), 60, 3))
    check('pool gone', wait(lambda: rm_pool(NPOOL) is None, 60, 3))
    r = rm('DELETE', f'api/nodes/{NODE}')
    check('DELETE node after its pool is gone: 200', r.status == 200 and r.json() == {'deleted': NODE}, short(r))
    check('node not listed, not in nodes.json', not any(x['name'] == NODE for x in rm('GET', 'api/nodes').json()['nodes']) and NODE not in rm_nodes_file())
    r = rm('DELETE', f'api/nodes/{NODE}')
    check('DELETE node again: 404', r.status == 404, short(r))
    names, bad = local_workers_reachable()
    check('after the node tests the RM still reaches every local worker directly', not bad, bad)
    check('node-b untouched (still registered)', any(x['name'] == 'node-b' for x in rm('GET', 'api/nodes').json()['nodes']))
except Stop as e:
    check('stopped early', False, e)
finally:
    section('Cleanup (end)')
    if token_id:
        rm('DELETE', f'api/tokens/{token_id}')
    cleanup()
    sh(['docker', 'rmi', '-f', AGENT_IMG])
    if rm('GET', 'api/settings').json() != orig_settings:
        rm('PUT', 'api/settings', orig_settings)
    if jar_tmp:
        shutil.rmtree(jar_tmp, ignore_errors=True)
    check('cleanup: no t-api- apps/pools/nodes/containers left',
          not any(a['name'].startswith(P) for a in rm('GET', 'api/apps').json()['apps'])
          and not any(p['name'].startswith(P) for p in rm('GET', 'api/pools').json()['pools'])
          and not any(n['name'].startswith(P) for n in rm('GET', 'api/nodes').json()['nodes'])
          and not sh(['docker', 'ps', '-aq', '--filter', 'name=t-api-'])[1].strip()
          and not sh(['docker', 'volume', 'ls', '-q', '--filter', f'name={DIND_VOL}'])[1].strip())
    check('cleanup: default pool and ce-mule-base still there', rm_pool('default') is not None and rm_app('ce-mule-base') is not None)
    print(f'runtime {int(time.time() - T0)} s')
done()
