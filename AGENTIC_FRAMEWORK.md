# Agentic Framework — AKS Migration Agent

This document describes the **agent architecture** of the migration engine
itself: how it perceives, reasons, acts, checks itself, and decides — and,
specifically, how the LLM is wired in as a mandatory, file-generating part of
that loop, with a deterministic "freeze" mechanism so a confirmed result can
be reproduced exactly, on demand, forever.

This is not a presentation aid (see [`presentation/`](presentation/) for
that) - it's the design reference for the agent's own behaviour: what each
stage is accountable for, where the LLM is and isn't trusted, and how
idempotency is guaranteed even though LLMs are not inherently deterministic.

---

## 1. The agent loop

The agent is a **single-pass, seven-stage pipeline**, not a conversational
or open-ended agent — every run is bounded, ordered, and auditable:

```
 1. DISCOVER    perceive:  walk the repo, classify every file, score
                           OpenShift coupling
 2. TRANSFORM   act:       deterministic rules rewrite OpenShift constructs
                           to their AKS equivalent (T1-T8)
 3. REMEDIATE   perceive:  deterministic rules detect latent defects
                           OpenShift tolerated but AKS will reject (M1-M9)
 4. REFINE      act (LLM): the model reviews every file TRANSFORM/REMEDIATE
                           touched and may rewrite it - mandatory, every run
 5. RENDER      act:       write the accepted files to disk, compute the diff
 6. VALIDATE    check:     helm lint/template, kubeconform, conftest, trivy,
                           residual-OCP/forbidden-API scans - re-run against
                           the LLM's output, not just the deterministic one
 7. JUDGE       decide:    aggregate every finding from every stage into one
                           verdict: AUTO_APPROVE / NEEDS_REVIEW / BLOCK
```

Mapping this to standard agent vocabulary:

| Agent concept | Where it lives here |
|---|---|
| **Perception** | DISCOVER (file classification) and REMEDIATE (defect detection) |
| **Reasoning / generation** | REFINE - the only stage that calls the LLM |
| **Action** | TRANSFORM and REFINE mutate the migrated file set; RENDER commits it to disk |
| **Self-check / reflection** | VALIDATE - runs unconditionally against whatever REFINE produced |
| **Decision** | JUDGE - deterministic aggregation, never delegated to the LLM |
| **Memory** | The on-disk LLM cache (`LLM_CACHE_DIR`) + every run's `findings.json`/`verdict.json` as an audit trail |
| **Tools** | `helm`, `kubeconform`, `conftest`, `trivy` - called by VALIDATE, never by the LLM directly |

The agent never loops, re-plans, or calls the LLM more than once per file per
run. This is a deliberate choice: a bounded, seven-stage pass is auditable
and timeable; an open-ended agentic loop is neither.

---

## 2. Why the LLM is mandatory, and what it's actually trusted to do

Earlier versions of this agent treated the LLM as optional narrative only
(`provider: "null"` by default). That has changed: **every run now calls an
LLM, and its output can directly become the migrated file content.**

This is a bigger trust surface than "the LLM writes commentary," so the
guardrail model shifted with it - from *stopping the LLM from touching
files* to *catching it if it gets something wrong after the fact*:

| | Old model | Current model |
|---|---|---|
| Can the LLM touch rendered files? | No (`forbidLlmDirectApply: true`) | Yes (`forbidLlmDirectApply: false`) |
| What catches a bad LLM edit? | It never got the chance | VALIDATE, run against the LLM's output, same as any other stage |
| What happens if VALIDATE would have failed on the LLM's edit? | N/A | See §4 - rejected pre-emptively by a sanity check, reverted to the deterministic output, recorded as finding `L3` |
| Is the decision (BLOCK/etc.) ever made by the LLM? | No | Still no - JUDGE only ever reads `Finding.severity`, never LLM text |

The scope of what the LLM is asked to do is deliberately narrow and
*bounded by the deterministic engine*, not free-roaming:

- It only ever sees files that TRANSFORM already changed, or that REMEDIATE
  already flagged with a finding (`src/aksmig/llm_refine.py::refine_files`,
  the `changed | flagged` target set). It cannot introduce a new file, and
  it never sees files the deterministic engine considered untouched.
- Its system prompt (`SYSTEM_PROMPT` in `llm_refine.py`) instructs it to
  preserve Helm templating syntax verbatim and to change only what's
  necessary - it is not asked to redesign the file.
