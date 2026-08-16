"""Live-Gemini smoke test: runs each LLM-backed agent once against the real
API and prints what came back. Fails fast if no credentials are configured.

    cd backend && python scripts/smoke_live.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lalfita.agents import clerk, liaison, pathfinder  # noqa: E402
from lalfita.common import config, llm  # noqa: E402
from lalfita.common.fixtures import CLERK_EXTRACTIONS  # noqa: E402

SENTINEL_FIXTURE = {"__fixture__": True}


async def check(name: str, build_agent, prompt: str) -> bool:
    print(f"\n─── {name} " + "─" * (50 - len(name)))
    result = await llm.run_agent(build_agent, prompt, offline_fixture=SENTINEL_FIXTURE)
    if result.get("__fixture__"):
        print("❌ Got the offline fixture back — the live call did not produce parseable JSON.")
        return False
    print(json.dumps(result, indent=2, ensure_ascii=False)[:1500])
    return True


async def main() -> None:
    if config.offline():
        print(
            "❌ No Gemini credentials found.\n"
            "   Set GOOGLE_API_KEY (or GEMINI_API_KEY) in backend/.env or the\n"
            "   environment, or configure Vertex (GOOGLE_GENAI_USE_VERTEXAI=true)."
        )
        raise SystemExit(1)

    print(f"Models: {config.GEMINI_PRO} (pathfinder), {config.GEMINI_FLASH} (clerk/liaison)")

    results = [
        await check(
            "pathfinder",
            pathfinder.build_agent,
            "Goal: Make my home food business legal so I can sell on delivery "
            "platforms\nProfile: home kitchen in Ahmedabad, Gujarati snacks, "
            "annual turnover ₹8 lakh, residential premises, selling via "
            "delivery platforms",
        ),
        await check(
            "clerk",
            clerk.build_agent,
            f"Cross-validate these documents: {CLERK_EXTRACTIONS}",
        ),
        await check(
            "liaison",
            liaison.build_agent,
            "Notice from GST Network re ARN_TEST123: Clarification required "
            "regarding principal place of business (residential premises). "
            "Reply within 7 days or the application will be rejected.",
        ),
    ]

    if all(results):
        print("\n✅ All three agents answered live. LalFita is running on real Gemini.")
    else:
        print("\n⚠️  Some agents fell back to fixtures — check the output above.")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
