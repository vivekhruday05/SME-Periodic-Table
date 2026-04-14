# multitools.py - Production-Ready LangChain Module

## Module Overview

**Purpose**: Provide four specialized, production-ready tools for a LangChain-based educational multi-agent system focused on chemistry content.

**Key Features**:
- ✅ Structured JSON responses for agent parsing
- ✅ Comprehensive error logging to `logs/tools.log`
- ✅ Input validation with user-friendly error messages
- ✅ Automatic device management (CUDA/CPU)
- ✅ LangChain `@tool` decorator integration
- ✅ No print statements (logging only)

---

## Architecture

### Module Initialization Flow

```
Module Load
    ↓
├─ Import dependencies (os, json, logging, etc.)
├─ _setup_logger() → Logger to logs/tools.log
├─ Global variables initialized (_retriever, _text_model, _text_tokenizer)
│   (Lazy initialization on first tool call)
└─ @tool decorators register tools with LangChain

Tool Calls
    ↓
├─ Input Validation → Error JSON if invalid
├─ Lazy Model Init → Load if not already loaded
├─ Processing → Core functionality
├─ Logging → Log status/errors to tools.log
└─ Response → JSON string ({"status": ..., "result": ...})
```

### Response Structure

All tools follow this unified response format:

```python
# Success Response
{
    "status": "success",
    "result": "primary_output_data",
    "metadata_key": "metadata_value"  # Optional: chunk_count, file_size, length, recipient
}

# Error Response
{
    "status": "error",
    "message": "User-friendly error description"
}
```

---

## Tool Specifications

### 1. knowledge_retrieval(query: str) → str

**Purpose**: Retrieve chemistry content from Elasticsearch RAG system.

**Input Validation**:
- Query must be at least 3 characters
- Returns error JSON if invalid

**Processing**:
1. Initialize RAG retriever (first call only)
2. Query Elasticsearch hybrid index
3. Rerank results using BGE reranker
4. Return top chunks

**Outputs**:

Success:
```json
{
    "status": "success",
    "result": "[chemistry content]\n...",
    "chunk_count": 5
}
```

Error (Validation):
```json
{
    "status": "error",
    "message": "Query must be at least 3 characters long."
}
```

Error (System):
```json
{
    "status": "error",
    "message": "Error: Knowledge retrieval unavailable. Check logs for details."
}
```

**Logging**:
- INFO: "Successfully retrieved N chunks for query: ..."
- WARNING: Validation errors
- ERROR: System failures with traceback

---

### 2. quiz_generator(context: str, constraints: str) → str

**Purpose**: Generate educational quiz questions from knowledge context.

**Input Validation**:
- Context: minimum 50 characters (user-facing content)
- Constraints: minimum 5 characters (e.g., "Grade 8, 10 questions")
- Generated quiz: minimum 50 characters

**Processing**:
1. Validate inputs
2. Initialize Flan-T5-large model (first call only)
3. Build instruction prompt with context and constraints
4. Generate quiz using model
5. Validate output

**Outputs**:

Success:
```json
{
    "status": "success",
    "result": "[formatted quiz questions]",
    "length": 3450
}
```

Error (Validation):
```json
{
    "status": "error",
    "message": "Context must be at least 50 characters long."
}
```

Error (System):
```json
{
    "status": "error",
    "message": "Error: Quiz generation failed. Check logs for details."
}
```

**Logging**:
- INFO: "Successfully generated quiz (N characters) for constraints: ..."
- WARNING: Validation errors (short context/constraints)
- ERROR: Model failures, insufficient output

---

### 3. pdf_generator(content: str, filename: str) → str

**Purpose**: Create professional PDF documents from text content.

**Input Validation**:
- Content: 50 chars minimum, 1MB maximum
- Filename: 3+ characters (sanitized to alphanumeric + hyphen/underscore)

**Processing**:
1. Validate inputs
2. Sanitize filename
3. Create `generated_documents/` directory if needed
4. Initialize FPDF with Arial font
5. Add title and wrapped content
6. Output to disk

**Outputs**:

Success:
```json
{
    "status": "success",
    "result": "/absolute/path/to/generated_documents/filename.pdf",
    "file_size": 24580
}
```

Error (Validation):
```json
{
    "status": "error",
    "message": "Content must be at least 50 characters long."
}
```

Error (System):
```json
{
    "status": "error",
    "message": "Error: PDF generation failed. Check logs for details."
}
```

**Logging**:
- INFO: "Successfully generated PDF at [path] (N bytes)"
- WARNING: Validation errors (short content, oversized content)
- ERROR: FPDF exceptions, file I/O errors

---

### 4. email_tool(to_email: str, subject: str, body: str, attachment_path: str | None = None) → str

**Purpose**: Send emails with optional PDF attachments via SMTP.

**Input Validation**:
- Email address: must be provided
- Subject: must be provided
- Body: must be provided
- Attachment (optional): must exist if provided

**Environment Requirements**:
- `EMAIL_USERNAME`: Sender email
- `EMAIL_PASSWORD`: SMTP password (app-specific for Gmail)
- `EMAIL_SMTP_SERVER`: Default "smtp.gmail.com"
- `EMAIL_SMTP_PORT`: Default "587"

**Processing**:
1. Validate inputs
2. Retrieve SMTP config from environment
3. Create MIME message with text and attachment (if provided)
4. Connect to SMTP server with TLS
5. Authenticate and send
6. Disconnect

**Outputs**:

Success:
```json
{
    "status": "success",
    "result": "Email sent to student@example.com with attachment: quiz.pdf",
    "recipient": "student@example.com"
}
```

