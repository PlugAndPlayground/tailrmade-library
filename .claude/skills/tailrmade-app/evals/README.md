# Evals

Acceptance tests and worked examples. Each folder holds what the skill wrote for one prompt. Rebuild with `app.py ops`, `tmapp.py layout` and `app.py verify`, as in `references/build.md`.

| Folder | Prompt |
|---|---|
| `apps/tip-calculator` | "Make a tip calculator: bill, tip percent and number of people, showing what each person pays." |
| `apps/currency-converter` | "Make a currency converter that uses a live exchange rate API." |
| `apps/pattern-maker` | "Make an app that draws a pattern on a canvas, with sliders to change it." |
| `apps/weather-fahrenheit` | "Add a Celsius and Fahrenheit switch to the Simple weather app, and don't touch anything else." |

`weather-fahrenheit` needs the library's `apps/examples/Simple weather app.tmapp`. Its ops hold that file's layout ids, so regenerate them with `inspect_surface` if the file has changed.

An old file to explain: `git show 3c7e4ef:"apps/examples/Access APIs.ppgraph"` in the library repo, version 0.1.
