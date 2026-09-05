"""
UBP Bank Agent -- Mortgage Journey with HITL Requirements + Negotiation
=========================================================================
Simulates a real mortgage journey between a Customer Agent (maximizing
customer profit) and this Bank Agent (maximizing bank profit):

  1. Customer Agent asks:  "what do you already know, and what's missing?"
     -> GET/POST /ubp/v1/agent/mortgage/requirements
  2. Customer Agent (after HITL, asking the human for missing fields)
     submits a proposal and negotiates round-by-round:
     -> POST /ubp/v1/agent/mortgage/negotiate

  Pricing is deterministic and risk-based. The bank ANCHORS high (its
  opening rate has margin baked in) and has a FLOOR it will not go below
  (protects minimum profitability). Each negotiation round concedes
  gradually toward the floor, never straight to it -- exactly like a
  real underwriter would behave.

  30 customer data points total: ~20 the bank already has on file
  (existing account holder data), ~10 the customer must supply fresh
  for this specific mortgage application.
"""

import hashlib
import random
from datetime import date
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="UBP Bank Agent (Mock) -- Mortgage Negotiation Edition",
    version="2.0.0",
    description="Mock Lloyds Bank agent: requirements-gap check + round-based mortgage negotiation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# 1. CUSTOMER DATA MODEL -- 30 data points total
# ============================================================================
# KNOWN_TO_BANK: fields the bank already has because the person is an
# existing account holder (KYC, income analysis from salary deposits,
# credit bureau pull, internal debt records, etc.)
# CUSTOMER_SUPPLIED: fields specific to THIS mortgage application that
# the bank cannot know until the customer (or their agent) provides them.

class KnownToBank(BaseModel):
    customer_id: str
    full_name: str
    date_of_birth: str
    employment_status: Literal["employed", "self_employed", "contract", "unemployed"]
    employer_name: Optional[str] = None
    job_title: Optional[str] = None
    years_in_current_job: float
    annual_gross_income: float
    annual_net_income: float
    monthly_outgoings_total: float
    existing_debts_with_bank: float          # total balance of loans/cards held at this bank
    existing_debts_with_bank_monthly_payment: float
    credit_score: int                         # 300-850 mock scale
    credit_history_missed_payments_count: int
    current_savings_balance: float
    current_account_avg_balance_6m: float
    residency_status: Literal["uk_citizen", "settled_status", "visa_holder"]
    existing_mortgage_customer: bool
    years_as_bank_customer: float
    marital_status: Literal["single", "married", "civil_partnership", "divorced"]
    current_address_years: float


class CustomerSupplied(BaseModel):
    other_income_sources: Optional[float] = Field(
        None, description="Annual income NOT visible to the bank (freelance, rental, bonus, etc.)"
    )
    other_outstanding_debts_elsewhere: Optional[float] = Field(
        None, description="Total balance of loans/cards held at OTHER lenders"
    )
    deposit_available: Optional[float] = None
    deposit_source: Optional[Literal["savings", "gift", "inheritance", "property_sale"]] = None
    number_of_dependents: Optional[int] = None
    is_first_time_buyer: Optional[bool] = None
    property_location: Optional[str] = None
    property_type: Optional[Literal["flat", "terraced", "semi_detached", "detached", "new_build"]] = None
    requested_loan_amount: Optional[float] = None
    requested_mortgage_term_years: Optional[int] = None


# Metadata for the requirements-gap check -- which CustomerSupplied fields are
# BLOCKING (can't price a mortgage without them) vs OPTIONAL (refine pricing
# but negotiation can proceed on reasonable defaults if omitted).
FIELD_METADATA: dict[str, dict] = {
    "requested_loan_amount": {
        "required": True,
        "question": "How much do you need to borrow?",
    },
    "property_location": {
        "required": True,
        "question": "Where is the property located (city/postcode)?",
    },
    "deposit_available": {
        "required": True,
        "question": "How much deposit do you have available?",
    },
    "requested_mortgage_term_years": {
        "required": True,
        "question": "Over how many years would you like the mortgage term (e.g. 25, 30)?",
    },
    "is_first_time_buyer": {
        "required": True,
        "question": "Are you a first-time buyer?",
    },
    "property_type": {
        "required": False,
        "question": "What type of property is it (flat, terraced, semi-detached, detached, new build)?",
    },
    "deposit_source": {
        "required": False,
        "question": "What is the source of your deposit (savings, gift, inheritance, property sale)?",
    },
    "number_of_dependents": {
        "required": False,
        "question": "How many dependents do you have?",
    },
    "other_income_sources": {
        "required": False,
        "question": "Do you have any other annual income not held with this bank (freelance, rental, bonus)?",
    },
    "other_outstanding_debts_elsewhere": {
        "required": False,
        "question": "Do you have any outstanding loans or credit card debt with OTHER lenders?",
    },
}


