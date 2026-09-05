"""
UBP Bank Agent -- Mortgage Journey, Auto-Classified, with Live Dashboard
=========================================================================
Single entrypoint: POST /ubp/v1/agent
  Request:  { "customer_id": "1", "query": "<natural language from ChatGPT>", "parameters": {} }
  - customer_id defaults to "1" if omitted/blank.
  - workflow_type is NOT required from the caller -- the bank agent classifies
    it itself from the query text (mortgage vs subscription).
  - Every call appends to a per-customer audit trail: conversation, risk
    checks performed, negotiation rounds, and step/status tracker.

Dashboard: GET /ui  -- self-contained HTML+JS, polls the state endpoint and
renders 4 panels: (1) conversation, (2) checks performed, (3) negotiation
workflow, (4) steps completed.
"""

import hashlib
import random
import re
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="UBP Bank Agent -- Auto-Classified Mortgage Journey",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# 1. CUSTOMER DATA MODEL -- 20 known-to-bank + 10 customer-supplied = 30
# ============================================================================

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
    existing_debts_with_bank: float
    existing_debts_with_bank_monthly_payment: float
    credit_score: int
    credit_history_missed_payments_count: int
    current_savings_balance: float
    current_account_avg_balance_6m: float
    residency_status: Literal["uk_citizen", "settled_status", "visa_holder"]
    existing_mortgage_customer: bool
    years_as_bank_customer: float
    marital_status: Literal["single", "married", "civil_partnership", "divorced"]
    current_address_years: float


FIELD_METADATA: dict[str, dict] = {
    "requested_loan_amount": {"required": True, "question": "How much do you need to borrow?"},
    "property_location": {"required": True, "question": "Where is the property located (city/postcode)?"},
    "deposit_available": {"required": True, "question": "How much deposit do you have available?"},
    "requested_mortgage_term_years": {"required": True, "question": "Over how many years would you like the mortgage term (e.g. 25, 30)?"},
    "is_first_time_buyer": {"required": True, "question": "Are you a first-time buyer?"},
    "property_type": {"required": False, "question": "What type of property is it (flat, terraced, semi-detached, detached, new build)?"},
    "deposit_source": {"required": False, "question": "What is the source of your deposit (savings, gift, inheritance, property sale)?"},
    "number_of_dependents": {"required": False, "question": "How many dependents do you have?"},
    "other_income_sources": {"required": False, "question": "Do you have any other annual income not held with this bank?"},
    "other_outstanding_debts_elsewhere": {"required": False, "question": "Any outstanding loans/credit cards with OTHER lenders?"},
}


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
        employer_name=rng.choice(["Acme Corp", "Globex Ltd", "Initech"] if employment != "self_employed" else ["Self-Employed"]),
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


def _mock_subscriptions(customer_id: str) -> list[dict]:
    providers = ["Sky", "Netflix", "Spotify", "Amazon Prime", "Disney+"]
    rng = _seeded_rng(customer_id, "subs")
    subs = []
    for provider in providers:
        amount = rng.choice([6.99, 9.99, 12.99, 24.99, 34.99, 49.99])
        paid = rng.random() > 0.15
        subs.append({
            "provider": provider,
            "monthly_amount_gbp": amount,
            "last_payment_status": "PAID" if paid else "FAILED",
        })
    return subs


# ============================================================================
# 2. PER-CUSTOMER STATE -- conversation / checks / negotiation / steps
# ============================================================================

_CUSTOMER_DB: dict[str, dict] = {}
STEP_NAMES = ["Requirements gathering", "Risk checks", "Negotiation", "Decision"]


def _get_customer(customer_id: str) -> dict:
    if customer_id not in _CUSTOMER_DB:
        _CUSTOMER_DB[customer_id] = {
            "known": _generate_known_profile(customer_id),
            "supplied": {},
            "conversation": [],
            "checks": [],
            "negotiation": [],
            "steps": [{"step": s, "status": "pending"} for s in STEP_NAMES],
            "workflow_type": None,
            "final_decision": None,
        }
    return _CUSTOMER_DB[customer_id]


def _log(state: dict, role: str, message: str):
    state["conversation"].append({
        "role": role, "message": message, "timestamp": datetime.utcnow().isoformat(),
    })


def _check(state: dict, name: str, passed: bool, detail: str):
    state["checks"].append({"name": name, "passed": passed, "detail": detail})


def _set_step(state: dict, step_name: str, status: str):
    for s in state["steps"]:
        if s["step"] == step_name:
            s["status"] = status


