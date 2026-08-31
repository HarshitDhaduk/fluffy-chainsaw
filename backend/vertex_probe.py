"""Quick sanity-check: can this project reach Gemini via Vertex AI?

Run:
    python vertex_probe.py [project] [location] [model]

Defaults to lalfita-hack / asia-south1 / gemini-3.5-flash by reading .env first.
"""
import os, sys
from pathlib import Path

# Load .env so GOOGLE_GENAI_USE_VERTEXAI / GOOGLE_CLOUD_PROJECT are set
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

from google import genai

project  = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GOOGLE_CLOUD_PROJECT", "lalfita-hack")
location = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-south1")
model    = sys.argv[3] if len(sys.argv) > 3 else "gemini-3.5-flash"

print(f"project={project}  location={location}  model={model}")

client = genai.Client(vertexai=True, project=project, location=location)

try:
    resp = client.models.generate_content(
        model=model,
        contents="Reply with the single word: pong",
    )
    print("✓ OK ->", (resp.text or "").strip())
except Exception as exc:
    print("✗ FAIL ->", type(exc).__name__)
    print(str(exc)[:1200])
