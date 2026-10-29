# Runtime Manager UI, end to end in a real browser (Playwright + installed Chrome) against the live stack:
# every button, checkbox, radio, select, link and dialog of index.html and login.html. Real flows on throwaway
# resources (pool t-ui-pool, apps t-ui-mvn / t-ui-jar, node t-ui-node, token t-ui-token); states that can't be
# produced safely (a pool in error, an update check that failed, tracing off, ...) are rendered from mocked responses.
# Run: tests/.venv/Scripts/python tests/test_rm_ui.py   (~15-20 min: it creates a pool and deploys apps)
import glob, json, os, re, secrets, sys, time, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *
import lib
from playwright.sync_api import sync_playwright

POOL, MVN, JAR, NODE, TOKEN_NAME = 't-ui-pool', 't-ui-mvn', 't-ui-jar', 't-ui-node', 't-ui-token'
AGENT = 't-ui-node-agent'
OUT = os.path.join(ROOT, 'tests', 'out')
os.makedirs(OUT, exist_ok=True)
GROUP, ARTIFACT = ENV.get('MULEAPP_GROUP_ID', 'com.acqua'), ENV.get('MULEAPP_ARTIFACT_ID', 'ce-mule-base')
OLD, NEW = '1.0.19', '1.0.20'   # two published releases: deploy OLD pinned, the update check offers NEW
page_errors = []


def jar_file():
    """The app jar with its HTTP listener on ${http.port} (default 8093): the stock jar hard-codes 8081, so it
    couldn't share a worker with the Maven-deployed copy, and a property couldn't move it."""
    hits = sorted(glob.glob('git/CE-MULE-4-Platform-Backend-Mule/target/*-mule-application.jar'))
    src = hits[-1] if hits else os.path.join(OUT, 'app.jar')
    if not hits:
        sh(['docker', 'cp', 'ce-base-runtime-manager:/data/artifacts/ce-mule-base.jar', src])
    out = os.path.join(OUT, f'{JAR}.jar')
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zo:
        for item in zi.infolist():
            data = zi.read(item.filename)
            if item.filename == 'global-config.xml':
                data = data.replace(b'port="8081"', b'port="${http.port}"')
            elif item.filename == 'config/local-docker.properties':
                data = re.sub(rb'(?m)^http\.port=.*$', b'http.port=8093', data)
            zo.writestr(item, data)
    return out


def anchor_times(app):
    """mtime of the app's anchor file on each worker (Mule rewrites it on every (re)deploy)."""
    out = {}
    for w in rm_app(app)['workers']:
        code, t = sh(['docker', 'exec', w, 'sh', '-c', f'stat -c %Y /opt/mule/mule-standalone/apps/{app}-anchor.txt'])
        out[w] = t.strip() if code == 0 else None
    return out


def cleanup():
    cleanup_rm('t-ui-')
    r = rm('GET', 'api/tokens')
    for t in (r.json().get('tokens', []) if r.status == 200 else []):
        if t['name'].startswith('t-ui-'):
            rm('DELETE', f'api/tokens/{t["id"]}')
    if rm('GET', 'api/nodes').text.find(f'"{NODE}"') >= 0:
        rm('DELETE', f'api/nodes/{NODE}')
    sh(['docker', 'rm', '-f', AGENT])


def gw_status(path, token):
    return get(path, token=token).status


# ---------- page helpers ----------
def clear_toasts(pg):
    pg.evaluate("document.querySelector('#toasts').innerHTML = ''")


def toast(pg, title, timeout=90000):
    """Waits for a toast whose title starts with `title`; returns its full text or ''."""
    loc = pg.locator('#toasts .toast', has=pg.locator('b', has_text=title)).first
    try:
        loc.wait_for(timeout=timeout)
        return loc.inner_text()
    except Exception:
        return ''


def act(pg, selector, want_toast, confirm=None, timeout=90000):
    """Click, optionally answer the confirm() dialog, and wait for a toast."""
    clear_toasts(pg)
    if confirm is not None:
        pg.once('dialog', lambda d: d.accept() if confirm else d.dismiss())
    pg.click(selector)
    return toast(pg, want_toast, timeout) if want_toast else ''


def mock_json(pg, pattern, edit):
    """Route matching requests through the real server, then rewrite the JSON body with edit(data)."""
    def handler(route):
        resp = route.fetch()
        try:
            data = resp.json()
        except Exception:
            return route.fulfill(response=resp)
        route.fulfill(response=resp, json=edit(data) or data)
    pg.route(pattern, handler)
    return handler


def sign_in(pg, user, pw):
    pg.goto(RM + '/')
    pg.click('text=Sign in with Keycloak')
    pg.wait_for_selector('#username', timeout=30000)
    pg.fill('#username', user)
    pg.fill('#password', pw)
    pg.click('#kc-login')


def open_app(pg, name, tab='overview'):
    pg.click(f'[data-app="{name}"]')
    pg.click(f'[data-tab="{tab}"]')
    pg.wait_for_selector(f'[data-tab="{tab}"][aria-selected="true"]')


def goto_view(pg, v):
    pg.click(f'nav.views a[data-view="{v}"]')
    pg.wait_for_selector(f'#view-{v}.on')


def pool_card(pg, name):
    return pg.locator('#view-pools .card', has=pg.locator('h3', has_text=name)).first


# ---------- sections ----------
def t_sign_in(br):
    section('Sign-in page')
    if not AUTH_ON:
        return skip('Keycloak sign-in', 'GATEWAY_AUTH=off')
    ctx = br.new_context(ignore_https_errors=True)
    pg = ctx.new_page()
    pg.goto(RM + '/')
    check('signed out: sign-in page, not the app', pg.locator('a.btn', has_text='Sign in with Keycloak').is_visible()
          and pg.title().startswith('Sign in'), pg.title())
    check('API refuses the signed-out browser', ctx.request.get(RM + '/api/apps').status == 401)
    # developer: valid Keycloak account without the operator role
    sign_in(pg, 'developer', ENV['KEYCLOAK_REALM_DEV_PASSWORD'])
    pg.wait_for_selector('#err:not([hidden])', timeout=30000)
    check('developer refused with the reason shown', 'lacks' in pg.inner_text('#err'), pg.inner_text('#err'))
    check('error query string removed from the URL', '?error' not in pg.url, pg.url)
    link = pg.locator('#foot a', has_text='Sign out of Keycloak')
    check('"Sign out of Keycloak" offered', link.is_visible())
    link.click()
    # no RM session to hand Keycloak an id_token_hint, so Keycloak asks to confirm (its standard page)
    pg.wait_for_selector('#kc-logout', timeout=30000)
    pg.click('#kc-logout')
    pg.wait_for_url(RM + '/', timeout=30000)
    check('confirming returns to the sign-in page', pg.locator('a.btn', has_text='Sign in with Keycloak').is_visible())
    pg.click('text=Sign in with Keycloak')
    check('after signing out, Keycloak asks for a password again', pg.wait_for_selector('#username', timeout=30000) is not None)
    # Keycloak error passed back (?error=) is shown
    pg.goto(RM + '/?error=' + 'login%20state%20mismatch')
    check('callback errors shown on the sign-in page', 'state mismatch' in pg.inner_text('#err'))
    ctx.close()


