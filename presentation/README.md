# presentation/

A leadership-facing one-pager for the AKS Migration Agent, plus the framework
for presenting it.

| File | What it is |
|---|---|
| [`AKS_Migration_Agent_OnePager.pptx`](./AKS_Migration_Agent_OnePager.pptx) | The deck — one dense executive slide: problem, solution, proven results, governance, deliverables, roadmap/ask. |
| [`PRESENTATION_FRAMEWORK.md`](./PRESENTATION_FRAMEWORK.md) | How to present it — narrative arc, card-by-card talking points, 30s/1min/3min pitches, anticipated Q&A, and a backup-deck outline if a technical follow-up is requested. |
| [`build_onepager.py`](./build_onepager.py) | Generates the `.pptx`. Content lives here as code so the numbers are easy to refresh after a real run. |

## Regenerating the deck

The numbers on the slide (rule counts, golden score, finding counts, LLM
refine/revert counts, freeze timing) come from a real
`./run.sh demo && ./run.sh golden` run — refresh them there first if it's
been a while, then rebuild. Note that `demo` now calls a mandatory LLM (see
the main [README](../README.md#the-llm-is-mandatory)); a smaller/faster
local model (e.g. `LLM_MODEL=qwen2.5:1.5b`) keeps the refresh quick.

```bash
python -m venv .venv        # if you don't already have one
.venv/Scripts/pip install -r presentation/requirements.txt
.venv/Scripts/python presentation/build_onepager.py
```

Edit the `stats` list and `cards` list in `build_onepager.py` directly — it's
plain Python, not a template engine.
