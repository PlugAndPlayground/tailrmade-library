#!/usr/bin/env python3
"""Drives the real Tailrmade app through Cypress. Run tmapp.py for anything that needs no app.

  catalog OUTDIR                  save the in-app AI's rules, node catalogue and tool schemas
  ops JOB.json OUTDIR [--from F]  run MCP tool calls in order, save the result to OUTDIR/export.json
  export FILE OUT.json            load a file and save the migrated export
  verify FILE OUTDIR [--scenarios S.json] [--tag T] [--quick]

Exit codes: 0 pass, 1 fail, 3 no dev server, so the result is UNVERIFIED.
Set TM_BASE_URL to use another dev server than http://127.0.0.1:8080.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
BASE = os.environ.get('TM_BASE_URL', 'http://127.0.0.1:8080')
THEMES = [
    {'name': 'tailrmade-dark', 'theme': {'mode': 'dark'}},
    {'name': 'newsprint-light', 'theme': {'presetId': 'newsprint', 'mode': 'light'}},
    {'name': 'neon-dark', 'theme': {'presetId': 'neon', 'mode': 'dark'}},
]
# Known app noise, unrelated to the file under test. Anything else in the console counts.
LOG_NOISE = ('main.js:', 'PixiJS Warning', 'clipboard', 'HMR', 'is not a standard HTML/SVG', 'Cannot update a component', 'first-child', 'ReactDOM', 'preset', 'MUI:', 'findDOMNode', 'deprecat', 'Download the React', 'WebGL', 'GL Driver', 'GPU stall', 'Failed to load resource: the server responded with a status of 404')
SHARED_SERVER_ERRORS = ('graphConfiguredAndReady', "testController", 'Timed out retrying')


def require_server():
    try:
        urllib.request.urlopen(BASE, timeout=5)
    except OSError as e:
        print(f'UNVERIFIED: no dev server at {BASE} ({e}). Start one with `yarn dev` in {REPO}, or set TM_BASE_URL.')
        sys.exit(3)


def repo_state():
    run = lambda *a: subprocess.run(['git', *a], cwd=REPO, capture_output=True, text=True).stdout.strip()
    changed = [l for l in run('status', '--short').splitlines() if '.claude/' not in l]
    return {'branch': run('branch', '--show-current'), 'uncommitted_files': len(changed)}


def cypress(spec, out, job_file=None, job_inline=None):
    env = {k: v for k, v in os.environ.items() if k != 'ELECTRON_RUN_AS_NODE'}
    env.update(TM_OUT=str(out), TM_SPEC=spec, TM_BASE_URL=BASE, TM_JOB=str(job_file or ''), TM_JOB_INLINE=str(job_inline or ''))
    cmd = [str(REPO / 'node_modules/.bin/cypress'), 'run', '--project', '.', '--config-file', str(HERE / 'cypress/config.js'), '--browser', 'chrome', '--spec', str(HERE / f'cypress/{spec}.cy.js')]
    r = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def tail(output, size=25):
    keep = [l for l in output.splitlines() if any(k in l for k in ('passing', 'failing', 'rror', '✓')) or l.strip().startswith(tuple('123456789'))]
    return '\n'.join(keep[:size])


def run_ops(ops, out, source=None, **extra):
    require_server()
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    job = {'out': str(out), 'ops': ops, **extra}
    if source:
        job['from'] = str(Path(source).resolve())
    job_file = out / 'job.json'
    job_file.write_text(json.dumps(job, ensure_ascii=False))
    code, output = cypress('ops', out, job_file=job_file)
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


def verify(file, out, scenarios_file, tag, quick):
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
    print(f'  {len(errors)} errors, {len(warnings)} warnings')
    try:
        urllib.request.urlopen(BASE, timeout=5)
    except OSError:
        print(f'\nUNVERIFIED: static checks only. No dev server at {BASE}, so nothing was run in the app.')
        print(f'For full verification run `yarn dev` in {REPO}, then run this again.')
        (out / 'report.json').write_text(json.dumps({**report, 'verdict': 'UNVERIFIED'}, indent=2, ensure_ascii=False))
        sys.exit(3)
    scenarios = json.loads(Path(scenarios_file).read_text()) if scenarios_file else {}
    job = {'text': json.dumps(data, ensure_ascii=False), 'out': str(out), 'tag': tag, 'themes': THEMES, 'quick': quick, 'scenarios': scenarios.get('scenarios', [])}
    job_file = out / 'verify-job.json'
    job_file.write_text(json.dumps(job, ensure_ascii=False))
    code, output = cypress('verify', out, job_inline=job_file)
    report['cypress_exit'] = code
    if code and any(k in output for k in SHARED_SERVER_ERRORS):
        # Another session on the shared dev server can break a load. Say so, and try once more.
        first = tail(output)
        report['rerun_after'] = first
        print(f'\nNOTE: load failure that can come from another session on the dev server ({report["repo"]}):\n{first}\nRunning once more.')
        code, output = cypress('verify', out, job_inline=job_file)
        report['cypress_exit'] = code
    failures = judge(report, res, data, scenarios, tag, quick, out)
    if code and not failures:
        failures.append(f'Cypress exited with {code}:\n{tail(output)}')
    report['failures'] = failures
    report['verdict'] = 'FAIL' if failures or errors else 'PASS'
    (out / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f'\n== Result: {report["verdict"]}')
    for f in failures:
        print('  FAIL:', f)
    shots = sorted(glob.glob(str(out / 'shots/**/*.png'), recursive=True))
    print(f'\n{len(shots)} screenshots in {out / "shots"}. Tests miss clipped numbers and invisible highlights, so look at them.')
    sys.exit(0 if report['verdict'] == 'PASS' else 1)


def judge(report, res, data, scenarios, tag, quick, out):
    failures = []
    expected_risks = scenarios.get('expect_risks')
    allowed_logs = scenarios.get('allow_logs', [])
    expected_cells = [] if quick else [f'{t["name"]}-{w}' for t in THEMES for w in ('desktop', 'phone')]
    expected_cells += [f'scenario-{s["name"]}' for s in scenarios.get('scenarios', [])] + ['graph']
    rows = {}
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
                if p.get('node') not in allowed_problems:
                    failures.append(f'{name}: node problem on load: {p.get("node")} {p.get("sock") or ""} {p.get("msg")}')
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
    first, second = res / 'export-1.json', res / 'export-2.json'
    if first.exists() and second.exists():
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


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('catalog'); c.add_argument('out')
    c = sub.add_parser('ops'); c.add_argument('job'); c.add_argument('out'); c.add_argument('--from', dest='source')
    c = sub.add_parser('export'); c.add_argument('file'); c.add_argument('out')
    c = sub.add_parser('verify'); c.add_argument('file'); c.add_argument('out'); c.add_argument('--scenarios'); c.add_argument('--tag', default='app'); c.add_argument('--quick', action='store_true')
    a = p.parse_args()
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
        verify(a.file, a.out, a.scenarios, a.tag, a.quick)


if __name__ == '__main__':
    main()