def t_header_and_nav(pg):
    section('Header, navigation, routing, theme, layout')
    me = pg.evaluate('me')
    want = ''.join(w[0] for w in re.split(r'[\s._-]+', me['name'] or me['user']) if w)[:2].upper()
    check('user shown with initials and Keycloak as sign-in method',
          me['name'] in pg.inner_text('#user') and 'Keycloak' in pg.inner_text('#user') and pg.inner_text('#user .avatar') == want,
          (pg.inner_text('#user'), want))
    check('summary counts pools and apps', re.match(r'^\d+ pools? · \d+ apps?$', pg.inner_text('#summary')), pg.inner_text('#summary'))
    for v in ['pools', 'access', 'apps']:
        goto_view(pg, v)
        check(f'nav: {v} view shown and marked current',
              pg.get_attribute(f'nav.views a[data-view="{v}"]', 'aria-current') == 'page'
              and all(not pg.locator(f'#view-{o}').is_visible() for o in {'apps', 'pools', 'access'} - {v}))
    pg.goto(RM + '/#/pools')
    pg.wait_for_selector('#view-pools.on h1')
    check('deep link #/pools opens the pools view', pg.locator('#view-pools h1').inner_text() == 'Runtime pools')
    pg.goto(RM + '/#/nonsense/x')
    pg.wait_for_selector('#view-apps.on')
    check('unknown hash falls back to Applications', pg.locator('#view-apps').is_visible())
    pg.goto(RM + '/#/apps/ce-mule-base/logs')
    pg.wait_for_selector('[data-tab="logs"][aria-selected="true"]')
    check('deep link #/apps/<app>/<tab> opens that app and tab', pg.locator('[data-app="ce-mule-base"][aria-current="true"]').count() == 1)
    pg.click('[data-tab="overview"]')
    check('tab click updates the URL', pg.url.endswith('#/apps/ce-mule-base/overview'), pg.url)
    # theme follows the OS setting
    bg = lambda: pg.evaluate("getComputedStyle(document.body).backgroundColor")
    pg.emulate_media(color_scheme='light'); light = bg()
    pg.emulate_media(color_scheme='dark'); dark = bg()
    pg.emulate_media(color_scheme='light')
    check('dark mode applies dark colors', light != dark and dark.startswith('rgb(18'), (light, dark))
    # phone width: no page-level horizontal scroll (wide tables scroll inside their card)
    pg.set_viewport_size({'width': 390, 'height': 844})
    for v in ['apps', 'pools', 'access']:
        pg.goto(RM + f'/#/{v}'); pg.wait_for_timeout(1500)
        w = pg.evaluate('[document.documentElement.scrollWidth, innerWidth]')
        check(f'phone width, {v}: no horizontal page scroll', w[0] <= w[1] + 1, w)
    pg.set_viewport_size({'width': 1400, 'height': 1000})
    pg.goto(RM + '/#/apps')
    pg.wait_for_selector('[data-app]')


def t_pools_create(pg):
    section('Runtime pools: new pool dialog and create')
    goto_view(pg, 'pools')
    pg.click('#newPool')
    pg.wait_for_selector('#poolForm')
    check('"+ New pool" opens the dialog', pg.inner_text('#dlgTitle') == 'New runtime pool')
    opts = pg.eval_on_selector_all('#poolForm [name=mule_version] option', 'os => os.map(o => o.value)')
    check('Mule versions listed (from MuleSoft)', '4.12.0' in opts and len(opts) > 3, opts[:5])
    old = next((v for v in opts if v.startswith('4.4.')), None)
    if old:
        pg.select_option('#poolForm [name=mule_version]', old)
        js = pg.eval_on_selector_all('#poolForm [name=java_version] option', 'os => os.map(o => o.value)')
        check(f'Java choices follow the Mule version ({old}: 8/11)', set(js) <= {'8', '11'} and js, js)
    pg.select_option('#poolForm [name=mule_version]', '4.12.0')
    js = pg.eval_on_selector_all('#poolForm [name=java_version] option', 'os => os.map(o => o.value)')
    check('Mule 4.12.0: Java 17 only', js == ['17'], js)
    check('local workers default 1, nodes listed', pg.input_value('#poolForm [data-node=local]') == '1')
    # invalid name: the browser blocks the submit
    pg.fill('#poolForm [name=name]', 'Bad Name!')
    pg.click('#poolForm [type=submit]')
    check('invalid pool name blocked by the form', pg.locator('#dlg').is_visible() and not pg.eval_on_selector('#poolForm', 'f => f.checkValidity()'))
    pg.click('#dlg [data-close]')
    check('Close button closes the dialog', not pg.locator('#dlg').is_visible())
    # versions list unavailable: the form still works and says why
    pg.evaluate('versions = null')
    pg.route('**/api/runtime/versions', lambda r: r.fulfill(status=502, json={'error': 'mocked outage'}))
    pg.click('#newPool')
    pg.wait_for_selector('#poolForm')
    check('version list outage shown in the form', 'version list is unavailable' in pg.inner_text('#poolForm'))
    pg.unroute('**/api/runtime/versions')
    pg.click('#dlg [data-close]')
    pg.evaluate('versions = null')
    # create for real
    pg.click('#newPool')
    pg.fill('#poolForm [name=name]', POOL)
    pg.select_option('#poolForm [name=mule_version]', '4.12.0')
    pg.fill('#poolForm [name=heap_mb]', '512')
    pg.fill('#poolForm [data-node=local]', '1')
    pg.fill('#poolForm [name=jvm_options]', '-XX:+UseG1GC\n\n  -Dt.ui=1  ')
    t = act(pg, '#poolForm [type=submit]', 'Pool created')
    check('Create pool: toast, dialog closed', t and not pg.locator('#dlg').is_visible(), t)
    p = rm_pool(POOL)
    check('pool saved as entered (blank lines/spaces trimmed)', p and p['heap_mb'] == 512 and p['jvm_options'] == ['-XX:+UseG1GC', '-Dt.ui=1']
          and p['mule_version'] == '4.12.0' and p['java_version'] == '17', p)
    pg.wait_for_timeout(1500)
    check('pool card appears', wait(lambda: pool_card(pg, POOL).is_visible(), 15, 1))
    check('pool becomes ready with a healthy worker', wait_pool_ready(POOL, 600))
    pg.wait_for_timeout(4000)
    card = pool_card(pg, POOL)
    check('card: ready badge, runtime, JVM options, worker row healthy',
          'ready' in card.inner_text() and 'Mule 4.12.0' in card.inner_text() and '-Dt.ui=1' in card.inner_text()
          and card.locator('.worker-row .badge.good').count() == 1, card.inner_text())


def t_pools_edit(pg):
    section('Runtime pools: edit (rolling), retry, delete guard')
    goto_view(pg, 'pools')
    pool_card(pg, POOL).locator('[data-edit-pool]').click()
    check('Edit opens the dialog prefilled', pg.inner_text('#dlgTitle') == f'Edit pool {POOL}'
          and pg.input_value('#poolForm [name=heap_mb]') == '512' and '-Dt.ui=1' in pg.input_value('#poolForm [name=jvm_options]')
          and pg.locator('#poolForm [name=name]').count() == 0)
    pg.fill('#poolForm [data-node=local]', '2')
    t = act(pg, '#poolForm [type=submit]', 'Rolling out')
    check('Save & roll out: toast', t, t)
    pg.wait_for_timeout(1500)
    busy = pool_card(pg, POOL).inner_text()
    check('card shows the rollout in progress or done', any(s in busy for s in ['working', 'pending', 'ready']), busy[:200])
    check('pool scaled to 2 healthy workers', wait_pool_ready(POOL, 600) and len(rm_pool(POOL)['workers']) == 2)
    # error state + Retry (mocked status; the click hits the real reconcile endpoint)
    def err(d):
        for p in d['pools']:
            if p['name'] == POOL:
                p['status'] = {'state': 'error', 'message': 'mocked: image build failed'}
    mock_json(pg, '**/api/pools', err)
    pg.evaluate('loadPools()')
    card = pool_card(pg, POOL)
    card.locator('[data-retry]').wait_for(timeout=10000)
    check('error state: red badge, message, Retry button', 'mocked: image build failed' in card.inner_text()
          and card.locator('.badge.bad').count() >= 1)
    with pg.expect_request(lambda r: r.url.endswith(f'/api/pools/{POOL}/reconcile') and r.method == 'POST') as req:
        card.locator('[data-retry]').click()
    check('Retry calls reconcile', req.value is not None)
    pg.unroute('**/api/pools')
    pg.evaluate('loadPools()')


