#!/usr/bin/env bash
# All API operations go through ts; never delete by name without expected-id.
set -euo pipefail
fail() { echo "::error::$1" >&2; exit 1; }
ts=("$HOME/.local/bin/ts" --json)
if [ -n "$PROJECT" ]; then ts+=(-project "$PROJECT"); fi
cli() { "${ts[@]}" "$@" 2>/dev/null || fail 'CLI request failed; inspect permissions and resource state before retrying.'; }
verb=${COMMAND:-create}
if [ -z "$verb" ]; then verb=create; fi
if [ -z "$COMMAND" ] && [ "$EVENT_ACTION" = closed ]; then verb=delete; fi
case $verb in
  create | delete) ;;
  reset) fail 'Reset requires the generation refresh contract.' ;;
  *) fail 'command must be create, reset or delete.' ;;
esac
[[ $DATABASE =~ ^[a-z][a-z0-9_-]{0,62}$ ]] || fail 'database must be a valid database name.'
label=${BRANCH:-preview}
[[ $label =~ ^[a-z][a-z0-9_-]{0,62}$ ]] || fail 'branch must be a valid namespace label.'
[[ $GITHUB_EVENT_NAME = pull_request && $GITHUB_REPOSITORY_ID =~ ^[1-9][0-9]{0,19}$ && $PR_NUMBER =~ ^[1-9][0-9]{0,19}$ ]] || fail 'A pull_request event with repository ID and PR number is required.'
jq -e --arg repo "$GITHUB_REPOSITORY_ID" --arg pr "$PR_NUMBER" \
  '(.pull_request.base.repo.id | tostring) == $repo and (.number | tostring) == $pr' "$GITHUB_EVENT_PATH" >/dev/null || fail 'Repository or PR event identity mismatch.'
# Explicit labels also stay inside this namespace; source identity is checked separately.
digest=$(printf '%s\n' "$GITHUB_REPOSITORY_ID:$PR_NUMBER:$label" | shasum -a 256 | cut -c1-24)
name="pr-$PR_NUMBER-$digest"
[[ $name != "$DATABASE" ]] || fail 'Source and target must be different databases.'
select_name() {
  jq -c --arg name "$1" 'map(select(.name == $name)) | if length == 1 then .[0] elif length == 0 then null else error("duplicate name") end' <<< "$list"
}
valid_info() {
  jq -e --arg name "$1" '
    def id: type == "string" and test("^[0-7][0-9A-HJKMNP-TV-Z]{25}$");
    type == "object" and .name == $name and (.id | id) and (.projectId | id)' <<< "$2" >/dev/null
}
list=$(cli db list)
jq -e 'type == "array"' <<< "$list" >/dev/null || fail 'Invalid database list JSON.'
source=$(select_name "$DATABASE")
valid_info "$DATABASE" "$source" || fail 'Source database is absent or invalid.'
source_id=$(jq -r .id <<< "$source")
project=$(jq -r .projectId <<< "$source")
if [ -n "$PROJECT" ]; then [[ $PROJECT = "$project" ]] || fail 'Project identity mismatch.'; fi
check_source() {
  local current
  current=$(cli db info "$DATABASE")
  valid_info "$DATABASE" "$current" && \
    jq -e --arg id "$source_id" --arg project "$project" '.id == $id and .projectId == $project' <<< "$current" >/dev/null || fail 'Source identity changed; refusing operation.'
}
check_target() {
  valid_info "$name" "$1" && \
    jq -e --arg source "$source_id" --arg project "$project" '.id != $source and .projectId == $project and .branchedFrom == $source' <<< "$1" >/dev/null || fail 'Target identity or source lineage mismatch; refusing operation.'
}
target=$(select_name "$name")
check_source
if [ "$target" != null ]; then
  check_target "$target"
  observed_id=$(jq -r .id <<< "$target")
  target=$(cli db info "$name")
  check_target "$target"
  [[ $(jq -r .id <<< "$target") = "$observed_id" ]] || fail 'Target identity changed; refusing operation.'
fi
if [ "$verb" = delete ]; then
  if [ "$target" != null ]; then
    check_source
    # The server must enforce this immutable ID, including across concurrent replacements.
    cli -yes -expected-id "$observed_id" db delete "$name" >/dev/null
  fi
  echo "name=$name" >> "$GITHUB_OUTPUT"
  exit 0
fi
if [ "$target" = null ]; then
  target=$(cli db branch "$DATABASE" "$name")
  check_target "$target"
fi
id=$(jq -r .id <<< "$target")
check_source
confirmed=$(cli db info "$name")
check_target "$confirmed"
[[ $(jq -r .id <<< "$confirmed") = "$id" ]] || fail 'Target identity changed before publication.'
{
  echo "name=$name"
  echo "id=$id"
  echo "project-id=$project"
  echo "api-url=https://api.terrascale.tech/v1/projects/$project/databases/$name"
} >> "$GITHUB_OUTPUT"
