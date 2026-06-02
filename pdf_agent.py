"""
PDF AGENT — Format-Aware Product PDF Generator
================================================
Converts a product dict into a clean, professional PDF.
Detects the product format from concept.format and applies a matching layout:

  checklist        → checkbox table rows, alternating shading
  cheat sheet      → two-column grid with bold section headers
  prompt pack      → numbered prompts in monospace boxes
  template         → labelled fields with fill-in lines
  action plan      → numbered steps with coloured step-number badges
  reference guide  → clean sections with headers and bullet points
  <default>        → single-column parsed markdown

Same function signature and output path as before:
    from pdf_agent import generate_pdf
    pdf_path = generate_pdf(product)   # Path or None on failure

Standalone test:
    python3 pdf_agent.py
"""

import json
import os
import re
import traceback
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ─────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR  = BASE_DIR / "outputs" / "pdfs"


# ─────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────

# Neutral foundation — all body pages use WHITE bg with near-black text
WHITE       = colors.white
OFF_WHITE   = colors.HexColor("#FAFAFA")   # barely-off-white for row alt
STRIPE      = colors.HexColor("#F3F4F6")   # alternating row / card bg
RULE_GREY   = colors.HexColor("#D1D5DB")   # rule lines, borders
LIGHT_GREY  = colors.HexColor("#F3F4F6")   # kept for compat — same as STRIPE
MID_GREY    = colors.HexColor("#9CA3AF")   # muted text / borders
BODY_TEXT   = colors.HexColor("#111827")   # near-black — primary text
SUBTEXT     = colors.HexColor("#6B7280")   # secondary/caption text

# Cover page — intentionally dark and bold
MID         = colors.HexColor("#0F172A")   # cover bg (dark slate)
DARK        = colors.HexColor("#1E293B")   # cover footer bar

# Default accent (used when no format detected)
ACCENT      = colors.HexColor("#1A237E")   # deep navy
ACCENT_SOFT = colors.HexColor("#C5CAE9")   # light indigo tint

# Per-format accent colours — all dark enough for WHITE text on bg
# AND dark enough for text-on-white use (WCAG AA ≥ 4.5:1)
FMT_COLORS = {
    "checklist":       colors.HexColor("#276749"),  # deep green   (#276749 on white ≈ 7.2:1)
    "cheat sheet":     colors.HexColor("#1E40AF"),  # deep blue    (#1E40AF on white ≈ 8.5:1)
    "prompt pack":     colors.HexColor("#581C87"),  # deep purple  (#581C87 on white ≈ 9.8:1)
    "template":        colors.HexColor("#92400E"),  # deep amber   (#92400E on white ≈ 6.8:1)
    "action plan":     colors.HexColor("#1A237E"),  # deep navy    (#1A237E on white ≈ 10.1:1)
    "reference guide": colors.HexColor("#00695C"),  # deep teal    (#00695C on white ≈ 6.6:1)
}


# ─────────────────────────────────────────
# FORMAT DETECTION
# ─────────────────────────────────────────

_FORMAT_MAP = {
    "checklist":       "checklist",
    "check list":      "checklist",
    "cheat sheet":     "cheat sheet",
    "cheatsheet":      "cheat sheet",
    "cheat-sheet":     "cheat sheet",
    "prompt pack":     "prompt pack",
    "prompt-pack":     "prompt pack",
    "prompts":         "prompt pack",
    "template":        "template",
    "template pack":   "template",
    "micro-template":  "template",
    "micro-template pack": "template",
    "action plan":     "action plan",
    "action-plan":     "action plan",
    "reference guide": "reference guide",
    "reference":       "reference guide",
    "guide":           "reference guide",
    "swipe file":      "reference guide",
    "one-page reference guide": "reference guide",
    "script template": "template",
}

def detect_format(product: dict) -> str:
    raw = (
        product.get("concept", {}).get("format")
        or product.get("listing", {}).get("format")
        or product.get("format")
        or ""
    ).lower().strip()
    return _FORMAT_MAP.get(raw, "default")


# ─────────────────────────────────────────
# STYLE SHEET
# ─────────────────────────────────────────

