# AKS Migration Agent

Model-independent, reference-driven OpenShift → AKS migration agent.
Runs entirely inside one container. No cluster access and no cloud account
are required for the default demo — but an LLM is mandatory on every run
(local, via Ollama, by default: no API key, no per-call cost).

| Layer | Question it answers |
|---|---|
| Repository | What the application currently *is* |
| Reference / RAG | What the organisation *wants* |
| Kubernetes / AKS | What is technically *possible* |
| Agent | Decides *how* to transform, and generates the migrated files (LLM) |
| Validator | Checks whether the result is *acceptable* |
| LLM | Mandatory reasoning + generation component — always re-validated, never trusted for the final decision |

> **Presenting this to stakeholders?** See
> [`presentation/`](presentation/) for a one-slide executive summary
> (`.pptx`) and the talking-points framework that goes with it.
>
> **How the agent itself works?** See
> [`AGENTIC_FRAMEWORK.md`](AGENTIC_FRAMEWORK.md) for the seven-stage
> agent loop, why the LLM is mandatory, the validate-after-generate safety
> net, and the idempotency/freeze mechanism.
>
> **Wiring this into a real CI/CD deploy?** See
> [`azure-pipelines.yaml`](azure-pipelines.yaml) — an Azure DevOps pipeline
> that checks out a separate OCP source repo, converts it with
> `aks-migrator`, and pushes the result back into that repo's own `aks/`
> folder (idempotent — skips re-converting if `aks/` already exists, with a
> `forceConvert` override), then validates the result with `helm lint`. See
> [`pipelines/README.md`](pipelines/README.md) for the two-repo setup.

---

## Prerequisites

