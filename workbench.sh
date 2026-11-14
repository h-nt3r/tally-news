#!/bin/sh
# Your own copy of the news page, with a Manage sources page. It listens on this Mac only.
#   ./workbench.sh            start it, then open http://localhost:8766
#   ./workbench.sh --lan      also show a read-only copy to your phone on the same Wi-Fi (http://<this Mac>:8767)
#   ./workbench.sh --no-build skip the first build and serve what is already there
# Your changes are saved in workbench/changes.toml. Delete that file (or press "Reset to default"
# on the Manage page) to go back to the default list.
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python workbench.py serve "$@"
