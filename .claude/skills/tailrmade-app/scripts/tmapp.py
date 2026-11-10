#!/usr/bin/env python3
"""Offline tool for Tailrmade app files: needs only Python, no app or dev server.

  decode  FILE [OUT]                 print or write plain JSON
  encode  JSON OUT [--compressed]    write a loadable file
  check   FILE                       static checks; exit 1 on errors
  explain FILE                       pages, sections, data flow, code and network
  diff    OLD NEW [--ignore-layout]  semantic diff; exit 1 if anything differs
  merge   ORIGINAL BASELINE EDITED OUT   put back fields the app dropped on export
  layout  JSON OUT PLAN              hierarchical graph layout, see references/build.md
"""
import argparse
import base64
import json
import os
import re
import sys
import zlib
from pathlib import Path



def app_graph_version(fallback=12):
    """The app's GRAPH_DATA_VERSION, read from the app repo so the checker follows its migrations."""
    here = Path(__file__).resolve()
    repos = [Path(os.environ['TM_APP_REPO']).expanduser()] if os.environ.get('TM_APP_REPO') else []
    repos += [here.parents[4], here.parents[5] / 'tailrmade']
    for repo in repos:
        try:
            m = re.search(r'GRAPH_DATA_VERSION\s*=\s*(\d+)', (repo / 'src/utils/graphMigrations.ts').read_text())
        except OSError:
            continue
        if m:
            return int(m.group(1))
    return fallback


CURRENT_VERSION = app_graph_version()
NEUTRAL, PAGE = '#BBC5D4', '#C0B6FF'
SECTION_COLORS = ['#60D2FF', '#E2ABFF', '#FFAE6B', '#7DDD9C', '#FF9EC4', '#F4D35E', '#8FB8FF']
HTML_TYPES = {'htmlrenderer', 'iframerenderer', 'iframerenderercanvas', 'iframerendererdiv', 'embedwebsite'}
HEX_COLOR = re.compile(r'#[0-9a-fA-F]{3,8}\b|\brgba?\(')
UNSET_NAME = re.compile(r'^(ai-node-\d+)?$')
TRANSPARENT = {'r': 0, 'g': 0, 'b': 0, 'a': 0}


def read_app(path):
    with open(path, 'rb') as f:
        raw = f.read().strip()
    if raw[:1] == b'{':
        return json.loads(raw)
    raw = raw.replace(b'-', b'+').replace(b'_', b'/')
    raw += b'=' * (-len(raw) % 4)
    return json.loads(zlib.decompress(base64.b64decode(raw)))


def write_app(data, path, compressed=False):
    text = json.dumps(data, indent=None if compressed else 2, ensure_ascii=False)
    if compressed:
        packed = zlib.compress(text.encode('utf8'), 9)
        text = base64.urlsafe_b64encode(packed).decode().rstrip('=')
    with open(path, 'w', encoding='utf8') as f:
        f.write(text)


def graph_of(data):
    return data.get('graphData', data)


def socket(node, name, kinds=('in', 'trigger')):
    return next((s for s in node.get('socketArray', []) if s.get('name') == name and s.get('socketType') in kinds), None)


def socket_data(node, name, default=None):
    s = socket(node, name)
    return default if s is None or 'data' not in s else s['data']


def surface_tree(node):
    data = socket_data(node, 'Layout JSON')
    return data.get('tree') if isinstance(data, dict) else None