Error (Validation):
```json
{
    "status": "error",
    "message": "Email address, subject, and body are required."
}
```

Error (Configuration):
```json
{
    "status": "error",
    "message": "Error: Email credentials not configured. Check logs for details."
}
```

Error (System):
```json
{
    "status": "error",
    "message": "Error: SMTP authentication failed. Check EMAIL_USERNAME and EMAIL_PASSWORD."
}
```

**Logging**:
- INFO: "Email sent to [email] with/without attachment"
- WARNING: Validation errors, missing credentials
- ERROR: SMTP connection failures, attachment errors with traceback

---

## Device Management

### CUDA/CPU Auto-Detection

The text generation model uses automatic device detection:

```python
def _init_text_gen_model():
    # ... initialization code ...
    device = 0 if torch.cuda.is_available() else -1
    # device=0 for CUDA (first GPU)
    # device=-1 for CPU
    model = model.to(device)
    return model, tokenizer
```

**Implications**:
- On GPU systems: ~2-3s initialization, ~3-5s generation
- On CPU systems: ~5-10s initialization, ~10-30s generation
- Device detection is automatic, no configuration needed

---

## Error Handling Pattern

All tools follow this consistent pattern:

```python
@tool
def tool_name(param1: str, param2: str) -> str:
    """Docstring with purpose, inputs, outputs."""
    try:
        # ===== Input Validation =====
        if not valid_input:
            logger.warning(f"tool_name: Error description")
            return json.dumps({
                "status": "error",
                "message": "User-friendly message"
            })
        
        # ===== Processing =====
        result = process(param1, param2)
        
        # ===== Success Response =====
        logger.info(f"tool_name: Success details")
        return json.dumps({
            "status": "success",
            "result": result,
            "metadata": value
        })
        
    except SpecificException as e:
        logger.error(f"tool_name specific error: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": "Error: Description. Check logs for details."
        })
    except Exception as e:
        logger.error(f"tool_name exception: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": "Error: Tool execution failed. Check logs for details."
        })
```

---

## Logging Reference

### Log File Location
- **Path**: `logs/tools.log`
- **Level**: INFO (captures success, warnings, and errors)
- **Format**: `TIMESTAMP - MODULE - LEVEL - MESSAGE`
- **Auto-created**: On first tool execution

### Log Entry Examples

**Success**:
```
2024-01-15 10:30:45,123 - multitools - INFO - knowledge_retrieval: Successfully retrieved 5 chunks (2340 characters) for query: periodic table elements
```

**Validation Warning**:
```
2024-01-15 10:31:12,456 - multitools - WARNING - quiz_generator: Context must be at least 50 characters long.
```

**Exception Error** (with traceback):
```
2024-01-15 10:32:00,789 - multitools - ERROR - email_tool exception: [Errno 111] Connection refused
Traceback (most recent call last):
  File "/path/to/multitools.py", line 415, in email_tool
    server = smtplib.SMTP(smtp_server, smtp_port)
  ...
```

---

## Integration with LangChain Agent

### Basic Setup

```python
from langchain.agents import AgentExecutor, ReActSingleInputAgent
from multitools import knowledge_retrieval, quiz_generator, pdf_generator, email_tool

tools = [
    knowledge_retrieval,
    quiz_generator,
    pdf_generator,
    email_tool
]
```

### Tool Invocation (via LangChain)

```python
# LangChain agent automatically:
# 1. Calls tool.invoke({"input": user_request})
# 2. Receives JSON string response
# 3. Parses JSON for next decision
# 4. May call another tool or return to user

agent_executor.invoke({
    "input": "Generate a chemistry quiz about periodic table and email to student@example.com"
})
```

### Manual Tool Invocation (for testing)

```python
# Tools are StructuredTool objects from LangChain
result = knowledge_retrieval.invoke({"query": "periodic table"})
# result is a JSON string: {"status": "success", "result": "...", "chunk_count": 3}
response = json.loads(result)
```

---

## Production Deployment Checklist

- [ ] `logs/` directory exists and is writable
- [ ] `generated_documents/` directory exists and is writable
- [ ] Environment variables configured:
  - [ ] `ES_HOST`, `ES_INDEX` for Elasticsearch
  - [ ] `EMBED_MODEL`, `RERANKER_MODEL` for RAG
  - [ ] `EMAIL_USERNAME`, `EMAIL_PASSWORD` for SMTP
- [ ] Elasticsearch index populated with chemistry content
- [ ] Embedding models cached (BAAI/bge-base-en-v1.5)
- [ ] Text generation model cached (google/flan-t5-large)
- [ ] Run `verify_production_ready.py` and confirm all checks pass
- [ ] Monitor `logs/tools.log` for initialization and errors
- [ ] Test complete workflow: knowledge → quiz → pdf → email

---

## Future Extensions (Post-v1.0)

Placeholder for future feedback_tool:

```python
@tool
def feedback_tool(quiz_performance: dict, user_profile: dict) -> str:
    """
    Adaptive learning tool for self-learning and personalized recommendations.
    
    Future implementation will enable:
    - Adaptive quiz difficulty based on performance
    - Personalized content recommendations
    - Learning path optimization
    - Performance analytics
    """
    pass
```

---

## Summary

**multitools.py** provides a production-ready module for LangChain integration with:
- ✅ Four specialized tools for educational workflows
- ✅ Structured JSON responses for reliable parsing
- ✅ Comprehensive error logging with full tracebacks
- ✅ Automatic device management for GPU/CPU
- ✅ Input validation preventing resource waste
- ✅ Consistent error handling patterns
- ✅ Ready for immediate deployment with proper configuration

**Next Step**: Use with `main_agent.py` for orchestrated multi-agent workflows.
