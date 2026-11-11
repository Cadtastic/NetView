# NetView themes

A theme is one CSS file that sets the colour and shape tokens on `:root`. All component styling lives in
`css/app.css` and reads only these tokens, so a theme never needs to know about the markup.

## Where themes live

- Built-in themes ship with NetView in this folder: `daylight`, `graphite`, `harbor`, `contrast`.
- Your own themes go in the `themes` folder inside the NetView data directory: `<data_dir>/themes`.
  The Appearance tab of the settings dialog shows the exact path. Drop a file in and reopen the
  dialog; no restart is needed. Your themes are listed with the id prefix `user-`.
- The file name (without `.css`) is the theme id. It must match `^[a-z0-9][a-z0-9-]{0,40}$`.

**The quickest start is to copy `graphite.css` into your themes folder, rename it and edit the values.**

## The header

The first thing in the file must be this comment, on one line or several:

```css
/* netview-theme name="Graphite" scheme="dark" preview="#1b1f24,#4fb3c8,#e4e8ec" */
```

- `name`: the label shown in the theme picker.
- `scheme`: `light` or `dark`. It should match the `color-scheme` you set below.
- `preview`: three `#rrggbb` colours (page, accent, text) used to draw the swatch in the picker.

A file with a missing or malformed header is listed with an error and cannot be selected.

## The token contract

Define every token on `:root`, plus `color-scheme`.

| Token | What it colours |
|---|---|
| `--bg` | The page background, and the sticky table header. |
| `--surface` | Top bar, cards, tiles, dialog and popovers. |
| `--surface-2` | Recessed areas: the dialog rail, group rows, chips. |
| `--surface-hover` | Hover state for rows, buttons and menu items. |
| `--border` | Hairlines between rows and around cards. |
| `--border-strong` | Borders of inputs and buttons, and the table header rule. |
| `--text` | Primary text. |
| `--text-muted` | Secondary text: labels, meta, inactive tabs. |
| `--text-faint` | Placeholders and disabled text. Not for anything that must be read. |
| `--accent` | The one accent: active tab underline, primary button, selected segment, links. |
| `--accent-contrast` | Text and icons drawn on top of `--accent`. |
| `--focus` | The keyboard focus ring. |
| `--ok` | Status: online. |
| `--warn` | Status: quiet. |
| `--bad` | Status: offline, errors. |
| `--idle` | Status: unknown, and the off state of switches. |
| `--series-1` | Chart series 1. |
| `--series-2` | Chart series 2. |
| `--series-3` | Chart series 3. |
| `--series-4` | Chart series 4. |
| `--chip-bg` | Optional. Background of solid capability chips; falls back to `--border-strong`. |
| `--chip-fg` | Optional. Text on solid chips; falls back to `--text`. Keep the pair at 4.5:1. |
| `--shadow` | Shadow (any `box-shadow` value) under the dialog, popovers and toasts. |
| `--radius-s` | Corner radius of buttons, inputs and small controls. |
| `--radius-m` | Corner radius of cards, tiles and the dialog. |

## Keeping it readable

- Body text and muted text should reach 4.5:1 against `--bg`, `--surface` and `--surface-2`
  (7:1 for a high-contrast theme). `--accent-contrast` needs the same against `--accent`.
- Keep `--ok`, `--warn`, `--bad` and `--idle` clearly different from `--accent` and from each other.
- Pick the four series colours so they can be told apart on `--surface`, including for colour-blind
  readers. The built-in themes were checked with the dataviz palette validator.
