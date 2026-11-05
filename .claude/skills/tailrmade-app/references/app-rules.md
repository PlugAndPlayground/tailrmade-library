# App rules

Each of these cost a round of trial and error. Follow them unless the app's purpose says otherwise, and say so when it does.

## Native first
- Use Text, inputs, buttons, containers, HTTP and Custom Function nodes before HTML nodes.
- A wired HTML node always gets a network warning, even with sanitize on, so use it only when nothing native works. Example: Met images load in a plain `<img>` but not with `crossOrigin`, so the Image node can't show them. A Text node has no risk and takes `{{r.x}}`.
- Custom functions have no risk unless Main Thread is on, so keep it off unless the code needs the DOM. A function in Main Thread blanks everything downstream until the app is reviewed, so keep it off the path to page text.
- For a picture from numbers, a Shader takes uniforms from a sandboxed function and has no risk. `{ value, type: 'f32' }` or `{ value: [r, g, b], type: 'vec3<f32>' }`.
- Pin LoadNPM versions. An unpinned name runs whatever is latest on esm.run at load.

## Custom functions
- A node's name is the code text before the first `(`, reset on load. Start code with `(`. `async (a) =>` renames the node "async", so return a promise from a plain arrow function.
- The sandbox (QuickJS) has no locale data: `toLocaleString` neither rounds nor groups, and printed `110.00000000000001`. Use `toFixed` and a regular expression.
- Set Code before wiring: parameters become sockets only then.

## Theme
- Colours come only from container `emphasis` and `tone`, Text `variant` and `tone`, the button `Inherit` variant and theme classes in HTML nodes (`bg-paper`, `text-foreground`, `text-muted-foreground`, `border-divider`, `text-primary`, `font-theme`, `rounded-theme`). No fixed colours, unless brand colours are the point of the app, as in Brand echo; then only the card keeps them and it sets its own text colour.
- Strong emphasis with neutral tone gives an opaque, theme-driven background.
- Newsprint's primary is black, so a highlight in primary vanishes inside black text. To mark one word, have a function return `[word]{.secondary}` and wire it into a Text node's Content socket.
- A `{{r}}` token inserts its value literally, so Markdown in a value shows raw. Wire Markdown into the Content socket instead.
- Migrated legacy text can show literal `<span style=...>`. Rewrite it as plain content with variant and tone.
- Element Renderers and function code don't get theme variables. Wire the Theme node's `Theme` output (`tokens.primary`, `tokens['text.primary']`, `tokens['background.paper']`) into the function. It updates on load, not on a live preset switch.
- Table2 ignores themes and stays light. Keep it on the page only when editing the data is part of the demo.
- Graph nodes (pie, scatter, line) draw black axes in every theme, so put them on a white plate.

## Mobile
- Check at 390px and at desktop width, with no sideways overflow.
- 900px is where the app switches to one view at a time. Rows stack below 600px unless `mobileBehavior` says otherwise.
- Use a fixed px width for controls that shouldn't stretch. `width: 100%` in a row shrinks from a 100% basis; `50%` with a `maxWidth` works for a control sharing a row.
- `maxWidth` and `customStyles` go through `props` in a layout spec. Container `customStyles` take `@media` keys.
- Set the page width on the root with `"props": {"maxWidth": "md"}`: one of `xs` (444px), `sm` (600), `md` (900), `lg` (1200, the default), `xl` (1536) or `false` (full width). The root centres itself. Don't cap the root's children with px `maxWidth`: the root ignores `align` and stretches its children, so a capped child sits at the left.
- Draw widgets scale with `height: 'auto'`. The renderer overwrites an element's size with the widget's: use `auto` for a canvas or an SVG with a viewBox, fixed height only for what has no intrinsic size.
- A sticky element must sit on the page surface, whose root needs `overflow: visible`.

## Every state must work
Opening, loading, empty, not found and failed requests.
- An HTTP node always sends and nothing downstream can stop it. When an earlier answer is empty, give the next request a valid fallback address and show the message on the page.
- A failed request returns `{}`, the same as the socket's default, with no status output. The page opens only after the first requests finish ("Loading user interface"), so on the page `{}` means it failed.
- Label results from the answer, not the inputs, so an old rate never appears under a new currency.
- Layout must not jump when results vanish. Return a non-breaking space for each blank line, so it keeps its height.
- Big `cqw` numbers need `lineHeight` equal to `fontSize`; less clips the glyphs.
- A Number Field can't be empty: clearing it never reaches the graph and leaving the field brings the last value back. Its empty state is 0. Use a Text Field if "nothing entered" must be seen.

## External APIs
- Test from Chrome, not curl. The Art Institute works in curl but is blocked in Chrome.
- Prefer keyless APIs, and a manual trigger over intervals. Manual: `set_update_behaviour` with `update: false`, then `add_trigger_input`, then wire a button's `Out` to `Trigger 1`. One click is one request.
- A chain from one button works: only the first HTTP node has the trigger, later ones use `load: false, update: true`. They re-send even when the address stays the same.
- Treat API text as messy. Cat facts contain stray backslashes and quotes, which then get read as Markdown.

## Graph readability
- Numbered groups in a hierarchical layout: a parent to the left of its children and centred on them, other sections in one column, generous vertical space. Don't put unrelated sections side by side.
- Group headers keep their screen size at any zoom, about 150-215px by 32px, so they grow in world units as you zoom out. Check for collisions in a screenshot at the opening zoom.
- A "Start here" label, real names on every node, and a short comment only where a choice isn't obvious. Say why, not what.
- Text and comments are for someone new to the app. New nodes placed at 0,0 can fall inside a macro's bounds and move with it.

## Updating an app
- A round trip must preserve unknown fields, the user's text and positions.
- Never overwrite: start from the user's latest copy and write a new file, because they edit between rounds.
- Explain what will change before changing it, and keep the diff small.
