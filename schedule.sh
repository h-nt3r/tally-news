#!/bin/sh
# Keep the site current on this Mac. Two small background jobs (macOS "launch agents"):
#   build  rebuilds the site every 5 minutes (and once right away), so breaking stories show up quickly
#   serve  keeps the web page available at http://localhost:8765
# Both start again by themselves after a restart or log-in. macOS only.
#
#   ./schedule.sh install          start both; the page is reachable only from this Mac
#   ./schedule.sh install --lan    same, but also reachable from your phone on the same Wi-Fi
#   ./schedule.sh status           is it running, and how fresh is the page?
#   ./schedule.sh build-now        rebuild right now, without waiting for the next 5 minutes
#   ./schedule.sh reschedule       rewrite and restart only the build job (after changing EVERY below); leaves the server alone
#   ./schedule.sh uninstall        stop both and remove them
#   ./schedule.sh summaries-install    write the machine-written summaries in their own job (keeps page builds short; see summaries_in_build)
#   ./schedule.sh summaries-uninstall  remove that job
#
# The workbench (your own copy with the Manage sources page; see ./workbench.sh) has its own job:
#   ./schedule.sh workbench-install          keep the workbench running and rebuilding every 20 minutes
#   ./schedule.sh workbench-install --lan    same, plus the read-only phone view (port 8767) on your Wi-Fi
#   ./schedule.sh workbench-status           is it running, and how fresh is its page?
#   ./schedule.sh workbench-uninstall        stop it and remove the job
#
# The Ask page's helper (chat_server.py; see the README) has its own job:
#   ./schedule.sh chat-install          keep the helper running; only this Mac can use it
#   ./schedule.sh chat-install --lan    same, but a phone on your Wi-Fi can use it too (needed to ask from a phone)
#   ./schedule.sh chat-status           is it running, and is the model loaded?
#   ./schedule.sh chat-uninstall        stop it and remove the job
#
# On a Linux machine, run `.venv/bin/python build.py` from cron instead (see the Fork it page).
cd "$(dirname "$0")" || exit 1
ROOT=$(pwd)
AGENTS="$HOME/Library/LaunchAgents"
BUILD=local.opennews.build
SERVE=local.opennews.serve
WORKBENCH=local.opennews.workbench
DOMAIN="gui/$(id -u)"
PORT=8765
EVERY=300       # seconds between rebuilds of the main site (a build takes a minute or two; launchd never starts a second one while one runs)
WB_EVERY=1200   # seconds between workbench rebuilds
CHAT=local.opennews.chat
CHAT_PORT=8770
SUMMARIZE=local.opennews.summaries
SUM_EVERY=600   # seconds between summary runs (each one writes the few summaries that are missing; see summary_per_build)

need_mac() { [ "$(uname)" = Darwin ] || { echo "This script is for macOS. On Linux, use cron (see the Fork it page)."; exit 1; }; }

write_build_plist() {
  cat > "$AGENTS/$BUILD.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$BUILD</string>
  <key>ProgramArguments</key><array>
    <string>/bin/sh</string><string>-c</string>
    <string>cd "$ROOT" &amp;&amp; { [ "\$(wc -c &lt; logs/serve.log 2&gt;/dev/null || echo 0)" -gt 1000000 ] &amp;&amp; : &gt; logs/serve.log; exec .venv/bin/python build.py &gt; logs/build.log 2&gt;&amp;1; }</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartInterval</key><integer>$EVERY</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
</dict></plist>
EOF
}

write_summaries_plist() {  # its own job, so the slow model never holds up a page build. Not "Background": macOS then gives the model about a fifth of a core, and it times out
  cat > "$AGENTS/$SUMMARIZE.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$SUMMARIZE</string>
  <key>ProgramArguments</key><array>
    <string>/bin/sh</string><string>-c</string>
    <string>cd "$ROOT" &amp;&amp; { [ "\$(wc -c &lt; logs/summaries.log 2&gt;/dev/null || echo 0)" -gt 1000000 ] &amp;&amp; : &gt; logs/summaries.log; exec .venv/bin/python build.py --summaries-only &gt;&gt; logs/summaries.log 2&gt;&amp;1; }</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartInterval</key><integer>$SUM_EVERY</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Standard</string>
</dict></plist>
EOF
}

