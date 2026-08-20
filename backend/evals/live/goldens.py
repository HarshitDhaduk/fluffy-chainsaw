"""Golden expectations for live-model output.

Deliberately loose: they assert the decisions that change what LalFita *does*
(which registrations, whether a document is rejected, whether a deadline is
parsed), not the model's wording."""

from pydantic import BaseModel, Field

MEERA_PROMPT = (
    "Goal: Make my home food business legal so I can sell on delivery platforms\n"
    'Profile: {"applicant_name": "Meera Shah", "city": "Ahmedabad", '
    '"business": "home kitchen making Gujarati snacks", '
    '"annual_turnover_inr": 800000, "premises": "residential", '
    '"channels": ["delivery platforms"]}'
)

FREELANCE_PROMPT = (
    "Goal: Register my freelance design studio\n"
    'Profile: {"applicant_name": "Meera Shah", "city": "Ahmedabad", '
    '"business": "solo graphic design services for clients across India", '
    '"annual_turnover_inr": 1500000, "premises": "residential", '
    '"channels": ["direct clients"]}'
)

NOTICE_TEXT = (
    "Notice from GST Network re ARN_TEST123: Clarification required regarding "
    "principal place of business (residential premises). Reply within 7 days "
    "or the application will be rejected."
)

# Goldens assert only what is legally uncontroversial. GST for a small
# home-kitchen seller is genuinely contested (the e-commerce-operator
# exemption for small intra-state suppliers), and the model legitimately
# varies on it run to run — so it is tracked as advisory, not required. An
# eval that fails a defensible answer teaches people to ignore evals.
MEERA_REQUIRED_KEYWORDS = [["fssai", "food safety"]]
MEERA_ADVISORY_KEYWORDS = [["gst"]]

# A design studio needs no food licence — that one IS clear-cut.
FREELANCE_FORBIDDEN_KEYWORDS = ["fssai", "food safety"]


class NoticeParse(BaseModel):
    """The shape Liaison's downstream code depends on."""

    notice_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    reply_deadline_days: int = Field(ge=1, le=60)
    draft_reply: str = Field(min_length=40)


def determination_keys(result: dict) -> list[str]:
    """Flatten a determination into lowercase text per requirement."""
    out = []
    for req in result.get("requirements", []):
        out.append(
            " ".join(
                str(req.get(field, "")) for field in ("key", "title", "authority", "form")
            ).lower()
        )
    return out


def covers(keys: list[str], keyword_groups: list[list[str]]) -> list[list[str]]:
    """Return the keyword groups no requirement matched."""
    return [
        group
        for group in keyword_groups
        if not any(any(word in key for word in group) for key in keys)
    ]


def wellformed(result: dict) -> list[str]:
    """Structural faults that would break the downstream pipeline."""
    problems = []
    requirements = result.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        return ["no requirements returned"]
    for i, req in enumerate(requirements):
        for field in ("key", "title", "authority", "form", "why"):
            if not str(req.get(field, "")).strip():
                problems.append(f"requirement {i}: empty {field}")
    return problems