def t_nodes(pg):
    section('Nodes: add (real agent), edit, remove')
    goto_view(pg, 'pools')
    check('local server row shown', 'this server' in pg.inner_text('#view-pools table'))
    pg.click('#newNode')
    check('"+ Add node" opens the dialog', pg.inner_text('#dlgTitle') == 'Add a node')
    for k, v in [('name', 't-ui-bad'), ('address', 'https://t-ui-nowhere:7443'), ('token', 'x' * 32),
                 ('fingerprint', 'sha256:' + '0' * 64), ('gateway', '172.42.0.20')]:
        pg.fill(f'#nodeForm [name={k}]', v)
    t = act(pg, '#nodeForm [type=submit]', 'Node not saved', timeout=60000)
    check('unreachable node: error toast, dialog stays open, button re-enabled',
          t and pg.locator('#dlg').is_visible() and pg.is_enabled('#nodeForm [type=submit]'), t)
    check('nothing saved for the unreachable node', '"t-ui-bad"' not in rm('GET', 'api/nodes').text)
    pg.click('#dlg [data-close]')
    # a real agent on this Docker (no workers put on it)
    code, out = sh(['docker', 'build', '-q', '-t', f'{AGENT}:test', 'node/agent'], timeout=600)
    if code:
        return check('node agent image builds', False, out[-300:])
    tok = secrets.token_hex(24)
    sh(['docker', 'run', '-d', '--name', AGENT, '--network', 'ce-base-micronet', '-e', f'NODE_TOKEN={tok}',
        '-v', '/var/run/docker.sock:/var/run/docker.sock', f'{AGENT}:test'])
    fp = wait(lambda: (m := re.search(r'NODE-FINGERPRINT (sha256:[0-9a-f]+)', sh(['docker', 'logs', AGENT])[1])) and m.group(1), 60, 2)
    if not check('node agent started and printed its fingerprint', fp):
        return
    pg.click('#newNode')
    for k, v in [('name', NODE), ('address', f'https://{AGENT}:7443'), ('token', tok), ('fingerprint', fp), ('gateway', '172.42.0.20')]:
        pg.fill(f'#nodeForm [name={k}]', v)
    t = act(pg, '#nodeForm [type=submit]', 'Node added', timeout=60000)
    check('Connect & add: toast with Docker info', t and 'CPUs' in t, t)
    pg.wait_for_timeout(1500)
    row = pg.locator('#view-pools tr', has=pg.locator('b', has_text=NODE)).first
    check('node row: reachable, address, Docker version', 'reachable' in row.inner_text() and AGENT in row.inner_text(), row.inner_text())
    row.locator('[data-edit-node]').click()
    check('Edit node: prefilled, token not revealed', pg.input_value('#nodeForm [name=address]') == f'https://{AGENT}:7443'
          and pg.input_value('#nodeForm [name=token]') == '' and 'stored' in pg.get_attribute('#nodeForm [name=token]', 'placeholder'))
    pg.fill('#nodeForm [name=fingerprint]', 'sha256:' + 'f' * 64)
    t = act(pg, '#nodeForm [type=submit]', 'Node not saved', timeout=60000)
    check('wrong fingerprint refused (pinned cert)', t, t)
    pg.fill('#nodeForm [name=fingerprint]', fp)
    t = act(pg, '#nodeForm [type=submit]', 'Node saved', timeout=60000)
    check('Save with the right fingerprint (token kept)', t, t)
    pg.click('#newPool')
    check('pool form offers workers on the new node', pg.locator(f'#poolForm [data-node="{NODE}"]').count() == 1)
    pg.click('#dlg [data-close]')
    # Remove is disabled while pools use the node (mocked usage)
    mock_json(pg, '**/api/nodes', lambda d: [n.update(pools=['some-pool']) for n in d['nodes'] if n['name'] == NODE] and None)
    pg.evaluate('loadPools()'); pg.wait_for_timeout(1000)
    check('Remove disabled while pools use the node', pg.is_disabled(f'[data-del-node="{NODE}"]'))
    pg.unroute('**/api/nodes')
    pg.evaluate('loadPools()'); pg.wait_for_timeout(1000)
    act(pg, f'[data-del-node="{NODE}"]', None, confirm=False)
    pg.wait_for_timeout(1000)
    check('Remove → Cancel keeps the node', f'"{NODE}"' in rm('GET', 'api/nodes').text)
    t = act(pg, f'[data-del-node="{NODE}"]', 'Node removed', confirm=True)
    check('Remove → OK removes it', t and f'"{NODE}"' not in rm('GET', 'api/nodes').text, t)
    # the agent ran on this same Docker, so its listings included the platform's own workers: they must stay local
    w = sorted(rm_app('ce-mule-base')['workers'])[0]
    r = rm('GET', f'api/apps/ce-mule-base/log?worker={w}&bytes=1024')
    check('local workers still reached directly after a node on the same Docker', r.status == 200, (r.status, r.text[:120]))
    sh(['docker', 'rm', '-f', AGENT])


def t_deploy_maven(pg):
    section('Deploy dialog: validation and a Maven deploy')
    goto_view(pg, 'apps')
    pg.click('#newApp')
    pg.wait_for_selector('#deployForm')
    check('"+ Deploy" opens the dialog', pg.inner_text('#dlgTitle') == 'Deploy a new application')
    check('new-app form: name field, Updates default Notify, no Discard button',
          pg.locator('#deployForm [name=name]').count() == 1 and pg.is_checked('#deployForm [name=updates][value=notify]')
          and pg.locator('#deployForm [type=reset]').count() == 0)
    pg.fill('#deployForm [name=name]', 'Bad_Name')
    pg.click('#deployForm [type=submit]')
    check('invalid app name blocked by the form', not pg.eval_on_selector('#deployForm', 'f => f.checkValidity()'))
    pg.fill('#deployForm [name=name]', MVN)
    pg.select_option('#deployForm [name=pool]', POOL)
    check('pool choice re-renders the workers list', f'Workers in pool {POOL}' in pg.inner_text('#workersSet')
          and 'All 2' in pg.inner_text('#workersSet'))
    t = act(pg, '#deployForm [type=submit]', 'Choose a source')
    check('no source: "Choose a source"', t, t)
    pg.check('#deployForm [name=wmode][value=list]')
    check('"Specific workers" shows the worker checkboxes', pg.is_visible('#wlist') and pg.locator('#wlist [name=w]').count() == 2)
    for c in pg.locator('#wlist [name=w]').all():
        c.uncheck()
    pg.fill('#deployForm [name=group]', GROUP); pg.fill('#deployForm [name=artifact]', ARTIFACT); pg.fill('#deployForm [name=version]', OLD)
    t = act(pg, '#deployForm [type=submit]', 'Pick at least one worker')
    check('no worker ticked: "Pick at least one worker"', t, t)
    pg.check('#deployForm [name=wmode][value=all]')
    check('other modes hide the checkboxes', not pg.is_visible('#wlist'))
    pg.check('#deployForm [name=wmode][value=count]')
    pg.fill('#deployForm [name=wcount]', '1')
    if pg.locator('#deployForm [name=path]').count():
        pg.fill('#deployForm [name=path]', f'/{MVN}'); pg.fill('#deployForm [name=port]', '8081')
    t = act(pg, '#deployForm [type=submit]', 'Deploying', timeout=180000)
    try:
        pg.wait_for_url(f'**#/apps/{MVN}/overview', timeout=60000)  # after the app list refresh
    except Exception:
        pass
    check('Deploy: toast, dialog closed, overview opened', t and not pg.locator('#dlg').is_visible()
          and pg.url.endswith(f'#/apps/{MVN}/overview'), (t, pg.url))
    a = rm_app(MVN)
    check('saved: Maven coords, notify, count 1, route', a and a['maven']['version'] == OLD and a['updates'] == 'notify'
          and a['placement'] == 1 and (a['route'] or {}).get('path') == f'/{MVN}', a)
    check('app starts on one worker', wait_app_started(MVN, 600))


