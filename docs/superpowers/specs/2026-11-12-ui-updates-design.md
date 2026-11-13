# NetView UI updates: account menu, blade layout, customizable dashboard

Date: 2026-11-12
Branch: `feature/ui-updates` (worktree `netview-ui-updates`, based on main 86ff893)
Approved mockup: [2026-11-12-ui-updates-mockup.html](2026-11-12-ui-updates-mockup.html). Open it in a browser and use the three buttons in the dark bar. The owner approved it in full, including the styling.

## Intent

NetView's top bar is crowded, and Admin and Settings each use their own navigation. The owner wants:

- a cleaner top bar;
- Admin and Settings to share one Azure-portal-style "blade" layout;
- a dashboard that each person can arrange for themselves, within limits an administrator sets.

The owner signed off on these points:

- The Admin styling in the mockup is "perfect". Match it.
- Settings uses the same blade layout and the same colours as Admin: a white side menu and the light page background behind the content.
- On the dashboard, Group by offers None, Plugin and Plugin type. "Type" means the plugin's `plugin_type`, not the kind of control.
- A card can be dropped after the last card in a row, without first dropping it in front of that card and then moving it.
- Group by and the save controls appear only while editing.
- The "This device …" text is removed from the top bar.

## Goals

1. Admin moves out of the top-nav tabs and into the account menu.
2. Admin becomes a blade layout with General listed first.
3. The Settings dialog uses the same blade layout.
4. Dashboard cards and tiles sit on one grid that can be rearranged.
5. Administrators set a default dashboard layout.
6. A new role permission lets users save their own layout. A saved layout belongs to their profile only.
7. Users with that permission can move, resize (cards only), hide and show cards, and choose a grouping.

## Non-goals

- Free placement with gaps or explicit row and column positions. The layout is an ordered list that flows onto a 12-column grid.
- Changing card heights, or resizing the small stat tiles.
- Different layouts per browser or device. A layout belongs to a user, not to a browser.
- A "view as role" preview. The "Mockup only, signed in as" switch exists only in the mockup.
- Dragging on touch screens. Touch users get the keyboard and button alternatives described below; drag-and-drop is for mouse users.
- Restyling pages other than Admin, Settings and the dashboard.

## Anti-goals (failures even if everything technically works)

- **Cards losing live state.** Dashboard cards are persistent (`createCardGrid` in `pages/dashboard.js`): charts, open `<details>` and half-typed forms survive every update. Rearranging, regrouping, entering or leaving edit mode, and saving must move the existing nodes, never rebuild them.
- **Layouts that break when a plugin is reinstalled or its folder is renamed.** Saved data is keyed by plugin guid, never by source id. This follows the 2026-11-12 plugin identity spec.
- **Another user's layout changing silently.** Saving to your profile affects only you. Only an administrator's explicit "Reset everyone to the default" touches other people's layouts.
- **Permissions enforced only in the browser.** The server checks every write.

## 1. Top bar and account menu

- Remove the "This device <ip> (<hostname>)" text. That is the `#meta` element in `index.html`, filled in by `main.js`. Delete the element and the code that fills it, and keep the `/api/v1/host` call only if something else uses it.
- Remove the Admin tab. `withAdminRoute` stops adding a nav tab, but the `#/admin` route stays.
- The account menu becomes:
  1. name and "Signed in with …";
  2. **Admin** (shield icon), only when `canSeeAdmin(auth)`;
  3. **Settings** (gear icon);
  4. **Change password** (local accounts only, as today);
  5. **Sign out**.
- *Builder's call:* the existing gear button stays in the top bar as a shortcut to Settings. The mockup draws a theme icon there, which was a mockup placeholder.

## 2. The blade layout (shared by Admin and Settings)

A reusable front-end component that matches the mockup:

- **Breadcrumb bar** across the top, e.g. `Admin › Users › Edit Addam`. Earlier parts are links: clicking the section part closes any open child blade.
- **Side menu**, 230 px wide, with a white background:
  - a "«" button that collapses it to an icon rail;
  - a Search box that filters items by label as you type;
  - optional groups with a small collapsible heading (chevron plus label);
  - items with a Tabler-style icon, a label and an optional count on the right;
  - the selected item has the light fill and a 3 px accent bar on the left.
