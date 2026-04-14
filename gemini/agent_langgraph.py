import os
import re
import json
import logging
from textwrap import dedent
from typing import TypedDict, Optional, Literal, List

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_classic.schema import HumanMessage
from langgraph.graph import StateGraph, END

# --- IMPORTS ---
from multitools import (
    knowledge_retrieval,
    quiz_generator,
    pdf_generator,
    email_tool,
    report_generator,
    presentation_generator
)

# -------------------------------------------------------------------
# Logging Setup
# -------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("edu-langgraph")

# -------------------------------------------------------------------
# Environment and Gemini LLM Initialization
# -------------------------------------------------------------------
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("Missing GOOGLE_API_KEY in .env")

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    google_api_key=GOOGLE_API_KEY,
    response_mime_type="application/json"
)
logger.info("✅ Gemini LLM initialized successfully.")

# -------------------------------------------------------------------
# State Schema (MODIFIED FOR MULTI-TASK)
# -------------------------------------------------------------------
class AppState(TypedDict):
    user_query: str
    user_id: Optional[str]  # <-- NEW
    chat_summary: Optional[str] # <-- NEW
    feedback_summary: Optional[str] # <-- NEW
    user_email: Optional[str]  # <-- NEW: populated from users table for email tasks
    
    # Extracted fields
    task_type: Optional[Literal["quiz", "report", "presentation", "knowledge"]] # For legacy/primary task
    tasks: Optional[List[Literal["quiz", "report", "presentation", "knowledge", "explanation"]]] # NEW: Task queue
    email: Optional[str]
    topic: Optional[str]
    grade: Optional[str]
    duration: Optional[str]
    
    # Payload fields
    knowledge: Optional[str]
    quiz: Optional[str]
    report_content: Optional[str]
    explanation: Optional[str] # NEW: For explanation output
    
    # Content to be PDF'd (NOW ACCUMULATES)
    pdf_content: Optional[str] 
    
    # Final file paths
    pdf_path: Optional[str]
    pptx_path: Optional[str]
    
    # Status
    email_status: Optional[str]

def defer_task(state: AppState):
    """
    Moves the current task (tasks[0]) to the end of the queue.
    This is used when a task's dependencies (like 'report' for 'presentation')
    are in the queue but haven't run yet.
    """
    logger.info("⏳ Deferring task, moving to end of queue.")
    tasks = state.get("tasks", [])
    if tasks:
        deferred_task = tasks.pop(0) # Remove from front
        tasks.append(deferred_task)  # Add to back
    return {"tasks": tasks}

def inject_report_dependency(state: AppState):
    """
    Injects 'report' as a dependency and defers the current task.
    This is called when 'presentation' is requested but 'report' is not in the queue.
    """
    logger.info("Injecting 'report' task and deferring current task.")
    tasks = state.get("tasks", [])
    if tasks:
        # Defer the current task (e.g., 'presentation')
        deferred_task = tasks.pop(0) 
        # Inject 'report' as the new first task
        tasks.insert(0, "report") 
        # Add the deferred task back to the end
        tasks.append(deferred_task)
    return {"tasks": tasks}

# -------------------------------------------------------------------
# Utility — Clean and Format Text
# -------------------------------------------------------------------
def clean_llm_output(raw_text: str, title: str) -> str:
    """Cleans model reasoning and formats a neat output."""
    if not raw_text:
        return "No content generated."

    # Handle JSON string by parsing it
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            if parsed.get("status") == "success":
                raw_text = parsed.get("result", "")
            elif parsed.get("status") == "error":
                return f"Error generating content: {parsed.get('message')}"
            else:
                raw_text = json.dumps(parsed, ensure_ascii=False)
        else:
            raw_text = str(parsed)
    except json.JSONDecodeError:
        pass

    cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL)
    cleaned = re.sub(r"<.*?>", "", cleaned)
    cleaned = cleaned.strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)

    header = f"{title.upper()}: {title}\n" + ("=" * 40) + "\n\n"
    return header + cleaned