def t_app_header(pg):
    section('App header: updates switch, check, update, restart, list')
    pg.evaluate('refresh()'); pg.wait_for_timeout(1000)
    open_app(pg, MVN)
    head = pg.inner_text('#head')
    check('header: coords, build, pool badge, "1 worker of 2", route badge',
          f'{GROUP}:{ARTIFACT}' in head and OLD in head and f'pool {POOL}' in head and '1 worker of 2' in head and f'/{MVN}/*' in head, head)
    check('worker chip started', pg.locator('#head .badge.good').count() >= 1)
    for mode, label in [('off', 'Off'), ('auto', 'Auto'), ('notify', 'Notify')]:
        t = act(pg, f'[data-updates="{mode}"]', f'Updates: {label}')
        pg.wait_for_timeout(500)
        check(f'Updates switch → {label}: toast, pressed, saved', t and pg.get_attribute(f'[data-updates="{mode}"]', 'aria-pressed') == 'true'
              and rm_app(MVN)['updates'] == mode, t)
    t = act(pg, '[data-act="check"]', 'Update available', timeout=120000)
    check(f'Check for updates (notify): "{NEW} is published"', NEW in t, t)
    pg.wait_for_timeout(1500)
    check('"Update to" button and list hint appear', pg.locator('[data-act="update"]', has_text=NEW).count() == 1
          and 'update available' in pg.inner_text(f'[data-app="{MVN}"]'))
    t = act(pg, '[data-act="update"]', 'Deploying', timeout=180000)
    check('Update → deploys the new build', t and wait(lambda: rm_app(MVN)['maven']['build'] == NEW, 300, 5), t)
    check('updated app started', wait_app_started(MVN, 600))
    t = act(pg, '[data-act="check"]', 'Up to date', timeout=120000)
    check('Check again: up to date', t, t)
    # failed update check is shown (mocked)
    mock_json(pg, '**/api/apps', lambda d: [a['maven'].update(error='mocked: repository unreachable') for a in d['apps'] if a['name'] == MVN] and None)
    pg.evaluate('refresh()')
    check('failed check shown in the header', pg.locator('#head .badge.bad', has_text='last update check failed').count() == 1
          and 'mocked: repository unreachable' in pg.inner_text('#head'))
    pg.unroute('**/api/apps')
    before = anchor_times(MVN)
    time.sleep(1.1)  # anchor mtimes have 1 s resolution
    t = act(pg, '[data-act="restart"]', 'Restarting')
    check('Restart: toast names the workers', t and 'worker' in t, t)
    check('restart redeploys on its worker and the app starts again',
          wait(lambda: all(v and v != before.get(w) for w, v in anchor_times(MVN).items()), 300, 5) and wait_app_started(MVN, 600),
          (before, anchor_times(MVN)))
    pg.click('#head a.badge[href="#/pools"]')
    check('pool badge links to Runtime pools', pg.locator('#view-pools').is_visible())
    goto_view(pg, 'apps')
    pg.click('[data-app="ce-mule-base"]')
    check('app list click selects the app', pg.get_attribute('[data-app="ce-mule-base"]', 'aria-current') == 'true'
          and pg.inner_text('#head h1') == 'ce-mule-base')
    pg.click(f'[data-app="{MVN}"]')


def t_properties(pg):
    section('Properties tab')
    open_app(pg, MVN, 'properties')
    pg.wait_for_selector('#saveProps')
    check('no properties yet', 'No properties yet' in pg.inner_text('#tabBody'))
    pg.click('[data-add="plain"]')
    check('+ Property adds a row and focuses its name', pg.locator('table.props tbody tr').count() == 1
          and pg.evaluate("document.activeElement.dataset.f") == 'key')
    t = act(pg, '#saveProps', 'Every property needs a name')
    check('empty name refused', t, t)
    pg.fill('[data-i="0"][data-f="key"]', 'mule_env'); pg.fill('[data-i="0"][data-f="value"]', 't-ui')
    pg.click('[data-add="plain"]')
    pg.fill('[data-i="1"][data-f="key"]', 'mule_env'); pg.fill('[data-i="1"][data-f="value"]', 'x')
    t = act(pg, '#saveProps', 'Duplicate property')
    check('duplicate name refused', 'mule_env' in t, t)
    pg.click('[data-del="1"]')
    check('✕ removes the row', pg.locator('table.props tbody tr').count() == 1)
    pg.click('[data-add="plain"]')
    pg.fill('[data-i="1"][data-f="key"]', 't.mask'); pg.fill('[data-i="1"][data-f="value"]', 'plain-then-secure')
    pg.check('[data-i="1"][data-f="secure"]')
    check('secure checkbox masks the value', pg.get_attribute('[data-i="1"][data-f="value"]', 'type') == 'password')
    pg.uncheck('[data-i="1"][data-f="secure"]')
    check('unticking shows it again, value kept', pg.get_attribute('[data-i="1"][data-f="value"]', 'type') == 'text'
          and pg.input_value('[data-i="1"][data-f="value"]') == 'plain-then-secure')
    pg.click('[data-del="1"]')
    secret = 's3cr3t-' + secrets.token_hex(6)
    pg.click('[data-add="secure"]')
    check('+ Secure property adds a masked row', pg.get_attribute('[data-i="1"][data-f="value"]', 'type') == 'password'
          and pg.is_checked('[data-i="1"][data-f="secure"]'))
    pg.fill('[data-i="1"][data-f="key"]', 't.secret'); pg.fill('[data-i="1"][data-f="value"]', secret)
    pg.click('[data-add="plain"]')
    pg.fill('[data-i="2"][data-f="key"]', 't.plain'); pg.fill('[data-i="2"][data-f="value"]', 'hello')
    t = act(pg, '#saveProps', 'Properties saved', timeout=120000)
    check('Save & restart: toast counts 3 properties', '3 properties' in t, t)
    pg.wait_for_selector('[data-f="secure"][disabled]')
    r = rm('GET', f'api/apps/{MVN}/properties').json()
    check('API: plain values, secure names only', r['properties'] == {'mule_env': 't-ui', 't.plain': 'hello'} and r['secure'] == ['t.secret']
          and secret not in json.dumps(r), r)
    row = pg.locator('table.props tbody tr', has=pg.locator('[data-f="secure"][disabled]')).first
    val = row.locator('[data-f="value"]')
    check('stored secure: empty, "stored" placeholder, checkbox locked', val.input_value() == ''
          and 'stored' in (val.get_attribute('placeholder') or '') and row.locator('[data-f="secure"]').is_disabled())
    check('header shows 3 properties · 1 secure', '3 properties · 1 secure' in pg.inner_text('#head'))
    check('app restarted with the properties', wait_app_started(MVN, 600))
    t = act(pg, '#saveProps', 'Properties saved', timeout=120000)
    check('saving again leaves the stored secret as is', t and rm('GET', f'api/apps/{MVN}/properties').json()['secure'] == ['t.secret'])
    check('app restarted again', wait_app_started(MVN, 600))
    w = list(rm_app(MVN)['workers'])[0]
    code, out = sh(['docker', 'exec', w, 'sh', '-c', f'cat /opt/mule/mule-standalone/.mule/{MVN}/deployment-properties/deployment.properties'])
    check('worker got plain + decrypted secure values', 'mule_env=t-ui' in out and 't.plain=hello' in out and secret in out,
          'missing keys' if code == 0 else out[-200:])
    code, out = sh(['docker', 'exec', 'ce-base-runtime-manager', 'grep', '-rl', secret, '/data'])
    check('secure value not stored in plain text in the RM', secret not in out and code == 1, 'found in RM data')
    tok = admin_token()
    check('gateway route reaches the app', wait(lambda: gw_status(f'/{MVN}/api/v1/status', tok) == 200, 120, 5))
    check('route needs a token', gw_status(f'/{MVN}/api/v1/status', None) == 401)
    # secure disabled (no RM_SECRETS_KEY): mocked flag
    pg.evaluate('me.secure = false; renderProps()')
    check('without RM_SECRETS_KEY: "+ Secure property" disabled and explained',
          pg.is_disabled('[data-add="secure"]') and 'RM_SECRETS_KEY' in pg.inner_text('#tabBody'))
    pg.evaluate('me.secure = true; renderProps()')


