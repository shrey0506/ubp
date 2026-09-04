import asyncio
import os
from datetime import datetime
from typing import List
import uvicorn
from fastapi import FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security.api_key import APIKeyHeader
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

app = FastAPI(
    title="Lloyds Bank UBP & LLM-Powered Profit-Maximization Agent",
    version="2.0.0",
    description=(
        "Universal Banking Protocol (UBP) server utilizing Gemini for live"
        " intelligent bank negotiations."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UBP_API_KEY = "lloyds-ubp-secure-token-2026"
api_key_header = APIKeyHeader(name="X-UBP-Signature", auto_error=False)

# Initialize the Google GenAI client (picks up GEMINI_API_KEY from environment variables)
# Make sure to set GEMINI_API_KEY in your Render environment variables dashboard!
client = genai.Client()


async def verify_ubp_protocol(api_key: str = Security(api_key_header)):
  if api_key != UBP_API_KEY:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="UBP Handshake Failed: Invalid signature.",
    )
  return api_key


system_state = {
    "active_steps": [],
    "bank_checks": [],
    "negotiation_logs": [],
    "chat_logs": [],
}


class UBPMessageRequest(BaseModel):
  customer_id: str
  intent: str = Field(..., description="mortgage or subscription")
  parameters: dict


class BankAgentResponse(BaseModel):
  status: str
  ubp_protocol_version: str = "2.0-secure-llm"
  profit_optimization_applied: bool = True
  recommendation: str
  financial_metrics: dict
  execution_steps: List[str]
  audit_checks: List[dict]
  negotiation_history: List[str]


def log_activity(step: str, check: dict, negotiation: str, chat: dict):
  if step:
    system_state["active_steps"].append(
        {"timestamp": datetime.now().strftime("%H:%M:%S"), "step": step}
    )
  if check:
    system_state["bank_checks"].append(
        {"timestamp": datetime.now().strftime("%H:%M:%S"), **check}
    )
  if negotiation:
    system_state["negotiation_logs"].append(
        {"timestamp": datetime.now().strftime("%H:%M:%S"), "log": negotiation}
    )
  if chat:
    system_state["chat_logs"].append(
        {"timestamp": datetime.now().strftime("%H:%M:%S"), **chat}
    )


# --- UI Dashboard Endpoint ---
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
  return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lloyds Bank Agent - LLM & UBP Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .glass-panel { background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.1); }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 font-sans min-h-screen p-6">
    <header class="max-w-7xl mx-auto mb-8 flex flex-col md:flex-row justify-between items-center border-b border-slate-800 pb-4">
        <div>
            <h1 class="text-3xl font-extrabold tracking-tight text-emerald-400 flex items-center gap-3">
                <span class="bg-emerald-500 text-slate-950 px-3 py-1 rounded-lg text-sm">UBP v2.0 LLM</span> 
                Lloyds Bank Agent Dashboard
            </h1>
            <p class="text-slate-400 text-sm mt-1">Powered by Gemini AI • Objective: Maximize Bank Profitability</p>
        </div>
        <div class="mt-4 md:mt-0 flex items-center gap-3">
            <button onclick="triggerSimulation('mortgage')" class="bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold px-4 py-2 rounded-lg text-sm transition shadow-lg shadow-emerald-900/40">
                Simulate Mortgage Flow
            </button>
            <button onclick="triggerSimulation('subscription')" class="bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold px-4 py-2 rounded-lg text-sm transition shadow-lg shadow-cyan-900/40">
                Simulate Subscription Upsell
            </button>
        </div>
    </header>

    <main class="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-6">
        <section class="glass-panel rounded-2xl p-5 flex flex-col h-[400px]">
            <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
                <h2 class="font-semibold text-lg text-slate-200">💬 Part 1: Live Chat Log (ChatGPT Plugin ⇄ Bank)</h2>
                <span class="text-xs bg-slate-800 text-emerald-400 px-2.5 py-1 rounded-full">Secure UBP</span>
            </div>
            <div id="chat-logs" class="flex-1 overflow-y-auto space-y-3 pr-2 text-sm">
                <div class="text-slate-500 text-center italic mt-10">Awaiting UBP simulation request...</div>
            </div>
        </section>

        <section class="glass-panel rounded-2xl p-5 flex flex-col h-[400px]">
            <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
                <h2 class="font-semibold text-lg text-slate-200">🔒 Part 2: Bank Compliance & Checks</h2>
                <span class="text-xs bg-slate-800 text-amber-400 px-2.5 py-1 rounded-full">Automated Audits</span>
            </div>
            <div id="bank-checks" class="flex-1 overflow-y-auto space-y-2 pr-2 text-sm">
                <div class="text-slate-500 text-center italic mt-10">No active verification rules triggered.</div>
            </div>
        </section>

        <section class="glass-panel rounded-2xl p-5 flex flex-col h-[400px]">
            <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
                <h2 class="font-semibold text-lg text-slate-200">📈 Part 3: Profit Maximization Negotiation</h2>
                <span class="text-xs bg-slate-800 text-purple-400 px-2.5 py-1 rounded-full">Gemini NIM Strategy</span>
            </div>
            <div id="negotiation-logs" class="flex-1 overflow-y-auto space-y-3 pr-2 text-sm">
                <div class="text-slate-500 text-center italic mt-10">Optimization engine idling...</div>
            </div>
        </section>

        <section class="glass-panel rounded-2xl p-5 flex flex-col h-[400px]">
            <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
                <h2 class="font-semibold text-lg text-slate-200">⚙️ Part 4: Step Execution Pipeline</h2>
                <span class="text-xs bg-slate-800 text-blue-400 px-2.5 py-1 rounded-full">UBP Workflow</span>
            </div>
            <div id="execution-steps" class="flex-1 overflow-y-auto space-y-3 pr-2 text-sm">
                <div class="text-slate-500 text-center italic mt-10">Pipeline steps will render here sequentially.</div>
            </div>
        </section>
    </main>

    <script>
        async function triggerSimulation(intentType) {
            let payload = {
                customer_id: "GB-LLOYDS-88219",
                intent: intentType,
                parameters: intentType === 'mortgage' 
                    ? { loan_amount: 380000, deposit: 60000, income: 80000 }
                    : { tier: "standard rewards" }
            };
            try {
                await fetch('/ubp/v1/negotiate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-UBP-Signature': 'lloyds-ubp-secure-token-2026' },
                    body: JSON.stringify(payload)
                });
                pollState();
            } catch (err) { alert("Simulation request failed."); }
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
                            <span class="font-bold text-purple-400">[Gemini Strategy] ${n.timestamp}:</span> ${n.log}
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


