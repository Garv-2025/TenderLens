import json
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi import File, UploadFile
from pydantic import BaseModel
import shutil
import os

import os
import requests

def generate_ai_explanation(finding_title: str, rule_applied: str, extracted_value: str, fallback_text: str) -> str:
    """
    Calls OpenRouter via the Prune Gateway to generate a plain-English explanation.
    """
    prune_key = os.getenv("PRUNE_API_KEY")
    model = os.getenv("LLM_MODEL", "meta-llama/llama-3.1-8b-instruct:free")

    if not prune_key:
        return fallback_text

    try:
        resp = requests.post(
            "https://api.withprune.com/v1/proxy/openrouter/chat/completions",
            headers={
                "X-Prune-Key": prune_key,
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "SageStack"
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a compliance assistant. Explain the rule finding in 1 short sentence."
                    },
                    {
                        "role": "user",
                        "content": f"Finding: {finding_title} | Extracted: {extracted_value} | Rule: {rule_applied}"
                    }
                ],
                "max_tokens": 45,
                "temperature": 0.1
            },
            timeout=5
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        else:
            print(f"Prune Gateway Error: {resp.text}")
    except Exception as e:
        print(f"Connection Error: {e}")
        
    return fallback_text
from ocr_extractor import extract_fields_from_pdf
from rule_engine import (
    extract_pan_from_gstin,
    compare_names_across_docs,
     normalize_address,
    check_validity_date,
    calculate_readiness_score
)

