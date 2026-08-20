"""FlakyLLM — a stand-in for lalfita.common.llm.run_agent.

Production run_agent never raises (offline short-circuit plus a catch-all
that degrades to the fixture), so model failures have to be simulated at the
call site itself. All three LLM-using agents call llm.run_agent through the
module, so one patch reaches pathfinder, clerk and liaison; faults are
targeted by the module name of the build_agent they pass in."""

from collections.abc import Callable
from typing import Any

from lalfita.common import llm as real_llm

from .faults import CrashInjected, FaultPlan


class FlakyLLM:
    def __init__(self, plan: FaultPlan) -> None:
        self._plan = plan
        self._counts: dict[str, int] = {}
        self.calls: list[str] = []
        # Bind the real implementation now, before this object is patched over
        # the module attribute — otherwise the passthrough calls itself.
        self._real = real_llm.run_agent

    async def __call__(
        self,
        build_agent: Callable[[], Any],
        prompt: str,
        *,
        offline_fixture: dict,
        images: list[tuple[bytes, str]] | None = None,
    ) -> dict:
        module = getattr(build_agent, "__module__", "")
        self.calls.append(module)

        for fault in self._plan.llm:
            if fault.agent_module not in module:
                continue
            key = f"{fault.agent_module}:{fault.action}"
            used = self._counts.get(key, 0)
            if used >= fault.times:
                continue
            self._counts[key] = used + 1

            if fault.action == "raise":
                # Models a crash inside the handler at the model call.
                raise CrashInjected(f"injected LLM failure in {module}")
            if fault.action == "malformed":
                return dict(fault.payload)  # e.g. {} or a wrong-shaped dict

        return await self._real(
            build_agent, prompt, offline_fixture=offline_fixture, images=images
        )
