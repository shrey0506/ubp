from datetime import datetime
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP

# Initialize FastAPI app for standard web endpoints and UI
app = FastAPI(
    title="Universal Banking Protocol (UBP) MCP Gateway",
    version="4.0.0",
    description="Native MCP SSE Server routing requests to Lloyds Bank Agent.",
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

# Initialize FastMCP Server
mcp = FastMCP("Lloyds-Bank-UBP-Gateway")


# Define the tool that MCP clients (ChatGPT / Claude) can natively discover & call
@mcp.tool()
async def lloyds_bank_workflow(
    customer_id: str,
    workflow_type: str,
    query: str,
    parameters: dict = {},
) -> str:
  """Executes a Lloyds Bank workflow (Mortgage profit-maximization or Subscription/Sky analysis)

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


@app.get("/")
async def root():
  return {
      "status": "Online",
      "protocol": "MCP over SSE",
      "target_agent": BANK_AGENT_URL,
  }


# Mount the native FastMCP SSE application onto FastAPI
# This automatically handles /sse and /messages/ routes required by MCP clients
mcp_asgi_app = mcp._sse_app() if hasattr(mcp, "_sse_app") else mcp.sse_app()
app.mount("/", mcp_asgi_app)


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("ub:app", host="0.0.0.0", port=8000, reload=True)
