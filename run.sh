#!/usr/bin/env bash
# Makefile replacement for Windows Git Bash / any shell without make.
set -euo pipefail

# Git Bash mangles container paths; disable that for docker invocations.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

here() { pwd -W 2>/dev/null || pwd; }
ROOT="$(here)"

# --- Job file --------------------------------------------------------------
# Loads REPO, REPO_BRANCH, ENV, MODE, FAIL_ON_BLOCK, OUT_DIR, CONFIG_DIR and
# WORKBOOK_INTAKE from migration.env, if present (copy migration.env.example
# to get started). A shell env var you set explicitly on the command line
# (e.g. `ENV=int ./run.sh demo`) always takes priority over the file.
load_job_file() {
  local f="$ROOT/migration.env"
  [ -f "$f" ] || return 0
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *"="* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    key="$(echo "$key" | xargs)"
    [ -z "$key" ] && continue
    if [ -z "${!key:-}" ]; then
      export "$key=$value"
    fi
  done < "$f"
}
load_job_file

IMAGE="${IMAGE:-aks-migrator:latest}"
# Blank by default - migrate converts every environment in
# config/env-matrix.yaml in one pass when ENV isn't set. Set ENV=<name> to
# restrict a run to just one.
ENVIRONMENT="${ENV:-}"
MODE="${MODE:-offline}"
FAIL_ON_BLOCK="${FAIL_ON_BLOCK:-true}"
OUT_DIR="${OUT_DIR:-$ROOT/aks}"
CONFIG_DIR="${CONFIG_DIR:-$ROOT/config}"
WORKBOOK_INTAKE="${WORKBOOK_INTAKE:-}"

# --- LLM (mandatory) + idempotency/freeze -----------------------------------
# The agent always calls an LLM (config/models.yaml, default provider:
# ollama). From inside the container, "localhost" means the container
# itself, not your machine - so the default endpoint here points at Docker
# Desktop's host gateway instead. Override LLM_ENDPOINT if Ollama runs
# elsewhere (a remote host, or a hosted provider's URL).
LLM_ENDPOINT="${LLM_ENDPOINT:-http://host.docker.internal:11434}"
LLM_MODEL="${LLM_MODEL:-}"
LLM_SEED="${LLM_SEED:-}"
LLM_TIMEOUT="${LLM_TIMEOUT:-}"
FREEZE_OUTPUT="${FREEZE_OUTPUT:-false}"
LLM_FORCE_REFRESH="${LLM_FORCE_REFRESH:-false}"
# Frozen/cached LLM responses live under $OUT_DIR by default, so they
# survive across --rm'd containers the same way the rest of $OUT_DIR does.
LLM_CACHE_DIR="${LLM_CACHE_DIR:-}"

