import uvicorn
import json
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# --- NEW IMPORTS FOR CORS ---
from fastapi.middleware.cors import CORSMiddleware
# --------------------------

import os  # <-- NEW IMPORT
from pathlib import Path
from fastapi.staticfiles import StaticFiles  # <-- NEW IMPORT
import traceback

# Import the compiled graph from your agent file
from agent_langgraph import graph, AppState

# RAG imports for ask mode
from retrieval import Retriever
from rag import RAGPipeline

# --- NEW IMPORTS FOR DB AND SUMMARIZER ---
from database import db_manager
from summarizer import generate_new_summary
# ---------------------------------------

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Educational Agent API",
    description="API for running the LangGraph-based educational task agent.",
    version="1.0.0"
)

# --- NEW CORS CONFIGURATION ---
# This allows your frontend (e.g., http://localhost:3000)
# to make requests to your backend (http://localhost:8000)
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
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
    """The request model for starting an agent task or simple ask mode."""
    user_query: str
    user_id: str
    mode: str | None = "agent"  # "agent" or "ask"
    chat_id: str | None = None  # client-generated chat identifier

# --- NEW PYDANTIC MODELS FOR USER DATA ---
class ChatHistoryRequest(BaseModel):
    user_id: str
    chat_id: str
    messages: list[dict] # e.g., [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi!"}]

class FeedbackRequest(BaseModel):
    user_id: str
    feedback_text: str

class UserDataResponse(BaseModel):
    user_id: str
    data: list | dict | str | None

class SummaryResponse(BaseModel):
    user_id: str
    summary_type: str
    summary: str | None
    chat_id: str | None = None
# -----------------------------------------

class FinalResponse(BaseModel):
    """The response model for the standard invoke endpoint."""
    final_state: dict

class SignupRequest(BaseModel):
    username: str
    email: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

# --- Streaming Endpoint (for Frontend) ---

async def stream_graph_events(user_query: str, user_id: str, chat_id: str | None):
    """
    Runs the graph in a streaming fashion and yields Server-Sent Events (SSE).
    NOW ALSO SAVES THE FINAL CONVERSATION TO THE DB.
    """
    
    print(f"Fetching context for user: {user_id}")
    chat_summary = db_manager.get_summary(user_id, "chat", chat_id=chat_id) if chat_id else None
    feedback_summary = db_manager.get_summary(user_id, "feedback")
    user_email = db_manager.get_user_email(user_id)

    initial_state: AppState = {
        "user_query": user_query,
        "user_id": user_id,
        "chat_summary": chat_summary,
        "feedback_summary": feedback_summary,
        "user_email": user_email,
        # ... (rest of initial_state) ...
        "task_type": None,
        "tasks": None,
        "email": None,
        "topic": None,
        "grade": None,
        "duration": None,
        "knowledge": None,
        "quiz": None,
        "report_content": None,
        "explanation": None,
        "pdf_content": None,
        "pdf_path": None,
        "pptx_path": None,
        "email_status": None,
    }
    
    # --- NEW: We need to capture the final agent response ---
    user_message = {"role": "user", "content": user_query}
    final_agent_output_chunks = []
    
    try:
        async for chunk in graph.astream(initial_state):
            node_name = list(chunk.keys())[0]
            node_output = chunk[node_name]
            event_data = {"node": node_name, "output": node_output}
            
            # --- NEW: Capture final outputs as they are generated ---
            if node_name == "generate_quiz" and node_output.get("quiz"):
                final_agent_output_chunks.append(node_output["quiz"])
            elif node_name == "generate_report" and node_output.get("report_content"):
                final_agent_output_chunks.append(node_output["report_content"])
            elif node_name == "generate_explanation" and node_output.get("explanation"):
                final_agent_output_chunks.append(node_output["explanation"])
            
            # Also capture file paths and email status
            if node_name == "generate_pdf" and node_output.get("pdf_path"):
                final_agent_output_chunks.append(f"PDF generated: [View Link]({node_output.get('pdf_path')})")
            if node_name == "generate_presentation" and node_output.get("pptx_path"):
                final_agent_output_chunks.append(f"Presentation generated: [View Link]({node_output.get('pptx_path')})")
            if node_name == "email" and node_output.get("email_status"):
                final_agent_output_chunks.append(f"Email status: {node_output.get('email_status')}")

            yield f"event: graph_update\ndata: {json.dumps(event_data)}\n\n"
        
        yield f"event: end\ndata: {{}}\n\n"

    except Exception as e:
        error_data = {"node": "error", "output": str(e)}
        print(f"❌ Error during graph stream: {e}\n{traceback.format_exc()}") # <-- Better logging
        yield f"event: error\ndata: {json.dumps(error_data)}\n\n"
    
    finally:
        # --- THIS IS THE FIX ---
        # After the stream is done, save the history
        if final_agent_output_chunks and chat_id:
            try:
                final_content = "\n\n".join(final_agent_output_chunks).strip()
                agent_message = {"role": "assistant", "content": final_content}
                messages_to_save = [user_message, agent_message]
                
                db_manager.add_chat_history(user_id, chat_id, messages_to_save)
                
                # Now update the summary
                previous_summary = db_manager.get_summary(user_id, "chat", chat_id=chat_id)
                new_summary = generate_new_summary(
                    summary_type="chat",
                    previous_summary=previous_summary,
                    new_data=messages_to_save,
                )
                db_manager.update_chat_summary(user_id, chat_id, "chat", new_summary)
                print(f"✅ [Server-Side Save] Saved AGENT chat and summary for {user_id} in {chat_id}")
            except Exception as db_e:
                print(f"❌ [Server-Side Save] Failed to save AGENT chat history: {db_e}")