- **Content blade:** page background `--bg`, an h1 title, a muted subtitle, and a **command bar**. The command bar is a row of borderless accent-coloured icon-and-text buttons with a hairline underneath. It replaces the big primary buttons that sit in card headers today.
- **Child blade:**
  - 420 px wide; slides in from the right over the content blade, with a shadow on its left edge;
  - header with a title and a close (X) button;
  - scrollable body;
  - footer with the primary action, Cancel, and a right-aligned danger action where one applies.
  - Opening it adds its title to the breadcrumb.
  - Esc closes it, and focus moves into it on open and back to the opener on close.
  - Unsaved edits are dropped on close, the same as today's dialogs.
- The current selection is kept in the URL hash so reload and Back work: `#/admin/<section>`, and in Settings the existing tab ids.
- Colours come from the theme variables so every theme works: `--surface`, `--bg`, `--border`, `--accent`, `--text`, `--text-muted`, `--surface-2`, `--surface-hover`.

## 3. Admin

- Route `#/admin`, defaulting to the first section the user may open. `#/admin/<section-id>` opens a given section.
- Side menu, in this order:
  - **General** (`core.system`), with no group heading;
  - group **Identity**: **Users** (count) and **Roles** (count), both `core.users`;
  - group **Dashboard**: **Default dashboard** (`core.system`).
- Sections the user can't open are left out, as `adminSections` does today.
- **Users:**
  - The command bar has Add local user and Refresh. The table matches today's.
  - Clicking a row opens the **Edit user** child blade with the same fields as today's edit dialog: display name, roles, enabled, reset password, and Delete with its confirm step.
  - Add local user opens an **Add local user** child blade.
  - The built-in admin row's "Change password" opens a child blade too, or the self-service dialog when it's your own row, as today.
- **Roles:** clicking a row opens the role editor in a child blade, and New role sits in the command bar. Fields and behaviour are unchanged.
- **General:** today's General settings, with Save and Discard changes in the command bar.
- **Default dashboard:**
  - Subtitle: "The layout new users start with, and what anyone gets when they choose Reset to default."
  - Command bar:
    - **Edit default layout** opens the dashboard in default-editing mode (see 5.5).
    - **Reset everyone to the default** deletes every saved user layout, after a confirm step.
  - The body shows which roles have **Customize my dashboard**, and how many users have their own layout.
- `openAdminDialog` (`pages/admin/dialog.js`) is replaced by the child blade wherever Admin uses it. The password rules tooltip behaviour from `fix/password-rule-tooltips` must carry over if that branch merges first.

## 4. Settings

- Still a modal dialog, opened from the account menu, the gear button, and the existing `openSettings(tabId)` callers.
- The inside uses the blade layout: a breadcrumb under the dialog title, the side menu, the content blade, and child blades.
- Side menu:
  - group **Personal**: **Appearance**, **My dashboard**;
  - group **Plugins**: **Installed** (count), **Available** (count).