write_serve_plist() {
  cat > "$AGENTS/$SERVE.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$SERVE</string>
  <key>ProgramArguments</key><array>
    <string>$ROOT/.venv/bin/python</string><string>-m</string><string>http.server</string>
    <string>$PORT</string><string>--bind</string><string>$1</string><string>--directory</string><string>$ROOT/site</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$ROOT/logs/serve.log</string>
  <key>StandardOutPath</key><string>/dev/null</string>
</dict></plist>
EOF
}

write_workbench_plist() {  # $1 = extra argument ("--lan" or nothing)
  cat > "$AGENTS/$WORKBENCH.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$WORKBENCH</string>
  <key>ProgramArguments</key><array>
    <string>$ROOT/.venv/bin/python</string><string>workbench.py</string><string>serve</string>
    <string>--every</string><string>$WB_EVERY</string>$([ -n "$1" ] && printf '<string>%s</string>' "$1")
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/workbench.log</string>
  <key>StandardOutPath</key><string>$ROOT/logs/workbench.log</string>
</dict></plist>
EOF
}

write_chat_plist() {  # $1 = extra argument ("--lan" or nothing). The helper itself loads the model only while questions are being asked
  cat > "$AGENTS/$CHAT.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$CHAT</string>
  <key>ProgramArguments</key><array>
    <string>$ROOT/.venv/bin/python</string><string>chat_server.py</string>$([ -n "$1" ] && printf '<string>%s</string>' "$1")
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/chat.log</string>
  <key>StandardOutPath</key><string>$ROOT/logs/chat.log</string>
</dict></plist>
EOF
}

load() {  # label
  launchctl bootout "$DOMAIN/$1" 2>/dev/null
  launchctl bootstrap "$DOMAIN" "$AGENTS/$1.plist"
}

