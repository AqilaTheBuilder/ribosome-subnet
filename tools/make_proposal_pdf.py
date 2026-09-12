"""Build the Checkpoint-1 proposal PDF (Report route, Template 07 body palette).

Pipeline:
  1. ReportLab body (TocDocTemplate + multiBuild, clickable TOC)
  2. Template-07 cover HTML -> poster_validate -> cover_validate -> html2poster.js
  3. pypdf merge (cover as page 0, normalized to A4)
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/download/ribosome-network")
SCRIPTS = Path("/home/z/my-project/scripts")
PDF_SKILL = Path("/home/z/my-project/skills/pdf")
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(PDF_SKILL / "scripts"))

from proposal_content import CHAPTERS, DOC_AUTHOR, DOC_SUBJECT, DOC_TITLE  # noqa: E402

# ------------------------------------------------------------------ fonts ----
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import inch  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.pdfmetrics import registerFontFamily  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    CondPageBreak, HRFlowable, Image, KeepTogether, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents  # noqa: E402

FONT_DIR = "/usr/share/fonts"
pdfmetrics.registerFont(TTFont("NotoSerifSC", f"{FONT_DIR}/truetype/noto-serif-sc/NotoSerifSC-Regular.ttf"))
pdfmetrics.registerFont(TTFont("NotoSerifSC-Bold", f"{FONT_DIR}/truetype/noto-serif-sc/NotoSerifSC-Bold.ttf"))
try:  # static file absent on some systems; fall back to the variable font
    pdfmetrics.registerFont(TTFont("Noto Sans SC", f"{FONT_DIR}/truetype/chinese/NotoSansSC-Regular.ttf"))
    pdfmetrics.registerFont(TTFont("Noto Sans SC Bold", f"{FONT_DIR}/truetype/chinese/NotoSansSC-Bold.ttf"))
    registerFontFamily("Noto Sans SC", normal="Noto Sans SC", bold="Noto Sans SC Bold")
except Exception:  # NotoSerifSC covers the CJK fallback chain
    pass
pdfmetrics.registerFont(TTFont("SarasaMonoSC", f"{FONT_DIR}/truetype/chinese/SarasaMonoSC-Regular.ttf"))
pdfmetrics.registerFont(TTFont("FreeSerif", f"{FONT_DIR}/truetype/freefont/FreeSerif.ttf"))
pdfmetrics.registerFont(TTFont("FreeSerif-Bold", f"{FONT_DIR}/truetype/freefont/FreeSerifBold.ttf"))
pdfmetrics.registerFont(TTFont("FreeSerif-Italic", f"{FONT_DIR}/truetype/freefont/FreeSerifItalic.ttf"))
pdfmetrics.registerFont(TTFont("FreeSerif-BoldItalic", f"{FONT_DIR}/truetype/freefont/FreeSerifBoldItalic.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSans", f"{FONT_DIR}/truetype/dejavu/DejaVuSansMono.ttf"))
registerFontFamily("NotoSerifSC", normal="NotoSerifSC", bold="NotoSerifSC-Bold")
registerFontFamily("FreeSerif", normal="FreeSerif", bold="FreeSerif-Bold",
                   italic="FreeSerif-Italic", boldItalic="FreeSerif-BoldItalic")
registerFontFamily("DejaVuSans", normal="DejaVuSans", bold="DejaVuSans")

from pdf import install_font_fallback  # noqa: E402

install_font_fallback()

# ------------------------------------------------- Template 07 body palette ----
PAGE_BG = colors.HexColor("#f5f8fc")       # XL
SECTION_BG = colors.HexColor("#edf2f9")    # XL
CARD_BG = colors.HexColor("#e4ecf5")       # L
TABLE_STRIPE = colors.HexColor("#eef3fa")  # L
HEADER_FILL = colors.HexColor("#1a4a7a")   # M
BORDER = colors.HexColor("#c0d0e2")        # S
ACCENT = colors.HexColor("#2d7ab3")        # XS
TEXT_PRIMARY = colors.HexColor("#142840")
TEXT_MUTED = colors.HexColor("#5a7a96")

MARGIN = 0.95 * inch
PAGE_W, PAGE_H = A4
AVAIL_W = PAGE_W - 2 * MARGIN
AVAIL_H = PAGE_H - 2 * MARGIN
MAX_KEEP = PAGE_H * 0.4

# ------------------------------------------------------------------ styles ----
S = {}
S["body"] = ParagraphStyle("Body", fontName="FreeSerif", fontSize=10.5,
                           leading=17, alignment=TA_JUSTIFY,
                           textColor=TEXT_PRIMARY, spaceAfter=10)
S["h1"] = ParagraphStyle("H1", fontName="FreeSerif-Bold", fontSize=21,
                         leading=27, textColor=HEADER_FILL, spaceBefore=14,
                         spaceAfter=4)
S["h2"] = ParagraphStyle("H2", fontName="FreeSerif-Bold", fontSize=14,
                         leading=19, textColor=TEXT_PRIMARY, spaceBefore=12,
                         spaceAfter=6)
S["bullet"] = ParagraphStyle("Bullet", fontName="FreeSerif", fontSize=10.5,
                             leading=16.5, alignment=TA_LEFT,
                             textColor=TEXT_PRIMARY, leftIndent=16,
                             firstLineIndent=-10, spaceAfter=5)
S["caption"] = ParagraphStyle("Caption", fontName="FreeSerif-Italic",
                              fontSize=8.5, leading=12, alignment=TA_CENTER,
                              textColor=TEXT_MUTED)
S["th"] = ParagraphStyle("TH", fontName="FreeSerif", fontSize=9.5,
                         leading=12.5, alignment=TA_CENTER, textColor=colors.white)
S["td"] = ParagraphStyle("TD", fontName="FreeSerif", fontSize=9.5,
                         leading=12.5, alignment=TA_LEFT,
                         textColor=TEXT_PRIMARY)
S["stat"] = ParagraphStyle("Stat", fontName="FreeSerif-Bold", fontSize=17,
                           leading=20, alignment=TA_CENTER, textColor=ACCENT)
S["statlabel"] = ParagraphStyle("StatLabel", fontName="FreeSerif", fontSize=8,
                                leading=10.5, alignment=TA_CENTER,
                                textColor=TEXT_MUTED)
S["toc_title"] = ParagraphStyle("TocTitle", fontName="FreeSerif-Bold",
                                fontSize=21, leading=27,
                                textColor=HEADER_FILL, spaceAfter=14)
S["toc0"] = ParagraphStyle("TOC0", fontName="FreeSerif", fontSize=11.5,
                           leading=20, leftIndent=6, textColor=TEXT_PRIMARY)


# --------------------------------------------------------------- doc class ----
class TocDocTemplate(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if hasattr(flowable, "bookmark_name"):
            level = getattr(flowable, "bookmark_level", 0)
            text = getattr(flowable, "bookmark_text", "")
            key = getattr(flowable, "bookmark_key", "")
            self.notify("TOCEntry", (level, text, self.page, key))


def on_page(canvas, doc):
    canvas.saveState()
    # Template-07 light-blue page wash
    canvas.setFillColor(PAGE_BG)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # header
    canvas.setFont("FreeSerif", 7.5)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawString(MARGIN, PAGE_H - 0.55 * inch, DOC_TITLE)
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1.2)
    canvas.line(MARGIN, PAGE_H - 0.63 * inch, PAGE_W - MARGIN, PAGE_H - 0.63 * inch)
    # footer
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, 0.62 * inch, PAGE_W - MARGIN, 0.62 * inch)
    canvas.setFont("FreeSerif", 7.5)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawString(MARGIN, 0.45 * inch, DOC_AUTHOR)
    canvas.drawRightString(PAGE_W - MARGIN, 0.45 * inch, str(doc.page))
    canvas.restoreState()


# ------------------------------------------------------------------ helpers ----
def add_heading(text, style, level=0):
    key = "h_%s" % hashlib.md5(text.encode()).hexdigest()[:8]
    p = Paragraph('<a name="%s"/><b>%s</b>' % (key, text), style)
    p.bookmark_name = key
    p.bookmark_level = level
    p.bookmark_text = text
    p.bookmark_key = key
    return p


def safe_keep(elements):
    total = 0
    for el in elements:
        w, h = el.wrap(AVAIL_W, PAGE_H)
        total += h
    if total <= MAX_KEEP:
        return [KeepTogether(elements)]
    if len(elements) >= 2:
        return [KeepTogether(elements[:2])] + list(elements[2:])
    return list(elements)


def embed_image(path, max_width=AVAIL_W, max_height=PAGE_H * 0.32):
    from PIL import Image as PILImage

    img_path = REPO / path
    pil = PILImage.open(img_path)
    ow, oh = pil.size
    ratio = min(max_width / ow, max_height / oh, 1.0 * max_width / ow)
    ratio = min(max_width / ow, max_height / oh)
    return Image(str(img_path), width=ow * ratio, height=oh * ratio)


def build_table(spec):
    ratios = spec["ratios"]
    col_widths = [r * AVAIL_W for r in ratios]
    assert abs(sum(ratios) - 1.0) < 1e-6
    assert sum(col_widths) <= AVAIL_W + 0.5
    data = [[Paragraph(f"<b>{h}</b>", S["th"]) for h in spec["headers"]]]
    for row in spec["rows"]:
        data.append([Paragraph(str(c), S["td"]) for c in row])
    t = Table(data, colWidths=col_widths, hAlign="CENTER", repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i in range(1, len(data)):
        style.append(("BACKGROUND", (0, i), (-1, i),
                      TABLE_STRIPE if i % 2 == 1 else colors.white))
    t.setStyle(TableStyle(style))
    return t


def build_callouts(items):
    n = len(items)
    gap = 12
    box_w = (AVAIL_W - gap * (n - 1)) / n
    cells, widths = [], []
    for i, (value, label) in enumerate(items):
        inner = Table(
            [[Paragraph(f"<b>{value}</b>", S["stat"])],
             [Paragraph(label, S["statlabel"])]],
            colWidths=[box_w],
        )
        inner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
            ("BOX", (0, 0), (-1, -1), 0.8, ACCENT),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
            ("TOPPADDING", (0, 1), (-1, 1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        cells.append(inner)
        widths.append(box_w)
        if i < n - 1:
            cells.append(Spacer(gap, 1))
            widths.append(gap)
    row = Table([cells], colWidths=widths, hAlign="CENTER")
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return row


def build_figure_pair(spec):
    """Two figures side by side, each with its own caption underneath."""
    col_w = (AVAIL_W - 18) / 2
    img_w = col_w - 4
    cells = []
    for side in ("left", "right"):
        payload = spec[side]
        img = embed_image(payload["path"], max_width=img_w, max_height=150)
        cap = Paragraph(payload["caption"], S["caption"])
        cells.append([img, Spacer(1, 4), cap])
    row = Table([[cells[0], "", cells[1]]], colWidths=[col_w, 18, col_w],
                hAlign="CENTER")
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return row


# -------------------------------------------------------------------- story ----
def build_story():
    story = []
    toc = TableOfContents()
    toc.levelStyles = [S["toc0"]]
    story.append(Paragraph("<b>Table of Contents</b>", S["toc_title"]))
    story.append(HRFlowable(width="100%", color=ACCENT, thickness=1.2,
                            spaceBefore=0, spaceAfter=12))
    story.append(toc)
    story.append(PageBreak())

    chapter_no = 0
    for chapter in CHAPTERS:
        title = chapter["title"]
        if chapter.get("numbered", True):
            chapter_no += 1
            display = f"{chapter_no}.  {title}"
        else:
            display = title
        story.append(CondPageBreak(AVAIL_H * 0.25))
        heading = add_heading(display, S["h1"], level=0)
        rule = HRFlowable(width="100%", color=ACCENT, thickness=1.2,
                          spaceBefore=0, spaceAfter=10)
        first_blocks = [heading, rule]
        blocks = chapter["blocks"]
        # bind heading + first paragraph
        if blocks and blocks[0][0] == "body":
            first_blocks.append(Paragraph(blocks[0][1], S["body"]))
            blocks = blocks[1:]
        story.extend(safe_keep(first_blocks))

        for kind, payload in blocks:
            if kind == "body":
                story.append(Paragraph(payload, S["body"]))
            elif kind == "h2":
                story.extend(safe_keep([
                    Paragraph(f"<b>{payload}</b>", S["h2"]),
                    Spacer(1, 2),
                ]))
            elif kind == "bullet":
                for item in payload:
                    story.append(Paragraph(f"• {item}", S["bullet"]))
                story.append(Spacer(1, 6))
            elif kind == "callouts":
                story.append(Spacer(1, 6))
                story.append(build_callouts(payload))
                story.append(Spacer(1, 12))
            elif kind == "table":
                story.append(Spacer(1, 8))
                t = build_table(payload)
                cap = Paragraph(payload["caption"], S["caption"])
                if len(payload["rows"]) <= 8:
                    story.extend(safe_keep([t, Spacer(1, 6), cap]))
                else:
                    story.append(t)
                    story.append(Spacer(1, 6))
                    story.append(cap)
                story.append(Spacer(1, 14))
            elif kind == "figure":
                story.append(Spacer(1, 10))
                img = embed_image(payload["path"],
                                  max_height=payload.get("max_h", 220))
                cap = Paragraph(payload["caption"], S["caption"])
                story.extend(safe_keep([img, Spacer(1, 5), cap]))
                story.append(Spacer(1, 12))
            elif kind == "figure_pair":
                story.append(Spacer(1, 10))
                pair = build_figure_pair(payload)
                story.extend(safe_keep([pair]))
                story.append(Spacer(1, 12))
            elif kind == "quote":
                q = ParagraphStyle("Q", parent=S["body"], fontName="FreeSerif-Italic",
                                   leftIndent=24, textColor=TEXT_MUTED)
                story.append(Paragraph(payload, q))
    return story


# --------------------------------------------------------------------- main ----
def main() -> None:
    body_path = SCRIPTS / "proposal_body.pdf"
    doc = TocDocTemplate(
        str(body_path), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=DOC_TITLE, author="Z.ai", creator="Z.ai", subject=DOC_SUBJECT,
    )
    doc.multiBuild(build_story(), onFirstPage=on_page, onLaterPages=on_page)
    print(f"body: {body_path} ({os.path.getsize(body_path)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
