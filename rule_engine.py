import re
from datetime import datetime
from difflib import SequenceMatcher

# Regex patterns for Indian procurement IDs
GSTIN_REGEX = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
PAN_REGEX = r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$"

def normalize_entity_name(name: str) -> str:
    """
    Slide 5 Rule: Ignore case, punctuation, and Pvt / Private / Ltd / Limited variants.
    """
    if not name:
        return ""
    cleaned = name.upper()
    cleaned = re.sub(r"[^A-Z0-9\s]", " ", cleaned)
    replacements = {
        r"\bPVT\b": "PRIVATE",
        r"\bLTD\b": "LIMITED",
        r"\bCO\b": "COMPANY",
    }
    for pattern, repl in replacements.items():
        cleaned = re.sub(pattern, repl, cleaned)
    return " ".join(cleaned.split())

def normalize_address(addr: str) -> str:
    """Normalizes common Indian address shorthands like Sec-5 vs Sector 5."""
    if not addr:
        return ""
    cleaned = addr.upper()
    cleaned = re.sub(r"\bSEC[\s\-]*(\d+)\b", r"SECTOR \1", cleaned)
    cleaned = re.sub(r"[^A-Z0-9\s]", " ", cleaned)
    return " ".join(cleaned.split())

def extract_pan_from_gstin(gstin: str) -> str:
    """
    Slide 5 Rule: A 10-char PAN sits inside characters 2..12 of a 15-char GSTIN.
    """
    if gstin and len(gstin.strip()) == 15:
        return gstin.strip().upper()[2:12]
    return ""

def compare_names_across_docs(gst_name: str, pan_name: str, udyam_name: str) -> dict:
    """
    Compares normalized legal names across GST, PAN, and Udyam.
    Doubtful matches go to REQUIRES REVIEW, never auto-fail or auto-pass.
    """
    n_gst = normalize_entity_name(gst_name)
    n_pan = normalize_entity_name(pan_name)
    n_udyam = normalize_entity_name(udyam_name)

    if n_gst == n_pan == n_udyam and n_gst != "":
        return {
            "status": "MATCH",
            "compliance": "COMPLIANT",
            "reason": "Normalized legal names match 100% across GST, PAN, and Udyam."
        }

    # Calculate similarity ratio between GST and Udyam
    similarity = SequenceMatcher(None, n_gst, n_udyam).ratio()
    return {
        "status": "REVIEW",
        "compliance": "REQUIRES REVIEW",
        "similarity": round(similarity * 100, 1),
        "reason": f"Name variation detected ('{gst_name}' vs '{udyam_name}', {round(similarity*100)}% similarity). Routed to human review."
    }

def check_validity_date(valid_until_str: str, submission_date_str: str = "2026-04-15") -> dict:
    """
    Slide 6 Rule: Validity date must be on or after tender submission date.
    """
    try:
        valid_until = datetime.strptime(valid_until_str, "%Y-%m-%d")
        submission_date = datetime.strptime(submission_date_str, "%Y-%m-%d")
        if valid_until >= submission_date:
            return {
                "status": "COMPLIANT",
                "reason": f"Valid until {valid_until.strftime('%d %b %Y')} (on or after submission date)."
            }
        else:
            return {
                "status": "NON-COMPLIANT",
                "reason": f"Expired on {valid_until.strftime('%d %b %Y')} (prior to {submission_date.strftime('%d %b %Y')} submission date)."
            }
    except Exception:
        return {
            "status": "REQUIRES REVIEW",
            "reason": "Date format ambiguous or low OCR confidence; requires manual verification."
        }

def calculate_readiness_score(findings: list) -> dict:
    """
    Slide 4 Formula: score = weight of met items / total weight.
    Items needing review are NEVER counted as met.
    """
    total_weight = sum(item.get("weight", 1.0) for item in findings)
    met_weight = sum(item.get("weight", 1.0) for item in findings if item.get("status") == "COMPLIANT")

    counts = {
        "met": sum(1 for item in findings if item.get("status") == "COMPLIANT"),
        "review": sum(1 for item in findings if item.get("status") == "REQUIRES REVIEW"),
        "not_met": sum(1 for item in findings if item.get("status") == "NON-COMPLIANT"),
        "total": len(findings)
    }
    score_pct = round((met_weight / total_weight) * 100) if total_weight > 0 else 0
    return {
        "score_percent": score_pct,
        "met_weight": met_weight,
        "total_weight": total_weight,
        "counts": counts
    }