case "$1" in
  install)
    need_mac
    [ -x .venv/bin/python ] || { echo "Run the first-time setup in README.md first (python3 -m venv .venv ...)."; exit 1; }
    BIND=127.0.0.1
    [ "$2" = "--lan" ] && BIND=0.0.0.0
    mkdir -p "$AGENTS" logs
    others=$(lsof -nP -iTCP:$PORT -sTCP:LISTEN 2>/dev/null | tail -n +2 | grep -v "local.opennews" || true)
    if [ -n "$others" ]; then
      echo "Heads up: something else is already using port $PORT, so the web server job may not start:"
      echo "$others"
      echo "Stop it (for example with: kill <PID>) and run ./schedule.sh install again."
      echo ""
    fi
    write_build_plist
    write_serve_plist "$BIND"
    load $SERVE
    load $BUILD
    echo "Installed. The first build is running now (about a minute), then every $((EVERY / 60)) minutes."
    if [ "$BIND" = 0.0.0.0 ]; then
      IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
      echo "Open on this Mac:  http://localhost:$PORT"
      echo "Open on your phone (same Wi-Fi):  http://${IP:-<your-mac-ip>}:$PORT"
      echo "Anyone on this Wi-Fi can open it. Don't run this on public Wi-Fi."
    else
      echo "Open: http://localhost:$PORT   (only this Mac can reach it; use --lan for your phone)"
    fi
    echo "Check on it any time with: ./schedule.sh status"
    ;;
  status)
    need_mac
    for label in $BUILD $SERVE; do
      if launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
        echo "$label: installed"
        launchctl print "$DOMAIN/$label" | grep -E "^\s+(state|runs|last exit code) =" | sed 's/^/    /'
      else
        echo "$label: not installed"
      fi
    done
    if [ -f site/build.json ]; then
      built=$(.venv/bin/python -c "import json;print(json.load(open('site/build.json'))['built'])")
      age=$(( $(date +%s) - built ))
      echo "Last finished build: $((age / 60)) minutes ago ($(.venv/bin/python -c "import json;d=json.load(open('site/build.json'));print(d['stories'],'stories from',d['articles'],'articles')"))"
      [ "$age" -gt 5400 ] && echo "  That is old. Look at logs/build.log."
    else
      echo "No finished build yet (give the first one about a minute)."
    fi
    [ -f logs/build.log ] && { echo "Last line of logs/build.log:"; tail -n 1 logs/build.log | sed 's/^/    /'; }
    lsof -nP -iTCP:$PORT -sTCP:LISTEN 2>/dev/null | tail -n +2 | awk '{print "Port '$PORT' is held by pid " $2 " (" $9 ")"}'
    ;;
  reschedule)
    need_mac
    mkdir -p "$AGENTS" logs
    write_build_plist
    load $BUILD
    echo "Build job restarted: it now runs every $((EVERY / 60)) minutes. The web server job was not touched."
    ;;
  build-now)
    need_mac
    launchctl kickstart -k "$DOMAIN/$BUILD" && echo "Rebuilding now. Watch it with: ./schedule.sh status"
    ;;
  uninstall)
    need_mac
    for label in $BUILD $SERVE; do
      launchctl bootout "$DOMAIN/$label" 2>/dev/null
      rm -f "${AGENTS:?}/$label.plist"
    done
    echo "Removed both background jobs. The site files stay; use ./run.sh to build and serve by hand."
    ;;
  summaries-install)
    need_mac
    [ -x .venv/bin/python ] || { echo "Run the first-time setup in README.md first (python3 -m venv .venv ...)."; exit 1; }
    mkdir -p "$AGENTS" logs
    write_summaries_plist
    load $SUMMARIZE
    echo "Installed. A summary run starts now and repeats every $((SUM_EVERY / 60)) minutes; it only writes summaries, never pages."
    echo "Set summaries_in_build = false in config/sources.toml so the page build stops writing them too."
    echo "Progress: tail logs/summaries.log"
    ;;
  summaries-uninstall)
    need_mac
    launchctl bootout "$DOMAIN/$SUMMARIZE" 2>/dev/null
    rm -f "${AGENTS:?}/$SUMMARIZE.plist"
    echo "Removed the summary job. Set summaries_in_build = true in config/sources.toml to have the page build write summaries again."
    ;;
  workbench-install)
    need_mac
    [ -x .venv/bin/python ] || { echo "Run the first-time setup in README.md first (python3 -m venv .venv ...)."; exit 1; }
    mkdir -p "$AGENTS" logs
    [ -f logs/workbench.log ] && [ "$(wc -c < logs/workbench.log)" -gt 1000000 ] && : > logs/workbench.log
    held=$(lsof -nP -iTCP:8766 -sTCP:LISTEN 2>/dev/null | tail -n +2 | grep -v "local.opennews" || true)
    if [ -n "$held" ]; then
      echo "Port 8766 is already in use (probably ./workbench.sh running in a terminal). Stop it (Ctrl+C) and run this again:"
      echo "$held"
      exit 1
    fi
    ARG=""
    [ "$2" = "--lan" ] && ARG="--lan"
    write_workbench_plist "$ARG"
    load $WORKBENCH
    echo "Installed. The workbench is starting (the first build takes about a minute), then rebuilds every $((WB_EVERY / 60)) minutes."
    echo "Open on this Mac:  http://localhost:8766   (Manage sources is in the top bar)"
    if [ -n "$ARG" ]; then
      IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
      echo "Open on your phone (same Wi-Fi, read-only):  http://${IP:-<your-mac-ip>}:8767"
      echo "Anyone on this Wi-Fi can open the phone view. Don't run this on public Wi-Fi."
    fi
    echo "Check on it any time with: ./schedule.sh workbench-status"
    ;;
  workbench-status)
    need_mac
    if launchctl print "$DOMAIN/$WORKBENCH" >/dev/null 2>&1; then
      echo "$WORKBENCH: installed"
      launchctl print "$DOMAIN/$WORKBENCH" | grep -E "^\s+(state|runs|last exit code) =" | sed 's/^/    /'
    else
      echo "$WORKBENCH: not installed"
    fi
    if [ -f workbench/site/build.json ]; then
      built=$(.venv/bin/python -c "import json;print(json.load(open('workbench/site/build.json'))['built'])")
      age=$(( $(date +%s) - built ))
      echo "Last finished workbench build: $((age / 60)) minutes ago"
      [ "$age" -gt 5400 ] && echo "  That is old. Look at workbench/build.log and logs/workbench.log."
    else
      echo "No finished workbench build yet (give the first one about a minute)."
    fi
    [ -f workbench/build.log ] && { echo "Last line of workbench/build.log:"; tail -n 1 workbench/build.log | sed 's/^/    /'; }
    lsof -nP -iTCP:8766 -iTCP:8767 -sTCP:LISTEN 2>/dev/null | tail -n +2 | awk '{print "Port " $9 " is held by pid " $2}'
    ;;
  workbench-uninstall)
    need_mac
    launchctl bootout "$DOMAIN/$WORKBENCH" 2>/dev/null
    rm -f "${AGENTS:?}/$WORKBENCH.plist"
    echo "Removed the workbench job. Your changes (workbench/changes.toml) stay; use ./workbench.sh to run it by hand."
    ;;
  chat-install)
    need_mac
    [ -x .venv/bin/python ] || { echo "Run the first-time setup in README.md first (python3 -m venv .venv ...)."; exit 1; }
    mkdir -p "$AGENTS" logs
    [ -f logs/chat.log ] && [ "$(wc -c < logs/chat.log)" -gt 1000000 ] && : > logs/chat.log
    held=$(lsof -nP -iTCP:$CHAT_PORT -sTCP:LISTEN 2>/dev/null | tail -n +2 | grep -v "local.opennews" || true)
    if [ -n "$held" ]; then
      echo "Port $CHAT_PORT is already in use (probably ./chat.sh running in a terminal). Stop it (Ctrl+C) and run this again:"
      echo "$held"
      exit 1
    fi
    ARG=""
    [ "$2" = "--lan" ] && ARG="--lan"
    write_chat_plist "$ARG"
    load $CHAT
    echo "Installed. The Ask helper is running; it loads the model when the first question arrives and lets it go after a quiet spell."
    echo "Ask on this Mac:  http://localhost:$PORT/chat.html"
    if [ -n "$ARG" ]; then
      IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
      echo "Ask on your phone (same Wi-Fi):  http://${IP:-<your-mac-ip>}:$PORT/chat.html   (the news site itself must be installed with --lan too)"
      echo "Anyone on this Wi-Fi can ask it questions, which uses this Mac's processor. Don't use this on public Wi-Fi."
    else
      echo "Only this Mac can use it. Use --lan to ask from your phone."
    fi
    echo "Check on it any time with: ./schedule.sh chat-status"
    ;;
  chat-status)
    need_mac
    if launchctl print "$DOMAIN/$CHAT" >/dev/null 2>&1; then
      echo "$CHAT: installed"
      launchctl print "$DOMAIN/$CHAT" | grep -E "^\s+(state|runs|last exit code) =" | sed 's/^/    /'
      launchctl print "$DOMAIN/$CHAT" | grep -q -- "--lan" && echo "    reachable from your Wi-Fi (--lan)" || echo "    this Mac only"
    else
      echo "$CHAT: not installed"
    fi
    curl -s -m 3 "http://localhost:$CHAT_PORT/api/status" | .venv/bin/python -c "import sys,json
try: d=json.load(sys.stdin)
except ValueError: sys.exit('Helper did not answer on port $CHAT_PORT.')
print('Model', d['model'], 'installed' if d['installed'] else 'NOT installed', '| loaded now' if d['running'] else '| not loaded (it loads on the first question)', '|', d['stories'], 'stories')" 2>&1 | sed 's/^/    /'
    ;;
  chat-uninstall)
    need_mac
    launchctl bootout "$DOMAIN/$CHAT" 2>/dev/null
    rm -f "${AGENTS:?}/$CHAT.plist"
    echo "Removed the Ask helper job. Use ./chat.sh to run it by hand."
    ;;
  *)
    sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac
