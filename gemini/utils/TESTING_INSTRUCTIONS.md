# Testing Instructions: User Data and Summarization API

This document provides step-by-step instructions to test the API endpoints for managing user chat history, feedback, and automated summaries.

---

## Step 1: Prerequisites

### 1. Install Dependencies
Ensure all required Python packages are installed. Open your terminal and run:

```bash
# It's recommended to use a virtual environment
# python -m venv venv
# source venv/bin/activate

pip install -r requirements_gemini.txt
pip install -r requirements_agent.txt
pip install -r requirements_tools.txt
```
*Note: You may need to install `fastapi`, `uvicorn`, and other web-related libraries if they are not already in your requirements files.*

### 2. Set Up Environment Variables
Create a file named `.env` in the `gemini/` directory if it doesn't already exist. Add your Google API key to this file:

```
GOOGLE_API_KEY="your_google_api_key_here"
```

---

## Step 2: Start the FastAPI Server

1.  Navigate to the `gemini/` directory in your terminal.
2.  Run the `app.py` file using `uvicorn`:

    ```bash
    python3 app.py
    ```
3.  The server will start. You should see output indicating that the server is running and listening on `http://127.0.0.1:8000`.

---

## Step 3: Test the Endpoints

Open a **new terminal window** to execute the following `curl` commands. We will simulate interactions for a user with `user_id="test_user_001"`.

### Test Case 1: First Interaction

1.  **Add Initial Chat History**
    *This simulates a user's first question and the agent's answer.*

    ```bash
    curl -X POST "http://127.0.0.1:8000/add_chat_history" \
    -H "Content-Type: application/json" \
    -d '{
      "user_id": "test_user_001",
      "messages": [
        {"role": "user", "content": "What is the powerhouse of the cell?"},
        {"role": "assistant", "content": "The mitochondrion is known as the powerhouse of the cell."}
      ]
    }'
    ```
    **Expected Outcome**: A success message is returned. A `user_data.db` file is created in your `gemini/` directory.

2.  **Add User Feedback**
    *This simulates the user providing feedback on the interaction.*

    ```bash
    curl -X POST "http://127.0.0.1:8000/add_feedback" \
    -H "Content-Type: application/json" \
    -d '{
      "user_id": "test_user_001",
      "feedback_text": "The answer was fast and accurate. Very helpful!"
    }'
    ```
    **Expected Outcome**: A success message is returned.

3.  **Retrieve Chat History to Verify**
    *Check if the chat messages were stored correctly.*

    ```bash
    curl -X GET "http://127.0.0.1:8000/get_chat_history/test_user_001"
    ```
    **Expected Outcome**: You should see the chat history you just added in the `data` field of the JSON response.

4.  **Retrieve the First Chat Summary**
    *Check the initial AI-generated summary of the chat.*

    ```bash
    curl -X GET "http://127.0.0.1:8000/get_summary/test_user_001/chat"
    ```
    **Expected Outcome**: A JSON response containing the first summary. The summary text should mention the user asking about the "powerhouse of the cell."

5.  **Retrieve the First Feedback Summary**
    *Check the initial AI-generated summary of the feedback.*

    ```bash
    curl -X GET "http://127.0.0.1:8000/get_summary/test_user_001/feedback"
    ```
    **Expected Outcome**: A JSON response with a summary indicating the user was satisfied and found the answer helpful.

### Test Case 2: Follow-up Interaction and Summary Update

1.  **Add More Chat History**
    *This simulates a follow-up question from the same user.*

    ```bash
    curl -X POST "http://127.0.0.1:8000/add_chat_history" \
    -H "Content-Type: application/json" \
    -d '{
      "user_id": "test_user_001",
      "messages": [
        {"role": "user", "content": "Can you also explain what a ribosome does?"}
      ]
    }'
    ```
    **Expected Outcome**: A success message.

2.  **Retrieve the Updated Chat Summary**
    *Verify that the summary has been updated to include the new context.*

    ```bash
    curl -X GET "http://127.0.0.1:8000/get_summary/test_user_001/chat"
    ```
    **Expected Outcome**: The new summary should be a synthesis of the old and new interactions. It should now mention both the **mitochondrion** and the user's new interest in **ribosomes**, demonstrating the summarizer's ability to update its context.

---

## Step 4: Cleanup (Optional)

After you have finished testing:

1.  Stop the server by pressing `Ctrl+C` in the terminal where it is running.
2.  To reset the database for a clean test run next time, you can delete the generated database file:
    ```bash
    rm user_data.db
    ```