def check(data):
    """Returns (errors, warnings). Errors break the app or the brief; warnings need a look."""
    g = graph_of(data)
    errors, warnings = [], []
    version = g.get('version')
    if version != CURRENT_VERSION:
        return [f'version is {version}, not {CURRENT_VERSION}: run `app.py export` and check the migrated export'], []
    for key in ('name', 'id'):
        if not data.get(key):
            errors.append(f'top level has no {key}')
    nodes = g.get('nodes', [])
    by_id = {}
    for n in nodes:
        if n['id'] in by_id:
            errors.append(f'duplicate node id {n["id"]}')
        by_id[n['id']] = n

    def has_socket(node, name, kinds):
        # A macro's sockets live on its inner nodes as well as on the macro.
        return node.get('type') == 'macro' or socket(node, name, kinds) is not None

    for l in g.get('links', []):
        a, b = by_id.get(l['sourceNodeId']), by_id.get(l['targetNodeId'])
        label = f'{l["sourceNodeId"]}.{l["sourceSocketName"]} -> {l["targetNodeId"]}.{l["targetSocketName"]}'
        if a is None or b is None:
            errors.append(f'link to a missing node: {label}')
        elif not has_socket(a, l['sourceSocketName'], ('out',)):
            errors.append(f'link from a missing output: {label}')
        elif not has_socket(b, l['targetSocketName'], ('in', 'trigger')):
            errors.append(f'link to a missing input: {label}')

    grouped = [i for gr in g.get('groups', []) for i in gr.get('nodeIds', [])]
    for i in {i for i in grouped if grouped.count(i) > 1}:
        errors.append(f'node {i} is in more than one group')
    for i in set(grouped) - set(by_id):
        errors.append(f'group holds missing node {i}')
    for i in set(by_id) - set(grouped):
        errors.append(f'node {by_id[i].get("name") or i} is in no group')
    names = [gr.get('name', '') for gr in g.get('groups', [])]
    if not any(re.match(r'\d+\. ', nm) for nm in names):
        warnings.append('no numbered groups ("1. Fetch the rate"), so the reading order is not shown')

    for n in nodes:
        name = n.get('name') or ''
        who = name or n['id']
        if UNSET_NAME.match(name):
            errors.append(f'node {n["id"]} ({n.get("type")}) has no real name')
        if n.get('type') == 'customfunction':
            code = socket_data(n, 'Code', '') or ''
            if not code.lstrip().startswith('('):
                errors.append(f'{who}: code must start with "(" or the node gets renamed to what comes before it')
            if socket_data(n, 'Main Thread') is True and not n.get('comment'):
                warnings.append(f'{who}: Main Thread is on with no comment saying why')
        if n.get('type') in HTML_TYPES:
            wired = any(l['targetNodeId'] == n['id'] for l in g.get('links', []))
            why = 'a wired HTML node always gets a network warning' if wired else 'native nodes come first'
            warnings.append(f'{who}: HTML-type node ({why}); say why in a comment if nothing native works')
            if not n.get('comment'):
                warnings.append(f'{who}: HTML-type node has no comment')
        if n.get('type') == 'loadnpm' or 'npm' in str(n.get('type', '')).lower():
            for s in n.get('socketArray', []):
                value = s.get('data')
                if s.get('socketType') == 'in' and isinstance(value, str) and value and not re.search(r'@\d', value) and 'name' in s['name'].lower():
                    warnings.append(f'{who}: package "{value}" has no pinned version')
        if n.get('updateBehaviour', {}).get('interval') and n.get('type') == 'httpnode':
            warnings.append(f'{who}: HTTP on an interval; prefer a manual trigger to stay under rate limits')
        if n.get('type') == 'widgetbutton' and socket_data(n, 'Variant') not in (None, 'Inherit'):
            warnings.append(f'{who}: button variant is not Inherit, so it may not follow the theme')
        styles = socket_data(n, 'Custom styles')
        if isinstance(styles, dict) and HEX_COLOR.search(json.dumps(styles)):
            warnings.append(f'{who}: fixed colour in Custom styles')
        if n.get('type') == 'uisurfacenode':
            check_surface(n, g, by_id, errors, warnings)

    for n in nodes:
        if n.get('type') in ('text', 'customfunction') and '{.primary' in json.dumps(n.get('socketArray', [])):
            warnings.append(f'{n.get("name") or n["id"]}: a mark in primary vanishes in Newsprint, whose primary is black; use secondary')
    default = g.get('graphSettings', {}).get('defaultUISurfaceNodeId')
    if any(n.get('type') == 'uisurfacenode' for n in nodes):
        if not default:
            errors.append('no default page: graphSettings.defaultUISurfaceNodeId is empty')
        elif default not in by_id:
            errors.append(f'default page {default} does not exist')
    if not any(n.get('type') == 'label' and 'start here' in (n.get('name') or '').lower() for n in nodes):
        warnings.append('no "Start here" label')
    return errors, warnings


