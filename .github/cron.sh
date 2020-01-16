#!/bin/bash
set -ex

pip3 install -r .github/requirements.txt
git worktree add gh-pages gh-pages
.github/cron.py
.github/commit.sh