def build_styles(fmt_accent=None):
    ac = fmt_accent or ACCENT

    def ps(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        # ── Cover ── (all on dark bg: WHITE or very light text)
        "cover_title": ps("cover_title",
            fontName="Helvetica-Bold", fontSize=32, leading=40,
            textColor=WHITE, alignment=TA_CENTER, spaceAfter=16),
        "cover_tagline": ps("cover_tagline",
            fontName="Helvetica-Oblique", fontSize=16, leading=22,
            textColor=colors.HexColor("#CBD5E1"),  # light slate on dark bg
            alignment=TA_CENTER, spaceAfter=24),
        "cover_price": ps("cover_price",
            fontName="Helvetica-Bold", fontSize=22, leading=28,
            textColor=colors.HexColor("#93C5FD"),  # light blue on dark bg
            alignment=TA_CENTER, spaceAfter=8),
        "cover_brand": ps("cover_brand",
            fontName="Helvetica", fontSize=10, leading=14,
            textColor=colors.HexColor("#94A3B8"),  # slate-400 on dark bg
            alignment=TA_CENTER),
        # ── Body headings — ac on WHITE body bg ──
        "h1": ps("h1",
            fontName="Helvetica-Bold", fontSize=20, leading=26,
            textColor=ac, spaceBefore=20, spaceAfter=8),
        "h2": ps("h2",
            fontName="Helvetica-Bold", fontSize=15, leading=20,
            textColor=ac, spaceBefore=16, spaceAfter=6),
        "h3": ps("h3",
            fontName="Helvetica-Bold", fontSize=12, leading=16,
            textColor=BODY_TEXT, spaceBefore=12, spaceAfter=4),
        # ── Body text ──
        "body": ps("body",
            fontName="Helvetica", fontSize=11, leading=18,
            textColor=BODY_TEXT, spaceBefore=0, spaceAfter=8),
        "body_small": ps("body_small",
            fontName="Helvetica", fontSize=10, leading=15,
            textColor=BODY_TEXT, spaceBefore=0, spaceAfter=6),
        # ── Lists ──
        "bullet": ps("bullet",
            fontName="Helvetica", fontSize=11, leading=17,
            textColor=BODY_TEXT, leftIndent=16, spaceBefore=2, spaceAfter=3),
        "numbered": ps("numbered",
            fontName="Helvetica", fontSize=11, leading=17,
            textColor=BODY_TEXT, leftIndent=24, firstLineIndent=-16,
            spaceBefore=2, spaceAfter=3),
        # ── Checklist ──
        "check_item": ps("check_item",
            fontName="Helvetica", fontSize=11, leading=16,
            textColor=BODY_TEXT, spaceBefore=0, spaceAfter=0),
        "check_mark": ps("check_mark",
            fontName="Helvetica-Bold", fontSize=13, leading=16,
            textColor=ac, alignment=TA_CENTER, spaceBefore=0, spaceAfter=0),
        # ── Cheat sheet ──
        "col_header": ps("col_header",
            fontName="Helvetica-Bold", fontSize=11, leading=15,
            textColor=WHITE, spaceBefore=0, spaceAfter=4),   # WHITE on ac bg
        "col_body": ps("col_body",
            fontName="Helvetica", fontSize=10, leading=15,
            textColor=BODY_TEXT, spaceBefore=0, spaceAfter=3),
        # ── Prompt pack ──
        "prompt_num": ps("prompt_num",
            fontName="Helvetica-Bold", fontSize=13, leading=16,
            textColor=WHITE, alignment=TA_CENTER),             # WHITE on ac bg
        "prompt_text": ps("prompt_text",
            fontName="Courier", fontSize=10, leading=15,
            textColor=BODY_TEXT, spaceBefore=0, spaceAfter=0),
        "prompt_label": ps("prompt_label",
            fontName="Helvetica-Bold", fontSize=9, leading=12,
            textColor=SUBTEXT, spaceAfter=2),
        # ── Template ──
        "field_label": ps("field_label",
            fontName="Helvetica-Bold", fontSize=11, leading=15,
            textColor=BODY_TEXT, spaceBefore=10, spaceAfter=2),
        "field_hint": ps("field_hint",
            fontName="Helvetica-Oblique", fontSize=9, leading=12,
            textColor=SUBTEXT, spaceBefore=0, spaceAfter=2),
        # ── Action plan ──
        "step_num": ps("step_num",
            fontName="Helvetica-Bold", fontSize=14, leading=18,
            textColor=WHITE, alignment=TA_CENTER),             # WHITE on ac bg
        "step_title": ps("step_title",
            fontName="Helvetica-Bold", fontSize=12, leading=16,
            textColor=BODY_TEXT, spaceBefore=0, spaceAfter=3),
        "step_body": ps("step_body",
            fontName="Helvetica", fontSize=10, leading=15,
            textColor=BODY_TEXT, spaceBefore=0, spaceAfter=0),
        # ── Meta / labels ──
        "label": ps("label",
            fontName="Helvetica-Bold", fontSize=9, leading=12,
            textColor=colors.HexColor("#94A3B8"),  # slate-400 on dark cover bg
            spaceAfter=4),
        "meta": ps("meta",
            fontName="Helvetica", fontSize=8, leading=11,
            textColor=SUBTEXT, alignment=TA_CENTER),
        "pull": ps("pull",
            fontName="Helvetica-Oblique", fontSize=13, leading=19,
            textColor=ac, alignment=TA_CENTER),
    }


# ─────────────────────────────────────────
# PAGE TEMPLATES
# ─────────────────────────────────────────

def cover_background(canvas, doc):
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(MID)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, w, h * 0.18, fill=1, stroke=0)
    canvas.setFillColor(ACCENT)
    canvas.rect(0, h - 6 * mm, w, 6 * mm, fill=1, stroke=0)
    canvas.restoreState()