def check_surface(n, g, by_id, errors, warnings):
    who = n.get('name') or n['id']
    tree = surface_tree(n)
    if not tree or 'ROOT' not in tree:
        errors.append(f'{who}: Layout JSON has no tree with a ROOT')
        return
    placed = set()
    for key, item in tree.items():
        for child in item.get('nodes', []):
            if child not in tree:
                errors.append(f'{who}: {key} lists missing child {child}')
            elif tree[child].get('parent') != key:
                errors.append(f'{who}: {child} has parent {tree[child].get("parent")}, not {key}')
        kind = item.get('type', {}).get('resolvedName')
        props = item.get('props', {})
        if kind == 'DynamicWidget' and str(props.get('id', '')).startswith('NODE_'):
            source = props['id'][5:]
            placed.add(source)
            if not any(l['sourceNodeId'] == source and l['targetNodeId'] == n['id'] for l in g.get('links', [])):
                errors.append(f'{who}: widget {source} is on the page with no ReactUI link')
        background = props.get('background')
        if isinstance(background, dict) and kind in ('Container', 'DynamicWidget') and background.get('a', 0) not in (0, None):
            warnings.append(f'{who}: {key} has a fixed background; use emphasis and tone')
        if HEX_COLOR.search(json.dumps(props.get('customStyles', {}))):
            warnings.append(f'{who}: {key} has a fixed colour in customStyles')
    reached, stack = set(), ['ROOT']
    while stack:
        key = stack.pop()
        if key in reached or key not in tree:
            continue
        reached.add(key)
        stack += tree[key].get('nodes', [])
    for key in set(tree) - reached:
        errors.append(f'{who}: {key} is not reachable from ROOT')
    # Each linked widget owns a trio of sockets; leftovers bring removed widgets back.
    linked = {l['sourceNodeId']: l['targetSocketName'] for l in g.get('links', []) if l['targetNodeId'] == n['id'] and l['targetSocketName'] != 'Layout JSON' and l['sourceSocketName'] == 'ReactUI'}
    for source, slot in linked.items():
        if source not in placed:
            errors.append(f'{who}: {slot} is linked but has no widget in the tree')
        for suffix in (' visible', ' layout'):
            if socket(n, slot + suffix) is None:
                errors.append(f'{who}: {slot} is missing its "{slot + suffix}" socket')
    for s in n.get('socketArray', []):
        parent = s.get('dependentSocketName')
        if parent and socket(n, parent) is None:
            errors.append(f'{who}: {s["name"]} belongs to missing socket {parent}')


def short(value, size=90):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = ' '.join(text.split())
    return text if len(text) <= size else text[:size - 1] + '…'


def outline(tree, by_id, key='ROOT', depth=0, out=None):
    out = [] if out is None else out
    item = tree.get(key)
    if item is None:
        return out
    kind = item.get('type', {}).get('resolvedName')
    props = item.get('props', {})
    pad = '  ' * (depth + 2)
    if kind == 'Text':
        out.append(f'{pad}text ({props.get("variant")}, {props.get("tone")}): {short(props.get("content", ""))}')
    elif kind == 'DynamicWidget':
        source = str(props.get('id', '')).removeprefix('NODE_')
        node = by_id.get(source)
        label = (node.get('name') or source) if node else props.get('id')
        out.append(f'{pad}{label} [{node.get("type") if node else "socket"}]')
    else:
        extras = [props.get('flexDirection')]
        if props.get('emphasis') not in (None, 'none'):
            extras.append(f'{props["emphasis"]}/{props.get("tone")}')
        out.append(f'{pad}{kind} ({", ".join(str(e) for e in extras)})')
    for child in item.get('nodes', []):
        outline(tree, by_id, child, depth + 1, out)
    return out


