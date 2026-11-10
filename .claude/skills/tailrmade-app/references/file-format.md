# File format

Checked against `src/PPStorage.tsx`, `src/classes/GraphClass.ts` and `src/utils/graphMigrations.ts`. If they disagree with this page, they win.

## Encoding
A file (`.tmapp` or `.ppgraph`) is plain JSON, or URL-safe base64 of zlib-compressed JSON with the padding removed. `tmapp.py decode` and `encode` handle both. The extension says nothing about the encoding or age.

## Top level
`id` (`Default/<name>`), `location`, `name`, `access`, `graphData`, `date`, `owner`, `isRemote`.

## graphData
- `version`: the app's `GRAPH_DATA_VERSION` (`src/utils/graphMigrations.ts`) is current, 12 as of November 2026. `tmapp.py` reads it from the app repo. Older files, such as 0.1, migrate when loaded and can have `layouts` instead of surfaces.
- `nodes`, `links`, `groups`.
- `graphSettings`: `showExecutionVisualisation`, `viewportCenterPosition`, `viewportScale`, `defaultUISurfaceNodeId`, `theme` (for example `{"mode": "dark"}` or `{"presetId": "newsprint", "mode": "light"}`; absent means untouched).
- `overlay.dashboard`: `visible`, `fullscreen`, `maximized`, `widthPercentage`, `locked`.

**Judge an old file from its migrated export** (`app.py export`), not the raw file: a legacy file with `layouts` does get a UI after migration.

## Node
`id`, `name`, `type` (lowercase key, such as `customfunction`), `x`, `y`, `width`, `height`, `socketArray`, `updateBehaviour` (`load`, `update`, `interval`), optional `comment`, sometimes `version`.

A node left on its default name is exported **without** `name`. Set a real name on every node.

## Socket
`socketType` (`in`, `out`, `trigger`), `name`, `dataType` (a JSON string like `{"class":"NumberType"}`), `data`, sometimes `visible`, `dependentSocketName`.

A linked input is exported without `data`. Some types are never saved at all: a Shader's `Images` is dropped, so left unwired it warns "Not a JSON" on every load. Wire a function returning `{}` into it.

## Link
`sourceNodeId`, `sourceSocketName`, `targetNodeId`, `targetSocketName`. The app does not keep their order, so compare with `tmapp.py diff`.

## Group
`id`, `name`, `color`, `nodeIds`. The frame is worked out from its nodes; there are no stored positions.

## Pages
A page is a `uisurfacenode`. Its `Layout JSON` socket holds `data.tree`, a craft.js map of key to item:

- `ROOT`, `Container`, `Text` and `DynamicWidget` items. `type.resolvedName` says which.
- `parent` and `nodes` link them, and must agree.
- A widget's `props.id` is `NODE_<nodeId>` (or `SOCKET_...`).
- Each linked widget needs its trio of sockets on the surface: `X`, `X visible`, `X layout`, plus the ReactUI link into `X`. **Removing a widget means removing all of them**, or the socket comes back.

Prefer `inspect_surface` and `set_layout_value`, which hide all this.

## What changes when the app saves
Measured on a current file:
- Saving twice is stable: export, reload and export again gives the same app apart from `date`.
- First export of a hand-edited file may change: `date`, link order, rounding of `x` and `y`, a Label's `width` and `height` (measured from its text).
- A custom function's input `dataType` is inferred from the wired value at run time and can flip between saves. `tmapp.py diff` ignores it.
- Any field the app does not know about is dropped. See `update` in [build.md](build.md).
