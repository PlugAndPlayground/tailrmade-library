# Building and updating with the app's tools

The app has a browser-local MCP server (`src/services/TailrmadeMCPServer.ts`), the same tools its in-app AI uses, and no external transport. `app.py` reaches it through Cypress and `window.testController`. A run takes about 15 to 35 seconds, so batch tool calls.

```bash
python3 scripts/app.py catalog DIR     # prompt.md (rules, node list), tools.json, nodes.json
python3 scripts/app.py ops ops.json DIR [--from App.tmapp]    # writes DIR/export.json
```

`ops.json` is a list of `{"tool": "add_node", "input": {...}}`, run in order, stopping at the first error. Add `{"tool": "describe_node", "input": {"node_type": "Text"}}` before using an unfamiliar node, then read `DIR/results.json`. Use the catalogue rather than guessing at nodes or sockets.

The worked examples in `evals/apps/*/` show a full `ops.json`, `plan.json` and `verify.json`.

## New app
1. Read `prompt.md`, then describe the nodes you plan to use.
2. Write the ops. Order matters:
   - IDs must be `ai-node-N`. `add_node` first, then `set_node_name` on every node.
   - Set a function's `Code` before connecting to its parameters. Wiring to a Text node's token name, such as `r`, creates the socket.
   - `set_surface_layout` connects the widgets it names. Sizes are CSS strings.
   - Finish with `set_default_surface` and `inspect_warnings_and_errors`.
3. Run `ops`, then lay it out and name it:
   ```bash
   python3 scripts/tmapp.py layout DIR/export.json "App.tmapp" plan.json
   ```
4. Run `verify`, read the screenshots, and fix by changing the ops and running again.

## plan.json
```json
{
  "name": "Tip calculator",
  "chain": true,
  "app_theme": {"mode": "dark"},
  "overlay": {"dashboard": {"visible": true, "fullscreen": false, "maximized": false, "widthPercentage": 52, "locked": false}},
  "start": ["ai-node-1"],
  "theme": ["ai-node-2"],
  "page": "ai-node-11",
  "sections": [
    {"name": "Read the inputs", "nodes": ["ai-node-3"], "children": [], "reserve": {"ai-node-7": [640, 700]}}
  ]
}
```
It numbers sections in order and replaces all groups. `chain` makes a staircase, for sections that feed each other. `children` puts child sections right of their parent, centred on it. `reserve` keeps room for a draw node's picture. `page` can be a list.

## What the tools can't do
| Need | Tools | Do this |
|---|---|---|
| Theme props, `emphasis`, `tone`, Text `variant` | yes | layout spec or `set_layout_value` |
| Custom styles, `maxWidth`, `@media` on layout items | only through `props` in `set_surface_layout` | `set_layout_value` refuses them |
| Text node Custom styles | yes | `set_socket_value` |
| Moving a node | no tool | `tmapp.py layout` |
| Parent and child layout | `finish_section` makes rows only | `tmapp.py layout` |
| App name, saved theme, page open on load, opening view | no tool | `tmapp.py layout` plan |
| Theme node | not in the catalogue, but `add_node` takes `theme` | works |
| Unwired Shader `Images` | never saved, warns on load | wire a function returning `{}` |
| Add one item to a page | `set_layout_value` only edits | `inspect_surface`, add the item, send it back to `set_surface_layout`: ids are kept |

Editing JSON is the fallback for these only, because the tools keep the trio of sockets and the tree consistent. For a change the tools can't make, edit the export and let `check` and `verify` catch mistakes.

## Explaining a file
```bash
python3 scripts/tmapp.py explain "Old.ppgraph"   # version check: stops short of trusting a raw old file
python3 scripts/app.py export "Old.ppgraph" migrated.json
python3 scripts/tmapp.py explain migrated.json
```
Explain what the app does for its user first, then how: pages, sections in reading order, what triggers requests, and anything risky. Use the export for any old file; the raw file has unnamed nodes and `layouts` rather than pages. Read the code and comments before describing behaviour, and run it if the answer depends on what it does.

## Updating an app
1. Copy the user's **latest** file. Re-read it just before you write, because they edit between rounds. Write a new file; don't overwrite theirs unless they ask.
2. Run `tmapp.py explain`, then tell them what will change and what won't, before changing it.
3. Make a baseline, with no edits, then the edited export:
   ```bash
   python3 scripts/app.py export "App.tmapp" baseline.json
   python3 scripts/app.py ops ops.json DIR --from "App.tmapp"
   python3 scripts/tmapp.py merge "App.tmapp" baseline.json DIR/export.json "App v2.tmapp"
   ```
   `merge` puts back fields the app dropped on export: a field in the original but not the baseline was dropped by the app, not by the edit. It also restores the saved opening view, which the tools move.
4. Use the targeted tools (`set_layout_value`, `set_socket_value`), not `set_surface_layout`, which replaces the whole surface. New nodes land at automatic positions, so place only those, near what they feed; never re-run `layout` on the user's graph unless they asked for a tidy-up. To place one, make the job an object: `{"ops": [...], "after": "c.getNodeByID('ai-node-1').setPosition(x, y);"}`. The test controller's `moveNodeByID` is relative, so don't use it for this.
5. Prove the rest is unchanged, and show the user the list:
   ```bash
   python3 scripts/tmapp.py diff baseline.json "App v2.tmapp"
   ```
   Every line must be something you meant to change, or a field `merge` restored. Sending a layout back adds a harmless `heightMode: hug` to items. Add a scenario for the old behaviour too.
6. Run `verify`.
