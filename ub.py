import contextlib

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# Target deployed Bank Agent URL
BANK_AGENT_URL = "https://ubp-bank-agent.onrender.com/ubp/v1/agent"

# Initialize FastMCP Server.
# transport_security is set on the constructor (mcp 1.x API) --
# without allowed_hosts matching your real Render hostname, every
# production request gets rejected with 421 "Invalid Host header"
# because the SDK defaults to localhost-only DNS-rebinding protection.
mcp = FastMCP(
    "Lloyds-Bank-UBP-Gateway",
    transport_security=TransportSecuritySettings(
        allowed_hosts=["ubp-gateway.onrender.com"],
        allowed_origins=["https://ubp-gateway.onrender.com"],
    ),
)


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


# Build the Streamable HTTP ASGI app -- reads transport_security
# from the FastMCP instance above, no args needed here.
mcp_asgi_app = mcp.streamable_http_app()


# FastAPI does NOT auto-run a mounted sub-app's lifespan.
# Without this, the MCP session manager's task group never starts,
# and every request fails with "Task group is not initialized."
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


# Initialize FastAPI app for standard web endpoints and UI
app = FastAPI(
    title="Universal Banking Protocol (UBP) MCP Gateway",
    version="4.1.0",
    description="Streamable HTTP MCP Server routing requests to Lloyds Bank Agent.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "status": "Online",
        "protocol": "MCP Streamable HTTP",
        "target_agent": BANK_AGENT_URL,
    }


# FastMCP's streamable_http_app() internally serves at /mcp,
# so mounting at "/" exposes it at https://your-host/mcp
app.mount("/", mcp_asgi_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("ub:app", host="0.0.0.0", port=8000, reload=True)
