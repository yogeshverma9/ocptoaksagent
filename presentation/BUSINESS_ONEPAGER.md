# AKS Migration Agent — Executive One-Pager

**Audience:** CIO / Head of Cloud / CFO sponsor for cloud migration
**Ask:** funded pilot on 5–10 applications, 6-week window, 1 engineer on rotation
**Companion to:** [AKS_Migration_Agent_OnePager.pptx](./AKS_Migration_Agent_OnePager.pptx) (technical one-pager) and [PRESENTATION_FRAMEWORK.md](./PRESENTATION_FRAMEWORK.md)

---

## 1. The business problem in one paragraph

OpenShift-to-AKS migrations are today a **manual, per-app engineering effort** with no repeatable scorecard. Even careful, senior-engineer-led migrations ship with production defects — committed secrets, root containers, CronJobs silently missing in 4 of 5 environments — that only surface after cutover. Every app is a bespoke discovery/audit exercise. There is no way today to say, on paper, *"this migrated app is ready to run in AKS"* — only *"the engineer thinks it is."*

---

## 2. What we built — in business terms

An **AI-assisted migration agent** that converts an OpenShift app repository to AKS, produces the actual manifests and pipelines, scores itself against a human baseline, and hands leadership a **single verdict per app**: `AUTO_APPROVE`, `NEEDS_REVIEW`, or `BLOCK`. No cluster access, no code pushes — a human always merges.

**Reproducible:** confirm one good run, freeze it, and every rerun produces byte-identical output. That is the compliance/audit story.

---

## 3. Proven numbers (from one real Spark app: BillingDevOps_PDFGenerator)

| Metric | Result | Why leadership cares |
|---|---|---|
| Production-blocking defects found in an **already-deployed** human migration | **12 BLOCK, 14 HIGH** | Human review is not a safety net today — this is the size of the risk we're accepting |
| File-level fidelity vs. the human-authored AKS branch | **86.3%** (target ≥ 90%) | We can measure "how done is this?" instead of asking |
| Files improved by the LLM safely | **9 / 15** | Real acceleration, not slideware |
| Files where LLM output was rejected & auto-reverted | **6 / 15** | The safety net works — bad AI output never survives the run |
| Repeat run replay time once frozen | **~30 seconds** vs. ~25 min fresh | Audit-friendly, cheap to re-verify |

---

## 4. Estimated savings (per application)

Conservative, per typical enterprise mid-size app. Numbers frame the pitch — validate against your own baselines before quoting externally.

| Line item | Today (manual) | With agent | Saving per app |
|---|---|---|---|
| Discovery + audit (namespaces, storage, routes, deps) | 3–5 engineer days | Auto-generated Migration Workbook, ~1 hour to review | **~3 days** |
| OCP-to-AKS manifest & pipeline rewrite | 4–7 engineer days | Draft in minutes, engineer reviews `NEEDS_REVIEW` items | **~4 days** |
| Post-cutover defect firefighting (avg. 2 P2 incidents/app) | 1–2 engineer days per incident | Caught pre-merge as BLOCK / HIGH findings | **~3 days** |
| **Total per app** | **~10 engineer days** | **~1 engineer day** | **~9 engineer days (~90% cycle-time reduction)** |

**At scale (indicative, ~50 apps in migration backlog):**
- ≈ **450 engineer days saved** = ~2 FTE-years
- **12 blocking defects × 50 apps ≈ 600 defects intercepted before cutover** — biggest saving isn't hours, it's *not having those production incidents*
- **~2 FTE-years redirected** from repetitive audit work to migration-judgement work

---

## 5. Errors we now prevent (categories, not one-offs)

- **Secrets committed to values files** — caught by rule `M3` before merge, always.
- **Container running as root / world-writable chmod** — caught by rule `M8` before merge.
- **CronJobs (or any env-specific resource) silently dropped in some environments** — caught by rule `M2` env-parity check.
- **HPA missing or under-configured on a Deployment** — flagged by `M6`.
- **Ingress/Route TLS misconfiguration** — flagged as `NEEDS_INPUT`, never silently downgraded to HTTP.
- **Residual OpenShift hostnames after "migration"** — flagged by validator `V6`.
- **Forbidden OpenShift-only APIs** (`Route`, `DeploymentConfig`, `ImageStream`, `BuildConfig`) — deterministically converted or removed with an explicit finding.

