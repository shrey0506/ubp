from datetime import datetime
import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# Initialize FastAPI app
app = FastAPI(
    title="Universal Banking Protocol (UBP) MCP Gateway",
    version="3.0.0",
    description=(
        "Model Context Protocol (MCP) Server and Gateway routing requests to"
        " Lloyds Bank Agent."
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

# Initialize FastMCP server instance
mcp = FastMCP("Lloyds-Bank-UBP-Server")


# Define the MCP Tool wrapper that ChatGPT / Claude can discover and execute
@mcp.tool()
async def lloyds_bank_workflow(
    customer_id: str,
    workflow_type: str,
    query: str,
    parameters: dict = {},
) -> str:
  """Executes a Lloyds Bank workflow (Mortgage profit-maximization or Subscription ledger/Sky check)

  via the Universal Banking Protocol (UBP).
  """
  payload = {
      "customer_id": customer_id,
      "workflow_type": workflow_type,
      "query": query,
      "parameters": parameters,
  }

  async with httpx.AsyncClient() as client:
    try:
      response = await client.post(BANK_AGENT_URL, json=payload, timeout=30.0)
      if response.status_code != 200:
        return f"Error from Bank Agent: {response.text}"

      data = response.json()
      return str(data.get("agent_response", data))
    except Exception as e:
      return f"MCP Gateway Connection Error: {str(e)}"


# Mount the FastMCP SSE application handlers directly onto FastAPI
from starlette.applications import Starlette
from starlette.routing import Mount

# Get the native MCP SSE app and mount it
mcp_app = mcp._sse_app()
app.mount("/", mcp_app)


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("ubp:app", host="0.0.0.0", port=8000, reload=True)