# -------------------------------------------------------------------
# Node 1 — Extract Task Details (MODIFIED FOR MULTI-TASK)
# -------------------------------------------------------------------
def llm_extractor(state: AppState):
    logger.info("🧠 Step 1: Extracting key details (with history/feedback context)...")

    # --- NEW: Build context strings ---
    chat_context = state.get('chat_summary') or "No previous chat summary available."
    feedback_context = state.get('feedback_summary') or "No previous feedback summary available."

    extraction_prompt = f"""
    You are a task detail extractor. You must consider the user's previous history and feedback
    to better understand their current request.

    **Previous Chat Summary:**
    {chat_context}

    **Previous Feedback Summary:**
    {feedback_context}

    ---
    **Current User Request:**
    {state['user_query']}
    ---
    
    {f"**User's Registered Email (if known):** {state.get('user_email')}" if state.get('user_email') else ""}
    ---

    Based on ALL the context above, extract key fields and ALL tasks requested.
    A user may request multiple tasks in one prompt (e.g. "Explain X and generate a quiz").
    
    Tasks you can identify: quiz, report, presentation, knowledge/explanation.
    If a field is not mentioned, return null for it.
    Return ONLY a valid JSON object with this schema:
    {{
      "tasks": ["quiz" | "report" | "presentation" | "knowledge" | "explanation"],
      "task_type": "quiz" | "report" | "presentation" | "knowledge" | null,
      "email": string | null,
      "topic": string | null,
      "grade": string | null,
      "duration": string | null
    }}

    Rules:
    - **Email Rule (Priority):** If the user mentions "email", "send", or "send me"
      (e.g., "...and send it to my email"), you MUST extract the email.
      - If they provide a specific address (e.g., "...to_bob@x.com"), set `email: "bob@x.com"`.
      - If they just say "email me" AND "User's Registered Email" is available, set `email` to that address.
      - If they say "email me" AND no registered email is available, set `email: null`.
    
    - **Context-First Rule:** If the "Current User Request" is vague (e.g., "Solve this," "Explain more," "Generate a quiz on that"), you MUST use the "Previous Chat Summary" to identify the main `topic`.
      (e.g., Summary says "quiz on periodic table", User says "Solve it" -> `topic: "periodic table"`)

    - **Explanation Rule:** If user asks a general question ("tell me about", "what is", "explain", "describe") about a subject, you MUST:
      1. Include "knowledge" in the `tasks` list.
      2. Extract the main subject as the `topic`.
      (e.g., "Explain periodic table" -> `tasks: ["knowledge"]`, `topic: "periodic table"`)
      
    - 'email' is NOT a task, it is a separate field. Do not add 'email' to the tasks list.
    - Normalize synonyms: explanation -> knowledge.
    """    
    response = llm.invoke([HumanMessage(content=extraction_prompt)])
    content = response.content.strip()

    try:
        if content.startswith("```json"):
            content = content[7:-3].strip()

        extracted_data = json.loads(content)

        tasks = extracted_data.get("tasks") or []
        normalized = []
        for t in tasks:
            if t == "explanation":
                t = "knowledge"
            if t not in normalized:
                normalized.append(t)

        extracted_data["tasks"] = normalized if normalized else None

        if not extracted_data.get("task_type") and normalized:
            primary = next((x for x in normalized if x in ["quiz", "report", "presentation"]), normalized[0])
            extracted_data["task_type"] = primary

        valid_keys = AppState.__annotations__.keys()
        filtered_data = {k: v for k, v in extracted_data.items() if k in valid_keys and v is not None}

        logger.info(f"🔍 Extracted fields: {filtered_data}")
        return filtered_data

    except json.JSONDecodeError:
        logger.error(f"❌ JSON parse failed for content: {content}")
        return {}
    except Exception as e:
        logger.error(f"❌ Error in extractor: {e}")
        return {}


# -------------------------------------------------------------------
# Node 2 — Knowledge Retrieval
# -------------------------------------------------------------------
def retrieve_knowledge(state: AppState):
    logger.info("📚 Step 2: Running knowledge retrieval...")
    try:
        topic_query = state.get("topic")
        result_data = knowledge_retrieval.invoke({"query": topic_query})
        
        if result_data.get("status") == "success":
            logger.info(f"✅ Knowledge retrieved for: {topic_query}")
            return {"knowledge": result_data.get("result")}
        else:
            logger.error(f"❌ Retrieval error: {result_data.get('message')}")
            return {"knowledge": f"Retrieval failed: {result_data.get('message')}"}
    except Exception as e:
        logger.error(f"❌ Retrieval exception: {e}")
        return {"knowledge": f"Retrieval failed: {e}"}