# ============================================================================
# 3. WORKFLOW CLASSIFICATION -- bank agent decides, caller doesn't specify
# ============================================================================

MORTGAGE_KEYWORDS = ["mortgage", "home", "house", "property", "buy", "borrow", "loan", "deposit", "flat"]
SUBSCRIPTION_KEYWORDS = ["subscription", "sky", "netflix", "spotify", "prime", "disney", "payment", "bill", "paid"]


def classify_workflow(query: str) -> Literal["mortgage", "subscription"]:
    q = query.lower()
    mortgage_score = sum(1 for kw in MORTGAGE_KEYWORDS if kw in q)
    subscription_score = sum(1 for kw in SUBSCRIPTION_KEYWORDS if kw in q)
    return "subscription" if subscription_score > mortgage_score else "mortgage"


_AMOUNT_PATTERN = re.compile(r"£?\s*([\d,]+(?:\.\d+)?)\s*(k|thousand)?", re.IGNORECASE)


def _extract_amount(query: str, key_hints: list[str], parameters: dict) -> Optional[float]:
    for hint in key_hints:
        if hint in parameters and parameters[hint] is not None:
            try:
                return float(parameters[hint])
            except (TypeError, ValueError):
                pass
    for match in _AMOUNT_PATTERN.finditer(query):
        raw, suffix = match.groups()
        if not raw:
            continue
        value = float(raw.replace(",", ""))
        if suffix:
            value *= 1_000
        if value >= 1_000:
            return value
    return None


# ============================================================================
# 4. PRICING ENGINE
# ============================================================================

def _compute_fair_rate(known: KnownToBank, supplied: dict, ltv_percent: float, state: dict) -> float:
    rate = 4.20
    if ltv_percent > 85:
        rate += 0.55
        _check(state, "LTV check", False, f"{ltv_percent:.1f}% LTV is high risk -- rate loaded +0.55%")
    elif ltv_percent > 75:
        rate += 0.20
        _check(state, "LTV check", True, f"{ltv_percent:.1f}% LTV is moderate -- rate loaded +0.20%")
    else:
        _check(state, "LTV check", True, f"{ltv_percent:.1f}% LTV is low risk -- no loading")

    cs = known.credit_score
    if cs < 650:
        rate += 0.50
        _check(state, "Credit score check", False, f"Score {cs} is below preferred threshold -- rate loaded +0.50%")
    elif cs < 780:
        rate += 0.10
        _check(state, "Credit score check", True, f"Score {cs} is acceptable -- small loading +0.10%")
    else:
        rate -= 0.10
        _check(state, "Credit score check", True, f"Score {cs} is excellent -- discount -0.10%")

    if known.employment_status in ("self_employed", "contract"):
        rate += 0.20
        _check(state, "Employment stability check", False, f"{known.employment_status} status -- rate loaded +0.20%")
    else:
        _check(state, "Employment stability check", True, "Salaried employment -- no loading")

    monthly_debt = known.existing_debts_with_bank_monthly_payment + (supplied.get("other_outstanding_debts_elsewhere") or 0) / 24
    annual_income = known.annual_gross_income + (supplied.get("other_income_sources") or 0)
    dti = (monthly_debt * 12) / annual_income if annual_income else 1.0
    if dti > 0.35:
        rate += 0.30
        _check(state, "Debt-to-income check", False, f"DTI {dti:.0%} is elevated -- rate loaded +0.30%")
    else:
        _check(state, "Debt-to-income check", True, f"DTI {dti:.0%} is healthy -- no loading")

    return round(max(rate, 3.20), 2)


def _monthly_repayment(loan_amount: float, annual_rate: float, term_years: int) -> float:
    monthly_rate = annual_rate / 100 / 12
    n = term_years * 12
    if monthly_rate == 0:
        return round(loan_amount / n, 2)
    payment = loan_amount * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)
    return round(payment, 2)


MAX_ROUNDS = 4
ANCHOR_MARGIN = 0.45
FLOOR_MARGIN = 0.05