def _get_rag_pipeline() -> RAGPipeline:
    """Singleton accessor for RAGPipeline with proper Retriever initialization."""
    global _rag_pipeline
    if _rag_pipeline is None:
        print("[ask-mode] Initializing retriever & RAG pipeline...")
        # Use defaults from retrieval.Retriever which pull from env, else fallback constants
        retriever = Retriever(
            es_host=os.getenv("ES_HOST", "http://localhost:9200"),
            index_name=os.getenv("ES_INDEX", "periodic-table-hybrid-search"),
            model_name=os.getenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5"),
            max_length=int(os.getenv("EMBED_MAX_LEN", "512")),
            reranker_name=os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base"),
            log_dir=Path(os.getenv("LOG_DIR", "logs"))
        )
        _rag_pipeline = RAGPipeline(retriever=retriever)
    return _rag_pipeline

@app.post("/execute_stream")
async def execute_stream(request: TaskRequest):
    """Execute either agent workflow (graph) or simple ask mode using RAG, streaming SSE."""
    if request.mode == "ask":
        # --- NEW: Define these here to use in 'finally' block ---
        answer = ""
        sources = []
        
        async def ask_stream():
            nonlocal answer, sources # <-- Allow modification
            yield f"event: ask_status\ndata: {json.dumps({'stage':'init','message':'Initializing RAG pipeline'})}\n\n"
            try:
                pipeline = _get_rag_pipeline()
                yield f"event: ask_status\ndata: {json.dumps({'stage':'retrieval','message':'Retrieving context & generating answer'})}\n\n"
                answer, sources = pipeline.generate_answer(query=request.user_query)
                yield f"event: ask_status\ndata: {json.dumps({'stage':'stream','message':'Streaming answer'})}\n\n"
                sentences = [s.strip() for s in answer.split('.') if s.strip()]
                for idx, sent in enumerate(sentences):
                    payload = {"chunk_index": idx, "content": sent + '.'}
                    yield f"event: ask_update\ndata: {json.dumps(payload)}\n\n"
                yield f"event: ask_sources\ndata: {json.dumps({'sources': sources})}\n\n"
                yield f"event: end\ndata: {{}}\n\n"
            except Exception as e:
                print(f"❌ Error during ask stream: {e}\n{traceback.format_exc()}") # <-- Better logging
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            
            finally:
                # --- THIS IS THE FIX FOR ASK MODE ---
                if answer and request.chat_id:
                    try:
                        user_message = {"role": "user", "content": request.user_query}
                        agent_message = {"role": "assistant", "content": f"{answer}\n\nSources: {', '.join(sources)}"}
                        messages_to_save = [user_message, agent_message]
                        
                        db_manager.add_chat_history(request.user_id, request.chat_id, messages_to_save)
                        
                        previous_summary = db_manager.get_summary(request.user_id, "chat", chat_id=request.chat_id)
                        new_summary = generate_new_summary(
                            summary_type="chat",
                            previous_summary=previous_summary,
                            new_data=messages_to_save,
                        )
                        db_manager.update_chat_summary(request.user_id, request.chat_id, "chat", new_summary)
                        print(f"✅ [Server-Side Save] Saved ASK chat and summary for {request.user_id} in {request.chat_id}")
                    except Exception as db_e:
                        print(f"❌ [Server-Side Save] Failed to save ASK chat history: {db_e}")

        return StreamingResponse(ask_stream(), media_type="text/event-stream")
    
    # Agent mode
    return StreamingResponse(
        stream_graph_events(request.user_query, request.user_id, request.chat_id),
        media_type="text/event-stream"
    )