- Its context is the rule engine's own findings (`FINDINGS FOR THIS FILE`)
  and the org's own standards (`config/standards.yaml` excerpts) - it is
  reasoning from the same policy the deterministic rules already enforce,
  not inventing new policy.

This makes the LLM closer to **a bounded code-review-and-patch step
delegated by the deterministic engine** than an autonomous generator - see
[`config/models.yaml`](config/models.yaml) `guardrails:` for the policy
statement, and [`llm_refine.py`](src/aksmig/llm_refine.py) for the
implementation.

---

## 3. Provider abstraction

The engine only ever calls `LLMProvider.complete()` /
`LLMProvider.embed()` (`src/aksmig/providers/base.py`). Vendor SDKs live
exclusively under `src/aksmig/providers/`; swapping providers is a
one-line change to `config/models.yaml`, never a code change.

Default provider: **Ollama**, local, no API key, no per-call cost - it
still needs the Ollama daemon installed, running, and the configured model
pulled (`ollama pull llama3.1:8b`). `azure_openai` / `openai` / `anthropic`
are supported the same way for a hosted model.

Because the LLM is now mandatory, `selftest` and `migrate` both hard-fail
fast if the configured provider isn't reachable
(`OllamaProvider.available` does a live `/api/tags` check) rather than
silently degrading to a deterministic no-op the way the old `null` provider
did.