def _run_negotiation(state: dict, known: KnownToBank, supplied: dict, loan_amount: float, term_years: int, ltv_percent: float) -> dict:
    """Auto-simulates the back-and-forth in one call: bank anchors high,
    a simulated customer-profit-maximizing agent counters low, bank concedes
    gradually toward its floor. Every round is logged for the UI."""
    fair_rate = _compute_fair_rate(known, supplied, ltv_percent, state)
    anchor = round(fair_rate + ANCHOR_MARGIN, 2)
    floor = round(fair_rate + FLOOR_MARGIN, 2)

    state["negotiation"].append({"round": 0, "who": "bank", "rate": anchor, "note": "Opening anchor offer"})
    _log(state, "bank_agent", f"Opening offer: {anchor}% APR.")

    current = anchor
    customer_ask = floor  # simulated customer agent always pushes toward the floor
    concession_schedule = {1: 0.20, 2: 0.45, 3: 0.70}

    for rnd in range(1, MAX_ROUNDS):
        state["negotiation"].append({"round": rnd, "who": "customer", "rate": customer_ask, "note": "Counter -- requesting lower rate"})
        _log(state, "customer_agent", f"Round {rnd}: requesting {customer_ask}%.")

        if customer_ask >= current:
            break
        if customer_ask <= floor or rnd >= MAX_ROUNDS - 1:
            current = floor
            state["negotiation"].append({"round": rnd, "who": "bank", "rate": current, "note": "Final offer -- at floor"})
            _log(state, "bank_agent", f"Round {rnd}: final offer {current}% (floor reached).")
            break
        fraction = concession_schedule.get(rnd, 0.90)
        gap = anchor - floor
        current = round(anchor - gap * fraction, 2)
        current = max(current, floor)
        state["negotiation"].append({"round": rnd, "who": "bank", "rate": current, "note": "Counter -- partial concession"})
        _log(state, "bank_agent", f"Round {rnd}: countering at {current}%.")

    repayment = _monthly_repayment(loan_amount, current, term_years)
    return {"final_rate": current, "monthly_repayment": repayment}


# ============================================================================
# 5. REQUEST / RESPONSE
# ============================================================================

class AgentRequest(BaseModel):
    customer_id: str = Field(default="1", description="Customer identifier -- defaults to '1' if not supplied")
    workflow_type: Optional[str] = Field(default=None, description="Ignored -- bank agent classifies this itself from the query")
    query: str = Field(..., description="Natural language message, as sent by the AI assistant")
    parameters: dict = Field(default_factory=dict)


@app.get("/")
async def root():
    return {"status": "Online", "service": "UBP Bank Agent -- Auto-Classified Mortgage Journey"}


@app.post("/ubp/v1/agent")
async def bank_agent(req: AgentRequest):
    customer_id = req.customer_id.strip() if req.customer_id and req.customer_id.strip() else "1"
    state = _get_customer(customer_id)
    known = state["known"]

    _log(state, "customer_agent", req.query or "(no message)")

    workflow_type = classify_workflow(req.query)
    state["workflow_type"] = workflow_type
    _log(state, "bank_agent", f"Classified this request as a '{workflow_type}' workflow.")

    if workflow_type == "subscription":
        _set_step(state, "Requirements gathering", "done")
        _set_step(state, "Risk checks", "done")
        _set_step(state, "Negotiation", "not_applicable")

        subs = _mock_subscriptions(customer_id)
        target = req.parameters.get("provider")
        if not target:
            for s in subs:
                if s["provider"].lower() in req.query.lower():
                    target = s["provider"]
                    break

        if target:
            match = next((s for s in subs if s["provider"].lower() == str(target).lower()), None)
            _check(state, "Subscription lookup", match is not None, f"Searched for provider '{target}'")
            if match:
                paid = match["last_payment_status"] == "PAID"
                answer = (
                    f"Yes -- your £{match['monthly_amount_gbp']:.2f} {match['provider']} payment went through."
                    if paid else
                    f"No -- your £{match['monthly_amount_gbp']:.2f} {match['provider']} payment failed."
                )
            else:
                answer = f"No subscription found matching '{target}'."
        else:
            answer = "Here is your full recurring payment summary."
            state["_subs_snapshot"] = subs

        _set_step(state, "Decision", "done")
        _log(state, "bank_agent", answer)
        state["final_decision"] = {"answer": answer, "subscriptions": subs if not target else None}
        return {"status": "SUCCESS", "workflow_type": workflow_type, "agent_response": {"verdict": answer, "subscriptions": subs}}

    # --- mortgage workflow ---
    supplied = state["supplied"]
    supplied.update({k: v for k, v in req.parameters.items() if v is not None})
    if "requested_loan_amount" not in supplied or supplied.get("requested_loan_amount") is None:
        amt = _extract_amount(req.query, ["requested_loan_amount", "amount"], req.parameters)
        if amt:
            supplied["requested_loan_amount"] = amt

    missing_required = [f for f, m in FIELD_METADATA.items() if m["required"] and supplied.get(f) is None]

    if missing_required:
        _set_step(state, "Requirements gathering", "in_progress")
        questions = [FIELD_METADATA[f]["question"] for f in missing_required]
        answer = "Before I can proceed, I need a bit more information: " + " ".join(questions)
        _log(state, "bank_agent", answer)
        return {
            "status": "NEEDS_INFO",
            "workflow_type": workflow_type,
            "agent_response": {"verdict": answer, "missing_fields": missing_required},
        }

    _set_step(state, "Requirements gathering", "done")
    _set_step(state, "Risk checks", "in_progress")

    loan_amount = float(supplied["requested_loan_amount"])
    deposit = float(supplied["deposit_available"])
    term_years = int(supplied["requested_mortgage_term_years"])
    property_value = loan_amount + deposit
    ltv_percent = round((loan_amount / property_value) * 100, 2) if property_value else 100.0

    if ltv_percent > 90:
        _check(state, "LTV eligibility", False, f"{ltv_percent:.1f}% LTV exceeds 90% maximum")
        _set_step(state, "Risk checks", "done")
        _set_step(state, "Negotiation", "not_applicable")
        _set_step(state, "Decision", "done")
        answer = f"Requested loan implies {ltv_percent:.1f}% LTV, which exceeds our 90% maximum. A larger deposit is needed."
        _log(state, "bank_agent", answer)
        return {"status": "REJECTED", "workflow_type": workflow_type, "agent_response": {"verdict": answer}}

    _set_step(state, "Risk checks", "done")
    _set_step(state, "Negotiation", "in_progress")
    result = _run_negotiation(state, known, supplied, loan_amount, term_years, ltv_percent)
    _set_step(state, "Negotiation", "done")
    _set_step(state, "Decision", "done")

    answer = (
        f"Based on your profile, we've agreed a rate of {result['final_rate']}% APR on £{loan_amount:,.0f} "
        f"over {term_years} years -- estimated monthly repayment £{result['monthly_repayment']:,.2f}."
    )
    _log(state, "bank_agent", answer)
    state["final_decision"] = {"rate": result["final_rate"], "monthly_repayment": result["monthly_repayment"]}
    return {
        "status": "SUCCESS",
        "workflow_type": workflow_type,
        "agent_response": {
            "verdict": answer,
            "final_rate": result["final_rate"],
            "loan_amount": loan_amount,
            "ltv_percent": ltv_percent,
            "term_years": term_years,
            "monthly_repayment_estimate": result["monthly_repayment"],
        },
    }


