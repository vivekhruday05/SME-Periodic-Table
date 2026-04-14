# API Documentation: User Data, Summarization & Interaction Modes

This document provides details on the API endpoints for managing user chat history, feedback, and automated summaries.

**Base URL:** `http://127.0.0.1:8000`

---
## 0. Core Execution Endpoints (Agent vs Ask Mode)

The system now supports two interaction modes:

| Mode | Description | Endpoint | Stream Events |
|------|-------------|----------|---------------|
| `agent` | Full LangGraph multi-task workflow (quiz/report/presentation/PDF/email) | `/execute_stream` (POST) | `graph_update`, `end`, `error` |
| `ask` | Lightweight retrieval-augmented Q&A (direct RAG) | `/execute_stream` (POST) | `ask_update` (answer chunks), `ask_sources`, `end`, `error` |

### Request Body (shared)
```json
{
  "user_query": "Explain atomic radius trends",
  "user_id": "alice",            // username (must exist after signup)
  "mode": "ask",                 // "ask" or "agent" (default: agent)
  "chat_id": "1731707332000"    // client generated per conversation
}
```

### Ask Mode Streaming Events
Example SSE stream payloads:
```
event: ask_update
data: {"chunk_index":0,"content":"Atomic radius generally increases down a group."}

event: ask_sources
data: {"sources":["periodic_table.txt","group_trends.pdf"]}

event: end
data: {}
```

### Agent Mode Streaming Events
```
event: graph_update
data: {"node":"retrieve","output":{"knowledge":"..."}}

event: graph_update
data: {"node":"generate_report","output":{"report_content":"..."}}

event: end
data: {}
```

> When you only need an answer without generating artifacts (quiz/report/presentation/PDF/email), use `mode: "ask"` for faster, cheaper responses.

---
## Chat Identification (`chat_id`)

All chat history and chat summaries are now scoped by a **client-assigned** `chat_id` (e.g., a timestamp). You must send the same `chat_id` for successive messages in a conversation.

| Resource | Scoped by `chat_id` | Notes |
|----------|--------------------|-------|
| Chat messages (`/add_chat_history`) | Yes | Each message batch belongs to a chat session. |
| Chat summary (`summary_type=chat`) | Yes | Stored separately per user + chat. |
| Feedback summary | No | Global per user (no chat_id). |

---
## User Accounts

### Signup
`POST /signup`
```json
{ "username": "alice", "email": "alice@example.com", "password": "secret123" }
```
On success the user is stored; the frontend also logs them in immediately.

### Login
`POST /login`
```json
{ "username": "alice", "password": "secret123" }
```
Returns:
```json
{ "status": "success", "username": "alice", "email": "alice@example.com" }
```

Use `username` as `user_id` in all subsequent requests. The system looks up the user's stored email and injects it into the agent state so that when an email task is requested the address is auto-populated.

---

---

## 1. Add Chat History

Adds a user's chat session to the database and triggers an update of their rolling chat summary.

- **Endpoint:** `/add_chat_history`
- **Method:** `POST`
- **Description:** Use this endpoint to send a list of messages from a user's session. The system will store these messages and then use them to update a summary of the user's interactions.

### Request Body

```json
{
  "user_id": "string",
  "messages": [
    {
      "role": "string",
      "content": "string"
    }
  ]
}
```
- `user_id`: A unique identifier for the user (e.g., "user123").
- `messages`: A list of message objects. Each object should have a `role` (e.g., "user", "assistant") and the `content` of the message.

### Example `curl` Request

```bash
curl -X POST "http://127.0.0.1:8000/add_chat_history" \
-H "Content-Type: application/json" \
-d '{
  "user_id": "user_alpha",
  "messages": [
    {"role": "user", "content": "Tell me about black holes."},
    {"role": "assistant", "content": "A black hole is a region of spacetime where gravity is so strong that nothing, no particles or even electromagnetic radiation such as light, can escape from it."}
  ]
}'
```

### Success Response (201)

```json
{
  "status": "success",
  "message": "Chat history and summary updated for user user_alpha."
}
```

---

## 2. Add Feedback

Adds a user's feedback to the database and triggers an update of their feedback summary.

- **Endpoint:** `/add_feedback`
- **Method:** `POST`
- **Description:** Use this to submit feedback from a user. This is useful for collecting user opinions or bug reports and summarizing them over time.

### Request Body

```json
{
  "user_id": "string",
  "feedback_text": "string"
}
```
- `user_id`: The unique identifier for the user.
- `feedback_text`: The raw text of the user's feedback.

### Example `curl` Request

```bash
curl -X POST "http://127.0.0.1:8000/add_feedback" \
-H "Content-Type: application/json" \
-d '{
  "user_id": "user_alpha",
  "feedback_text": "Now the diagrams too are great, but the color gradient is not optimal."
}'
```

### Success Response (201)

```json
{
  "status": "success",
  "message": "Feedback and summary updated for user user_alpha."
}
```

---

## 3. Get Chat History

Retrieves the most recent chat messages for a specific user.

- **Endpoint:** `/get_chat_history/{user_id}`
- **Method:** `GET`
- **Description:** Fetches a list of the most recent chat messages, which is useful for displaying conversation history in a UI.

### URL Parameters

- `user_id` (required): The ID of the user whose history you want to retrieve.
- `limit` (optional, default: 20): The maximum number of messages to return.

### Example `curl` Request

```bash
# Get the last 20 messages for user_alpha
curl -X GET "http://127.0.0.1:8000/get_chat_history/user_alpha"

# Get the last 5 messages
curl -X GET "http://127.0.0.1:8000/get_chat_history/user_alpha?limit=5"
```

### Success Response (200)

```json
{
  "user_id": "user_alpha",
  "data": [
    {
      "role": "user",
      "content": "Tell me about black holes."
    },
    {
      "role": "assistant",
      "content": "A black hole is a region of spacetime where gravity is so strong that nothing, no particles or even electromagnetic radiation such as light, can escape from it."
    }
  ]
}
```

---

## 4. Get Feedback

Retrieves the most recent feedback entries for a specific user.

- **Endpoint:** `/get_feedback/{user_id}`
- **Method:** `GET`
- **Description:** Fetches a list of the most recent feedback submissions from a user.

### URL Parameters

- `user_id` (required): The ID of the user whose feedback you want to retrieve.
- `limit` (optional, default: 20): The maximum number of feedback entries to return.

### Example `curl` Request

```bash
curl -X GET "http://127.0.0.1:8000/get_feedback/user_alpha"
```

### Success Response (200)

```json
{
    "user_id": "user_alpha",
    "data": [
        "The explanation was great, but I wish the agent could generate diagrams."
    ]
}
```

---

## 5. Get Summary

Retrieves the latest generated summary for a user.

- **Endpoint:** `/get_summary/{user_id}/{summary_type}`
- **Method:** `GET`
- **Description:** Fetches the most up-to-date summary for a user. This summary is automatically updated every time you add new chat history or feedback.

### URL Parameters

- `user_id` (required): The ID of the user.
- `summary_type` (required): The type of summary to retrieve. Must be either `chat` or `feedback`.

### Example `curl` Request

```bash
# Get the chat summary
curl -X GET "http://127.0.0.1:8000/get_summary/user_alpha/chat"

# Get the feedback summary
curl -X GET "http://127.0.0.1:8000/get_summary/user_alpha/feedback"
```

### Success Response (200)

```json
{
    "user_id": "user_alpha",
    "summary_type": "chat",
    "summary": "The user expressed interest in black holes, asking for a basic definition. The agent provided a standard scientific explanation of the concept."
}
```