# ============================================================================
# 2. MOCK CUSTOMER DB -- deterministic per customer_id, existing-account data
# ============================================================================

def _seeded_rng(customer_id: str, salt: str = "") -> random.Random:
    seed = int(hashlib.sha256(f"{customer_id}:{salt}".encode()).hexdigest(), 16)
    return random.Random(seed)


def _generate_known_profile(customer_id: str) -> KnownToBank:
    rng = _seeded_rng(customer_id, "known")
    gross_income = rng.randrange(28_000, 95_000, 1_000)
    net_income = round(gross_income * rng.uniform(0.68, 0.78), 2)
    employment = rng.choice(["employed", "employed", "employed", "self_employed", "contract"])
    return KnownToBank(
        customer_id=customer_id,
        full_name=f"Customer {customer_id.upper()}",
        date_of_birth=str(date(rng.randint(1965, 2000), rng.randint(1, 12), rng.randint(1, 28))),
        employment_status=employment,
        employer_name=rng.choice(["Acme Corp", "Globex Ltd", "Initech", "Self-Employed"] if employment != "self_employed" else ["Self-Employed"]),
        job_title=rng.choice(["Analyst", "Engineer", "Manager", "Consultant", "Designer"]),
        years_in_current_job=round(rng.uniform(0.5, 12), 1),
        annual_gross_income=gross_income,
        annual_net_income=net_income,
        monthly_outgoings_total=round(net_income / 12 * rng.uniform(0.35, 0.6), 2),
        existing_debts_with_bank=round(rng.choice([0, 0, 1500, 4000, 8000, 15000]), 2),
        existing_debts_with_bank_monthly_payment=round(rng.choice([0, 0, 60, 150, 300]), 2),
        credit_score=rng.randrange(560, 830, 5),
        credit_history_missed_payments_count=rng.choice([0, 0, 0, 1, 2]),
        current_savings_balance=rng.randrange(2_000, 40_000, 1_000),
        current_account_avg_balance_6m=rng.randrange(500, 8_000, 250),
        residency_status=rng.choice(["uk_citizen", "uk_citizen", "settled_status", "visa_holder"]),
        existing_mortgage_customer=rng.random() > 0.7,
        years_as_bank_customer=round(rng.uniform(0.5, 20), 1),
        marital_status=rng.choice(["single", "married", "married", "civil_partnership", "divorced"]),
        current_address_years=round(rng.uniform(0.5, 10), 1),
    )


# In-memory store: customer_id -> {"known": KnownToBank, "supplied": dict}
_CUSTOMER_DB: dict[str, dict] = {}


def _get_or_create_customer(customer_id: str) -> dict:
    if customer_id not in _CUSTOMER_DB:
        _CUSTOMER_DB[customer_id] = {
            "known": _generate_known_profile(customer_id),
            "supplied": {},
        }
    return _CUSTOMER_DB[customer_id]


# ============================================================================
# 3. REQUEST / RESPONSE MODELS
# ============================================================================

class RequirementsRequest(BaseModel):
    customer_id: str
    supplied_so_far: dict = Field(
        default_factory=dict,
        description="Any CustomerSupplied fields the customer agent has already collected",
    )


class RequirementsResponse(BaseModel):
    customer_id: str
    known_to_bank: dict
    still_missing_required: list[dict]
    still_missing_optional: list[dict]
    ready_to_negotiate: bool


class NegotiationProposal(BaseModel):
    customer_id: str
    supplied_data: dict = Field(
        default_factory=dict, description="All CustomerSupplied fields collected so far"
    )
    desired_interest_rate: Optional[float] = Field(
        None, description="Customer agent's asking rate (%) for this round. Omit for round 1 to get the bank's opening offer."
    )
    round: int = Field(1, ge=1, description="Negotiation round number, starting at 1")


