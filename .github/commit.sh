#!/bin/bash
set -ex

cd gh-pages
git config user.name 'GitHub Actions'
git config user.email "$(whoami)@$(hostname --fqdn)"
git add --all
git commit --amend --reset-author --message 'automatic commit'
git push --force
