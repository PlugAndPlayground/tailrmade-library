# User testing an app

`verify` proves the app does what its builder meant. A user test asks whether someone who didn't build it can get what they came for. A tester with no build context uses the running app through screenshots and the controls on screen, as one persona with a goal, and reports where they hesitated, guessed wrong or gave up.

Offer it in one line after a PASS, such as "Want me to user-test it as a first-time phone user?". Don't run it unasked: a test takes 5 to 15 minutes. It doesn't replace real users. It finds unclear labels, hidden controls, confusing empty and error states and dead ends. It can't tell whether anyone wants the app.

## Session
`verify` runs a fixed scenario. A user test needs to look, decide, then act, so `app.py session` keeps Chrome open on one fresh load and takes one command at a time:

```bash
python3 scripts/app.py session start "App.tmapp" DIR [--viewport 390x844] [--theme tailrmade-dark] [--hash k=v] [--stub stubs.json]
python3 scripts/app.py session do DIR '{"press": "Calculate"}'       # one or more steps, about 10 s
python3 scripts/app.py session stop DIR
```

Each command prints the screenshot path, the text on screen, the scroll position and the controls on screen with refs (`u3 input "Bill" = "47"`). Refs change with every screen. The app runs through the risk review on load, as `verify` does. Themes are `tailrmade-dark`, `newsprint-light` and `neon-dark`. `--stub` takes a list of stubs, as in a `verify` scenario, to test a failing API. The session closes itself after 30 idle minutes.

`DIR/session/state-N.json` also records node problems, console lines and requests for each command. They're for you, not the tester.

| Step | Does |
|---|---|
| `{"press": "Label"}` | presses a button or tab by its text, or `"Decrease (People)"` when the screen lists two |
| `{"type": "Label", "text": "47"}` | replaces the text of the input with that label |
| `{"choose": "Label", "option": "GBP"}` | picks from a dropdown |
| `{"click": "[data-ut=u4]"}` | clicks a control by ref, such as a switch or an unlabelled button |
| `{"keys": "{rightarrow}{rightarrow}", "selector": "[data-ut=u2]"}` | keys into a control by ref, such as a slider |
| `{"scroll": "down"}` | `down`, `up`, `top` or `bottom` |
| `{"view": "graph"}`, `{"view": "graph", "node": "split"}`, `{"view": "app"}` | the graph, fitted or zoomed to nodes whose name contains `node`, and back. The phone graph is view only. |
| `{"look": true}` | takes nothing, just shows the screen again |
| `{"see": "text", "timeout": 10000}`, `{"wait": 2000}` | waits for a slow result |

## Personas
Use these, not personas you make up. LLM personas drift into stereotypes; a fixed set gives findings you can compare between runs.

| Persona | Start with | Behaves | Finds |
|---|---|---|---|
| **First-timer on a phone** | `--viewport 390x844` | Has never seen the app. Skims, reads labels, not hints. Does the obvious thing first. | unclear labels, controls below the fold, results that don't look like results |
| **Impatient expert** | `--viewport 1440x900` | Knows what they want. Fewest steps, keyboard where it can, no reading. | extra steps, missing defaults, inputs that fight typing |
| **Edge-case poker** | `--viewport 390x844` | Leaves fields empty, types `-5`, `0`, `1e9` and words, presses things twice and out of order, uses `--stub` failures. | states nobody wrote a scenario for, silent failures, junk on screen |
| **Tinkerer** | `--viewport 1440x900` | Liked the app and wants to change one thing. Uses `{"view": "graph"}` and node zoom. Says which node they would change and why. | whether the graph can be followed, the promise of a graph a person can follow |

Pick one by default: the first-timer for most apps, the tinkerer when the user cares about remixing. Run another only if the user asks.

An app with two audiences, such as an organizer who sends links and the people who open them, gets one run for each. Recreate the first run's result yourself with `session do`, take a real link from its controls list, and start the second session with `--hash` from that link. You can then check what the second tester reads against what the first one made.

## Goals
Write two to four goals as the persona's situation, not as steps. For each, write down the right outcome for yourself, and keep it out of the brief:

- First-timer, tip calculator: "Dinner for three came to €47 and the service was good. Find out what each of you pays." You expect about 18.02 at 15%, or what the persona's tip implies.
- Tinkerer: "Your friends always tip 20%. Make that the starting tip." You expect the node that holds the tip default, which you find with `tmapp.py explain`.

The most important finding is a tester who believes a wrong result, so every goal needs an answer you can check.

## Run the tester
Start the session yourself, then give the test to a fresh subagent (general-purpose). Building the app gave you its labels and wires, so you can't play a newcomer. Give it only this brief, filled in:

```
You are user-testing an app. Persona: <persona row, in a sentence or two>.
Your goals, in order: <goals>.

The app is open in a browser you drive with commands. Run from <skill dir>:
  python3 scripts/app.py session do <DIR> '<step JSON>'
Start with '{"look": true}'. Each command prints the screen: a screenshot path, the text on screen and the controls with refs. Read every screenshot with the Read tool before you decide what to do next; it is what the persona sees. Steps: <the step table above>.

Act as the persona: one action per command, as a person would, unless you're filling in a field and moving on. Don't read any file except the screenshots, and don't read the app's file, its JSON, the session folder's JSON or the skill's references. If you would give up as the persona, give up and say why. Stop after <25> commands.

Report, for each goal: done, done with trouble, gave up, or the answer you believe is right. Then list the moments of friction as observations: the screen number, what you expected, what happened, and how long it took you to recover. Keep opinions about looks apart, at the end. Don't suggest fixes in the app's internals; you haven't seen them.
```

Stop the session when the tester is done, even if it failed.

## Report
1. Check each goal against your expected outcome. A wrong answer the tester believed goes first.
2. Read the screenshots for the moments the tester names, and `state-N.json` for node problems, console lines and requests at those moments. A bug there belongs in `verify.json` as a scenario.
3. Give the user ranked findings: what happened, the evidence (screenshot path and screen number), and a suggested change. Say which persona and goals ran, and that one simulated tester is a hint, not proof.
4. Change nothing until the user picks. Then follow the update steps and run `verify`.