class NegotiationResponse(BaseModel):
    customer_id: str
    round: int
    negotiation_status: Literal["opening_offer", "counter", "accept", "reject", "final_offer"]
    bank_offered_rate: Optional[float] = None
    loan_amount: Optional[float] = None
    ltv_percent: Optional[float] = None
    term_years: Optional[int] = None
    monthly_repayment_estimate: Optional[float] = None
    rationale: str
    can_continue_negotiating: bool


# ============================================================================
# 4. PRICING ENGINE (bank's internal risk model -- not exposed to customer)
# ============================================================================

def _compute_fair_rate(known: KnownToBank, supplied: dict, ltv_percent: float) -> float:
    rate = 4.20  # base rate

    if ltv_percent > 90:
        rate += 999  # signal: infeasible, handled by caller
    elif ltv_percent > 85:
        rate += 0.55
    elif ltv_percent > 80:
        rate += 0.35
    elif ltv_percent > 75:
        rate += 0.20
    elif ltv_percent > 60:
        rate += 0.05

    cs = known.credit_score
    if cs < 580:
        rate += 0.90
    elif cs < 650:
        rate += 0.50
    elif cs < 720:
        rate += 0.20
    elif cs < 780:
        rate += 0.05
    else:
        rate -= 0.10

    if known.employment_status == "self_employed":
        rate += 0.25
    elif known.employment_status == "contract":
        rate += 0.15

    monthly_debt = (
        known.existing_debts_with_bank_monthly_payment
        + (supplied.get("other_outstanding_debts_elsewhere") or 0) / 24
    )
    annual_income = known.annual_gross_income + (supplied.get("other_income_sources") or 0)
    dti = (monthly_debt * 12) / annual_income if annual_income else 1.0
    if dti > 0.45:
        rate += 0.40
    elif dti > 0.35:
        rate += 0.20
    elif dti > 0.25:
        rate += 0.05

    if known.credit_history_missed_payments_count >= 2:
        rate += 0.30
    elif known.credit_history_missed_payments_count == 1:
        rate += 0.10

    return round(max(rate, 3.20), 2)


def _monthly_repayment(loan_amount: float, annual_rate: float, term_years: int) -> float:
    monthly_rate = annual_rate / 100 / 12
    n = term_years * 12
    if monthly_rate == 0:
        return round(loan_amount / n, 2)
    payment = loan_amount * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)
    return round(payment, 2)


MAX_NEGOTIATION_ROUNDS = 5
BANK_ANCHOR_MARGIN = 0.45   # bank's opening rate = fair_rate + this
BANK_FLOOR_MARGIN = 0.05    # bank will not price below fair_rate + this


# ============================================================================
# 5. ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    return {"status": "Online", "service": "UBP Bank Agent -- Mortgage Negotiation Edition"}


@app.post("/ubp/v1/agent/mortgage/requirements", response_model=RequirementsResponse)
async def mortgage_requirements(req: RequirementsRequest):
    """Customer Agent calls this first: 'here's what I already have -- what else do you need?'"""
    customer = _get_or_create_customer(req.customer_id)
    customer["supplied"].update({k: v for k, v in req.supplied_so_far.items() if v is not None})

    missing_required = []
    missing_optional = []
    for field, meta in FIELD_METADATA.items():
        if customer["supplied"].get(field) is None:
            entry = {"field": field, "question": meta["question"]}
            (missing_required if meta["required"] else missing_optional).append(entry)

    return RequirementsResponse(
        customer_id=req.customer_id,
        known_to_bank=customer["known"].model_dump(),
        still_missing_required=missing_required,
        still_missing_optional=missing_optional,
        ready_to_negotiate=len(missing_required) == 0,
    )


