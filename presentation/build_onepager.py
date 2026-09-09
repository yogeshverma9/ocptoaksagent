"""Generates presentation/AKS_Migration_Agent_OnePager.pptx.

A single dense executive slide summarising the AKS Migration Agent for a
leadership/stakeholder audience. Content lives here as code (not hand-edited
in PowerPoint) so the numbers stay easy to refresh after a real ./run.sh demo
+ ./run.sh golden run - see PRESENTATION_FRAMEWORK.md for the numbers' source
and the talking points that go with each section.

Numbers below are from a run with LLM_MODEL=qwen2.5:1.5b (a small local
model, chosen so the fresh-generation timing is reproducible in a few tens
of minutes rather than longer on larger models on CPU-only hardware) against
config/models.yaml's default provider (ollama). The "~30s frozen" stat is
FREEZE_OUTPUT=true replaying the same run; the "~25 min" fresh-generation
figure is model/hardware-dependent, not a fixed guarantee - see
AGENTIC_FRAMEWORK.md section 5.

Regenerate after editing:
    python -m pip install python-pptx
    python presentation/build_onepager.py
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Emu, Inches, Pt

OUT = Path(__file__).parent / "AKS_Migration_Agent_OnePager.pptx"

# --- Palette ----------------------------------------------------------------
NAVY = RGBColor(0x1B, 0x26, 0x40)
AZURE = RGBColor(0x00, 0x78, 0xD4)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x22, 0x22, 0x22)
GREY = RGBColor(0x5A, 0x5A, 0x5A)
LIGHT_BG = RGBColor(0xF4, 0xF6, 0xF9)
CARD_BG = RGBColor(0xFF, 0xFF, 0xFF)
BORDER = RGBColor(0xDC, 0xE1, 0xE8)

RED = RGBColor(0xC0, 0x2B, 0x2B)
GREEN = RGBColor(0x1E, 0x7B, 0x34)
TEAL = RGBColor(0x0E, 0x7C, 0x86)
PURPLE = RGBColor(0x5B, 0x3E, 0x96)
GOLD = RGBColor(0xB0, 0x7D, 0x0E)

FONT = "Segoe UI"


def _textbox(slide, x, y, w, h, *, anchor=MSO_ANCHOR.TOP, wrap=True):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Pt(2)
    tf.margin_top = tf.margin_bottom = Pt(1)
    return box, tf


def _set_run(run, *, size, bold=False, color=INK, italic=False, font=FONT):
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color


def _para(tf, text, *, size=10, bold=False, color=INK, space_after=2,
          bullet=False, first=False, align=PP_ALIGN.LEFT):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_after = Pt(space_after)
    prefix = "\u2022  " if bullet else ""
    run = p.add_run()
    run.text = prefix + text
    _set_run(run, size=size, bold=bold, color=color)
    return p


def _rect(slide, x, y, w, h, fill, *, line=None, shape=MSO_SHAPE.RECTANGLE,
          shadow=False):
    shp = slide.shapes.add_shape(shape, x, y, w, h)
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(0.75)
    shp.shadow.inherit = False
    return shp


def build() -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

    # Full-bleed light background
    _rect(slide, 0, 0, prs.slide_width, prs.slide_height, LIGHT_BG)

    # --- Header band ---------------------------------------------------
    header_h = Inches(1.05)
    _rect(slide, 0, 0, prs.slide_width, header_h, NAVY)

    _, tf = _textbox(slide, Inches(0.35), Inches(0.08), Inches(9.2), Inches(0.55))
    _para(tf, "AKS Migration Agent", size=26, bold=True, color=WHITE, first=True)

    _, tf = _textbox(slide, Inches(0.37), Inches(0.62), Inches(9.2), Inches(0.4))
    _para(tf, "AI-assisted, reference-driven OpenShift \u2192 Azure Kubernetes Service migration \u2014 "
              "a mandatory LLM refines every file, with byte-for-byte idempotent output once confirmed.",
          size=11.5, color=RGBColor(0xC9, 0xD6, 0xEA), first=True)

    # Badge top-right
    badge_w, badge_h = Inches(3.05), Inches(0.55)
    badge = _rect(slide, prs.slide_width - badge_w - Inches(0.35), Inches(0.25),
                  badge_w, badge_h, AZURE, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    badge.adjustments[0] = 0.25
    tf = badge.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    _para(tf, "LLM-MANDATORY \u00b7 IDEMPOTENT BY DESIGN", size=11.5, bold=True, color=WHITE,
          first=True, align=PP_ALIGN.CENTER)

    # --- Footer stat strip ----------------------------------------------
    footer_h = Inches(0.62)
    footer_y = prs.slide_height - footer_h
    _rect(slide, 0, footer_y, prs.slide_width, footer_h, NAVY)

    stats = [
        ("17+LLM", "deterministic rules (8 transform + 9 remediate) plus a mandatory LLM refine stage"),
        ("9/15", "files the LLM safely improved this run; 6 failed validation and were auto-reverted"),
        ("12B/14H", "BLOCK/HIGH defects found in an already-deployed, human-verified migration"),
        ("86.3%", "fidelity vs. the human-authored AKS branch (target \u2265 90%)"),
        ("~30s", "to replay a frozen result vs. ~25 min to generate fresh \u2014 confirm once, reproduce forever"),
    ]
    n = len(stats)
    gap = Inches(0.12)
    col_w = Emu(int((prs.slide_width - Inches(0.3) * 2 - gap * (n - 1)) / n))
    x = Inches(0.3)
    for big, small in stats:
        _, tf = _textbox(slide, x, footer_y + Inches(0.04), col_w, footer_h - Inches(0.08),
                          anchor=MSO_ANCHOR.MIDDLE)
        p = _para(tf, big, size=14, bold=True, color=AZURE, first=True, align=PP_ALIGN.CENTER)
        p.space_after = Pt(0)
        _para(tf, small, size=7.5, color=RGBColor(0xD4, 0xDC, 0xEA), align=PP_ALIGN.CENTER)
        x = Emu(int(x + col_w + gap))

    # --- Body: 3x2 card grid ---------------------------------------------
    margin = Inches(0.3)
    top = header_h + Inches(0.12)
    bottom = footer_y - Inches(0.12)
    body_h = Emu(int(bottom - top))
    body_w = Emu(int(prs.slide_width - margin * 2))

    col_gap = Inches(0.16)
    row_gap = Inches(0.14)
    col_w = Emu(int((body_w - col_gap * 2) / 3))
    row_h = Emu(int((body_h - row_gap) / 2))

    cards = [
        # (title, accent, bullets)
        ("THE PROBLEM", RED, [
            "Manual OCP\u2192AKS migrations are slow, inconsistent, "
            "and hard to audit across dozens of apps/environments",
            "Careful, already-deployed human migrations still hide "
            "production-blocking defects (root containers, committed "
            "secrets, missing probes)",
            "No repeatable, scorable way to prove a migration is "
            "safe before cutover",
        ]),
        ("THE SOLUTION", AZURE, [
            "Seven-stage agent loop: Discover \u2192 Transform \u2192 "
            "Remediate \u2192 Refine (LLM, mandatory) \u2192 Render \u2192 "
            "Validate \u2192 Judge",
            "The LLM only reviews files the deterministic rules already "
            "flagged \u2014 it never roams free over the repo",
            "Config-driven: onboard a new app/environment via YAML \u2014 "
            "zero code changes. Storage/network \u2192 Azure mapping "
            "tables + auto-generated Migration Workbook",
        ]),
        ("PROVEN RESULTS", GREEN, [
            "Benchmarked against a real, human-verified Spark migration "
            "(BillingDevOps_PDFGenerator)",
            "Finds defects the human migration missed: committed "
            "prod secret, root-user container, CronJobs silently "
            "dropped in 4/5 environments",
            "Never guesses \u2014 flags NEEDS_INPUT (e.g. target ACR, "
            "ingress host) instead of fabricating values",
        ]),
        ("GOVERNANCE & SAFETY", PURPLE, [
            "Source repo mounted read-only \u2014 structurally cannot "
            "modify your input; no cluster writes, no git pushes",
            "The LLM may generate file content directly, but every edit "
            "is re-validated after the fact \u2014 a failed edit reverts "
            "to the deterministic output, never silently kept",
            "Confirm once, freeze the result: idempotent output is "
            "reproducible byte-for-byte on every future run",
        ]),
        ("EVERY RUN DELIVERS", TEAL, [
            "validation.md \u2014 human-readable report for review boards",
            "diff.patch + rendered/ \u2014 PR-ready migrated artefacts",
            "migration_workbook.md/.csv \u2014 namespace/storage/network/"
            "database inventory and risk register",
            "AUTO_APPROVE / NEEDS_REVIEW / BLOCK \u2014 a CI-gateable verdict, "
            "decided from rule severities, never from LLM text",
        ]),
        ("ROADMAP & THE ASK", GOLD, [
            "Now: mandatory LLM + idempotent freeze proven end-to-end on a "
            "real production app (Phase 1 target: \u2265 90% fidelity)",
            "Next: evaluate hosted model providers for quality/speed, "
            "widen rule/mapping coverage, Connected mode (live cluster "
            "dry-run + RBAC checks)",
            "Ask: sponsor a pilot across N additional applications; "
            "feedback on rule/mapping coverage",
        ]),
    ]

    for i, (title, accent, bullets) in enumerate(cards):
        row, col = divmod(i, 3)
        x = Emu(int(margin + col * (col_w + col_gap)))
        y = Emu(int(top + row * (row_h + row_gap)))

        card = _rect(slide, x, y, col_w, row_h, CARD_BG, line=BORDER,
                      shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        card.adjustments[0] = 0.045

        # Accent bar on the left edge
        _rect(slide, x, y, Inches(0.08), row_h, accent)

        pad_x = Inches(0.18)
        _, tf = _textbox(slide, x + pad_x, y + Inches(0.08),
                          col_w - pad_x - Inches(0.12), Inches(0.32))
        _para(tf, title, size=12.5, bold=True, color=accent, first=True)

        _, tf = _textbox(slide, x + pad_x, y + Inches(0.42),
                          col_w - pad_x - Inches(0.12), row_h - Inches(0.5))
        for j, b in enumerate(bullets):
            _para(tf, b, size=9.3, color=INK, bullet=True, first=(j == 0),
                  space_after=4)

    prs.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
