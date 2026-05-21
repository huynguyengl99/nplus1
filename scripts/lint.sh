#!/usr/bin/env bash

if [ "$1" == "--fix" ]; then
  ruff check . --fix && ruff format . && toml-sort ./*.toml
else
  ruff check . && ruff format . --check && toml-sort ./*.toml --check
fi
