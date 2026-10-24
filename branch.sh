#!/usr/bin/env bash
# Creates, resets or deletes the branch database BRANCH of DATABASE with the
# ts CLI, acting as TERRASCALE_API_KEY, and writes the step outputs.
set -euo pipefail

ts=("$HOME/.local/bin/ts")
if [ -n "$PROJECT" ]; then
  ts+=(-project "$PROJECT")
fi
verb=$COMMAND
if [ -z "$verb" ]; then
  verb=create
  if [ "$EVENT_ACTION" = closed ]; then
    verb=delete
  fi
fi
case $verb in
  create | reset | delete) ;;
  *) echo "::error::command must be create, reset or delete, not $verb"; exit 2 ;;
esac
if [[ ! $BRANCH =~ ^[a-z][a-z0-9_-]{0,62}$ ]]; then
  echo "::error::branch $BRANCH must match ^[a-z][a-z0-9_-]{0,62}$"
  exit 2
fi

echo "name=$BRANCH" >> "$GITHUB_OUTPUT"
# A failing db list stops the step, so an API error never reads as no branch.
list=$("${ts[@]}" db list)
exists=$(awk -v name="$BRANCH" 'NR > 1 && $1 == name { print "yes" }' <<< "$list")
if [ "$verb" != create ] && [ -n "$exists" ]; then
  "${ts[@]}" db delete "$BRANCH"
  exists=
fi
if [ "$verb" = delete ]; then
  exit 0
fi
if [ -z "$exists" ]; then
  "${ts[@]}" db branch "$DATABASE" "$BRANCH"
else
  echo "Keeping $BRANCH"
fi
info=$("${ts[@]}" db info "$BRANCH")
id=$(jq -r .id <<< "$info")
project=$(jq -r .projectId <<< "$info")
{
  echo "id=$id"
  echo "project-id=$project"
  echo "api-url=https://api.terrascale.tech/v1/projects/$project/databases/$BRANCH"
} >> "$GITHUB_OUTPUT"