@app.get("/ubp/v1/agent/state/{customer_id}")
async def get_state(customer_id: str):
    if customer_id not in _CUSTOMER_DB:
        raise HTTPException(status_code=404, detail="No state yet for this customer_id")
    state = _CUSTOMER_DB[customer_id]
    return {
        "customer_id": customer_id,
        "workflow_type": state["workflow_type"],
        "conversation": state["conversation"],
        "checks": state["checks"],
        "negotiation": state["negotiation"],
        "steps": state["steps"],
        "final_decision": state["final_decision"],
    }


# ============================================================================
# 6. DASHBOARD UI -- 4 panels, polls the state endpoint
# ============================================================================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>UBP Mortgage Journey Dashboard</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#8891a3;
          --accent:#4f7cff; --ok:#3ecf8e; --bad:#ff5c5c; --pending:#c9a13b; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font-family: -apple-system, Segoe UI, Roboto, sans-serif; }
  header { padding:20px 24px; border-bottom:1px solid var(--border); display:flex; align-items:center; gap:16px; }
  header h1 { font-size:18px; margin:0; font-weight:600; }
  header input { background:var(--panel); border:1px solid var(--border); color:var(--text); padding:6px 10px; border-radius:6px; width:120px; }
  header button { background:var(--accent); border:none; color:white; padding:7px 14px; border-radius:6px; cursor:pointer; font-size:13px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; padding:20px; }
  .panel { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:16px; min-height:280px; max-height:420px; overflow-y:auto; }
  .panel h2 { font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:0 0 12px 0; }
  .msg { margin-bottom:10px; padding:8px 10px; border-radius:8px; font-size:13px; line-height:1.4; }
  .msg.customer_agent { background:#1d2433; border-left:3px solid var(--accent); }
  .msg.bank_agent { background:#1e2420; border-left:3px solid var(--ok); }
  .msg .role { font-size:10px; color:var(--muted); text-transform:uppercase; margin-bottom:3px; }
  .check { display:flex; justify-content:space-between; gap:8px; padding:8px 0; border-bottom:1px solid var(--border); font-size:13px; }
  .check:last-child { border-bottom:none; }
  .badge { font-size:11px; padding:2px 8px; border-radius:20px; white-space:nowrap; height:fit-content; }
  .badge.ok { background:rgba(62,207,142,.15); color:var(--ok); }
  .badge.bad { background:rgba(255,92,92,.15); color:var(--bad); }
  .round { display:flex; justify-content:space-between; font-size:13px; padding:6px 0; border-bottom:1px solid var(--border); }
  .round .who { text-transform:capitalize; color:var(--muted); }
  .step { display:flex; align-items:center; gap:10px; padding:10px 0; }
  .dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
  .dot.done { background:var(--ok); }
  .dot.in_progress { background:var(--pending); }
  .dot.pending { background:var(--border); }
  .dot.not_applicable { background:var(--muted); opacity:.4; }
  .step .label { font-size:13px; }
  .step .status { font-size:11px; color:var(--muted); margin-left:auto; text-transform:capitalize; }
  .empty { color:var(--muted); font-size:13px; }
  .verdict { margin-top:12px; padding:10px; background:#1a2e22; border:1px solid #2a4a36; border-radius:8px; font-size:13px; }
</style>
</head>
<body>
  <header>
    <h1>UBP Mortgage Journey Dashboard</h1>
    <input id="customerId" value="1" placeholder="customer_id">
    <button onclick="load()">Refresh</button>
  </header>
  <div class="grid">
    <div class="panel">
      <h2>1. Conversation</h2>
      <div id="conversation"><div class="empty">No conversation yet.</div></div>
    </div>
    <div class="panel">
      <h2>2. Checks Performed</h2>
      <div id="checks"><div class="empty">No checks yet.</div></div>
    </div>
    <div class="panel">
      <h2>3. Negotiation Workflow</h2>
      <div id="negotiation"><div class="empty">No negotiation yet.</div></div>
    </div>
    <div class="panel">
      <h2>4. Steps Completed</h2>
      <div id="steps"><div class="empty">No activity yet.</div></div>
    </div>
  </div>

<script>
async function load() {
  const id = document.getElementById('customerId').value || '1';
  try {
    const res = await fetch(`/ubp/v1/agent/state/${id}`);
    if (!res.ok) { renderEmpty(); return; }
    const data = await res.json();
    renderConversation(data.conversation);
    renderChecks(data.checks);
    renderNegotiation(data.negotiation);
    renderSteps(data.steps, data.final_decision);
  } catch (e) { renderEmpty(); }
}
function renderEmpty() {
  ['conversation','checks','negotiation','steps'].forEach(id => {
    document.getElementById(id).innerHTML = '<div class="empty">No data yet for this customer_id.</div>';
  });
}
function renderConversation(items) {
  const el = document.getElementById('conversation');
  if (!items || !items.length) { el.innerHTML = '<div class="empty">No conversation yet.</div>'; return; }
  el.innerHTML = items.map(m => `
    <div class="msg ${m.role}">
      <div class="role">${m.role.replace('_',' ')}</div>
      <div>${m.message}</div>
    </div>`).join('');
}
function renderChecks(items) {
  const el = document.getElementById('checks');
  if (!items || !items.length) { el.innerHTML = '<div class="empty">No checks yet.</div>'; return; }
  el.innerHTML = items.map(c => `
    <div class="check">
      <div><strong>${c.name}</strong><br><span style="color:var(--muted)">${c.detail}</span></div>
      <span class="badge ${c.passed ? 'ok' : 'bad'}">${c.passed ? 'PASS' : 'FLAG'}</span>
    </div>`).join('');
}
function renderNegotiation(items) {
  const el = document.getElementById('negotiation');
  if (!items || !items.length) { el.innerHTML = '<div class="empty">No negotiation yet.</div>'; return; }
  el.innerHTML = items.map(r => `
    <div class="round">
      <span class="who">Round ${r.round} -- ${r.who}</span>
      <span>${r.rate}% -- ${r.note}</span>
    </div>`).join('');
}
function renderSteps(items, decision) {
  const el = document.getElementById('steps');
  if (!items || !items.length) { el.innerHTML = '<div class="empty">No activity yet.</div>'; return; }
  let html = items.map(s => `
    <div class="step">
      <div class="dot ${s.status}"></div>
      <div class="label">${s.step}</div>
      <div class="status">${s.status.replace('_',' ')}</div>
    </div>`).join('');
  if (decision) {
    html += `<div class="verdict">${decision.answer || JSON.stringify(decision)}</div>`;
  }
  el.innerHTML = html;
}
load();
setInterval(load, 3000);
</script>
</body>
</html>
"""


@app.get("/ui", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bank_agent:app", host="0.0.0.0", port=8000, reload=True)