def explain(data):
    g = graph_of(data)
    nodes = g.get('nodes', [])
    links = g.get('links', [])
    by_id = {n['id']: n for n in nodes}
    names = [n.get('name') for n in nodes]

    def label(i):
        # Old files repeat default names, so three "HTTPNode"s need their ids to be told apart.
        if i not in by_id:
            return i
        name = by_id[i].get('name')
        return name if name and names.count(name) == 1 else f'{name or by_id[i].get("type")} ({i})'

    lines = [f'# {data.get("name")}', f'version {g.get("version")}, {len(nodes)} nodes, {len(links)} links, theme {g.get("graphSettings", {}).get("theme", "default")}']
    if g.get('version') != CURRENT_VERSION:
        lines.append(f'NOT CURRENT: judge this from `app.py export`, not the raw file. Pages, names and links can change when it migrates.')
    default = g.get('graphSettings', {}).get('defaultUISurfaceNodeId')
    lines.append('\n## Pages')
    surfaces = [n for n in nodes if n.get('type') == 'uisurfacenode']
    if not surfaces:
        lines.append('  none in this file')
    for n in surfaces:
        lines.append(f'  {label(n["id"])}{" (opens first)" if n["id"] == default else ""}')
        tree = surface_tree(n)
        if tree:
            lines += outline(tree, by_id)
    lines.append('\n## Sections')
    grouped = set()
    for gr in g.get('groups', []):
        grouped.update(gr.get('nodeIds', []))
        lines.append(f'  {gr.get("name")}: ' + ', '.join(label(i) for i in gr.get('nodeIds', [])))
    loose = [label(n['id']) for n in nodes if n['id'] not in grouped]
    if loose:
        lines.append('  (no group): ' + ', '.join(loose))
    lines.append('\n## Data flow')
    for l in links:
        if l['targetSocketName'] != 'Layout JSON' and l['sourceSocketName'] != 'ReactUI':
            lines.append(f'  {label(l["sourceNodeId"])}.{l["sourceSocketName"]} -> {label(l["targetNodeId"])}.{l["targetSocketName"]}')
    lines.append('\n## Inputs on the page')
    for n in nodes:
        if str(n.get('type', '')).startswith('widget'):
            lines.append(f'  {label(n["id"])} [{n["type"]}] initial={short(socket_data(n, "Initial Value", ""), 40)} label={short(socket_data(n, "Label", ""), 40)}')
    lines.append('\n## Network and code')
    for n in nodes:
        t = n.get('type')
        behaviour = n.get('updateBehaviour', {})
        if t == 'httpnode':
            url = socket_data(n, 'URL', '')
            wired = any(l['targetNodeId'] == n['id'] and l['targetSocketName'] == 'URL' for l in links)
            triggers = [s['name'] for s in n.get('socketArray', []) if s.get('socketType') == 'trigger']
            every = f' every {behaviour.get("intervalFrequency")}ms' if behaviour.get('interval') and behaviour.get('intervalFrequency') else ''
            lines.append(f'  HTTP {label(n["id"])}: {"URL from a wire" if wired else short(url)}; on load={behaviour.get("load")}, on update={behaviour.get("update")}, interval={behaviour.get("interval")}{every}, triggers={triggers}')
        elif t == 'customfunction':
            lines.append(f'  function {label(n["id"])} (main thread: {socket_data(n, "Main Thread", False)}): {short(socket_data(n, "Code", ""), 150)}')
        elif t in HTML_TYPES:
            lines.append(f'  HTML {label(n["id"])} [{t}]: {short(socket_data(n, "Html", socket_data(n, "Input", "")), 150)}')
    constants = [(n, socket_data(n, 'Input')) for n in nodes if n.get('type') == 'label']
    constants = [(n, v) for n, v in constants if isinstance(v, str) and v and any(l['sourceNodeId'] == n['id'] for l in links)]
    if constants:
        lines.append('\n## Constant text used as values')
        lines += [f'  {label(n["id"])}: {short(v)}' for n, v in constants]
    editors = [(n, socket_data(n, 'Markdown')) for n in nodes if n.get('type') == 'texteditor2']
    editors = [(n, v) for n, v in editors if isinstance(v, str) and v]
    if editors:
        lines.append('\n## Saved text')
        lines += [f'  {label(n["id"])}: {short(v, 150)}' for n, v in editors]
    comments = [(label(n['id']), n['comment']) for n in nodes if n.get('comment')]
    if comments:
        lines.append('\n## Comments')
        lines += [f'  {who}: {short(text, 200)}' for who, text in comments]
    return '\n'.join(lines)


