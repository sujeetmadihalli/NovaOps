import os
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

PIR_OUTPUT_DIR = "runbooks/pir_reports"


class PIRPDFGenerator:
    def __init__(self, output_dir: str = PIR_OUTPUT_DIR):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate(self, incident_id: str, pir_text: str) -> str:
        """Render PIR markdown to a styled PDF. Returns the saved file path."""
        filepath = os.path.join(self.output_dir, f"PIR_{incident_id}.pdf")
        doc = SimpleDocTemplate(
            filepath,
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        styles = self._build_styles()
        doc.build(self._parse_markdown(pir_text, styles))
        return filepath

    def _build_styles(self) -> dict:
        base = getSampleStyleSheet()
        return {
            "h2": ParagraphStyle(
                "H2", parent=base["Heading1"],
                fontSize=15, textColor=colors.HexColor("#1a1a2e"),
                spaceBefore=10, spaceAfter=5,
            ),
            "h3": ParagraphStyle(
                "H3", parent=base["Heading2"],
                fontSize=11, textColor=colors.HexColor("#0f3460"),
                spaceBefore=8, spaceAfter=3,
            ),
            "body": ParagraphStyle(
                "Body", parent=base["Normal"],
                fontSize=10, spaceAfter=3, leading=14,
            ),
            "bullet": ParagraphStyle(
                "Bullet", parent=base["Normal"],
                fontSize=10, leftIndent=14, spaceAfter=2, leading=14,
            ),
            "meta": ParagraphStyle(
                "Meta", parent=base["Normal"],
                fontSize=10, textColor=colors.HexColor("#333333"), spaceAfter=2,
            ),
            "footer": ParagraphStyle(
                "Footer", parent=base["Normal"],
                fontSize=8, textColor=colors.grey, alignment=TA_CENTER,
            ),
        }

    @staticmethod
    def _bold(text: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    def _parse_markdown(self, text: str, styles: dict) -> list:
        story = []
        for line in text.split("\n"):
            s = line.strip()
            if not s:
                story.append(Spacer(1, 3 * mm))
            elif s.startswith("## "):
                story.append(Paragraph(s[3:].strip(), styles["h2"]))
            elif s.startswith("### "):
                story.append(Paragraph(s[4:].strip(), styles["h3"]))
            elif s == "---":
                story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=4))
            elif s.startswith("- [ ]") or s.startswith("- [x]"):
                checkbox = "\u2610" if "[ ]" in s else "\u2611"
                story.append(Paragraph(f"{checkbox} {self._bold(s[5:].strip())}", styles["bullet"]))
            elif s.startswith("- ") or s.startswith("* "):
                story.append(Paragraph(f"\u2022 {self._bold(s[2:].strip())}", styles["bullet"]))
            elif s.startswith("*") and s.endswith("*") and not s.startswith("**"):
                story.append(Paragraph(f"<i>{s[1:-1]}</i>", styles["footer"]))
            elif re.match(r"^\*\*.+?\*\*", s):
                story.append(Paragraph(self._bold(s), styles["meta"]))
            else:
                story.append(Paragraph(self._bold(s), styles["body"]))
        return story
