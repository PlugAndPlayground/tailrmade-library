// Loads an app in the real app across themes and widths, then runs its scenarios.
// Findings go in JSON files; app.py decides pass or fail, so one bad cell does not hide the rest.
const D = '[data-cy="dashboard"]';
const WIDTHS = [[1440, 900, 'desktop'], [390, 844, 'phone']];
const AsyncFunction = (async () => {}).constructor;
const local = (url) => /^(blob:|data:)/.test(url) || url.startsWith(Cypress.expose('base')) || /^\/[^/]/.test(url);
const ctl = (fn) => cy.window().its('testController', { timeout: 90000 }).then({ timeout: 180000 }, fn);
const clean = (text) => String(text).slice(0, 300);

let logs = [];
let stubs = [];
let requests = [];
const job = JSON.parse(Cypress.expose('job'));

Cypress.on('uncaught:exception', () => false);
Cypress.on('window:before:load', (win) => {
  ['warn', 'error'].forEach((level) => {
    const original = win.console[level].bind(win.console);
    win.console[level] = (...args) => {
      try {
        logs.push(`${level}: ${clean(args.map((x) => x?.stack ?? x?.message ?? (typeof x === 'string' ? x : JSON.stringify(x))).join(' '))}`);
      } catch (e) { /* unprintable */ }
      original(...args);
    };
  });
  win.addEventListener('error', (e) => logs.push(`uncaught: ${clean(e.message)}`));
  win.addEventListener('unhandledrejection', (e) => logs.push(`rejection: ${clean(e.reason?.message ?? e.reason)}`));
  const realFetch = win.fetch.bind(win);
  win.fetch = async (...args) => {
    const url = String(args[0]?.url ?? args[0]);
    if (!local(url)) requests.push(url);
    const stub = stubs.find((s) => new RegExp(s.match).test(url));
    if (!stub) return realFetch(...args);
    if (stub.delay) await new Promise((resolve) => win.setTimeout(resolve, stub.delay));
    if (stub.network_error) throw new win.TypeError('Failed to fetch');
    const body = typeof stub.body === 'string' ? stub.body : JSON.stringify(stub.body ?? {});
    return new win.Response(body, { status: stub.status ?? 200, headers: { 'Content-Type': stub.content_type ?? 'application/json' } });
  };
});

const statuses = (c) => c.getNodes().flatMap((n) => {
  const out = [];
  const add = (s, sock) => { try { if (s.isProblem()) out.push({ node: n.name, sock, msg: clean(s.message) }); } catch (e) { /* no status */ } };
  add(n.status.node);
  (n.status.custom ?? []).forEach((s) => add(s));
  n.getAllSockets().forEach((s) => add(s.status, s.name));
  return out;
});

