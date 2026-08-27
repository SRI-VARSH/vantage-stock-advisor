"""
Agentic recommendation flow.

This replaces the old fixed for-loop over STRATEGY_PROFILES with an actual
agent: when a Gemini key is configured, the LLM decides which tool to call
next (screen stocks / propose a strategy / finish), with what parameters,
and how many strategies make sense for THIS profile and amount — instead of
always producing the same 3 hardcoded presets.

Every number still comes from your existing deterministic functions
(screener.screen_with_relaxation, allocator.decide_equity_allocation,
allocator.build_portfolio, validator.validate_portfolio). The LLM never
computes a number itself — it only chooses which of those to call and with
what scalar parameters. The actual stock objects/existing holdings never
cross the LLM boundary; they stay server-side in _AgentState.

If no GEMINI_API_KEY is configured, or the agent loop fails to produce
anything usable, this falls back to the original fixed-3-strategy pipeline,
so the app never breaks because of the LLM.
"""

import screener
import allocator
import validator
import llm_reasoning
from config import STRATEGY_PROFILES

MODEL = llm_reasoning.MODEL
MAX_AGENT_STEPS = 8


# ---------------------------------------------------------------------------
# Deterministic fallback — this is your ORIGINAL agent.run() logic, unchanged,
# just pulled out into its own function so both code paths can call it.
# ---------------------------------------------------------------------------
def _run_fixed_strategies(profile: dict, amount_available: float, screen_result: dict) -> list:
    strategies = []
    if not screen_result["qualified"]:
        return strategies

    for spec in STRATEGY_PROFILES:
        allocation = allocator.decide_equity_allocation(
            amount_available,
            profile["risk_tier"],
            profile.get("time_horizon_years") or 5,
            profile.get("emergency_fund_months") or 0,
            bool(profile.get("has_high_interest_debt")),
            ceiling_multiplier=spec["ceiling_multiplier"],
        )
        portfolio = allocator.build_portfolio(
            screen_result["qualified"],
            allocation["equity_amount"],
            profile.get("existing_holdings") or {},
            per_stock_cap_pct=spec["per_stock_cap_pct"],
            min_picks=spec["min_picks"],
        )
        strategies.append({
            "id": spec["id"],
            "label": spec["label"],
            "tagline": spec["tagline"],
            "recommended": bool(spec.get("recommended")),
            **allocation,
            **portfolio,
        })
    return strategies


def _screen_with_relaxation(profile, all_stocks):
    return screener.screen_with_relaxation(
        all_stocks, profile["risk_tier"], profile.get("excluded_sectors"),
        target_min_qualified=8,
    )


# ---------------------------------------------------------------------------
# Tool declarations exposed to the LLM. Only scalar args cross the boundary.
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "screen_stocks",
        "description": (
            "Screen the cached stock universe against a risk tier. Returns "
            "counts of qualified/rejected stocks and whether the tier had to "
            "be relaxed to find enough candidates. Call this first, and again "
            "if you want to try a different risk tier."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "risk_tier": {
                    "type": "string",
                    "enum": ["conservative", "moderate", "aggressive"],
                },
                "target_min_qualified": {
                    "type": "integer",
                    "description": "Minimum qualified stocks desired before giving up relaxing further. Default 8.",
                },
            },
            "required": ["risk_tier"],
        },
    },
    {
        "name": "propose_strategy",
        "description": (
            "Compute one complete, concrete strategy: how much of the amount "
            "goes to equity (ceiling_multiplier scales the user's risk-tier "
            "ceiling from config, capped at 100%), and how it's split across "
            "stocks (per_stock_cap_pct = max % of equity in any one stock, "
            "min_picks = minimum number of stocks to spread across). Must be "
            "called after a successful screen_stocks call. The result is "
            "automatically validated against hard safety limits — if "
            "validation fails you'll be told why and can adjust and retry "
            "rather than giving up."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "short id, e.g. 'steady', 'balanced', 'focused'"},
                "label": {"type": "string", "description": "short human label for this strategy"},
                "tagline": {"type": "string", "description": "one-sentence description of the trade-off"},
                "ceiling_multiplier": {"type": "number"},
                "per_stock_cap_pct": {"type": "number"},
                "min_picks": {"type": "integer"},
            },
            "required": ["id", "label", "tagline", "ceiling_multiplier", "per_stock_cap_pct", "min_picks"],
        },
    },
    {
        "name": "finish",
        "description": (
            "Call this once you've proposed all the strategies you want to "
            "show the user (typically 2-4, covering genuinely different "
            "trade-offs) and are done. No further tool calls are processed "
            "after this."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "comparison": {
                    "type": "string",
                    "description": (
                        "Under 120 words, plain-language paragraph comparing "
                        "the proposed strategies for THIS person specifically. "
                        "No markdown/bullets. Present as options, not one "
                        "'right' answer. Never claim certainty about future "
                        "returns."
                    ),
                },
            },
            "required": ["comparison"],
        },
    },
]


