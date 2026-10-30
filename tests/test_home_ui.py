# Browser checks of the platform's single sign-on (real Chrome through Playwright): the home page as admin and as developer
# (cards: usable, greyed, hidden; each opens its tool signed in without a second password prompt), sign out, the Keycloak
# admin consoles, the tools' pages rendering real content, Dashboards Discover tenant isolation, and the home page on a phone.
#   tests/.venv/Scripts/python tests/test_home_ui.py
# Failure screenshots go to tests/out/. Nothing is left behind (a private-tenant index pattern is created and deleted).
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
OUT = os.path.join(ROOT, 'tests', 'out')
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):   # this file's screenshots of an earlier run
    if f.startswith('ui-') and f.endswith('.png'):
        os.remove(os.path.join(OUT, f))
T0 = time.time()
USERS = {'admin': ENV['KEYCLOAK_REALM_ADMIN_PASSWORD'], 'developer': ENV['KEYCLOAK_REALM_DEV_PASSWORD']}
XSRF = {'osd-xsrf': 'true', 'Content-Type': 'application/json'}
ERR_PAGE = re.compile(r'502 Bad Gateway|503 Service|504 Gateway|Internal Server Error|404 Not Found|Cookie Too Large'
                      r'|Request Header Or Cookie Too Large|We are sorry|Page not found', re.I)

# card href -> (profile it needs or None, realm role admin needed, text a signed-in page shows)
CARDS = {
    '/runtime-manager/': (None, True, r'Runtime pools|Applications'),
    '/dashboards/': ('logging', False, r'OpenSearch Dashboards|Home|Discover'),
    '/log-archiver/': ('logging', True, r'Log Archiver|Log indices|Activity'),
    '/grafana/': ('monitoring', True, r'Welcome to Grafana|Dashboards|Home'),
    '/jaeger/': ('tracing', True, r'Find Traces|Search|Service'),
    '/prometheus/': ('monitoring', True, r'Prometheus|Execute|Query'),
    '/alertmanager/': ('alerting', True, r'Alertmanager|Alerts|Silences'),
    '/activemq/admin/': ('mq', True, r'ActiveMQ'),
    '/runtime-manager/api/docs': (None, None, r'API|OpenAPI'),   # public page: shown to everyone
    '/auth/admin/mule/console/': ('auth', True, r'Realm settings|Clients|Users|Manage'),
    '/auth/realms/mule/account/': ('auth', False, r'Personal info|Account|Signing in'),
}
fail_no = 0


def shot(page, name):
    global fail_no
    fail_no += 1
    try:
        page.screenshot(path=os.path.join(OUT, f'ui-{fail_no:02d}-{re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:80]}.png'), full_page=True)
    except Exception:
        pass


def ck(page, name, ok, detail=''):
    if not check(name, ok, detail):
        shot(page, name)
    return ok


def login_form(page):
    return page.locator('#kc-form-login').count() > 0


def sign_in(page, user, pw):
    page.wait_for_selector('#username', timeout=30000)
    page.fill('#username', user)
    page.fill('#password', pw)
    page.click('#kc-login')


def body_text(page):
    try:
        return page.inner_text('body', timeout=10000)
    except Exception:
        return ''


def wait_text(page, pattern, timeout=25000):
    """True once the page body matches pattern (SPAs render late)."""
    end = time.time() + timeout / 1000
    while time.time() < end:
        if re.search(pattern, body_text(page)):
            return True
        page.wait_for_timeout(500)
    return False


def home_cards(page):
    page.wait_for_selector('main .card', timeout=30000)
    page.wait_for_function("!document.querySelector('.card.wait')", timeout=20000)
    return [{'href': c.get_attribute('href'), 'cls': c.get_attribute('class') or '', 'aria': c.get_attribute('aria-disabled'),
             'text': c.inner_text().split('\n')[0], 'el': c} for c in page.query_selector_all('main .card')]


def card_key(c):
    """The card's original link: an off card lost its href, so match by its title."""
    titles = {'Runtime Manager': '/runtime-manager/', 'Logs': '/dashboards/', 'Log archiver': '/log-archiver/', 'Metrics dashboards': '/grafana/',
              'Traces': '/jaeger/', 'Metrics and alerts': '/prometheus/', 'Alert notifications': '/alertmanager/',
              'Message broker': '/activemq/admin/', 'API docs': '/runtime-manager/api/docs',
              'Users and tenants': '/auth/admin/mule/console/', 'My account': '/auth/realms/mule/account/'}
    return titles.get(c['text'], c['href'])


