---
name: Tally News
description: The category-standard news aggregator played straight: white and near-black surfaces, system sans, one teal action color, and blue, gray and red lean labels that always carry a word.
colors:
  accent: "#0f766e"
  accent-ink: "#ffffff"
  page-bg: "#f5f6f8"
  surface: "#ffffff"
  line: "#e1e4ea"
  line-strong: "#c4cad5"
  ink: "#12161c"
  ink-muted: "#4a5565"
  left: "#2563eb"
  left-ink: "#1e40af"
  left-bg: "#e6eeff"
  center: "#64748b"
  center-ink: "#3d4a5c"
  center-bg: "#eceff3"
  right: "#dc2626"
  right-ink: "#991b1b"
  right-bg: "#fdeaea"
  warn-ink: "#8a4b00"
  warn-bg: "#fdf1dc"
  warn-line: "#e3b872"
typography:
  page-title:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "28px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  section-heading:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  story-headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  caption:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: "18px"
  code:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  sm: "6px"
  md: "10px"
  lg: "12px"
  pill: "99px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  gutter: "16px"
  lg: "20px"
  xl: "32px"
components:
  card-story:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "16px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "44px"
  button-danger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.right-ink}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "44px"
  pill-left:
    backgroundColor: "{colors.left-bg}"
    textColor: "{colors.left-ink}"
    rounded: "{rounded.pill}"
    padding: "1px 9px 1px 7px"
  pill-center:
    backgroundColor: "{colors.center-bg}"
    textColor: "{colors.center-ink}"
    rounded: "{rounded.pill}"
    padding: "1px 9px 1px 7px"
  pill-right:
    backgroundColor: "{colors.right-bg}"
    textColor: "{colors.right-ink}"
    rounded: "{rounded.pill}"
    padding: "1px 9px 1px 7px"
  badge-type:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    padding: "0 7px"
  badge-new:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.sm}"
    padding: "0 7px"
  switch-on:
    backgroundColor: "{colors.accent}"
    rounded: "{rounded.pill}"
    width: "44px"
    height: "26px"
  switch-off:
    backgroundColor: "{colors.line-strong}"
    rounded: "{rounded.pill}"
    width: "44px"
    height: "26px"
  panel-controls:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "12px 16px 14px"
---

# Design System: News Digest (open news aggregator)

## Overview

**Creative North Star: "The Standard Newsstand Rack"**

This is the look every news aggregator already has, built carefully: a pale gray page, white panels with hairline borders, near-black text in the platform's own sans-serif, and one teal for things you can act on. It sits beside AllSides, Feedly and Ground News on purpose. The product's brand commitment is a familiar, category-standard look at full craft, so nothing here is a costume, a metaphor or a house quirk. Where a convention exists (tabs under a header, a pill beside every outlet, a switch for every setting), the build uses it.

The system makes the rules visible. The ordering rule sits next to the filters, every outlet carries its label as a word, and the coverage of each story is shown as a bar with counts beside it. Density is moderate and utility-first: 15px headlines, 12-13px metadata, 44px minimum touch targets. Light and dark follow the device with no manual toggle.

**Key Characteristics:**
- Flat white panels on a pale gray page (dark: near-black on near-black), separated by 1px hairlines, not shadows.
- System sans at every level; weight and size do the hierarchy, never a second typeface.
- One teal accent, reserved for actions, current location, links and the "New" badge.
- Blue, gray and red mean left, center and right, and are always printed next to the word.
- Phone gets a fixed bottom tab bar with icons; desktop gets a top text nav and a sticky right-hand controls rail.

## Colors

A restrained neutral base, one teal accent, and three muted lean colors used only as a labeled code. Every value below has a dark-mode counterpart that the stylesheet swaps in when the device prefers dark (listed in the sidecar); the frontmatter holds the light values.

