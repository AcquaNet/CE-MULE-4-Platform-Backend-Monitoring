// config/apisix/test_home_link.js <home-link.js>: the "Home" link script (route home-link-js in apisix.yaml) in a minimal DOM stand-in:
// appended once to <html>, and its window capture listener keeps app click handlers (Grafana) off the link only
const appended = [], listeners = [];
const el = () => ({ style: {}, set textContent(v) { this.text = v; } });
global.document = { getElementById: id => appended.find(a => a.id === id) || null, createElement: el,
  documentElement: { appendChild: a => appended.push(a) } };
global.window = { addEventListener: (t, f, cap) => listeners.push({ t, f, cap }) };
const src = require('fs').readFileSync(process.argv[2], 'utf8');
eval(src); eval(src);  // twice: second run must not add a second link
if (appended.length !== 1) throw new Error('links: ' + appended.length);
const a = appended[0];
if (a.href !== '/' || a.target !== '_top' || a.text !== '\u2190 Home') throw new Error(JSON.stringify(a));
if (!listeners.some(l => l.t === 'click' && l.cap === true)) throw new Error('no capture click listener');
let stopped = false;
listeners[0].f({ target: { closest: s => s === '#ce-home-link' ? a : null }, stopImmediatePropagation: () => { stopped = true; } });
if (!stopped) throw new Error('click on the link not shielded from the app');
stopped = false;
listeners[0].f({ target: { closest: () => null }, stopImmediatePropagation: () => { stopped = true; } });
if (stopped) throw new Error('other clicks must reach the app');
console.log('home-link.js: ok');