LAYOUT_FIELDS = {'x', 'y', 'width', 'height'}


def canonical(data, ignore_layout=False):
    """Same app, same output: drops the save date and the order of links, which the app reshuffles."""
    d = json.loads(json.dumps(data))
    d.pop('date', None)
    g = graph_of(d)
    g['links'] = sorted(g.get('links', []), key=lambda l: json.dumps(l, sort_keys=True))
    g['nodes'] = sorted(g.get('nodes', []), key=lambda n: n['id'])
    for gr in g.get('groups', []):
        gr['nodeIds'] = sorted(gr.get('nodeIds', []))
    g['groups'] = sorted(g.get('groups', []), key=lambda gr: gr.get('name', ''))
    # The app infers these from the wired value at run time, so they can flip between saves.
    for n in g['nodes']:
        if n.get('type') == 'customfunction':
            for s in n.get('socketArray', []):
                if s.get('socketType') == 'in' and s.get('name') not in ('Code', 'Main Thread'):
                    s.pop('dataType', None)
    if ignore_layout:
        for n in g['nodes']:
            for f in LAYOUT_FIELDS:
                n.pop(f, None)
        g.get('graphSettings', {}).pop('viewportCenterPosition', None)
        g.get('graphSettings', {}).pop('viewportScale', None)
    return d


def list_key(path, item):
    if isinstance(item, dict):
        if 'socketType' in item and 'name' in item:
            return f'{item["socketType"]}:{item["name"]}'
        if 'id' in item:
            return item['id']
        if 'sourceNodeId' in item:
            return json.dumps(item, sort_keys=True)
    return None


def walk_diff(a, b, path, out):
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        out.append(f'CHANGED {path}: {short(a)} -> {short(b)}')
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f'ADDED {path}/{k}: {short(b[k])}')
            elif k not in b:
                out.append(f'REMOVED {path}/{k}: {short(a[k])}')
            else:
                walk_diff(a[k], b[k], f'{path}/{k}', out)
    elif isinstance(a, list):
        keys_a = [list_key(path, x) for x in a]
        keys_b = [list_key(path, x) for x in b]
        if a and b and None not in keys_a and None not in keys_b or (not a and None not in keys_b) or (not b and None not in keys_a):
            map_a, map_b = dict(zip(keys_a, a)), dict(zip(keys_b, b))
            for k in keys_a:
                if k not in map_b:
                    out.append(f'REMOVED {path}/{k}')
                else:
                    walk_diff(map_a[k], map_b[k], f'{path}/{k}', out)
            out.extend(f'ADDED {path}/{k}: {short(map_b[k])}' for k in keys_b if k not in map_a)
        elif len(a) != len(b):
            out.append(f'CHANGED {path}: {short(a)} -> {short(b)}')
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                walk_diff(x, y, f'{path}/{i}', out)
    elif a != b:
        out.append(f'CHANGED {path}: {short(a)} -> {short(b)}')


def diff(a, b, ignore_layout=False):
    out = []
    walk_diff(canonical(a, ignore_layout), canonical(b, ignore_layout), '', out)
    return out


