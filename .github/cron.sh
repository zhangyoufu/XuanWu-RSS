#!/bin/bash
set -ex

git worktree add gh-pages
pip3 install -r .github/requirements.txt
exec .github/cron.py
