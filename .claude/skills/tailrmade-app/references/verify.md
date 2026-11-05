# Verifying an app

```bash
python3 scripts/app.py verify "App.tmapp" OUTDIR --scenarios verify.json --tag my-app
```

It takes 2 to 5 minutes. Exit codes: 0 pass, 1 fail, 3 no dev server.

## What it runs
1. **Static checks** (`tmapp.py check`): links point to real sockets, every node is named and in one group, trees are consistent, widgets have their sockets, a default page exists. Warnings cover fixed colours, HTML nodes, Main Thread, intervals and unpinned packages.
2. **Matrix**: `{"mode":"dark"}`, `{"presetId":"newsprint","mode":"light"}` and `{"presetId":"neon","mode":"dark"}`, each at 1440 and 390 wide, from a fresh load. A desktop-to-phone resize can blank the graph view, so it never resizes across widths.
3. **Each cell records** node status on load and after start, risks, console output and page measurements: sideways overflow, clipped text, contrast below 3:1, raw markup and tokens, `undefined`, `NaN`, `null`, broken images.
4. **Scenarios** from your file.
5. **Export and reload**, which must be identical, plus a comparison of the file with its first export.
6. **Screenshots** of each cell, the opening view and the graph.

## Look at the screenshots
Do this every time, at least one per theme and width, plus the graph. Passing tests have missed a clipped number and an invisible highlight. `tightLines` in `res/*.json` points at likely clipped glyphs.

`inspect_ui` works under Cypress but is not a substitute: it paints through html2canvas at about 490px wide and showed a dark page on white.

## Scenarios file
```json
{
  "expect_risks": ["warning/network/Get the rate"],
  "allow_logs": [],
  "scenarios": [{
    "name": "server-error",
    "viewport": [390, 844],
    "theme": {"mode": "dark"},
    "wait": 6000,
    "stub": [{"match": "frankfurter", "status": 500, "body": {}}],
    "allow_problems": ["Get the rate"],
    "allow_logs": ["frankfurter"],
    "steps": [{"see": "Could not get the rate"}, {"shot": "failed"}]
  }]
}
```
`expect_risks` entries are `severity/kind/node name`. `allow_problems` lists nodes that may show a status in that scenario, such as an HTTP node on a forced failure. Keep it narrow: everything else fails the run.

A stub has `match` (regular expression on the URL) and any of `status`, `body`, `delay`, `network_error`, `content_type`. The first match wins. Unstubbed requests go to the real server, so one scenario should always use the real API from Chrome.

| Step | Does |
|---|---|
| `{"press": "Label"}` | clicks a button or tab |
| `{"type": "Label", "text": "12"}` | replaces an input's text |
| `{"choose": "Label", "option": "GBP"}` | picks from a dropdown |
| `{"keys": "{rightarrow}", "selector": "input[type=range]"}` | keys into a control, such as a slider |
| `{"click": "[role=switch]"}` | clicks by selector, for a control with no label |
| `{"set_socket": "node-id", "socket": "In", "value": 1}` | sets an input directly, as a last resort |
| `{"see": "text"}`, `{"not_see": "text"}` | waits for page text (`timeout` in ms) |
| `{"requests": "regex", "count": 1}` | counts requests since the start or the last reset |
| `{"reset_requests": true}` | resets that count |
| `{"set_stub": [...]}` | swaps the fake server, to test recovery |
| `{"remember": "text"}`, `{"same_place": "text"}` | checks that the layout didn't jump |
| `{"check_page": "name"}` | measures the page in this state |
| `{"shot": "name"}` | takes a screenshot |
| `{"wait": 1000}` | waits, only when nothing can be polled |
| `{"eval": "return ...", "expect": 10}` | runs code with the test controller `c`; without `expect` it must return `true` |

Cover what the app can get wrong: every button with a request count, each state in [app-rules.md](app-rules.md), the largest input at 390px and recovery after a failure.

## Failures that aren't the app
Load errors such as `graphConfiguredAndReady` of undefined or a missing `testController` can come from another session sharing the dev server. `app.py` re-runs once when it sees them and keeps the first failure in `report.json`. Check `git status` and the branch, then report it rather than hiding it. The report records the branch and the number of uncommitted files, because the dev server serves that working tree.

Environment rules are built into `app.py` and `cypress/config.js`: it unsets `ELECTRON_RUN_AS_NODE`, which VS Code leaks and which makes Cypress die with `MODULE_NOT_FOUND`. The window stays larger than the viewport, or the canvas renders black. Use the scratch config, not the repo's.

## No dev server
`verify` runs the static checks, prints `UNVERIFIED` and exits 3. Deliver the file only if the user wants it, tell them in plain words that it has not been run in the app, and give them the command to finish: `yarn dev` in the app repo, then `verify`. Don't call the app verified.