def t_overview(pg):
    section('Overview tab')
    tok = admin_token()
    for i in range(12):
        get(f'/{MVN}/api/v1/status', token=tok)
    get(f'/{MVN}/api/v1/does-not-exist', token=tok)
    has = wait(lambda: (o := rm('GET', f'api/apps/{MVN}/overview?minutes=15').json())['traces'].get('total', {}).get('count', 0) >= 12 and o,
               120, 5)
    check('traces of the requests reach the overview', has)
    open_app(pg, MVN, 'overview')
    for v in [15, 360, 1440, 60]:
        with pg.expect_request(lambda r, v=v: f'/overview?minutes={v}' in r.url):
            pg.click(f'[data-range="{v}"]')
        pg.wait_for_selector(f'[data-range="{v}"][aria-pressed="true"]')
        check(f'range {v} min: requested and pressed', True)
    pg.wait_for_selector('.tile', timeout=30000)
    tiles = pg.inner_text('.tiles')
    check('tiles: requests, error rate, p95, log problems', all(s in tiles for s in ['Requests', 'Error rate', 'p95 latency', 'Log problems']), tiles)
    n = int(re.sub(r'\D', '', pg.locator('.tile .value').first.inner_text()) or 0)
    check('request count shown', n >= 12, n)
    check('both charts drawn', pg.locator('#chReq svg rect').count() >= 1 and pg.locator('#chLat svg circle').count() >= 1)
    pg.hover('#chReq svg', position={'x': 400, 'y': 100})
    check('chart hover shows a tooltip and crosshair', pg.locator('#chReq .tip').is_visible() and 'requests' in pg.inner_text('#chReq .tip'))
    pg.mouse.move(0, 0)
    check('tooltip hides on leave', not pg.locator('#chReq .tip').is_visible())
    workers = pg.inner_text('.card:has(h3:text("Workers")) tbody')
    check('workers table lists the app worker with counts', list(rm_app(MVN)['workers'])[0] in workers, workers)
    check('endpoints table lists /api/v1/status', '/v1/status' in pg.inner_text('.card:has(h3:has-text("Endpoints"))'))
    link = pg.locator('a[title="Open trace in Jaeger"]').first
    if has and has['traces'].get('notable'):
        check('failed request links to its Jaeger trace', link.count() == 1 and '/jaeger/trace/' in link.get_attribute('href')
              and link.get_attribute('target') == '_blank')
    else:
        skip('Jaeger trace link', 'no failed/slow request in the window')
    # mocked states
    def ov(fn):
        pg.route('**/overview?*', fn)
        pg.click('[data-range="15"]'); pg.wait_for_timeout(800)
        txt = pg.inner_text('#tabBody')
        pg.unroute('**/overview?*')
        return txt
    txt = ov(lambda r: r.fulfill(json={'app': rm_app(MVN), 'traces': {'state': 'disabled'}, 'logs': {'state': 'disabled'}}))
    check('tracing/logging off: panels say so', 'Tracing (Jaeger) is not configured' in txt and 'Log search (OpenSearch) is not configured' in txt, txt[:300])
    txt = ov(lambda r: r.fulfill(json={'app': rm_app(MVN), 'traces': {'state': 'error'}, 'logs': {'state': 'error'}}))
    check('tracing/logging down: panels say unreachable', 'Tracing (Jaeger) is unreachable' in txt and 'Log search (OpenSearch) is unreachable' in txt, txt[:300])
    txt = ov(lambda r: r.fulfill(status=500, json={'error': 'mocked boom'}))
    check('overview error shown', 'Overview unavailable: mocked boom' in txt, txt[:200])
    pg.click('[data-range="60"]')


LOG_SAMPLE = '''INFO  2026-10-26 18:41:27,036 [[MuleRuntime].uber.29: [ce-mule-base].main.CPU_LITE @59cef68] [processor: extract-tenant-id/processors/4; event: aaa-111] com.acqua.tenant: Tenant demo resolved
WARN  2026-10-26 18:41:28,000 [[MuleRuntime].uber.21: [ce-mule-base].main.CPU_LITE @59cef68] [processor: p/1; event: bbb-222] com.acqua.tenant: No JWT, falling back to header
ERROR 2026-10-26 18:41:29,000 [[MuleRuntime].uber.21: [ce-mule-base].main.CPU_LITE @59cef68] [processor: ce-backend-main/processors/1; event: ccc-333] org.mule.runtime.core.internal.exception.OnErrorPropagateHandler:
********************************************************************************
Message               : /v1/no-such-thing
Error type            : APIKIT:NOT_FOUND
********************************************************************************
INFO  2026-10-26 18:41:30,000 [WrapperListener_start_runner] org.mule.runtime.core: Connection timeout to db-host
'''


def t_log_search_functions(pg):
    section('Logs: search language (page functions)')
    r = pg.evaluate('''(t) => {
      const es = logEntries(t);
      const run = (q, mode = 'mule', mc = false) => { const m = logMatcher(q, mode, mc); return es.filter(e => m.test(e)).map(e => e.event || e.text.slice(0, 4)); };
      return {
        n: es.length, levels: es.map(e => e.level), errLines: es[2].text.split('\\n').length,
        logger: es[0].logger, thread: es[0].thread, proc: es[2].processor,
        words: run('tenant demo'), phrase: run('"falling back"'), phraseMiss: run('"back falling"'),
        or: run('timeout OR APIKIT'), not: run('tenant -demo'), not2: run('com.acqua NOT jwt'), and: run('tenant AND demo'),
        wild: run('APIKIT:NOT_*'), level: run('level:error'), prio: run('priority:WARN'),
        loggerQ: run('logger:com.acqua*'), loggerExact: run('logger:com.acqua.tenant'), event: run('event:bbb-*'),
        procq: run('processor:ce-backend-main*'), threadq: run('thread:WrapperListener*'), fieldPhrase: run('logger:"com.acqua.tenant"'),
        caseOn: run('TENANT', 'mule', true), caseOff: run('TENANT'), empty: run('   '),
        regex: run('no-such-\\\\w+|timeout', 'regex'), regexCase: run('Timeout', 'regex', true),
        hl: logMatcher('tenant demo', 'mule', false).hl.source, hlNeg: logMatcher('-tenant', 'mule', false).hl,
        mark: markLog('a <b> tenant', logMatcher('tenant', 'mule', false).hl),
        bad: (() => { try { logMatcher('(x', 'regex', false); return 'no throw'; } catch (e) { return 'throws'; } })(),
        blank: logEntries('').length, cont: logEntries('banner line\\nINFO  x').length,
      };
    }''', LOG_SAMPLE)
    check('4 entries; multi-line ERROR kept together', r['n'] == 4 and r['errLines'] == 5, r)
    check('levels parsed', r['levels'] == ['INFO', 'WARN', 'ERROR', 'INFO'], r['levels'])
    check('fields: logger, nested-bracket thread, processor', r['logger'] == 'com.acqua.tenant'
          and r['thread'].startswith('[MuleRuntime].uber.29') and r['proc'] == 'ce-backend-main/processors/1', r)
    check('words ANDed (and explicit AND)', r['words'] == ['aaa-111'] and r['and'] == ['aaa-111'], (r['words'], r['and']))
    check('"phrase" is exact', r['phrase'] == ['bbb-222'] and r['phraseMiss'] == [], (r['phrase'], r['phraseMiss']))
    check('OR', r['or'] == ['ccc-333', 'INFO'], r['or'])
    check('-word and NOT word', r['not'] == ['bbb-222'] and r['not2'] == ['aaa-111'], (r['not'], r['not2']))
    check('* wildcard', r['wild'] == ['ccc-333'], r['wild'])
    check('level:/priority: exact', r['level'] == ['ccc-333'] and r['prio'] == ['bbb-222'], (r['level'], r['prio']))
    check('logger: wildcard, exact, quoted', r['loggerQ'] == r['loggerExact'] == r['fieldPhrase'] == ['aaa-111', 'bbb-222'], r['loggerQ'])
    check('event:/processor:/thread:', r['event'] == ['bbb-222'] and r['procq'] == ['ccc-333'] and r['threadq'] == ['INFO'], r)
    check('match case', r['caseOn'] == [] and len(r['caseOff']) == 2, (r['caseOn'], r['caseOff']))
    check('blank query matches everything', len(r['empty']) == 4)
    check('regex mode (+ case)', r['regex'] == ['ccc-333', 'INFO'] and r['regexCase'] == [], (r['regex'], r['regexCase']))
    check('highlight: positive words only', r['hl'] == 'tenant|demo' and r['hlNeg'] is None, (r['hl'], r['hlNeg']))
    check('highlighting escapes HTML', r['mark'] == 'a &lt;b&gt; <mark>tenant</mark>', r['mark'])
    check('invalid regex throws (UI reports it)', r['bad'] == 'throws')
    check('empty log: no entries; text before the first level line kept', r['blank'] == 0 and r['cont'] == 2, (r['blank'], r['cont']))