def run_user(browser, user):
    section(f'Home page as {user}')
    admin = user == 'admin'
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1280, 'height': 900})
    page = ctx.new_page()
    prompts = 0
    try:
        page.goto(GW + '/')
        ck(page, f'{user}: home redirects to the Keycloak sign-in (realm mule)', login_form(page) and '/realms/mule/' in page.url, page.url)
        sign_in(page, user, USERS[user])
        prompts += 1
        cards = home_cards(page)
        ck(page, f'{user}: back on the home page after sign-in', page.url.rstrip('/') == GW and 'Mule Platform' in page.title(), page.url)
        by = {card_key(c): c for c in cards}
        for href, (prof, needs_admin, _) in CARDS.items():
            running = prof is None or need(prof)
            allowed = needs_admin is None or admin or not needs_admin
            c = by.get(href)
            if not allowed:
                ck(page, f'{user}: card {href} hidden (not for this user)', c is None, c and c['cls'])
            elif not running:
                ok = c is not None and 'off' in c['cls'].split() and c['href'] is None and c['aria'] == 'true'
                ck(page, f'{user}: card {href} greyed (profile {prof} off): class off, no href, aria-disabled', ok,
                   c and (c['cls'], c['href'], c['aria']))
                if c:
                    before = page.url
                    c['el'].click(force=True)
                    page.wait_for_timeout(800)
                    ck(page, f'{user}: greyed card {href} is not clickable', page.url == before, page.url)
            else:
                ck(page, f'{user}: card {href} usable', c is not None and 'off' not in c['cls'] and c['href'] == href,
                   c and (c['cls'], c['href']))
        # every usable card opens its tool signed in, without another password prompt
        for href, (prof, needs_admin, pattern) in CARDS.items():
            c = by.get(href)
            if not c or not c['href'] or (needs_admin and not admin):
                continue
            page.goto(GW + '/')
            home_cards(page)
            page.click(f'main .card[href="{href}"]')
            try:
                page.wait_for_load_state('networkidle', timeout=20000)
            except Exception:
                pass
            btn = page.locator('text=Sign in with Keycloak')
            if btn.count():
                btn.first.click()   # the Runtime Manager's own sign-in button: rides the Keycloak session
                page.wait_for_load_state('networkidle', timeout=20000)
            if login_form(page):
                prompts += 1
                ck(page, f'{user}: {href} opened without a password prompt', False, page.url)
                continue
            ok = wait_text(page, pattern)
            txt = body_text(page)
            ck(page, f'{user}: {href} opens signed in and renders ({pattern})', ok and not ERR_PAGE.search(txt[:3000]),
               f'{page.url} {txt[:200]}')
            if href == '/grafana/' or href == '/runtime-manager/':
                ck(page, f'{user}: {href} did not land on a login page', '/login' not in page.url, page.url)
        ck(page, f'{user}: one password prompt in total', prompts == 1, prompts)
        if admin:
            tool_pages(page)
        else:
            discover_tenant(page)
        # sign out: the Keycloak session ends too, the next page asks for the password again
        page.goto(GW + '/')
        home_cards(page)
        page.click('header a[href="/logout"]')
        page.wait_for_load_state('networkidle', timeout=20000)
        ck(page, f'{user}: Sign out lands on the Keycloak sign-in', login_form(page), page.url)
        for href in ['/', '/dashboards/' if need('logging') else '/']:
            page.goto(GW + href)
            page.wait_for_load_state('networkidle', timeout=20000)
            ck(page, f'{user}: after sign out {href} asks for the password', login_form(page), page.url)
    except Exception as e:
        ck(page, f'{user}: home page flow ran without errors', False, e)
    finally:
        ctx.close()


def tool_pages(page):
    section('Tool pages render real content (admin)')
    if need('tracing'):
        page.goto(GW + '/jaeger/search?service=ce-mule-base&limit=5&lookback=1h')
        ck(page, 'Jaeger search page lists ce-mule-base traces', wait_text(page, r'ce-mule-base') and
           wait_text(page, r'\d+ Traces?|Spans?'), body_text(page)[:200])
    if need('monitoring'):
        page.goto(GW + '/prometheus/query?g0.expr=up&g0.tab=table')
        ck(page, 'Prometheus UI runs the query up', wait_text(page, r'job="apisix"|apisix'), body_text(page)[:200])
        page.goto(GW + '/prometheus/targets')
        ck(page, 'Prometheus targets page', wait_text(page, r'apisix') and not re.search(r'\bDOWN\b', body_text(page)),
           body_text(page)[:300])
        page.goto(GW + '/grafana/connections/datasources')
        ck(page, 'Grafana data sources page shows Prometheus', wait_text(page, r'Prometheus'), body_text(page)[:200])
        page.goto(GW + '/grafana/dashboards?query=APISIX')
        ck(page, 'Grafana dashboards list shows Apache APISIX', wait_text(page, r'Apache APISIX'), body_text(page)[:200])
    if need('mq'):
        page.goto(GW + '/activemq/admin/queues.jsp')
        ck(page, 'ActiveMQ console queues page', wait_text(page, r'Queues') and not ERR_PAGE.search(body_text(page)),
           body_text(page)[:200])
    if need('logging'):
        page.goto(GW + '/dashboards/app/home')
        ck(page, 'Dashboards home', wait_text(page, r'Home|OpenSearch Dashboards'), body_text(page)[:200])
    page.goto(GW + '/auth/admin/mule/console/#/mule/users')
    ck(page, 'Keycloak realm console: users list', wait_text(page, r'developer'), body_text(page)[:200])
    if need('logging'):
        log_archiver(page)
    home_link(page)


