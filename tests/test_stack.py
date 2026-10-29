# Live checks of every non-Runtime-Manager part of the platform (gateway, TLS, Keycloak SSO, Mule API, log ingestion,
# OpenSearch + DLS, tracing, monitoring, ActiveMQ, MySQL, ops scripts). Stdlib only; the stack must be running.
#   python tests/test_stack.py
# Checks of a compose profile that is off in .env are skipped. Everything this creates is named t-stack-* and removed
# again (finally blocks), so reruns are idempotent. Secrets are never printed (failure details are redacted).
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
import http.client as httpclient, http.cookiejar as cookiejar
import socket, struct, uuid

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
T0 = time.time()
RUN = 't-stack-' + uuid.uuid4().hex[:6]
SECRET_VALUES = sorted({v for k, v in ENV.items() if re.search(r'PASSWORD|SECRET|TOKEN|KEY', k) and len(v) >= 6},
                       key=len, reverse=True)


def redact(s):
    s = str(s)
    for v in SECRET_VALUES:
        s = s.replace(v, '***')
    return re.sub(r'eyJ[\w-]+\.[\w-]+\.[\w-]*', '<jwt>', s)


_check = check


def check(name, ok, detail=''):
    return _check(name, ok, redact(detail) if not ok else '')


def claims(tok):
    try:
        p = tok.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4)))
    except Exception:
        return {}


def form(d):
    return urllib.parse.urlencode(d), {'Content-Type': 'application/x-www-form-urlencoded'}


def token_req(d, base=GW, realm='mule'):
    body, h = form(d)
    return http('POST', f'{base}/auth/realms/{realm}/protocol/openid-connect/token', body, h)


def run(script, timeout=600):
    """Ops script / bash snippet from the repo root, as a user runs it from Git Bash: without MSYS_NO_PATHCONV (with it,
    MSYS curl exits 23 in the scripts' `curl | grep -q` checks under pipefail) and with stdin closed."""
    p = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                       env={k: v for k, v in os.environ.items() if k != 'MSYS_NO_PATHCONV'}, encoding='utf-8',
                       errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def master_token():
    r = token_req({'grant_type': 'password', 'client_id': 'admin-cli', 'username': ENV.get('KEYCLOAK_ADMIN_USER', 'admin'),
                   'password': ENV['KEYCLOAK_ADMIN_PASSWORD']}, LO, 'master')
    return r.json().get('access_token', '') if r.status == 200 else ''


_mt = [0, '']


def mtok():
    """Master-realm admin token, renewed every 30 s (master access tokens live 60 s)."""
    if time.time() - _mt[0] > 30:
        _mt[:] = [time.time(), master_token()]
    return _mt[1]


def kcadm(method, path, body=None):
    """Keycloak admin REST (master realm token, 9080 only)."""
    return http(method, f'{LO}/auth/admin/realms/{path.lstrip("/")}', body, token=mtok())


def ingest(events, port=9100):
    """JSON lines over TCP to the APISIX stream proxy (-> Fluent Bit :5000)."""
    with socket.create_connection(('localhost', port), 5) as s:
        s.sendall(''.join(json.dumps(e) + '\n' for e in events).encode())


def os_search(index, query, size=50, **kw):
    r = os_api('POST', f'{index}/_search?ignore_unavailable=true', {'size': size, 'query': query}, **kw)
    return [h['_source'] for h in r.json()['hits']['hits']] if r.status == 200 else None


def os_wait(index, query, n=1, timeout=40):
    return wait(lambda: (h := os_search(index, query)) is not None and len(h) >= n and h, timeout, 2) or []


def control(path):
    """APISIX Control API (container-local; output holds secrets: never print it)."""
    code, out = sh(['docker', 'run', '--rm', '--network', 'container:apisix', 'curlimages/curl:8.10.1', '-s',
                    'http://127.0.0.1:9092' + path], timeout=60)
    try:
        return json.loads(out)
    except Exception:
        return None


def jaeger_trace(trace_id, tok):
    r = get(f'/jaeger/api/v3/traces/{trace_id}', token=tok)
    if r.status != 200:
        return []
    out = []
    for rs in r.json().get('result', {}).get('resourceSpans', []):
        res = {a['key']: list(a['value'].values())[0] for a in rs.get('resource', {}).get('attributes', [])}
        for ss in rs.get('scopeSpans', []):
            for sp in ss.get('spans', []):
                attrs = {a['key']: list(a['value'].values())[0] for a in sp.get('attributes', [])}
                out.append({'res': res, 'scope': ss.get('scope', {}), 'span': sp, 'attrs': attrs})
    return out


def raw_https(path, headers, body=b'', port=9443):
    """Send the request headers (and a small body) and read the answer: body-size limits without uploading the body."""
    c = httpclient.HTTPSConnection('localhost', port, context=CTX, timeout=30)
    try:
        c.putrequest('POST', path)
        for k, v in headers.items():
            c.putheader(k, v)
        c.endheaders()
        if body:
            c.send(body)
        return c.getresponse().status
    except Exception as e:
        return str(e)
    finally:
        c.close()


ADMIN_T = admin_token() if need('auth') else ''
DEV_T = dev_token() if need('auth') else ''
MT = mtok() if need('auth') else ''
OTHER_T = ''   # token of another realm client (admin-cli): valid signature, wrong azp
if need('auth'):
    r = token_req({'grant_type': 'password', 'client_id': 'admin-cli', 'username': 'developer',
                   'password': ENV['KEYCLOAK_REALM_DEV_PASSWORD']})
    OTHER_T = r.json().get('access_token', '') if r.status == 200 else ''
cleanups = []   # (description, fn) run at the end, newest first