# -------------------------------------------------------------------
# Node 3a — Quiz Generation (MODIFIED)
# -------------------------------------------------------------------
def generate_quiz(state: AppState):
    logger.info("🧩 Step 3a: Generating quiz...")
    constraints = f"{state.get('grade', '8th grade')}, {state.get('duration', '20 minutes')}"
    try:
        quiz_json = quiz_generator.invoke({
            "context": str(state["knowledge"]),
            "constraints": constraints
        })
        quiz_content = clean_llm_output(quiz_json, state.get("topic", "Quiz"))
        
        # --- MODIFICATION: Accumulate PDF content ---
        current_pdf_content = state.get("pdf_content") or ""
        return {
            "quiz": quiz_content, 
            "pdf_content": current_pdf_content + "\n\n" + quiz_content
        }
    except Exception as e:
        logger.error(f"❌ Quiz generation error: {e}")
        return {"quiz": f"Quiz generation failed: {e}"}

# -------------------------------------------------------------------
# Node 3b — Report Generation (MODIFIED)
# -------------------------------------------------------------------
def generate_report(state: AppState):
    logger.info("📄 Step 3b: Generating report...")
    try:
        report_json = report_generator.invoke({
            "context": str(state["knowledge"]),
            "topic": str(state["topic"])
        })
        report_content = clean_llm_output(report_json, state.get("topic", "Report"))
        
        # --- MODIFICATION: Accumulate PDF content ---
        current_pdf_content = state.get("pdf_content") or ""
        return {
            "report_content": report_content, 
            "pdf_content": current_pdf_content + "\n\n" + report_content
        }
    except Exception as e:
        logger.error(f"❌ Report generation error: {e}")
        return {"report_content": f"Report generation failed: {e}"}

# -------------------------------------------------------------------
# Node 3c — Explanation Generation (NEW)
# -------------------------------------------------------------------
def generate_explanation(state: AppState):
    logger.info("🗣️ Generating explanatory summary from knowledge...")
    try:
        knowledge = state.get("knowledge")
        topic = state.get("topic", "Topic")
        if not knowledge:
            logger.warning("⚠️ No knowledge context available for explanation.")
            return {"explanation": "No knowledge context to explain."}
        
        expl_prompt = dedent(f"""
        You are an educational explainer. Produce a clear, student-friendly explanation of the topic below.
        Topic: {topic}
        Knowledge Context (raw retrieved chunks):
        {knowledge[:6000]}

        Requirements:
        - Begin with a concise overview.
        - Then use short sections with clear headings.
        - Use plain language and define any key terms.
        - Finish with 3 quick recap bullet points.
        Return only the explanation text (no JSON).
        """)
        resp = llm.invoke([HumanMessage(content=expl_prompt)])
        explanation_raw = resp.content.strip()
        explanation_clean = clean_llm_output(explanation_raw, f"Explanation: {topic}")

        # --- MODIFICATION: Accumulate PDF content ---
        current_pdf_content = state.get("pdf_content") or ""
        return {
            "explanation": explanation_clean,
            "pdf_content": current_pdf_content + "\n\n" + explanation_clean
        }
    except Exception as e:
        logger.error(f"❌ Explanation generation error: {e}")
        return {"explanation": f"Explanation generation failed: {e}"}

# -------------------------------------------------------------------
# Node 4a — PDF Generation (Unmodified)
# -------------------------------------------------------------------
def generate_pdf(state: AppState):
    logger.info("📝 Step 4a: Generating PDF...")
    try:
        content_to_pdf = state.get("pdf_content")
        if not content_to_pdf or content_to_pdf.strip() == "":
            logger.warning("⚠️ No content found to generate PDF. Skipping.")
            return {}
            
        topic_name = re.sub(r'[^a-zA-Z0-9]', '_', state.get('topic', 'document'))
        filename = f"{topic_name}_multi_document.pdf"

        pdf_result = pdf_generator.invoke({
            "content": content_to_pdf,
            "filename": filename,
            "title": state.get("topic", "Generated Document")
        })

        if pdf_result.get("status") == "success":
            pdf_path = pdf_result.get("result")
            logger.info(f"✅ PDF generation completed: {pdf_path}")
            return {"pdf_path": pdf_path}
        else:
            logger.error(f"❌ PDF generation failed: {pdf_result.get('message')}")
            return {"pdf_path": f"PDF generation failed: {pdf_result.get('message')}"}
            
    except Exception as e:
        logger.error(f"❌ PDF generation error: {e}", exc_info=True)
        return {"pdf_path": f"PDF generation failed: {e}"}