def log_archiver(page):
    section('Log archiver page (admin)')
    page.goto(GW + '/log-archiver/')
    ck(page, 'Overview: disk, last pass, log indices', wait_text(page, r'OpenSearch disk') and wait_text(page, r'Log indices'),
       body_text(page)[:200])
    page.click('[data-tab="usage"]')
    ck(page, 'Usage: both disks, per app, per day, destinations', wait_text(page, r'OpenSearch disk') and wait_text(page, r'Archive disk')
       and wait_text(page, r'Logs per app') and page.locator('#dayChart svg rect[data-i]').count() >= 1, body_text(page)[:200])
    page.hover('#dayChart svg rect[data-i]', force=True)
    ck(page, 'Usage: day chart hover shows the day', page.locator('#dayChart .tip').is_visible())
    page.click('[data-tab="rules"]')
    ck(page, 'Rules: global rules and archive filters', wait_text(page, r'Global rules') and wait_text(page, r'Archive filters'),
       body_text(page)[:200])
    ck(page, 'Rules: log size and archive space limits apart', all(page.locator(s).count() == 1 for s in ('#rMax', '#rDisk', '#aMax', '#aPct')))
    page.click('[data-addr]')  # + rule: an unsaved change shows the save bar; Discard puts it back
    ck(page, 'editing shows the save bar', page.locator('#savebar').is_visible())
    page.click('#discardBtn')
    ck(page, 'Discard hides it again', not page.locator('#savebar').is_visible())
    page.click('[data-tab="destinations"]')
    ck(page, 'Destinations: the default disk folder and S3 connections', wait_text(page, r'S3 connections')
       and page.locator('[data-t="local"]').count() == 1, body_text(page)[:200])
    page.click('[data-tab="apps"]')
    ck(page, 'Apps tab lists apps from the logs', wait_text(page, r'Archive filters'), body_text(page)[:200])


def home_link(page):
    """The gateway's "Home" link (home-link.js): visible on each tool once the app has rendered, and a click lands on the
    platform home page, not the tool's own home (Grafana routes link clicks itself; Dashboards empties <body>)."""
    section('Home link on the tool pages (admin)')
    tools = [('Runtime Manager', '/runtime-manager/', True), ('Log archiver', '/log-archiver/', need('logging')),
             ('Jaeger', '/jaeger/search', need('tracing')),
             ('Grafana', '/grafana/dashboards', need('monitoring')), ('Prometheus', '/prometheus/query', need('monitoring')),
             ('Dashboards', '/dashboards/app/home', need('logging')), ('Keycloak console', '/auth/admin/mule/console/', True)]
    for name, path, on in tools:
        if not on:
            skip(f'Home link on {name}', 'profile off')
            continue
        page.goto(GW + path)
        page.wait_for_load_state('networkidle', timeout=30000)
        page.wait_for_timeout(1500)  # SPAs that rebuild the page after load (Dashboards)
        link = page.locator('#ce-home-link')
        ck(page, f'{name}: Home link visible', link.count() == 1 and link.is_visible(), link.count())
        if link.count() == 1:
            link.click()
            page.wait_for_load_state('networkidle', timeout=20000)
            ck(page, f'{name}: Home link opens the platform home page', page.url.rstrip('/?') == GW.rstrip('/'), page.url)