try:
    # ------------------------------------------------------------------------------------------------------------
    section('Self-checks: compose files and shell scripts')
    combos = [('every profile', ['docker', 'compose', '--profile', '*', 'config', '-q'], None),
              ('no profile (gateway + RM)', ['docker', 'compose', 'config', '-q'], ''),
              ('db,mq', ['docker', 'compose', 'config', '-q'], 'db,mq'),
              ('default profiles', ['docker', 'compose', 'config', '-q'], 'db,mq,logging,tracing,monitoring,auth')]
    combos += [(p, ['docker', 'compose', 'config', '-q'], p) for p in
               ['db', 'mq', 'logging', 'tracing', 'monitoring', 'alerting', 'opensearch-monitoring', 'auth']]
    for name, cmd, prof in combos:
        env = dict(os.environ)
        if prof is not None:
            env['COMPOSE_PROFILES'] = prof
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
        check(f'docker compose config -q: {name}', p.returncode == 0 and not p.stdout.strip() and not p.stderr.strip(),
              (p.stdout + p.stderr)[:300])
    code, out = run(r"find . \( -path ./git -o -path ./tests/.venv -o -name node_modules -o -path ./mule/volumes "
                     r"-o -path ./.git \) -prune -o -name '*.sh' -print")
    scripts = [s for s in out.split() if s.endswith('.sh')]
    check('found the repo shell scripts', len(scripts) >= 15, scripts)
    for s in scripts:
        c, o = sh(['bash', '-n', s])
        check(f'bash -n {s}', c == 0, o)

    # ------------------------------------------------------------------------------------------------------------
    section('Containers and health')
    code, out = sh(['docker', 'compose', 'ps', '-a', '--format', 'json'])
    svcs = [json.loads(l) for l in out.splitlines() if l.strip().startswith('{')]
    code2, want = sh(['docker', 'compose', 'config', '--services'])
    want = set(want.split())
    check('every service of the active profiles has a container', want <= {s['Service'] for s in svcs},
          want - {s['Service'] for s in svcs})
    for s in svcs:
        ok = s['State'] == 'running' and s.get('Health', '') in ('healthy', '')
        check(f'{s["Name"]}: running and healthy', ok, f'{s["State"]} {s.get("Health")}')
    for s in svcs:
        c, h = sh(['docker', 'inspect', '-f', '{{if .State.Health}}yes{{end}}', s['Name']])
        check(f'{s["Name"]}: has a healthcheck', h.strip() == 'yes', 'no healthcheck')
    c, out = sh(['docker', 'ps', '-a', '--filter', 'label=com.docker.compose.project=dockerelasticsearch',
                 '--filter', 'status=exited', '--format', '{{.Names}}'])
    exited = [n for n in out.split() if n != 'rm-node-b']
    check('no Exited container in the project (rm-node-b ignored)', not exited, exited)
    c, out = sh(['docker', 'ps', '-a', '--filter', 'label=rm.pool=default', '--format', '{{.Names}}|{{.Status}}'])
    workers = [l.split('|') for l in out.splitlines() if '|' in l]
    check('default pool has workers', len(workers) >= 1, out)
    for n, st in workers:
        check(f'pool worker {n} healthy', st.startswith('Up') and '(healthy)' in st, st)

    # ------------------------------------------------------------------------------------------------------------
    section('Published ports')
    mq = {ENV.get('MULE_MQ_WEB_CONSOL_PORT', '8161'): '8161', ENV.get('MULE_MQ_AMQP_PORT', '5672'): '5672',
          ENV.get('MULE_MQ_OPENWIRE_PORT', '61616'): '61616'}
    expect = {'apisix': {'127.0.0.1:9080->9080/tcp', '0.0.0.0:9443->9443/tcp', '127.0.0.1:9091->9091/tcp',
                         '0.0.0.0:9100->9100/tcp'}}
    if need('mq'):
        expect['ce-base-apachemq-backend'] = {f'127.0.0.1:{h}->{c}/tcp' for h, c in mq.items()}
    if need('db'):
        expect['ce-base-db-backend'] = {f'127.0.0.1:{ENV.get("MYSQL_EXTERNAL_PORT", "3306")}->'
                                        f'{ENV.get("MYSQL_INTERNAL_PORT", "3306")}/tcp'}
    c, out = sh(['docker', 'ps', '--format', '{{.Names}}|{{.Ports}}|{{.Label "com.docker.compose.project"}}|{{.Label "rm.pool"}}'])
    seen_ports = {}
    for l in out.splitlines():
        name, ports, proj, pool = (l.split('|') + ['', '', ''])[:4]
        if proj != 'dockerelasticsearch' and not pool:
            continue
        pub = {p.strip() for p in ports.split(',') if '->' in p}
        v6 = {p for p in pub if p.startswith('[::]:')}
        pub -= v6
        seen_ports[name] = pub
        # a v6 binding may only mirror a public v4 one (never a loopback-only port)
        check(f'{name}: IPv6 bindings only for public ports', all(p.replace('[::]:', '0.0.0.0:') in pub for p in v6), v6)
    for name, pub in seen_ports.items():
        check(f'{name}: published ports exactly as documented', pub == expect.get(name, set()),
              f'got {sorted(pub)} want {sorted(expect.get(name, set()))}')
    check('UDP 5000 / Fluent Bit not published on the host', not any('5000' in p for v in seen_ports.values() for p in v),
          seen_ports)
    r = get('http://127.0.0.1:9091/apisix/prometheus/metrics')
    check('APISIX metrics on 127.0.0.1:9091', r.status == 200 and b'apisix_' in r.body, r.status)

    # ------------------------------------------------------------------------------------------------------------
    section('TLS on 9443')
    ca = os.path.join(ROOT, 'certs', 'ca', 'ca.crt')
    for sni in ['localhost', '127.0.0.1']:
        try:
            tctx = ssl.create_default_context(cafile=ca)
            tctx.set_alpn_protocols(['h2', 'http/1.1'])
            with socket.create_connection(('localhost', 9443), 10) as s, tctx.wrap_socket(s, server_hostname=sni) as t:
                cert, der, alpn, ver = t.getpeercert(), t.getpeercert(True), t.selected_alpn_protocol(), t.version()
            check(f'cert chains to certs/ca/ca.crt and matches {sni}', True)
            if sni == 'localhost':
                sans = {v for k, v in cert.get('subjectAltName', ())}
                check('SANs include localhost, 127.0.0.1, apisix', {'localhost', '127.0.0.1', 'apisix'} <= sans, sans)
                gh = [h.strip() for h in ENV.get('GATEWAY_HOSTNAMES', '').split(',') if h.strip()]
                check('SANs include GATEWAY_HOSTNAMES', set(gh) <= sans, (gh, sans))
                check('HTTP/2 negotiated via ALPN', alpn == 'h2', alpn)
                check('TLS 1.2+ negotiated', ver in ('TLSv1.2', 'TLSv1.3'), ver)
                c, txt = sh(['openssl', 'x509', '-noout', '-ext', 'keyUsage,extendedKeyUsage'],
                            input=ssl.DER_cert_to_PEM_cert(der))
                check('keyUsage has Digital Signature', 'Digital Signature' in txt, txt)
                check('extendedKeyUsage has TLS Web Server Authentication', 'Server Authentication' in txt, txt)
                c, txt = sh(['openssl', 'x509', '-noout', '-checkend', str(14 * 86400)], input=ssl.DER_cert_to_PEM_cert(der))
                check('gateway cert valid for at least 14 more days', c == 0, txt)
                served = ssl.DER_cert_to_PEM_cert(der).strip()
                ondisk = open(os.path.join(ROOT, 'certs', 'apisix', 'apisix.crt')).read()
                check('served cert is certs/apisix/apisix.crt', served.split('-----')[2].strip().replace('\n', '')
                      in ondisk.replace('\n', ''), 'differs')
        except Exception as e:
            check(f'cert chains to certs/ca/ca.crt and matches {sni}', False, e)
    try:
        with socket.create_connection(('localhost', 9443), 10) as s, \
                ssl.create_default_context().wrap_socket(s, server_hostname='localhost'):
            pass
        check('cert is not trusted without the platform CA (not a public cert by accident)', False, 'trusted')
    except ssl.SSLError:
        check('cert is not trusted without the platform CA (not a public cert by accident)', True)
    r = get('http://localhost:9443/')
    check('plain HTTP on 9443 refused', r.status in (0, 400, 497), r.status)

    # ------------------------------------------------------------------------------------------------------------
    section('Gateway routes')
    forged = base64.b64encode(json.dumps({'azp': 'gateway-sso', 'roles': ['admin']}).encode()).decode()
    GARBAGE = 'abc.def.ghi'
    if AUTH_ON and need('auth'):
        check('admin / developer / other-client tokens issued', ADMIN_T and DEV_T and OTHER_T)
        sso_admin = ['/jaeger/', '/jaeger/api/v3/services', '/prometheus/-/healthy', '/activemq/admin/']
        if not need('tracing'):
            sso_admin = [p for p in sso_admin if not p.startswith('/jaeger')]
        if not need('monitoring') and not need('alerting'):
            sso_admin = [p for p in sso_admin if not p.startswith('/prometheus')]
        if not need('mq'):
            sso_admin = [p for p in sso_admin if not p.startswith('/activemq')]
        for p in sso_admin:
            for who, kw, want in [('no auth', {}, (302,)), ('admin token', {'token': ADMIN_T}, (200,)),
                                  ('developer token', {'token': DEV_T}, (403,)),
                                  ('other-client token', {'token': OTHER_T}, (403,)),
                                  ('garbage token', {'token': GARBAGE}, (401,)),
                                  ('developer + forged X-ID-Token', {'token': DEV_T, 'headers': {'X-ID-Token': forged}}, (403,)),
                                  ('forged X-ID-Token only', {'headers': {'X-ID-Token': forged}}, (302,))]:
                r = get(p, **kw)
                check(f'{p} {who} -> {want[0]}', r.status in want, r.status)
            r = get(p)
            check(f'{p} unauthenticated redirect goes to realm mule sign-in',
                  r.headers.get('Location', '').startswith(GW + '/auth/realms/mule/protocol/openid-connect/auth'),
                  r.headers.get('Location'))
        for p in ['/', '/jaeger/', '/activemq/admin/']:
            h = get(p, token=ADMIN_T).headers
            check(f'{p}: X-Frame-Options DENY + frame-ancestors none', h.get('X-Frame-Options') == 'DENY'
                  and "frame-ancestors 'none'" in (h.get('Content-Security-Policy') or ''), dict(h))
        for who, kw, want in [('no auth', {}, 302), ('admin', {'token': ADMIN_T}, 200), ('developer', {'token': DEV_T}, 200),
                              ('garbage', {'token': GARBAGE}, 401)]:
            check(f'home / {who} -> {want}', get('/', **kw).status == want, get('/', **kw).status)
        r = get('/logout', headers={'Sec-Fetch-Site': 'cross-site'})
        check('cross-site /logout -> 403', r.status == 403, r.status)
        r = get('/logout', headers={'Sec-Fetch-Site': 'same-origin'})
        check('same-origin /logout is not refused', r.status in (200, 302), r.status)
        if need('mq'):
            for p in ['/activemq/api/jolokia/read/org.apache.activemq:type=Broker,brokerName=localhost', '/activemq/api',
                      '/activemq/api/message/x?type=queue', '/activemq/API/jolokia']:
                r = get(p, token=ADMIN_T)
                check(f'{p[:40]} blocked for admin -> 403/404', r.status in (403, 404), r.status)
            r = get('/activemq', token=ADMIN_T)
            loc = r.headers.get('Location', '')
            check('/activemq (no slash) redirects to an https URL under /activemq/',
                  r.status in (200,) or (loc.startswith(GW + '/activemq/') or loc.startswith('/activemq/')),
                  f'{r.status} Location={loc}')
        if need('monitoring') or need('alerting'):
            r = get('/prometheus', token=ADMIN_T)
            check('/prometheus redirects under /prometheus/', r.status == 302
                  and '/prometheus/' in r.headers.get('Location', ''), r.headers.get('Location'))
    else:
        skip('SSO route matrix', 'GATEWAY_AUTH=off or auth profile off')
    if not need('alerting'):
        r = get('/alertmanager/', token=ADMIN_T) if ADMIN_T else get('/alertmanager/')
        check('/alertmanager/ (profile off) is not served (5xx/302, so the home card greys out)',
              r.status >= 500 or r.status == 302, r.status)
    # 9443 vs 9080
    r = get('/opensearch/_cluster/health', auth=('admin', ENV['OPENSEARCH_ADMIN_PASSWORD']))
    check('/opensearch on 9443 -> 404 even with the right password', r.status == 404, r.status)
    check('/opensearch (root) on 9443 -> 404', get('/opensearch').status == 404)
    if need('logging') or need('tracing'):
        check('/opensearch on 9080 without auth -> 401', get(LO + '/opensearch/_cluster/health').status == 401)
        check('/opensearch on 9080 as admin -> 200', os_api('GET', '_cluster/health').status == 200)
    if need('auth'):
        for p in ['/auth/admin/master/console/', '/auth/realms/master/.well-known/openid-configuration',
                  '/auth/realms/MASTER/account', '/auth/admin/realms/master/users', '/auth/realms/Master/protocol/openid-connect/token',
                  '/auth/realms/mule/../master/account']:
            r = get(p)
            check(f'{p} on 9443 -> 404', r.status == 404, r.status)
        check('master realm on 9080 -> 200', get(LO + '/auth/realms/master/.well-known/openid-configuration').status == 200)
        check('realm mule on 9443 -> 200', get('/auth/realms/mule/.well-known/openid-configuration').status == 200)
        h = get('/auth/realms/mule/account', headers={'Origin': 'https://evil.example'}).headers
        check('no wildcard CORS on /auth', h.get('Access-Control-Allow-Origin') in (None, ''), h.get('Access-Control-Allow-Origin'))
        body, fh = form({'grant_type': 'password', 'client_id': 'mule-api-gateway', 'username': 'developer',
                         'password': ENV['KEYCLOAK_REALM_DEV_PASSWORD'], 'client_secret': ENV['MULE_GATEWAY_CLIENT_SECRET']})
        r = http('POST', '/auth/realms/mule/protocol/openid-connect/token', body, dict(fh, Origin='https://evil.example'))
        check('token endpoint: no CORS for a foreign origin',
              r.headers.get('Access-Control-Allow-Origin') not in ('*', 'https://evil.example'), r.headers.get('Access-Control-Allow-Origin'))
    for p in ['/', '/jaeger/', '/dashboards/app/home', '/grafana/login', '/runtime-manager/']:
        h = get(p, headers={'Origin': 'https://evil.example'}).headers
        check(f'no wildcard/foreign CORS on {p}', h.get('Access-Control-Allow-Origin') in (None, ''), h.get('Access-Control-Allow-Origin'))
    r = http('OPTIONS', '/api/v1/status', headers={'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'GET'})
    check('/api CORS never allows credentials (bearer-only API)', r.headers.get('Access-Control-Allow-Credentials') != 'true',
          dict(r.headers))
    check('unknown path -> 404', get('/t-stack-no-such-route').status == 404)
    r = get('/runtime-manager')
    check('/runtime-manager -> redirect to /runtime-manager/', r.status in (301, 302) and
          r.headers.get('Location', '').endswith('/runtime-manager/'), r.headers.get('Location'))
    check('/runtime-manager/api/apps without auth -> 401', get('/runtime-manager/api/apps').status == 401)
    if need('logging'):
        r = get('/dashboards/')
        check('/dashboards/ without session -> Dashboards openid sign-in', r.status == 302 and '/dashboards/auth/openid' in
              r.headers.get('Location', ''), r.headers.get('Location'))
    if need('monitoring'):
        check('/grafana/api/health -> 200', get('/grafana/api/health').status == 200)
        check('/grafana/api/datasources anonymous -> 401', get('/grafana/api/datasources').status == 401)
        check('/grafana admin/admin -> 401', get('/grafana/api/datasources', auth=('admin', 'admin')).status == 401)
    # request body limit: 50m gateway-wide (only header sent, no upload)
    bh = {'Content-Type': 'application/octet-stream', 'Authorization': 'Bearer ' + DEV_T} if AUTH_ON else {}
    st = raw_https('/api/v1/status', dict(bh, **{'Content-Length': str(60 * 1024 * 1024)}))
    check('body over 50 MB -> 413', st == 413, st)
    st = raw_https('/api/v1/status', dict(bh, **{'Content-Length': '1000'}), b'x' * 1000)
    check('small body passes the size limit (405 from the app)', st == 405, st)
    # /otlp key-auth
    if need('tracing'):
        empty = {'resourceSpans': []}
        check('/otlp without x-otlp-token -> 401', http('POST', '/otlp/v1/traces', empty).status == 401)
        check('/otlp with a wrong token -> 401', http('POST', '/otlp/v1/traces', empty, {'x-otlp-token': 'nope'}).status == 401)
        check('/otlp with OTLP_INGEST_TOKEN -> 200', http('POST', '/otlp/v1/traces', empty,
                                                          {'x-otlp-token': ENV['OTLP_INGEST_TOKEN']}).status == 200)
        check('/otlp GET -> 404 (POST only)', get('/otlp/v1/traces').status == 404)
        check('/otlp token in a query string is not accepted', http('POST', '/otlp/v1/traces?x-otlp-token=' +
                                                                   urllib.parse.quote(ENV['OTLP_INGEST_TOKEN']), empty).status == 401)
    # /api identity headers: live route config (Control API) clears them before the backend
    routes = control('/v1/routes') or []
    api_routes = [r.get('value', r) for r in routes if str(r.get('value', r).get('uri', '')).startswith('/api')]
    check('Control API lists the /api routes', len(api_routes) >= 2, len(api_routes))
    if AUTH_ON:
        for rt in api_routes:
            pl = rt.get('plugins', {})
            oc, post = pl.get('openid-connect', {}), json.dumps(pl.get('serverless-post-function', {}))
            check(f'{rt["uri"]}: openid-connect sets no X-Userinfo/X-ID-Token/X-Access-Token',
                  oc.get('bearer_only') is True and not oc.get('set_userinfo_header') and not oc.get('set_id_token_header')
                  and not oc.get('set_access_token_header'), 'header flags')
            check(f'{rt["uri"]}: client-sent X-Tenant-ID/X-ID-Token/X-Userinfo/X-Access-Token are dropped',
                  all(h in post for h in ['X-Tenant-ID', 'X-ID-Token', 'X-Userinfo', 'X-Access-Token']), 'post-function')
    hc = control('/v1/healthcheck') or []
    mw = next((u for u in hc if u.get('name') == '/upstreams/1'), None)
    check('APISIX active health checks run on the /api upstream', mw is not None, 'no healthcheck for /upstreams/1')
    if mw:
        nodes = {n.get('hostheader') or n.get('hostname'): n.get('status') for n in mw['nodes']}
        check('every /api upstream node is healthy', nodes and all(s == 'healthy' for s in nodes.values()), nodes)
        app = wait(lambda: rm_app(ENV.get('MULEAPP_ARTIFACT_ID', 'ce-mule-base')), 60, 5) or {}
        aw = set(app.get('workers', {}))
        check('the /api upstream nodes are the default app workers', aw and aw == set(nodes), (aw, nodes))

    # ------------------------------------------------------------------------------------------------------------
    section('Stream 9100 and Fluent Bit')
    if need('logging'):
        try:
            with socket.create_connection(('localhost', 9100), 5):
                pass
            check('TCP 9100 accepts connections', True)
        except OSError as e:
            check('TCP 9100 accepts connections', False, e)
    else:
        skip('stream 9100', 'logging profile off')

    # ------------------------------------------------------------------------------------------------------------
    section('Keycloak')
    if need('auth'):
        d = get('/auth/realms/mule/.well-known/openid-configuration').json()
        check('realm mule discovery: issuer on 9443', d.get('issuer') == GW + '/auth/realms/mule', d.get('issuer'))
        check('realm mule discovery: token endpoint on 9443', d.get('token_endpoint', '').startswith(GW + '/auth/'), d.get('token_endpoint'))
        a, dv = claims(ADMIN_T), claims(DEV_T)
        check('admin token: tenant_id default', a.get('tenant_id') == 'default', a.get('tenant_id'))
        check('admin token: realm role admin', 'admin' in a.get('roles', []) and 'admin' in a.get('realm_access', {}).get('roles', []), a.get('roles'))
        check('admin token: azp mule-api-gateway + api-access', a.get('azp') == 'mule-api-gateway' and 'api-access' in
              a.get('resource_access', {}).get('mule-api-gateway', {}).get('roles', []), a.get('azp'))
        check('developer token: tenant_id demo', dv.get('tenant_id') == 'demo', dv.get('tenant_id'))
        check('developer token: no admin role', 'admin' not in dv.get('roles', []) and 'user' in dv.get('roles', []), dv.get('roles'))
        check('token issuer is the public 9443 URL', dv.get('iss') == GW + '/auth/realms/mule', dv.get('iss'))
        idt = claims(kc_token('developer', ENV['KEYCLOAK_REALM_DEV_PASSWORD']).get('id_token', ''))
        check('developer ID token carries tenant_id and roles', idt.get('tenant_id') == 'demo' and idt.get('roles') == ['user'], idt.get('roles'))
        r = token_req({'grant_type': 'client_credentials', 'client_id': 'mule-api-gateway',
                       'client_secret': ENV['MULE_GATEWAY_CLIENT_SECRET']})
        check('client_credentials refused for mule-api-gateway', r.status in (400, 401) and 'unauthorized_client' in r.text, r.status)
        r = token_req({'grant_type': 'password', 'client_id': 'mule-api-gateway', 'client_secret': 'wrong',
                       'username': 'developer', 'password': ENV['KEYCLOAK_REALM_DEV_PASSWORD']})
        check('wrong client secret refused', r.status == 401, r.status)
        for c in ['dashboards', 'gateway-sso', 'grafana', 'runtime-manager']:
            r = token_req({'grant_type': 'password', 'client_id': c, 'username': 'developer',
                           'password': ENV['KEYCLOAK_REALM_DEV_PASSWORD']})
            check(f'password grant refused for browser client {c}', r.status in (400, 401), r.status)
        check('master realm token with KEYCLOAK_ADMIN_USER/PASSWORD', bool(MT))
        m = kcadm('GET', 'master').json()
        check('master realm: sslRequired none', m.get('sslRequired') == 'none', m.get('sslRequired'))
        check('master realm: frontendUrl http://localhost:9080/auth', m.get('attributes', {}).get('frontendUrl') ==
              'http://localhost:9080/auth', m.get('attributes', {}).get('frontendUrl'))
        check('master realm: brute-force protection on', m.get('bruteForceProtected') is True)
        mu = kcadm('GET', 'mule').json()
        check('realm mule: brute-force protection on', mu.get('bruteForceProtected') is True and mu.get('failureFactor', 0) > 0,
              (mu.get('bruteForceProtected'), mu.get('failureFactor')))
        check('realm mule: sslRequired external or all', mu.get('sslRequired') in ('external', 'all'), mu.get('sslRequired'))
        locs = [get('/auth').headers.get('Location', '') for _ in range(3)]
        check('/auth on 9443 never redirects to the 9080 frontend URL (after master-realm calls)',
              all(l.startswith(GW + '/auth/') or l.startswith('/auth/') for l in locs), locs)
        # throwaway user: claims, account API, lockout
        uname, upw = RUN + '-user', 'Pw-' + uuid.uuid4().hex + '!'
        r = kcadm('POST', 'mule/users', {'username': uname, 'enabled': True, 'email': f'{uname}@example.invalid',
                                         'emailVerified': True, 'firstName': 'T', 'lastName': 'Stack',
                                         'attributes': {'tenant_id': [RUN + '-a']},
                                         'credentials': [{'type': 'password', 'value': upw, 'temporary': False}]})
        check('create throwaway Keycloak user', r.status == 201, r.status)
        uid = (kcadm('GET', f'mule/users?exact=true&username={uname}').json() or [{}])[0].get('id')
        if uid:
            cleanups.append((f'delete Keycloak user {uname}', lambda uid=uid: kcadm('DELETE', f'mule/users/{uid}')))
            tk = kc_token(uname, upw)
            c = claims(tk.get('access_token', ''))
            check('throwaway user token: tenant_id from the user attribute', c.get('tenant_id') == RUN + '-a', c.get('tenant_id'))
            check('throwaway user without api-access role: /api -> 403', get('/api/v1/status', token=tk.get('access_token')).status == 403)
            acct = get('/auth/realms/mule/account/', token=tk.get('access_token'), headers={'Accept': 'application/json'})
            check('account API readable by a new user', acct.status == 200, acct.status)
            for who, tk2 in [('developer', DEV_T), ('admin', ADMIN_T)]:
                r = get('/auth/realms/mule/account/', token=tk2, headers={'Accept': 'application/json'})
                check(f'account API readable by the realm user {who} (My account page works)', r.status == 200,
                      f'{r.status} {r.text[:100]}')
            body = acct.json() if acct.status == 200 else {}
            body.setdefault('attributes', {})['tenant_id'] = ['acme-corp']
            r = http('POST', '/auth/realms/mule/account/', body, token=tk.get('access_token'), headers={'Accept': 'application/json'})
            check('account API refuses a tenant_id change', r.status == 400 and 'read-only' in r.text, f'{r.status} {r.text[:150]}')
            after = kcadm('GET', f'mule/users/{uid}').json().get('attributes', {}).get('tenant_id')
            check('tenant_id unchanged after the attempt', after == [RUN + '-a'], after)
            r = http('POST', '/auth/realms/mule/account/', {'username': uname, 'email': f'{uname}@example.invalid', 'firstName': 'T',
                                                            'lastName': 'Changed', 'attributes': {'tenant_id': ['acme-corp']}},
                     token=tk.get('access_token'), headers={'Accept': 'application/json'})
            after = kcadm('GET', f'mule/users/{uid}').json().get('attributes', {}).get('tenant_id')
            check('tenant_id unchanged by a minimal account update', after == [RUN + '-a'], (r.status, after))
            # lockout after failureFactor wrong passwords
            ff = mu.get('failureFactor', 10)
            for _ in range(ff):
                kc_token(uname, 'wrong-' + uuid.uuid4().hex)
            check(f'brute force: correct password refused after {ff} failures', not kc_token(uname, upw))
            bf = kcadm('GET', f'mule/attack-detection/brute-force/users/{uid}').json()
            check('brute force: user reported as locked', bf.get('disabled') is True, bf)
        # identity of other users is safe: developer still signs in (never locked by these tests)
        check('developer not locked', bool(dev_token()))
    else:
        skip('Keycloak', 'auth profile off')

    # ------------------------------------------------------------------------------------------------------------
    section('SSO end to end (one password prompt per user)')

    class Browser:
        def __init__(self, user, pw):
            self.user, self.pw, self.logins = user, pw, 0
            self.jar = cookiejar.CookieJar()
            self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                                  urllib.request.HTTPSHandler(context=CTX))

        def req(self, path, data=None, headers=None, method=None, raw=None):
            url = path if path.startswith('http') else GW + path
            body = raw if raw is not None else (urllib.parse.urlencode(data).encode() if data else None)
            rq = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
            try:
                r = self.op.open(rq, timeout=60)
                b, code, final = r.read().decode('utf-8', 'replace'), r.status, r.geturl()
            except urllib.error.HTTPError as e:
                b, code, final = e.read().decode('utf-8', 'replace'), e.code, e.geturl()
            m = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', b)
            if m and data is None and raw is None:
                self.logins += 1
                import html as _h
                return self.req(_h.unescape(m.group(1)), {'username': self.user, 'password': self.pw})
            return code, final, b

        def jpost(self, path, body, method='POST'):
            return self.req(path, headers={'osd-xsrf': 'true', 'Content-Type': 'application/json'},
                            raw=json.dumps(body).encode(), method=method)

    def sso(user, pw, admin):
        b = Browser(user, pw)
        code, final, body = b.req('/')
        check(f'{user}: home page after sign-in', code == 200 and 'Mule Platform' in body, f'{code} {final}')
        check(f'{user}: one password prompt so far', b.logins == 1, b.logins)
        tools = [('/jaeger/', 'tracing'), ('/jaeger/search', 'tracing'), ('/prometheus/graph', 'monitoring'),
                 ('/activemq/admin/', 'mq')]
        for path, prof in tools:
            if not need(prof):
                continue
            want = 200 if admin else 403
            code, final, _ = b.req(path)
            check(f'{user}: {path} -> {want}', code == want, f'{code} {final}')
        if need('monitoring'):
            b.req('/grafana/login/generic_oauth')
            code, _, body = b.req('/grafana/api/user')
            if admin:
                u = json.loads(body) if code == 200 else {}
                check(f'{user}: Grafana signed in via Keycloak', u.get('login') == user, f'{code} {body[:120]}')
                code, _, body = b.req('/grafana/api/user/orgs')
                orgs = json.loads(body) if code == 200 else []
                check(f'{user}: Grafana org role Admin', any(o.get('role') == 'Admin' for o in orgs), orgs)
            else:
                check(f'{user}: Grafana refuses non-admin', code != 200, f'{code} {body[:120]}')
        if need('logging'):
            b.req('/dashboards/auth/openid/login')
            code, _, body = b.req('/dashboards/api/v1/configuration/account', headers={'osd-xsrf': 'true'})
            acct = json.loads(body).get('data', {}) if code == 200 else {}
            check(f'{user}: Dashboards signed in', acct.get('user_name') == user, f'{code} {body[:160]}')
            roles = acct.get('roles', [])
            check(f'{user}: Dashboards roles', ('all_access' in roles) == admin and 'sso_tenant_logs' in roles, roles)
            agg = {'size': 0, 'aggs': {'t': {'terms': {'field': 'tenant_id', 'size': 100}}}}
            code, _, body = b.jpost('/dashboards/api/console/proxy?path=mule-logs-*/_search&method=POST', agg)
            seen = sorted(x['key'] for x in json.loads(body)['aggregations']['t']['buckets']) if code == 200 else body[:150]
            check(f'{user}: tenants visible in Dashboards ({"all" if admin else "demo only"})',
                  code == 200 and (len(seen) > 1 if admin else seen in (['demo'], [])), seen)
            code, body = b.jpost('/dashboards/api/v1/multitenancy/tenant', {'tenant': '', 'username': user})[0::2]
            check(f'{user}: switch to the Global tenant', code == 200, f'{code} {body[:120]}')
            code, _, body = b.jpost(f'/dashboards/api/saved_objects/index-pattern/{RUN}-probe?overwrite=true',
                                    {'attributes': {'title': RUN + '-probe-*'}})
            check(f'{user}: write to the Global tenant -> {200 if admin else 403}', code == (200 if admin else 403), f'{code} {body[:120]}')
            if code == 200:
                b.jpost(f'/dashboards/api/saved_objects/index-pattern/{RUN}-probe', {}, 'DELETE')
            b.jpost('/dashboards/api/v1/multitenancy/tenant', {'tenant': '__user__', 'username': user})
        code, final, body = b.req('/runtime-manager/login')
        if admin:
            check(f'{user}: Runtime Manager signed in', code == 200 and '/login' not in final and 'lacks' not in body, f'{code} {final}')
        else:
            check(f'{user}: Runtime Manager refuses non-admin', 'lacks' in body or code == 403, f'{code} {final}')
        code, final, _ = b.req('/auth/admin/mule/console/')
        check(f'{user}: Keycloak admin console page', code == 200, f'{code} {final}')
        code, final, _ = b.req('/auth/realms/mule/account/')
        check(f'{user}: Keycloak My account page', code == 200, f'{code} {final}')
        check(f'{user}: still one password prompt in total', b.logins == 1, b.logins)
        before = b.logins
        code, final, _ = b.req('/logout')
        check(f'{user}: /logout ends the session (next page asks for the password)', b.logins == before + 1, f'{b.logins} {final}')

    if AUTH_ON and need('auth'):
        sso('admin', ENV['KEYCLOAK_REALM_ADMIN_PASSWORD'], True)
        sso('developer', ENV['KEYCLOAK_REALM_DEV_PASSWORD'], False)
    else:
        skip('SSO end to end', 'GATEWAY_AUTH=off or auth profile off')

    # ------------------------------------------------------------------------------------------------------------
    section('Mule API through the gateway')
    tok = DEV_T if AUTH_ON else None
    r = get('/api/v1/status', token=tok)
    check('/api/v1/status -> 200 JSON status OK', r.status == 200 and r.json().get('status') == 'OK', f'{r.status} {r.text[:100]}')
    check('rate limit header present (100/min)', r.headers.get('X-RateLimit-Limit') == '100', r.headers.get('X-RateLimit-Limit'))
    if AUTH_ON:
        check('/api/v1/status without token -> 401', get('/api/v1/status').status == 401)
        check('/api/v1/status admin token -> 200', get('/api/v1/status', token=ADMIN_T).status == 200)
        check('/api/v1/status other-client token -> 403', get('/api/v1/status', token=OTHER_T).status == 403)
        check('/api/v1/status garbage token -> 401', get('/api/v1/status', token=GARBAGE).status == 401)
        check('/api/other without token -> 401', get('/api/t-stack').status == 401)
        check('/api/v1/status Basic auth -> 401', get('/api/v1/status', auth=('admin', 'admin')).status == 401)
    for m, p, want, msg in [('GET', '/api/v1/t-stack-nope', 404, 'Resource not found'), ('GET', '/api/t-stack', 404, 'Resource not found'),
                            ('POST', '/api/v1/status', 405, 'Method not allowed'), ('DELETE', '/api/v1/status', 405, 'Method not allowed')]:
        r = http(m, p, token=tok)
        ok = r.status == want and 'json' in (r.headers.get('Content-Type') or '')
        try:
            ok = ok and r.json().get('message') == msg
        except Exception:
            ok = False
        check(f'{m} {p} -> {want} with a JSON error body', ok, f'{r.status} {r.text[:100]}')
    if need('logging'):
        # the app may be mid-redeploy (Maven auto updates): wait until every worker runs it
        app = wait_app_started(ENV.get('MULEAPP_ARTIFACT_ID', 'ce-mule-base'), 300) or {}
        started = set(app.get('workers', {}))
        for i in range(8):
            get('/api/v1/status', token=tok, headers={'X-Correlation-ID': f'{RUN}-rr-{i}'})
        def rr():
            h = os_search('mule-logs-*', {'prefix': {'contextMap.correlationId.keyword': f'{RUN}-rr-'}}, 200) or []
            p = {}
            for x in h:
                p.setdefault(x['contextMap']['correlationId'], x.get('worker_id'))
            return p if len(p) >= 8 else None
        per = wait(rr, 40, 2) or rr() or {}
        ws = set(per.values())
        check('round robin: requests spread over every worker of the default app', len(per) == 8 and ws == started,
              f'{len(per)} requests on {sorted(ws)}; app workers {sorted(started)}')
    else:
        skip('round robin via logs', 'logging profile off')

    # ------------------------------------------------------------------------------------------------------------
    section('Log ingestion (TCP 9100 -> Fluent Bit -> OpenSearch)')
    if need('logging'):
        tokn = ENV['LOG_INGEST_TOKEN']
        ingest([{'auth_token': tokn, 'application': RUN, 'log_type': 'mule', 'level': 'INFO', 'message': f'{RUN} good',
                 'tenant_id': 'T-Stack Acme!', 'host': 'h1'},
                {'auth_token': tokn, 'log_type': 'audit', 'level': 'INFO', 'message': f'{RUN} other', 'tenant_id': 'acme-corp'},
                {'application': RUN, 'log_type': 'mule', 'level': 'INFO', 'message': f'{RUN} notoken', 'tenant_id': 'acme-corp'},
                {'auth_token': 'wrong', 'application': RUN, 'log_type': 'mule', 'level': 'INFO', 'message': f'{RUN} wrongtoken'},
                {'auth_token': tokn, 'application': RUN, 'log_type': 'mule', 'level': 'WARN', 'message': f'{RUN} notenant'}])
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
                u.sendto(json.dumps({'auth_token': tokn, 'application': RUN, 'log_type': 'mule', 'message': f'{RUN} udp'}).encode(),
                         ('127.0.0.1', 5000))
        except OSError:
            pass
        good = os_wait('mule-logs-*', {'term': {'message.keyword': f'{RUN} good'}})
        g = good[0] if good else {}
        check('event with LOG_INGEST_TOKEN indexed into mule-logs-*', bool(good))
        check('tenant_id cleaned and lowercased', g.get('tenant_id') == 't-stackacme', g.get('tenant_id'))
        check('original tenant kept in tenant_id_original', g.get('tenant_id_original') == 'T-Stack Acme!', g.get('tenant_id_original'))
        check('auth_token removed from the document', 'auth_token' not in g, list(g))
        check('host renamed to source_host', g.get('source_host') == 'h1' and 'host' not in g, list(g))
        nt = os_wait('mule-logs-*', {'term': {'message.keyword': f'{RUN} notenant'}})
        check('missing tenant_id -> unknown', nt and nt[0].get('tenant_id') == 'unknown', nt)
        other = os_wait('logstash-*', {'term': {'message.keyword': f'{RUN} other'}})
        check('non-mule event goes to logstash-*', bool(other))
        time.sleep(3)
        for m in ['notoken', 'wrongtoken', 'udp']:
            h = os_search('mule-logs-*,logstash-*', {'term': {'message.keyword': f'{RUN} {m}'}})
            check(f'event "{m}" dropped', h == [], h)
        check('the rest of the run\'s events are not in logstash-*', not os_search('logstash-*', {'term': {'application': RUN}}))
    else:
        skip('log ingestion', 'logging profile off')

    # ------------------------------------------------------------------------------------------------------------
    section('Tenant comes from the token (end to end)')
    if AUTH_ON and need('auth') and need('logging'):
        cid = f'{RUN}-tenancy'
        r = get('/api/v1/status', token=DEV_T, headers={'X-Tenant-ID': 'acme-corp', 'X-Correlation-ID': cid})
        check('developer call with forged X-Tenant-ID -> 200', r.status == 200, r.status)
        hits = os_wait('mule-logs-*', {'term': {'contextMap.correlationId.keyword': cid}}, 2)
        ts = {h.get('tenant_id') for h in hits}
        check('logged as tenant demo, never acme-corp', ts == {'demo'}, ts)
        trace_id = next((h['contextMap'].get('trace.id') for h in hits if h.get('contextMap', {}).get('trace.id')), None)
        if need('tracing') and trace_id:
            spans = wait(lambda: (s := jaeger_trace(trace_id, ADMIN_T)) and any('tenant.id' in x['attrs'] for x in s) and s, 60, 3) or []
            root = next((x for x in spans if not x['span'].get('parentSpanId')), None)
            check('trace of the call found in Jaeger (/jaeger/api/v3)', root is not None, len(spans))
            if root:
                check('root span tenant.id = demo', root['attrs'].get('tenant.id') == 'demo', root['attrs'].get('tenant.id'))
                check('root span http.* attributes', root['attrs'].get('http.method') == 'GET' and
                      str(root['attrs'].get('http.status_code')) == '200' and root['attrs'].get('http.target') == '/api/v1/status',
                      root['attrs'])
                check('agent scope io.opentelemetry.mule4 0.3.0', root['scope'] == {'name': 'io.opentelemetry.mule4', 'version': '0.3.0'},
                      root['scope'])
                check('resource: service ce-mule-base, worker.id, SDK 1.67.0', root['res'].get('service.name') == 'ce-mule-base'
                      and str(root['res'].get('worker.id', '')).startswith('mule-') and root['res'].get('telemetry.sdk.version') == '1.67.0',
                      root['res'])
        elif need('tracing'):
            check('log carries the trace id', False, 'no trace.id in contextMap')
        # a user without tenant_id: a forged X-Tenant-ID must not be used either (gateway drops it)
        uname, upw = RUN + '-nt', 'Pw-' + uuid.uuid4().hex + '!'
        r = kcadm('POST', 'mule/users', {'username': uname, 'enabled': True, 'email': f'{uname}@example.invalid', 'emailVerified': True,
                                         'firstName': 'T', 'lastName': 'Stack',
                                         'credentials': [{'type': 'password', 'value': upw, 'temporary': False}]})
        uid = (kcadm('GET', f'mule/users?exact=true&username={uname}').json() or [{}])[0].get('id')
        if uid:
            cleanups.append((f'delete Keycloak user {uname}', lambda uid=uid: kcadm('DELETE', f'mule/users/{uid}')))
            cl = (kcadm('GET', 'mule/clients?clientId=mule-api-gateway').json() or [{}])[0].get('id')
            role = kcadm('GET', f'mule/clients/{cl}/roles/api-access').json()
            kcadm('POST', f'mule/users/{uid}/role-mappings/clients/{cl}', [role])
            t2 = kc_token(uname, upw).get('access_token', '')
            check('tenant-less user token has no tenant_id claim', t2 and 'tenant_id' not in claims(t2))
            cid2 = f'{RUN}-notenant'
            r = get('/api/v1/status', token=t2, headers={'X-Tenant-ID': 'acme-corp', 'X-Correlation-ID': cid2})
            check('tenant-less user with api-access -> 200', r.status == 200, r.status)
            hits = os_wait('mule-logs-*', {'term': {'contextMap.correlationId.keyword': cid2}}, 2)
            ts = {h.get('tenant_id') for h in hits}
            check('forged X-Tenant-ID of a tenant-less token is dropped (logged as unknown)', ts == {'unknown'}, ts)
    else:
        skip('tenant from token', 'needs auth + logging profiles and GATEWAY_AUTH=on')

    # ------------------------------------------------------------------------------------------------------------
    section('Multi-tenancy DLS (manage-tenants.sh)')
    if need('logging'):
        tenant, tuser, tpw = RUN, RUN + '-u', 'Pw-' + uuid.uuid4().hex
        other_t = RUN + '-other'
        try:
            c, o = run(f'./config/scripts/tenants/manage-tenants.sh create {tenant} --user {tuser} --password {tpw}', 120)
            check('manage-tenants.sh create', c == 0 and 'Role created' in o, o[-300:])
            check('script output has no password', tpw not in o)
            c, o = run('./config/scripts/tenants/manage-tenants.sh list', 120)
            check('manage-tenants.sh list shows the tenant', c == 0 and f'tenant_{tenant}' in o and f'tenant-{tenant}' in o, o[-300:])
            ingest([{'auth_token': ENV['LOG_INGEST_TOKEN'], 'application': RUN, 'log_type': 'mule', 'message': f'{RUN} dls {i}',
                     'tenant_id': t} for i, t in enumerate([tenant, tenant, other_t, 'demo'])])
            os_wait('mule-logs-*', {'prefix': {'message.keyword': f'{RUN} dls'}}, 4)
            c, o = run(f'./config/scripts/tenants/manage-tenants.sh verify {tenant}', 120)
            check('manage-tenants.sh verify finds the tenant\'s docs', c == 0 and 'Found 2 documents' in o, o[-300:])
            mine = os_search('mule-logs-*', {'prefix': {'message.keyword': f'{RUN} dls'}}, auth=(tuser, tpw))
            check('tenant user sees exactly its 2 seeded docs', mine is not None and len(mine) == 2 and
                  {h['tenant_id'] for h in mine} == {tenant}, mine)
            r = os_api('POST', 'mule-logs-*,logstash-*/_search', {'size': 0, 'aggs': {'t': {'terms': {'field': 'tenant_id', 'size': 100}}}},
                       auth=(tuser, tpw))
            seen = [b['key'] for b in r.json()['aggregations']['t']['buckets']] if r.status == 200 else r.status
            check('tenant user: aggregation over all logs shows only its tenant', seen == [tenant], seen)
            r = os_api('PUT', f'mule-logs-{RUN}/_doc/1', {'tenant_id': tenant}, auth=(tuser, tpw))
            check('tenant user cannot write', r.status == 403, r.status)
            r = os_api('GET', '_plugins/_security/api/internalusers', auth=(tuser, tpw))
            check('tenant user cannot read the security config', r.status in (401, 403), r.status)
            r = os_api('GET', 'jaeger-span-*/_search?size=1', auth=(tuser, tpw))
            check('tenant user cannot read traces', r.status == 403, r.status)
            r = os_api('POST', 'mule-logs-*/_search?ignore_unavailable=true', {'size': 0, 'query': {'prefix': {'message.keyword': f'{RUN} dls'}}})
            check('admin sees all 4 seeded docs', r.status == 200 and r.json()['hits']['total']['value'] == 4, r.text[:200])
        finally:
            c, o = run(f'./config/scripts/tenants/manage-tenants.sh delete {tenant} --force', 120)
        check('manage-tenants.sh delete', c == 0 and 'Role deleted' in o, o[-300:])
        check('tenant role gone', os_api('GET', f'_plugins/_security/api/roles/tenant_{tenant}').status == 404)
        check('tenant user gone (401)', os_api('GET', '_cluster/health', auth=(tuser, tpw)).status == 401)
        if MT:
            g = kcadm('GET', f'mule/groups?search=tenant-{tenant}').json()
            names = json.dumps(g)
            check('Keycloak tenant group gone', f'"tenant-{tenant}"' not in names, names[:200])
        c, o = run(f'./config/scripts/tenants/manage-tenants.sh create "Bad Tenant!"', 60)
        check('manage-tenants.sh rejects an invalid tenant id', c != 0 and 'Invalid tenant_id' in o, o[-200:])
    else:
        skip('DLS', 'logging profile off')

    # ------------------------------------------------------------------------------------------------------------
    section('OpenSearch')
    if need('logging') or need('tracing'):
        h = wait(lambda: (r := os_api('GET', '_cluster/health')).status == 200 and r.json()['status'] == 'green' and r.json(), 60, 3)
        check('cluster green', bool(h), os_api('GET', '_cluster/health').text[:200])
        for t in ['mule-logs-template', 'logstash-template']:
            r = os_api('GET', f'_index_template/{t}')
            s = r.json()['index_templates'][0]['index_template']['template']['settings'] if r.status == 200 else {}
            check(f'index template {t} present, 0 replicas', str(s.get('index', {}).get('number_of_replicas', s.get('number_of_replicas'))) == '0', s)
        r = os_api('GET', '_cat/indices/mule-logs-*,logstash-*,jaeger-*?format=json&h=index,rep,health')
        bad = [i for i in r.json() if i['rep'] != '0' or i['health'] != 'green'] if r.status == 200 else r.status
        check('every log/trace index has 0 replicas and is green', bad == [], bad)
        for p in ['mule-logs-retention', 'logstash-retention', 'jaeger-retention']:
            check(f'ISM policy {p} present', os_api('GET', f'_plugins/_ism/policies/{p}').status == 200)
        c, o = run('./config/scripts/ilm/setup-retention-policy.sh --verify', 180)
        check('setup-retention-policy.sh --verify', c == 0, o[-300:])
        for u, pw in [('admin', 'admin'), ('kibanaserver', 'kibanaserver'), ('readall', 'readall'), ('logstash', 'logstash'),
                      ('kibanaro', 'kibanaro'), ('snapshotrestore', 'snapshotrestore'), ('anomalyadmin', 'anomalyadmin')]:
            check(f'demo user {u}/{pw} -> 401', os_api('GET', '_cluster/health', auth=(u, pw)).status == 401)
        users = os_api('GET', '_plugins/_security/api/internalusers').json()
        demo = {'kibanaserver', 'readall', 'logstash', 'kibanaro', 'snapshotrestore', 'anomalyadmin'} & set(users)
        check('no demo internal users', not demo, demo)
        check('internal user admin exists', 'admin' in users)
        sc = os_api('GET', '_plugins/_security/api/securityconfig').json()
        authc = sc.get('config', {}).get('dynamic', {}).get('authc', {})
        oid = authc.get('openid_auth_domain', {})
        check('security config: openid domain enabled, order 0', oid.get('http_enabled') is True and oid.get('order') == 0, oid)
        check('security config: openid required_audience dashboards',
              oid.get('http_authenticator', {}).get('config', {}).get('required_audience') == 'dashboards', 'audience')
        check('security config: basic auth domain present',
              any(d.get('http_authenticator', {}).get('type') == 'basic' and d.get('http_enabled') for d in authc.values()), list(authc))
        if need('auth'):
            idt = kc_token('admin', ENV['KEYCLOAK_REALM_ADMIN_PASSWORD']).get('id_token', '')
            r = os_api('GET', '_cluster/health', auth=None, headers={'Authorization': 'Bearer ' + idt})
            check('OpenSearch refuses an ID token of another client (aud mule-api-gateway) -> 401', r.status == 401, r.status)
        r = os_api('GET', '_plugins/_security/api/roles/sso_tenant_logs').json().get('sso_tenant_logs', {})
        check('role sso_tenant_logs has DLS on the JWT tenant_id', '${attr.jwt.tenant_id}' in json.dumps(r), 'dls')
    else:
        skip('OpenSearch', 'no profile uses it')

    # ------------------------------------------------------------------------------------------------------------
    section('Tracing (Jaeger)')
    if need('tracing') and AUTH_ON and need('auth'):
        svc = RUN + '-otlp'
        tid, sid = uuid.uuid4().hex, uuid.uuid4().hex[:16]
        now = time.time_ns()
        payload = {'resourceSpans': [{'resource': {'attributes': [{'key': 'service.name', 'value': {'stringValue': svc}}]},
                                      'scopeSpans': [{'scope': {'name': 't-stack'}, 'spans': [{
                                          'traceId': tid, 'spanId': sid, 'name': 't-stack-span', 'kind': 2,
                                          'startTimeUnixNano': str(now - 5_000_000), 'endTimeUnixNano': str(now),
                                          'attributes': [{'key': 'tenant.id', 'value': {'stringValue': 't-stack'}}]}]}]}]}
        r = http('POST', '/otlp/v1/traces', payload, {'x-otlp-token': ENV['OTLP_INGEST_TOKEN']})
        check('OTLP/HTTP span accepted via /otlp', r.status == 200, r.status)
        got = wait(lambda: jaeger_trace(tid, ADMIN_T), 60, 3) or []
        check('the span is queryable via /jaeger/api/v3/traces/<id>', any(x['span']['name'] == 't-stack-span' for x in got), len(got))
        svcs = wait(lambda: (x := get('/jaeger/api/v3/services', token=ADMIN_T).json().get('services', [])) and svc in x and x,
                    60, 5) or get('/jaeger/api/v3/services', token=ADMIN_T).json().get('services', [])
        check('the unique service is listed in /jaeger/api/v3/services', svc in svcs, len(svcs))
        check('ce-mule-base is a Jaeger service', 'ce-mule-base' in svcs, svcs[:10])
        t1 = time.gmtime(time.time() - 600); t2 = time.gmtime(time.time() + 60)
        q = urllib.parse.urlencode({'query.service_name': svc, 'query.start_time_min': time.strftime('%Y-%m-%dT%H:%M:%SZ', t1),
                                    'query.start_time_max': time.strftime('%Y-%m-%dT%H:%M:%SZ', t2), 'query.num_traces': 5})
        r = get('/jaeger/api/v3/traces?' + q, token=ADMIN_T)
        check('trace search by service finds it', r.status == 200 and tid in r.text, r.status)
        r = get('/jaeger/api/v3/services', token=DEV_T)
        check('Jaeger API refused for developer', r.status == 403, r.status)
        r = get('/jaeger/api/v3/services', token=OTHER_T)
        check('Jaeger API refused for other-client admin-cli token', r.status == 403, r.status)
        c, o = sh(['docker', 'inspect', '-f', '{{.State.Health.Status}}', 'jaeger'])
        check('Jaeger healthcheck (13133) healthy', o.strip() == 'healthy', o)
    else:
        skip('tracing', 'tracing/auth profile off or GATEWAY_AUTH=off')

    # ------------------------------------------------------------------------------------------------------------
    section('Prometheus, Grafana, Alertmanager')
    if (need('monitoring') or need('alerting')) and AUTH_ON and need('auth'):
        check('/prometheus/-/healthy', get('/prometheus/-/healthy', token=ADMIN_T).status == 200)
        tg = get('/prometheus/api/v1/targets', token=ADMIN_T).json()['data']['activeTargets']
        jobs = {t['labels']['job']: t['health'] for t in tg}
        for t in tg:
            check(f'target {t["labels"]["job"]} ({t["scrapeUrl"].split("/")[2]}) up', t['health'] == 'up', t.get('lastError'))
        expected_jobs = {'prometheus', 'apisix', 'grafana', 'jaeger' if need('tracing') else None,
                         'fluent-bit' if need('logging') else None, 'alertmanager' if need('alerting') else None,
                         'opensearch-exporter' if need('opensearch-monitoring') else None} - {None}
        check('every expected scrape job has a target', expected_jobs <= set(jobs), expected_jobs - set(jobs))
        groups = get('/prometheus/api/v1/rules', token=ADMIN_T).json()['data']['groups']
        rules = [r for g in groups for r in g['rules']]
        check('rule groups loaded', len(groups) >= 5, len(groups))
        bad = [(r['name'], r.get('lastError')) for r in rules if r.get('health') != 'ok']
        check('every rule evaluates without error', not bad, bad)
        want = set(re.findall(r'-\s*alert:\s*(\S+)', open(os.path.join(ROOT, 'config/prometheus/rules/opensearch-alerts.yml')).read()))
        have = {r['name'] for r in rules if r.get('type') == 'alerting'}
        check(f'all {len(want)} alert rules of the rules file loaded', want == have, want ^ have)
        for a in ['APISIXDown', 'JaegerDown', 'PrometheusDown', 'GrafanaDown', 'OpenSearchClusterDown']:
            check(f'alert {a} defined', a in have)
        cfg = get('/prometheus/api/v1/status/config', token=ADMIN_T).json()['data']['yaml']
        check('external label environment = ENVIRONMENT', f"environment: {ENV.get('ENVIRONMENT')}" in cfg, 'labels')
        check('external label cluster = OPENSEARCH_CLUSTER_NAME', f"cluster: {ENV.get('OPENSEARCH_CLUSTER_NAME')}" in cfg, 'labels')
        check('external labels have no unexpanded ${...}', '${' not in cfg.split('scrape_configs')[0], 'unexpanded')
        rt = get('/prometheus/api/v1/status/runtimeinfo', token=ADMIN_T).json()['data']
        check('Prometheus config reload succeeded', rt.get('reloadConfigSuccess') is True)
        check('Prometheus retention = PROMETHEUS_RETENTION', rt.get('storageRetention', '').startswith(ENV.get('PROMETHEUS_RETENTION', '30d')),
              rt.get('storageRetention'))
        firing = [a['labels']['alertname'] for a in get('/prometheus/api/v1/alerts', token=ADMIN_T).json()['data']['alerts']
                  if a['state'] == 'firing']
        check('no Down alert firing', not [a for a in firing if a.endswith('Down')], firing)
    else:
        skip('Prometheus', 'monitoring profile off or GATEWAY_AUTH=off')
    if need('monitoring'):
        g = (ENV.get('GRAFANA_ADMIN_USER', 'grafana-admin'), ENV['GRAFANA_ADMIN_PASSWORD'])
        h = get('/grafana/api/health').json()
        check('Grafana health: database ok', h.get('database') == 'ok', h)
        u = get('/grafana/api/user', auth=g)
        check('break-glass GRAFANA_ADMIN_USER signs in (basic auth)', u.status == 200 and u.json().get('isGrafanaAdmin') is True, u.status)
        check('break-glass user is not called admin', g[0] != 'admin')
        ds = get('/grafana/api/datasources', auth=g).json() if u.status == 200 else []
        check('Grafana datasources provisioned', len(ds) >= 1, ds)
        for d in ds:
            r = get(f"/grafana/api/datasources/uid/{d['uid']}/health", auth=g)
            check(f"datasource {d['name']} health OK", r.status == 200 and r.json().get('status') == 'OK', r.text[:200])
        dbs = get('/grafana/api/search?type=dash-db', auth=g).json() if u.status == 200 else []
        check('Grafana dashboard Apache APISIX provisioned', any(d['title'] == 'Apache APISIX' for d in dbs), [d['title'] for d in dbs])
        r = get('/grafana/api/frontend/settings', auth=g).json()
        check('Grafana generic OAuth (Keycloak) enabled', 'generic_oauth' in json.dumps(r.get('oauth', {})) if AUTH_ON else True,
              list(r.get('oauth', {})))
    else:
        skip('Grafana', 'monitoring profile off')
    if need('alerting'):
        check('/alertmanager/-/healthy (admin)', get('/alertmanager/-/healthy', token=ADMIN_T).status == 200)
        check('/alertmanager/ developer -> 403', get('/alertmanager/', token=DEV_T).status == 403)
        am = get('/prometheus/api/v1/alertmanagers', token=ADMIN_T).json()['data']['activeAlertmanagers']
        check('Prometheus discovered Alertmanager', len(am) >= 1, am)
    else:
        skip('Alertmanager', 'alerting profile off')

    # ------------------------------------------------------------------------------------------------------------
    section('ActiveMQ')
    if need('mq'):
        def amqp_sasl(mech, user='', pw=''):
            """AMQP 1.0 SASL handshake on 127.0.0.1:5672; returns the sasl-outcome code (0 = ok, 1 = auth failed)."""
            s = socket.create_connection(('127.0.0.1', int(ENV.get('MULE_MQ_AMQP_PORT', 5672))), 5)
            s.settimeout(5)
            buf = b''
            try:
                s.sendall(b'AMQP\x03\x01\x00\x00')

                def frame():
                    nonlocal buf
                    while len(buf) < 4:
                        buf += s.recv(4096)
                    n = struct.unpack('>I', buf[:4])[0]
                    while len(buf) < n:
                        buf += s.recv(4096)
                    f, buf = buf[:n], buf[n:]
                    return f[f[4] * 4:]
                while len(buf) < 8:
                    buf += s.recv(4096)
                buf = buf[8:]
                frame()   # sasl-mechanisms
                resp = (b'\x00' + user.encode() + b'\x00' + pw.encode()) if mech == 'PLAIN' else b''
                m = mech.encode()
                fields = b'\xa3' + bytes([len(m)]) + m + b'\xa0' + bytes([len(resp)]) + resp
                body = b'\x00\x53\x41\xc0' + bytes([len(fields) + 1, 2]) + fields
                s.sendall(struct.pack('>IBBH', 8 + len(body), 2, 1, 0) + body)
                out = frame()
                i = out.find(b'\x00\x53\x44')
                return out[i + 7] if i >= 0 else None
            except Exception as e:
                return f'error {e}'
            finally:
                s.close()
        check('AMQP: ANONYMOUS refused', amqp_sasl('ANONYMOUS') == 1)
        check('AMQP: admin/admin refused', amqp_sasl('PLAIN', 'admin', 'admin') == 1)
        check('AMQP: admin/ACTIVEMQ_ADMIN_PASSWORD accepted (positive control)',
              amqp_sasl('PLAIN', 'admin', ENV['ACTIVEMQ_ADMIN_PASSWORD']) == 0)
        port = ENV.get('MULE_MQ_WEB_CONSOL_PORT', '8161')
        check('console on 127.0.0.1 refuses admin/admin', get(f'http://127.0.0.1:{port}/admin/', auth=('admin', 'admin')).status in (401, 403))
        check('console on 127.0.0.1 refuses anonymous', get(f'http://127.0.0.1:{port}/admin/').status in (401, 403))
        check('jolokia on 127.0.0.1 refuses admin/admin', get(f'http://127.0.0.1:{port}/api/jolokia/version',
                                                               auth=('admin', 'admin')).status in (401, 403, 404))
        if AUTH_ON and need('auth'):
            r = get('/activemq/admin/', token=ADMIN_T)
            check('console via gateway (admin SSO) shows the broker', r.status == 200 and 'ActiveMQ Console' in r.text
                  and 'localhost' in r.text, r.status)
            r = get('/activemq/admin/queues.jsp', token=ADMIN_T)
            check('console queues page renders', r.status == 200 and 'Queues' in r.text, r.status)
            check('console via gateway refused for developer', get('/activemq/admin/', token=DEV_T).status == 403)
    else:
        skip('ActiveMQ', 'mq profile off')

    # ------------------------------------------------------------------------------------------------------------
    section('MySQL')
    if need('db'):
        def mysql(user, pw, sql='select 1'):
            cmd = ['docker', 'exec']
            if pw is not None:
                cmd += ['-e', f'MYSQL_PWD={pw}']
            return sh(cmd + ['ce-base-db-backend', 'mysql', '-h', '127.0.0.1', f'-u{user}', '-N', '-e', sql], timeout=60, input='')
        c, o = mysql('root', ENV['MYSQL_ROOT_PASSWORD'])
        check('root login with MYSQL_ROOT_PASSWORD', c == 0 and o.strip().endswith('1'), o[-200:])
        c, o = mysql('root', None)
        check('root without password refused', c != 0 and 'Access denied' in o, o[-200:])
        c, o = mysql('root', 'root')
        check('root/root refused', c != 0 and 'Access denied' in o, o[-200:])
        c, o = mysql('', None)
        check('anonymous login refused', c != 0, o[-200:])
        c, o = mysql('root', ENV['MYSQL_ROOT_PASSWORD'], "select count(*) from mysql.user where user=''")
        check('no anonymous accounts', c == 0 and o.strip().endswith('0'), o[-200:])
        c, o = mysql(ENV.get('MYSQL_USER', 'ce_user'), ENV['MYSQL_PASSWORD'], f"use {ENV.get('MYSQL_DATABASE')}; select 7*6")
        check('app user MYSQL_USER signs in to MYSQL_DATABASE', c == 0 and o.strip().endswith('42'), o[-200:])
    else:
        skip('MySQL', 'db profile off')

    # ------------------------------------------------------------------------------------------------------------
    section('Ops scripts')
    c, o = '', ''
    for _ in range(3):
        c, o = run('./config/scripts/monitoring/check-health.sh', 120)
        if c == 0:
            break
        time.sleep(10)
    check('check-health.sh exits 0', c == 0, o[-400:])
    if need('logging') or need('tracing'):
        c, o = run('./config/scripts/backup/configure-backup.sh', 120)
        check('configure-backup.sh', c == 0, o[-300:])
        repo = ENV.get('BACKUP_REPOSITORY_NAME', 'backup-repo')
        check('snapshot repository registered', os_api('GET', f'_snapshot/{repo}').status == 200)
        snap = RUN + '-snapshot'
        try:
            c, o = run(f'./config/scripts/backup/backup.sh {snap}', 300)
            check('backup.sh', c == 0 and 'SUCCESS' in o.upper(), o[-300:])
            r = os_api('GET', f'_snapshot/{repo}/{snap}')
            st = r.json().get('snapshots', [{}])[0] if r.status == 200 else {}
            check('backup.sh snapshot is SUCCESS', st.get('state') == 'SUCCESS', st.get('state'))
        finally:
            os_api('DELETE', f'_snapshot/{repo}/{snap}')
        c, o = run('./config/scripts/backup/backup-cleanup.sh --dry-run', 120)
        check('backup-cleanup.sh --dry-run', c == 0, o[-300:])
        # restore.sh on a throwaway index only
        idx, rsnap = RUN + '-restore', RUN + '-rsnap'
        try:
            os_api('PUT', idx, {'settings': {'number_of_replicas': 0, 'number_of_shards': 1}})
            for i in range(3):
                os_api('PUT', f'{idx}/_doc/{i}', {'n': i})
            os_api('POST', f'{idx}/_refresh')
            r = os_api('PUT', f'_snapshot/{repo}/{rsnap}?wait_for_completion=true',
                       {'indices': idx, 'include_global_state': False})
            check('snapshot of the throwaway index', r.status == 200, r.text[:200])
            os_api('DELETE', idx)
            check('throwaway index deleted before restore', os_api('HEAD', idx).status == 404)
            c, o = run(f'echo yes | ./config/scripts/backup/restore.sh {rsnap} {idx}', 300)
            check('restore.sh', c == 0, o[-300:])
            cnt = wait(lambda: (r := os_api('GET', f'{idx}/_count')).status == 200 and r.json()['count'] == 3, 60, 2)
            check('restored index has its 3 docs back', bool(cnt), os_api('GET', f'{idx}/_count').text[:200])
        finally:
            os_api('DELETE', idx)
            os_api('DELETE', f'_snapshot/{repo}/{rsnap}')
    else:
        skip('backup scripts', 'no OpenSearch')
    # ------------------------------------------------------------------------------------------------------------
    section('Old default passwords (last: wrong passwords count toward brute-force lockout of real users)')
    if need('auth'):
        # one failure per user, more than 1 s apart (Keycloak's quick-login check locks a user for a minute after two
        # failures within a second), each followed by a successful sign-in that resets the counter
        for realm, base, client, u, pw, ok in [
                ('mule', GW, 'mule-api-gateway', 'admin', 'admin123', admin_token),
                ('mule', GW, 'mule-api-gateway', 'developer', 'dev123', dev_token),
                ('master', LO, 'admin-cli', ENV.get('KEYCLOAK_ADMIN_USER', 'admin'), 'admin', master_token)]:
            d = {'grant_type': 'password', 'client_id': client, 'username': u, 'password': pw}
            if client == 'mule-api-gateway':
                d['client_secret'] = ENV['MULE_GATEWAY_CLIENT_SECRET']
            r = token_req(d, base, realm)
            check(f'old default password refused: realm {realm} {u}/{pw}', r.status in (400, 401) and 'invalid_grant' in r.text, r.status)
            time.sleep(1.5)
            check(f'{u} ({realm}) still signs in afterwards (counter reset)', bool(ok()))
    crt = os.path.join(ROOT, 'certs', 'apisix', 'apisix.crt')
    before = os.path.getmtime(crt) if os.path.exists(crt) else None
    c, o = run('./config/scripts/setup/generate-certs.sh --help', 60)
    check('generate-certs.sh --help prints usage and changes nothing', c != 0 and 'Usage' in o and
          (os.path.getmtime(crt) if os.path.exists(crt) else None) == before, o[-200:])
    c, o = run('./config/scripts/setup/generate-certs.sh', 60)
    check('generate-certs.sh without arguments does nothing', c != 0 and 'Usage' in o and
          (os.path.getmtime(crt) if os.path.exists(crt) else None) == before, o[-200:])
finally:
    for what, fn in reversed(cleanups):
        try:
            fn()
        except Exception as e:
            print(f'cleanup failed: {what}: {e}')
    # leftovers of earlier interrupted runs
    try:
        if MT:
            for u in kcadm('GET', 'mule/users?search=t-stack-&max=100').json():
                if u.get('username', '').startswith('t-stack-'):
                    kcadm('DELETE', f'mule/users/{u["id"]}')
        if need('logging') or need('tracing'):
            for i in os_api('GET', '_cat/indices/t-stack-*?format=json&h=index').json():
                os_api('DELETE', i['index'])
            roles = os_api('GET', '_plugins/_security/api/roles').json()
            for r in roles:
                if r.startswith('tenant_t-stack-'):
                    run(f'./config/scripts/tenants/manage-tenants.sh delete {r[len("tenant_"):]} --force', 120)
            repo = ENV.get('BACKUP_REPOSITORY_NAME', 'backup-repo')
            r = os_api('GET', f'_snapshot/{repo}/t-stack-*')
            for s in (r.json().get('snapshots', []) if r.status == 200 else []):
                os_api('DELETE', f'_snapshot/{repo}/{s["snapshot"]}')
    except Exception as e:
        print('cleanup of leftovers failed:', e)

print(f'\nruntime {time.time() - T0:.0f} s')
done()