### Primary
- **Newsroom Teal** (`accent`, #0f766e; dark #2dd4bf): Actions and place. The active nav underline (desktop) or icon and label (phone), the active section tab underline, "On" switches, links in rules and footers, "Show N more" and the focus ring. Text on it is `accent-ink` (white; dark #06201d). Also fills the "New" badge.

### Secondary (lean code)
- **Left Blue** (`left`, #2563eb): bar segment and dot for left outlets. Text and label use `left-ink` (#1e40af) on `left-bg` (#e6eeff).
- **Center Slate** (`center`, #64748b): bar segment and dot for center outlets. Text uses `center-ink` (#3d4a5c) on `center-bg` (#eceff3).
- **Right Red** (`right`, #dc2626): bar segment and dot for right outlets. Text uses `right-ink` (#991b1b) on `right-bg` (#fdeaea). The same `right-ink` colors the destructive button label.

### Tertiary
- **Warning Amber** (`warn-ink` #8a4b00 on `warn-bg` #fdf1dc with a `warn-line` #e3b872 inset ring): the "Hidden by your Show settings" note on Sources.

### Neutral
- **Page Gray** (`page-bg`, #f5f6f8; dark #0d1117): page background and sticky tab strip.
- **Panel White** (`surface`, #ffffff; dark #161b22): header, footer, story cards, controls panel, lists, code blocks.
- **Hairline** (`line`, #e1e4ea) and **Hairline Strong** (`line-strong`, #c4cad5): panel borders and row dividers; strong is the off-switch track, button border and dashed placeholder border.
- **Near-Black Ink** (`ink`, #12161c; dark #e7ebf0): primary text.
- **Muted Ink** (`ink-muted`, #4a5565; dark #9ba6b5): metadata, descriptions, inactive nav and tabs.

### Named Rules
**The Word-Beside-Color Rule.** Blue, gray and red are a category convention for left, center and right and must always be paired with the word Left, Center or Right (pill, group heading or legend). The coverage bar carries an aria-label with the counts; its legend carries the words. Never use a lean color alone.

**The One Teal Rule.** Teal marks actions and current location only. It is never a lean color, never a status of a side, and never a decorative fill.

**The Lean-Variable Rule.** A lean is applied by setting `--c`, `--c-ink`, `--c-bg` on a `lean-*` class, and pills, dots, bar segments and group headings read those. New lean-aware elements reuse the trio rather than naming a color.

## Typography

**Display Font:** the platform system sans (-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial)
**Body Font:** the same stack
**Label/Mono Font:** ui-monospace stack (SFMono, Menlo, Consolas) for code and the fork instructions only

**Character:** Neutral and native, so the page reads as the reader's own device. Hierarchy comes from weight (400 / 500 / 600 / 700) and a compact size ladder. Numbers are tabular throughout (`font-variant-numeric: tabular-nums` on body) so outlet counts align.

### Hierarchy
- **Page title** (700, 28px, 1.2, -0.02em): H1 on Sources, Settings and Run-your-own.
- **Section heading** (700, 20px, 1.3, -0.01em): news section names (Videos, US, World, Tech); 17px at weight 700 for H2 within secondary pages.
- **Story headline** (700, 19px, 1.3, -0.01em, balanced wrap): the lead headline of a story card.
- **Title** (600 or 500, 15px, 1.35-1.4): outlet-level headlines, video titles (3-line clamp), nav links, tabs, row labels.
- **Body** (400, 16px, 1.5): page text; lede and prose capped at 62-65ch.
- **Caption** (400 to 600, 13px): rule text, stamp, row descriptions, footer.
- **Label** (600, 12px, 18px line): pills, badges, legend, video and outlet metadata. Sentence case; no uppercase, no letter-spacing.

### Named Rules
**The One Family Rule.** Every text role is the system sans at a weight and size from the ladder above; the only other face is the monospace used for code.

**The Quiet Metadata Rule.** Anything that explains an item (outlet, views, counts, hosts, rules) is 12-13px in muted ink; headlines stay in full ink.

## Layout

Single column on phone; on screens 1000px and wider a two-column grid (feed plus a 288px sticky controls rail, 32px gap) inside a 1160px centered container with a 16px gutter. Secondary pages (Sources, Settings, Run-your-own) are one 820px column. Section order on the news page: stamp line, videos, then one block per section of ranked story cards, then an end line.

Breakpoints in use: 720px (phone to desktop: nav moves from a fixed bottom bar to the header, video row becomes a grid, story groups become three columns separated by vertical hairlines) and 1000px (controls panel moves from a compact row above the feed to a right rail). Spacing is a 4px-based rhythm with a 16px gutter: common steps 4, 8, 12, 14, 16, 20, 32; section headings sit 28px above and 12px below.

On phone the Show controls collapse to one wrapping row of 44px chips with the ordering rule beneath, so the news starts higher. The video row is a horizontally scrolling snap strip (72vw up to 260px per card) and always holds every video; on desktop it is an auto-fill grid (cards at least 200px) that shows six until "Show all videos" is pressed. Sticky section tabs sit at the top with a 64px scroll offset. Body gets bottom padding on phone to clear the fixed tab bar and safe-area inset.

## Elevation & Depth

Flat. Depth is tonal: the page is gray, panels are white, and 1px hairlines separate them. There are no card shadows. The only shadow is a small 1px drop under the white switch thumb (`0 1px 2px rgba(0,0,0,.35)`). Sticky elements (tab strip, controls rail, bottom tab bar) are distinguished by their background and a hairline border, not by shadow. Motion is minimal: switch transitions of 150ms and smooth anchor scrolling, both disabled under reduced motion.

### Named Rules
**The Hairline-Not-Shadow Rule.** Panels are separated from the page by a 1px `line` border and a surface fill. Do not add shadows to cards, buttons or headers.

## Shapes

Softly rounded rectangles with a few fixed radii: 12px for panels, story cards and lists (`--radius`), 10px for thumbnails, buttons and code blocks, 8px on the desktop nav link hit area, 6px for rectangular badges, 4-5px for the focus ring and inline code, and a full 99px for pills, chips, switches and the coverage bar. The three-bar brand mark (blue, gray, red rounded bars) and the 8px dots in pills, legend and group headings are the only recurring geometry. Section dividers inside cards are 1px hairlines; there are no thick borders except the 3px underline on the current tab or nav item.

## Components

### Navigation
- **Main nav:** four destinations rendered as text links in the header (desktop) with a 3px teal inset underline on the current page; on phone a fixed bottom tab bar of equal-width items with a 24px line icon over a 12px label, current item colored teal. Minimum 44px tall (56px on phone).
- **Section tabs:** a sticky strip below the header, scrolling horizontally if needed, 15px 600-weight links with a teal underline for the current section; on desktop it is prefixed by a muted "Jump to" label.
- **Brand:** the three-bar mark beside the site name in 18px bold.

### Show controls (filter panel)
- **Desktop:** a white panel titled "Show" with three switch rows (Left, Center, Right pills), the ordering rule below a hairline, and links to All settings and Sources.
- **Phone/tablet:** the same buttons as wrapped 44px pill chips. On: ink border. Off: strong-line border, 60% opacity and line-through. The pill and badge lose their fill inside a chip.

### Switch row
- A whole-row 44px button with a label (15px 600) and optional description (13px muted), and a 44x26 track with a 20px white thumb. On: teal track and thumb moved 18px. Off: `line-strong` track. Used in Show controls, Settings and Sources.

### Lean pill and badges
- **Pill:** 12px 600 label with an 8px lean-colored dot, in `lean-bg` with `lean-ink` text, fully rounded. It always contains the word.
- **Type tag:** muted text, no fill, 1px hairline inset ring, 6px radius (outlet funding or ownership, shown on the Sources and story pages).
- **Gap badge** ("Not covered by: left and right"): teal text on a 12% teal tint. **New badge:** white (dark: near-black) on solid teal. Shown only when the browser has a last-visit time.

### Story card (signature component)
- White panel, 1px hairline, 12px radius, 16px padding (20px 22px on desktop). Structure top to bottom: one 19px bold headline, the coverage bar (8px high, rounded, segments flex-sized by outlet count with a 6px minimum, 2px gaps), a legend of lean dots with word and count, a meta line with outlet total and badges, then three lean groups (Left, Center, Right), each with a colored dot heading, a count at the right, and rows of outlet headline (15px 500) over the outlet name. More than the row limit folds into a "Show N more" disclosure in teal. An empty side says "No coverage from this side."
- On phone the groups stack; on desktop they sit in three columns divided by vertical hairlines.

### Video card
- A 16:9 thumbnail (10px radius), a meta line (lean pill, outlet name, views), and a 15px 600 title clamped to three lines that underlines on hover.

### Story row and summary
Stories in US, World and Tech are collapsed rows (headline, coverage bar, outlet count, chevron); one opens at a time. The open row leads with a two-sentence machine-written summary (16px, 68ch, with a 12px muted label saying so), then the legend, flags, timeline and each outlet's own headlines by side. First-reported timing sits inside the timeline when a summary is shown.

### Breaking
When the rule finds any, a "Breaking" section sits above Videos and joins the jump tabs. Its stories use the same collapsed rows as every other section (moved out of their topic section, never shown twice). A row carries a small amber "Breaking" badge (warn tokens, with the word; never red, which is reserved for the right lean) and "first reported N min ago", kept current by script. No flashing, sound or counters: signals inform, they do not pressure.

### Blindspots
When the rule finds any, a "Blindspots" section opens the topic sections and joins the jump tabs (after Clips, before US). It reuses the briefs list (one bordered white list of 12px 16px rows): each row is the story's neutral label as a link to that story's row below, then one muted 13px line with the side pill (word always present) and "N outlets, all labelled <side>. Nothing yet from <other sides> outlets." A 13px note under the heading says it is a count, not a claim that anyone is hiding the story, and links to the Methods page. No new color: the pill carries the side; absence is stated in words. Section notes under Breaking and Blindspots use `.sec-note`, which stays visible at every width (`.hint` is phone-only).

### Briefs list
- Single-outlet items under a collapsed "Reported by one outlet" toggle (count beside it, drawn chevron) at the end of US, World and Tech: one white bordered list of 12px 16px rows, each headline with its pill and outlet.

### Buttons
- **Secondary (the only button):** 44px tall, 16px side padding, 10px radius, white surface, 1px strong-line border, 15px 600 ink label; hover darkens the border to muted ink.
- **Danger:** same button with `right-ink` text.

### Lists and source rows
- A white bordered 12px-radius list with hairline row dividers. A source row shows name, optional type tag, host and feed link, the lean pill, a plain status line and a switch; on phone it is two columns, on desktop three columns (name, meta, switch).

### Footer and notes
- White footer with a top hairline holding three 13px muted lines (ordering rule, label disclaimer, code and license). Unknown facts show as dashed-border placeholders ("not published yet"), never invented values. Code blocks are surface-white with a hairline border and wrap long lines.

### Focus
- Every focusable element gets a 3px teal outline with 2px offset on `:focus-visible`.

## Do's and Don'ts

### Do:
- **Do** print the word Left, Center or Right wherever a blue, gray or red lean color appears (Word-Beside-Color Rule).
- **Do** keep the page flat: gray background, white surfaces, 1px `line` borders, radii from the Shapes list.
- **Do** use teal only for actions, current location, links and the New badge.
- **Do** keep every interactive target at least 44px tall and every state (current, off, focus) visible without relying on color alone (underline, line-through, outline).
- **Do** state any rule that affects ordering or visibility in plain text next to the control it affects.
- **Do** use dashed-border placeholders for facts that do not exist yet.
- **Do** keep light and dark following the device by changing only the custom properties.

### Don't:
- **Don't** introduce a second typeface, display type or uppercase tracked labels; the system sans ladder is the whole voice.
- **Don't** add card shadows, gradients, glass or decorative imagery; depth is tonal.
- **Don't** use lean colors for anything other than lean, or teal for anything other than action and place.
- **Don't** add rankings by engagement or any color that implies a side is good or bad. Model-written text is always labelled as machine-written, and no perspective text is added yet (decided 2026-11-13).
- **Don't** hide a rule inside a tooltip or a file; it belongs on the page.

## Analytics components (added with the reader-facing analytics)

- **Facts line:** one 13px sentence under a story's meta line ("First reported by X at T. All three sides had covered it by T2"). Bold outlet names, muted ink otherwise.
- **Coverage timeline:** a three-lane strip chart in a disclosure. One lane per side (dot and word), one 10px dot per outlet in the side's color with a 2px surface ring and a 24px hit area, hairline lane rules, only the first and last times labeled, a tooltip on hover or focus, and a table version of the same times. The side colors were checked with the dataviz validator; the neutral center is a deliberate gray that passes separation but not the chroma floor, so side is always carried by the lane label and position as well as color.
- **Summary line:** a plain paragraph that leads the written coverage, not a stat tile: counts in bold inside a sentence, with a link to how they are counted.

- **Story page:** the news card's parts at page width. A permalink header (crumbs, headline, outlet count, span), the coverage bar and legend, the facts line, then a multi-day coverage timeline (same lane chart; relative ticks such as +12 h and +1 d so no time zone is guessed), every report as a list with its time, side pill and a "Headline changed" outline badge, headline edits as before and after rows where removed words are struck through and added words are underlined (never color alone), and a plain-text citation with Copy and per-story JSON download.
- **Archive page:** a filter field and day-grouped lists of stories, each a headline link over a muted line of counts and first reporter.

- **Clip card:** a 9:16 tile with the clip's preview frame, a round play button and a solid dark scrim (never a gradient) carrying the account name and up to three lines of caption. Cards sit in a horizontal snap strip on a phone and a grid on wide screens. A post with nothing playable here becomes a text tile that links out.
- **Clips viewer:** an always-dark, full-screen dialog with one clip per screen (vertical scroll-snap). Tap to play or pause, Mute or Unmute, a thin progress line, the account and time, up to three lines of caption, a link to the matched story, "Open on <platform>" and a reminder that the clip is unchecked. Previous and Next buttons appear on wide screens; keys: arrows or Page keys to move, Space or K to play, Esc to close. Nothing autoplays and the last screen says the feed is finished.

- **Story label (review pass):** a story's heading is a generated neutral label of shared words with dots between phrases, never one outlet's headline; if nothing is shared it is the earliest headline with its outlet named beneath. The facts line says "among the outlets we track". On story pages every time carries its UTC beside it.
- **Absence:** a side that did not cover a story is an empty dashed slot at the end of the coverage bar, a dashed neutral badge ("Not covered by"), and a dashed empty box in its column. Teal stays reserved for actions.
- **Phone controls:** the Show panel folds to one line ("Showing all sides" / what is hidden, with "Change"); the page says when any switch is changing what you see. Wide screens keep the panel open in the side rail.
- **Disclosures** (timeline, table, "Show N more") carry a drawn chevron. A skip link leads the page.
- **Clip viewer controls:** one bottom bar (Close, position "3 of 18", Mute; Previous and Next on wide screens), a short swipe hint that disappears, a story link as a filled button, the platform link quiet, and the unchecked reminder as a bordered chip at normal size. Cards keep one fixed footer line whether or not they match a story, and the play mark sits in a corner.
- **Citation:** a block that wraps in full, with Copy as the main action, the time zone named, and UTC times.
