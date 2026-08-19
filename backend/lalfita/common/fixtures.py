"""Canned LLM responses for offline mode. These mirror the JSON shapes the
real Gemini prompts are instructed to produce, so swapping offline -> live
changes zero downstream code. Meera's fixture deliberately contains a
PAN vs. utility-bill name mismatch — the demo's first 'wow' moment."""

PATHFINDER_DETERMINATION = {
    "requirements": [
        {
            "key": "fssai_basic",
            "title": "FSSAI Basic Registration",
            "authority": "FoSCoS",
            "form": "Form A",
            "why": (
                "Annual turnover below ₹12 lakh puts you in the Basic Registration "
                "tier — a full State License is not needed yet."
            ),
            "citations": ["https://foscos.fssai.gov.in/"],
        },
        {
            "key": "gst",
            "title": "GST Registration",
            "authority": "GST Network",
            "form": "GST REG-01",
            "why": (
                "Selling through online food delivery platforms generally requires "
                "GST registration regardless of turnover."
            ),
            "citations": ["https://www.gst.gov.in/"],
        },
        {
            "key": "udyam",
            "title": "Udyam (MSME) Registration",
            "authority": "Ministry of MSME",
            "form": "Udyam Registration Form",
            "why": "Optional but recommended: unlocks MSME benefits and credit access.",
            "citations": ["https://udyamregistration.gov.in/"],
        },
    ]
}

# Second journey preset (F9): a freelance services business. Different
# requirement set proves the engine isn't hardcoded to the food journey.
FREELANCE_DETERMINATION = {
    "requirements": [
        {
            "key": "gst",
            "title": "GST Registration",
            "authority": "GST Network",
            "form": "GST REG-01",
            "why": (
                "Registering lets you invoice clients with GST and claim input "
                "credits; required once turnover crosses the services threshold "
                "or for interstate clients."
            ),
            "citations": ["https://www.gst.gov.in/"],
        },
        {
            "key": "udyam",
            "title": "Udyam (MSME) Registration",
            "authority": "Ministry of MSME",
            "form": "Udyam Registration Form",
            "why": "Unlocks MSME benefits, easier credit, and payment protections.",
            "citations": ["https://udyamregistration.gov.in/"],
        },
        {
            "key": "shop_establishment",
            "title": "Shop & Establishment Intimation (Gumastadhara)",
            "authority": "Municipal Corporation",
            "form": "Form G",
            "why": (
                "Businesses operating within municipal limits must register under "
                "the state Shops & Establishments Act; home offices file a simple "
                "intimation."
            ),
            "citations": ["https://labour.gujarat.gov.in/"],
        },
    ]
}

# Keyed by document kind -> extracted fields. Note the name variants.
CLERK_EXTRACTIONS = {
    "pan": {"name": "MEERA R SHAH", "number": "ABCPS1234F"},
    "aadhaar": {"name": "Meera Rajesh Shah", "number": "XXXX-XXXX-7890"},
    "utility_bill": {"name": "MIRA SHAH", "address": "12 Navrangpura, Ahmedabad 380009"},
}

CLERK_VALIDATION = {
    "issues": [
        {
            "document_kind": "utility_bill",
            "field": "name",
            "detail": (
                "Name on electricity bill reads 'MIRA SHAH' but PAN/Aadhaar read "
                "'Meera (R.) Shah'. Authorities routinely reject applications over "
                "this. Fix: upload a corrected bill or a supporting affidavit."
            ),
            "severity": "blocking",
        }
    ]
}

LIAISON_NOTICE_PARSE = {
    "notice_type": "clarification",
    "summary": (
        "GST officer seeks clarification on principal place of business: the "
        "premises is residential. Requested: ownership proof or notarised consent "
        "letter (NOC) from the property owner."
    ),
    "reply_deadline_days": 7,
    "draft_reply": (
        "Respected Sir/Madam, in response to notice ref {ref}: the principal place "
        "of business is the applicant's own residence, used as a home kitchen. "
        "Enclosed: (1) electricity bill as ownership proof, (2) signed declaration "
        "of residential food business operation. Kindly process the application."
    ),
    "attachments": ["utility_bill", "declaration"],
}
