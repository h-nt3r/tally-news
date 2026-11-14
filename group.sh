#!/bin/sh
# Build and serve one group's page. Each group has its own folder (groups/<name>/), archive and port.
#   ./group.sh <name>          build, then serve on this Mac only (the port is printed)
#   ./group.sh <name> --lan    also reachable from phones on the same Wi-Fi
#   ./group.sh <name> --serve  skip the rebuild
# Make a group first:  .venv/bin/python groups.py new "Its Name"
cd "$(dirname "$0")" || exit 1
SLUG=$1
[ -n "$SLUG" ] || { echo "Usage: ./group.sh <name> [--lan] [--serve]   (groups: .venv/bin/python groups.py list)"; exit 1; }
shift
PORT=$(.venv/bin/python groups.py port "$SLUG") || exit 1
BIND=127.0.0.1; BUILD=1
for arg in "$@"; do
  case "$arg" in
    --lan) BIND=0.0.0.0 ;;
    --serve) BUILD=0 ;;
  esac
done
if [ "$BUILD" = 1 ]; then
  .venv/bin/python build.py --group "$SLUG" || exit 1
fi
if [ "$BIND" = 0.0.0.0 ]; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
  echo ""; echo "Open this on a phone (same Wi-Fi):  http://${IP:-<your-mac-ip>}:$PORT"
  echo "Anyone on this Wi-Fi can open it while this is running. Don't use it on public Wi-Fi."
else
  echo ""; echo "Open http://localhost:$PORT   (Ctrl+C to stop)"
fi
echo ""
cd "groups/$SLUG/site" && exec ../../../.venv/bin/python -m http.server "$PORT" --bind "$BIND"
