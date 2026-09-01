"""
ai_narrative.py

The AI layer of the IPS Review Assistant. This is the ONLY place in the
project that calls Claude. It never re-derives numbers -- it receives the
already-computed findings from ips_checker.py and turns them into a
professional, client-file-ready review memo. Keeping the LLM out of the
arithmetic is what makes this tool trustworthy enough to actually use:
the math is deterministic Python, the AI's job is explanation and
prioritization, which is what it's actually good at.

Requires an Anthropic API key set as the ANTHROPIC_API_KEY environment
variable. Get one at https://console.anthropic.com/settings/keys
"""

from __future__ import annotations

import os
from typing import Any

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """\
You are an investment operations analyst assistant. You write internal \
review memos that check a client portfolio against their Investment \
Policy Statement (IPS). You are given a list of findings that were \
already computed by a deterministic rules engine -- every number in \
those findings is correct and you must not recompute, guess, or alter \
any figure. Your job is only to:

1. Summarize the overall state of alignment between the portfolio and the IPS.
2. Explain, in plain professional language, why each FLAG matters for this \
   specific client (use their stated risk tolerance, time horizon, and \
   constraints for context -- don't just restate the finding).
3. Prioritize the flags from most to least urgent to address.
4. Suggest a concrete, reasonable next action for each flag (e.g. "trim \
   position by X to bring back within band" -- directionally, not a \
   precise trade recommendation).
5. Keep a neutral, professional tone suitable for an advisor's client file \
   or a compliance review note -- not alarmist, not casual.

Do not invent any holding, percentage, or dollar figure not present in the \
findings you are given. If something is unclear, say so rather than \
guessing.
"""


def _format_ips_context(ips: dict[str, Any]) -> str:
    lines = [
        f"Client: {ips.get('client_name', 'Unnamed client')}",
        f"Stated risk tolerance: {ips.get('risk_tolerance')}",
        f"Time horizon: {ips.get('time_horizon_years')} years",
        f"Liquidity reserve requirement: {ips.get('liquidity_reserve_pct')}%",
        f"Single-position limit: {ips.get('single_position_limit_pct')}%",
    ]
    constraints = ips.get("constraints") or []
    if constraints:
        lines.append("Constraints: " + "; ".join(constraints))
    return "\n".join(lines)


def _format_findings(findings: list[dict[str, Any]]) -> str:
    lines = []
    for f in findings:
        lines.append(f"- [{f['status']}] {f['check']}: {f['detail']}")
    return "\n".join(lines)


def build_user_message(ips: dict[str, Any], check_result: dict[str, Any]) -> str:
    return (
        f"IPS SUMMARY\n{_format_ips_context(ips)}\n\n"
        f"PORTFOLIO TOTAL: ${check_result['total_market_value']:,.0f}\n\n"
        f"COMPUTED FINDINGS ({check_result['flag_count']} flags, "
        f"{check_result['ok_count']} passed)\n{_format_findings(check_result['findings'])}\n\n"
        "Write the review memo described in your instructions."
    )


class NoApiKeyError(RuntimeError):
    pass


def generate_review_memo(ips: dict[str, Any], check_result: dict[str, Any]) -> str:
    """
    Calls the Claude API to turn structured findings into a review memo.
    Raises NoApiKeyError with a helpful message if ANTHROPIC_API_KEY isn't set,
    so the UI layer can show that message instead of crashing.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise NoApiKeyError(
            "No ANTHROPIC_API_KEY environment variable is set, so the AI narrative "
            "step can't run. Get a key at https://console.anthropic.com/settings/keys "
            "and set it (e.g. `export ANTHROPIC_API_KEY=sk-ant-...`) before starting "
            "the app. The rule-based findings above are unaffected -- only the "
            "written memo needs the key."
        )

    import anthropic  # imported lazily so the rest of the app works without the package too

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_message(ips, check_result)}],
    )
    return "".join(block.text for block in message.content if block.type == "text")