# --- Standard Invoke Endpoint (for Testing) ---

@app.post("/execute_invoke", response_model=FinalResponse)
async def execute_invoke(request: TaskRequest):
    """
    Execute the agent task, wait for it to complete, and return the final state.
    
    This is useful for testing or for requests that don't need streaming.
    """
    # --- NEW: Fetch summaries ---
    print(f"Fetching context for user: {request.user_id}")
    chat_summary = db_manager.get_summary(request.user_id, "chat", chat_id=request.chat_id) if request.chat_id else None
    feedback_summary = db_manager.get_summary(request.user_id, "feedback")
    user_email = db_manager.get_user_email(request.user_id)

    initial_state: AppState = {
        "user_query": request.user_query,
        "user_id": request.user_id,
        "chat_summary": chat_summary,
        "feedback_summary": feedback_summary,
        "user_email": user_email,
        
        # --- Set defaults for other keys ---
        "task_type": None,
        "tasks": None,
        "email": None,
        "topic": None,
        "grade": None,
        "duration": None,
        "knowledge": None,
        "quiz": None,
        "report_content": None,
        "explanation": None,
        "pdf_content": None,
        "pdf_path": None,
        "pptx_path": None,
        "email_status": None,
    }
    
    if request.mode == "ask":
        # Non-streaming simple answer
        global _rag_pipeline
        pipeline = _get_rag_pipeline()
        answer, sources = pipeline.generate_answer(query=request.user_query)
        return {"final_state": {"mode": "ask", "answer": answer, "sources": sources}}
    final_state = graph.invoke(initial_state)
    return {"final_state": final_state}


# --- NEW ENDPOINTS FOR CHAT HISTORY AND FEEDBACK ---

@app.post("/add_chat_history", status_code=201)
async def add_chat_history(request: ChatHistoryRequest):
    """
    Adds a user's chat history.
    This is now a fallback, as server saves history itself.
    But it's still useful for the client to trigger a summary update.
    """
    try:
        # We still add the history from the client, just in case.
        # The database (chat_id, user_id, content) should handle duplicates if we design it that way
        # But for now, let's just use this to trigger a summary.
        
        # 1. Get recent history (which server-side save just added)
        recent_history = db_manager.get_recent_history(request.user_id, chat_id=request.chat_id, limit=50)
        if not recent_history:
             # If server-side save failed, add the client's version
             db_manager.add_chat_history(request.user_id, request.chat_id, request.messages)
             recent_history = request.messages

        previous_summary = db_manager.get_summary(request.user_id, "chat", chat_id=request.chat_id)
        
        new_summary = generate_new_summary(
            summary_type="chat",
            previous_summary=previous_summary,
            new_data=recent_history, # Use the most up-to-date history
        )
        db_manager.update_chat_summary(request.user_id, request.chat_id, "chat", new_summary)
        return {"status": "success", "message": f"Chat history and summary updated for user {request.user_id}."}
    except Exception as e:
        print(f"❌ Error in /add_chat_history: {e}\n{traceback.format_exc()}") # <-- Better logging
        return {"status": "error", "message": str(e)}

