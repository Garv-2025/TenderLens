import re
from pypdf import PdfReader

GSTIN_PATTERN = r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b"
PAN_PATTERN = r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b"
UDYAM_PATTERN = r"\bUDYAM-[A-Z]{2}-\d{2}-\d{7}\b"
DATE_PATTERN = r"\b(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b"

def extract_fields_from_pdf(file_path: str) -> dict:
    """
    Reads text from an uploaded PDF and extracts GSTIN, PAN, Udyam ID, and dates.
    Flags low-text/scanned PDFs as low confidence so they route to Human Review.
    """
    try:
        reader = PdfReader(file_path)
        full_text = ""
        for page in reader.pages:
            full_text += (page.extract_text() or "") + "\n"

        # If a scanned image PDF has almost no selectable text, flag for human review
        if len(full_text.strip()) < 20:
            return {
                "ocr_confidence": 0.45,
                "needs_human_review": True,
                "reason": "Low-confidence scan detected; routed to Requires Review."
            }

        gstin_match = re.search(GSTIN_PATTERN, full_text)
        pan_match = re.search(PAN_PATTERN, full_text)
        udyam_match = re.search(UDYAM_PATTERN, full_text)
        dates_found = re.findall(DATE_PATTERN, full_text)

        return {
            "ocr_confidence": 0.96,
            "needs_human_review": False,
            "extracted": {
                "gstin": gstin_match.group(0) if gstin_match else None,
                "pan": pan_match.group(0) if pan_match else None,
                "udyam_no": udyam_match.group(0) if udyam_match else None,
                "dates": dates_found,
                "page_count": len(reader.pages)
            }
        }
    except Exception as e:
        return {
            "ocr_confidence": 0.0,
            "needs_human_review": True,
            "reason": f"Unreadable PDF structure ({str(e)}); routed to Requires Review."
        }