# -------------------------------------------------------------------
# Node 4b — Presentation Generation (Unmodified)
# -------------------------------------------------------------------
def generate_presentation(state: AppState):
    logger.info("🖥️ Step 4b: Generating Presentation...")
    try:
        content_for_ppt = state.get("report_content") # Use report for slides
        if not content_for_ppt:
            logger.warning("⚠️ No report content found for presentation. Using knowledge.")
            content_for_ppt = state.get("knowledge", "No content available.")
            
        topic_name = re.sub(r'[^a-zA-Z0-9]', '_', state.get('topic', 'document'))
        filename = f"{topic_name}_presentation.pptx"

        pptx_result = presentation_generator.invoke({
            "content": content_for_ppt,
            "filename": filename,
            "topic": state.get("topic", "Generated Presentation")
        })
        
        pptx_result = json.loads(pptx_result) # Tool returns JSON string

        if pptx_result.get("status") == "success":
            pptx_path = pptx_result.get("result")
            logger.info(f"✅ Presentation generation completed: {pptx_path}")
            return {"pptx_path": pptx_path}
        else:
            logger.error(f"❌ PPTX generation failed: {pptx_result.get('message')}")
            return {"pptx_path": f"PPTX generation failed: {pptx_result.get('message')}"}
            
    except Exception as e:
        logger.error(f"❌ PPTX generation error: {e}", exc_info=True)
        return {"pptx_path": f"PPTX generation failed: {e}"}

# -------------------------------------------------------------------
# Node 5 — Send Email (Unmodified)
# -------------------------------------------------------------------
def send_email(state: AppState):
    logger.info("📨 Step 5: Sending email...")
    email = state.get("email")
    if not email:
        logger.error("❌ Email node called but no email in state.")
        return {"email_status": "error: no email provided"}

    # --- Collect all available attachments ---
    attachments = []
    pdf_path = state.get("pdf_path")
    pptx_path = state.get("pptx_path")
    
    if pdf_path and os.path.exists(pdf_path):
        attachments.append(pdf_path)
    if pptx_path and os.path.exists(pptx_path):
        attachments.append(pptx_path)

    if not attachments:
        logger.error(f"❌ No valid file attachments found to send to {email}")
        return {"email_status": "error: file(s) missing"}

    try:
        email_result_json = email_tool.invoke({
            "to_email": email,
            "subject": f"Your Generated {state.get('topic', 'Document')}",
            "body": (
                f"Here is your requested {state.get('task_type', 'document')} "
                f"for {state.get('topic', 'your topic')}.\n\n"
                f"This email contains {len(attachments)} attachment(s)."
            ),
            "attachment_paths": attachments
        })
        
        email_result = json.loads(email_result_json)

        if email_result.get("status") == "success":
            status = email_result.get("result")
            logger.info(f"✅ Email status: {status}")
            return {"email_status": status}
        else:
            status = email_result.get("message")
            logger.error(f"❌ Email failed: {status}")
            return {"email_status": status}
            
    except Exception as e:
        logger.error(f"❌ Email error: {e}")
        return {"email_status": f"Email failed: {e}"}

# -------------------------------------------------------------------
# Node 6 — Loop Control: Pop Task
# -------------------------------------------------------------------
def pop_task(state: AppState):
    """
    Pops the most recent task from the state's task list.
    This is called AFTER a task node (like generate_quiz) runs.
    """
    logger.info("✅ Task completed, popping from queue.")
    tasks = state.get("tasks", [])
    if tasks:
        tasks.pop(0) # Remove the task we just finished
    return {"tasks": tasks}

