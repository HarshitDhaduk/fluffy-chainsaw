"""Runtime configuration, all environment-driven so the same image serves every service."""

import contextlib
import os
from datetime import timedelta
from pathlib import Path

# Load backend/.env (gitignored) so a locally stored API key just works.
with contextlib.suppress(ImportError):
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    load_dotenv()  # also honor a .env in the current working directory

# Google AI Studio issues keys as GEMINI_API_KEY; ADK/google-genai read
# GOOGLE_API_KEY. Accept either.
if os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


# --- Simulation clock -------------------------------------------------------
# The sandbox government and the Sentinel both express durations in "days".
# SIM_DAY_SECONDS converts one bureaucratic day into wall-clock seconds so a
# three-week journey plays out in minutes (demo) or milliseconds (tests).
SIM_DAY_SECONDS: float = float(os.environ.get("SIM_DAY_SECONDS", "3.0"))


def days(n: float) -> timedelta:
    return timedelta(seconds=n * SIM_DAY_SECONDS)


# --- LLM --------------------------------------------------------------------
# Offline mode returns canned fixture responses so the walking skeleton runs
# end-to-end with no credentials. It is on by default unless Gemini access is
# configured (API key or Vertex AI) or explicitly forced.
def offline() -> bool:
    if _bool("LALFITA_OFFLINE"):
        return True
    has_creds = bool(os.environ.get("GOOGLE_API_KEY")) or _bool("GOOGLE_GENAI_USE_VERTEXAI")
    return not has_creds


GEMINI_FLASH: str = os.environ.get("GEMINI_FLASH_MODEL", "gemini-2.5-flash")
GEMINI_PRO: str = os.environ.get("GEMINI_PRO_MODEL", "gemini-2.5-pro")

# --- Wiring -----------------------------------------------------------------
# "local"  -> in-process event bus + in-memory store + direct sandbox calls
# "cloud"  -> Pub/Sub bus + Firestore store + HTTP sandbox gateway
MODE: str = os.environ.get("LALFITA_MODE", "local")

GCP_PROJECT: str = os.environ.get("GCP_PROJECT", "")
PUBSUB_TOPIC: str = os.environ.get("PUBSUB_TOPIC", "lalfita-events")
SANDBOX_BASE_URL: str = os.environ.get("SANDBOX_BASE_URL", "http://localhost:8081")
AGENTS_WEBHOOK_URL: str = os.environ.get("AGENTS_WEBHOOK_URL", "http://localhost:8080/webhooks/portal")
