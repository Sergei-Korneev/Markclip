#!/usr/bin/env bash
# Run Markclip (Linux). Extra arguments are passed to the program: ./run.sh --help
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "Virtual environment not found. Run ./install.sh first." >&2
    exit 1
fi

exec .venv/bin/python run.py "$@"