# -------------------------------------------------------------------
# Conditional Routing Functions (MODIFIED FOR MULTI-TASK)
# -------------------------------------------------------------------

def route_after_extraction(state: AppState) -> Literal["retrieve", "END"]:
    """
    Decides where to go after extraction.
    If a topic and tasks were extracted, retrieve knowledge.
    Otherwise, end.
    """
    # MODIFIED: Check for 'tasks' list
    if state.get("topic") and state.get("tasks"):
        logger.info("Decision: Topic and task(s) found, routing to 'retrieve'.")
        return "retrieve"
    else:
        logger.info("Decision: No topic/task found, routing to 'END'.")
        return END

# --- NEW: Task Loop Router ---
def route_tasks(state: AppState):
    """
    This is the main task dispatcher.
    It reads the 'tasks' list and routes to the next task.
    """
    tasks = state.get("tasks", [])
    if not tasks:
        # All tasks are done. Time to generate the PDF and/or email.
        logger.info("Decision: All tasks done, routing to 'generate_pdf'.")
        return "generate_pdf"
    
    next_task = tasks[0]
    logger.info(f"Decision: Next task is '{next_task}', routing.")
    
    if next_task == "knowledge":
        return "generate_explanation"
    if next_task == "report":
        return "generate_report"
    if next_task == "quiz":
        return "generate_quiz"
    if next_task == "presentation":
        # A presentation needs a report first.
        if not state.get("report_content"):
            logger.warning("Task 'presentation' needs 'report' first. Re-routing...")
            if "report" not in state.get("tasks", []):
                # If report isn't in the list, we MUST inject it.
                logger.info("...Routing to inject 'report' as dependency.")
                return "inject_report_dependency" # <-- THE FIX
            else:
                logger.info("...'report' is already in queue. Deferring 'presentation'.")
                return "defer_task" # This part is still correct
        else:
            return "generate_presentation"
    
    # Fallback if task is unknown
    logger.warning(f"Unknown task '{next_task}', skipping.")
    return "pop_task"


def route_after_file_gen(state: AppState) -> Literal["email", "END"]:
    """
    After any file (PDF) is created, check if we need to email it.
    (Note: PPTX generation happens *inside* the loop)
    """
    if state.get("email"):
        logger.info("Decision: Email found, routing to 'email'.")
        return "email"
    else:
        logger.info("Decision: No email found, skipping email, routing to 'END'.")
        return END

# -------------------------------------------------------------------
# Build LangGraph Workflow (MODIFIED FOR MULTI-TASK LOOP)
# -------------------------------------------------------------------
workflow = StateGraph(AppState)

# 1. Add all nodes
workflow.add_node("extract", llm_extractor)
workflow.add_node("retrieve", retrieve_knowledge)

# --- The Task Loop Nodes ---
workflow.add_node("generate_explanation", generate_explanation) # NEW
workflow.add_node("generate_report", generate_report)
workflow.add_node("generate_quiz", generate_quiz)
workflow.add_node("generate_presentation", generate_presentation)
workflow.add_node("pop_task", pop_task) 
workflow.add_node("defer_task", defer_task)
workflow.add_node("inject_report_dependency", inject_report_dependency) # <-- ADDED

# --- Final Nodes ---
workflow.add_node("generate_pdf", generate_pdf)
workflow.add_node("email", send_email)

# 2. Set entry point
workflow.set_entry_point("extract")

# 3. Add conditional edge from 'extract'
workflow.add_conditional_edges(
    "extract",
    route_after_extraction,
    {
        "retrieve": "retrieve",
        END: END
    }
)

# 4. Edge from 'retrieve' to the START of the task loop
workflow.add_conditional_edges(
    "retrieve",
    route_tasks, # NEW dispatcher
    {
        "generate_explanation": "generate_explanation",
        "generate_report": "generate_report",
        "generate_quiz": "generate_quiz",
        "generate_presentation": "generate_presentation",
        "defer_task": "defer_task", # <-- UPDATED
        "inject_report_dependency": "inject_report_dependency", # <-- UPDATED
        "generate_pdf": "generate_pdf", 
        "pop_task": "pop_task" 
    }
)

