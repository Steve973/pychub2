#!/usr/bin/env bash

clear
find . -type f -regextype posix-extended -regex '.*\.(py|sh|md|toml|json|txt)$' | \
  grep -v "\.venv" | \
  grep -v "mypy_cache" | \
  grep -v "__init__" |
  sed 's|\./|https://github.com/Steve973/pychub2/raw/refs/heads/main/|g'