def merge_dropped(original, baseline, edited):
    """Puts back what the app drops on export. ORIGINAL is the user's file, BASELINE is that
    file loaded and exported with no edits, and EDITED is the export after the edits. A field
    in ORIGINAL but not BASELINE was dropped by the app, not removed by the edit."""
    restored = []

    def walk(o, b, e, path):
        if not (isinstance(o, dict) and isinstance(e, dict)):
            if isinstance(o, list) and isinstance(e, list) and isinstance(b, list):
                keyed_o = {list_key(path, x): x for x in o if list_key(path, x)}
                keyed_b = {list_key(path, x): x for x in b if list_key(path, x)}
                for x in e:
                    k = list_key(path, x)
                    if k in keyed_o and k in keyed_b:
                        walk(keyed_o[k], keyed_b[k], x, f'{path}/{k}')
            return
        b = b if isinstance(b, dict) else {}
        for k, v in o.items():
            if k not in b and k not in e:
                e[k] = v
                restored.append(f'{path}/{k}')
            elif k in b and k in e:
                walk(v, b[k], e[k], f'{path}/{k}')

    walk(original, baseline, edited, '')
    # The tools move the camera to whatever they touch. The saved opening view is the user's.
    settings = graph_of(edited).get('graphSettings', {})
    for key in ('viewportCenterPosition', 'viewportScale'):
        saved = graph_of(baseline).get('graphSettings', {}).get(key)
        if saved is not None and settings.get(key) != saved:
            settings[key] = saved
            restored.append(f'/graphData/graphSettings/{key}')
    return restored


def grow(plan_item, by_id, links, x, y):
    """Places a section's nodes in columns along the data flow. Returns the bottom edge and right edge."""
    ids = plan_item['nodes']
    column = {i: 0 for i in ids}
    for _ in ids:
        for l in links:
            a, b = l['sourceNodeId'], l['targetNodeId']
            if a in column and b in column and a != b and column[b] <= column[a]:
                column[b] = column[a] + 1
    cx, bottom = x, y
    for c in sorted(set(column.values())):
        cy, width = y, 0
        for i in [i for i in ids if column[i] == c]:
            n = by_id[i]
            n['x'], n['y'] = cx, cy
            w, h = plan_item.get('reserve', {}).get(i, (n.get('width') or 160, n.get('height') or 100))
            width = max(width, w)
            cy += h + 80
        bottom = max(bottom, cy)
        cx += width + 140
    return bottom, cx - 140


