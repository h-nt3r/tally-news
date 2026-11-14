# Tally News

An open-source news aggregator that gives you the tool, not the message. It reads about 50 outlets and 11 video
channels across left, center and right, shows videos first and written coverage below, and groups outlets
reporting the same event so you can see how each side covers it and which side is silent. Every rule, source and
label is in plain view, and you can change all of it or copy the whole thing. (The name appears in one place in the
code, `SITE_NAME` in `build.py`.)

## First-time setup

You need Python 3.11 or newer. In Terminal, in this folder:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Optional: summaries written on your own computer

Each story can open with a two-sentence "what happened", written by a small open model (Qwen3 4B, run by llama.cpp) on your own machine. Nothing is sent anywhere. It is off in effect until you add two files under `tools/` (both are large and not in the repository):

1. llama.cpp: download the release for your computer from https://github.com/ggml-org/llama.cpp/releases and unpack it to `tools/llama/` so that `tools/llama/llama-completion` exists.
2. The model: `Qwen3-4B-Q4_K_M.gguf` (about 2.5 GB, from https://huggingface.co/unsloth/Qwen3-4B-GGUF) into `tools/`.

Each build writes a few new summaries (`summary_per_build` in `config/sources.toml`) and remembers them, so a full set fills in over a few builds. `.venv/bin/python build.py --all-summaries` does them all at once (about 40 seconds each on an older laptop). The instructions the model gets are in `config/summary_prompt.txt`. With no model installed the page works as before, without summaries.

## A copy for your group

Mutual aid networks, union locals, chapters and neighborhood groups can run their own copy, with their own name and outlets:

```
.venv/bin/python groups.py new "Eastside Mutual Aid"           # add --empty to start from no outlets
.venv/bin/python groups.py add eastside-mutual-aid https://your-local-paper.org --lean center
./group.sh eastside-mutual-aid                                  # build it and serve it (add --lan for phones)
```

Pages that publish no feed can be watched too: `.venv/bin/python groups.py add-page <name> <page address> --link-contains /news/` (see `pages.py` for how, and its limits).

A group is one file, `groups/<name>/group.toml`: a name, which outlets it follows (the default list with removals and relabels, or only its own), and settings that override `config/sources.toml` for that group. Each group builds into its own folder with its own archive and port. `groups/example-chapter/` is a small working example. Because local outlets rarely cover the same story, group pages also list single-outlet headlines.

## How to use it

1. Run `./run.sh`. It fetches fresh news (about a minute), then serves the site.
2. Visit http://localhost:8765 in your browser.
3. Press Ctrl+C in Terminal to stop it.

### Keep it current automatically (macOS)

Running `./run.sh` by hand shows the news as of that moment. To keep the site fresh on its own:

```
./schedule.sh install --lan
```

That starts two small background jobs: one rebuilds the news every 5 minutes (and again after a restart or log-in),
and one keeps the web page running at http://localhost:8765. With `--lan` your phone can open it too, on the same
Wi-Fi (anyone on that Wi-Fi can, so don't use it on public Wi-Fi). Leave off `--lan` to keep it to this Mac only.

- `./schedule.sh status`: is it running, and how old is the page?
- `./schedule.sh build-now`: rebuild right now.
- `./schedule.sh uninstall`: stop both jobs and remove them.

It only runs while the Mac is awake. If you want it fresh around the clock, set the Mac not to sleep (System Settings,
Battery or Energy) or move it to a machine that stays on.

What keeps it safe and honest:

- A rebuild that finds almost nothing (for example the network is down) is thrown away, so the last good page stays.
- Pages are swapped in one file at a time, so nobody ever sees a half-built page.
- If the page you're looking at gets old, it says so ("This page was built 3 hours ago"). While it's open it checks every
  few minutes, and when a newer build exists a small "A newer update is ready" box offers Refresh. It never reorders the
  page on its own.
- Logs are in `logs/` and each is overwritten, so they don't pile up.

### On your phone (same Wi-Fi), by hand

1. Run `./run.sh --lan`. It prints an address like `http://192.168.0.49:8765`.
2. Open that address in Safari on your phone. Both devices must be on the same Wi-Fi.
3. Press Ctrl+C when you're done. While it runs, anyone on that Wi-Fi can open the site, so don't use this on public Wi-Fi.
4. To restart quickly without re-fetching the news, use `./run.sh --lan --serve`.
5. Optional: in Safari tap Share, then Add to Home Screen, for an app-style icon.

## The pages

- **News**: tabs jump to Clips, Videos, US, World and Tech. Each story is labelled by the words its outlets' headlines share (never one outlet's headline). Each story has a coverage bar (how many left, center and right
  outlets covered it) and the outlets' own headlines in three groups. "Not covered by: left/right" appears when a story
  has 3 or more outlets and one side has said nothing (only in sections that have outlets on that side).
- **Latest** (the second tab): every headline from the last few days (`latest_days` in `config/sources.toml`, default 3), newest first, **including the ones only one outlet ran**, which the News page leaves out because it shows only stories that several outlets covered. Search it by word or by an "exact phrase" (the outlet name counts too), filter by topic, and your Settings switches still apply. A search box on the News page jumps straight to it, and a result that belongs to a story links to that story's page. The list is read from `data/headlines.json` and drawn in your browser; nothing is sent anywhere.
- **Sources**: every outlet, its label, how it is funded or owned (wire, public, state, nonprofit or commercial), a link to its homepage and its feed, how many
  items it returned in the last build, and a switch to hide it for you.
- **Settings**: show or hide left, center and right; turn popularity signals and "new" tags off; export or
  import your settings as a file; reset. Everything is saved only in your browser. There is no account.
- **How the numbers are made** (linked from the footer): what every number on the site is, how it is worked out, and what it can't tell you.
- **Story pages** (open one from "Story page" on any story): a permanent address for the story, its timeline across days, every report with its time, any headline edits shown word by word, a cite-this text and the story's data as JSON.
- **Clips and posts** (off by default: set `clips = true` under `[settings]` in `config/sources.toml` to turn them on; then they are the first section of the news page, ahead of Videos, and a list on each story page): video clips from the open-platform accounts you follow (Bluesky out of the box; Mastodon and Reddit if you add them), shown as tall cards. Tap one to watch it in a full-screen, one-clip-per-screen viewer (swipe or use the arrow keys; Esc to close; Mute and "Open on Bluesky" are in the viewer). Nothing plays by itself, the viewer ends, and the clip streams straight from the public file, with no platform scripts, cookies or embeds. Newest first, never ranked by likes, matched to stories by wording, and labeled unchecked.
- **Archive**: every multi-outlet story from the last 14 days, newest first, with a filter box.
- **Run your own**: how to run your own copy, how to choose sources, how stories are ordered and how labels are set.

Notes on what you see:

- Stories are ranked only by how many different outlets covered them, then by recency. Nothing is personalized.
- **Popularity labels** ("shared by N people on Mastodon", "trending on Bluesky", "N points on Hacker News", video
  views) are information only. They never change the order or hide anything, and a story with no label is not
  unimportant. Each label links to the platform: Bluesky's feed for that topic, the Hacker News discussion, or Mastodon's
  list of trending links (Mastodon has no page for one article, and its list changes through the day). Bluesky only publishes trending topics, not which articles are shared, so a trend is matched to a story
  by wording and shown with its own name. If the name doesn't fit the story, trust your own eyes, not the label.
- **First reported and the coverage timeline** (under each story): which outlet in the list published first, when all three sides had covered it, and a three-lane timeline (one dot per outlet at its publish time) with a table version. They follow your switches, so an outlet you've hidden is never named first.
- **"In this update"** (above the written stories): how many stories, articles and outlets, how many stories all three sides covered, and how many had no left or right coverage.
- **Per-outlet counts** on the Sources page: how many of the page's stories an outlet appears in and how often it was first.
- **The data behind the page** is downloadable at `data/latest.json` (rebuilt every update).
- **New** tag and the "N new since 4:49 PM" line: stories that gained coverage since you last opened the page on this
  device. It only labels; it never reorders or hides anything.
- **Type** tag (Sources and story pages): how an outlet is funded or owned, such as wire service, public broadcaster, state-funded, nonprofit or commercial. A fact about the outlet, not a rating. Outlets without a tag have not been classified yet.
- The Show switches only hide outlets for you, in your browser. Adding an outlet that isn't in the build means
  editing `config/sources.toml` and rebuilding, which is what forking is for.

## Folders

- `config/`: the source list you edit (see its README)
- `template/`: the site's design: look, layout and script (see its README)
- `site/`: the generated pages (see its README)
- `build.py`: the program that fetches, groups and builds the pages
- `analytics.py`: works out the timing facts, the summary counts, the per-outlet counts, the data file and the hourly history snapshot
- `site/story/`: one page and one data file per story (made by the build)
- `social.py`: reads clips and posts from Bluesky, Mastodon and Reddit and matches them to stories
- `template/clips.js` and `template/vendor/`: the clips viewer and the self-hosted video player library
- `archive.py`: the archive of every headline seen, with stable story ids and headline versions
- `tests/`: automatic checks for the archive (see its README)
- `history/`: the archive and hourly summaries, kept on this machine only (see its README)
- `workbench.sh`, `workbench.py`, `workbench_server.py`: your own copy of the news page with a **Manage sources** page (remove, add, relabel; see "The workbench" above). Runs on this Mac only. Your changes live in `workbench/changes.toml`, which is not saved to git
- `run.sh`: builds and serves the site by hand
- `schedule.sh`: keeps the site (and, with `workbench-install`, the workbench) current on a Mac: rebuilds every 5 minutes and keeps the servers running
- `logs/`: the last build's log and the server's log (made by `schedule.sh`; overwritten, not saved to git)

## The workbench: your own copy
There are two copies of the page. The **default dashboard** (`site/`, built by `run.sh` or `schedule.sh`) always shows the default source list, and you can only filter and switch sources off and on there. The **workbench** (`./workbench.sh`, then open http://localhost:8766) is yours to change.

- **Manage sources** page: remove an outlet you never want to see, add one by pasting a website, a feed address or a YouTube channel (it finds the feed and shows the latest headlines first), and change an outlet's side or type if you disagree with it.
- **The way back is always there.** Your changes are a short list kept in `workbench/changes.toml` on top of the defaults, never a copy of them. A banner on every workbench page says how many defaults you removed, with a Restore link, and "Reset to default" on the Manage page forgets all of it.
- **Private and local.** It listens on this Mac only (not your Wi-Fi, not your phone), refuses requests that did not come from this Mac, and needs a secret token for every change, so a web page you visit cannot edit your list. It has its own archive and history in `workbench/`.
- **On your phone, read-only.** `./workbench.sh --lan` also starts a second server that shows your built pages to your phone on the same Wi-Fi (it prints the address, port 8767). It cannot change anything: no editing, no API, pages only, and the Manage page there just says to edit on the Mac. The editing server itself never leaves this Mac. Anyone on that Wi-Fi can open the phone view while it runs, so don't use it on public Wi-Fi. Your phone saves its filter and switch settings separately from the default dashboard's.
- **Source health.** The Manage page has a "Needs attention" section for sources that have failed to load (or had no items) for at least 2 builds in a row, so a dead feed does not quietly shrink your picture. Each row also says what is wrong and since when. One failed build alone is shown as "may be temporary". The same per-source status is saved for every build in `data/health.json`.
- **Keep it running without a terminal.** `./schedule.sh workbench-install` (add `--lan` for the read-only phone view) installs a background job that starts the workbench at log-in, keeps it running, and rebuilds every 20 minutes, even after the Mac wakes from sleep. `./schedule.sh workbench-status` shows how fresh it is and `./schedule.sh workbench-uninstall` removes it. Stop a copy running in a terminal first, because only one can use the port.
- **Rebuilds take about a minute.** Changes show up after you press "Rebuild now", and it rebuilds on its own every 20 minutes while it is running.

## License

Tally News is licensed under the **GNU Affero General Public License v3.0** (see `LICENSE`). In plain terms: you may run, change and share it, including for your group's own copy. If you run a modified version for other people to use over the web, you must make your changes available to them under the same license. Third-party code keeps its own license: `template/vendor/` holds hls.js (see `template/vendor/LICENSE-hls.js.txt`). The local language model and llama.cpp are downloaded by you and are not part of this repository.

## Status

- [x] Phase 1: sources, video row, story grouping, left/center/right view, blind-spot flag
- [x] Phase 1b: show/hide filters for left, center, right (saved in your browser)
- [x] Phase 1c: popularity signals (Mastodon shares, Bluesky trends, Hacker News points, YouTube views), display only
- [x] Phase 1e: section navigation (Videos / US / World / Tech)
- [x] Phase 1g: pivot to an open, forkable tool: Sources, Settings and Fork it pages, per-source switches, settings export/import, "new since your last visit" tags, light and dark, bottom tab bar on phones
- [x] Phase 1h-a: name chosen: Tally News
- [x] Phase 1i: reader-facing analytics: first reported and coverage timeline per story, "in this update" summary, per-outlet counts, Methods page, open data file, hourly history snapshots
- [x] Phase 1k: the archive: every headline seen is remembered with stable story ids and headline versions (edits are caught and listed in the data file)
- [x] Phase 1l-a: story pages with permalinks, multi-day timelines, headline-edit display, a cite-this text and per-story data; the Archive page
- [x] Phase 1m: clips and posts from Bluesky accounts, Mastodon and Reddit, matched to stories, with no embeds, no thumbnails and no referrer sent
- [ ] Phase 1n: the local workbench: a live Bluesky keyword listener, paste-a-link intake for TikTok, Instagram and others, optional Telegram channels
- [x] Phase 1l-a: the workbench: your own copy of the news page with a Manage sources page (remove sources for good, add by pasting a site, feed or YouTube channel with a preview, relabel sides and types, restore or reset to default in a click)
- [ ] Phase 1l-b: keyword watches in the workbench; CSV and feed exports; frozen snapshots of a story; deeper provenance last
- [ ] Phase 1j: analytics that need about a week of history: volume against a typical day, rising names and phrases, and an Insights page with trends
- [x] Phase 1h-b: license chosen (AGPL-3.0, 2026-11-14) and repository planned at github.com/h-nt3r/tally-news; the footer reads both from `config/sources.toml`. Publishing the repository is the remaining step
- [ ] Phase 1d: reader votes of your own (needs a small shared server, so best done once other people use it)
- [x] Phase 2: stay current by itself: rebuild every 20 minutes, stale-page warning, "newer update ready" nudge (this Mac)
- [ ] Phase 2b: alerts for big stories (opt-in, rate-limited, for example a push notification to your phone); the rule would be readable, like the ordering rule
- [ ] Phase 3: optional AI one-line "what all sides agree on" per story
- [ ] Phase 4: more sources (X, Telegram, Rumble have no simple feeds)
- [ ] Phase 5: run it somewhere always on (a public host or a machine that never sleeps) so it doesn't depend on this Mac being awake

## Known limits

- Popularity signals come from Mastodon, Bluesky and Hacker News readers, who are a small, tech-minded group and not the
  general public. Reddit blocks automated requests, so it isn't used. Bluesky blocks searching by link, so only its 25
  biggest trending topics are available and most stories won't have a Bluesky label. The match strictness is
  `trend_match` in `config/sources.toml`. YouTube views mostly reflect how big a channel is.
- Left/center/right labels are one maintainer's judgment, not facts. Edit `config/sources.toml`.
- "First reported" means first among the outlets in the list, using the publish time in each feed. Some feeds report an update time instead, so a time can be later than the real one. The Methods page lists every limit.
- YouTube's feed service is unreliable right now, so videos use a backup method (yt-dlp).
- Story grouping is by wording, so occasionally two stories merge or one splits.
- Paywalled outlets show headlines only.
- Settings are saved per browser and per address (for example `localhost:8765`). A different browser starts with everything on.
- Hiding outlets doesn't fetch more to fill the gap, so the video row can get shorter (12 videos total, shared across outlets).
- TikTok and Instagram have no open public feed and are not scraped. Reddit rate-limits quickly. Clip matching is by wording, so it can miss one or pair one loosely.
- Some feeds go quiet or stop updating (for example CNN's). The Sources page shows "nothing newer than 36 hours" for those.
