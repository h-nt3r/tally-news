#!/bin/sh
# Rebuild the page, then serve it.
#   ./run.sh         only this Mac can see it:  http://localhost:8765
#   ./run.sh --lan   also reachable from your phone on the same Wi-Fi
#   ./run.sh --serve skip the rebuild and just serve the last page (fast restart)
cd "$(dirname "$0")"

BIND=127.0.0.1
BUILD=1
for arg in "$@"; do
  case "$arg" in
    --lan) BIND=0.0.0.0 ;;
    --serve) BUILD=0 ;;
  esac
done

if [ "$BUILD" = 1 ]; then
  .venv/bin/python build.py || exit 1
fi

if [ "$BIND" = 0.0.0.0 ]; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
  echo ""
  echo "Open this on your phone (same Wi-Fi):  http://${IP:-<your-mac-ip>}:8765"
  echo "Anyone on this Wi-Fi can open it while this is running. Don't use it on public Wi-Fi."
  echo "Press Ctrl+C to stop."
  echo ""
else
  echo ""
  echo "Open http://localhost:8765   (Ctrl+C to stop)"
  echo ""
fi

cd site && exec ../.venv/bin/python -m http.server 8765 --bind "$BIND"
