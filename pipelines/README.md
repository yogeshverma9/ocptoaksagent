# pipelines/

Supporting files for the root-level [`azure-pipelines.yaml`](../azure-pipelines.yaml)
pipeline, which converts an OCP source repo to AKS using `aks-migrator`,
commits + pushes the converted output back into that source repo, then
validates it with `helm lint`.

| File | What it is |
|---|---|
| [`../azure-pipelines.yaml`](../azure-pipelines.yaml) | The pipeline itself: three stages - **Conversion** (idempotent - skips if `aks/` already exists in the source repo) / **force-conversion** (always regenerates and overwrites) / **helm lint validation**. |
| [`scripts/convert-and-push.sh`](./scripts/convert-and-push.sh) | The shared logic behind both conversion stages: check → convert → commit → push. |

## The two-repo architecture

- **Repo A — the OCP source repo.** Contains the application(s) to migrate.
  The converted output is pushed back into **this repo**, into a top-level
  `aks/` folder, as a real git commit.
- **Repo B — this repo.** Named `ocp-to-aks` in git. Contains `aks-migrator`
  itself plus `azure-pipelines.yaml`, and is what the Azure DevOps pipeline
  definition actually lives in (`self`). It's a separate repo from Repo A -
  the pipeline talks to Repo A purely via a multi-repo checkout + a
  `git push` at the end, not by vendoring one repo's content into the other.

`azure-pipelines.yaml`'s `resources.repositories` entry checks out Repo A as
`ocpSource` alongside `self` (Repo B); both get explicit `path:`s so the
scripts can rely on fixed locations regardless of either repo's actual name:

```yaml
resources:
  repositories:
    - repository: ocpSource
      type: github
      name: YOUR_GITHUB_OWNER/YOUR_OCP_SOURCE_REPO   # <- e.g. arun-jathari/nginx-app
      endpoint: YOUR_GITHUB_SERVICE_CONNECTION        # <- see step 1 below
      ref: refs/heads/main
```

Use `type: git` instead (and drop `endpoint:`) if Repo A is an Azure Repos
Git repo rather than GitHub - see the note in step 1.

## One-time setup

1. **Grant push access.** If both repos are on **GitHub** (as above): create
   a GitHub service connection (Project Settings → Service connections →
   New → GitHub) authorised against a token/GitHub App installation with
   **read+write ("repo") access to Repo A**, and reference its name as
   `endpoint:` above. The `self` checkout (Repo B) already works without
   this, since the pipeline itself was created from GitHub - but
   `resources.repositories` entries need their *own* explicit connection.
   If Repo A is an **Azure Repos** git repo instead, use `type: git` with
   `name: <ADO project>/<repo>` (no `endpoint:` needed) and grant
   **Contribute** permission on Repo A to the
   *`[Your Project] Build Service ([Your Organization])`* identity
   (Project Settings → Repositories → Repo A → Security) - the pipeline
   pushes using its own checkout credentials (`persistCredentials: true`),
   not a separate PAT, either way.
2. **`helm` and Docker** on the self-hosted agent - Docker for the
   Conversion/force-conversion stages (they run `./run.sh build/migrate`
   from Repo B), `helm` for the validation stage. No cluster/`kubectl`
   access is required by this pipeline at all - `helm lint` is fully local,
   and this pipeline stops at validation (deploying the validated chart to
   AKS is a separate concern, left to whatever deploy pipeline you already
   have, pointed at the pushed `aks/rendered/helm` chart).
3. **An LLM reachable from the agent** - mandatory for `aks-migrator` (see
   [AGENTIC_FRAMEWORK.md](../AGENTIC_FRAMEWORK.md)). Default provider is
   Ollama, running on/reachable from the agent host.

## How the idempotent Conversion stage works

Rather than guessing from a possibly-ephemeral agent workspace, this design
asks the question the direct way: **is there already an `aks/` folder in
Repo A?** Every run checks out Repo A fresh, so the answer is always
accurate - whatever the last successful pipeline run actually pushed.

```bash
if [ -d "$OCP_SOURCE_PATH/aks/rendered" ] && [ has *.yaml files* ]; then
  echo "already converted - skip"
else
  ./run.sh build && OUT_DIR="$OCP_SOURCE_PATH/aks" ./run.sh migrate "$OCP_SOURCE_PATH"
  git add aks/ && git commit && git push   # back into Repo A
fi
```

- **`Conversion`** stage (runs when `forceConvert=false`, the default): the
  check above - skip if already converted, else convert and push.
- **`force-conversion`** stage (runs only when `forceConvert=true`, a
  pipeline parameter): skips the check and always reconverts, overwriting
  whatever was there and pushing the new result.
- Exactly one of the two stages actually runs per invocation - the other is
  reported "Skipped" by Azure Pipelines, which counts as satisfying
  `succeeded()` for the dependent `helm lint validation` stage, so
  validation always runs after whichever one applied.
- If the freshly-converted output is byte-identical to what's already
  committed (can happen with `FREEZE_OUTPUT=true` - see
  [AGENTIC_FRAMEWORK.md §5](../AGENTIC_FRAMEWORK.md)), the script detects
  "nothing to commit" via `git diff --cached --quiet` and skips the push
  rather than creating an empty commit.

## Why Helm, not `kubectl apply`

`aks-migrator` outputs a migrated **Helm chart** (`aks/rendered/helm`), not
flattened plain manifests - the templates still contain `{{ .Values.x }}`
syntax. `helm lint` here validates that chart directly; this is also the
pattern `aks-migrator` itself generates for a *migrated application's own*
CD pipeline (see rule `T2` in [`config/rules.yaml`](../config/rules.yaml)).
