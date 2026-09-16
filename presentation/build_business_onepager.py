"""Generates presentation/AKS_Migration_Agent_BusinessOnePager.pptx.

A one-slide executive/business-facing companion to build_onepager.py. Where
that deck talks architecture and rule catalogue, this one talks *money and
risk*: savings per app, at-scale extrapolation, categories of errors
prevented, governance, and a bounded ask. Written for CIO / Head of Cloud /
CFO-sponsor audiences.

Content lives here as code (not hand-edited in PowerPoint) so numbers are
easy to refresh. See BUSINESS_ONEPAGER.md for source data, assumptions, and
the spoken 2-minute pitch that goes with this slide.

Regenerate after editing:
    python -m pip install python-pptx
    python presentation/build_business_onepager.py
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Emu, Inches, Pt

OUT = Path(__file__).parent / "AKS_Migration_Agent_BusinessOnePager.pptx"

# Palette lifted verbatim from build_onepager.py so both decks read as a set.
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


def _rect(slide, x, y, w, h, fill, *, line=None, shape=MSO_SHAPE.RECTANGLE):
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

    _rect(slide, 0, 0, prs.slide_width, prs.slide_height, LIGHT_BG)

    # --- Header band -------------------------------------------------------
    header_h = Inches(1.05)
    _rect(slide, 0, 0, prs.slide_width, header_h, NAVY)

    _, tf = _textbox(slide, Inches(0.35), Inches(0.08), Inches(9.2), Inches(0.55))
    _para(tf, "AKS Migration Agent \u2014 Executive Business Case",
          size=26, bold=True, color=WHITE, first=True)

    _, tf = _textbox(slide, Inches(0.37), Inches(0.62), Inches(9.6), Inches(0.4))
    _para(tf, "~9 engineer days saved per app \u00b7 12 blocking defects intercepted per shipped app "
              "\u00b7 reversible pilot \u00b7 human-approved cutover.",
          size=11.5, color=RGBColor(0xC9, 0xD6, 0xEA), first=True)

    badge_w, badge_h = Inches(3.05), Inches(0.55)
    badge = _rect(slide, prs.slide_width - badge_w - Inches(0.35), Inches(0.25),
                  badge_w, badge_h, GOLD, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    badge.adjustments[0] = 0.25
    tf = badge.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    _para(tf, "ASK: 6-WEEK PILOT \u00b7 5\u201310 APPS", size=11.5, bold=True, color=WHITE,
          first=True, align=PP_ALIGN.CENTER)

    # --- Footer KPI strip --------------------------------------------------
    footer_h = Inches(0.62)
    footer_y = prs.slide_height - footer_h
    _rect(slide, 0, footer_y, prs.slide_width, footer_h, NAVY)

    stats = [
        ("~9 days", "engineer time saved per app vs. today's ~10-day manual baseline"),
        ("~90%",    "cycle-time reduction per app; ~2 FTE-years across a ~50-app backlog"),
        ("12 / 14", "BLOCK / HIGH defects caught in an already-deployed human migration"),
        ("~600",    "blocking defects extrapolated to be intercepted across the backlog"),
        ("$0",      "cluster or per-seat cost \u2014 no cluster writes, LLM is swappable/on-prem-capable"),
    ]
    n = len(stats)
    gap = Inches(0.12)
    col_w = Emu(int((prs.slide_width - Inches(0.3) * 2 - gap * (n - 1)) / n))
    x = Inches(0.3)
    for big, small in stats:
        _, tf = _textbox(slide, x, footer_y + Inches(0.04), col_w, footer_h - Inches(0.08),
                          anchor=MSO_ANCHOR.MIDDLE)
        p = _para(tf, big, size=14, bold=True, color=GOLD, first=True, align=PP_ALIGN.CENTER)
        p.space_after = Pt(0)
        _para(tf, small, size=7.5, color=RGBColor(0xD4, 0xDC, 0xEA), align=PP_ALIGN.CENTER)
        x = Emu(int(x + col_w + gap))

    # --- Body: 3x2 card grid ----------------------------------------------
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
        ("THE BUSINESS PROBLEM", RED, [
            "OCP\u2192AKS migrations today are manual, per-app "
            "engineering \u2014 no repeatable scorecard, no audit trail",
            "Even senior-led migrations ship production defects: "
            "committed secrets, root containers, CronJobs silently "
            "missing in 4 of 5 environments",
            "No way today to say on paper \u2018this migrated app is "
            "ready to run in AKS\u2019 \u2014 only \u2018the engineer "
            "thinks it is\u2019",
        ]),
        ("SAVINGS PER APP", GREEN, [
            "Discovery + audit: 3\u20135 days today \u2192 ~1 hour "
            "(auto-generated Migration Workbook)",
            "Manifest & pipeline rewrite: 4\u20137 days today \u2192 "
            "minutes to draft; engineer reviews NEEDS_REVIEW items only",
            "Post-cutover defect firefighting: ~3 days per app avoided "
            "\u2014 defects caught pre-merge as BLOCK / HIGH findings",
            "TOTAL: ~10 engineer days per app \u2192 ~1 engineer day "
            "\u2014 the biggest saving is the incidents that don't happen",
        ]),
        ("AT SCALE (~50-APP BACKLOG)", AZURE, [
            "~450 engineer days saved = ~2 FTE-years redirected from "
            "repetitive audit work to migration-judgement work",
            "~600 blocking defects extrapolated to be intercepted "
            "before cutover, instead of surfacing as production incidents",
            "Onboarding a new app = a YAML change, not new code \u2014 "
            "throughput bounded by review capacity, not by the tool",
            "Same rule catalogue, same scoring, every app \u2014 "
            "consistent audit story across the entire migration programme",
        ]),
        ("ERRORS WE PREVENT (RULE-BACKED)", PURPLE, [
            "Committed prod secrets in values files (M3); root or "
            "world-writable containers (M8)",
            "Env-parity gaps \u2014 resources present in some envs, "
            "silently missing from others (M2)",
            "Missing HPAs on Deployments (M6); missing/misconfigured "
            "TLS on Routes/Ingress (T1)",
            "Residual OCP hostnames (V6); forbidden OpenShift APIs "
            "\u2014 Route, DeploymentConfig, ImageStream, BuildConfig "
            "(T1, T9, T10, T11)",
        ]),
        ("GOVERNANCE & RISK POSTURE", TEAL, [
            "Source mounted read-only \u2014 no cluster writes, no git "
            "pushes; structurally cannot modify your input",
            "Verdict decided by rule severities only; LLM output never "
            "contributes to AUTO_APPROVE / NEEDS_REVIEW / BLOCK",
            "LLM is swappable: Ollama on-prem, Azure OpenAI, OpenAI, "
            "Anthropic \u2014 data residency stays your call",
            "Freeze mode = byte-identical output on repeat runs \u2014 "
            "the audit/compliance story",
        ]),
        ("THE ASK", GOLD, [
            "Sponsor a bounded 6-week pilot on 5\u201310 apps from the "
            "current OCP\u2192AKS backlog",
            "We deliver: migration workbook + draft AKS chart + CI/CD "
            "pipeline + verdict + fidelity score, per app",
            "You provide: read-access to 5\u201310 repos, ~20% of one "
            "engineer's time to validate NEEDS_REVIEW items, a go/no-go "
            "decision at the end",
            "Downside if we stop: zero (nothing pushed, nothing "
            "applied). Downside of doing nothing: keep paying ~9 "
            "engineer days per app and shipping the same defects.",
        ]),
    ]

    for i, (title, accent, bullets) in enumerate(cards):
        row, col = divmod(i, 3)
        x = Emu(int(margin + col * (col_w + col_gap)))
        y = Emu(int(top + row * (row_h + row_gap)))

        card = _rect(slide, x, y, col_w, row_h, CARD_BG, line=BORDER,
                      shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        card.adjustments[0] = 0.045

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