- The Plugins group keeps its collapsible behaviour and the "is it open" memory it has today.
- Existing tab ids still work, and `resolveTab` keeps its contract. `plugin:<id>` opens Installed with that plugin's child blade open.
- Picking an installed plugin opens its detail as a **child blade**: enable switch, settings form, and Save / Cancel / Uninstall. This replaces the current overlay (`settings/overlay.js`).
- **Not included (owner's decision):** the mockup's "Show on dashboard" checklist in the plugin blade was a placeholder. Cards are hidden and shown only through Customize on the dashboard.
- **My dashboard** says whether you use your own layout or the default, shows when it was saved, its grouping and how many cards are hidden, and has **Reset to default** in the command bar. That deletes your saved layout.
- The side menu is white, and the content blade's background is `--bg`, as in Admin.

## 5. Dashboard

### 5.1 Grid and items

- One 12-column grid holds both the stat tiles and the cards. Today tiles have a row of their own above the cards.
- Tiles always span 2 columns.
- Cards span **third (4)**, **half (6)** or **full (12)**. The card spec's existing `span` values map straight across.
- Items flow in layout order, with no gaps.
- Every item has a stable **layout key**, `<owner>.<kind>.<id>`:
  - `<owner>` is `core` for what core draws itself: the online, quiet, offline and sweep tiles, and the watches and events cards. For anything a plugin contributes, it is the plugin's **guid**. That includes the built-in plugins under `src/netview/plugins/builtin`, such as Health and This device.
  - `<kind>` is `tile` or `card`. Health registers both a tile and a card with id `dns`, so the kind keeps them apart. The plugin slot contract doesn't change.
- The current `cardKey` (`<source id>.<id>`) stays as the DOM and runtime key. The layout key is separate.
- **Grouping built-ins (owner's decision):** items from core and from the built-in plugins all go in one group: "NetView" under Group by Plugin, and "NetView (built in)" under Group by Plugin type. Built-in plugins don't get groups of their own, and don't appear under their `plugin_type` (software).
  - The builder uses whatever the plugin list already exposes to tell a built-in plugin from an installed one. If nothing does, add a flag.
  - Third-party plugins group by display name, or by their `plugin_type` label. A plugin with no `plugin_type` goes under "Other".

### 5.2 The layout record

```json
{"version": 1,
 "order": ["core.tile.online", "c66a564b-…-1c7f6ebae6be.tile.ports", "<health guid>.card.latency"],
 "hidden": ["<local_host guid>.tile.wifi"],
 "spans": {"<health guid>.card.latency": "half"},
 "group": "none"}
```

- `group` is `none`, `plugin` or `plugin_type`.
- `spans` lists cards only. A missing entry means the card's own default.
- Applying a layout to the items present now:
  1. Keys in `order` that match a present item are placed in that order.
  2. Present items missing from `order` (new plugins, new cards) go after them, in their default order (`order` field, then registration). They are visible.
  3. Keys for items that no longer exist are ignored. They're dropped the next time the layout is saved.
  4. Hidden keys are left out of the grid and listed in the Hidden cards tray while editing.
- The **built-in default**, used when no administrator default exists, is today's ordering with nothing hidden and `group` none.

### 5.3 Viewing mode

- The layout used, in this order of preference:
  1. your saved layout, if you have one **and** your roles still include `core.dashboard`;
  2. the administrator default;
  3. the built-in default.
- With `core.dashboard`, a **Customize** button sits at the top right of the dashboard. Without it there is no button. The mockup shows "Layout set by your administrator" in that case, and the builder may keep that text.
- With a grouping, each group has a heading: chevron, name, and item count. Clicking the heading collapses the group. *Builder's call:* collapse state is per browser in localStorage, not saved to the profile.
- Group order is the built-in group first, then alphabetical by name.

### 5.4 Edit mode (Customize)

- A toolbar replaces the Customize button. It has:
  - **Group by** (None / Plugin / Plugin type);
  - **Save to my profile** (primary);
  - **Save as default for everyone**, only with `core.system`;
  - **Reset to default**, which loads the default into the editor and is saved only when you press Save;
  - **Cancel**, which restores the layout from before editing.
- An info banner reads: "Drag cards to move them. Changes are only yours, and only kept when you save."
- *Builder's call:* **Reset to default, then Save.**
  - If you press Reset to default and then Save without changing anything else, your saved layout is **deleted** (`DELETE`). You follow the default again, including later changes to it.
  - If you change anything after the reset, Save stores your layout as usual (`PUT`).
  - So "users with their own layout" counts only people who really differ.
- *Builder's call:* **Save as default for everyone, from your own edit mode.**
  - This saves the edited layout as the default.
  - It also deletes the administrator's own saved layout, so they see the default they just saved.
  - It doesn't touch anyone else's layout.
- Each item gets:
  - a dashed outline and a grip mark;
  - a **width** button (cards only), cycling third → half → full;
  - a **hide** button.
- **Hidden cards** tray under the grid: one chip per hidden item. Clicking a chip shows that item again, at its previous position in `order`.
- **Drag and drop** (mouse):
  - Dragging over a card shows an accent bar on the side the card will land: the left half means before, the right half means after.
  - Dragging over empty grid space shows the bar on the nearest card in that row:
    - before the first card to the right of the pointer;
    - otherwise after the last card in the row;
    - in an empty group area, the end of the group.
  - Dropping moves the item in the single `order` list.
  - With a grouping, a card can only move within its own group. Dragging over another group does nothing, and a toast says "Cards stay in their own group".
- **Keyboard:** in edit mode, items are focusable. *Builder's call:* Ctrl+Left/Right moves the focused item one place within its group, and the width and hide buttons are reachable with Tab. Announce moves through an `aria-live` region.
- Cards keep updating while editing, and none is re-created (anti-goal 1).
- Leaving the page or signing out while editing discards the changes. *Builder's call:* no "unsaved changes" prompt.
- Toasts:
  - "Saved to your profile. Only you see this layout."
  - "Saved as the default layout for everyone"
  - "Changes discarded"

### 5.5 Editing the default (administrators)

- Admin › Default dashboard › Edit default layout opens the dashboard in edit mode, loaded with the current default.
- The banner reads: "Editing the default layout for everyone. Users who saved their own layout keep it until they reset."
- The toolbar shows Group by, **Save as default for everyone** (primary) and Cancel.
- This mode never touches the administrator's own saved layout.

### 5.6 Permission

- New core permission in `CORE_GROUP`, placed after `core.view`:
  `PermissionInfo("core.dashboard", "Customize my dashboard", "Arrange, resize, hide and group dashboard cards and save the layout to your profile")`.
- Administrators get it, as they get everything.
- *Builder's call:* the migration does **not** add it to the built-in Default role. An administrator grants it.
- Losing the permission doesn't delete a saved layout. It stops being used (see 5.3).

### 5.7 Storage and API

- New core table `user_dashboard_layouts`:
  - `user_id` (PK, FK `users.id` ON DELETE CASCADE);
  - `layout` (JSON text);
  - `updated_ms`.
- Added by Alembic migration `0007` in `infrastructure/db/core_versions`.
- The administrator default is stored in `app_settings` under the key `dashboard.default_layout`.
- Endpoints. All use the existing session auth and CSRF rules.

  | Method and path | Who may call | What it does |
  |---|---|---|
  | `GET /api/v1/dashboard/layout` | `core.view` | Returns `{layout, source: "user" \| "default" \| "builtin", updated_ms}`, applying 5.3 |
  | `PUT /api/v1/dashboard/layout` | `core.dashboard` | Saves your layout |
  | `DELETE /api/v1/dashboard/layout` | `core.view` | Deletes your own layout (Reset to default from Settings) |
  | `GET /api/v1/admin/dashboard/default` | `core.system` | Returns `{layout, users_with_own_layout, roles_with_permission}` |
  | `PUT /api/v1/admin/dashboard/default` | `core.system` | Saves the default |
  | `DELETE /api/v1/admin/dashboard/layouts` | `core.system` | Deletes every user's saved layout and returns the count |

- **Validation, server side:**
  - `version` is 1;
  - `group` is one of the three values;
  - `spans` values are `third`, `half` or `full`;
  - every key matches `^(core|[0-9a-f-]{36})\.(tile|card)\.[A-Za-z0-9_-]{1,100}$`;
  - at most 500 keys in total;
  - body at most 64 KB.
- The server doesn't check keys against the items present, because plugins come and go.
- Bad input returns 422 with field errors in the existing format.
- Layering follows the project's import-linter contracts: a use case in `application`, a repository port, and the SQLAlchemy implementation in `infrastructure`.

## 6. Constraints

- Plain ES modules, no new front-end dependencies. Drag and drop uses the HTML5 API.
- The mockup's icons are Tabler. NetView has its own `icons.js`, so the builder uses that, adding SVGs as needed. Pulling in an icon font is not allowed.
- All gates stay green:
  - `uv run pytest -q`
  - `npm test`
  - `uv run ruff check .`
  - `uv run mypy src plugins`
  - `uv run lint-imports`
  - `uv run python scripts/build_plugin_index.py --check`
- Pure front-end logic gets `node --test` tests: layout apply and merge, the drop-position maths, grouping, and the blade breadcrumb and state.
- Every theme in `static/themes` must look right. Only theme variables are used.
- Commits use the no-reply author email already configured in this worktree.

## 7. Left to the builder

- How the blade component is split into modules. One shared module, used by both Admin and Settings, is expected.
- Exact animation timing, around 180 ms ease. Respect `prefers-reduced-motion`.
- How the collapsed side menu looks.
- The order of work, as long as each step leaves the app working.