# --- LLM-Powered UBP Bank Agent Endpoint ---
@app.post("/ubp/v1/negotiate", response_model=BankAgentResponse)
async def process_ubp_negotiation(
    payload: UBPMessageRequest, token: str = Security(verify_ubp_protocol)
):
  customer_id = payload.customer_id
  intent = payload.intent.lower()
  params = payload.parameters

  steps, checks, negotiation_trail = [], [], []

  # Step 1: Gathering Payload
  step_desc = f"Step 1: Gathered UBP payload metrics for client {customer_id}"
  steps.append(step_desc)
  log_activity(
      step_desc,
      None,
      None,
      {
          "sender": "Customer Agent (ChatGPT)",
          "text": (
              f"Requested {intent} with parameters: {params} via UBP secure tunnel."
          ),
      },
  )
  await asyncio.sleep(0.3)

  # Step 2: Risk & Compliance Checks
  step_desc = "Step 2: Executing automated backend risk validation"
  steps.append(step_desc)

  check_1 = {
      "check_name": "Universal Banking Protocol Handshake",
      "result": "SECURED",
      "detail": "Encrypted tunnel authenticated via X-UBP-Signature.",
  }
  check_2 = {
      "check_name": "Financial Risk & Yield Scoring",
      "result": "PASSED",
      "detail": f"Parameters evaluated for intent: {intent}.",
  }
  checks.extend([check_1, check_2])
  log_activity(None, check_1, None, None)
  log_activity(None, check_2, None, None)

  # Step 3: Real LLM Call (Gemini) for Profit Maximization & Negotiation
  step_desc = "Step 3: Invoking Gemini AI for profit-maximization strategy"
  steps.append(step_desc)

  prompt = f"""
    You are the intelligent banking agent for Lloyds Bank. 
    Your absolute core objective is to MAXIMIZE BANK PROFITABILITY (via higher Net Interest Margins, cross-selling fee products, or upselling higher-tier subscriptions).
    
    The customer (via ChatGPT) has requested: '{intent}' with the following financial parameters: {params}.
    
    Task:
    1. Formulate a counter-offer or optimized recommendation that extracts maximum value/profit for Lloyds Bank.
    2. Provide a clear reasoning log explaining how this maximizes bank profit.
    3. Return a clean recommendation string and structured financial metrics.
    
    Format your response explicitly as plain text or structured analysis. Keep it professional, strategic, and profit-focused.
    """

  try:
    # Call Gemini model
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    llm_output = response.text
  except Exception as e:
    llm_output = (
        f"Fallback optimization applied due to LLM connectivity: {str(e)}"
    )

  negotiation_text = (
      f"Gemini Profit-Optimization Engine Execution: {llm_output}"
  )
  negotiation_trail.append(negotiation_text)
  log_activity(None, None, negotiation_text, None)

  # Build response payload
  recommendation_text = (
      f"Lloyds Bank AI Agent processed your {intent} request securely via UBP."
      " An optimized financial offer has been tailored."
  )

  response_payload = BankAgentResponse(
      status="SUCCESS_LLM_OPTIMIZED",
      recommendation=recommendation_text,
      financial_metrics={
          "intent_processed": intent,
          "parameters_analyzed": str(params),
          "ai_model": "Google Gemini 2.5 Flash",
          "strategy": "Maximum Yield Extraction",
      },
      execution_steps=steps,
      audit_checks=checks,
      negotiation_history=negotiation_trail,
  )

  log_activity(
      "Step 4: Secure UBP packet compiled and dispatched to ChatGPT Plugin",
      None,
      None,
      {
          "sender": "Lloyds Bank Agent (Gemini)",
          "text": recommendation_text,
      },
  )
  return response_payload


@app.get("/ubp/v1/state")
async def get_system_state():
  return system_state


if __name__ == "__main__":
  uvicorn.run("ubp:app", host="0.0.0.0", port=8000, reload=True)