# Resolve a possibly-relative host path against $ROOT.
resolve_path() {
  local p="$1"
  case "$p" in
    /*|?:*) echo "$p" ;;                 # already absolute (POSIX or C:\...)
    *)      echo "$ROOT/$p" ;;
  esac
}
OUT_DIR="$(resolve_path "$OUT_DIR")"
CONFIG_DIR="$(resolve_path "$CONFIG_DIR")"

fail_on_block_flag() {
  case "$(echo "${FAIL_ON_BLOCK}" | tr '[:upper:]' '[:lower:]')" in
    false|0|no)  echo "--no-fail-on-block" ;;
    *)           echo "--fail-on-block" ;;
  esac
}

# Emits --env <name> only if ENVIRONMENT is actually set - omitting --env
# entirely tells aks-migrator to convert every environment in
# config/env-matrix.yaml in one pass, rather than defaulting to one.
env_flag() {
  [ -n "$ENVIRONMENT" ] && printf '%s\n' "--env" "$ENVIRONMENT"
  return 0
}

# Docker args carrying the LLM/freeze configuration into the container.
# --add-host is a no-op on Docker Desktop (host.docker.internal already
# resolves) but is required for host.docker.internal to work on native
# Linux Docker.
LLM_ARGS=(
  --add-host=host.docker.internal:host-gateway
  -e "LLM_ENDPOINT=$LLM_ENDPOINT"
  -e "FREEZE_OUTPUT=$FREEZE_OUTPUT"
  -e "LLM_FORCE_REFRESH=$LLM_FORCE_REFRESH"
)
[ -n "$LLM_MODEL" ] && LLM_ARGS+=(-e "LLM_MODEL=$LLM_MODEL")
[ -n "$LLM_SEED" ] && LLM_ARGS+=(-e "LLM_SEED=$LLM_SEED")
[ -n "$LLM_TIMEOUT" ] && LLM_ARGS+=(-e "LLM_TIMEOUT=$LLM_TIMEOUT")
[ -n "$LLM_CACHE_DIR" ] && LLM_ARGS+=(-e "LLM_CACHE_DIR=$LLM_CACHE_DIR")

DOCKER="docker"

# Fails fast with actionable guidance instead of a cryptic docker error when
# the invoking user can't reach the daemon (common on freshly-provisioned
# self-hosted agents where the service account isn't in the `docker` group
# yet, or the .env change hasn't been picked up by a running agent process).
require_docker() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi
  if sudo -n docker info >/dev/null 2>&1; then
    DOCKER="sudo -n docker"
    return 0
  fi
  cat >&2 <<EOF
ERROR: cannot reach the Docker daemon as user '$(whoami)'.
  Fix on the agent host (one-time):
    sudo usermod -aG docker $(whoami)
  then restart the agent process/service (group membership only applies to
  new login sessions) - simply re-running this script will not pick it up.
EOF
  exit 1
}

# LLM is mandatory (config/models.yaml) - fail before the container starts
# with guidance instead of letting the migrate/selftest call error out deep
# inside the run. Checked from the host, substituting host.docker.internal
# with localhost since that's what --add-host=host.docker.internal:host-gateway
# resolves to for the container.
require_llm() {
  command -v curl >/dev/null 2>&1 || return 0
  local check_url="${LLM_ENDPOINT/host.docker.internal/localhost}"
  if curl -fsS --max-time 5 "$check_url/api/tags" >/dev/null 2>&1; then
    return 0
  fi
  cat >&2 <<EOF
ERROR: Ollama not reachable at $LLM_ENDPOINT (checked $check_url/api/tags from the host).
  Fix on the agent host (one-time):
    1. Install Ollama: https://ollama.com/download
    2. Make it listen on all interfaces so containers can reach it:
       export OLLAMA_HOST=0.0.0.0:11434   (persist in the ollama service
       environment, then restart the ollama service)
    3. Pull the model: ollama pull ${LLM_MODEL:-llama3.1:8b}
  Or set LLM_ENDPOINT to point at a different reachable Ollama/API instead.
EOF
  exit 1
}

build() {
  require_docker
  $DOCKER build -t "$IMAGE" "$ROOT"
}

selftest() {
  require_docker
  require_llm
  $DOCKER run --rm "${LLM_ARGS[@]}" "$IMAGE" selftest
}

demo() {
  require_docker
  require_llm
  mkdir -p "$OUT_DIR"
  if [ ! -d "$ROOT/tests/fixtures/pdfgenerator-ocp" ]; then
    echo "Fixtures missing. Run: ./run.sh fetch" >&2
    exit 1
  fi
  $DOCKER run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$ROOT/tests/fixtures/pdfgenerator-ocp:/workspace:ro" \
    -v "$OUT_DIR:/aks" \
    -v "$CONFIG_DIR:/config:ro" \
    "${LLM_ARGS[@]}" \
    "$IMAGE" migrate \
      --repo BillingDevOps_PDFGenerator \
      --env "${ENVIRONMENT:-dev}" \
      --mode "$MODE" \
      --out /aks \
      $(fail_on_block_flag)
}

# Windows holds file handles (antivirus, indexer, editor watchers) briefly after
# a clone, so a plain `rm -rf` can fail with "Device or resource busy".
# Retry a few times, then warn instead of aborting the whole script.
force_rm() {
  local target="$1" i
  [ -e "$target" ] || return 0
  for i in 1 2 3 4 5; do
    if rm -rf "$target" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "WARNING: could not remove $target (a process is holding it open)." >&2
  echo "         It is safe to delete manually later." >&2
  return 0
}

_looks_like_git_url() {
  case "$1" in
    git@*|*://*|*.git) return 0 ;;
    *)                 return 1 ;;
  esac
}

# Resolves $1 (CLI arg, may be empty) -> a local workspace directory, printed
# on stdout. Falls back to $REPO from the job file, then ./ocp. Clones if the
# result looks like a git URL.
resolve_workspace() {
  local requested="${1:-${REPO:-}}"

  if [ -z "$requested" ]; then
    if [ -d "$ROOT/ocp" ]; then
      requested="$ROOT/ocp"
    else
      echo "usage: ./run.sh migrate <path-or-git-url>" >&2
      echo "       (or set REPO= in migration.env, or check out your repo into ./ocp)" >&2
      exit 1
    fi
  fi

  if _looks_like_git_url "$requested"; then
    local tmp="$ROOT/.tmp-repo"
    force_rm "$tmp" >&2
    echo "Cloning $requested..." >&2
    git clone --quiet "$requested" "$tmp" >&2
    if [ -n "${REPO_BRANCH:-}" ]; then
      ( cd "$tmp" && git checkout --quiet "$REPO_BRANCH" ) >&2
    fi
    echo "$tmp"
  else
    echo "$(resolve_path "$requested")"
  fi
}

migrate() {
  require_docker
  require_llm
  local workspace rc
  workspace="$(resolve_workspace "${1:-}")"
  mkdir -p "$OUT_DIR"
  set +e
  $DOCKER run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$workspace:/workspace:ro" \
    -v "$OUT_DIR:/aks" \
    -v "$CONFIG_DIR:/config:ro" \
    "${LLM_ARGS[@]}" \
    "$IMAGE" migrate \
      --repo "$(basename "$workspace")" \
      $(env_flag) \
      --mode "$MODE" \
      --out /aks \
      $(fail_on_block_flag)
  rc=$?
  set -e
  if [ "$workspace" = "$ROOT/.tmp-repo" ]; then
    force_rm "$workspace"
  fi
  return $rc
}

workbook() {
  local intake="${1:-$WORKBOOK_INTAKE}"
  if [ -z "$intake" ]; then
    echo "usage: ./run.sh workbook <path-to-intake.txt>" >&2
    echo "       (or set WORKBOOK_INTAKE= in migration.env)" >&2
    exit 1
  fi
  intake="$(resolve_path "$intake")"
  mkdir -p "$OUT_DIR"
  require_docker
  require_llm
  $DOCKER run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$intake:/intake.txt:ro" \
    -v "$OUT_DIR:/aks" \
    -v "$CONFIG_DIR:/config:ro" \
    "$IMAGE" workbook \
      --intake /intake.txt \
      --out /aks
}

golden() {
  require_docker
  $DOCKER run --rm --network none \
    --user "$(id -u):$(id -g)" \
    -v "$ROOT/tests/fixtures:/fixtures:ro" \
    -v "$OUT_DIR:/aks" \
    -v "$CONFIG_DIR:/config:ro" \
    "$IMAGE" golden \
      --candidate /aks \
      --reference /fixtures/pdfgenerator-aks \
      --out /aks
}

fetch() {
  local tmp="$ROOT/.tmp-fixtures"
  force_rm "$tmp"
  echo "Cloning BillingDevOps_PDFGenerator..."
  git clone --quiet https://github.com/sparknz/BillingDevOps_PDFGenerator.git "$tmp"

  ( cd "$tmp" && git checkout --quiet master )
  mkdir -p "$ROOT/tests/fixtures/pdfgenerator-ocp"
  cp -r "$tmp/helm" "$tmp/pipeline" "$tmp/Dockerfile" "$ROOT/tests/fixtures/pdfgenerator-ocp/"

  ( cd "$tmp" && git checkout --quiet user/t988794/aks_migration )
  mkdir -p "$ROOT/tests/fixtures/pdfgenerator-aks"
  cp -r "$tmp/helm" "$tmp/pipeline" "$ROOT/tests/fixtures/pdfgenerator-aks/"

  force_rm "$tmp"
  echo "Fixtures ready. Now run: ./run.sh demo"
}

report() {
  cat "$OUT_DIR/validation.md"
}

clean() {
  rm -rf "$OUT_DIR"
}

case "${1:-help}" in
  build)    build ;;
  selftest) selftest ;;
  demo)     demo ;;
  migrate)  shift; migrate "$@" ;;
  workbook) shift; workbook "$@" ;;
  golden)   golden ;;
  fetch)    fetch ;;
  report)   report ;;
  clean)    clean ;;
  *)
    cat <<'EOF'
Usage: ./run.sh <command>

  build                    Build the container image
  selftest                 Verify config and tooling inside the image
  fetch                    Clone OCP + AKS fixtures from GitHub
  demo                     Run offline migration against fixtures
  migrate [path-or-url]    Run against a real repo checkout or git URL
                           (falls back to REPO in migration.env, then ./ocp)
  workbook [path]          Build the migration workbook from a text intake file
                           (falls back to WORKBOOK_INTAKE in migration.env)
  golden                   Score output vs the human AKS branch
  report                   Print $OUT_DIR/validation.md
  clean                    Remove $OUT_DIR

Convenience - migration.env:
  cp migration.env.example migration.env, then set REPO, ENV, MODE,
  FAIL_ON_BLOCK, OUT_DIR, CONFIG_DIR, WORKBOOK_INTAKE, and the LLM_*/
  FREEZE_OUTPUT settings below once instead of passing flags every time.
  An explicit shell env var still wins, e.g. `ENV=int ./run.sh demo`
  overrides ENV= in the file for that one run.

LLM (mandatory) + idempotency:
  Every run calls an LLM to review/refine the migrated files - see
  config/models.yaml (default provider: ollama, runs locally, no API key).
  LLM_ENDPOINT=<url>          default: http://host.docker.internal:11434
  LLM_MODEL=<name>            override the model tag, e.g. llama3.1:8b
  LLM_SEED=<int>              sampling seed, for determinism
  LLM_TIMEOUT=<seconds>       per-file call timeout (default: 600). A file
                              that times out never aborts the run - it just
                              keeps its deterministic output (rule L4).
                              Raise this, or use a smaller LLM_MODEL, on
                              slower/CPU-only/VDI hardware.
  FREEZE_OUTPUT=true|false    replay the last cached response instead of
                              calling the model again - flip on once you're
                              happy with a run, for idempotent output
                              (default: false)
  LLM_FORCE_REFRESH=true|false  regenerate even if FREEZE_OUTPUT is on
  LLM_CACHE_DIR=<path>        default: $OUT_DIR/.llm_cache

Environment overrides:
  ENV=dev|int|nft|stg|prd            target environment (default: dev)
  MODE=offline|assisted|connected    (default: offline)
  REPO=<path-or-git-url>             source repo for `migrate` with no arg
  OUT_DIR=<path>                     artefact output dir (default: ./aks)
  FAIL_ON_BLOCK=true|false           exit non-zero on BLOCK (default: true)

Examples:
  ./run.sh build && ./run.sh fetch && ./run.sh demo
  ENV=int ./run.sh demo
  ./run.sh migrate /c/repos/BillingDevOps_PDFGenerator
  ./run.sh migrate https://github.com/sparknz/BillingDevOps_PDFGenerator.git
  ./run.sh workbook migration-intake.txt

  cp migration.env.example migration.env   # then edit it
  ./run.sh migrate                         # no path needed anymore
EOF
    ;;
esac