const parseColor = (text) => {
  const m = text.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const [r, g, b, a = 1] = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
  return { r, g, b, a };
};
const over = (top, under) => ({
  r: top.r * top.a + under.r * (1 - top.a),
  g: top.g * top.a + under.g * (1 - top.a),
  b: top.b * top.a + under.b * (1 - top.a),
  a: 1,
});
const luminance = ({ r, g, b }) => {
  const f = (v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
// The colour behind an element, or null when an image or gradient makes it unknowable.
const backdrop = (win, el) => {
  const layers = [];
  for (let e = el; e; e = e.parentElement) {
    const style = win.getComputedStyle(e);
    if (style.backgroundImage !== 'none') return null;
    const c = parseColor(style.backgroundColor);
    if (c && c.a > 0) { layers.push(c); if (c.a === 1) break; }
  }
  return layers.reduceRight((under, top) => over(top, under), { r: 255, g: 255, b: 255, a: 1 });
};
const describeEl = (e) => `${e.tagName.toLowerCase()} "${clean((e.textContent || e.value || '').trim()).slice(0, 50)}"`;

const measure = (win) => {
  const r = {};
  const dash = win.document.querySelector(D);
  if (!dash) return { noPage: true };
  const box = dash.getBoundingClientRect();
  r.pageWidth = Math.round(box.width);
  r.pageHeight = dash.scrollHeight;
  r.docOverflowX = win.document.documentElement.scrollWidth - win.innerWidth;
  const skip = '.leaflet-container, .dvn-scroller, [class*="gdg-"], svg';
  const all = [...dash.querySelectorAll('*')].filter((e) => {
    const b = e.getBoundingClientRect();
    // A 1px box is a visually hidden input, not content.
    return b.width > 1 && b.height > 1 && !e.closest(skip) && win.getComputedStyle(e).visibility !== 'hidden';
  });
  r.overflowing = all.filter((e) => { const b = e.getBoundingClientRect(); return b.right > box.right + 1 || b.left < box.left - 1; }).slice(0, 6).map((e) => { const b = e.getBoundingClientRect(); return `${describeEl(e)} x=${Math.round(b.left)}..${Math.round(b.right)} page=${Math.round(box.left)}..${Math.round(box.right)}`; });
  const texts = all.filter((e) => [...e.childNodes].some((c) => c.nodeType === 3 && c.textContent.replace(/ /g, ' ').trim()));
  r.clipped = [];
  r.tightLines = [];
  r.lowContrast = [];
  texts.forEach((e) => {
    const style = win.getComputedStyle(e);
    if (style.overflowX !== 'visible' && e.scrollWidth > e.clientWidth + 1) r.clipped.push(describeEl(e));
    if (style.overflowY !== 'visible' && e.scrollHeight > e.clientHeight + 1) r.clipped.push(describeEl(e));
    const size = parseFloat(style.fontSize);
    const line = parseFloat(style.lineHeight);
    if (line && line < size * 0.95) r.tightLines.push(`${describeEl(e)} line ${line}px, font ${size}px`);
    const color = parseColor(style.color);
    const back = backdrop(win, e);
    if (color && back && !e.closest('[disabled], [aria-disabled="true"]')) {
      const ratio = contrast(over(color, back), back);
      if (ratio < 3) r.lowContrast.push(`${describeEl(e)} ${ratio.toFixed(1)}:1`);
    }
  });
  r.sidewaysScroll = all.filter((e) => /auto|scroll/.test(win.getComputedStyle(e).overflowX) && e.scrollWidth > e.clientWidth + 1).slice(0, 4).map(describeEl);
  const text = dash.textContent;
  r.placeholderPage = /No user interface yet|Create user interface/.test(text);
  r.literalMarkup = (text.match(/<\/?[a-z]+[ >]|\{\{[^}]*\}\}|\[[^\]]+\]\{\.[a-z]+\}/g) ?? []).slice(0, 5);
  // Per element: the page's whole text runs words together, so "undefinedTotal" would slip past \b.
  r.junk = texts.map((e) => (e.textContent.match(/\bundefined\b|\bNaN\b|\[object Object\]|\bnull\b/) ?? [])[0]).filter(Boolean).slice(0, 5);
  r.brokenImages = [...dash.querySelectorAll('img')].filter((i) => i.complete && i.naturalWidth === 0).map((i) => clean(i.src).slice(0, 100));
  r.text = clean(text.replace(/\s+/g, ' '));
  return r;
};

