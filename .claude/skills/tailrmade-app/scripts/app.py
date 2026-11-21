#!/usr/bin/env python3
"""Drives the real Tailrmade app through Cypress. Run tmapp.py for anything that needs no app.

  catalog OUTDIR                  save the in-app AI's rules, node catalogue and tool schemas
  ops JOB.json OUTDIR [--from F]  run MCP tool calls in order, save the result to OUTDIR/export.json
  export FILE OUT.json            load a file and save the migrated export
  verify FILE OUTDIR [--scenarios S.json] [--tag T] [--quick | --only NAME,...] [--timeout MIN]
  session start FILE DIR [--viewport 390x844] [--theme T] [--hash H] [--stub S.json]
  session do DIR STEP...          take steps in the open app and print what is on screen
  session stop DIR                close Chrome
  server start|status|stop [--all]  this session's own dev server (started on demand anyway)

Exit codes: 0 pass, 1 fail, 3 no dev server (UNVERIFIED), 4 stalled (Cypress stopped making progress).

Each Claude session gets its own webpack dev server on a free port, started on first use and
reused after that, so parallel sessions never share one. Servers whose Claude process has
exited, or that sat idle for TM_SERVER_IDLE_HOURS (default 3), are stopped by the next run.
Set TM_BASE_URL to use a server you started yourself instead, such as `yarn dev` on :8080.
"""
import argparse
import glob
import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
import tmapp  # noqa: E402

HERE = Path(__file__).resolve().parent


def find_app_repo():
    # The skill lives in tailrmade-library; Cypress and the dev server come from the app repo.
    # Set TM_APP_REPO, or keep the app checked out next to the library as ../tailrmade.
    if os.environ.get('TM_APP_REPO'):
        return Path(os.environ['TM_APP_REPO']).expanduser().resolve()
    home = HERE.parents[3]
    for repo in (home, home.parent / 'tailrmade'):
        if (repo / 'node_modules/.bin/cypress').exists():
            return repo
    return home.parent / 'tailrmade'


REPO = find_app_repo()
BASE = os.environ.get('TM_BASE_URL')  # None: use this session's own server, see ensure_server
BASE_IS_EXTERNAL = BASE is not None
SERVERS = Path(os.environ.get('TM_SERVER_HOME', Path.home() / '.cache/tailrmade-app/servers'))
SERVER_KEY = os.environ.get('TM_SERVER_KEY') or os.environ.get('CLAUDE_CODE_SESSION_ID') or 'default'
IDLE_HOURS = float(os.environ.get('TM_SERVER_IDLE_HOURS', '3'))
THEMES = [
    {'name': 'tailrmade-dark', 'theme': {'mode': 'dark'}},
    {'name': 'newsprint-light', 'theme': {'presetId': 'newsprint', 'mode': 'light'}},
    {'name': 'neon-dark', 'theme': {'presetId': 'neon', 'mode': 'dark'}},
]
# Known app noise, unrelated to the file under test. Anything else in the console counts.
LOG_NOISE = ('main.js:', 'PixiJS Warning', 'clipboard', 'HMR', 'is not a standard HTML/SVG', 'Cannot update a component', 'first-child', 'ReactDOM', 'preset', 'MUI:', 'findDOMNode', 'deprecat', 'Download the React', 'WebGL', 'GL Driver', 'GPU stall', 'Failed to load resource: the server responded with a status of 404')
SHARED_SERVER_ERRORS = ('graphConfiguredAndReady', "testController", 'Timed out retrying')


# ---- Processes. Everything app.py starts runs in its own process group, so it can be stopped
# whole: a killed run used to leave Cypress and Chrome behind, loading the dev server for hours.

def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def descendants(pid):
    rows = subprocess.run(['ps', '-A', '-o', 'pid=,ppid='], capture_output=True, text=True).stdout.split('\n')
    kids = {}
    for row in rows:
        parts = row.split()
        if len(parts) == 2:
            kids.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = [], [int(pid)]
    while todo:
        for k in kids.get(todo.pop(), []):
            found.append(k)
            todo.append(k)
    return found


