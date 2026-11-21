# Verifying an app

```bash
python3 scripts/app.py verify "App.tmapp" OUTDIR --scenarios verify.json --tag my-app              # full: report this one
python3 scripts/app.py verify "App.tmapp" OUTDIR --scenarios verify.json --only bad-city,phone   # just these scenarios
python3 scripts/app.py verify "App.tmapp" OUTDIR --scenarios verify.json --quick                 # scenarios + export, no matrix
```

Exit codes: 0 pass, 1 fail, 3 no dev server, 4 stalled.

**Always run `verify` with `run_in_background`.** A full run takes about 30 seconds per cell (6 matrix cells, each scenario, the graph), plus each scenario's waits, so 5 to 10 minutes for a typical app. With a retry that passes the 10 minute foreground limit. It prints `done 3/11: neon-dark-phone (95s)` as each cell finishes, so read the output when you need a line, rather than polling `res/`. Don't wrap it in `timeout`: macOS has none, and `verify` stops itself.

## Iterate fast, verify fully once
Every full run repeats the whole matrix, so don't use it to try fixes:
1. Debug in a **session** (`app.py session start`, `do`, `stop`): one load, then each step in seconds, with what's on screen.
2. Re-run the scenarios you changed with `--only NAME,...` (no matrix, no export), or all of them with `--quick`.
3. Run the **full** verify once at the end, and report that run. A partial run prints its verdict as partial; never report it as PASS.

## Dev server
Each Claude session gets its own dev server on a free port. The first command that needs the app starts it (about 30 seconds with webpack's cache, a few minutes cold), and later commands reuse it. Sharing one server between sessions stalled Cypress runs for up to hours, so don't point sessions at a shared `yarn dev`. `app.py server status` lists the servers app.py started, and `server stop` stops this session's. A server whose Claude process has exited, or that sat idle for 3 hours, is stopped by the next run. `TM_BASE_URL` points everything at a server you started yourself instead.

The server serves the app repo's working tree, so uncommitted changes there are in what you test. The report records the branch and the number of uncommitted files.

## Stalled
With no finished cell and no Cypress output for 5 minutes, or past `--timeout` minutes (default 3 per cell), `verify` stops Cypress and its Chrome, exits 4 and prints STALLED. Cells that finished are real results. A stall is the environment, not the app: look at `OUTDIR/cypress-verify.log` and the last screenshot, then run again. Report it as unverified if it keeps stalling; don't call the app passed or failed on a stalled run.

## What it runs
1. **Static checks** (`tmapp.py check`): links point to real sockets, every node is named and in one group, trees are consistent, widgets have their sockets, a default page exists. Warnings cover fixed colours, HTML nodes, Main Thread, intervals and unpinned packages.
2. **Matrix**: `{"mode":"dark"}`, `{"presetId":"newsprint","mode":"light"}` and `{"presetId":"neon","mode":"dark"}`, each at 1440 and 390 wide, from a fresh load. A desktop-to-phone resize can blank the graph view, so it never resizes across widths.
3. **Each cell records** node status on load and after start, risks, console output and page measurements: sideways overflow, clipped text, contrast below 3:1, raw markup and tokens, `undefined`, `NaN`, `null`, broken images. Content inside a box that clips or scrolls sideways doesn't count as wider than the page; the box itself does. A box meant to scroll sideways, such as a wide diagram in an HTML node, carries `data-scroll-x` so it isn't reported. An app with risks opens paused behind the review; the cell presses the banner and Run, as a person would, and fails if it is still paused after 45 seconds. Node problems shown while it is paused are listed under "Shown while the app waits behind the review", not as failures: mention them, since a person sees them before pressing Run.
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
A scenario's `"hash": "santa=abc"` opens the app as if from a shared link ending in `#santa=abc`, so a URL Parameter node sees it on load. Use it for every page an app shows only when its link carries a parameter, and for a damaged value.

`expect_risks` entries are `severity/kind/node name`. `allow_problems` lists nodes that may show a status in that scenario, such as an HTTP node on a forced failure. Keep it narrow: everything else fails the run.

A stub has `match` (regular expression on the URL) and any of `status`, `body`, `delay`, `network_error`, `content_type`. The first match wins. Unstubbed requests go to the real server, so one scenario should always use the real API from Chrome.

| Step | Does |
|---|---|
| `{"press": "Label"}` | clicks a button or tab |
| `{"type": "Label", "text": "12"}` | replaces an input's text |
| `{"choose": "Label", "option": "GBP"}` | picks from a dropdown |
| `{"toggle": "Label", "on": false}` | sets a switch or checkbox; without `on` it flips it. `press` is only for buttons and tabs |

`press`, `toggle`, `type` and `choose` wait up to 5 seconds for their control, because a tab's content can render a moment after the tab is pressed. Labels are matched with whitespace collapsed, as the user-test screen lists them.
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

In `eval`, `document` is the Cypress runner's, not the app's. Use `doc` (the app's document), `win` (its window) or `dash` (the page element). HTML and draw nodes also render a preview on the canvas, so query inside `dash`, or you count everything twice: `return dash.querySelectorAll('svg').length`.

Cover what the app can get wrong: every button with a request count, each state in [app-rules.md](app-rules.md), the largest input at 390px and recovery after a failure.

## Failures that aren't the app
Load errors such as `graphConfiguredAndReady` of undefined or a missing `testController` can still happen while the machine is busy. `app.py` re-runs once when it sees them and keeps the first failure in `report.json`. Report it rather than hiding it.

Environment rules are built into `app.py` and `cypress/config.js`: it unsets `ELECTRON_RUN_AS_NODE`, which VS Code leaks and which makes Cypress die with `MODULE_NOT_FOUND`. The window stays larger than the viewport, or the canvas renders black. Use the scratch config, not the repo's.

`app.py` stops every Cypress and Chrome it started when it exits or is stopped (anything but `kill -9`). Don't kill processes by hand. If you must, stop only ones whose `TM_OUT` is under your own output folder, because other sessions run their own.

## No dev server
If the server can't start, for example because the app repo has no `node_modules`, `verify` runs the static checks, prints `UNVERIFIED` and the reason, and exits 3. Deliver the file only if the user wants it, tell them in plain words that it has not been run in the app, and give them the command to finish: `yarn` in the app repo, then `verify`. Don't call the app verified.