const openApp = (theme, width, height, wait, scenarioStubs, hash) => {
  cy.then(() => { logs = []; stubs = scenarioStubs ?? []; requests = []; });
  cy.viewport(width, height);
  // A scenario's hash opens the app as if from a shared link (#key=value), for the URL Parameter node.
  cy.visit(`${Cypress.expose('base')}/?new=true&toastEverything=true${hash ? `#${hash}` : ''}`, { timeout: 120000 });
  cy.wait(2500);
  ctl((c) => {
    const graph = JSON.parse(job.text);
    if (theme) graph.graphData.graphSettings = { ...graph.graphData.graphSettings, theme };
    return c.loadStringifiedGraph(JSON.stringify(graph));
  });
};
const startApp = (r, wait) => {
  cy.wait(3000);
  ctl((c) => {
    r.pausedOnLoad = !c.isLoadedAppRunning();
    r.nodeCount = c.getNodes().length;
    r.risks = c.getNodes().flatMap((n) => n.getRisks().map((x) => ({ node: n.name, kind: x.kind, severity: x.severity, target: x.target })));
    r.problemsOnLoad = statuses(c);
  });
  // Files from outside open paused behind the risk review, as a user would meet them.
  // The sheet can take several seconds to open on a big graph, so wait for Run app.
  // The banner can also show up after the first check, so a paused app waits for it.
  // It shows either the banner or the sheet itself.
  const gate = '[data-cy="start-app"], [data-cy="run-reviewed-app"]';
  cy.get('body').then(($b) => {
    if (!r.pausedOnLoad && !$b.find(gate).length) return;
    cy.get(gate, { timeout: 20000 }).first().then(($el) => {
      if ($el.attr('data-cy') === 'start-app') cy.wrap($el).click({ force: true });
      cy.get('[data-cy="run-reviewed-app"]', { timeout: 20000 }).click({ force: true });
    });
  });
  cy.wait(wait ?? 6000);
  ctl((c) => { r.running = c.isLoadedAppRunning(); r.problems = statuses(c); });
};

// Polls inside one promise. A chain of Cypress commands held the page's update back, so a
// slow request looked stuck while a real user would have seen the result.
const pollText = (r, want, present, timeout) => cy.window().then({ timeout: timeout + 5000 }, (win) => new Promise((resolve) => {
  const started = Date.now();
  const look = () => {
    const text = win.document.querySelector(D)?.textContent ?? '';
    if (text.includes(want) === present) return resolve(null);
    if (Date.now() - started > timeout) {
      r.failures.push(`${present ? 'expected to see' : 'expected not to see'} "${want}"; page says: ${clean(text.replace(/\s+/g, ' '))}`);
      return resolve(null);
    }
    return win.setTimeout(look, 200);
  };
  look();
}));
const controlFor = ($d, label) => {
  const labels = $d.find('label').toArray().filter((e) => e.textContent.trim().startsWith(label));
  for (const e of labels) {
    const byId = e.htmlFor && e.ownerDocument.getElementById(e.htmlFor);
    if (byId) return byId;
    for (let p = e.parentElement; p && p !== $d[0]; p = p.parentElement) {
      const found = p.querySelector('input:not([type=hidden]), textarea, [role=combobox], select');
      if (found) return found;
    }
  }
  return $d.find(`input[aria-label="${label}"], input[placeholder="${label}"]`)[0];
};
const textElement = ($d, text) => $d.find('*').toArray().filter((e) => e.children.length === 0 && e.textContent.includes(text))[0];
const STEPS = {
  press: (r, s) => cy.get(D).then(($d) => {
    const cyButton = $d.find(`[data-cy="button-${s.press}"]`);
    if (cyButton.length) return cy.wrap(cyButton.first()).click({ force: true });
    const b = $d.find('button, [role=button], [role=tab]').toArray().find((e) => e.textContent.trim() === s.press);
    if (!b) { r.failures.push(`no button "${s.press}"`); return null; }
    return cy.wrap(b).click({ force: true });
  }),
  type: (r, s) => cy.get(D).then(($d) => {
    const input = controlFor($d, s.type);
    if (!input) { r.failures.push(`no input labelled "${s.type}"`); return null; }
    const typed = s.text === '' ? '{selectall}{backspace}' : `{selectall}{backspace}${s.text}`;
    return cy.wrap(input).click({ force: true }).type(typed, { force: true, delay: 10 });
  }),
  choose: (r, s) => cy.get(D).then(($d) => {
    const input = controlFor($d, s.choose);
    if (!input) { r.failures.push(`no dropdown labelled "${s.choose}"`); return null; }
    cy.wrap(input).click({ force: true });
    cy.wait(300);
    return cy.get('body').then(($b) => {
      const option = $b.find('[role=option], li').toArray().find((e) => e.textContent.trim() === s.option);
      if (!option) { r.failures.push(`no option "${s.option}" in "${s.choose}"`); return null; }
      return cy.wrap(option).click({ force: true });
    });
  }),
  set_socket: (r, s) => ctl((c) => { c.setNodeInputValue(s.set_socket, s.socket, s.value); return c.executeNodeByID ? c.executeNodeByID(s.set_socket) : null; }),
  // For controls a label cannot reach: keys is Cypress type syntax, such as {rightarrow}.
  keys: (r, s) => cy.get(`${D} ${s.selector}`).first().focus().type(s.keys, { force: true }),
  click: (r, s) => cy.get(`${D} ${s.click}`).first().click({ force: true }),
  wait: (r, s) => cy.wait(s.wait),
  see: (r, s) => pollText(r, s.see, true, s.timeout ?? 15000),
  not_see: (r, s) => pollText(r, s.not_see, false, s.timeout ?? 5000),
  requests: (r, s) => cy.then(() => {
    const hits = requests.filter((u) => new RegExp(s.requests).test(u));
    if (hits.length !== s.count) r.failures.push(`expected ${s.count} requests matching ${s.requests}, got ${hits.length}: ${hits.map((u) => u.slice(0, 80)).join(', ')}`);
  }),
  reset_requests: () => cy.then(() => { requests = []; }),
  // Swap the fake server mid-scenario, to test recovery.
  set_stub: (r, s) => cy.then(() => { stubs = s.set_stub; }),
  // Remember where a piece of text sits, then check that it has not moved.
  remember: (r, s) => cy.get(D).then(($d) => {
    const e = textElement($d, s.remember);
    if (!e) { r.failures.push(`no text "${s.remember}" to remember`); return; }
    r.positions[s.remember] = Math.round(e.getBoundingClientRect().top);
  }),
  same_place: (r, s) => cy.get(D).then(($d) => {
    const e = textElement($d, s.same_place);
    if (!e) { r.failures.push(`text "${s.same_place}" is gone`); return; }
    const top = Math.round(e.getBoundingClientRect().top);
    if (Math.abs(top - r.positions[s.same_place]) > 1) r.failures.push(`"${s.same_place}" moved from y=${r.positions[s.same_place]} to y=${top}`);
  }),
  check_page: (r, s) => cy.window().then((win) => { r.pages.push({ at: s.check_page, ...measure(win) }); }),
  shot: (r, s) => cy.screenshot(`${job.tag}-${r.name}-${s.shot}`, { capture: 'viewport', overwrite: true }),
  eval: (r, s) => ctl((c) => new AsyncFunction('c', s.eval)(c)).then((value) => {
    if (value !== true && s.expect === undefined) r.failures.push(`eval returned ${JSON.stringify(value)}: ${s.eval.slice(0, 100)}`);
    if (s.expect !== undefined && JSON.stringify(value) !== JSON.stringify(s.expect)) r.failures.push(`expected ${JSON.stringify(s.expect)}, got ${JSON.stringify(value)}: ${s.eval.slice(0, 100)}`);
  }),
};
const finish = (r) => {
  cy.then(() => { r.logs = [...new Set(logs)]; r.requests = [...requests]; });
  cy.then(() => cy.writeFile(`${job.out}/res/${r.name}.json`, r));
};

if (!job.quick) {
  job.themes.forEach(({ name, theme }) => {
    WIDTHS.forEach(([width, height, label]) => {
      it(`${name} ${label}`, () => {
        const r = { name: `${name}-${label}`, kind: 'matrix', theme: name, width };
        openApp(theme, width, height);
        startApp(r);
        cy.window().then((win) => { Object.assign(r, measure(win)); });
        cy.screenshot(`${job.tag}-${name}-${label}`, { capture: 'viewport', overwrite: true });
        // Grow the window to fit the whole page for a second picture when it scrolls.
        cy.then(() => {
          if (r.pageHeight > height + 8) {
            cy.viewport(width, Math.min(r.pageHeight + 60, 4200));
            cy.wait(800);
            cy.screenshot(`${job.tag}-${name}-${label}-full`, { capture: 'viewport', overwrite: true });
          }
        });
        finish(r);
      });
    });
  });
}

(job.scenarios ?? []).forEach((scenario) => {
  it(`scenario ${scenario.name}`, () => {
    const r = { name: `scenario-${scenario.name}`, kind: 'scenario', failures: [], positions: {}, pages: [], allowProblems: scenario.allow_problems ?? [], allowLogs: scenario.allow_logs ?? [] };
    const [width, height] = scenario.viewport ?? [1440, 900];
    openApp(scenario.theme, width, height, undefined, scenario.stub, scenario.hash);
    startApp(r, scenario.wait);
    (scenario.steps ?? []).forEach((step) => {
      const kind = Object.keys(STEPS).find((k) => k in step);
      if (!kind) throw new Error(`unknown step ${JSON.stringify(step)}`);
      STEPS[kind](r, step);
    });
    cy.window().then((win) => { r.pages.push({ at: 'end', ...measure(win) }); });
    cy.screenshot(`${job.tag}-${r.name}`, { capture: 'viewport', overwrite: true });
    ctl((c) => { r.problems = statuses(c); });
    finish(r);
  });
});

it('graph and reload', () => {
  const r = { name: 'graph', kind: 'graph' };
  openApp(null, 1440, 900);
  startApp(r);
  cy.screenshot(`${job.tag}-opening`, { capture: 'viewport', overwrite: true });
  ctl((c) => JSON.parse(JSON.stringify(c.getGraph().getSerializedStoredGraph()))).then((first) => {
    cy.writeFile(`${job.out}/res/export-1.json`, first);
    ctl((c) => c.loadStringifiedGraph(JSON.stringify(first)));
    cy.wait(4000);
    ctl((c) => JSON.parse(JSON.stringify(c.getGraph().getSerializedStoredGraph()))).then((second) => cy.writeFile(`${job.out}/res/export-2.json`, second));
  });
  startApp({}, 2000);
  ctl((c) => c.toggleDashboard('CLOSE'));
  cy.wait(1500);
  ctl((c) => { c.zoomToFitNodesById(undefined, 1); });
  cy.wait(2500);
  cy.screenshot(`${job.tag}-graph`, { capture: 'viewport', overwrite: true });
  finish(r);
});
