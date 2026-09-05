"""
UBP Bank Agent -- Mock/Demo Backend
Simulates Lloyds Bank workflows (mortgage affordability + subscription
payment history) with fake but *consistent* per-customer data, so the
same customer_id always gets the same numbers across repeated calls.
No real banking data or integration -- purely for testing the
gateway <-> agent <-> AI-assistant pipeline end-to-end.
"""

import hashlib
import random
import re
from datetime import datetime, timedelta
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="UBP Bank Agent (Mock)",
    version="1.0.0",
    description="Mock Lloyds Bank agent -- mortgage affordability & subscription history.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentRequest(BaseModel):
    customer_id: str = Field(..., description="Unique customer identifier")
    workflow_type: Literal["mortgage", "subscription"] = Field(
        ..., description="Either 'mortgage' or 'subscription'"
    )
    query: str = Field(..., description="Original natural language prompt")
    parameters: dict = Field(default_factory=dict, description="Extracted parameters")


# ---------------------------------------------------------------------------
# Deterministic mock-data helpers
# Every value is derived from a hash of customer_id, so the SAME customer_id
# always produces the SAME income/deposit/payment-history on every call --
# it's fake, but it's consistent, which is what makes it usable for testing.
# ---------------------------------------------------------------------------

def _seeded_rng(customer_id: str, salt: str = "") -> random.Random:
    seed_material = f"{customer_id}:{salt}".encode()
    seed = int(hashlib.sha256(seed_material).hexdigest(), 16)
    return random.Random(seed)


def _mock_income(customer_id: str) -> int:
    rng = _seeded_rng(customer_id, "income")
    return rng.randrange(28_000, 95_000, 1_000)


def _mock_deposit_savings(customer_id: str) -> int:
    rng = _seeded_rng(customer_id, "deposit")
    return rng.randrange(8_000, 60_000, 1_000)


def _mock_subscriptions(customer_id: str) -> list[dict]:
    """Generates a consistent list of recurring subscriptions for a customer,
    each with a deterministic 'last payment' status."""
    providers = ["Sky", "Netflix", "Spotify", "Amazon Prime", "Disney+"]
    rng = _seeded_rng(customer_id, "subs")
    subs = []
    for provider in providers:
        amount = rng.choice([6.99, 9.99, 12.99, 24.99, 34.99, 49.99])
        # Deterministically decide if last month's payment went through
        paid_last_month = rng.random() > 0.15  # ~85% chance of "paid"
        last_payment_date = datetime.utcnow().replace(day=1) - timedelta(days=rng.randint(1, 20))
        subs.append(
            {
                "provider": provider,
                "monthly_amount_gbp": amount,
                "last_payment_date": last_payment_date.strftime("%Y-%m-%d"),
                "last_payment_status": "PAID" if paid_last_month else "FAILED",
            }
        )
    return subs


_AMOUNT_PATTERN = re.compile(
    r"£?\s*([\d,]+(?:\.\d+)?)\s*(k|thousand)?", re.IGNORECASE
)


def _extract_requested_amount(query: str, parameters: dict) -> float | None:
    """Pull a requested loan amount from explicit parameters first,
    falling back to a light-touch parse of the free-text query."""
    if "requested_amount" in parameters:
        try:
            return float(parameters["requested_amount"])
        except (TypeError, ValueError):
            pass
    if "amount" in parameters:
        try:
            return float(parameters["amount"])
        except (TypeError, ValueError):
            pass

    for match in _AMOUNT_PATTERN.finditer(query):
        raw, suffix = match.groups()
        if not raw:
            continue
        value = float(raw.replace(",", ""))
        if value == 0:
            continue
        if suffix:
            value *= 1_000
        # Ignore tiny numbers that are probably not a loan amount (e.g. "2 kids")
        if value >= 1_000:
            return value
    return None


# ---------------------------------------------------------------------------
# Workflow handlers
# ---------------------------------------------------------------------------

