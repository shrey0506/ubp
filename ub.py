from datetime import datetime
import httpx
from fastapi import FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

app = FastAPI(
    title="Universal Banking Protocol (UBP) Gateway",
    version="2.0.0",
    description=(
        "Middleware routing user requests from ChatGPT and Claude plugins to"
        " the Lloyds Bank Agent backend."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Target deployed Bank Agent URL
BANK_AGENT_URL = "https://ubp-bank-agent.onrender.com/ubp/v1/agent"


class UserQueryPayload(BaseModel):
  customer_id: str = Field(
      ..., description="Unique customer identifier from the AI platform"
  )
  workflow_type: str = Field(
      ..., description="Either 'mortgage' or 'subscription'"
  )
  query: str = Field(..., description="The original natural language prompt")
  parameters: dict = Field(
      default={}, description="Extracted parameters like income, deposit, etc."
  )


# --- OpenAI / ChatGPT Plugin Manifest Endpoints ---
@app.get("/ai-plugin/openai/manifest.json")
async def openai_manifest():
  """Manifest required for ChatGPT Custom Plugins."""
  return {
      "schema_version": "v1",
      "name_for_human": "Lloyds Bank UBP Assistant",
      "name_for_model": "lloyds_bank_ubp",
      "description_for_human": (
          "Interact with Lloyds Bank for mortgages and subscription tracking"
          " via UBP."
      ),
      "description_for_model": (
          "Use this plugin to check bank accounts, analyze subscription"
          " distributions, and process mortgages."
      ),
      "auth": {"type": "none"},
      "api": {
          "type": "openapi",
          "url": "https://ubp.onrender.com/openapi.json",
          "is_user_authenticated": False,
      },
      "logo_url": "https://ubp.onrender.com/logo.png",
      "contact_email": "support@lloyds-ubp.com",
      "legal_info_url": "https://ubp.onrender.com/legal",
  }


# --- Anthropic / Claude Plugin / MCP Manifest Endpoints ---
@app.get("/ai-plugin/anthropic/manifest.json")
async def anthropic_manifest():
  """Manifest declaration for Claude tool/MCP usage."""
  return {
      "protocol": "Model Context Protocol / UBP 2.0",
      "server_name": "lloyds-bank-ubp-gateway",
      "endpoints": {"dispatch": "https://ubp.onrender.com/ubp/v1/tunnel/dispatch"},
  }


# --- Core UBP Tunnel Dispatcher ---
@app.post("/ubp/v1/tunnel/dispatch")
async def dispatch_to_bank(payload: UserQueryPayload):
  """Receives requests from ChatGPT or Claude plugins, wraps them in UBP

  envelopes, and proxies them directly to the bank agent backend.
  """
  print(
      f"\n[UBP Gateway] Intercepted request from AI Client for customer:"
      f" {payload.customer_id}"
  )

  # Construct standardized Universal Banking Protocol (UBP) Envelope
  ubp_envelope = {
      "ubp_version": "2.0-secure",
      "timestamp": datetime.utcnow().isoformat(),
      "origin_client": "AI-Assistant-Plugin (ChatGPT/Claude)",
      "payload": {
          "customer_id": payload.customer_id,
          "workflow_type": payload.workflow_type,
          "query": payload.query,
          "parameters": payload.parameters,
      },
  }

  async with httpx.AsyncClient() as client:
    try:
      # Forward securely to your deployed Bank Agent
      print(f"[UBP Gateway] Tunneling request to: {BANK_AGENT_URL}")
      bank_response = await client.post(
          BANK_AGENT_URL, json=ubp_envelope["payload"], timeout=20.0
      )

      if bank_response.status_code != 200:
        raise HTTPException(
            status_code=bank_response.status_code,
            detail=(
                "Bank Agent rejected UBP packet:"
                f" {bank_response.text}"
            ),
        )

      bank_data = bank_response.json()

    except httpx.RequestError as exc:
      raise HTTPException(
          status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
          detail=(
              "UBP Tunnel Error: Could not reach Bank Agent backend"
              f" ({str(exc)})"
          ),
      )

  # Return response formatted for the AI Assistant's context window
  return {
      "status": "SUCCESS",
      "protocol": "UBP/2.0",
      "bank_agent_response": bank_data,
  }


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("ubp_gateway:app", host="0.0.0.0", port=8000, reload=True)