def t_logs_tab(pg, app):
    section(f'Logs tab ({app})')
    tok = admin_token()
    for _ in range(3):
        get(f'/{app}/api/v1/status', token=tok)
    open_app(pg, app, 'logs')
    pg.wait_for_function("/entries/.test(document.querySelector('#logN')?.textContent || '')", timeout=30000)
    total = pg.inner_text('#logN')
    check('log loads with an entry count', re.match(r'^\d+ entries$', total), total)
    ws = pg.eval_on_selector_all('#logW option', 'os => os.map(o => o.value)')
    check('worker select lists the app workers', sorted(ws) == sorted(rm_app(app)['workers']), ws)
    if len(ws) > 1:
        with pg.expect_request(lambda r: f'worker={ws[1]}' in r.url):
            pg.select_option('#logW', ws[1])
        check('switching worker loads its log', True)
    with pg.expect_request(lambda r: 'source=runtime' in r.url):
        pg.select_option('#logS', 'runtime')
    pg.wait_for_timeout(1000)
    pg.fill('#logQ', app); pg.wait_for_timeout(600)
    check('Mule runtime log: shows the deployment of the app', ' of ' in pg.inner_text('#logN') and pg.locator('#log .le').count() > 0,
          pg.inner_text('#logN'))
    with pg.expect_request(lambda r: 'source=app' in r.url):
        pg.select_option('#logS', 'app')
    pg.wait_for_timeout(1000)
    pg.fill('#logQ', '"tenant" -nothing-matches-this'); pg.wait_for_timeout(600)
    rows = pg.locator('#log .le').count()
    check('Mule search on the live log: hits, count, highlights', rows > 0 and ' of ' in pg.inner_text('#logN')
          and pg.locator('#log mark').count() >= rows, (rows, pg.inner_text('#logN')))
    pg.fill('#logQ', 'zzz-no-such-text-zzz'); pg.wait_for_timeout(600)
    check('no match: "No entries match."', 'No entries match' in pg.inner_text('#log'))
    pg.check('#logC'); pg.fill('#logQ', 'TENANT'); pg.wait_for_timeout(600)
    upper = pg.locator('#log .le').count()
    pg.uncheck('#logC'); pg.wait_for_timeout(600)
    check('Match case checkbox narrows the hits', pg.locator('#log .le').count() > upper, (upper, pg.locator('#log .le').count()))
    pg.click('[data-logmode="regex"]')
    check('Regex mode: pressed, help and placeholder change, query kept, focus in box',
          pg.get_attribute('[data-logmode="regex"]', 'aria-pressed') == 'true' and 'JavaScript regular expression' in pg.inner_text('.loghelp')
          and 'Regular expression' in pg.get_attribute('#logQ', 'placeholder') and pg.input_value('#logQ') == 'TENANT'
          and pg.evaluate('document.activeElement.id') == 'logQ')
    pg.fill('#logQ', '[Tt]enant\\W+\\w+'); pg.wait_for_timeout(600)
    check('regex search on the live log', pg.locator('#log .le').count() > 0, pg.inner_text('#logN'))
    pg.fill('#logQ', '(unclosed'); pg.wait_for_timeout(600)
    check('invalid regex reported, nothing crashes', 'Invalid regex' in pg.inner_text('#logN') and pg.locator('#logN.bad').count() == 1)
    pg.fill('#logQ', '')
    for lv, allowed in [('ERROR', {'ERROR', 'FATAL'}), ('WARN', {'WARN', 'ERROR', 'FATAL'}), ('INFO', {'INFO', 'WARN', 'ERROR', 'FATAL'}),
                        ('DEBUG', {'DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL'})]:
        pg.select_option('#logL', lv); pg.wait_for_timeout(400)
        got = {c.replace('le lv-', '') for c in pg.eval_on_selector_all('#log .le', 'es => es.map(e => e.className)')}
        check(f'priority "{lv} and above"', got <= allowed, got)
    pg.select_option('#logL', 'WARN')
    with pg.expect_request(lambda r: '/log?' in r.url):
        pg.click('[data-act="refresh-log"]')
    pg.wait_for_timeout(1000)
    check('Refresh reloads and keeps the filters', pg.input_value('#logL') == 'WARN'
          and pg.get_attribute('[data-logmode="regex"]', 'aria-pressed') == 'true')
    pg.click('[data-logmode="mule"]'); pg.select_option('#logL', '')
    check('back to Mule search', pg.get_attribute('[data-logmode="mule"]', 'aria-pressed') == 'true')