def handle_mortgage(req: AgentRequest) -> dict:
    income = req.parameters.get("income") or _mock_income(req.customer_id)
    deposit_savings = req.parameters.get("deposit") or _mock_deposit_savings(req.customer_id)
    requested_amount = _extract_requested_amount(req.query, req.parameters)

    income = float(income)
    deposit_savings = float(deposit_savings)

    income_multiple = 4.5
    max_loan = round(income * income_multiple, 2)
    max_property_value = round(max_loan + deposit_savings, 2)

    result = {
        "customer_id": req.customer_id,
        "assumed_annual_income_gbp": income,
        "assumed_available_deposit_gbp": deposit_savings,
        "income_multiple_used": income_multiple,
        "max_loan_amount_gbp": max_loan,
        "max_affordable_property_value_gbp": max_property_value,
    }

    if requested_amount is not None:
        result["requested_amount_gbp"] = requested_amount
        result["required_deposit_estimate_gbp"] = round(max(requested_amount - max_loan, 0), 2)
        result["affordable"] = requested_amount <= max_property_value
        result["verdict"] = (
            f"Based on an assumed income of £{income:,.0f} and available deposit of "
            f"£{deposit_savings:,.0f}, you could likely borrow up to £{max_loan:,.0f}, "
            f"putting your affordable property range up to roughly £{max_property_value:,.0f}. "
            + (
                f"Your requested £{requested_amount:,.0f} looks affordable."
                if result["affordable"]
                else f"Your requested £{requested_amount:,.0f} looks short by about "
                f"£{result['required_deposit_estimate_gbp']:,.0f} versus what a lender would "
                f"likely offer -- consider a larger deposit or lower purchase price."
            )
        )
    else:
        result["verdict"] = (
            f"Based on an assumed income of £{income:,.0f} and available deposit of "
            f"£{deposit_savings:,.0f}, you could likely borrow up to £{max_loan:,.0f}, "
            f"for a total affordable property value up to roughly £{max_property_value:,.0f}."
        )

    return result


def handle_subscription(req: AgentRequest) -> dict:
    subs = _mock_subscriptions(req.customer_id)

    # Try to match a specific provider mentioned in the query/parameters
    target_provider = req.parameters.get("provider") or req.parameters.get("subscription_name")
    if not target_provider:
        query_lower = req.query.lower()
        for sub in subs:
            if sub["provider"].lower() in query_lower:
                target_provider = sub["provider"]
                break

    if target_provider:
        match = next(
            (s for s in subs if s["provider"].lower() == str(target_provider).lower()),
            None,
        )
        if match:
            paid = match["last_payment_status"] == "PAID"
            return {
                "customer_id": req.customer_id,
                "provider": match["provider"],
                "monthly_amount_gbp": match["monthly_amount_gbp"],
                "last_payment_date": match["last_payment_date"],
                "last_payment_status": match["last_payment_status"],
                "verdict": (
                    f"Yes -- your £{match['monthly_amount_gbp']:.2f} {match['provider']} "
                    f"payment on {match['last_payment_date']} went through successfully."
                    if paid
                    else f"No -- your £{match['monthly_amount_gbp']:.2f} {match['provider']} "
                    f"payment scheduled for {match['last_payment_date']} failed."
                ),
            }
        return {
            "customer_id": req.customer_id,
            "provider": target_provider,
            "verdict": f"No subscription found matching '{target_provider}' on this account.",
        }

    # No specific provider identified -- return the full mock subscription summary
    return {
        "customer_id": req.customer_id,
        "subscriptions": subs,
        "verdict": (
            "Here is the current recurring payment status across all tracked subscriptions."
        ),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {"status": "Online", "service": "UBP Bank Agent (Mock)"}


@app.post("/ubp/v1/agent")
async def bank_agent(req: AgentRequest):
    if req.workflow_type == "mortgage":
        agent_response = handle_mortgage(req)
    else:
        agent_response = handle_subscription(req)

    return {
        "status": "SUCCESS",
        "workflow_type": req.workflow_type,
        "agent_response": agent_response,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("bank_agent:app", host="0.0.0.0", port=8000, reload=True)
