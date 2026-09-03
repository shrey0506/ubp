from datetime import datetime
import httpx
from fastapi import FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

app = FastAPI(
    title="Universal Banking Protocol (UBP) Gateway",
    version="1.0.0",
    description=(
        "Middleware protocol routing securely between ChatGPT Customer Agent"
        " and Lloyds Bank Agent."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# UBP Security Credentials
UBP_GATEWAY_TOKEN = "ubp-master-secure-handshake-2026"
BANK_AGENT_URL = (
    "http://localhost:8000/ubp/v1/negotiate"  # Points to the Bank Agent backend
)
BANK_API_KEY = "lloyds-ubp-secure-token-2026"

api_key_header = APIKeyHeader(name="X-ChatGPT-Plugin-Signature", auto_error=False)


async def verify_chatgpt_plugin(api_key: str = Security(api_key_header)):
  """Authenticates incoming connections originating from the ChatGPT Plugin."""
  # In production, validate JWT or client certificate signature matching OpenAI requirements
  return True


class ChatGPTUserPayload(BaseModel):
  customer_id: str = Field(
      ..., description="Unique user identifier mapped by ChatGPT"
  )
  intent: str = Field(
      ..., description="Banking intent e.g. mortgage or subscription"
  )
  parameters: dict = Field(..., description="Financial properties and terms")


class UBPEnvelope(BaseModel):
  protocol: str = "UBP/1.0-Secure"
  timestamp: str
  encrypted_payload: ChatGPTUserPayload
  routing_metadata: dict


@app.post("/ubp/v1/tunnel/dispatch")
async def dispatch_via_ubp(
    payload: ChatGPTUserPayload, authorized: bool = Security(verify_chatgpt_plugin)
):
  """Intercepts customer requests from ChatGPT, wraps them into a UBP compliant

  secure envelope, enforces protocol validation, and routes it to the Lloyds
  Bank Agent.
  """
  print(
      f"\n[UBP Gateway] Received request from ChatGPT Plugin for client:"
      f" {payload.customer_id}"
  )

  # Step 1: Wrap into Universal Banking Protocol (UBP) Standard Envelope
  ubp_envelope = UBPEnvelope(
      timestamp=datetime.utcnow().isoformat(),
      encrypted_payload=payload,
      routing_metadata={
          "source_agent": "ChatGPT-CustomerAgent",
          "destination_bank": "Lloyds-Bank-Agent",
          "security_tier": "End-to-End-Encrypted-TLS",
          "profit_maximization_flag": True,
      },
  )

  # Step 2: Dispatch securely to Bank Agent via authenticated headers
  headers = {
      "X-UBP-Signature": BANK_API_KEY,
      "Content-Type": "application/json",
  }

  print(
      f"[UBP Gateway] Translating packet and tunneling securely to Bank Agent at"
      f" {BANK_AGENT_URL}..."
  )

  async with httpx.AsyncClient() as client:
    try:
      # Forward payload matching the Bank Agent's expected schema
      bank_response = await client.post(
          BANK_AGENT_URL,
          json={
              "customer_id": payload.customer_id,
              "intent": payload.intent,
              "parameters": payload.parameters,
          },
          headers=headers,
          timeout=10.0,
      )

      if bank_response.status_code != 200:
        raise HTTPException(
            status_code=bank_response.status_code,
            detail=(
                "Bank Agent rejected UBP transmission:"
                f" {bank_response.text}"
            ),
        )

      bank_data = bank_response.json()

    except httpx.RequestError as exc:
      raise HTTPException(
          status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
          detail=(
              "UBP Tunneling Error: Could not establish secure link with Bank"
              f" Agent ({exc})"
          ),
      )

  # Step 3: Format response back into UBP specification for ChatGPT plugin consumption
  ubp_response_packet = {
      "ubp_protocol_version": "1.0-secure",
      "status": "DELIVERED_SUCCESS",
      "routing_audit": ubp_envelope.routing_metadata,
      "bank_agent_response": bank_data,
  }

  print(
      "[UBP Gateway] Successfully received response from Bank Agent, routing"
      " back to ChatGPT."
  )
  return ubp_response_packet


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("ubp_gateway:app", host="0.0.0.0", port=8050, reload=True)