# 5. --- THIS IS THE LOOP ---
# After each task node runs, it goes to 'pop_task'
workflow.add_edge("generate_explanation", "pop_task")
workflow.add_edge("generate_report", "pop_task")
workflow.add_edge("generate_quiz", "pop_task")
workflow.add_edge("generate_presentation", "pop_task")

# After 'pop_task', route back to the dispatcher to get the NEXT task
workflow.add_conditional_edges(
    "pop_task",
    route_tasks, # The dispatcher routes again
    {
        "generate_explanation": "generate_explanation",
        "generate_report": "generate_report",
        "generate_quiz": "generate_quiz",
        "generate_presentation": "generate_presentation",
        "defer_task": "defer_task", # <-- UPDATED
        "inject_report_dependency": "inject_report_dependency", # <-- UPDATED
        "generate_pdf": "generate_pdf",
        "pop_task": "pop_task"
    }
)

# --- ADDED WIRING FOR DEFER AND INJECT ---
# After 'defer_task', route back to the dispatcher
workflow.add_conditional_edges(
    "defer_task",
    route_tasks, # The dispatcher routes again
    {
        "generate_explanation": "generate_explanation",
        "generate_report": "generate_report",
        "generate_quiz": "generate_quiz",
        "generate_presentation": "generate_presentation",
        "defer_task": "defer_task", 
        "inject_report_dependency": "inject_report_dependency", 
        "generate_pdf": "generate_pdf",
        "pop_task": "pop_task"
    }
)

# After 'inject_report_dependency', route back to the dispatcher
workflow.add_conditional_edges(
    "inject_report_dependency",
    route_tasks, # The dispatcher routes again
    {
        "generate_explanation": "generate_explanation",
        "generate_report": "generate_report", # This will be the next step
        "generate_quiz": "generate_quiz",
        "generate_presentation": "generate_presentation",
        "defer_task": "defer_task", 
        "inject_report_dependency": "inject_report_dependency",
        "generate_pdf": "generate_pdf",
        "pop_task": "pop_task"
    }
)
# -------------------------

# 6. Edges after file generation (same as before)
workflow.add_conditional_edges(
    "generate_pdf",
    route_after_file_gen,
    {
        "email": "email",
        END: END
    }
)

# 7. Add final edge
workflow.add_edge("email", END)

# 8. Compile
graph = workflow.compile()
logger.info("✅ LangGraph task-based loop compiled successfully.")


# -------------------------------------------------------------------
# CLI Entrypoint (MODIFIED to show streaming)
# -------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Educational Task Agent using LangGraph + Gemini")
    parser.add_argument("--prompt", "-p", required=True, help="User request describing the task")
    args = parser.parse_args()

    # --- THIS IS FOR CLI TESTING ---
    # In app.py, the state will be populated with user_id, chat_summary, etc.
    # For CLI, we just provide the query.
    initial_state = {
        "user_query": args.prompt,
        "user_id": "cli-test-user", # Add a dummy user for testing
        "chat_summary": None,
        "feedback_summary": None,
    }
    
    logger.info(f"🚀 Executing graph with prompt: '{args.prompt}'")
    
    print("\n=== STREAMING EXECUTION ===")
    final_state = {}
    
    # Use graph.stream() to get live updates
    for chunk in graph.stream(initial_state): # <-- Use initial_state
        # The chunk is a dictionary with one key: the node that just ran
        node_name = list(chunk.keys())[0]
        node_output = chunk[node_name]
        
        print(f"--- Just Ran Node: {node_name} ---")
        
        # Don't print the full knowledge chunk, it's too big
        if node_name == 'retrieve' and 'knowledge' in node_output:
             print("Output: {'knowledge': '... [Retrieved knowledge] ...'}")
        else:
            print(f"Output: {node_output}")
        print("="*30)
        
        # Merge the output into our final state tracker
        final_state.update(chunk)

    print("\n=== FINAL PIPLINE STATE ===")
    for k, v in final_state.items():
        if v:
            # Don't print full knowledge in final state either
            if k == 'knowledge':
                preview = "... [Retrieved knowledge] ..."
            else:
                preview = str(v)
            print(f"{k}: {preview[:400]}{'...' if len(preview) > 400 else ''}")