**Operational note - corporate proxies:** Ollama is inherently a
local/private-network service. A machine-wide `HTTP_PROXY`/`HTTPS_PROXY`
can silently break `localhost`/`host.docker.internal` calls to it (a proxy
returning `403` for traffic it doesn't recognise). `OllamaProvider` builds
its own `urllib` opener with proxying explicitly disabled
(`_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))`)
so this can't happen silently - see the comment in
[`ollama_provider.py`](src/aksmig/providers/ollama_provider.py).

---

## 4. The safety net: validate-after-generate, not trust-before-generate

Every LLM response for a file goes through checks before it's accepted -
and, just as importantly, the call itself is never allowed to take the
whole run down with it:

0. **The model call is wrapped in a per-file try/except** (`refine_files` in
   `llm_refine.py`). A timeout, an unreachable endpoint, or any other
   provider error for one file is caught, that file keeps its deterministic
   output, and the loop moves on - it does not abort the run. This matters
   in practice: CPU-only or VDI hardware can make a single file's generation
   exceed `LLM_TIMEOUT`, and that must degrade gracefully, not crash a
   pipeline that otherwise fully succeeded.
1. **A cheap sanity check, inline in REFINE** (`_looks_valid` in
   `llm_refine.py`): non-empty, and if the file was valid YAML before, the
   candidate must still parse as YAML (Helm-placeholder-tolerant). This
   catches truncation, refusals, and garbage output immediately, without
   spending a VALIDATE cycle on it.
2. **The full VALIDATE stage**, unconditionally, against whatever REFINE
   produced - `helm lint --strict`, `helm template`, `kubeconform`,
   `conftest`, `trivy`, residual-OCP/forbidden-API scans. An LLM edit that
   passes the cheap check but breaks a real validator surfaces as a normal
   `V*` finding, exactly like a defect in the deterministic output would.

If check 0 or check 1 fails, the file is **reverted to the deterministic
transform/remediate output** and a finding is recorded:

| Rule | Meaning |
|---|---|
| `L1` | LLM reviewed and updated this file - generated fresh this run |
| `L2` | Frozen/cached response replayed verbatim (idempotent output) |
| `L3` | LLM output failed the sanity check; deterministic output was kept |
| `L4` | The model call itself failed (timeout, unreachable endpoint, provider error); deterministic output was kept |

`L1`/`L2` are `INFO` (transparency, not a problem). `L3`/`L4` are `MEDIUM` -
visible in the report, not silently swallowed, but not itself a blocker
either: the deterministic engine's output - the same one this whole tool was
originally scored against - is always the fallback, never a null result or
a crash.

---

## 5. Idempotency: the freeze mechanism

LLMs are not guaranteed deterministic - even at `temperature: 0`, output can
drift between calls, hosts, or model point-releases. Confirming "this
migration output is correct" is only useful if you can get that exact same
output again later (a second reviewer, a re-run before merge, an audit six
months on). The freeze mechanism exists to make that guarantee without
depending on the model itself being deterministic.

**How it works** (`LLMCache` in `llm_refine.py`):

- Every LLM call is keyed by a content hash of
  `(provider name, model, system prompt, the exact user prompt for that
  file)` - `_cache_key()`. Any change to the input (a different file, a
  different rule outcome upstream, a different model) is a different key.
- **Every** response is written to the cache when generated, regardless of
  the freeze flag - the cache always holds "the latest attempt" for each
  key.
- Whether a cached response is *read back* is gated by one flag:
  - `FREEZE_OUTPUT=false` (default): always call the model fresh. Use this
    while iterating - each run can differ as you tune rules/standards/model.
  - `FREEZE_OUTPUT=true`: replay the cached response for a matching key
    instead of calling the model. If no cached entry exists yet for that
    key, it generates once and the result becomes the frozen baseline for
    every run after.
  - `LLM_FORCE_REFRESH=true`: escape hatch - call the model even if frozen,
    to deliberately produce a new draft (then flip back to `false` and
    re-freeze once you like the new result).

**The intended workflow, matching how a human actually confirms a result:**

1. Run normally (`FREEZE_OUTPUT=false`, the default) until the migrated
   output looks right.
2. Set `FREEZE_OUTPUT=true` in `migration.env`.
3. Every subsequent run - by you, by a teammate, by CI, six months from
   now - reproduces **byte-for-byte identical** output for that input, with
   no further model calls for files that already have a cached response.

This was verified directly: two separate process invocations, `git`
identical input, `FREEZE_OUTPUT=true` both times, produced files with
matching SHA-256 hashes and the run that replayed from cache completed in
seconds instead of minutes (no model calls at all for the cached files).

**Where the cache lives:** `LLM_CACHE_DIR`, default
`<OUT_DIR>/.llm_cache` - a sibling of `rendered/` inside your output
directory, so it survives across `--rm`'d containers the same way the rest
of `OUT_DIR` does, without needing a separate volume mount.

---

## 6. Configuration surface (`migration.env`)

All of the above is controlled from the same job file used for repo
path/environment/mode (see [`migration.env.example`](migration.env.example)):

| Variable | Purpose |
|---|---|
| `LLM_ENDPOINT` | Where the provider lives. Defaults to Docker Desktop's host gateway (`host.docker.internal`) since "localhost" inside the container is the container itself. |
| `LLM_MODEL` | Override the model tag from `config/models.yaml`, e.g. a smaller/faster model while iterating. |
| `LLM_SEED` | Sampling seed, provider-dependent. |
| `LLM_TIMEOUT` | Per-file call timeout in seconds (default: 600). A file that exceeds it is not retried mid-run - it keeps its deterministic output and is recorded as `L4` (§4). Raise this, or drop to a smaller `LLM_MODEL`, on slower/CPU-only/VDI hardware. |
| `FREEZE_OUTPUT` | The idempotency switch - see §5. |
| `LLM_FORCE_REFRESH` | One-shot override to regenerate while frozen. |
| `LLM_CACHE_DIR` | Override the cache location if you want one shared across multiple `OUT_DIR`s. |

`config/models.yaml` holds the policy defaults (provider, model, temperature,
guardrails); `migration.env` holds the per-run/per-operator knobs. This
mirrors the existing split in the rest of the tool: YAML under `config/` is
what the organisation decides once, `migration.env` is what an operator
tunes per run.

---

## 7. What stays deterministic, on purpose

Not everything moved to the LLM, and that's intentional:

- **TRANSFORM (T1-T8)** and **REMEDIATE (M1-M9)** remain plain rule-engine
  code (`transform.py`, `remediate.py`). They are what the golden-diff score
  (`./run.sh golden`) is measured against, and what makes "this finding is
  rule `M3`" a reproducible, inspectable claim rather than a model's opinion.
- **JUDGE** reads `Finding.severity` values only - never LLM free text -
  to decide `AUTO_APPROVE`/`NEEDS_REVIEW`/`BLOCK`.
- **VALIDATE**'s external tools (`helm`, `kubeconform`, `conftest`, `trivy`)
  are unaware an LLM was involved at all; they validate the final files the
  same way regardless of which stage produced them.

The LLM's job is narrowly: *take what the deterministic engine already
decided needs attention, and finish the file* - not to replace the
deterministic engine, and not to make the go/no-go call.