def stop_tree(pid, grace=10):
    """Stops a process, its group and every descendant, even ones that left the group."""
    pids = [int(pid)] + descendants(pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(int(pid), sig)
        except OSError:
            pass
        for p in pids:
            try:
                os.kill(p, sig)
            except OSError:
                pass
        deadline = time.time() + grace
        while time.time() < deadline and any(pid_alive(p) for p in pids):
            time.sleep(0.3)
        if not any(pid_alive(p) for p in pids):
            return


RUNNING = []  # Cypress runs to stop if app.py itself is stopped


def stop_running(*_):
    while RUNNING:
        stop_tree(RUNNING.pop().pid, grace=3)


def on_signal(signum, _frame):
    stop_running()
    sys.exit(128 + signum)


atexit.register(stop_running)
for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(_sig, on_signal)


# ---- Dev server: one per Claude session. Several sessions on one server stalled each other's
# Cypress runs for up to hours, so each gets its own, keyed by CLAUDE_CODE_SESSION_ID.

def server_dir(key=SERVER_KEY):
    return SERVERS / key


def server_info(sd):
    try:
        return json.loads((sd / 'server.json').read_text())
    except (OSError, json.JSONDecodeError):
        return None


def responds(url, timeout=5):
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except OSError:
        return False


def stop_server(sd, why):
    info = server_info(sd)
    if info and pid_alive(info['pid']):
        stop_tree(info['pid'])
    print(f'Stopped dev server {sd.name} on port {info["port"] if info else "?"}: {why}.')
    shutil.rmtree(sd, ignore_errors=True)


def reap_servers():
    """Stops servers whose Claude process has exited or that sat idle too long."""
    if not SERVERS.exists():
        return
    for sd in SERVERS.iterdir():
        info = server_info(sd)
        if not info:
            continue
        if not pid_alive(info['pid']):
            shutil.rmtree(sd, ignore_errors=True)
        elif sd.name != SERVER_KEY and info.get('owner') and not pid_alive(info['owner']):
            stop_server(sd, 'its Claude session has ended')
        elif time.time() - (sd / 'last_used').stat().st_mtime > IDLE_HOURS * 3600:
            stop_server(sd, f'idle for over {IDLE_HOURS:g} hours')


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def start_server(sd):
    sd.mkdir(parents=True, exist_ok=True)
    port = free_port()
    server_js = REPO / 'node_modules/webpack-dev-server/bin/webpack-dev-server.js'
    ts_node = REPO / 'node_modules/.bin/ts-node'
    if not server_js.exists() or not ts_node.exists():
        return None, f'{REPO} has no webpack-dev-server or ts-node; run `yarn` there first'
    # As `yarn dev`, but without live reload, so an edit in the app repo can't reload the page in
    # the middle of a test. Not FAST_BUILD: its eval source maps change the console lines verify filters.
    cmd = [str(ts_node), '-P', 'tsconfig.webpack.json', str(server_js), '--mode', 'development', '--env', 'development',
           '--host', '127.0.0.1', '--port', str(port), '--no-hot', '--no-live-reload', '--no-open']
    env = {**os.environ, 'CLOUD_MODE': 'false'}
    log = open(sd / 'server.log', 'w')
    proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    info = {'pid': proc.pid, 'port': port, 'url': f'http://127.0.0.1:{port}', 'owner': os.environ.get('CLAUDE_PID'), 'started': time.strftime('%H:%M:%S')}
    (sd / 'server.json').write_text(json.dumps(info))
    (sd / 'last_used').touch()
    print(f'Starting this session\'s own dev server on port {port} (log: {sd / "server.log"}). The first build takes a few minutes...', flush=True)
    started = time.time()
    while time.time() - started < 900:
        if proc.poll() is not None:
            tail_log = (sd / 'server.log').read_text()[-1500:]
            shutil.rmtree(sd, ignore_errors=True)
            return None, f'the dev server exited with {proc.returncode}:\n{tail_log}'
        # The dev server holds requests until the first bundle is built, so this returns when it is ready.
        if responds(info['url'], timeout=20):
            print(f'Dev server ready at {info["url"]} after {int(time.time() - started)}s.', flush=True)
            return info, None
        time.sleep(2)
    stop_tree(proc.pid)
    shutil.rmtree(sd, ignore_errors=True)
    return None, 'the dev server did not answer within 15 minutes'


def ensure_server(required=True):
    """Returns the base URL to test against, starting this session's server if needed."""
    global BASE
    if BASE:
        if responds(BASE):
            return BASE
        problem = f'nothing answers at TM_BASE_URL={BASE}'
    else:
        reap_servers()
        sd = server_dir()
        info = server_info(sd)
        if info and pid_alive(info['pid']) and responds(info['url'], timeout=20):
            (sd / 'last_used').touch()
            BASE = info['url']
            return BASE
        if info:
            stop_server(sd, 'it no longer answered')
        info, problem = start_server(sd)
        if info:
            BASE = info['url']
            return BASE
    if required:
        print(f'UNVERIFIED: no dev server ({problem}). Nothing was run in the app.')
        sys.exit(3)
    print(f'\nUNVERIFIED: static checks only. No dev server ({problem}), so nothing was run in the app.')
    return None


def server_cmd(action, all_):
    if action == 'start':
        print(f'Dev server for session {SERVER_KEY}: {ensure_server()}')
    elif action == 'status':
        reap_servers()
        rows = [(sd, server_info(sd)) for sd in sorted(SERVERS.iterdir())] if SERVERS.exists() else []
        if not rows:
            print('No dev servers started by app.py are running.')
        for sd, info in rows:
            if info:
                idle = int((time.time() - (sd / 'last_used').stat().st_mtime) / 60)
                print(f'{"* " if sd.name == SERVER_KEY else "  "}{sd.name}: {info["url"]} pid {info["pid"]}, started {info["started"]}, idle {idle} min')
    else:
        targets = [sd for sd in SERVERS.iterdir()] if all_ and SERVERS.exists() else [server_dir()]
        for sd in targets:
            if server_info(sd):
                stop_server(sd, 'asked to')
            elif not all_:
                print(f'No dev server for session {SERVER_KEY}.')


def repo_state():
    run = lambda *a: subprocess.run(['git', *a], cwd=REPO, capture_output=True, text=True).stdout.strip()
    changed = [l for l in run('status', '--short').splitlines() if '.claude/' not in l]
    return {'branch': run('branch', '--show-current'), 'uncommitted_files': len(changed)}


def cypress_command(spec, out, job_file=None, job_inline=None):
    env = {k: v for k, v in os.environ.items() if k != 'ELECTRON_RUN_AS_NODE'}
    env.update(TM_OUT=str(out), TM_SPEC=spec, TM_BASE_URL=BASE, TM_JOB=str(job_file or ''), TM_JOB_INLINE=str(job_inline or ''))
    cmd = [str(REPO / 'node_modules/.bin/cypress'), 'run', '--project', '.', '--config-file', str(HERE / 'cypress/config.js'), '--browser', 'chrome', '--spec', str(HERE / f'cypress/{spec}.cy.js')]
    return cmd, env


STALLED = 124


def cypress(spec, out, job_file=None, job_inline=None, progress=None, stall=300, limit=None):
    """Runs Cypress with its output in OUT/cypress.log. `progress()` returns lines to print as
    work finishes. With no new progress and no new output for `stall` seconds, or past `limit`
    seconds in all, the run is stopped and the code is STALLED."""
    cmd, env = cypress_command(spec, out, job_file, job_inline)
    log_path = Path(out) / f'cypress-{spec}.log'
    with open(log_path, 'w') as log:
        proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    RUNNING.append(proc)
    started = last = time.time()
    size = 0
    reason = None
    while proc.poll() is None:
        time.sleep(2)
        now = time.time()
        lines = progress() if progress else []
        for line in lines:
            print(line, flush=True)
        new_size = log_path.stat().st_size
        if lines or new_size != size:
            last, size = now, new_size
        if not BASE_IS_EXTERNAL and (server_dir() / 'last_used').exists():
            (server_dir() / 'last_used').touch()
        if now - last > stall:
            reason = f'no progress for {stall}s'
        elif limit and now - started > limit:
            reason = f'over the {int(limit / 60)} minute limit'
        if reason:
            print(f'STALLED: {reason}; stopping Cypress.', flush=True)
            stop_tree(proc.pid)
            break
    if proc in RUNNING:
        RUNNING.remove(proc)
    output = log_path.read_text(errors='replace')
    if reason:
        return STALLED, output + f'\nSTALLED: {reason}'
    return proc.returncode, output


def tail(output, size=25):
    keep = [l for l in output.splitlines() if any(k in l for k in ('passing', 'failing', 'rror', '✓')) or l.strip().startswith(tuple('123456789'))]
    return '\n'.join(keep[:size])


def run_ops(ops, out, source=None, **extra):
    ensure_server()
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    job = {'out': str(out), 'ops': ops, **extra}
    if source:
        job['from'] = str(Path(source).resolve())
    job_file = out / 'job.json'
    job_file.write_text(json.dumps(job, ensure_ascii=False))
    code, output = cypress('ops', out, job_file=job_file, limit=15 * 60)
    if code == STALLED:
        print(output[-1500:])
        sys.exit(4)
    if code:
        print(tail(output))
        sys.exit(1)
    results = json.loads((out / 'results.json').read_text())
    failed = [r for r in results if r['is_error']]
    for r in failed:
        print(f'TOOL ERROR at op {r["index"]} {r["tool"]} {json.dumps(r["input"])[:200]}: {str(r["content"])[:400]}')
    if len(results) != len(ops):
        print(f'stopped after {len(results)} of {len(ops)} ops')
    print(f'{len(results)} ops, {len(failed)} errors -> {out / "export.json"}')
    problems = json.loads((out / 'problems.json').read_text())
    print('app warnings and errors:', str(problems.get('content'))[:800])
    if failed or len(results) != len(ops):
        sys.exit(1)


def expected_cells(scenarios, quick, only):
    if only:
        return [f'scenario-{s["name"]}' for s in scenarios]
    cells = [] if quick else [f'{t["name"]}-{w}' for t in THEMES for w in ('desktop', 'phone')]
    return cells + [f'scenario-{s["name"]}' for s in scenarios] + ['graph']


def progress_reporter(res, cells):
    seen, started = set(), time.time()

    def report():
        lines = []
        for path in sorted(res.glob('*.json'), key=lambda p: p.stat().st_mtime):
            name = path.stem
            if name in seen or name not in cells:
                continue
            seen.add(name)
            lines.append(f'  done {len(seen)}/{len(cells)}: {name} ({int(time.time() - started)}s)')
        return lines
    return report


def verify(file, out, scenarios_file, tag, quick, only, timeout_min):
    out = Path(out).resolve()
    res = out / 'res'
    if res.exists():
        shutil.rmtree(res)
    res.mkdir(parents=True)
    data = tmapp.read_app(file)
    errors, warnings = tmapp.check(data)
    report = {'file': str(file), 'static': {'errors': errors, 'warnings': warnings}, 'repo': repo_state()}
    print('== Static checks')
    for w in warnings:
        print('  warning:', w)
    for e in errors:
        print('  ERROR:', e)
    print(f'  {len(errors)} errors, {len(warnings)} warnings', flush=True)
    if not ensure_server(required=False):
        print(f'To finish, start a dev server (`yarn dev` in {REPO}, then set TM_BASE_URL) or fix the problem above, then run this again.')
        (out / 'report.json').write_text(json.dumps({**report, 'verdict': 'UNVERIFIED'}, indent=2, ensure_ascii=False))
        sys.exit(3)
    report['server'] = BASE
    scenarios = json.loads(Path(scenarios_file).read_text()) if scenarios_file else {}
    chosen = scenarios.get('scenarios', [])
    if only:
        names = [n.strip() for n in only.split(',') if n.strip()]
        missing = [n for n in names if n not in {s['name'] for s in chosen}]
        if missing:
            print(f'--only: no scenario called {", ".join(missing)}. There are: {", ".join(s["name"] for s in chosen)}')
            sys.exit(2)
        chosen = [s for s in chosen if s['name'] in names]
    partial = bool(quick or only)
    report['partial'] = 'only ' + only if only else ('quick: no theme and width matrix' if quick else False)
    cells = expected_cells(chosen, quick, only)
    job = {'text': json.dumps(data, ensure_ascii=False), 'out': str(out), 'tag': tag, 'themes': THEMES, 'quick': partial, 'skip_graph': bool(only), 'scenarios': chosen}
    job_file = out / 'verify-job.json'
    job_file.write_text(json.dumps(job, ensure_ascii=False))
    limit = (timeout_min or max(10, 3 * len(cells))) * 60
    print(f'\n== Running {len(cells)} cells in the app at {BASE} (stops if stuck for 5 min, or after {int(limit / 60)} min)', flush=True)
    code, output = cypress('verify', out, job_inline=job_file, progress=progress_reporter(res, cells), limit=limit)
    report['cypress_exit'] = code
    if code and code != STALLED and any(k in output for k in SHARED_SERVER_ERRORS):
        # A load can still fail while the server is busy rebuilding. Say so, and try once more.
        first = tail(output)
        report['rerun_after'] = first
        print(f'\nNOTE: the app failed to load ({report["repo"]}):\n{first}\nRunning once more.', flush=True)
        shutil.rmtree(res)
        res.mkdir()
        code, output = cypress('verify', out, job_inline=job_file, progress=progress_reporter(res, cells), limit=limit)
        report['cypress_exit'] = code
    failures = judge(report, res, data, scenarios, cells)
    if code == STALLED:
        report['stalled'] = output.rsplit('STALLED: ', 1)[-1]
    elif code and not failures:
        failures.append(f'Cypress exited with {code}:\n{tail(output)}')
    report['failures'] = failures
    report['verdict'] = 'STALLED' if code == STALLED else ('FAIL' if failures or errors else 'PASS')
    (out / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f'\n== Result: {report["verdict"]}' + (f' (partial run, {report["partial"]}; run the full verify before reporting PASS)' if partial else ''))
    if code == STALLED:
        print(f'  Cypress stopped making progress ({report["stalled"]}). The cells below that finished are real results;')
        print(f'  the rest did not run. The log is {out / "cypress-verify.log"}.')
    for e in errors:
        print('  FAIL: static check:', e)
    for f in failures:
        print('  FAIL:', f)
    shots = sorted(glob.glob(str(out / 'shots/**/*.png'), recursive=True))
    print(f'\n{len(shots)} screenshots in {out / "shots"}. Tests miss clipped numbers and invisible highlights, so look at them.')
    sys.exit({'PASS': 0, 'FAIL': 1, 'STALLED': 4}[report['verdict']])


def judge(report, res, data, scenarios, cells):
    failures = []
    expected_risks = scenarios.get('expect_risks')
    allowed_logs = scenarios.get('allow_logs', [])
    expected_cells = cells
    rows = {}
    paused_notes = []
    for name in expected_cells:
        path = res / f'{name}.json'
        if not path.exists():
            failures.append(f'{name}: did not finish, see the failure screenshot')
            continue
        r = json.loads(path.read_text())
        rows[name] = r
        allowed_problems = r.get('allowProblems') or []
        for p in r.get('problems') or []:
            if p.get('node') not in allowed_problems:
                failures.append(f'{name}: node problem after start: {p.get("node")} {p.get("sock") or ""} {p.get("msg")}')
        if r['kind'] != 'graph':
            for p in r.get('problemsOnLoad') or []:
                if p.get('node') in allowed_problems:
                    continue
                text = f'{p.get("node")} {p.get("sock") or ""} {p.get("msg")}'
                if r.get('pausedOnLoad'):
                    # Paused behind the review, nothing has run yet; what counts is the state after Run.
                    paused_notes.append(text)
                else:
                    failures.append(f'{name}: node problem on load: {text}')
        logs = [l for l in r.get('logs') or [] if not any(n in l for n in LOG_NOISE) and not any(a in l for a in allowed_logs + (r.get('allowLogs') or []))]
        for l in logs[:5]:
            failures.append(f'{name}: console: {l[:220]}')
        for fail in r.get('failures') or []:
            failures.append(f'{name}: {fail}')
        expected_nodes = len(tmapp.graph_of(data).get('nodes', []))
        if r.get('nodeCount') is not None and r['nodeCount'] != expected_nodes:
            failures.append(f'{name}: {r["nodeCount"]} of {expected_nodes} nodes loaded')
        pages = r.get('pages') or ([r] if r['kind'] == 'matrix' else [])
        for page in pages:
            at = f'{name}{"@" + page["at"] if "at" in page else ""}'
            if page.get('noPage'):
                failures.append(f'{at}: page is not on screen')
                continue
            if page.get('placeholderPage'):
                failures.append(f'{at}: the app shows its empty placeholder, not this page')
            if page.get('docOverflowX', 0) > 0:
                failures.append(f'{at}: page scrolls sideways by {page["docOverflowX"]}px')
            for key, what in (('overflowing', 'wider than the page'), ('sidewaysScroll', 'sideways scroll'), ('clipped', 'clipped'), ('lowContrast', 'low contrast'), ('literalMarkup', 'raw markup on the page'), ('junk', 'junk text on the page'), ('brokenImages', 'image failed')):
                if page.get(key):
                    failures.append(f'{at}: {what}: {page[key][:4]}')
    risks = sorted({f'{x["severity"]}/{x["kind"]}/{x["node"]}' for r in rows.values() for x in r.get('risks') or []})
    report['risks'] = risks
    print('\n== Risks the review will show')
    print('  ' + ('\n  '.join(risks) if risks else 'none'))
    if expected_risks is not None and sorted(expected_risks) != risks:
        failures.append(f'risks differ from expect_risks: unexpected {sorted(set(risks) - set(expected_risks))}, missing {sorted(set(expected_risks) - set(risks))}')
    paused_notes = sorted(set(paused_notes))
    report['shown_while_paused'] = paused_notes
    if paused_notes:
        print('\n== Shown while the app waits behind the review (not failures, but a person sees them before pressing Run)')
        print('  ' + '\n  '.join(paused_notes[:8]))
    first, second = res / 'export-1.json', res / 'export-2.json'
    if 'graph' not in expected_cells:
        pass
    elif first.exists() and second.exists():
        changes = tmapp.diff(tmapp.read_app(first), tmapp.read_app(second))
        print(f'\n== Export and reload: {"identical" if not changes else str(len(changes)) + " changes"}')
        for c in changes[:8]:
            failures.append(f'export and reload differ: {c}')
        changes = tmapp.diff(data, tmapp.read_app(first), ignore_layout=True)
        report['file_vs_export'] = changes
        print(f'== File against its first export, ignoring sizes: {len(changes)} changes')
        for c in changes[:6]:
            print('  ', c)
    else:
        failures.append('export and reload did not finish')
    print('\n== Cells')
    for name, r in rows.items():
        page = r if r['kind'] == 'matrix' else None
        print(f'  {name}: requests={len(r.get("requests") or [])}' + (f' width={page.get("pageWidth")} height={page.get("pageHeight")} tight={len(page.get("tightLines") or [])}' if page else ''))
    return failures


# ---- User test sessions: Chrome stays open on one fresh load and takes steps one command at a time.
# The files live in DIR/session: cmd-N.json from here, state-N.json and shots/**/session-N.png from Cypress.

def session_dir(d):
    return Path(d).resolve() / 'session'


def session_alive(sd):
    try:
        os.kill(int((sd / 'pid').read_text()), 0)
        return True
    except (OSError, ValueError):
        return False


def wait_state(sd, n, timeout):
    path = sd / f'state-{n}.json'
    started = time.time()
    while time.time() - started < timeout:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                pass  # still being written
        if not session_alive(sd):
            log = (sd / 'cypress.log').read_text() if (sd / 'cypress.log').exists() else ''
            print(f'SESSION ENDED: Chrome is no longer running.\n{tail(log)}')
            sys.exit(1)
        time.sleep(0.3)
    print(f'TIMEOUT: no screen after {timeout}s. The session is still open; try `session do {sd.parent} \'{{"look": true}}\'` or stop it.')
    sys.exit(1)


def print_state(sd, state):
    n = state['n']
    shots = sorted(glob.glob(str(sd / f'shots/**/session-{n}.png'), recursive=True))
    screen = state.get('screen') or {}
    print(f'== Screen {n}' + (f' after {json.dumps(state["steps"], ensure_ascii=False)}' if state.get('steps') else ' (just opened)'))
    for f in state.get('failures') or []:
        print(f'  could not: {f}')
    print(f'  screenshot: {shots[-1] if shots else "missing"}')
    if screen.get('view') == 'graph':
        print(f'  view: graph, {screen["size"][0]}x{screen["size"][1]}. Read the screenshot; `{{"view": "app"}}` goes back.')
        return
    if screen.get('noPage'):
        print('  view: app, but no page is on screen')
        return
    sc = screen.get('scroll') or {}
    more = f', scrolled {sc["top"]} of {sc["max"]}px' + (' (more below)' if sc['top'] < sc['max'] - 4 else '') if sc.get('max') else ''
    print(f'  view: app, {screen["size"][0]}x{screen["size"][1]}{more}')
    print(f'  text on screen: {screen.get("text") or "(none)"}')
    print('  controls on screen:' + ('' if screen.get('controls') else ' none'))
    for c in screen.get('controls') or []:
        print(f'    {c}')


def session_start(file, d, viewport, theme, hash_, stub_file, wait):
    ensure_server()
    sd = session_dir(d)
    if sd.exists() and session_alive(sd):
        print(f'A session is already open in {sd}. Stop it first: app.py session stop {d}')
        sys.exit(1)
    if sd.exists():
        shutil.rmtree(sd)
    sd.mkdir(parents=True)
    data = tmapp.read_app(file)
    themes = {t['name']: t['theme'] for t in THEMES}
    if theme not in themes:
        print(f'--theme takes one of {", ".join(themes)}')
        sys.exit(2)
    w, h = (int(x) for x in viewport.lower().split('x'))
    stub = json.loads(Path(stub_file).read_text()) if stub_file else []
    job = {'text': json.dumps(data, ensure_ascii=False), 'out': str(sd), 'tag': 'session', 'session': {'viewport': [w, h], 'theme': themes[theme], 'hash': hash_, 'stub': stub, 'wait': wait}}
    job_file = sd / 'job.json'
    job_file.write_text(json.dumps(job, ensure_ascii=False))
    cmd, env = cypress_command('verify', sd, job_inline=job_file)
    log = open(sd / 'cypress.log', 'w')
    proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (sd / 'pid').write_text(str(proc.pid))
    (sd / 'next').write_text('1')
    print(f'Opening {Path(file).name} at {w}x{h} in {theme} (repo {repo_state()})...')
    print_state(sd, wait_state(sd, 0, 300))


def session_do(d, steps_json, settle):
    sd = session_dir(d)
    if not session_alive(sd):
        print(f'No open session in {sd}. Start one with `app.py session start FILE {d}`.')
        sys.exit(1)
    if not BASE_IS_EXTERNAL and (server_dir() / 'last_used').exists():
        (server_dir() / 'last_used').touch()
    steps = []
    for text in steps_json:
        value = json.loads(text)
        steps += value if isinstance(value, list) else [value]
    n = int((sd / 'next').read_text())
    tmp = sd / f'cmd-{n}.tmp'
    tmp.write_text(json.dumps({'steps': steps, 'settle': settle}, ensure_ascii=False))
    tmp.rename(sd / f'cmd-{n}.json')
    (sd / 'next').write_text(str(n + 1))
    print_state(sd, wait_state(sd, n, 180))


def session_stop(d):
    sd = session_dir(d)
    if session_alive(sd):
        n = int((sd / 'next').read_text())
        (sd / f'cmd-{n}.json').write_text('{"stop": true}')
        pid = int((sd / 'pid').read_text())
        for _ in range(60):
            if not session_alive(sd):
                break
            time.sleep(1)
        else:
            stop_tree(pid)
    states = sorted(sd.glob('state-*.json'), key=lambda p: int(p.stem.split('-')[1]))
    print(f'Session closed after {max(len(states) - 1, 0)} commands. States and screenshots are in {sd}.')
    for p in states:
        s = json.loads(p.read_text())
        notes = [f'{len(s.get("problems") or [])} node problems' if s.get('problems') else '', f'{len(s.get("logs") or [])} console lines' if s.get('logs') else '', f'{len(s.get("requests") or [])} requests' if s.get('requests') else '']
        notes = ', '.join(x for x in notes if x)
        if notes:
            print(f'  screen {s["n"]}: {notes}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('catalog'); c.add_argument('out')
    c = sub.add_parser('ops'); c.add_argument('job'); c.add_argument('out'); c.add_argument('--from', dest='source')
    c = sub.add_parser('export'); c.add_argument('file'); c.add_argument('out')
    c = sub.add_parser('verify'); c.add_argument('file'); c.add_argument('out'); c.add_argument('--scenarios'); c.add_argument('--tag', default='app')
    c.add_argument('--quick', action='store_true', help='skip the theme and width matrix: scenarios and export only')
    c.add_argument('--only', help='comma-separated scenario names: run just those, no matrix and no export')
    c.add_argument('--timeout', type=int, help='minutes before the run is stopped (default 3 per cell, at least 10)')
    c = sub.add_parser('server'); c.add_argument('action', choices=['start', 'status', 'stop']); c.add_argument('--all', action='store_true', help='with stop: every server app.py started')
    c = sub.add_parser('session'); ss = c.add_subparsers(dest='action', required=True)
    c = ss.add_parser('start'); c.add_argument('file'); c.add_argument('dir'); c.add_argument('--viewport', default='390x844'); c.add_argument('--theme', default='tailrmade-dark'); c.add_argument('--hash'); c.add_argument('--stub', help='JSON file with a list of stubs, as in verify'); c.add_argument('--wait', type=int, default=6000)
    c = ss.add_parser('do'); c.add_argument('dir'); c.add_argument('steps', nargs='+', help='one or more steps as JSON, as in verify'); c.add_argument('--settle', type=int, default=1500, help='ms to wait after the steps')
    c = ss.add_parser('stop'); c.add_argument('dir')
    a = p.parse_args()
    if a.cmd == 'server':
        server_cmd(a.action, a.all)
        return
    if a.cmd == 'session':
        if a.action == 'start':
            session_start(a.file, a.dir, a.viewport, a.theme, a.hash, a.stub, a.wait)
        elif a.action == 'do':
            session_do(a.dir, a.steps, a.settle)
        else:
            session_stop(a.dir)
        return
    if a.cmd == 'catalog':
        extra = "const tools = await c.getAIToolDefinitions(); const nodes = JSON.parse((await c.callMCPTool('list_available_nodes', {})).content); return { prompt: await c.getAISystemPrompt(), tools, nodes };"
        run_ops([], a.out, extra=extra)
        data = json.loads((Path(a.out) / 'extra.json').read_text())
        (Path(a.out) / 'prompt.md').write_text(data['prompt'])
        (Path(a.out) / 'tools.json').write_text(json.dumps(data['tools'], indent=1))
        (Path(a.out) / 'nodes.json').write_text(json.dumps(data['nodes'], indent=1))
        print(f'saved prompt.md, tools.json and nodes.json to {a.out}')
    elif a.cmd == 'ops':
        job = json.loads(Path(a.job).read_text())
        ops, extra = (job, {}) if isinstance(job, list) else (job.pop('ops'), job)
        run_ops(ops, a.out, a.source, **extra)
    elif a.cmd == 'export':
        with tempfile.TemporaryDirectory() as d:
            run_ops([], d, a.file)
            shutil.copy(Path(d) / 'export.json', a.out)
        print(f'migrated export -> {a.out}')
    else:
        verify(a.file, a.out, a.scenarios, a.tag, a.quick, a.only, a.timeout)


if __name__ == '__main__':
    main()