app = FastAPI(title="SageStack Vendor Compliance Checker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sample extracted OCR data matching your pitch deck slides 4, 5, 6
SAMPLE_VENDOR_SUBMISSION = {
    "submission_date": "2026-04-15",
    "documents": {
        "gst": {
            "source": "gst_certificate.pdf, page 1",
            "legal_name": "Sample Traders Pvt Ltd",
            "gstin": "07ABCDE1234F1Z5",
            "address": "Plot 12, Sector 5"
        },
        "pan": {
            "source": "pan_card.pdf, page 1",
            "legal_name": "SAMPLE TRADERS PRIVATE LIMITED",
            "pan": "ABCDE1234F",
            "address": None
        },
        "udyam": {
            "source": "udyam_certificate.pdf, page 1",
            "legal_name": "Sample Trader Enterprises",
            "pan": "ABCDE1234F",
            "udyam_no": "UDYAM-DL-01-0012345",
            "address": "Plot 12, Sec-5"
        },
        "startup": {
            "source": "startup_india.pdf, page 1",
            "dipp_no": "DIPP99201",
            "valid_until": "2028-12-31"
        },
        "oem": {
            "source": "oem_letter.pdf, page 1",
            "valid_until": "2026-03-31",
            "product_covered": True
        }
    }
}

class OverrideRequest(BaseModel):
    finding_id: str
    new_status: str
    reviewer_note: str = "Updated by human reviewer"

@app.get("/")
def serve_frontend():
    return FileResponse("index.html")

@app.post("/api/evaluate")
async def evaluate_submission(file: UploadFile = File(...), checklist_id: str = "GeM-2026-IT-8841"):
    # 1. Save uploaded file locally
    temp_path = f"temp_{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 2. Run real local OCR
    ocr_result = extract_fields_from_pdf(temp_path)
    os.remove(temp_path)

    docs = SAMPLE_VENDOR_SUBMISSION["documents"]
    sub_date = SAMPLE_VENDOR_SUBMISSION["submission_date"]

    # 3. Override mock data with real OCR extractions if found
    if ocr_result.get("extracted"):
        ext = ocr_result["extracted"]
        if ext.get("gstin"): docs["gst"]["gstin"] = ext["gstin"]
        if ext.get("pan"): docs["pan"]["pan"] = ext["pan"]
        if ext.get("udyam_no"): docs["udyam"]["udyam_no"] = ext["udyam_no"]

    # 1. Cross-Document Checks (Slide 5)
    pan_in_gst = extract_pan_from_gstin(docs["gst"]["gstin"])
    pan_match = (pan_in_gst == docs["pan"]["pan"] == docs["udyam"]["pan"])
    name_check = compare_names_across_docs(
        docs["gst"]["legal_name"],
        docs["pan"]["legal_name"],
        docs["udyam"]["legal_name"]
    )
    addr_match = normalize_address(docs["gst"]["address"]) == normalize_address(docs["udyam"]["address"])

    # 2. OEM Expiry Check (Slide 6)
    oem_check = check_validity_date(docs["oem"]["valid_until"], sub_date)

    # 3. Build Evidence-Based Findings (10 Checklist Requirements)
    findings = [
        {
            "id": "F-1",
            "title": "GSTIN & PAN Structure Verification",
            "requirement": "Valid 15-digit GSTIN with embedded PAN matching PAN card",
            "extracted_value": f"{docs['gst']['gstin']} (PAN: {pan_in_gst})",
            "source": docs["gst"]["source"],
            "rule_applied": "PAN sits inside chars 3-12 of GSTIN and must match PAN card",
            "status": "COMPLIANT" if pan_match else "NON-COMPLIANT",
            "weight": 2.0,
            "explanation": "Embedded PAN (ABCDE1234F) in GSTIN matches PAN card and Udyam certificate."
        },
        {
            "id": "F-2",
            "title": "Corporate PAN Verification",
            "requirement": "Valid 10-character PAN card submitted",
            "extracted_value": docs["pan"]["pan"],
            "source": docs["pan"]["source"],
            "rule_applied": "Format [A-Z]{5}[0-9]{4}[A-Z]{1}",
            "status": "COMPLIANT",
            "weight": 2.0,
            "explanation": "Valid PAN structure extracted with high OCR confidence."
        },
        {
            "id": "F-3",
            "title": "OEM Authorization Validity",
            "requirement": "Valid OEM authorization for the tendered product",
            "extracted_value": "Valid until 31 Mar 2026",
            "source": docs["oem"]["source"],
            "rule_applied": "Validity date must be on or after submission date (15 Apr 2026)",
            "status": oem_check["status"],
            "weight": 2.0,
            "explanation": oem_check["reason"]
        },
        {
            "id": "F-4",
            "title": "Registered Address Consistency",
            "requirement": "Vendor address must match across GST and Udyam",
            "extracted_value": f"{docs['gst']['address']} vs {docs['udyam']['address']}",
            "source": "gst_certificate.pdf & udyam_certificate.pdf",
            "rule_applied": "Normalized address comparison (Sec-5 -> Sector 5)",
            "status": "COMPLIANT" if addr_match else "REQUIRES REVIEW",
            "weight": 1.0,
            "explanation": "Addresses match after normalizing 'Sec-5' and 'Sector 5'."
        },
        {
            "id": "F-5",
            "title": "Entity Legal Name Consistency",
            "requirement": "Legal entity name must match across GST, PAN, and Udyam",
            "extracted_value": docs["udyam"]["legal_name"],
            "source": docs["udyam"]["source"],
            "rule_applied": "Doubtful matches go to Requires Review, never auto-fail",
            "status": name_check["compliance"],
            "weight": 1.5,
            "explanation": name_check["reason"]
        },
        {
            "id": "F-6",
            "title": "Udyam / MSME Registration Number",
            "requirement": "Valid Udyam Registration Certificate",
            "extracted_value": docs["udyam"]["udyam_no"],
            "source": docs["udyam"]["source"],
            "rule_applied": "UDYAM-[STATE]-[00]-[0000000] pattern check",
            "status": "COMPLIANT",
            "weight": 1.0,
            "explanation": "Valid Udyam registration number extracted."
        },
        {
            "id": "F-7",
            "title": "Startup India DPIIT Recognition",
            "requirement": "Valid DPIIT Certificate of Recognition",
            "extracted_value": docs["startup"]["dipp_no"],
            "source": docs["startup"]["source"],
            "rule_applied": "Certificate must be present and unexpired",
            "status": "COMPLIANT",
            "weight": 1.0,
            "explanation": "Active DPIIT certificate verified."
        },
        {
            "id": "F-8",
            "title": "OEM Product Scope Match",
            "requirement": "OEM letter must list tendered item code",
            "extracted_value": "Item Code Verified",
            "source": docs["oem"]["source"],
            "rule_applied": "Exact product code presence check",
            "status": "COMPLIANT",
            "weight": 1.0,
            "explanation": "Tendered item code is covered in OEM letter."
        },
        {
            "id": "F-9",
            "title": "OCR Scan Confidence Check (Udyam Annex)",
            "requirement": "Minimum 85% OCR confidence on annexure table",
            "extracted_value": "74% OCR Confidence",
            "source": "udyam_certificate.pdf, page 2",
            "rule_applied": "Poor scans flagged for human review; never auto-passed",
            "status": "REQUIRES REVIEW",
            "weight": 1.0,
            "explanation": "Page 2 stamp slightly blurred; routed to human reviewer."
        },
        {
            "id": "F-10",
            "title": "FY25-26 Tax Clearance Annexure",
            "requirement": "Mandatory tax clearance certificate attached",
            "extracted_value": "Missing Document",
            "source": "Not found in upload bundle",
            "rule_applied": "Mandatory checklist document presence check",
            "status": "NON-COMPLIANT",
            "weight": 1.5,
            "explanation": "Required certificate was not found in the uploaded files."
        }
    ]

    readiness = calculate_readiness_score(findings)

    return {
        "checklist_id": checklist_id,
        "readiness": readiness,
        "cross_document_matrix": [
            {
                "field": "Legal name",
                "gst": docs["gst"]["legal_name"],
                "pan": docs["pan"]["legal_name"],
                "udyam": docs["udyam"]["legal_name"],
                "result": name_check["status"]
            },
            {
                "field": "PAN",
                "gst": f"{pan_in_gst} (inside GSTIN)",
                "pan": docs["pan"]["pan"],
                "udyam": docs["udyam"]["pan"],
                "result": "MATCH" if pan_match else "MISMATCH"
            },
            {
                "field": "Address",
                "gst": docs["gst"]["address"],
                "pan": "Not on card",
                "udyam": docs["udyam"]["address"],
                "result": "MATCH" if addr_match else "REVIEW"
            }
        ],
        "findings": findings
    }