class _AgentState:
    """Holds everything the tools need that the LLM must never see or invent
    directly (the actual stock objects, existing holdings, etc)."""

    def __init__(self, profile, amount_available, all_stocks):
        self.profile = profile
        self.amount_available = amount_available
        self.all_stocks = all_stocks
        self.screen_result = None
        self.strategies = []

    def screen_stocks(self, risk_tier, target_min_qualified=8):
        self.screen_result = screener.screen_with_relaxation(
            self.all_stocks, risk_tier, self.profile.get("excluded_sectors"),
            target_min_qualified=target_min_qualified,
        )
        r = self.screen_result
        return {
            "qualified_count": len(r["qualified"]),
            "rejected_count": len(r["rejected"]),
            "tier_used": r["tier_used"],
            "relaxed": r["relaxed"],
        }

    def propose_strategy(self, id, label, tagline, ceiling_multiplier, per_stock_cap_pct, min_picks):
        if not self.screen_result or not self.screen_result["qualified"]:
            return {"error": "Call screen_stocks first and make sure it found qualified stocks."}

        allocation = allocator.decide_equity_allocation(
            self.amount_available,
            self.profile["risk_tier"],
            self.profile.get("time_horizon_years") or 5,
            self.profile.get("emergency_fund_months") or 0,
            bool(self.profile.get("has_high_interest_debt")),
            ceiling_multiplier=ceiling_multiplier,
        )
        portfolio = allocator.build_portfolio(
            self.screen_result["qualified"],
            allocation["equity_amount"],
            self.profile.get("existing_holdings") or {},
            per_stock_cap_pct=per_stock_cap_pct,
            min_picks=min_picks,
        )

        strategy = {
            "id": id, "label": label, "tagline": tagline,
            "recommended": False,
            **allocation, **portfolio,
        }

        if strategy.get("picks"):
            qualified_symbols = {s["symbol"] for s in self.screen_result["qualified"]}
            validation = validator.validate_portfolio(
                strategy["picks"], strategy["equity_amount"], qualified_symbols,
                self.profile.get("excluded_sectors"),
                max_single_stock_pct=strategy.get("per_stock_cap_pct"),
            )
            if not validation["is_valid"]:
                return {
                    "error": "Validation failed: " + "; ".join(validation["violations"]) +
                             ". Adjust parameters (e.g. raise per_stock_cap_pct or lower "
                             "ceiling_multiplier) and try again."
                }

        self.strategies.append(strategy)
        return {
            "accepted": True,
            "equity_amount": strategy.get("equity_amount"),
            "equity_pct_used": strategy.get("equity_pct_used"),
            "num_picks": len(strategy.get("picks", [])),
        }


