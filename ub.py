import contextlib
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP

BANK_AGENT_URL = "https://ubp-bank-agent.onrender.com/ubp/v1/agent"

# Initialize FastMCP Server (unchanged)
mcp = FastMCP("Lloyds-Bank-UBP-Gateway")

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

# Build the Streamable HTTP ASGI app (NOT sse_app)
mcp_asgi_app = mcp.streamable_http_app()

# FastAPI does NOT auto-run a mounted sub-app's lifespan.
# Without this, the session manager's task group never starts.
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield

app = FastAPI(
    title="Universal Banking Protocol (UBP) MCP Gateway",
    version="4.1.0",
    description="Streamable HTTP MCP Server routing requests to Lloyds Bank Agent.",
    lifespan=lifespan,   # <-- critical
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
