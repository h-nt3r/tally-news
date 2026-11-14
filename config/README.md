# config/

`sources.toml` is the list of news outlets and YouTube channels the page pulls from.
It is the most important file in the project: **who is on this list decides what you see.**

Each entry has a `lean` (left / center / right), an optional `type` (how it is funded or owned: wire, public, state, nonprofit or commercial; leave it out when unsure), and a topic.
To add an outlet, copy an existing block and change the name and web address.
To drop one, delete its block. The lean labels are judgment calls; change any you disagree with.

Each outlet can also have a `site` line: its own homepage, shown on the Sources page next to the feed address.

## Public address for citations

`base_url` under `[settings]` in `sources.toml` is where this site is hosted, for example `"https://news.example.org/"`. Once it is set, each story's "Cite this" text carries a real link to the story page and the outlet list. While it is empty, citations say they come from a local copy and point to the story ID instead of printing a file path from your computer.

This file is the **default** list and is what the public page uses. To remove or add sources for yourself without touching it, use the workbench (`./workbench.sh`, then the Manage sources page). Its changes are kept separately in `workbench/changes.toml`.