def _system_prompt(profile, amount_available):
    return (
        "You are the recommendation agent inside a personal equity-advisor "
        f"app. Amount to invest: ₹{amount_available:,.0f}. Profile: risk "
        f"tier={profile.get('risk_tier')}, time horizon="
        f"{profile.get('time_horizon_years')} years, primary goal="
        f"{profile.get('primary_goal') or 'not specified'}, emergency fund "
        f"months={profile.get('emergency_fund_months')}, high-interest debt="
        f"{profile.get('has_high_interest_debt')}, excluded sectors="
        f"{profile.get('excluded_sectors') or 'none'}.\n\n"
        "Reason about what strategies genuinely make sense for THIS person "
        "and amount — you don't have to always produce the same 3 presets. "
        "2-4 clearly different strategies is typical. Always call "
        "screen_stocks first. If propose_strategy returns an error, adjust "
        "the parameters and retry rather than giving up. Never invent "
        "numbers yourself — every number must come from a tool result. "
        "Call finish exactly once when done."
    )


def run(profile: dict, amount_available: float, all_stocks: list) -> dict:
    """Runs the recommendation flow for one user + one amount.

    Returns a dict with `screen`, `strategies`, `comparison`, and
    `comparison_is_llm` — same shape as before, so pipeline.py needs no
    changes.
    """
    client = llm_reasoning._client()

    if not client:
        print("\n⚠️ NO GEMINI CLIENT — USING FIXED PIPELINE")
        # No Gemini key configured — deterministic fallback, original behavior.
        screen_result = _screen_with_relaxation(profile, all_stocks)
        strategies = _run_fixed_strategies(profile, amount_available, screen_result)
        comparison = llm_reasoning.compare_strategies(profile, amount_available, strategies) if strategies else None
        return {
            "screen": screen_result,
            "strategies": strategies,
            "comparison": comparison,
            "comparison_is_llm": False,
        }

    state = _AgentState(profile, amount_available, all_stocks)
    dispatch = {
        "screen_stocks": state.screen_stocks,
        "propose_strategy": state.propose_strategy,
    }

    contents = [{"role": "user", "parts": [{"text": _system_prompt(profile, amount_available)}]}]
    comparison = None
    for step in range(MAX_AGENT_STEPS):

        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config={
                    "tools": [
                        {
                            "function_declarations": TOOLS
                        }
                    ]
                },
            )

            part = resp.candidates[0].content.parts[0]
            call = getattr(part, "function_call", None)

            print("\n" + "=" * 60)
            print(f"🤖 AGENT STEP {step + 1}")
            print("=" * 60)

            if call:
                print(f"🤖 Gemini chose tool: {call.name}")
                print(f"📌 Arguments: {dict(call.args)}")
            else:
                print("🤖 Gemini did NOT choose a tool")

        except Exception as e:
            print(f"❌ Gemini error: {e}")
            call = None

        if not call:
            break

        if call.name == "finish":
            comparison = (call.args or {}).get("comparison")
            print("🏁 Gemini chose FINISH")
            break

        fn = dispatch.get(call.name)

        if fn:
            result = fn(**dict(call.args))
        else:
            result = {
                "error": f"unknown tool {call.name}"
            }

        print(f"🔧 Executed tool: {call.name}")
        print(f"📤 Tool result: {result}")

            # IMPORTANT:
            # Preserve Gemini's original response, including thought_signature
        contents.append(resp.candidates[0].content)

        contents.append({
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "name": call.name,
                        "response": result
                    }
                }
            ]
        })

    # Guarantee the user never sees an empty result because of an LLM
    # hiccup, timeout, or malformed tool call: fall back to the fixed
    # pipeline if the agent produced no usable strategies.
    if not state.strategies:
        screen_result = state.screen_result or _screen_with_relaxation(profile, all_stocks)
        strategies = _run_fixed_strategies(profile, amount_available, screen_result)
        comparison = llm_reasoning.compare_strategies(profile, amount_available, strategies) if strategies else None
        return {
            "screen": screen_result,
            "strategies": strategies,
            "comparison": comparison,
            "comparison_is_llm": bool(comparison) and client is not None,
        }

    if not comparison:
        comparison = llm_reasoning.compare_strategies(profile, amount_available, state.strategies)

    return {
        "screen": state.screen_result,
        "strategies": state.strategies,
        "comparison": comparison,
        "comparison_is_llm": True,
    }