@app.post("/add_feedback", status_code=201)
async def add_feedback(request: FeedbackRequest):
    """
    Adds user feedback to the database and updates the feedback summary.
    """
    try:
        # 1. Add new feedback
        db_manager.add_feedback(request.user_id, request.feedback_text)

        # 2. Get existing summary and recent feedback
        previous_summary = db_manager.get_summary(request.user_id, "feedback")
        recent_feedback = db_manager.get_recent_feedback(request.user_id, limit=20)

        # 3. Generate new summary
        new_summary = generate_new_summary(
            summary_type="feedback",
            previous_summary=previous_summary,
            new_data=recent_feedback,
        )

        # 4. Update summary in DB
        db_manager.update_summary(request.user_id, "feedback", new_summary)

        return {"status": "success", "message": f"Feedback and summary updated for user {request.user_id}."}
    except Exception as e:
        print(f"❌ Error in /add_feedback: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/get_chat_history/{user_id}", response_model=UserDataResponse)
async def get_chat_history(user_id: str, chat_id: str | None = None, limit: int = 20):
    """Retrieves recent chat history for a given user (optionally by chat_id)."""
    history = db_manager.get_recent_history(user_id, chat_id=chat_id, limit=limit)
    return {"user_id": user_id, "data": history}

@app.get("/get_feedback/{user_id}", response_model=UserDataResponse)
async def get_feedback(user_id: str, limit: int = 20):
    """Retrieves recent feedback for a given user."""
    feedback = db_manager.get_recent_feedback(user_id, limit=limit)
    return {"user_id": user_id, "data": feedback}

@app.get("/get_summary/{user_id}/{summary_type}", response_model=SummaryResponse)
async def get_summary(user_id: str, summary_type: str, chat_id: str | None = None):
    """Retrieves the latest summary of a specific type for a user; chat summaries require chat_id."""
    summary = db_manager.get_summary(user_id, summary_type, chat_id=chat_id)
    return {"user_id": user_id, "summary_type": summary_type, "summary": summary, "chat_id": chat_id}

# ===== USER AUTH / SIGNUP =====
@app.post("/signup", status_code=201)
async def signup(request: SignupRequest):
    try:
        if not request.username or not request.email or not request.password:
            return {"status": "error", "message": "All fields required"}
        db_manager.add_user(request.username, request.email, request.password)
        return {"status": "success", "message": f"User {request.username} created."}
    except ValueError as ve:
        return {"status": "error", "message": str(ve)}
    except Exception as e:
        return {"status": "error", "message": f"Signup failed: {e}"}

@app.post("/login")
async def login(request: LoginRequest):
    try:
        if db_manager.validate_user(request.username, request.password):
            email = db_manager.get_user_email(request.username)
            return {"status": "success", "username": request.username, "email": email}
        return {"status": "error", "message": "Invalid credentials"}
    except Exception as e:
        return {"status": "error", "message": f"Login failed: {e}"}

@app.get("/get_chat_list/{user_id}", response_model=UserDataResponse)
async def get_chat_list(user_id: str):
    """Retrieves the list of all chats (id, title, timestamp) for a user."""
    try:
        # Assumes db_manager has a function to get all chat metadata
        chat_list = db_manager.get_chat_list(user_id) 
        return {"user_id": user_id, "data": chat_list}
    except Exception as e:
        print(f"❌ Error in /get_chat_list: {e}")
        return {"user_id": user_id, "data": []}

@app.delete("/delete_chat/{user_id}/{chat_id}", status_code=200)
async def delete_chat(user_id: str, chat_id: str):
    """Deletes a specific chat and its summary from the database."""
    try:
        # Assumes db_manager has a function to delete a chat
        db_manager.delete_chat(user_id, chat_id) 
        return {"status": "success", "message": f"Chat {chat_id} deleted."}
    except Exception as e:
        print(f"❌ Error in /delete_chat: {e}")
        return {"status": "error", "message": str(e)}
# Global RAG pipeline holder
_rag_pipeline = None

# ----------------------------------------------------

# --- Run the Server ---
if __name__ == "__main__":
    print("🚀 Starting FastAPI server on http://127.0.0.1:8000")
    # Note: Use 127.0.0.1 instead of 0.0.0.0 for explicit matching
    # with the CORS origins if you face issues.
    uvicorn.run(app, host="127.0.0.1", port=8000)