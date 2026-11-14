# history/

`archive.sqlite` is the archive: every headline seen, with its link, outlet, side label, topic, publish time, when it was first and last seen, every version of its headline, and a lasting story id. It holds no article text and nothing about readers; entries older than a year are deleted. Open it with any SQLite viewer.

Hourly snapshots of the news, kept on this machine only (never published). Each line of `snapshots.jsonl` records the
size of each story, how many stories had no left or right coverage, and how often each headline word appeared.
Nothing in it is about readers. Entries older than 90 days are deleted automatically.

It exists so a later version can compare today with a typical day. Nothing is shown from it yet. The snapshot files
are not saved to git; only this note is.
