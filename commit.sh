#!/bin/bash
set -ex

cd gh-pages
if [ -z "$(git status --porcelain)" ]; then
	exit 0
fi

git config user.name 'GitHub Actions'
git config user.email "$(whoami)@$(hostname --fqdn)"
git config http.https://github.com/.extraheader "Authorization: Basic $(echo -n "dummy:${GITHUB_PERSONAL_ACCESS_TOKEN}" | base64 --wrap=0)"
git add --all
git commit --amend --reset-author --message 'automatic commit'
git push --force