def t_settings(pg):
    section('Settings tab: workers, pool, updates, route, discard')
    open_app(pg, MVN, 'settings')
    pg.wait_for_selector('#editForm')
    check('form prefilled: pool, coords, updates, route, count 1',
          pg.input_value('#editForm [name=pool]') == POOL and pg.input_value('#editForm [name=version]') == NEW
          and pg.is_checked('#editForm [name=updates][value=notify]') and pg.is_checked('#editForm [name=wmode][value=count]')
          and pg.input_value('#editForm [name=wcount]') == '1'
          and (pg.locator('#editForm [name=path]').count() == 0 or pg.input_value('#editForm [name=path]') == f'/{MVN}'))
    pg.select_option('#editForm [name=pool]', 'default')
    check('changing the pool re-renders its workers', 'Workers in pool default' in pg.inner_text('#workersSet'))
    pg.click('#editForm [type=reset]'); pg.wait_for_timeout(300)
    check('Discard changes restores the form', pg.input_value('#editForm [name=pool]') == POOL and f'Workers in pool {POOL}' in pg.inner_text('#workersSet'))
    pg.check('#editForm [name=wmode][value=list]')
    for c in pg.locator('#wlist [name=w]').all():
        c.uncheck()
    t = act(pg, '#editForm [type=submit]', 'Pick at least one worker')
    check('Specific workers with none ticked refused', t, t)
    target = sorted(rm_app(MVN)['workers'])[0] if rm_app(MVN)['workers'] else f'mule-{POOL}-1'
    other = next(w for w in [f'mule-{POOL}-1', f'mule-{POOL}-2'] if w != target)
    pg.check(f'#wlist [name=w][value="{other}"]')
    t = act(pg, '#editForm [type=submit]', 'Saved')
    check('pin to a specific worker', t and wait(lambda: rm_app(MVN)['placement'] == [other], 30, 2), rm_app(MVN)['placement'])
    check('app moves to that worker', wait(lambda: list(rm_app(MVN)['workers']) == [other] and rm_app(MVN)['workers'][other] == 'STARTED', 600, 5))
    open_app(pg, MVN, 'settings')
    check('pinned shows as "pinned to 1"', 'pinned to 1' in pg.inner_text('#head'))
    pg.check('#editForm [name=wmode][value=all]')
    pg.check('#editForm [name=updates][value=off]')
    t = act(pg, '#editForm [type=submit]', 'Saved')
    check('All workers + updates Off saved', t and wait(lambda: (a := rm_app(MVN))['placement'] is None and a['updates'] == 'off', 30, 2))
    check('app runs on both workers', wait(lambda: len(rm_app(MVN)['workers']) == 2 and wait_app_started(MVN, 5), 600, 5))
    if pg.locator('#editForm [name=path]').count():
        open_app(pg, MVN, 'settings')
        pg.fill('#editForm [name=path]', f'/{MVN}-moved')
        t = act(pg, '#editForm [type=submit]', 'Saved')
        tok = admin_token()
        check('route moved: new path answers, old one 404',
              t and wait(lambda: gw_status(f'/{MVN}-moved/api/v1/status', tok) == 200, 60, 3) and gw_status(f'/{MVN}/api/v1/status', tok) == 404)
        open_app(pg, MVN, 'settings')
        pg.fill('#editForm [name=path]', '')
        t = act(pg, '#editForm [type=submit]', 'Saved')
        check('route removed when the path is cleared', t and wait(lambda: rm_app(MVN)['route'] is None, 30, 2)
              and wait(lambda: gw_status(f'/{MVN}-moved/api/v1/status', tok) == 404, 60, 3))
        open_app(pg, MVN, 'settings')
        pg.fill('#editForm [name=path]', f'/{MVN}'); pg.fill('#editForm [name=port]', '8081')
        act(pg, '#editForm [type=submit]', 'Saved')
    else:
        skip('gateway path fields', 'routing is off')
    open_app(pg, MVN, 'settings')
    pg.click('#editForm a[href="#/pools"]')
    check('"Manage pools" link', pg.locator('#view-pools').is_visible())
    goto_view(pg, 'apps')
    open_app(pg, MVN, 'settings')
    pg.click('#editForm a[href="#/access"]')
    check('"API & settings" link from Updates', pg.locator('#view-access').is_visible())
    goto_view(pg, 'apps')


def t_deploy_jar(pg):
    section('Deploy a jar upload; settings re-upload; mocked empty states')
    jar = jar_file()
    if not check('a Mule app jar to upload', os.path.exists(jar), jar):
        return
    goto_view(pg, 'apps')
    pg.click('#newApp')
    pg.fill('#deployForm [name=name]', JAR)
    pg.select_option('#deployForm [name=pool]', POOL)
    pg.check('#deployForm [name=wmode][value=all]')
    pg.set_input_files('#deployForm [name=jar]', jar)
    if pg.locator('#deployForm [name=path]').count():
        pg.fill('#deployForm [name=path]', f'/{JAR}'); pg.fill('#deployForm [name=port]', '8092')
    t = act(pg, '#deployForm [type=submit]', 'Deploying', timeout=300000)
    check('jar upload deploy: toast', t, t)
    check('jar app starts on both workers', wait(lambda: len(rm_app(JAR)['workers']) == 2 and wait_app_started(JAR, 5), 600, 5))
    open_app(pg, JAR)
    head = pg.inner_text('#head')
    check('jar app: "uploaded jar", no Updates switch, no Check button', 'uploaded jar' in head
          and pg.locator('#head [data-updates]').count() == 0 and pg.locator('[data-act="check"]').count() == 0, head)
    tok = admin_token()
    check('route on 8092 fails while the app listens on its default 8093', gw_status(f'/{JAR}/api/v1/status', tok) in (502, 503, 504))
    open_app(pg, JAR, 'properties')
    pg.wait_for_selector('#saveProps')
    pg.click('[data-add="plain"]')
    pg.fill('[data-i="0"][data-f="key"]', 'http.port'); pg.fill('[data-i="0"][data-f="value"]', '8092')
    t = act(pg, '#saveProps', 'Properties saved', timeout=120000)
    check('a property moves the app to the routed port (properties override the app defaults)',
          t and wait(lambda: gw_status(f'/{JAR}/api/v1/status', tok) == 200, 300, 5), t)
    before = rm_app(JAR).get('deployed')
    open_app(pg, JAR, 'settings')
    pg.set_input_files('#editForm [name=jar]', jar)
    t = act(pg, '#editForm [type=submit]', 'Saved', timeout=300000)
    check('Settings: upload a new jar redeploys', t and wait(lambda: rm_app(JAR).get('deployed') != before, 120, 3), t)
    check('re-uploaded jar starts', wait_app_started(JAR, 600))
    t_logs_tab(pg, JAR)
    # mocked: pool without running workers, then no apps at all
    mock_json(pg, '**/api/apps', lambda d: [a.update(workers={}) for a in d['apps'] if a['name'] == JAR] and None)
    pg.evaluate('refresh()'); pg.wait_for_timeout(500)
    open_app(pg, JAR, 'logs')
    check('no running workers: header chip, list text, Logs placeholder', 'pool has no running workers' in pg.inner_text('#head')
          and 'No running workers' in pg.inner_text(f'[data-app="{JAR}"]') and 'no running workers' in pg.inner_text('#tabBody'))
    pg.unroute('**/api/apps')
    mock_json(pg, '**/api/apps', lambda d: d.update(apps=[]))
    pg.evaluate('refresh()'); pg.wait_for_timeout(500)
    pg.evaluate('route()'); pg.wait_for_timeout(300)
    check('no apps: list and main say so', 'No applications yet' in pg.inner_text('#appList') and 'No application selected' in pg.inner_text('#main'))
    pg.unroute('**/api/apps')
    pg.evaluate('refresh()'); pg.wait_for_timeout(500)


def t_delete(pg):
    section('Delete apps and the pool')
    goto_view(pg, 'pools')
    card = pool_card(pg, POOL)
    check('pool card lists its apps; Delete disabled while it has apps', MVN in card.inner_text() and JAR in card.inner_text()
          and card.locator('[data-del-pool]').is_disabled())
    card.locator(f'a[href="#/apps/{MVN}/overview"]').click()
    check('app link on the pool card opens the app', pg.url.endswith(f'#/apps/{MVN}/overview') and pg.inner_text('#head h1') == MVN)
    act(pg, '[data-act="delete"]', None, confirm=False)
    pg.wait_for_timeout(800)
    check('Delete → Cancel keeps the app', rm_app(MVN) is not None)
    for app in [MVN, JAR]:
        open_app(pg, app)
        t = act(pg, '[data-act="delete"]', 'Deleted', confirm=True, timeout=120000)
        check(f'Delete {app}: toast, gone from the list', t and wait(lambda: rm_app(app) is None, 60, 2)
              and pg.locator(f'[data-app="{app}"]').count() == 0, t)
    tok = admin_token()
    check('deleted apps\' routes are gone', wait(lambda: gw_status(f'/{MVN}/api/v1/status', tok) == 404 and gw_status(f'/{JAR}/api/v1/status', tok) == 404, 60, 3))
    w = f'mule-{POOL}-1'
    code, out = sh(['docker', 'exec', w, 'sh', '-c', 'ls /opt/mule/mule-standalone/apps'])
    check('undeployed from the workers', MVN not in out and JAR not in out, out[-200:])
    goto_view(pg, 'pools')
    pg.wait_for_timeout(1500)
    act(pg, f'[data-del-pool="{POOL}"]', None, confirm=False)
    pg.wait_for_timeout(800)
    check('Delete pool → Cancel keeps it', rm_pool(POOL) is not None)
    t = act(pg, f'[data-del-pool="{POOL}"]', 'Pool deleted', confirm=True, timeout=120000)
    check('Delete pool → OK: toast, card gone, containers removed', t and wait(lambda: rm_pool(POOL) is None, 60, 2)
          and wait(lambda: POOL not in sh(['docker', 'ps', '-a', '--format', '{{.Names}}'])[1], 120, 3), t)


