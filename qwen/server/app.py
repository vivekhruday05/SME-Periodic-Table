import uvicorn
import json
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime

# --- NEW IMPORTS FOR CORS ---
from fastapi.middleware.cors import CORSMiddleware
# --------------------------

import os  # <-- NEW IMPORT
from fastapi.staticfiles import StaticFiles  # <-- NEW IMPORT

# Import the compiled graph from your agent file
from agent_langgraph import graph, AppState

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Educational Agent API",
    description="API for running the LangGraph-based educational task agent.",
    version="1.0.0"
)

# --- NEW CORS CONFIGURATION ---
# This allows your frontend (e.g., http://localhost:3000 or 3001)
# to make requests to your backend (http://localhost:8000)
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)
# ------------------------------
# --- NEW: MOUNT STATIC FILES DIRECTORY ---
# This makes files in ../generated_documents available at http://.../files/filename.pdf
try:
    # Get the directory where app.py lives (server/)
    app_dir = os.path.dirname(os.path.abspath(__file__))
    # Go one level up (root/) and then into generated_documents/
    static_dir = os.path.abspath(os.path.join(app_dir, "..", "generated_documents"))
    
    # Create the directory if it doesn't exist
    os.makedirs(static_dir, exist_ok=True)
    
    # Mount this directory to the /files URL path
    app.mount("/files", StaticFiles(directory=static_dir), name="files")
    print(f"✅ Serving static files from: {static_dir}")
    print(f"✅ Access files at: http://127.0.0.1:8000/files/<filename>")
except Exception as e:
    print(f"❌ Failed to mount static directory: {e}")
# --- Pydantic Models ---
class TaskRequest(BaseModel):
    """The request model for starting an agent task."""
    user_query: str
    mode: str = "agent"  # Add mode parameter

class FinalResponse(BaseModel):
    """The response model for the standard invoke endpoint."""
    final_state: dict

class LoginRequest(BaseModel):
    """Request model for login endpoint."""
    email: str
    password: str

class LoginResponse(BaseModel):
    """Response model for login endpoint."""
    success: bool
    message: str
    user: dict = None

# --- Root Endpoint ---

@app.get("/")
async def root():
    """
    Root endpoint for health check and API info.
    """
    return {
        "message": "Educational Agent API is running",
        "docs": "http://127.0.0.1:8000/docs",
        "endpoints": {
            "stream": "/execute_stream (POST)",
            "invoke": "/execute_invoke (POST)",
            "files": "/files/ (GET)"
        }
    }

@app.get("/health")
async def health():
    """
    Health check endpoint.
    """
    return {"status": "healthy"}

# --- Authentication Endpoints ---

@app.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Simple login endpoint - validates email and password format.
    In production, this should authenticate against a real database.
    """
    if not request.email or not request.password:
        return LoginResponse(success=False, message="Email and password are required")
    
    if "@" not in request.email:
        return LoginResponse(success=False, message="Invalid email format")
    
    if len(request.password) < 6:
        return LoginResponse(success=False, message="Password must be at least 6 characters")
    
    # In production, validate against a real database
    user = {
        "email": request.email,
        "loginTime": datetime.now().isoformat()
    }
    
    return LoginResponse(
        success=True,
        message="Login successful",
        user=user
    )

@app.post("/logout")
async def logout():
    """
    Logout endpoint - placeholder for session cleanup.
    """
    return {"status": "logged_out", "message": "Successfully logged out"}

# --- Streaming Endpoint (for Frontend) ---

async def stream_graph_events(user_query: str, mode: str = "agent"):
    """
    Runs the graph in a streaming fashion and yields Server-Sent Events (SSE).
    The mode parameter can be 'agent' for full capabilities or 'ask' for simple Q&A.
    """
    # Define the initial state
    initial_state = {"user_query": user_query}
    
    try:
        # graph.stream() returns an iterator of the state *after* each node
        async for chunk in graph.astream(initial_state):
            # Each chunk is a dictionary with the node name as the key
            # e.g., {"extract": {"task_type": "quiz", ...}}
            
            # Get the node name that just ran
            node_name = list(chunk.keys())[0]
            node_output = chunk[node_name]
            
            # Format as a Server-Sent Event (SSE)
            # The frontend can listen for "graph_update" events
            event_data = {
                "node": node_name,
                "output": node_output,
                "mode": mode
            }
            # The 'data' field must be a single line.
            # We send the JSON string.
            yield f"event: graph_update\ndata: {json.dumps(event_data)}\n\n"

        # Signal the end of the stream
        yield f"event: end\ndata: {{}}\n\n"

    except Exception as e:
        # Send an error event
        error_data = {
            "node": "error",
            "output": str(e)
        }
        yield f"event: error\ndata: {json.dumps(error_data)}\n\n"


@app.post("/execute_stream")
async def execute_stream(request: TaskRequest):
    """
    Execute the agent task and stream the results back as Server-Sent Events.
    
    This is ideal for a frontend to show live updates.
    """
    return StreamingResponse(
        stream_graph_events(request.user_query, request.mode), 
        media_type="text/event-stream"
    )

# --- Standard Invoke Endpoint (for Testing) ---

@app.post("/execute_invoke", response_model=FinalResponse)
async def execute_invoke(request: TaskRequest):
    """
    Execute the agent task, wait for it to complete, and return the final state.
    
    This is useful for testing or for requests that don't need streaming.
    """
    initial_state = {"user_query": request.user_query}
    
    # graph.invoke() runs the entire graph and returns the final state
    final_state = graph.invoke(initial_state)
    
    return {"final_state": final_state}


# --- Run the Server ---
if __name__ == "__main__":
    print("🚀 Starting FastAPI server on http://127.0.0.1:8000")
    # Note: Use 127.0.0.1 instead of 0.0.0.0 for explicit matching
    # with the CORS origins if you face issues.
    uvicorn.run(app, host="127.0.0.1", port=8000)