def discover_tenant(page):
    section('Dashboards Discover as developer (tenant demo only)')
    if not need('logging'):
        skip('Discover', 'logging profile off')
        return
    # a fresh log line of tenant demo
    get('/api/v1/status', token=dev_token())
    page.goto(GW + '/dashboards/app/home')
    page.wait_for_load_state('networkidle', timeout=30000)
    ip = 't-stack-ui-' + uuid.uuid4().hex[:6]
    r = page.request.post(f'{GW}/dashboards/api/saved_objects/index-pattern/{ip}', headers=XSRF,
                          data=json.dumps({'attributes': {'title': 'mule-logs-*', 'timeFieldName': '@timestamp'}}))
    ck(page, 'developer can save an index pattern in the private tenant', r.status == 200, r.status)
    try:
        page.goto(f"{GW}/dashboards/app/data-explorer/discover#?_a=(discover:(columns:!(tenant_id),sort:!()),"
                  f"metadata:(indexPattern:'{ip}',view:discover))&_g=(time:(from:now-7d,to:now))")
        page.wait_for_load_state('networkidle', timeout=30000)

        last = [None]

        def count():
            t = body_text(page)
            if re.search(r'No results match|No Results', t):
                return 0
            m = re.search(r'([\d,]+)\s+hits?', t)
            return int(m.group(1).replace(',', '')) if m else None

        def hits(query):
            # typed into the search bar like a user (DQL); the count is read once it changed (or settled for 15 s)
            box = page.locator('[data-test-subj="queryInput"]')
            box.wait_for(timeout=30000)
            box.fill(query)
            box.press('Enter')
            end, n = time.time() + 15, None
            while time.time() < end:
                page.wait_for_timeout(500)
                n = count()
                if n is not None and n != last[0]:
                    break
            last[0] = n
            return n
        n_all = hits('')
        ck(page, 'Discover loads mule-logs-* with hits', n_all and n_all > 0, n_all)
        n_demo = hits('tenant_id:demo')
        ck(page, 'Discover: every hit is tenant demo', n_all is not None and n_demo == n_all, (n_all, n_demo))
        n_other = hits('not tenant_id:demo')
        ck(page, 'Discover: no hit of another tenant', n_other == 0, n_other)
        for t in ['acme-corp', 'default', 'unknown']:
            n = hits(f'tenant_id:{t}')
            ck(page, f'Discover: tenant {t} invisible', n == 0, n)
    finally:
        page.request.delete(f'{GW}/dashboards/api/saved_objects/index-pattern/{ip}', headers=XSRF)


def keycloak_master(browser):
    section('Keycloak master admin console (9080)')
    if not need('auth'):
        skip('master console', 'auth profile off')
        return
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 1280, 'height': 900})
    page = ctx.new_page()
    try:
        page.goto(LO + '/auth/admin/master/console/')
        page.wait_for_selector('#username', timeout=30000)
        ck(page, 'master console asks for the sign-in on 9080 (realm master)', login_form(page) and
           page.url.startswith(LO + '/auth/realms/master/'), page.url)
        sign_in(page, ENV.get('KEYCLOAK_ADMIN_USER', 'admin'), ENV['KEYCLOAK_ADMIN_PASSWORD'])
        ck(page, 'master console loads after sign-in (KEYCLOAK_ADMIN_USER)', wait_text(page, r'Realm settings|Clients|Manage realms'),
           f'{page.url} {body_text(page)[:200]}')
        ck(page, 'master console stays on 9080', page.url.startswith(LO + '/auth/admin/master/console'), page.url)
        r = page.goto(GW + '/auth/admin/master/console/')
        ck(page, 'master console on 9443 -> 404', r is not None and r.status == 404, r and r.status)
    except Exception as e:
        ck(page, 'master console flow ran without errors', False, e)
    finally:
        ctx.close()


def mobile(browser):
    section('Home page on a phone (390 px)')
    ctx = browser.new_context(ignore_https_errors=True, viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True,
                              device_scale_factor=3)
    page = ctx.new_page()
    try:
        page.goto(GW + '/')
        if login_form(page):
            w = page.evaluate('[document.documentElement.scrollWidth, document.documentElement.clientWidth]')
            ck(page, 'Keycloak sign-in page: no horizontal scroll at 390 px', w[0] <= w[1], w)
            sign_in(page, 'admin', USERS['admin'])
        cards = home_cards(page)
        w = page.evaluate('[document.documentElement.scrollWidth, document.documentElement.clientWidth]')
        ck(page, 'home page: no horizontal scroll at 390 px', w[0] <= w[1], w)
        boxes = [c['el'].bounding_box() for c in cards]
        ck(page, 'home page: every card fits the screen width', all(b and b['x'] >= 0 and b['x'] + b['width'] <= 390 for b in boxes),
           boxes[:3])
        ck(page, 'home page: one card per row on a phone', len({round(b['x']) for b in boxes if b}) == 1, {round(b['x']) for b in boxes if b})
        page.screenshot(path=os.path.join(OUT, 'ui-home-mobile.png'), full_page=True)
    except Exception as e:
        ck(page, 'mobile flow ran without errors', False, e)
    finally:
        ctx.close()


import uuid

if not (AUTH_ON and need('auth')):
    skip('browser SSO checks', 'GATEWAY_AUTH=off or auth profile off')
    done()
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    try:
        run_user(browser, 'admin')
        run_user(browser, 'developer')
        keycloak_master(browser)
        mobile(browser)
    finally:
        browser.close()
print(f'\nruntime {time.time() - T0:.0f} s')
done()
