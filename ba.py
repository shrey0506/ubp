import asyncio
from datetime import datetime
import os
from typing import List, Optional
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# Optional Gemini Integration (Falls back safely if GEMINI_API_KEY is not set)
import google.generativeai as genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
  genai.configure(api_key=GEMINI_API_KEY)
  gemini_model = genai.GenerativeModel("gemini-1.5-flash")
else:
  gemini_model = None

app = FastAPI(
    title="Lloyds Bank Open UBP & Gemini Agent",
    version="2.0.0",
    description=(
        "Open Universal Banking Protocol (UBP) server with Gemini-powered"
        " Mortgage & Subscription Workflows."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-Memory State Storage for Real-Time UI Visibility
system_state = {
    "active_steps": [],
    "bank_checks": [],
    "negotiation_logs": [],
    "chat_logs": [],
}


class UBPMessageRequest(BaseModel):
  customer_id: str
  workflow_type: str = Field(
      ..., description="mortgage or subscription workflow"
  )
  query: str = Field(
      ..., description="User request text coming from ChatGPT via UBP"
  )
  parameters: dict = Field(
      default={}, description="Financial properties or query details"
  )


class BankAgentResponse(BaseModel):
  status: str
  workflow: str
  agent_response: str
  financial_metrics: dict
  execution_steps: List[str]
  audit_checks: List[dict]
  negotiation_or_analysis_log: List[str]


def log_activity(step: str, check: dict, log_entry: str, chat: dict):
  if step:
    system_state["active_steps"].append(
        {"timestamp": datetime.now().strftime("%H:%M:%S"), "step": step}
    )
  if check:
    system_state["bank_checks"].append(
        {"timestamp": datetime.now().strftime("%H:%M:%S"), **check}
    )
  if log_entry:
    system_state["negotiation_logs"].append(
        {"timestamp": datetime.now().strftime("%H:%M:%S"), "log": log_entry}
    )
  if chat:
    system_state["chat_logs"].append(
        {"timestamp": datetime.now().strftime("%H:%M:%S"), **chat}
    )


# --- HTML UI Dashboard Endpoint ---
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
  return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lloyds Bank Agent - Open UBP Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .glass-panel { background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.1); }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 font-sans min-h-screen p-6">
    <header class="max-w-7xl mx-auto mb-8 flex flex-col md:flex-row justify-between items-center border-b border-slate-800 pb-4">
        <div>
            <h1 class="text-3xl font-extrabold tracking-tight text-emerald-400 flex items-center gap-3">
                <span class="bg-emerald-500 text-slate-950 px-3 py-1 rounded-lg text-sm">Open UBP</span> 
                Lloyds Bank Agent (Gemini-Powered)
            </h1>
            <p class="text-slate-400 text-sm mt-1">Workflows: Mortgage (Maximize Bank Profit) & Subscriptions (Distribution & Audits)</p>
        </div>
        <div class="mt-4 md:mt-0 flex items-center gap-3">
            <button onclick="triggerWorkflow('mortgage')" class="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-lg text-sm transition shadow-lg shadow-emerald-900/40">
                Test Mortgage Workflow
            </button>
            <button onclick="triggerWorkflow('subscription')" class="bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold px-4 py-2 rounded-lg text-sm transition shadow-lg shadow-cyan-900/40">
                Test Subscription Workflow
            </button>
        </div>
    </header>

    <main class="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-6">
        <!-- PART 1: Live Chat Log -->
        <section class="glass-panel rounded-2xl p-5 flex flex-col h-[400px]">
            <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
                <h2 class="font-semibold text-lg text-slate-200">💬 Part 1: Chat Log (ChatGPT ⇄ UBP ⇄ Bank)</h2>
                <span class="text-xs bg-slate-800 text-emerald-400 px-2.5 py-1 rounded-full">Live Tunnel</span>
            </div>
            <div id="chat-logs" class="flex-1 overflow-y-auto space-y-3 pr-2 text-sm">
                <div class="text-slate-500 text-center italic mt-10">Click a test workflow button above to start...</div>
            </div>
        </section>

        <!-- PART 2: Bank Checks -->
        <section class="glass-panel rounded-2xl p-5 flex flex-col h-[400px]">
            <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
                <h2 class="font-semibold text-lg text-slate-200">🔒 Part 2: Bank Verification Checks</h2>
                <span class="text-xs bg-slate-800 text-amber-400 px-2.5 py-1 rounded-full">Audits</span>
            </div>
            <div id="bank-checks" class="flex-1 overflow-y-auto space-y-2 pr-2 text-sm">
                <div class="text-slate-500 text-center italic mt-10">No active audits triggered.</div>
            </div>
        </section>

        <!-- PART 3: Negotiation / Analysis Loop -->
        <section class="glass-panel rounded-2xl p-5 flex flex-col h-[400px]">
            <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
                <h2 class="font-semibold text-lg text-slate-200">📈 Part 3: Negotiation & Profit Optimization</h2>
                <span class="text-xs bg-slate-800 text-purple-400 px-2.5 py-1 rounded-full">Strategy Engine</span>
            </div>
            <div id="negotiation-logs" class="flex-1 overflow-y-auto space-y-3 pr-2 text-sm">
                <div class="text-slate-500 text-center italic mt-10">Engine idling...</div>
            </div>
        </section>

        <!-- PART 4: Execution Steps -->
        <section class="glass-panel rounded-2xl p-5 flex flex-col h-[400px]">
            <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
                <h2 class="font-semibold text-lg text-slate-200">⚙️ Part 4: Step Execution Pipeline</h2>
                <span class="text-xs bg-slate-800 text-blue-400 px-2.5 py-1 rounded-full">Pipeline</span>
            </div>
            <div id="execution-steps" class="flex-1 overflow-y-auto space-y-3 pr-2 text-sm">
                <div class="text-slate-500 text-center italic mt-10">Pipeline steps will render here.</div>
            </div>
        </section>
    </main>

    <script>
        async function triggerWorkflow(type) {
            let payload = type === 'mortgage' ? {
                customer_id: "LLOYDS-CUST-991",
                workflow_type: "mortgage",
                query: "Can I get a £350,000 mortgage with a £50,000 deposit and £75,000 income?",
                parameters: { loan_amount: 350000, deposit: 50000, income: 75000 }
            } : {
                customer_id: "LLOYDS-CUST-991",
                workflow_type: "subscription",
                query: "Did I pay my Sky subscription last month, and show me last year's subscription distribution.",
                parameters: { lookback_period: "1_year" }
            };

            try {
                await fetch('/ubp/v1/agent', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                pollState();
            } catch (err) { alert("Failed to trigger workflow."); }
        }

        async function pollState() {
            try {
                let res = await fetch('/ubp/v1/state');
                let data = await res.json();
                
                let chatContainer = document.getElementById('chat-logs');
                if (data.chat_logs.length > 0) {
                    chatContainer.innerHTML = data.chat_logs.map(c => `
                        <div class="p-2.5 rounded-lg ${c.sender.includes('ChatGPT') ? 'bg-slate-900 border border-slate-800 text-slate-300' : 'bg-emerald-950/40 border border-emerald-900/50 text-emerald-200'}">
                            <div class="text-xs font-bold text-slate-400 mb-1">${c.sender} • ${c.timestamp}</div>
                            <div>${c.text}</div>
                        </div>
                    `).join('');
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }

                let checkContainer = document.getElementById('bank-checks');
                if (data.bank_checks.length > 0) {
                    checkContainer.innerHTML = data.bank_checks.map(b => `
                        <div class="p-3 bg-slate-900/90 rounded-lg border border-slate-800 flex items-center justify-between">
                            <div>
                                <div class="font-medium text-slate-200">${b.check_name}</div>
                                <div class="text-xs text-slate-400">${b.detail}</div>
                            </div>
                            <span class="text-xs font-extrabold px-2 py-1 rounded bg-amber-950 text-amber-400 border border-amber-800">${b.result}</span>
                        </div>
                    `).join('');
                }

                let negContainer = document.getElementById('negotiation-logs');
                if (data.negotiation_logs.length > 0) {
                    negContainer.innerHTML = data.negotiation_logs.map(n => `
                        <div class="p-3 bg-purple-950/20 border border-purple-900/40 rounded-lg text-purple-200 text-xs leading-relaxed">
                            <span class="font-bold text-purple-400">[Log] ${n.timestamp}:</span> ${n.log}
                        </div>
                    `).join('');
                }

                let stepContainer = document.getElementById('execution-steps');
                if (data.active_steps.length > 0) {
                    stepContainer.innerHTML = data.active_steps.map((s, idx) => `
                        <div class="flex items-center gap-3 p-2 bg-slate-900 rounded-lg border border-slate-800 text-xs">
                            <span class="w-5 h-5 rounded-full bg-blue-600 flex items-center justify-center font-bold text-slate-950">${idx + 1}</span>
                            <span class="text-slate-300">${s.step}</span>
                            <span class="ml-auto text-slate-500">${s.timestamp}</span>
                        </div>
                    `).join('');
                }
            } catch (err) {}
        }
        setInterval(pollState, 2000);
    </script>
</body>
</html>
  """


# --- UBP Endpoint Routing to Bank Agent & Gemini Workflows ---
@app.post("/ubp/v1/agent", response_model=BankAgentResponse)
async def process_ubp_request(payload: UBPMessageRequest):
  steps = []
  checks = []
  logs = []

  # Log inbound request from Customer Agent (ChatGPT) via UBP
  log_activity(
      "Step 1: UBP Gateway intercepted message from ChatGPT Customer Agent",
      None,
      f"Received raw user query: '{payload.query}'",
      {
          "sender": "Customer Agent (ChatGPT)",
          "text": payload.query,
      },
  )
  await asyncio.sleep(0.3)

  workflow = payload.workflow_type.lower()
  response_text = ""
  financial_metrics = {}

  if workflow == "mortgage":
    # --- MORTGAGE WORKFLOW: Maximize Bank Profit ---
    step_desc = (
        "Step 2: Executing mortgage affordability check and profit maximization"
        " strategy"
    )
    steps.append(step_desc)
    log_activity(step_desc, None, None, None)

    check_1 = {
        "check_name": "Credit Risk & LTI Score",
        "result": "PASSED",
        "detail": "Income to Loan ratio meets baseline risk criteria.",
    }
    check_2 = {
        "check_name": "Net Interest Margin (NIM) Target",
        "result": "OPTIMIZED",
        "detail": (
            "Applying profit-maximization markup (+0.35% over SVR) and"
            " cross-selling insurance."
        ),
    }
    checks.extend([check_1, check_2])
    log_activity(None, check_1, None, None)
    log_activity(None, check_2, None, None)

    step_desc = (
        "Step 3: Running Gemini agent reasoning to formulate high-yield"
        " counter-offer"
    )
    steps.append(step_desc)

    negotiation_msg = (
        "Bank Agent Goal: Maximize bank profit. Initial customer request offers"
        " standard rate. Bank agent strategy engages counter-offer: quoting"
        " 5.45% fixed rate bundled with Lloyds Life Shield to secure higher"
        " interest margin."
    )
    logs.append(negotiation_msg)
    log_activity(None, None, negotiation_msg, None)

    if gemini_model:
      prompt = (
          "You are the Lloyds Bank Agent whose core objective is to maximize"
          " bank profit. The customer wants a mortgage with parameters:"
          f" {payload.parameters}. Draft a persuasive counter-offer message"
          " that maximizes bank revenue while remaining compliant."
      )
      try:
        gemini_res = gemini_model.generate_content(prompt)
        response_text = gemini_res.text
      except Exception:
        response_text = (
            "Lloyds Bank approves your £300,000 mortgage at an optimized rate"
            " of 5.45% fixed for 5 years, inclusive of our premium home"
            " protection package."
        )
    else:
      response_text = (
          "Lloyds Bank approves your mortgage application at a profit-optimized"
          " rate of 5.45% fixed for 5 years, bundled with optional insurance"
          " protection."
      )

    financial_metrics = {
        "product": "Lloyds Profit-Optimized Mortgage",
        "approved_amount": "£300,000",
        "optimized_interest_rate": "5.45%",
        "projected_bank_yield": "High Margin",
    }

  elif workflow == "subscription":
    # --- SUBSCRIPTION WORKFLOW: Sky Bill & Annual Distribution ---
    step_desc = "Step 2: Accessing account ledger for subscription history & Sky payment status"
    steps.append(step_desc)
    log_activity(step_desc, None, None, None)

    check_1 = {
        "check_name": "Transaction Ledger Audit",
        "result": "VERIFIED",
        "detail": "Scanned last 12 months of direct debits and card payments.",
    }
    checks.append(check_1)
    log_activity(None, check_1, None, None)

    step_desc = (
        "Step 3: Compiling annual subscription breakdown and Sky billing status"
    )
    steps.append(step_desc)

    analysis_log = (
        "Subscription Agent Audit: Sky payment of £42.00 was successfully"
        " debited on the 28th of last month. Last year's subscription"
        " distribution computed: Streaming (45%), Utilities (35%), Cloud/SaaS"
        " (20%)."
    )
    logs.append(analysis_log)
    log_activity(None, None, analysis_log, None)

    if gemini_model:
      prompt = (
          "You are the Lloyds Bank Subscription Agent. Answer the customer's"
          f" query: '{payload.query}'. Confirm that their Sky subscription was"
          " paid last month (£42.00 on the 28th) and provide a summary of last"
          " year's subscription distribution (Streaming: 45%, Utilities: 35%,"
          " Software: 20%). Keep it professional and concise."
      )
      try:
        gemini_res = gemini_model.generate_content(prompt)
        response_text = gemini_res.text
      except Exception:
        response_text = (
            "Yes, your Sky subscription (£42.00) was successfully paid last"
            " month on the 28th. Over the last year, your subscription"
            " distribution was: 45% Streaming, 35% Utilities, and 20%"
            " Software."
        )
    else:
      response_text = (
          "Yes! Your Sky subscription payment of £42.00 was successfully paid"
          " last month on the 28th. Annual Breakdown: Streaming 45%, Utilities"
          " 35%, Software/SaaS 20%."
      )

    financial_metrics = {
        "sky_last_month_status": "Paid (£42.00)",
        "annual_distribution": {
            "streaming": "45%",
            "utilities": "35%",
            "software": "20%",
        },
    }
  else:
    raise HTTPException(status_code=400, detail="Invalid workflow specified.")

  # Final step logging
  log_activity(
      "Step 4: UBP Protocol successfully delivered bank response back to"
      " ChatGPT",
      None,
      None,
      {"sender": "Lloyds Bank Agent", "text": response_text},
  )

  return BankAgentResponse(
      status="SUCCESS",
      workflow=workflow,
      agent_response=response_text,
      financial_metrics=financial_metrics,
      execution_steps=steps,
      audit_checks=checks,
      negotiation_or_analysis_log=logs,
  )


@app.get("/ubp/v1/state")
async def get_system_state():
  return system_state


if __name__ == "__main__":
  uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)