@app.post("/ubp/v1/agent/mortgage/negotiate", response_model=NegotiationResponse)
async def mortgage_negotiate(proposal: NegotiationProposal):
    """Round-based negotiation. Bank anchors high, concedes gradually toward
    its floor as rounds progress, and will not go below floor no matter what."""
    customer = _get_or_create_customer(proposal.customer_id)
    known = customer["known"]
    customer["supplied"].update({k: v for k, v in proposal.supplied_data.items() if v is not None})
    supplied = customer["supplied"]

    required_missing = [
        f for f, meta in FIELD_METADATA.items() if meta["required"] and supplied.get(f) is None
    ]
    if required_missing:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot negotiate yet -- missing required fields: {required_missing}. Call /requirements first.",
        )

    loan_amount = float(supplied["requested_loan_amount"])
    deposit = float(supplied["deposit_available"])
    term_years = int(supplied["requested_mortgage_term_years"])
    property_value = loan_amount + deposit
    ltv_percent = round((loan_amount / property_value) * 100, 2) if property_value else 100.0

    fair_rate = _compute_fair_rate(known, supplied, ltv_percent)

    if ltv_percent > 90:
        return NegotiationResponse(
            customer_id=proposal.customer_id,
            round=proposal.round,
            negotiation_status="reject",
            ltv_percent=ltv_percent,
            loan_amount=loan_amount,
            term_years=term_years,
            rationale=(
                f"Requested loan implies {ltv_percent:.1f}% LTV, which exceeds this bank's 90% "
                f"maximum. Increase deposit or reduce loan amount to proceed."
            ),
            can_continue_negotiating=False,
        )

    anchor_rate = round(fair_rate + BANK_ANCHOR_MARGIN, 2)
    floor_rate = round(fair_rate + BANK_FLOOR_MARGIN, 2)

    # Round 1 with no customer ask yet -- bank makes its opening move
    if proposal.desired_interest_rate is None:
        repayment = _monthly_repayment(loan_amount, anchor_rate, term_years)
        return NegotiationResponse(
            customer_id=proposal.customer_id,
            round=proposal.round,
            negotiation_status="opening_offer",
            bank_offered_rate=anchor_rate,
            loan_amount=loan_amount,
            ltv_percent=ltv_percent,
            term_years=term_years,
            monthly_repayment_estimate=repayment,
            rationale=(
                f"Opening offer at {anchor_rate}% APR for {ltv_percent:.1f}% LTV. "
                f"Estimated monthly repayment: £{repayment:,.2f} over {term_years} years."
            ),
            can_continue_negotiating=True,
        )

    ask = float(proposal.desired_interest_rate)

    # Customer asking for a rate at/above bank's anchor -- great for the bank, accept immediately
    if ask >= anchor_rate:
        repayment = _monthly_repayment(loan_amount, anchor_rate, term_years)
        return NegotiationResponse(
            customer_id=proposal.customer_id,
            round=proposal.round,
            negotiation_status="accept",
            bank_offered_rate=anchor_rate,
            loan_amount=loan_amount,
            ltv_percent=ltv_percent,
            term_years=term_years,
            monthly_repayment_estimate=repayment,
            rationale=f"Accepted at {anchor_rate}% -- your ask was at or above our standard rate.",
            can_continue_negotiating=False,
        )

    # Customer asking at/below bank's true floor -- won't go there, final offer at floor
    if ask <= floor_rate or proposal.round >= MAX_NEGOTIATION_ROUNDS:
        repayment = _monthly_repayment(loan_amount, floor_rate, term_years)
        return NegotiationResponse(
            customer_id=proposal.customer_id,
            round=proposal.round,
            negotiation_status="final_offer",
            bank_offered_rate=floor_rate,
            loan_amount=loan_amount,
            ltv_percent=ltv_percent,
            term_years=term_years,
            monthly_repayment_estimate=repayment,
            rationale=(
                f"{floor_rate}% is our best and final rate given your risk profile -- "
                f"we cannot go lower and remain profitable on this loan."
            ),
            can_continue_negotiating=False,
        )

    # Gradual concession: bank moves a growing fraction of the gap toward the floor each round
    concession_schedule = {1: 0.20, 2: 0.45, 3: 0.70, 4: 0.90}
    fraction = concession_schedule.get(proposal.round, 0.90)
    gap = anchor_rate - floor_rate
    counter_rate = round(anchor_rate - gap * fraction, 2)
    counter_rate = max(counter_rate, floor_rate)

    repayment = _monthly_repayment(loan_amount, counter_rate, term_years)
    return NegotiationResponse(
        customer_id=proposal.customer_id,
        round=proposal.round,
        negotiation_status="counter",
        bank_offered_rate=counter_rate,
        loan_amount=loan_amount,
        ltv_percent=ltv_percent,
        term_years=term_years,
        monthly_repayment_estimate=repayment,
        rationale=(
            f"Your ask of {ask}% is below our current position. Countering at {counter_rate}% "
            f"(round {proposal.round} of up to {MAX_NEGOTIATION_ROUNDS})."
        ),
        can_continue_negotiating=True,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("bank_agent:app", host="0.0.0.0", port=8000, reload=True)