def t_access(pg, ctx):
    section('API & settings: docs links, tokens, update checks, examples')
    goto_view(pg, 'access')
    pg.wait_for_selector('#tokenForm')
    with ctx.expect_page() as np:
        pg.click('a:has-text("API documentation")')
    d = np.value; d.wait_for_load_state()
    check('API documentation opens in a new tab and renders', 'Runtime Manager' in d.title() + d.inner_text('body')[:2000]
          and '/api/apps' in d.inner_text('body'), d.title())
    d.close()
    with ctx.expect_page() as np:
        pg.click('a.btn:text-is("OpenAPI spec")')
    s = np.value; s.wait_for_load_state()
    check('OpenAPI spec opens as JSON', '"openapi"' in s.content())
    s.close()
    with pg.expect_download() as dl:
        pg.click('a[download]')
    path = dl.value.path()
    spec = json.load(open(path, encoding='utf-8'))
    check('Download spec: file name and valid OpenAPI', dl.value.suggested_filename == 'runtime-manager-openapi.json' and 'paths' in spec)
    base = 'https://localhost:9443/runtime-manager'
    check('pipeline examples use this server\'s URL', f'{base}/api/apps/orders-api' in pg.inner_text('#view-access pre.code'))
    # tokens
    pg.click('#tokenForm [type=submit]')
    check('token name required', not pg.eval_on_selector('#tokenForm', 'f => f.checkValidity()'))
    pg.fill('#tokenForm [name=name]', TOKEN_NAME)
    pg.click('#tokenForm [type=submit]')
    pg.wait_for_selector('#tok', timeout=15000)
    tok = pg.inner_text('#tok')
    check('Create token: shown once in a dialog', tok.startswith('rm_') and pg.inner_text('#dlgTitle') == 'Token created')
    clear_toasts(pg)
    pg.click('#copyTok')
    t = toast(pg, 'Copied', 10000)
    check('Copy puts the token on the clipboard', t and pg.evaluate('navigator.clipboard.readText()') == tok, t)
    pg.click('#dlg [data-close]')
    pg.wait_for_timeout(1000)
    row = pg.locator('#view-access tr', has=pg.locator('td', has_text=TOKEN_NAME)).first
    check('token listed, never used', 'never' in row.inner_text())
    check('token works on the API', get(RM + '/api/apps', token=tok).status == 200)
    check('a token cannot manage tokens', get(RM + '/api/tokens', token=tok).status in (401, 403))
    goto_view(pg, 'apps'); goto_view(pg, 'access'); pg.wait_for_timeout(800)
    row = pg.locator('#view-access tr', has=pg.locator('td', has_text=TOKEN_NAME)).first
    check('last used updated', 'never' not in row.inner_text(), row.inner_text())
    act(pg, f'#view-access tr:has(td:text-is("{TOKEN_NAME}")) [data-revoke]', None, confirm=False)
    pg.wait_for_timeout(800)
    check('Revoke → Cancel keeps it working', get(RM + '/api/apps', token=tok).status == 200)
    t = act(pg, f'#view-access tr:has(td:text-is("{TOKEN_NAME}")) [data-revoke]', 'Token revoked', confirm=True)
    check('Revoke → OK: toast, token refused', t and get(RM + '/api/apps', token=tok).status == 401, t)
    pg.wait_for_timeout(800)
    check('revoked token gone from the table', pg.locator(f'#view-access td:text-is("{TOKEN_NAME}")').count() == 0)
    # update checks
    orig = rm('GET', 'api/settings').json()['check_minutes']
    check('update interval shows the saved value', pg.input_value('#checkForm [name=minutes]') == str(orig))
    pg.fill('#checkForm [name=minutes]', '-1')
    pg.click('#checkForm [type=submit]')
    check('negative interval blocked by the form', not pg.eval_on_selector('#checkForm', 'f => f.checkValidity()'))
    pg.fill('#checkForm [name=minutes]', '0')
    t = act(pg, '#checkForm [type=submit]', 'Saved')
    check('0 turns scheduled checks off', 'off' in t and rm('GET', 'api/settings').json()['check_minutes'] == 0, t)
    pg.fill('#checkForm [name=minutes]', '7')
    t = act(pg, '#checkForm [type=submit]', 'Saved')
    check('7 minutes saved', 'every 7 minutes' in t and rm('GET', 'api/settings').json()['check_minutes'] == 7, t)
    rm('PUT', 'api/settings', {'check_minutes': orig})


def t_toasts_and_session(pg, ctx):
    section('Toasts, signed-out handling, Sign out')
    pg.evaluate("toast('t-ui transient', 'x', 'good')")
    check('toast shown', pg.locator('.toast', has_text='t-ui transient').count() == 1)
    pg.wait_for_timeout(5600)
    check('toast disappears after 5 s', pg.locator('.toast', has_text='t-ui transient').count() == 0)
    if not AUTH_ON:
        return skip('Sign out', 'GATEWAY_AUTH=off')
    pg.click('#user a:has-text("Sign out")')
    pg.wait_for_load_state('networkidle')
    pg.goto(RM + '/')
    check('Sign out: back to the sign-in page', pg.locator('a.btn', has_text='Sign in with Keycloak').is_visible())
    check('API refuses the old session', ctx.request.get(RM + '/api/apps').status == 401)
    pg.click('text=Sign in with Keycloak')
    check('Keycloak session ended too (password asked)', pg.wait_for_selector('#username', timeout=30000) is not None)


def main():
    cleanup()
    try:
        with sync_playwright() as p:
            br = launch(p)
            try:
                t_sign_in(br)
            except Exception as e:
                check('sign-in page section ran to the end', False, f'{type(e).__name__}: {str(e)[:250]}')
            ctx = br.new_context(ignore_https_errors=True, viewport={'width': 1400, 'height': 1000}, accept_downloads=True)
            ctx.grant_permissions(['clipboard-read', 'clipboard-write'], origin=GW)
            pg = ctx.new_page()
            pg.on('pageerror', lambda e: page_errors.append(str(e)))
            section('Admin sign-in')
            if AUTH_ON:
                sign_in(pg, 'admin', ENV['KEYCLOAK_REALM_ADMIN_PASSWORD'])
            else:
                ctx.set_http_credentials(RM_AUTH)
                pg.goto(RM + '/')
            check('admin lands in the Runtime Manager', pg.wait_for_selector('[data-app]', timeout=30000) is not None)
            steps = [lambda: t_header_and_nav(pg), lambda: t_log_search_functions(pg), lambda: t_logs_tab(pg, 'ce-mule-base'),
                     lambda: t_pools_create(pg), lambda: t_pools_edit(pg), lambda: t_nodes(pg), lambda: t_deploy_maven(pg),
                     lambda: t_app_header(pg), lambda: t_properties(pg), lambda: t_overview(pg), lambda: t_settings(pg),
                     lambda: t_deploy_jar(pg), lambda: t_delete(pg), lambda: t_access(pg, ctx), lambda: t_toasts_and_session(pg, ctx)]
            for i, step in enumerate(steps):
                try:
                    step()
                except Exception as e:  # a broken step fails loudly but the rest still run
                    shot = os.path.join(OUT, f'rm-ui-step{i}.png')
                    try:
                        pg.screenshot(path=shot, full_page=True)
                    except Exception:
                        pass
                    check(f'step {i} ({lib._section}) ran to the end', False, f'{type(e).__name__}: {str(e)[:250]} (screenshot {shot})')
                    try:
                        pg.unroute_all()
                        clear_toasts(pg)
                        pg.keyboard.press('Escape')
                        pg.goto(RM + '/#/apps'); pg.wait_for_selector('[data-app]', timeout=30000)
                    except Exception:
                        pass
            section('Page health')
            check('no uncaught JavaScript errors during the run', not page_errors, page_errors[:3])
            br.close()
    finally:
        cleanup()
    done()


if __name__ == '__main__':
    main()