def layout(data, plan):
    """plan: {"name", "start": [ids], "theme": [ids], "sections": [{"name", "nodes", "children": [..], "reserve": {id: [w, h]}}],
    "page": id or [ids], "chain": bool, "app_theme": {"mode": "dark"}, "overlay": {...}}.
    A parent sits left of its child sections and is centred on them; other sections stack in one column."""
    g = graph_of(data)
    by_id = {n['id']: n for n in g['nodes']}
    links = g['links']
    groups, y, number = [], 0, 0
    gap = plan.get('gap', 520)
    previous = {tuple(sorted(gr.get('nodeIds', []))): gr.get('id') for gr in g.get('groups', [])}

    def group(name, ids, color):
        return {'id': previous.get(tuple(sorted(ids))) or re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-'), 'name': name, 'color': color, 'nodeIds': list(ids)}

    for title, key in (('Start here', 'start'), ('App theme', 'theme')):
        if plan.get(key):
            x, height = 0, 0
            for i in plan[key]:
                by_id[i]['x'], by_id[i]['y'] = x, y
                x += (by_id[i].get('width') or 160) + 120
                height = max(height, by_id[i].get('height') or 100)
            groups.append(group(title, plan[key], NEUTRAL))
            y += height + gap

    right = 0

    def place(section, x, y):
        nonlocal number, right
        number += 1
        name = f'{number}. {section["name"]}'
        color = SECTION_COLORS[(number - 1) % len(SECTION_COLORS)]
        bottom, edge = grow(section, by_id, links, x, y)
        groups.append(group(name, section['nodes'], color))
        children = section.get('children', [])
        if children:
            child_x, cy, first = edge + 700, y, y
            for child in children:
                cy = place(child, child_x, cy) + gap
            child_bottom = cy - gap
            # Centre the parent on its children.
            shift = (first + child_bottom) / 2 - (y + bottom) / 2
            if shift > 0:
                for i in section['nodes']:
                    by_id[i]['y'] += shift
            bottom = max(bottom + max(shift, 0), child_bottom)
        right = max(right, edge)
        return bottom

    top = y
    x = 0
    for section in plan.get('sections', []):
        y = place(section, x, y) + gap
        # A chain reads as a staircase: each section starts right of the one that feeds it.
        if plan.get('chain'):
            x = right + 300
    bottom = y - gap
    # Group headers keep their screen size, so at the opening zoom they need this much room.
    right = max(right, *[by_id[i].get('width') or 160 for i in plan.get('start', [])], 0)
    scale_guess = min(0.5, 900 / (bottom + 1200))
    clearance = max(500, 260 / scale_guess)
    pages = plan.get('page') or []
    pages = [pages] if isinstance(pages, str) else pages
    page_y = top
    for i in pages:
        n = by_id[i]
        n['x'], n['y'] = right + clearance, page_y + max(0, (bottom - top - (n.get('height') or 300)) / 2 if len(pages) == 1 else 0)
        page_y += (n.get('height') or 300) + gap
    if pages:
        groups.append(group('Main page', pages, PAGE))
    g['groups'] = groups
    full_w = max((by_id[i]['x'] + (by_id[i].get('width') or 320) for i in pages), default=right)
    scale = round(min(0.5, 0.48 * 1440 / (full_w + 900), 900 / (bottom + 1200)), 3)
    settings = g.setdefault('graphSettings', {})
    settings['viewportCenterPosition'] = {'x': round(full_w / 2 - 0.26 * 1440 / scale), 'y': round(bottom / 2)}
    settings['viewportScale'] = scale
    if 'app_theme' in plan:
        settings['theme'] = plan['app_theme']
    if 'overlay' in plan:
        g['overlay'] = plan['overlay']
    if 'name' in plan:
        data['name'] = plan['name']
        data['id'] = plan.get('id', f'Default/{plan["name"]}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('decode'); c.add_argument('file'); c.add_argument('out', nargs='?')
    c = sub.add_parser('encode'); c.add_argument('json'); c.add_argument('out'); c.add_argument('--compressed', action='store_true')
    c = sub.add_parser('check'); c.add_argument('file')
    c = sub.add_parser('explain'); c.add_argument('file')
    c = sub.add_parser('diff'); c.add_argument('old'); c.add_argument('new'); c.add_argument('--ignore-layout', action='store_true')
    c = sub.add_parser('merge'); c.add_argument('original'); c.add_argument('baseline'); c.add_argument('edited'); c.add_argument('out')
    c = sub.add_parser('layout'); c.add_argument('json'); c.add_argument('out'); c.add_argument('plan')
    a = p.parse_args()

    if a.cmd == 'decode':
        data = read_app(a.file)
        if a.out:
            write_app(data, a.out)
        else:
            print(json.dumps(data, indent=2, ensure_ascii=False))
    elif a.cmd == 'encode':
        write_app(read_app(a.json), a.out, a.compressed)
    elif a.cmd == 'check':
        errors, warnings = check(read_app(a.file))
        for w in warnings:
            print('warning:', w)
        for e in errors:
            print('ERROR:', e)
        print(f'{len(errors)} errors, {len(warnings)} warnings')
        sys.exit(1 if errors else 0)
    elif a.cmd == 'explain':
        print(explain(read_app(a.file)))
    elif a.cmd == 'diff':
        out = diff(read_app(a.old), read_app(a.new), a.ignore_layout)
        print('\n'.join(out) if out else 'identical')
        sys.exit(1 if out else 0)
    elif a.cmd == 'merge':
        edited = read_app(a.edited)
        restored = merge_dropped(read_app(a.original), read_app(a.baseline), edited)
        write_app(edited, a.out)
        print(f'restored {len(restored)} dropped fields')
        for r in restored:
            print(' ', r)
    elif a.cmd == 'layout':
        data = read_app(a.json)
        with open(a.plan, encoding='utf8') as f:
            layout(data, json.load(f))
        write_app(data, a.out)


if __name__ == '__main__':
    main()
