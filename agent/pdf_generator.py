import os
import re
import logging

import boto3
from botocore.exceptions import ClientError
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak

logger = logging.getLogger(__name__)

PIR_OUTPUT_DIR = "runbooks/pir_reports"


class PIRPDFGenerator:
    def __init__(self, endpoint_url: str = None):
        self.endpoint_url = endpoint_url or os.environ.get('S3_ENDPOINT', 'http://localhost:4566')
        self.bucket_name = "novaops-pir-reports"
        self.s3_client = None

    def _get_s3_client(self):
        if not self.s3_client:
            self.s3_client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                region_name='us-east-1',
                aws_access_key_id='test',
                aws_secret_access_key='test'
            )
        return self.s3_client

    def generate(self, incident_id: str, pir_text: str) -> str:
        """Render PIR markdown to a styled PDF and upload to S3. Returns the S3 object key."""
        filename = f"PIR_{incident_id}.pdf"
        tmp_filepath = f"/tmp/{filename}"
        
        doc = SimpleDocTemplate(
            tmp_filepath,
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        styles = self._build_styles()
        story = self._parse_markdown(pir_text, styles)
        doc.build(story)
        
        # Upload to S3
        try:
            client = self._get_s3_client()
            client.upload_file(tmp_filepath, self.bucket_name, filename)
            logger.info(f"PIR PDF uploaded to S3: s3://{self.bucket_name}/{filename}")
            
            # Clean up local tmp file
            if os.path.exists(tmp_filepath):
                os.remove(tmp_filepath)
                
            return filename
        except ClientError as e:
            logger.error(f"Failed to upload PIR to S3: {e}")
            return ""

    def _build_styles(self) -> dict:
        base = getSampleStyleSheet()
        return {
            "title": ParagraphStyle(
                "PIRTitle", parent=base["Heading1"],
                fontSize=16, textColor=colors.HexColor("#1a1a2e"),
                spaceBefore=4, spaceAfter=8, alignment=TA_CENTER,
                wordWrap='CJK',
            ),
            "h2": ParagraphStyle(
                "H2", parent=base["Heading1"],
                fontSize=15, textColor=colors.HexColor("#1a1a2e"),
                spaceBefore=10, spaceAfter=5,
                wordWrap='CJK',
            ),
            "h3": ParagraphStyle(
                "H3", parent=base["Heading2"],
                fontSize=11, textColor=colors.HexColor("#0f3460"),
                spaceBefore=8, spaceAfter=3,
                wordWrap='CJK',
            ),
            "body": ParagraphStyle(
                "Body", parent=base["Normal"],
                fontSize=10, spaceAfter=3, leading=14,
                wordWrap='CJK', alignment=TA_LEFT,
            ),
            "bullet": ParagraphStyle(
                "Bullet", parent=base["Normal"],
                fontSize=10, leftIndent=14, spaceAfter=2, leading=14,
                wordWrap='CJK',
            ),
            "meta": ParagraphStyle(
                "Meta", parent=base["Normal"],
                fontSize=10, textColor=colors.HexColor("#333333"), spaceAfter=2,
                wordWrap='CJK',
            ),
            "footer": ParagraphStyle(
                "Footer", parent=base["Normal"],
                fontSize=8, textColor=colors.grey, alignment=TA_CENTER,
                wordWrap='CJK',
            ),
        }

    @staticmethod
    def _escape_xml(text: str) -> str:
        """Escape XML special characters that break reportlab Paragraph."""
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        return text

    @staticmethod
    def _bold(text: str) -> str:
        """Convert markdown **bold** to reportlab XML tags."""
        # First escape XML, then apply bold
        text = PIRPDFGenerator._escape_xml(text)
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    def _parse_markdown(self, text: str, styles: dict) -> list:
        """Parse markdown PIR text into reportlab flowables with proper wrapping."""
        story = []
        lines = text.split("\n")
        i = 0

        while i < len(lines):
            s = lines[i].strip()

            if not s:
                story.append(Spacer(1, 2 * mm))
            elif s.startswith("## "):
                story.append(Paragraph(self._escape_xml(s[3:].strip()), styles["h2"]))
            elif s.startswith("### "):
                story.append(Paragraph(self._escape_xml(s[4:].strip()), styles["h3"]))
            elif s == "---":
                story.append(Spacer(1, 2 * mm))
                story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=4))
            elif s.startswith("- [ ]") or s.startswith("- [x]"):
                checkbox = "\u2610" if "[ ]" in s else "\u2611"
                story.append(Paragraph(f"{checkbox} {self._bold(s[5:].strip())}", styles["bullet"]))
            elif s.startswith("- ") or s.startswith("* "):
                # Collect consecutive bullet lines into one block
                content = self._bold(s[2:].strip())
                story.append(Paragraph(f"\u2022 {content}", styles["bullet"]))
            elif s.startswith("*") and s.endswith("*") and not s.startswith("**"):
                story.append(Paragraph(f"<i>{self._escape_xml(s[1:-1])}</i>", styles["footer"]))
            elif re.match(r"^\*\*.+?\*\*", s):
                story.append(Paragraph(self._bold(s), styles["meta"]))
            else:
                # Regular body text — accumulate consecutive non-empty lines into one paragraph
                para_lines = [s]
                while i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if not next_line or next_line.startswith("#") or next_line.startswith("-") or \
                       next_line.startswith("*") or next_line == "---":
                        break
                    para_lines.append(next_line)
                    i += 1
                full_text = " ".join(para_lines)
                story.append(Paragraph(self._bold(full_text), styles["body"]))

            i += 1

        return story
