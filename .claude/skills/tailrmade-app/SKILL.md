---
name: tailrmade-app
description: Create, explain, update and verify Tailrmade apps (.tmapp and .ppgraph files). Use whenever someone asks to build a Tailrmade app or graph from a description, asks how an existing .tmapp or .ppgraph works, wants a change to one, or wants to test one in the real app across themes and phone width, even if they just say "make me an app that..." in this repo or name a file from the examples library.
---

# Tailrmade apps

Make apps that work, in the real app, on phone and desktop, in dark and light themes, with a graph a person can follow. An app isn't finished until it has been run.

Scripts are in `scripts/`; run them from anywhere. Read a reference when its step comes up:

- [references/build.md](references/build.md): tools, ops, layout, explaining, updating
- [references/app-rules.md](references/app-rules.md): native nodes, theme, mobile, states, APIs, graph readability. Read before you design an app.
- [references/verify.md](references/verify.md): checks and the scenarios file
- [references/file-format.md](references/file-format.md): only when you need the JSON itself

Worked examples are in `evals/apps/`.

## Create
1. Read app-rules. Decide on sections and states, and pick native nodes.
2. Run `app.py catalog DIR` and read `prompt.md`. Describe unfamiliar nodes.
3. Build with the app's tools (`app.py ops`), not by writing JSON, then run `tmapp.py layout`.
4. Write `verify.json` with a scenario for every button and state, then run `app.py verify`.
5. Read the screenshots. Fix and repeat until it passes and looks right.

## Explain
`tmapp.py explain FILE`. For a file whose version isn't 7, run `app.py export` first and explain the export. Lead with what the app does for its user.

## Update
Start from the user's latest copy, say what will change before changing it, keep the diff small, and write a new file. Follow the update steps in build.md: baseline, ops, `merge`, then `diff` to prove the rest is unchanged, then `verify`.

## Reporting
State the verdict from `verify`, in plain words:
- **PASS**: say which themes and widths ran, which screenshots you looked at, and the risks the review will show.
- **FAIL**: give the failures as they are. Don't hide a failure as flaky, even if a re-run passed.
- **UNVERIFIED**: no dev server, so only the static checks ran. Say so and give the command to finish: `yarn dev` in the app repo, then `verify`.

Never commit, and never change app source from this skill. If the tools or the in-app AI's rules get in the way, work around it and list the gap as a proposed app change for the user.
