#!/usr/bin/env bash
# Converts an OCP source repo to AKS via aks-migrator, then commits + pushes
# the result back into that same repo's `aks/` folder. Shared by the
# Conversion and force-conversion pipeline stages - the only difference
# between them is the `force` argument.
#
# Usage: convert-and-push.sh <ocp-source-path> <self-path> <force:true|false> <git-branch>
set -euo pipefail

OCP_SOURCE_PATH="${1:?usage: convert-and-push.sh <ocp-source-path> <self-path> <force:true|false> <git-branch>}"
SELF_PATH="${2:?}"
FORCE_CONVERT="$(echo "${3:-false}" | tr '[:upper:]' '[:lower:]')"
GIT_BRANCH="${4:?}"
GIT_USER_NAME="${GIT_COMMIT_USER_NAME:-aks-migrator-bot}"
GIT_USER_EMAIL="${GIT_COMMIT_USER_EMAIL:-aks-migrator-bot@localhost}"

AKS_DIR="$OCP_SOURCE_PATH/aks"

if [ "$FORCE_CONVERT" != "true" ] \
   && [ -d "$AKS_DIR/rendered" ] \
   && [ -n "$(find "$AKS_DIR/rendered" -name '*.yaml' -print -quit 2>/dev/null)" ]; then
  echo "✓ $AKS_DIR/rendered already exists in the OCP source repo - skipping conversion."
  echo "  Re-run with forceConvert=true (pipeline parameter) to regenerate."
  exit 0
fi

if [ "$FORCE_CONVERT" = "true" ]; then
  echo "forceConvert=true - regenerating regardless of any existing aks/ folder."
else
  echo "No converted output found in $AKS_DIR - running aks-migrator."
fi

echo "--- Running aks-migrator against $OCP_SOURCE_PATH ---"
cd "$SELF_PATH"
chmod +x run.sh
./run.sh build

# Exit code 2 means aks-migrator's own BLOCK verdict (fail-on-block) - still
# push the artefacts (validation.md/findings.json/diff.patch) so reviewers
# can see what's blocking, rather than losing them with the agent workspace.
set +e
OUT_DIR="$AKS_DIR" ./run.sh migrate "$OCP_SOURCE_PATH"
MIGRATE_EXIT=$?
set -e

if [ "$MIGRATE_EXIT" -ne 0 ] && [ "$MIGRATE_EXIT" -ne 2 ]; then
  echo "aks-migrator failed unexpectedly (exit $MIGRATE_EXIT) - not pushing any output." >&2
  exit "$MIGRATE_EXIT"
fi

echo "--- Committing converted output back to the OCP source repo ---"
cd "$OCP_SOURCE_PATH"
git config user.email "$GIT_USER_EMAIL"
git config user.name "$GIT_USER_NAME"
git add aks/

if git diff --cached --quiet; then
  echo "No changes to commit - converted output is identical to what's already there."
  exit "$MIGRATE_EXIT"
fi

COMMIT_MSG="aks-migrator: convert OCP to AKS [skip ci]"
if [ "$MIGRATE_EXIT" -eq 2 ]; then
  COMMIT_MSG="aks-migrator: convert OCP to AKS (BLOCKED - see aks/validation.md) [skip ci]"
fi

# [skip ci] is a widely-recognised convention (Azure Pipelines honours
# ***NO_CI*** / [skip ci] in the commit message) - prevents this push from
# re-triggering a CI pipeline on the OCP source repo, if it has one.
git commit -m "$COMMIT_MSG"
git push origin "HEAD:refs/heads/$GIT_BRANCH"
echo "✓ Pushed converted manifests to branch '$GIT_BRANCH'"

if [ "$MIGRATE_EXIT" -eq 2 ]; then
  echo "aks-migrator reported blocking findings - see aks/validation.md in the pushed output." >&2
  exit 2
fi