def make_body_page(title: str, fmt_accent=None):
    ac = fmt_accent or ACCENT
    def body_page(canvas, doc):
        w, h = A4
        canvas.saveState()
        canvas.setStrokeColor(ac)
        canvas.setLineWidth(2)
        canvas.line(2 * cm, h - 1.5 * cm, w - 2 * cm, h - 1.5 * cm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(SUBTEXT)
        canvas.drawCentredString(w / 2, 1.2 * cm, f"Page {doc.page}  ·  {title[:60]}")
        canvas.setStrokeColor(LIGHT_GREY)
        canvas.setLineWidth(0.5)
        canvas.line(2 * cm, 1.8 * cm, w - 2 * cm, 1.8 * cm)
        canvas.restoreState()
    return body_page


# ─────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────

def _is_hr(line: str) -> bool:
    """True for markdown horizontal rule lines: ---, ***, ___"""
    return bool(re.match(r'^[-*_]{3,}\s*$', line.strip()))

def _esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def _inline(text):
    """Apply inline bold/italic markdown to an already-escaped string."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _esc(text))
    text = re.sub(r"\*(.+?)\*",     r"<i>\1</i>", text)
    return text

def _split_sections(content):
    """
    Split markdown content into a list of (header_text, [body_lines]) tuples.
    header_text is None for the preamble before any header.
    """
    sections, cur_hdr, cur_lines = [], None, []
    for raw in content.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if re.match(r"^#{1,3} ", line):
            if cur_hdr is not None or cur_lines:
                sections.append((cur_hdr, cur_lines))
            cur_hdr = line.lstrip("#").strip()
            cur_lines = []
        else:
            cur_lines.append(line)
    if cur_hdr is not None or cur_lines:
        sections.append((cur_hdr, cur_lines))
    return sections


# ─────────────────────────────────────────
# FORMAT-SPECIFIC BODY BUILDERS
# ─────────────────────────────────────────

# ── 1. CHECKLIST ──────────────────────────

def build_body_checklist(content, styles, inner_w, ac):
    """
    Checkbox table: each bullet/[ ] line becomes a shaded table row
    with a proper ☐ checkbox on the left.
    """
    flowables = []
    lines = content.replace("\r\n", "\n").split("\n")
    pending_boxes = []  # (text, checked)

    def flush_boxes():
        if not pending_boxes:
            return
        rows = []
        for txt, chk in pending_boxes:
            mark = "&#9745;" if chk else "&#9744;"
            rows.append([
                Paragraph(mark, styles["check_mark"]),
                Paragraph(_inline(txt), styles["check_item"]),
            ])
        col_w = [0.7 * cm, inner_w - 0.7 * cm]
        t = Table(rows, colWidths=col_w, repeatRows=0)
        t.setStyle(TableStyle([
            ("VALIGN",          (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS",  (0, 0), (-1, -1), [WHITE, STRIPE]),
            ("LINEBELOW",       (0, 0), (-1, -2), 0.4, RULE_GREY),
            ("LINEBELOW",       (0, -1), (-1, -1), 1,   ac),
            ("TOPPADDING",      (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING",   (0, 0), (-1, -1), 9),
            ("LEFTPADDING",     (0, 0), (0, -1),  8),
            ("LEFTPADDING",     (1, 0), (1, -1),  6),
            ("RIGHTPADDING",    (1, 0), (1, -1),  8),
            ("BOX",             (0, 0), (-1, -1), 1, RULE_GREY),
        ]))
        flowables.append(t)
        flowables.append(Spacer(1, 0.3 * cm))
        pending_boxes.clear()

    for line in lines:
        s = line.rstrip()
        if not s:
            flush_boxes()
            flowables.append(Spacer(1, 4))
            continue
        if re.match(r"^# ", s) and not s.startswith("##"):
            flush_boxes()
            flowables.append(Paragraph(_esc(s[2:].strip()), styles["h1"]))
            flowables.append(HRFlowable(width="100%", thickness=2,
                                         color=ac, spaceAfter=6))
        elif re.match(r"^## ", s) and not s.startswith("###"):
            flush_boxes()
            flowables.append(Spacer(1, 0.3 * cm))
            flowables.append(Paragraph(_esc(s[3:].strip()), styles["h2"]))
        elif s.startswith("### "):
            flush_boxes()
            flowables.append(Paragraph(_esc(s[4:].strip()), styles["h3"]))
        elif m := re.match(r"^\[([xX ])\]\s+(.*)", s):
            pending_boxes.append((m.group(2), m.group(1).lower() == "x"))
        elif m := re.match(r"^[-*•]\s+(.*)", s):
            pending_boxes.append((m.group(1), False))
        elif m := re.match(r"^\d+[.)]\s+(.*)", s):
            pending_boxes.append((m.group(1), False))
        elif _is_hr(s):
            flush_boxes()
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                         color=RULE_GREY, spaceAfter=6))
        else:
            flush_boxes()
            flowables.append(Paragraph(_inline(s), styles["body"]))

    flush_boxes()
    return flowables


# ── 2. CHEAT SHEET ────────────────────────

def build_body_cheatsheet(content, styles, inner_w, ac):
    """
    Two-column layout. Sections are evenly distributed into left/right columns.
    Each section: coloured header bar + bullet lines below.
    """
    sections = _split_sections(content)

    col_w = (inner_w - 0.4 * cm) / 2  # half width with gutter

    def render_section(hdr, lines):
        """Render a single section as a list of Paragraphs for a table cell."""
        cell = []
        if hdr:
            cell.append(Paragraph(_esc(hdr), styles["col_header"]))
        for line in lines:
            s = line.strip()
            if not s:
                continue
            if m := re.match(r"^[-*•]\s+(.*)", s):
                cell.append(Paragraph(f"\u2022  {_inline(m.group(1))}", styles["col_body"]))
            elif m := re.match(r"^\d+[.)]\s+(.*)", s):
                cell.append(Paragraph(f"<b>{m.group(0)[:2]}</b> {_inline(s[len(m.group(0)):])}", styles["col_body"]))
            elif s.startswith("###"):
                cell.append(Paragraph(f"<b>{_esc(s.lstrip('#').strip())}</b>", styles["col_body"]))
            else:
                cell.append(Paragraph(_inline(s), styles["col_body"]))
        return cell

    # Split sections into left and right halves by total char count
    total_chars = sum(len(h or "") + sum(len(l) for l in ls) for h, ls in sections)
    half = total_chars / 2
    left_secs, right_secs = [], []
    running = 0
    for sec in sections:
        sec_len = len(sec[0] or "") + sum(len(l) for l in sec[1])
        if running < half:
            left_secs.append(sec)
        else:
            right_secs.append(sec)
        running += sec_len

    def secs_to_cell(secs):
        cell = []
        for hdr, lines in secs:
            cell.extend(render_section(hdr, lines))
            cell.append(Spacer(1, 6))
        return cell

    left_cell  = secs_to_cell(left_secs)  or [Paragraph("", styles["col_body"])]
    right_cell = secs_to_cell(right_secs) or [Paragraph("", styles["col_body"])]

    tbl = Table(
        [[left_cell, right_cell]],
        colWidths=[col_w, col_w],
    )
    tbl.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND",   (0, 0), (0, 0),   colors.HexColor("#EAF4FB")),
        ("BACKGROUND",   (1, 0), (1, 0),   colors.HexColor("#F0FAF4")),
        ("BOX",          (0, 0), (0, 0),   1,   colors.HexColor("#AED6F1")),
        ("BOX",          (1, 0), (1, 0),   1,   colors.HexColor("#A9DFBF")),
        ("TOPPADDING",   (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))

    # Section headers need a coloured bar — inject as a header row per section
    # instead, render each section as a separate mini-table pair:
    flowables = [tbl]
    return flowables


def build_body_cheatsheet_sections(content, styles, inner_w, ac):
    """
    Better cheat-sheet: render each section as its own coloured header + content
    block, two per row in a grid table so it looks like a proper cheat sheet.
    """
    sections = [s for s in _split_sections(content) if s[0] or any(l.strip() for l in s[1])]

    col_w = (inner_w - 0.3 * cm) / 2

    def section_cell(hdr, lines, bg, border_color):
        cell = []
        if hdr:
            # Header bar as a nested single-row table
            hdr_tbl = Table(
                [[Paragraph(_esc(hdr), styles["col_header"])]],
                colWidths=[col_w - 0.5 * cm],
            )
            hdr_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), ac),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ]))
            cell.append(hdr_tbl)
            cell.append(Spacer(1, 4))

        for line in lines:
            s = line.strip()
            if not s:
                continue
            if _is_hr(s):
                continue   # skip hr dividers in cheat sheet cells
            if m := re.match(r"^[-*•]\s+(.*)", s):
                cell.append(Paragraph(f"\u2022  {_inline(m.group(1))}", styles["col_body"]))
            elif m := re.match(r"^\d+[.)]\s+(.*)", s):
                cell.append(Paragraph(
                    f"<b>{m.group(1)}.</b>  {_inline(m.group(2) if len(m.groups()) > 1 else s[len(m.group(0)):].strip())}",
                    styles["col_body"]
                ))
            elif re.match(r"^#{1,3} ", s):
                cell.append(Paragraph(f"<b>{_esc(s.lstrip('#').strip())}</b>", styles["col_body"]))
            else:
                cell.append(Paragraph(_inline(s), styles["col_body"]))
        return cell

    bgs     = [STRIPE, WHITE, STRIPE, WHITE]
    borders = [RULE_GREY, RULE_GREY, RULE_GREY, RULE_GREY]

    flowables = []
    # Pair sections into rows of 2
    for i in range(0, len(sections), 2):
        left_hdr, left_lines = sections[i]
        bg_l = bgs[i % len(bgs)]
        bd_l = borders[i % len(borders)]
        left_cell = section_cell(left_hdr, left_lines, bg_l, bd_l)

        if i + 1 < len(sections):
            right_hdr, right_lines = sections[i + 1]
            bg_r = bgs[(i + 1) % len(bgs)]
            bd_r = borders[(i + 1) % len(borders)]
            right_cell = section_cell(right_hdr, right_lines, bg_r, bd_r)
        else:
            right_cell = [Paragraph("", styles["col_body"])]
            bg_r, bd_r = WHITE, WHITE

        row_tbl = Table(
            [[left_cell, right_cell]],
            colWidths=[col_w, col_w],
        )
        row_tbl.setStyle(TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND",   (0, 0), (0, 0),   bg_l),
            ("BACKGROUND",   (1, 0), (1, 0),   bg_r),
            ("BOX",          (0, 0), (-1, -1), 1,   RULE_GREY),
            ("LINEAFTER",    (0, 0), (0, -1),  1,   RULE_GREY),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        flowables.append(row_tbl)
        flowables.append(Spacer(1, 0.25 * cm))

    return flowables


# ── 3. PROMPT PACK ────────────────────────

def build_body_promptpack(content, styles, inner_w, ac):
    """
    Numbered prompts in monospace boxes. Each numbered item or block
    delimited by a blank line is treated as one prompt.
    """
    flowables = []
    lines = content.replace("\r\n", "\n").split("\n")

    prompt_num = 0
    current_prompt_lines = []
    in_prompt = False

    def flush_prompt(lines_buf):
        nonlocal prompt_num
        text = "\n".join(lines_buf).strip()
        if not text:
            return
        prompt_num += 1

        num_cell  = [Paragraph(str(prompt_num), styles["prompt_num"])]
        text_cell = [Paragraph(_esc(text), styles["prompt_text"])]

        badge_size = 0.8 * cm
        t = Table(
            [[num_cell, text_cell]],
            colWidths=[badge_size, inner_w - badge_size],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0),   ac),
            ("BACKGROUND",    (1, 0), (1, 0),   WHITE),
            ("BOX",           (0, 0), (-1, -1), 1, RULE_GREY),
            ("LINEAFTER",     (0, 0), (0, -1),  2, ac),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING",   (0, 0), (0, 0),   6),
            ("LEFTPADDING",   (1, 0), (1, 0),   12),
            ("RIGHTPADDING",  (1, 0), (1, 0),   12),
        ]))
        flowables.append(KeepTogether([t]))
        flowables.append(Spacer(1, 0.3 * cm))

    for line in lines:
        s = line.rstrip()

        # Section headers rendered outside prompt boxes
        if re.match(r"^# ", s) and not s.startswith("##"):
            if current_prompt_lines:
                flush_prompt(current_prompt_lines)
                current_prompt_lines = []
            flowables.append(Paragraph(_esc(s[2:].strip()), styles["h1"]))
            flowables.append(HRFlowable(width="100%", thickness=2,
                                         color=ac, spaceAfter=6))
            continue
        if re.match(r"^## ", s) and not s.startswith("###"):
            if current_prompt_lines:
                flush_prompt(current_prompt_lines)
                current_prompt_lines = []
            flowables.append(Paragraph(_esc(s[3:].strip()), styles["h2"]))
            continue
        if s.startswith("### "):
            if current_prompt_lines:
                flush_prompt(current_prompt_lines)
                current_prompt_lines = []
            flowables.append(Paragraph(_esc(s[4:].strip()), styles["h3"]))
            continue

        # Blank line → flush current prompt
        if not s:
            if current_prompt_lines:
                flush_prompt(current_prompt_lines)
                current_prompt_lines = []
            else:
                flowables.append(Spacer(1, 4))
            continue

        # Horizontal rule → flush + thin divider
        if _is_hr(s):
            if current_prompt_lines:
                flush_prompt(current_prompt_lines)
                current_prompt_lines = []
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                         color=RULE_GREY, spaceAfter=4))
            continue

        # Numbered item → start a new prompt box
        if m := re.match(r"^\d+[.)]\s+(.*)", s):
            if current_prompt_lines:
                flush_prompt(current_prompt_lines)
                current_prompt_lines = []
            current_prompt_lines.append(m.group(1))
        else:
            # Continuation line (bullet sub-point, follow-up text, etc.)
            current_prompt_lines.append(s)

    if current_prompt_lines:
        flush_prompt(current_prompt_lines)

    return flowables


# ── 4. TEMPLATE ───────────────────────────

def build_body_template(content, styles, inner_w, ac):
    """
    Form-style layout. Lines ending with ':' or containing '___' become
    labelled fields with a drawn fill-in line. Other lines render normally.
    """
    flowables = []
    lines = content.replace("\r\n", "\n").split("\n")
    field_count = 0

    def field_row(label, hint=""):
        nonlocal field_count
        field_count += 1
        label_p = Paragraph(f"<b>{_esc(label)}</b>", styles["field_label"])
        hint_p  = (Paragraph(_esc(hint), styles["field_hint"])
                   if hint else Spacer(1, 0))
        rule = Table([["", ""]], colWidths=[inner_w * 0.7, inner_w * 0.3],
                     rowHeights=[20])
        rule.setStyle(TableStyle([
            ("LINEBELOW",     (0, 0), (0, 0),  1.5, ac),
            ("LINEBELOW",     (1, 0), (1, 0),  0.5, RULE_GREY),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return KeepTogether([label_p, hint_p, rule, Spacer(1, 0.15 * cm)])

    for line in lines:
        s = line.rstrip()
        if not s:
            flowables.append(Spacer(1, 4))
            continue
        if _is_hr(s):
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                         color=RULE_GREY, spaceAfter=6))
            continue
        if re.match(r"^# ", s) and not s.startswith("##"):
            flowables.append(Paragraph(_esc(s[2:].strip()), styles["h1"]))
            flowables.append(HRFlowable(width="100%", thickness=2,
                                         color=ac, spaceAfter=6))
            continue
        if re.match(r"^## ", s) and not s.startswith("###"):
            flowables.append(Paragraph(_esc(s[3:].strip()), styles["h2"]))
            continue
        if s.startswith("### "):
            flowables.append(Paragraph(_esc(s[4:].strip()), styles["h3"]))
            continue

        # Field line: ends with ':', contains '___', or looks like label: ___
        if re.search(r"_{3,}", s):
            parts = re.split(r"_{3,}", s, 1)
            label = parts[0].strip().rstrip(":")
            hint  = parts[1].strip() if len(parts) > 1 else ""
            flowables.append(field_row(label, hint))
            continue
        if s.endswith(":") and len(s) < 80 and not s.startswith("-"):
            flowables.append(field_row(s.rstrip(":")))
            continue

        # Bullet / numbered
        if m := re.match(r"^[-*•]\s+(.*)", s):
            flowables.append(Paragraph(f"\u2022  {_inline(m.group(1))}", styles["bullet"]))
            continue
        if m := re.match(r"^\d+[.)]\s+(.*)", s):
            flowables.append(Paragraph(
                f"<b>{m.group(1)}.</b>  {_inline(s[len(m.group(0)):].strip())}",
                styles["numbered"]
            ))
            continue

        flowables.append(Paragraph(_inline(s), styles["body"]))

    return flowables


# ── 5. ACTION PLAN ────────────────────────

def build_body_actionplan(content, styles, inner_w, ac):
    """
    Numbered steps with a coloured badge on the left.
    Section headers are rendered as milestone markers.
    Non-numbered text is rendered as body copy.
    """
    flowables = []
    lines = content.replace("\r\n", "\n").split("\n")
    step_num = 0
    current_step_hdr = None
    current_step_lines = []

    badge_w = 1.1 * cm
    content_w = inner_w - badge_w - 0.2 * cm

    def flush_step(hdr, body_lines):
        nonlocal step_num
        step_num += 1
        body_text = []
        for bl in body_lines:
            bl = bl.strip()
            if not bl:
                continue
            if m2 := re.match(r"^[-*•]\s+(.*)", bl):
                body_text.append(f"\u2022  {_inline(m2.group(1))}")
            else:
                body_text.append(_inline(bl))

        badge_cell = [Paragraph(str(step_num), styles["step_num"])]
        content_cell = []
        if hdr:
            content_cell.append(Paragraph(_esc(hdr), styles["step_title"]))
        for bt in body_text:
            content_cell.append(Paragraph(bt, styles["step_body"]))

        if not content_cell:
            content_cell = [Paragraph("", styles["step_body"])]

        t = Table(
            [[badge_cell, content_cell]],
            colWidths=[badge_w, content_w],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0),   ac),
            ("BACKGROUND",    (1, 0), (1, 0),   WHITE),
            ("BOX",           (0, 0), (-1, -1), 1, RULE_GREY),
            ("LINEAFTER",     (0, 0), (0, -1),  3, ac),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN",         (0, 0), (0, -1),  "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("LEFTPADDING",   (0, 0), (0, 0),   4),
            ("LEFTPADDING",   (1, 0), (1, 0),   14),
            ("RIGHTPADDING",  (1, 0), (1, 0),   10),
        ]))
        flowables.append(KeepTogether([t]))
        flowables.append(Spacer(1, 0.25 * cm))

    def milestone(label):
        """Render a section divider milestone bar."""
        mt = Table(
            [[Paragraph(_esc(label.upper()), ParagraphStyle(
                "milestone",
                fontName="Helvetica-Bold", fontSize=10, leading=13,
                textColor=WHITE,
            ))]],
            colWidths=[inner_w],
        )
        mt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), ac),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ]))
        flowables.append(Spacer(1, 0.3 * cm))
        flowables.append(mt)
        flowables.append(Spacer(1, 0.2 * cm))

    for line in lines:
        s = line.rstrip()

        if re.match(r"^# ", s) and not s.startswith("##"):
            if current_step_hdr is not None or current_step_lines:
                flush_step(current_step_hdr, current_step_lines)
                current_step_hdr, current_step_lines = None, []
            flowables.append(Paragraph(_esc(s[2:].strip()), styles["h1"]))
            flowables.append(HRFlowable(width="100%", thickness=2,
                                         color=ac, spaceAfter=8))
            continue

        if re.match(r"^## ", s) and not s.startswith("###"):
            if current_step_hdr is not None or current_step_lines:
                flush_step(current_step_hdr, current_step_lines)
                current_step_hdr, current_step_lines = None, []
            milestone(s[3:].strip())
            continue

        # ### subheadings: milestone only if we're already inside a steps
        # section (step_num > 0). Before any steps, render as h3 sub-header.
        if s.startswith("### "):
            if current_step_hdr is not None or current_step_lines:
                flush_step(current_step_hdr, current_step_lines)
                current_step_hdr, current_step_lines = None, []
            if step_num > 0:
                milestone(s[4:].strip())
            else:
                flowables.append(Paragraph(_esc(s[4:].strip()), styles["h3"]))
            continue

        if not s:
            if current_step_hdr is not None or current_step_lines:
                flush_step(current_step_hdr, current_step_lines)
                current_step_hdr, current_step_lines = None, []
            else:
                flowables.append(Spacer(1, 4))
            continue

        if _is_hr(s):
            if current_step_hdr is not None or current_step_lines:
                flush_step(current_step_hdr, current_step_lines)
                current_step_hdr, current_step_lines = None, []
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                         color=RULE_GREY, spaceAfter=4))
            continue

        if m := re.match(r"^\d+[.)]\s+(.*)", s):
            if current_step_hdr is not None or current_step_lines:
                flush_step(current_step_hdr, current_step_lines)
                current_step_hdr, current_step_lines = None, []
            current_step_hdr = m.group(1)
            continue

        if current_step_hdr is not None:
            current_step_lines.append(s)
        elif m := re.match(r"^[-*•]\s+(.*)", s):
            # Bullet outside a step (e.g. intro decision list) → render as bullet
            flowables.append(Paragraph(f"\u2022  {_inline(m.group(1))}", styles["bullet"]))
        else:
            flowables.append(Paragraph(_inline(s), styles["body"]))

    if current_step_hdr is not None or current_step_lines:
        flush_step(current_step_hdr, current_step_lines)

    return flowables


# ── 6. REFERENCE GUIDE ────────────────────

def build_body_reference(content, styles, inner_w, ac):
    """
    Clean single-column sections with headers and bullet points.
    Section headers get a left accent bar for visual structure.
    """
    flowables = []
    lines = content.replace("\r\n", "\n").split("\n")

    for line in lines:
        s = line.rstrip()
        if not s:
            flowables.append(Spacer(1, 4))
            continue
        if _is_hr(s):
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                         color=RULE_GREY, spaceAfter=6))
            continue
        if re.match(r"^# ", s) and not s.startswith("##"):
            hdr_tbl = Table(
                [[Paragraph(_esc(s[2:].strip()), styles["h1"])]],
                colWidths=[inner_w],
            )
            hdr_tbl.setStyle(TableStyle([
                ("LINEBEFORE",   (0, 0), (0, -1), 5, ac),
                ("BACKGROUND",   (0, 0), (-1, -1), STRIPE),
                ("LEFTPADDING",  (0, 0), (-1, -1), 12),
                ("TOPPADDING",   (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]))
            flowables.append(hdr_tbl)
            flowables.append(Spacer(1, 0.25 * cm))
            continue

        if re.match(r"^## ", s) and not s.startswith("###"):
            hdr_tbl = Table(
                [[Paragraph(_esc(s[3:].strip()), styles["h2"])]],
                colWidths=[inner_w],
            )
            hdr_tbl.setStyle(TableStyle([
                ("LINEBEFORE",   (0, 0), (0, -1), 3, ac),
                ("LEFTPADDING",  (0, 0), (-1, -1), 10),
                ("TOPPADDING",   (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]))
            flowables.append(hdr_tbl)
            flowables.append(Spacer(1, 0.1 * cm))
            continue

        if s.startswith("### "):
            flowables.append(Paragraph(_esc(s[4:].strip()), styles["h3"]))
            continue

        if m := re.match(r"^\[([xX ])\]\s+(.*)", s):
            mark = "&#9745;" if m.group(1).lower() == "x" else "&#9744;"
            flowables.append(Paragraph(f"{mark}  {_inline(m.group(2))}", styles["bullet"]))
            continue

        if m := re.match(r"^[-*•]\s+(.*)", s):
            flowables.append(Paragraph(f"\u2022  {_inline(m.group(1))}", styles["bullet"]))
            continue

        if m := re.match(r"^\d+[.)]\s+(.*)", s):
            flowables.append(Paragraph(
                f"<b>{m.group(1)}.</b>  {_inline(s[len(m.group(0)):].strip())}",
                styles["numbered"]
            ))
            continue

        flowables.append(Paragraph(_inline(s), styles["body"]))

    return flowables


# ── 7. DEFAULT ────────────────────────────

def build_body_default(content, styles, inner_w, ac):
    """Standard single-column parsed markdown."""
    flowables = []
    lines = content.replace("\r\n", "\n").split("\n")
    for line in lines:
        s = line.rstrip()
        if not s:
            flowables.append(Spacer(1, 4))
            continue
        if _is_hr(s):
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                         color=RULE_GREY, spaceAfter=6))
            continue
        if re.match(r"^# ", s) and not s.startswith("##"):
            flowables.append(Paragraph(_esc(s[2:].strip()), styles["h1"]))
            flowables.append(HRFlowable(width="100%", thickness=1, color=ac, spaceAfter=4))
            continue
        if re.match(r"^## ", s) and not s.startswith("###"):
            flowables.append(Paragraph(_esc(s[3:].strip()), styles["h2"]))
            continue
        if s.startswith("### "):
            flowables.append(Paragraph(_esc(s[4:].strip()), styles["h3"]))
            continue
        if m := re.match(r"^\[([xX ])\]\s+(.*)", s):
            mark = "&#9745;" if m.group(1).lower() == "x" else "&#9744;"
            flowables.append(Paragraph(f"{mark}  {_inline(m.group(2))}", styles["bullet"]))
            continue
        if m := re.match(r"^[-*•]\s+(.*)", s):
            flowables.append(Paragraph(f"\u2022  {_inline(m.group(1))}", styles["bullet"]))
            continue
        if m := re.match(r"^\d+[.)]\s+(.*)", s):
            flowables.append(Paragraph(
                f"<b>{m.group(1)}.</b>  {_inline(s[len(m.group(0)):].strip())}",
                styles["numbered"]
            ))
            continue
        flowables.append(Paragraph(_inline(s), styles["body"]))
    return flowables


# ── Dispatcher ────────────────────────────

def build_body(product, content, styles, inner_w, fmt, ac):
    if fmt == "checklist":
        return build_body_checklist(content, styles, inner_w, ac)
    if fmt == "cheat sheet":
        return build_body_cheatsheet_sections(content, styles, inner_w, ac)
    if fmt == "prompt pack":
        return build_body_promptpack(content, styles, inner_w, ac)
    if fmt == "template":
        return build_body_template(content, styles, inner_w, ac)
    if fmt == "action plan":
        return build_body_actionplan(content, styles, inner_w, ac)
    if fmt == "reference guide":
        return build_body_reference(content, styles, inner_w, ac)
    return build_body_default(content, styles, inner_w, ac)


# ─────────────────────────────────────────
# COVER PAGE
# ─────────────────────────────────────────

def build_cover(product, styles, fmt, ac):
    listing  = product.get("listing", {})
    concept  = product.get("concept", {})
    title    = listing.get("title") or product.get("title", "Untitled Product")
    tagline  = listing.get("tagline") or concept.get("tagline") or product.get("tagline", "")
    fmt_disp = concept.get("format") or listing.get("format") or fmt.title()
    date_str = datetime.now().strftime("%B %Y")

    flows: list = [Spacer(1, 5.5 * cm)]
    flows.append(Paragraph(_esc(fmt_disp.upper()), styles["label"]))
    flows.append(Spacer(1, 0.3 * cm))
    flows.append(Paragraph(_esc(title), styles["cover_title"]))
    flows.append(Spacer(1, 0.4 * cm))

    rule = Table([[""]], colWidths=[8 * cm], rowHeights=[3])
    rule.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 2, ACCENT),
        ("ALIGN",     (0, 0), (-1, -1), "CENTER"),
    ]))
    flows.append(rule)
    flows.append(Spacer(1, 0.6 * cm))

    if tagline:
        flows.append(Paragraph(_esc(tagline), styles["cover_tagline"]))
        flows.append(Spacer(1, 0.6 * cm))

    flows.append(Spacer(1, 3.5 * cm))
    flows.append(Paragraph(f"The Solution Engine  ·  {date_str}", styles["cover_brand"]))
    flows.append(PageBreak())
    return flows


# ─────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────

def generate_pdf(product: dict) -> "Path | None":
    """
    Generate a format-aware PDF for a product dict and return its Path.
    Returns None on failure (error printed, never raised).

    Expected product keys (all optional except id):
        id, title, tagline, price, content, niche, listing, concept
    """
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    product_id = product.get("id", f"unknown_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    out_path   = PDF_DIR / f"{product_id}.pdf"

    listing = product.get("listing", {})
    concept = product.get("concept", {})
    title   = listing.get("title") or product.get("title", "Untitled Product")
    content = product.get("content", "")

    # Fallback content from listing fields
    if not content:
        bullets = listing.get("bulletPoints", [])
        desc    = listing.get("description", "No content available.")
        content = f"# {title}\n\n{desc}\n\n"
        if bullets:
            content += "## What You Get\n\n"
            content += "\n".join(f"- {b}" for b in bullets)

    fmt = detect_format(product)
    ac  = FMT_COLORS.get(fmt, ACCENT)
    styles = build_styles(fmt_accent=ac)

    print(f"  [PDF] Format detected: '{fmt}' — accent: {ac.hexval()}")

    try:
        doc = BaseDocTemplate(
            str(out_path),
            pagesize=A4,
            leftMargin=2.5 * cm, rightMargin=2.5 * cm,
            topMargin=2.5 * cm,  bottomMargin=2.5 * cm,
            title=title, author="The Solution Engine",
        )

        body_page_cb = make_body_page(title, fmt_accent=ac)
        w, h = A4
        inner_w = w - 5 * cm

        cover_frame = Frame(0, 0, w, h,
                            leftPadding=2.5*cm, rightPadding=2.5*cm,
                            topPadding=0, bottomPadding=0, id="cover_frame")
        cover_tpl = PageTemplate(id="Cover", frames=[cover_frame],
                                  onPage=cover_background)

        body_frame = Frame(2.5*cm, 2.5*cm, inner_w, h - 5.5*cm, id="body_frame")
        body_tpl = PageTemplate(id="Body", frames=[body_frame],
                                 onPage=body_page_cb)

        doc.addPageTemplates([cover_tpl, body_tpl])

        story = []

        # Cover
        story.append(NextPageTemplate("Cover"))
        story.extend(build_cover(product, styles, fmt, ac))
        story.append(NextPageTemplate("Body"))

        # Pull-quote
        tagline = listing.get("tagline") or concept.get("tagline") or product.get("tagline", "")
        if tagline:
            pq = Table([[Paragraph(_esc(tagline), styles["pull"])]], colWidths=[inner_w])
            pq.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), STRIPE),
                ("LINEBEFORE",    (0, 0), (0, -1),  4, ac),
                ("TOPPADDING",    (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING",   (0, 0), (-1, -1), 16),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
            ]))
            story.append(pq)
            story.append(Spacer(1, 0.6 * cm))

        # What's Inside summary box
        bullet_pts = listing.get("bulletPoints", [])
        if bullet_pts and fmt not in ("cheat sheet", "prompt pack"):
            bp_rows = [[Paragraph(f"\u2022  {_esc(b)}", ParagraphStyle(
                "bp_row", fontName="Helvetica", fontSize=10, leading=16,
                textColor=BODY_TEXT))] for b in bullet_pts]
            bp_tbl = Table(bp_rows, colWidths=[inner_w])
            bp_tbl.setStyle(TableStyle([
                ("ROWBACKGROUNDS",  (0, 0), (-1, -1), [WHITE, STRIPE]),
                ("TOPPADDING",      (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING",   (0, 0), (-1, -1), 7),
                ("LEFTPADDING",     (0, 0), (-1, -1), 14),
                ("RIGHTPADDING",    (0, 0), (-1, -1), 14),
                ("LINEBELOW",       (0, 0), (-1, -2), 0.3, RULE_GREY),
                ("BOX",             (0, 0), (-1, -1), 1,   RULE_GREY),
            ]))
            story.append(Paragraph("What's Inside", styles["h2"]))
            story.append(Spacer(1, 0.2 * cm))
            story.append(bp_tbl)
            story.append(Spacer(1, 0.6 * cm))

        # Format-specific body
        story.extend(build_body(product, content, styles, inner_w, fmt, ac))

        # Back-matter
        story.append(Spacer(1, 1 * cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT_GREY))
        story.append(Spacer(1, 0.3 * cm))
        meta_parts = []
        if product.get("niche"):
            meta_parts.append(f"Niche: {product['niche']}")
        if fmt != "default":
            meta_parts.append(f"Format: {fmt.title()}")
        meta_parts.append(f"Generated: {datetime.now().strftime('%B %d, %Y')}")
        story.append(Paragraph("  ·  ".join(meta_parts), styles["meta"]))

        doc.build(story)
        size_kb = out_path.stat().st_size // 1024
        print(f"  [PDF] Saved: {out_path} ({size_kb} KB, format={fmt})")
        return out_path

    except Exception as e:
        print(f"  [PDF ERROR] Failed to generate PDF for {product_id}: {e}")
        traceback.print_exc()
        return None


# ─────────────────────────────────────────
# STANDALONE TEST — exercises all 6 formats
# ─────────────────────────────────────────

if __name__ == "__main__":
    products_file = BASE_DIR / "outputs" / "products.json"

    SYNTHETIC = [
        {
            "id": "TEST_CHECKLIST",
            "title": "Morning Routine Checklist",
            "niche": "Adults who can't stick to a morning routine",
            "concept": {"format": "checklist"},
            "listing": {"title": "Morning Routine Checklist",
                        "tagline": "Your perfect morning in 23 actionable steps.",
                        "price": "$3.99",
                        "bulletPoints": ["Wake at same time daily", "No phone for first hour"]},
            "content": (
                "# Morning Routine Checklist\n\n"
                "## Wake-Up Phase\n"
                "- [ ] Alarm off — no snooze\n"
                "- [ ] Drink 500ml water immediately\n"
                "- [ ] Open blinds / get light exposure\n\n"
                "## Body Phase\n"
                "- [ ] 5-minute stretch or walk\n"
                "- [ ] Cold shower (30 sec minimum)\n\n"
                "## Mind Phase\n"
                "- [ ] Journal 3 gratitudes\n"
                "- [ ] Review today's top 3 priorities\n"
                "- [x] No social media until after breakfast\n"
            ),
        },
        {
            "id": "TEST_CHEATSHEET",
            "title": "Python Data Structures Cheat Sheet",
            "niche": "Python beginners",
            "concept": {"format": "cheat sheet"},
            "listing": {"title": "Python Data Structures Cheat Sheet",
                        "tagline": "Every core data structure on one page.",
                        "price": "$4.99"},
            "content": (
                "# Python Data Structures\n\n"
                "## Lists\n"
                "- Ordered, mutable sequence\n"
                "- `list.append(x)` — add to end\n"
                "- `list.pop()` — remove last\n"
                "- `list[i]` — index access\n\n"
                "## Dictionaries\n"
                "- Key-value pairs, unordered\n"
                "- `dict[key] = val` — set\n"
                "- `dict.get(key)` — safe get\n"
                "- `dict.items()` — iterate pairs\n\n"
                "## Sets\n"
                "- Unique values, unordered\n"
                "- `set.add(x)` — add item\n"
                "- `set & other` — intersection\n\n"
                "## Tuples\n"
                "- Ordered, immutable\n"
                "- Use for fixed data\n"
                "- `tuple[i]` — index access\n"
            ),
        },
        {
            "id": "TEST_PROMPTPACK",
            "title": "Job Interview Prompt Pack",
            "niche": "Job seekers preparing for interviews",
            "concept": {"format": "prompt pack"},
            "listing": {"title": "Job Interview Prompt Pack",
                        "tagline": "50 prompts to prepare you for any interview.",
                        "price": "$4.99"},
            "content": (
                "# Job Interview Prompt Pack\n\n"
                "## Behavioural Questions\n\n"
                "1. Tell me about a time you handled a difficult coworker. What did you do and what was the outcome?\n\n"
                "2. Describe a project where you had to learn a completely new skill quickly. How did you approach it?\n\n"
                "3. Give an example of a time you disagreed with your manager. How did you resolve it?\n\n"
                "## Situational Questions\n\n"
                "4. You are given three urgent tasks with the same deadline. How do you decide what to tackle first?\n\n"
                "5. A client is unhappy with your work. Walk me through exactly how you handle that conversation.\n"
            ),
        },
        {
            "id": "TEST_TEMPLATE",
            "title": "Freelancer Rate-Setting Template",
            "niche": "Freelancers who undercharge",
            "concept": {"format": "template"},
            "listing": {"title": "Freelancer Rate-Setting Template",
                        "tagline": "Calculate your real rate in 10 minutes.",
                        "price": "$3.99"},
            "content": (
                "# Freelancer Rate-Setting Worksheet\n\n"
                "## Step 1: Monthly Expenses\n\n"
                "Fixed costs (rent, subscriptions, tools):\n"
                "Variable costs (food, transport, misc):\n"
                "Business costs (software, insurance, tax reserve):\n\n"
                "## Step 2: Target Income\n\n"
                "Desired monthly take-home: _______________\n"
                "Buffer / savings target (20% recommended): _______________\n"
                "Total monthly target: _______________\n\n"
                "## Step 3: Billable Hours\n\n"
                "Working days per month: _______________\n"
                "Billable hours per day (realistic, not optimistic): _______________\n"
                "Total billable hours per month: _______________\n"
            ),
        },
        {
            "id": "TEST_ACTIONPLAN",
            "title": "30-Day Freelance Launch Action Plan",
            "niche": "Side hustle beginners",
            "concept": {"format": "action plan"},
            "listing": {"title": "30-Day Freelance Launch Action Plan",
                        "tagline": "Your first freelance client in 30 days.",
                        "price": "$4.99"},
            "content": (
                "# 30-Day Freelance Launch\n\n"
                "## Week 1: Foundation\n\n"
                "1. Define your one core service — what you will offer and who it's for\n"
                "- Write a one-sentence pitch\n"
                "- List 3 problems you solve\n\n"
                "2. Set your starter rate using the worksheet in Module 2\n"
                "- Do not discount before you have even one client\n\n"
                "## Week 2: Presence\n\n"
                "3. Create or update your LinkedIn profile with your new service\n\n"
                "4. Set up a simple portfolio page (Notion, Carrd, or Google Sites)\n"
                "- 2-3 work samples are enough to start\n\n"
                "## Week 3: Outreach\n\n"
                "5. Send 10 warm outreach messages to people who already know your work\n\n"
                "6. Post one piece of value content explaining your service area\n"
            ),
        },
        {
            "id": "TEST_REFERENCE",
            "title": "Home Office Setup Reference Guide",
            "niche": "Remote workers on a budget",
            "concept": {"format": "reference guide"},
            "listing": {"title": "Home Office Setup Reference Guide",
                        "tagline": "Everything you need. Nothing you don't.",
                        "price": "$3.99"},
            "content": (
                "# Home Office Setup Guide\n\n"
                "## Essential Hardware\n\n"
                "- Monitor: 24\" minimum, IPS panel for colour accuracy\n"
                "- Keyboard: mechanical or membrane — personal preference\n"
                "- Mouse: ergonomic if you type 6+ hours daily\n"
                "- Headset: noise-cancelling mic is non-negotiable for calls\n\n"
                "## Lighting\n\n"
                "- Natural light to your side — not behind the screen\n"
                "- Bias lighting behind monitor reduces eye strain\n"
                "- Ring light or softbox for video calls\n\n"
                "## Ergonomics\n\n"
                "- Chair: lumbar support, adjustable height\n"
                "- Desk height: elbows at 90° when typing\n"
                "- Screen top: at or slightly below eye level\n"
                "- 20-20-20 rule: every 20 min, look 20 ft away for 20 sec\n"
            ),
        },
    ]

    if products_file.exists():
        with open(products_file) as f:
            real_products = json.load(f)
        real_products.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        # Test with the most recent real product too
        SYNTHETIC.insert(0, real_products[0])
        print(f"Also testing with real product: {real_products[0].get('title', 'Untitled')}\n")

    results = []
    for p in SYNTHETIC:
        fmt = detect_format(p)
        print(f"\n{'─'*50}")
        print(f"Product : {p.get('title', 'Untitled')}")
        print(f"Format  : {fmt}")
        path = generate_pdf(p)
        results.append((p["id"], fmt, path))

    print(f"\n{'='*50}")
    print("TEST RESULTS:")
    for pid, fmt, path in results:
        status = "OK" if path else "FAIL"
        print(f"  [{status}] {pid} ({fmt}) -> {path or 'ERROR'}")
