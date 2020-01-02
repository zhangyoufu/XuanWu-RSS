#!/bin/bash
set -ex

pip3 install -r .github/requirements.txt

git config user.name 'GitHub Actions'
git config user.email "$(whoami)@$(hostname --fqdn)"

.github/cron.py
