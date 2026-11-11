// Loads an app in the real app across themes and widths, then runs its scenarios.
// Findings go in JSON files; app.py decides pass or fail, so one bad cell does not hide the rest.
// With job.session it instead opens the app once and takes steps one at a time from app.py, for a user test.
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

if (!job.session && !job.quick) {
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

if (!job.session) it('graph and reload', () => {
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

// ---- User test session: one fresh load, then steps from app.py one command file at a time.
// The tester sees what a person would: the screenshot, the text on screen and the controls in reach.
const REF = 'data-ut';
const visibleBox = (win, e) => {
  // MUI hides the real input of a switch or slider in a 1px box; its parent is what a person sees.
  let b = e.getBoundingClientRect();
  if ((b.width < 2 || b.height < 2) && e.parentElement) b = e.parentElement.getBoundingClientRect();
  return b;
};
const onScreen = (win, b) => b.width > 1 && b.height > 1 && b.bottom > 0 && b.right > 0 && b.top < win.innerHeight && b.left < win.innerWidth;
const textOf = (e) => (e?.textContent ?? '').replace(/\s+/g, ' ').trim();
const labelOf = (e) => {
  const doc = e.ownerDocument;
  if (e.getAttribute('aria-label')) return e.getAttribute('aria-label');
  const by = (e.getAttribute('aria-labelledby') ?? '').split(' ').filter((id) => id && id !== e.id).map((id) => textOf(doc.getElementById(id))).join(' ').trim();
  if (by) return by;
  if (e.id) { const l = doc.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) return textOf(l); }
  if (e.closest('label')) return textOf(e.closest('label'));
  for (let p = e.parentElement, i = 0; p && i < 4; p = p.parentElement, i += 1) {
    const l = p.querySelector('label');
    if (l) return textOf(l);
  }
  // A switch whose name sits beside it, in a box with nothing else to say.
  for (let p = e.parentElement, i = 0; p && i < 3; p = p.parentElement, i += 1) {
    const t = textOf(p);
    if (t && t.length <= 60) return t;
  }
  return e.getAttribute('placeholder') || e.getAttribute('title') || '';
};
// The field a button belongs to, such as the Bill box around a stepper's Increase button.
const fieldOf = (e) => {
  for (let p = e.parentElement, i = 0; p && i < 4; p = p.parentElement, i += 1) {
    const l = p.querySelector('label');
    if (l) return textOf(l);
  }
  return '';
};
const KINDS = [
  ['tab', '[role=tab]', (e) => (e.getAttribute('aria-selected') === 'true' ? 'selected' : '')],
  ['switch', 'input[type=checkbox], [role=switch], [role=checkbox]', (e) => ((e.checked ?? e.getAttribute('aria-checked') === 'true') ? 'on' : 'off')],
  ['slider', 'input[type=range], [role=slider]', (e) => `= ${e.value ?? e.getAttribute('aria-valuenow')} (${e.min ?? e.getAttribute('aria-valuemin')}..${e.max ?? e.getAttribute('aria-valuemax')})`],
  ['dropdown', '[role=combobox], select', (e) => `= "${e.tagName === 'SELECT' ? e.value : textOf(e)}"`],
  ['input', 'input:not([type=checkbox]):not([type=range]):not([type=radio]):not([type=hidden]), textarea', (e) => `= "${e.value.replace(/\n/g, '\\n')}"`],
  ['radio', 'input[type=radio], [role=radio]', (e) => ((e.checked ?? e.getAttribute('aria-checked') === 'true') ? 'chosen' : '')],
  ['button', 'button, [role=button]', () => ''],
  // In full: a person can long-press a link to copy it, so the tester may need all of it.
  ['link', 'a[href]', (e) => `-> ${e.getAttribute('href').slice(0, 1500)}`],
];
const describeScreen = (win, view) => {
  const doc = win.document;
  doc.querySelectorAll(`[${REF}]`).forEach((e) => e.removeAttribute(REF));
  if (view === 'graph') return { view, size: [win.innerWidth, win.innerHeight] };
  const dash = doc.querySelector(D);
  if (!dash) return { view, noPage: true };
  const found = [];
  KINDS.forEach(([kind, selector, state]) => {
    dash.querySelectorAll(selector).forEach((e) => {
      if (found.some((f) => f.e === e || f.e.contains(e) || e.contains(f.e))) return;
      if (e.closest('[aria-hidden=true]') || win.getComputedStyle(e).visibility === 'hidden') return;
      const box = visibleBox(win, e);
      if (!onScreen(win, box)) return;
      const named = kind === 'button' || kind === 'tab' || kind === 'link';
      found.push({ e, kind, state, box, label: (named ? (textOf(e) || labelOf(e)) : labelOf(e)).slice(0, 60), context: named ? fieldOf(e) : '' });
    });
  });
  // Reading order, and two "Increase" buttons become "Increase (Bill)" and "Increase (People)".
  found.sort((a, b) => Math.round(a.box.top) - Math.round(b.box.top) || a.box.left - b.box.left);
  const controls = found.map((f, i) => {
    const ref = `u${i + 1}`;
    f.e.setAttribute(REF, ref);
    const twin = found.filter((g) => g.label === f.label).length > 1 && f.context && f.context !== f.label;
    const disabled = f.e.disabled || f.e.getAttribute('aria-disabled') === 'true';
    return `${ref} ${f.kind} "${f.label}"${twin ? ` (${f.context.slice(0, 40)})` : ''} ${f.state(f.e)}${disabled ? ' disabled' : ''}`.trim();
  });
  const lines = [];
  dash.querySelectorAll('*').forEach((e) => {
    const own = [...e.childNodes].filter((c) => c.nodeType === 3).map((c) => c.textContent).join(' ').replace(/\s+/g, ' ').trim();
    if (!own || win.getComputedStyle(e).visibility === 'hidden' || !onScreen(win, e.getBoundingClientRect())) return;
    if (lines[lines.length - 1] !== own) lines.push(own);
  });
  const s = scroller(win);
  const scroll = { top: Math.round(s.scrollTop), max: Math.max(0, Math.round(s.scrollHeight - s.clientHeight)) };
  return { view, size: [win.innerWidth, win.innerHeight], text: lines.join(' · ').slice(0, 3000), controls, scroll };
};
const scroller = (win) => {
  const dash = win.document.querySelector(D);
  const scrolls = (e) => /auto|scroll/.test(win.getComputedStyle(e).overflowY) && e.scrollHeight > e.clientHeight + 1;
  for (let e = dash; e; e = e.parentElement) if (scrolls(e)) return e;
  const inner = dash && [...dash.querySelectorAll('*')].find((e) => scrolls(e) && e.clientHeight > win.innerHeight * 0.5);
  return inner ?? win.document.scrollingElement;
};
let view = 'app';
const SESSION_STEPS = {
  scroll: (r, s) => cy.window().then((win) => {
    const e = scroller(win);
    const to = { down: e.scrollTop + e.clientHeight * 0.8, up: e.scrollTop - e.clientHeight * 0.8, top: 0, bottom: e.scrollHeight }[s.scroll];
    if (to === undefined) r.failures.push('scroll takes "down", "up", "top" or "bottom"');
    else e.scrollTo({ top: to });
  }),
  // The graph as a person opening it would see it, fitted, or zoomed to the nodes whose name contains `node`.
  // It goes the way a person would. Phone: the logo opens the bottom bar, then Graph or UI.
  // Desktop: the logo leaves app view, then the page is hidden. The phone graph is view only.
  view: (r, s) => {
    view = s.view === 'app' ? 'app' : 'graph';
    const target = view === 'app' ? 'bottom-bar-ui' : 'bottom-bar-graph';
    cy.get('body').then(($b) => {
      // Commands only, no return value: Cypress refuses a value from a callback that queued commands.
      if ($b.find('[data-cy="bottom-bar"]').length) {
        if (!$b.find(`[data-cy="${target}"]`).length) cy.get('[data-cy="bottom-bar-toggle"]').click({ force: true });
        cy.get(`[data-cy="${target}"]`).click({ force: true });
      } else if (view === 'app') {
        ctl((c) => { c.toggleDashboard('OPEN'); });
        const enter = $b.find('[data-cy="toggle-app-button"]');
        if (enter.length) cy.wrap(enter.first()).click({ force: true });
      } else {
        const exit = $b.find('[data-cy="app-view-exit-button"]');
        if (exit.length) cy.wrap(exit.first()).click({ force: true });
        cy.wait(800);
        ctl((c) => { c.toggleDashboard('CLOSE'); });
      }
    });
    if (view === 'app') return cy.wait(800);
    cy.wait(1500);
    return ctl((c) => {
      const want = s.node && String(s.node).toLowerCase();
      const ids = want ? c.getNodes().filter((n) => n.name.toLowerCase().includes(want)).map((n) => n.id) : undefined;
      if (want && !ids.length) { r.failures.push(`no node named like "${s.node}"`); return; }
      c.zoomToFitNodesById(ids, want ? 2 : 1);
    });
  },
  // A missing selector would stall Cypress for a minute and end the session, so look first.
  click: (r, s) => cy.get(D).then(($d) => {
    const found = $d.find(s.click);
    if (!found.length) { r.failures.push(`nothing matches ${s.click} on screen`); return null; }
    return cy.wrap(found.first()).click({ force: true });
  }),
  keys: (r, s) => cy.get(D).then(($d) => {
    const found = $d.find(s.selector);
    if (!found.length) { r.failures.push(`nothing matches ${s.selector} on screen`); return null; }
    return cy.wrap(found.first()).focus().type(s.keys, { force: true });
  }),
  // As in verify, plus aria-labels and the names the screen gave, such as "Decrease (People)".
  press: (r, s) => cy.get(D).then(($d) => {
    const all = $d.find('button, [role=button], [role=tab]').toArray();
    const name = (e) => textOf(e) || e.getAttribute('aria-label') || '';
    let hits = all.filter((e) => name(e) === s.press || `${name(e)} (${fieldOf(e)})` === s.press);
    if (!hits.length) hits = $d.find(`[data-cy="button-${s.press}"]`).toArray();
    if (hits.length > 1) { r.failures.push(`${hits.length} buttons called "${s.press}": add the field in brackets, as the screen lists them, or click by ref`); return null; }
    if (!hits.length) { r.failures.push(`no button "${s.press}"`); return null; }
    return cy.wrap(hits[0]).click({ force: true });
  }),
  look: () => cy.then(() => null),
};
const snapshot = (n, r) => {
  cy.window().then((win) => { r.screen = describeScreen(win, view); });
  cy.screenshot(`session-${n}`, { capture: 'viewport', overwrite: true });
  ctl((c) => { r.problems = statuses(c); r.running = c.isLoadedAppRunning(); });
  cy.then(() => { r.logs = [...new Set(logs)]; r.requests = [...requests]; logs = []; requests = []; });
  cy.then(() => cy.writeFile(`${job.out}/state-${n}.json`, r));
};

if (job.session) {
  it('session', () => {
    const { viewport = [390, 844], theme, hash, stub, wait } = job.session;
    const positions = {};
    const first = { name: 'session', n: 0, failures: [], positions, pages: [] };
    openApp(theme, viewport[0], viewport[1], undefined, stub, hash);
    startApp(first, wait);
    snapshot(0, first);
    const loop = (n) => {
      cy.task('sessionNext', { dir: job.out, n }, { timeout: 2 * 60 * 60 * 1000, log: false }).then((cmd) => {
        if (cmd.stop) return;
        const r = { name: 'session', n, steps: cmd.steps, failures: [], positions, pages: [] };
        (cmd.steps ?? []).forEach((step) => {
          const kind = Object.keys(SESSION_STEPS).find((k) => k in step) ?? Object.keys(STEPS).find((k) => k in step);
          if (!kind) r.failures.push(`unknown step ${JSON.stringify(step)}`);
          else (SESSION_STEPS[kind] ?? STEPS[kind])(r, step);
        });
        cy.wait(cmd.settle ?? 1500);
        snapshot(n, r);
        loop(n + 1);
      });
    };
    loop(1);
  });
}
