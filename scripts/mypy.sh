#!/usr/bin/env bash

set -e

export PYTHONPATH=":nplusone"


# Cleaning existing cache:
if [ "$1" == "-nc" ]; then
  rm -rf .mypy_cache
fi


mypy nplusone
