# Tailrmade Library

Open library of [Tailrmade](https://tailrmade.app) apps, macros and segments. Fork them, remix them, learn from them.

## What's here

```
apps/
  examples/    The examples built into Tailrmade
  drafts/      Examples still being worked on
.claude/
  skills/
    tailrmade-app/   A Claude Code skill for building and testing apps
```

Folders for macros and segments will follow.

## Open an app

1. Download a `.tmapp` or `.ppgraph` file from `apps/examples/`.
2. Go to [tailrmade.app](https://tailrmade.app) and drag the file onto the canvas.

Every app opens with its full graph visible, so you can see how it works and change anything.

## Build apps with Claude Code

This repo includes a [Claude Code](https://claude.com/claude-code) skill, [`tailrmade-app`](.claude/skills/tailrmade-app/SKILL.md). Open Claude Code in this repo and ask in plain words, for example:

- "Make me an app that tracks how much water I drink"
- "Explain how `Mood journal.tmapp` works"
- "Add a dark mode switch to the weather app"
- "Verify `Bluesky live.tmapp`"

The skill builds apps with Tailrmade's own tools rather than writing the file by hand. Then it runs them in the real app: in three themes, at desktop and phone width, pressing every button. It looks at the screenshots and reports PASS or FAIL, along with the risks the app's review will show (network, AI and so on).

**Setup**

1. Install Python 3 and Chrome.
2. Check out the [tailrmade](https://github.com/PlugAndPlayground/tailrmade) app repo next to this one, as `../tailrmade`, and run `yarn install` there.
3. Run `yarn dev` in the app repo before you ask for a verify.

Without the dev server, the skill still checks the file, but it reports the app as UNVERIFIED. If the app repo is somewhere else, set `TM_APP_REPO` to its path. If the dev server isn't at `http://127.0.0.1:8080`, set `TM_BASE_URL`.

Worked examples, each with its plan, build steps and test scenarios, are in [`evals/apps/`](.claude/skills/tailrmade-app/evals/apps).

## Status

This repo is the version-controlled source of the examples built into Tailrmade.

## Contributing

We're not accepting submissions yet. Issues and suggestions are welcome.

## License

[MIT](LICENSE). The Tailrmade app itself is licensed separately; see the [tailrmade](https://github.com/PlugAndPlayground/tailrmade) repo.