| Requirement | Check | Notes |
|---|---|---|
| Docker Desktop, running | `docker version` | Everything runs in the container |
| Ollama, running, with a model pulled | `curl http://localhost:11434/api/tags` | The LLM is mandatory every run - default provider is local Ollama (see [Prerequisites: the LLM](#the-llm-is-mandatory)) |
| Git | `git --version` | Only needed for `fetch` |
| Access to `sparknz/BillingDevOps_PDFGenerator` | `git ls-remote https://github.com/sparknz/BillingDevOps_PDFGenerator.git` | Only needed for `fetch` |

`make` is **not** required. `run.sh` replaces it and works in Git Bash, WSL,
macOS and Linux.

Before the first build, confirm the tree is complete:

```bash
ls -R config policy src
```

You should see five YAML files in `config/`, `policy/aks.rego`, and
`src/aksmig/` containing `providers/`. The build fails if `policy/` is missing,
because the Dockerfile does `COPY policy /app/policy`.

---

## The LLM is mandatory

Every run — `demo`, `migrate`, `selftest` — calls an LLM to review and
update the migrated files (see [`AGENTIC_FRAMEWORK.md`](AGENTIC_FRAMEWORK.md)
for why, and what it is and isn't trusted to do). The default provider is
**Ollama**: it runs on your machine, needs no API key and costs nothing per
call, but it does need to be installed and running first:

```bash
# Install from https://ollama.com, then:
ollama pull llama3.1:8b
ollama serve          # usually already running as a background service
```

`./run.sh selftest` checks it's reachable before you run anything else. If
you'd rather use a hosted provider (Azure OpenAI, OpenAI, Anthropic), edit
`config/models.yaml` — see [Swapping the model](#swapping-the-model).

**Corporate proxy?** If `HTTP_PROXY`/`HTTPS_PROXY` is set machine-wide, it
can silently intercept calls to `localhost`/`host.docker.internal` and make
a running Ollama look unreachable. The Ollama provider explicitly bypasses
the proxy for its own calls (Ollama is inherently local, never something a
web proxy should see) — if `selftest` still reports it unreachable, confirm
`ollama serve` is actually running and listening on the expected port.

---

## Quick start

```bash
chmod +x run.sh
./run.sh build
./run.sh fetch
./run.sh demo
./run.sh report
./run.sh golden
```

Expected end state: a **BLOCK** verdict and a populated `aks/` directory.
That is the correct result — see [Reading the verdict](#reading-the-verdict).

---

## What each step does

### `chmod +x run.sh`

Marks the script executable. One-off. On Windows the filesystem may not persist
the permission bit; if you get `Permission denied`, run `bash run.sh <command>`
instead.

---

### `./run.sh build`

**Builds the container image `aks-migrator:latest`.**

Runs `docker build` against the `Dockerfile`, which assembles a hermetic
toolbox:

| Installed | Version pinned | Purpose |
|---|---|---|
| `python:3.12-slim` | base | Runs the agent |
| `helm` | `v3.16.3` | `helm lint --strict`, `helm template` |
| `kubeconform` | `v0.6.7` | Kubernetes schema validation |
| `conftest` | `0.56.0` | OPA/Rego policy evaluation |
| `trivy` | `0.58.1` | Security misconfiguration scanning |

It then copies `src/`, `config/` and `policy/` into the image, installs the
Python dependencies, creates a **non-root user (UID 10001)**, and sets the
entrypoint to `python -m aksmig`.

**Why versions are pinned:** the output of this agent is audit evidence. An
unpinned `helm` would make yesterday's report irreproducible. The image is also
deliberately non-root — it would be indefensible to ship a tool whose headline
finding is *"your container runs as root"* while running as root itself.

- **Duration:** 2–4 minutes first run; seconds thereafter (layer cache).
- **Requires network:** yes, to download the four tools.
- **Output:** a Docker image. Nothing written to your working directory.

**Verify it worked:**
```bash
./run.sh selftest
```
This confirms all five config files parse and all four binaries are on `PATH`.
Run it any time the build looks suspicious.

---

### `./run.sh fetch`

**Populates `tests/fixtures/` with the real "golden pair" from GitHub.**

Clones `sparknz/BillingDevOps_PDFGenerator` into a temporary directory, then
extracts two snapshots:

| Branch | Copied to | Represents |
|---|---|---|
| `master` | `tests/fixtures/pdfgenerator-ocp/` | **Input** — the OpenShift original |
| `user/t988794/aks_migration` | `tests/fixtures/pdfgenerator-aks/` | **Reference** — the human-verified AKS migration |

It copies only `helm/`, `pipeline/` and `Dockerfile` — the application source
is irrelevant to a deployment migration. The temp clone is deleted afterwards.

**Why this matters:** the agent is not evaluated against a synthetic example.
It is scored against a migration a Spark engineer actually performed and
deployed. `master` is the question; the migration branch is the marking guide.

- **Duration:** under a minute.
- **Requires network:** yes, plus repo access.
- **Output:** `tests/fixtures/pdfgenerator-ocp/` and `.../pdfgenerator-aks/`.
- **Idempotent:** safe to re-run; it overwrites.

**Verify:**
```bash
ls tests/fixtures/pdfgenerator-ocp/helm
```

> If your access is via SSH rather than HTTPS, edit the `git clone` URL in
> `run.sh` to `git@github.com:sparknz/BillingDevOps_PDFGenerator.git`.

---

### `./run.sh demo`

**The main event. Runs the full migration pipeline, offline.**

Mounts three volumes into the container and runs `migrate`:

| Host path | Container path | Mode |
|---|---|---|
| `tests/fixtures/pdfgenerator-ocp` | `/workspace` | read-only |
| `config/` | `/config` | read-only |
| `aks/` | `/aks` | writable |

The source repository is mounted **read-only**. The agent is structurally
incapable of modifying your input.

Seven stages execute in order:

| # | Stage | What happens |
|---|---|---|
| 1 | **DISCOVER** | Walks `/workspace`, classifies every YAML and Dockerfile, scores OpenShift coupling by scanning for markers (`route.openshift.io`, `HelmDeploy@0`, `autoscaling/v1`, `.ocp.internal.spark.co.nz`, …) |
| 2 | **TRANSFORM** | Applies rules **T1–T7** — make it AKS-native |
| 3 | **REMEDIATE** | Applies rules **M1–M9** — fix latent defects OCP tolerated but AKS will reject |
| 4 | **REFINE (LLM)** | The model reviews every file TRANSFORM/REMEDIATE touched and may rewrite it — mandatory, every run (see [`AGENTIC_FRAMEWORK.md`](AGENTIC_FRAMEWORK.md)) |
| 5 | **RENDER** | Writes migrated artefacts to `aks/rendered/` and computes a unified diff |
| 6 | **VALIDATE** | Runs `helm lint --strict`, `helm template`, `kubeconform`, `conftest`, `trivy`, plus residual-OCP, forbidden-API and pipeline-hygiene scans — against the LLM's output, same as anything else |
| 7 | **JUDGE** | Aggregates severity into one decision: `AUTO_APPROVE`, `NEEDS_REVIEW` or `BLOCK` — reads `Finding.severity` only, never LLM text |

**Transform vs Remediate vs Refine — the distinction that matters:**

- **TRANSFORM** = *"make it AKS-native."* Route → Ingress. `HelmDeploy@0` →
  `AzureCLI@2`. `autoscaling/v1` → `v2`. Pool remap. DNS remap.
- **REMEDIATE** = *"fix what was already broken."* A committed production
  secret. A Helm template referencing a value no file defines. CronJobs that
  silently vanish in four of five environments. A Dockerfile running as root.
- **REFINE** = *"finish it."* The LLM reviews exactly the files the two
  deterministic stages above already flagged, and may rewrite them — it
  never touches a file neither stage cared about, and every edit still goes
  through VALIDATE; one that fails is reverted to the deterministic version
  (rule `L3`), never silently kept. A per-file call failure — timeout,
  unreachable endpoint — is handled the same way (rule `L4`): that one
  file keeps its deterministic output, and the run continues rather than
  crashing (see `LLM_TIMEOUT` below if this happens often on slower/CPU-only
  hardware).

A tool that only transforms would faithfully carry every existing defect into
AKS. Remediation is why the agent's output is expected to be a **superset** of
the human migration branch — and why the golden score is judged `≥`, not `==`.

**Offline mode specifics:**

- `--network none` is *not* set here — the LLM call needs to reach Ollama
  (or your configured provider), and trivy may consult local caches. No
  cloud credentials are used with the default Ollama provider.
- Server-side checks (`helm --dry-run=server`, `kubectl auth can-i`) are
  skipped and reported as an `INFO` finding, not silently omitted.

**Duration:** with the default model, seconds for the deterministic stages;
the REFINE stage adds anywhere from under a minute to several minutes
depending on model size, hardware, and how many files were touched — set
`FREEZE_OUTPUT=true` once you're happy with a result to skip regeneration on
every subsequent run (see [Idempotency: freezing a confirmed
result](#idempotency-freezing-a-confirmed-result)).

**Variations:**
```bash
ENV=int ./run.sh demo          # target the INT environment
ENV=prd ./run.sh demo          # PRD — surfaces the committed secret
LLM_MODEL=qwen2.5:1.5b ./run.sh demo   # a smaller/faster local model
```

**Exit code 2 is expected** and means `BLOCK`. It is a finding, not a crash.

---

### `./run.sh report`

**Prints `aks/validation.md` — the human-readable report.**

Pure `cat`; no container involved. This is the artefact to present in a
resourcing or architecture review. It contains:

1. Run metadata — repo, environment, target cluster, namespace, mode, timestamp
2. The verdict and its rationale
3. A severity count table
4. Every transform applied, with rule ID and file
5. Every finding requiring action — location, explanation, remediation

Everything in `aks/`:

| File | Contents | Audience |
|---|---|---|
| `validation.md` | Formatted report | **Humans — present this** |
| `findings.json` | Structured findings | CI gates, dashboards |
| `verdict.json` | Decision + counts | Pipeline exit logic |
| `inventory.json` | Discovered files with coupling scores | Debugging discovery |
| `diff.patch` | Unified diff, source → migrated | Code review |
| `rendered/` | Migrated artefacts | The actual deliverable |

Review the diff like a pull request:
```bash
less aks/diff.patch
git diff --no-index tests/fixtures/pdfgenerator-ocp aks/rendered
```

---

### `./run.sh golden`

**Scores the agent's output against the human-verified AKS branch.**

Compares `aks/rendered/` (agent) against `tests/fixtures/pdfgenerator-aks/`
(human) file by file using sequence similarity, and prints a per-file table:

| Status | Meaning |
|---|---|
| `match` (≥90%) | Agent reproduced the human migration |
| `differs` (70–90%) | Close; inspect the diff |
| `MISSING` | Agent failed to produce a file the human did — **a real gap** |
| `agent extra` | Agent produced something the human did not — **usually remediation working correctly** |

**Phase 1 acceptance target: ≥ 90%.** Exit code `3` if below.

**Read `agent extra` carefully.** It is not automatically a failure. If the
agent emits a `NetworkPolicy` or adds `readinessProbe` blocks the human branch
lacks, that is remediation doing its job. Only `MISSING` entries are
unambiguous regressions.

This step is what converts "we built an AI agent" into a defensible,
quantified claim.

---

## Reading the verdict

| Verdict | Exit | Meaning |
|---|---|---|
| `AUTO_APPROVE` | 0 | All transforms applied, all validators passed |
| `NEEDS_REVIEW` | 0 | No blockers, but human judgement or TBC values outstanding |
| `BLOCK` | 2 | Blocking defects must be resolved before deployment |

**The demo returns `BLOCK`, and that is the point.**

Running against `BillingDevOps_PDFGenerator@master`, the agent should flag:

| Rule | Finding |
|---|---|
| **M1** | `service.yaml` references `.Values.service.targetPort`, but every values file defines `portTarget` — renders empty |
| **M2** | `cronJobs` is defined only in `prd_values.yaml`; four environments render zero CronJobs |
| **M3** | A real production `API_CONNECT_CLIENT_ID` value is committed to `prd_values.yaml` |
| **M7** | No liveness or readiness probes on any Deployment — `--atomic` rollback is therefore unreliable |
| **M8** | `Dockerfile` uses `USER root` and `chmod -R 777` — AKS Pod Security Admission will reject it |
| **V6** | Residual `*.ocp.internal.spark.co.nz` hostnames remain in `dev_values.yaml` and `int_values.yaml` |

The headline is not that the agent migrates YAML. It is that a careful,
manually executed, already-deployed migration still left production-blocking
defects in place — and the agent finds them in twenty seconds.

To produce a report without failing a CI job, run with `FAIL_ON_BLOCK=false`
(or set it once in `migration.env` — see below).

---

## Running against a real checkout

The simplest way — a git URL, cloned automatically:

```bash
./run.sh migrate https://github.com/sparknz/BillingDevOps_PDFGenerator.git
```

Or a local folder you already have checked out:

```bash
git clone https://github.com/sparknz/BillingDevOps_PDFGenerator.git /c/repos/pdfgen
cd /c/repos/pdfgen && git checkout master && cd -

./run.sh migrate /c/repos/pdfgen
ENV=int ./run.sh migrate /c/repos/pdfgen
```

Works on any repository with `helm/` and `pipeline/` directories. To onboard a
different application, add its environments to `config/env-matrix.yaml` — no
code changes.

---

## Convenience: `migration.env`

Typing the repo path/URL, environment and mode on every invocation gets old
fast. Set them once instead:

```bash
cp migration.env.example migration.env   # gitignored - never committed
```

Edit `migration.env`:

```bash
REPO=https://github.com/sparknz/BillingDevOps_PDFGenerator.git
# or: REPO=/c/repos/pdfgen           (a local folder path works too)
REPO_BRANCH=master                    # optional - branch/tag to check out
ENV=int
MODE=offline
FAIL_ON_BLOCK=false                   # so a BLOCK verdict doesn't fail your shell
OUT_DIR=aks                           # where artefacts land (default: ./aks)
CONFIG_DIR=config                     # point at a custom config/ if you have one
WORKBOOK_INTAKE=migration-intake.txt  # default file for `./run.sh workbook`
LLM_MODEL=qwen2.5:1.5b                # smaller/faster model on slower hardware
LLM_TIMEOUT=900                       # raise if REFINE times out on your hardware
```

Then just run:

```bash
./run.sh migrate      # no path needed - reads REPO from migration.env
./run.sh workbook      # no path needed - reads WORKBOOK_INTAKE
```

If `REPO` is blank and no path is given, `./run.sh migrate` falls back to a
local `./ocp` folder if one exists — a convenient standing spot to drop or
check out the repo you're migrating (mirrors `./aks`, the output folder).

**Precedence, low to high:** hardcoded default → `migration.env` → an
explicit shell env var for that one invocation. So `ENV=stg ./run.sh demo`
still overrides `ENV=int` in the file, and a CLI path argument
(`./run.sh migrate /some/other/path`) still overrides `REPO=`.

`make` users get the same variables (`REPO`, `ENV`, `MODE`, `OUT_DIR`,
`CONFIG_DIR`, `FAIL_ON_BLOCK`, `WORKBOOK_INTAKE`) via `-include migration.env`
in the `Makefile` — the same file works for both interfaces. The one
difference: `make migrate` does not auto-clone a git URL, only `run.sh` does;
point `REPO` at a local folder for `make`.

---

## Modes

`--mode` now only controls cluster connectivity for VALIDATE — it no
longer gates the LLM, which runs in every mode (see [The LLM is
mandatory](#the-llm-is-mandatory)):

| Mode | Cluster | Adds |
|---|---|---|
| `offline` | ✗ | Rules T1–T7 + M1–M9, LLM refine, helm lint/template, kubeconform, conftest, trivy. **Default.** |
| `assisted` | ✗ | Same as offline — kept for backwards compatibility with existing scripts/CI |
| `connected` | read-only | Adds `helm --dry-run=server`, `kubectl auth can-i` |

`offline` requires no cluster and no cloud account — with the default
(local) Ollama provider it runs on a laptop with the Wi-Fi off, once the
model is pulled.

---

## Swapping the model

Edit **`config/models.yaml` only**. No code changes anywhere.

```yaml
llm:
  provider: azure_openai   # ollama | azure_openai | openai | anthropic
  model: gpt-4o
  temperature: 0
```

Then, for a hosted provider:
```bash
cp .env.example .env       # add LLM_ENDPOINT and LLM_API_KEY
./run.sh demo
```

The engine only ever calls the `LLMProvider` interface (`complete`, `embed`).
Vendor SDKs live exclusively in `src/aksmig/providers/`. If your organisation
subscribes to a newer model tomorrow, it is a one-line config change — the
migration logic is untouched and needs no re-testing.

Per-task routing keeps cost proportionate: cheap models for classification,
the primary model for transform, remediate and judge.

---

## Idempotency: freezing a confirmed result

The LLM in REFINE isn't guaranteed deterministic between calls — so once a
migrated output looks right, you can freeze it so every future run against
the same input reproduces it exactly, byte-for-byte:

```bash
# migration.env
FREEZE_OUTPUT=false     # default - iterate freely, LLM runs fresh every time
```

Workflow:

1. Run normally until you're happy with the output.
2. Set `FREEZE_OUTPUT=true` in `migration.env`.
3. Every run after that — yours, a teammate's, CI — replays the cached LLM
   response per file instead of calling the model again, verified to
   produce **identical file hashes** across separate runs, and completing
   in seconds instead of minutes since no model calls happen for cached
   files.

Need to regenerate a specific result on purpose while frozen?
`LLM_FORCE_REFRESH=true` for one run, then set it back to `false` and
re-freeze once you like the new output. The cache itself lives at
`LLM_CACHE_DIR` (default `<OUT_DIR>/.llm_cache` — a sibling of `rendered/`,
so it persists the same way the rest of your output directory does).

See [`AGENTIC_FRAMEWORK.md`](AGENTIC_FRAMEWORK.md) §5 for exactly how the
cache key is computed and why every response is recorded regardless of the
freeze flag.

---

## Migration workbook

Not everything about a migration can be discovered by walking a repo — namespace
ownership, which route is actually externally exposed, which database is
staying on-prem, who owns the cutover. The workbook exists to capture that
human knowledge alongside the deterministic Azure mapping, in one artefact you
can hand to a review board.

### Storage mapping

| Requirement           | Azure Service      |
|------------------------|---------------------|
| RWO                    | Azure Disk          |
| RWX                     | Azure Files         |
| Large shared storage    | Azure NetApp Files  |
| Object storage          | Azure Blob          |

### Network mapping

| OpenShift          | Azure             |
|---------------------|-------------------|
| Route                | Ingress           |
| Egress Policies      | Network Policies  |
| Internal Services    | ClusterIP         |
| External Services    | LoadBalancer      |

Both tables are **data, not code** — they live in
[`config/mappings.yaml`](config/mappings.yaml), following the same
"config-driven, no code changes" pattern as `standards.yaml` and
`env-matrix.yaml`. Add a row there to teach the agent a new mapping.

### The workbook columns

| Column | Purpose |
|---|---|
| Namespace | OCP project / AKS namespace |
| Deployment | Workload name |
| Route | OCP `Route` host, if any |
| Service Type | Internal/External (or ClusterIP/LoadBalancer directly) |
| PVC | PersistentVolumeClaim name, if any |
| Storage Type | RWO / RWX / large shared / object — drives the storage mapping above |
| Database | Datastore name and whether it's migrating or staying put |
| Secrets/ConfigMaps | Flags that Key Vault CSI migration is needed |
| AKS Equivalent | Computed from the storage/network mapping tables |
| Owner | Team or person accountable for this row |
| Dependencies | Other namespaces/deployments this one depends on — drives migration sequencing |
| Migration Status | `NOT_YET_MIGRATED` / `NEEDS_INPUT` / `MIGRATED` / your own value |
| Risks | User-supplied notes plus auto-generated flags (unmapped storage type, secrets present, DB cutover strategy undecided, residual OCP hostnames, ...) |

`Service Type`, `Secrets/ConfigMaps`, `Owner` and `Dependencies` weren't in
the original ask — they were added because a workbook without an owner or a
dependency graph can't drive a cutover sequence, and secrets are the single
most common thing teams forget to re-plan for AKS (see rule `M3` above).

### Filling it in

Write what you know in a plain text file — see
[`migration-intake.example.txt`](migration-intake.example.txt). One block per
namespace/deployment, separated by a blank line, `Key: Value` lines, `#` for
comments:

```text
Namespace: billing-prod
Deployment: pdfgenerator
Route: pdfgenerator.apps.prod05.ocp.internal.spark.co.nz
Service Type: External
PVC: pdfgen-data-pvc
Storage Type: RWX
Database: postgres-prod (external, not migrating)
Secrets: API_CONNECT_CLIENT_ID, DB_PASSWORD
Owner: Billing Platform Team
Dependencies: reporting-service
Risks: Shared PVC across 3 replicas; confirm Azure Files performance tier
```

Keys are case-insensitive and a little fuzzy — `App`, `Service` and
`Workload` all mean `Deployment`; `Host`/`URL` mean `Route`; `DB` means
`Database`. Anything you type that isn't recognised is still kept (just not
mapped to a column), so nothing is silently dropped.

Run it:

```bash
./run.sh workbook migration-intake.txt
# or, without Docker:
python -m aksmig workbook --intake migration-intake.txt --out aks --config-dir config
```

This writes `aks/migration_workbook.md` (for the PR/review) and
`aks/migration_workbook.csv` (to open in Excel/Sheets). The agent:

- Matches `Storage Type` / `Service Type` text against `config/mappings.yaml`
  to populate `AKS Equivalent`.
- Flags a row `NEEDS_INPUT` if `Namespace`/`Deployment` is missing, or a PVC
  or storage/service type can't be mapped — the same "ask, don't guess"
  principle as the rest of the tool.
- Appends automatic risk notes (unmapped storage type, secrets needing Key
  Vault CSI migration, database cutover strategy undecided, residual OCP
  hostnames to confirm) on top of whatever you write in `Risks`.

---

## Command reference

| Command | Network | Writes | Purpose |
|---|---|---|---|
| `./run.sh build` | yes | Docker image | Build the toolbox |
| `./run.sh selftest` | no | – | Verify config + tooling |
| `./run.sh fetch` | yes | `tests/fixtures/` | Pull the golden pair |
| `./run.sh demo` | minimal | `aks/` | Run the migration |
| `./run.sh migrate [path-or-url]` | minimal | `aks/` | Run against a real checkout, git URL, or `REPO`/`./ocp` |
| `./run.sh workbook [intake.txt]` | no | `aks/migration_workbook.{md,csv}` | Build the migration workbook |
| `./run.sh report` | no | – | Print the report |
| `./run.sh golden` | no | `aks/golden.json` | Score vs the human branch |
| `./run.sh clean` | no | removes `aks/` | Reset |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `make: command not found` | `make` absent on Windows | Use `./run.sh` — that is what it is for |
| `Permission denied` on `./run.sh` | Permission bit not persisted | `bash run.sh <command>` |
| `docker: command not found` | Docker Desktop not running | Start Docker Desktop, verify with `docker version` |
| `COPY policy: not found` during build | `policy/aks.rego` missing | Save the file, re-run `build` |
| `Fixtures missing` | `fetch` not yet run | `./run.sh fetch` |
| Mount errors / mangled paths | Git Bash path conversion | `run.sh` sets `MSYS_NO_PATHCONV=1`; if invoking Docker directly, prefix the same |
| `git clone` authentication failure | HTTPS vs SSH | Switch the clone URL in `run.sh` to SSH, or use an SSH `REPO=git@github.com:...` in `migration.env` |
| `usage: ./run.sh migrate <path-or-git-url>` | No path given, `REPO=` unset in `migration.env`, and no `./ocp` folder | Pass a path/URL, set `REPO=`, or check out your repo into `./ocp` |
| Golden score under 90% | Fixtures absent, or genuine gap | Confirm `fetch` ran; inspect `MISSING` rows only |
| Exit code 2 | `BLOCK` verdict | Expected on `master`. Read `validation.md` |
| Exit code 3 | Golden below target | Inspect the golden table |
| Workbook row stuck on `NEEDS_INPUT` | Missing namespace/deployment, or an unrecognised storage/service type | Fill the gap in the intake file, or add a matching entry to `config/mappings.yaml` |
| `LLM provider 'ollama' is not available` | Ollama daemon not running, model not pulled, or wrong `LLM_ENDPOINT` | `ollama serve` + `ollama pull <model>`; from a container, endpoint must be `http://host.docker.internal:11434`, not `localhost` |
| LLM calls hang or return `403` unexpectedly | A machine-wide `HTTP_PROXY`/`HTTPS_PROXY` intercepting local traffic | The Ollama provider already bypasses the proxy for its own calls; confirm the daemon itself is reachable with `curl` first |
| REFINE stage is slow | Larger local models are CPU-bound per file | Set `LLM_MODEL=` to a smaller model while iterating, or set `FREEZE_OUTPUT=true` once happy so later runs replay instead of regenerating |
| `TimeoutError: timed out` during REFINE | A file's generation exceeded `LLM_TIMEOUT` (default 600s) — common on slower/CPU-only/VDI hardware with larger models | As of this fix, this no longer crashes the run — that one file keeps its deterministic output and is recorded as finding `L4`. To reduce how often it happens, raise `LLM_TIMEOUT` in `migration.env`, or switch to a smaller `LLM_MODEL` |
| Rule `L3` findings (LLM refinement reverted) | The model's output failed the sanity/YAML check for that file | Informational, not a blocker — the deterministic transform/remediate output was kept; `LLM_FORCE_REFRESH=true` to try again |
| Rule `L4` findings (LLM call failed) | The model call itself errored or timed out for that file | Informational, not a blocker — same fallback as `L3`. See the `LLM_TIMEOUT` row above if this is frequent |

---

## Safety

- **Never writes to a cluster.** There is no apply path in this release.
- **Never pushes to git.** It emits a diff and a rendered tree; you open the PR.
- **Source is mounted read-only.** The agent cannot alter its input.
- **The LLM may generate file content, but it never decides the verdict.**
  JUDGE reads `Finding.severity` values only — never LLM text — to decide
  `AUTO_APPROVE`/`NEEDS_REVIEW`/`BLOCK`.
- **Every LLM edit is re-validated after the fact, not trusted before it.**
  A basic sanity check plus the full VALIDATE stage run against whatever
  the LLM produced; an edit that fails either is reverted to the
  deterministic transform/remediate output (rule `L3`) and recorded, never
  silently kept. See [`AGENTIC_FRAMEWORK.md`](AGENTIC_FRAMEWORK.md) §4.
- **`NEEDS_INPUT` findings are values the agent refuses to guess** — the target
  ACR name, STG cluster facts, and the PRD ingress host. A migration tool that
  invents a resource group is worse than one that stops and asks.

---

## Outstanding inputs

Four values are `TBC` in `config/env-matrix.yaml` and `config/standards.yaml`.
The agent reports them as `NEEDS_INPUT` rather than guessing:

1. **Target ACR name** — replacing `billing-container-registry.artifacts.internal.spark.co.nz`
2. **STG subscription / resource group / cluster** — the STG stage is commented
   out on the migration branch and was never migrated
3. **PRD ingress host** — `master` uses `prod05.ocp`; no AKS equivalent exists yet
4. **AKS namespace PSA labels** — determines whether M8 (`USER root`) is a hard
   blocker or a warning