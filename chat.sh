#!/bin/sh
# Start the Ask helper: answers questions on the Ask page from today's stories, with the small open model on this computer.
#   ./chat.sh        then open http://localhost:8765/chat.html (the news site must be running: ./run.sh or ./schedule.sh install)
cd "$(dirname "$0")"
exec .venv/bin/python chat_server.py "$@"
