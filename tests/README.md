# tests/

Automatic checks for the parts that must not quietly break. `test_archive.py` checks that a story keeps the same id as
outlets join it, that splits and merges are handled, that headline edits are caught, and that old entries expire.
`test_build_helpers.py` checks the headline-edit markup, the timeline's tick marks, the "too close to call" rule and the duplicate-story merge the per-source health streaks and the Latest page's data (tracking-free links, the compact headline file, the archive query). `test_workbench.py` checks the workbench: applying removals, additions and relabels on top of the defaults, the changes file round trip, validation of a new source, feed discovery, and the guards that keep the Manage server private to this Mac.

Run them from the project folder:

```
.venv/bin/python -m unittest discover tests
```

`test_times.py` checks that feed publish times are read as UTC in any time zone (an earlier bug shifted every time by this computer's offset) and that the old shifted archive is repaired exactly once.
