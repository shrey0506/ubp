from datetime import datetime
import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="Universal Banking Protocol (UBP) Gateway",
    version="3.1.0",
    description=(
        "Universal Banking Protocol (UBP) Gateway routing requests to Lloyds"
        " Bank Agent."
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


@app.get("/")
async def root():
  return {
      "status": "Online",
      "service": "UBP Gateway",
      "target_agent": BANK_AGENT_URL,
  }


@app.post(
    "/ubp/v1/tunnel/dispatch",
    operation_id="dispatch_ubp_banking_request",
    summary="Dispatch request via UBP tunnel to Bank Agent",
)
async def dispatch_to_bank(payload: UserQueryPayload):
  """Receives requests from AI plugins, wraps them in UBP envelopes, and

  proxies them directly to the bank agent backend.
  """
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
      bank_response = await client.post(
          BANK_AGENT_URL, json=ubp_envelope["payload"], timeout=25.0
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

  return {
      "status": "SUCCESS",
      "protocol": "UBP/2.0",
      "bank_agent_response": bank_data,
  }


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("ub:app", host="0.0.0.0", port=8000, reload=True)