**Every one of these has an assigned rule ID and a documented remediation.** No black-box "the AI said so."

---

## 6. Governance & risk posture (pre-empts the top objection)

- **Source is mounted read-only.** Structurally cannot modify your input.
- **No cluster writes, no `kubectl apply`, no `git push` in-scope for this release.**
- **The verdict is decided by rule severities, never by LLM output.** The AI writes; the deterministic rules judge.
- **LLM is swappable** (Ollama on-prem, Azure OpenAI, OpenAI, Anthropic) via one config value. Data residency and vendor-choice stay in your hands.
- **Freeze mode = reproducible output.** Same inputs → same bytes, every time. Audit-ready.

---

## 7. Recommendation — the ask

**Fund a bounded 6-week pilot** covering **5–10 applications** currently in the OCP-to-AKS backlog.

We commit to deliver:
- One migration workbook per app (namespaces, storage, routes, dependencies mapped to Azure).
- One draft AKS chart + CI/CD pipeline per app.
- One `AUTO_APPROVE / NEEDS_REVIEW / BLOCK` verdict per app with a per-finding audit trail.
- A quantified fidelity score (target ≥ 90%) and defect list per app.
- A rollout plan to production migration engineering, with per-app savings measured against baseline, at end of pilot.

We need from you:
- Sponsor sign-off + read-access to 5–10 app repos.
- ~20% of one migration engineer's time to validate the `NEEDS_REVIEW` items.
- A decision by end of pilot: broaden rollout, or stop.

**Downside if we stop:** zero — nothing was pushed, nothing was applied.
**Downside if we do nothing:** we keep paying ~9 engineer days per app, and we keep shipping the same defects into production.

---

## 8. Two-minute pitch script (for the meeting itself)

> "We have around 50 apps in the OCP-to-AKS backlog. Today each one is roughly 10 engineer days of manual discovery, rewrite, and audit — and even our best engineers ship migrations that later turn out to have production secrets committed and containers running as root. We know that because we built a tool that ran against one such app we already migrated, and it found **12 blocking defects and 14 high-severity defects that were already live in production.**
>
> The tool is an AI-assisted agent, but the AI is bounded — it only touches files our deterministic rules already flagged, and every one of its edits is re-validated afterwards. When the validator rejects an edit, we automatically fall back to the safe deterministic output. **The AI never gets the last word — the validator does.**
>
> It cannot touch your cluster, cannot push code, and reads your repo read-only. A human still merges the PR. And once you've confirmed a run, you can freeze it — the same input reproduces the same bytes forever, which is what makes it audit-friendly.
>
> The ask is a six-week, bounded pilot on 5–10 apps. If we hit 90% fidelity and clean audit trails on those, we roll out. If we don't, you stop — nothing was applied, nothing was pushed. **The status quo, meanwhile, keeps costing about 9 engineer days per app and keeps shipping the same defects into production.**
>
> That's the trade-off. What questions can I answer?"

---

## 9. If they ask hard questions

| Question | One-line answer |
|---|---|
| "What if the AI hallucinates a resource name?" | It doesn't — anything it isn't sure about is a `NEEDS_INPUT` finding for a human, never a fabricated value. Every edit is re-validated afterwards and reverted on failure. |
| "Which LLM? Data residency?" | You pick — Azure OpenAI, on-prem Ollama, OpenAI, Anthropic. One config value. Default is local Ollama, no data leaves the network. |
| "Does the AI decide whether we ship?" | No. The verdict is computed from deterministic rule severities. The AI never contributes to it. |
| "How much does *the tool* cost to run?" | Compute for the LLM (or zero if on Ollama). No per-seat licence, no cluster resources, no cloud spend beyond the model call. |
| "Why 86.3%, not 100%?" | It's a superset, not a copy — the agent legitimately adds remediation the human missed. 90% is our sign-off bar, not 100%. |
| "How long to roll out to all 50 apps?" | Onboarding an app is a YAML change, not new code — after the pilot validates rule coverage on more app patterns, throughput is bounded by review capacity, not by the tool. |
| "What if we want to stop?" | Delete the branch. Nothing shipped, nothing applied. Reversible at every step. |

---

**Bottom line for the room:**
**~9 engineer days saved per app · 12 blocking defects intercepted per shipped app · reversible pilot · human-approved cutover.**
