import os
import logging
from textwrap import dedent
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment and LLM Initialization ---
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    # In a real app, you might handle this more gracefully
    raise ValueError("Missing GOOGLE_API_KEY in .env file")

# Using a specific, lightweight model for summarization tasks
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite", # Using gemini-pro as flash lite is not available
    temperature=0.1,
    google_api_key=GOOGLE_API_KEY,
)
logger.info("Summarizer LLM (gemini-2.5-flash-lite) initialized.")

def generate_new_summary(
    summary_type: str,
    previous_summary: str | None,
    new_data: list[dict] | list[str],
) -> str:
    """
    Generates a new summary by combining a previous summary with new data.

    Args:
        summary_type: The type of summary ('chat' or 'feedback').
        previous_summary: The existing summary text.
        new_data: The new data to incorporate (chat messages or feedback strings).

    Returns:
        The newly generated summary text.
    """
    if not new_data:
        return previous_summary or "No summary available."

    # Format the new data into a string
    if summary_type == "chat":
        new_content = "\n".join([f"- {d.get('role', 'user')}: {d.get('content', '')}" for d in new_data])
    elif summary_type == "feedback":
        new_content = "\n".join([f"- {item}" for item in new_data])
    else:
        new_content = str(new_data)

    prompt: str
    if summary_type == "chat":
        prompt = dedent(f"""
        You are an expert conversation summarizer. Your task is to update a running summary of a user's conversation with an AI assistant.
        The goal is to create a detailed summary that captures the full context of the interaction, making it easy to understand the user's journey and the assistant's responses.

        Combine the 'Previous Summary' with the 'New Conversation Turns' to create a concise, updated 'New Summary'.

        **Previous Summary:**
        {previous_summary or "This is the first entry. No previous summary exists."}

        **New Conversation Turns:**
        {new_content}

        **Instructions for creating the New Summary:**
        1.  **Synthesize, don't just append.** Integrate the new conversation turns into the existing summary.
        2.  **Structure the summary.** For each major topic, clearly distinguish between the user's goal and the assistant's response.
        3.  **Identify the User's Intent:** What was the user trying to achieve or what were their main questions? Note any shifts in topic.
        4.  **Capture the Assistant's Response:** What were the key points, facts, or solutions provided by the assistant?
        5.  **Maintain a Narrative:** The summary should read like a continuous story of the conversation.

        **Example Summary Structure:**
        - Initially, the user asked about [Topic A]. The assistant provided information on [Key Point 1] and [Key Point 2].
        - The user then shifted to [Topic B], asking for [Specific Detail]. The assistant responded by [Action/Explanation].

        **New Summary:**
        """)
    elif summary_type == "feedback":
        prompt = dedent(f"""
        You are an expert feedback analyst. Your task is to create a running summary of user feedback.
        The goal is to build a clear picture of user sentiment, feature requests, and reported issues over time.

        Combine the 'Previous Feedback Summary' with the 'New Feedback Entries' to create an updated 'New Summary'.

        **Previous Feedback Summary:**
        {previous_summary or "This is the first entry. No previous summary exists."}

        **New Feedback Entries:**
        {new_content}

        **Instructions for creating the New Summary:**
        1.  **Identify Key Themes:** Extract the main points from the new feedback. Is it positive, negative, a feature request, or a bug report?
        2.  **Synthesize and Group:** Group related feedback points together. For example, if multiple entries mention the same feature, consolidate them.
        3.  **Capture Sentiment:** Note the overall tone (e.g., "User expressed satisfaction with X," "User was frustrated with Y").
        4.  **Extract Actionable Items:** Clearly list any specific suggestions, feature requests, or bug reports.

        **Example Summary Structure:**
        - **Overall Sentiment:** Mostly positive, with some specific suggestions for improvement.
        - **Positive Feedback:**
          - User was pleased with the speed and accuracy of [Feature A].
        - **Feature Requests:**
          - Requested the ability to export data to PDF.
          - Suggested adding a dark mode theme.
        - **Issues Reported:**
          - Mentioned that the login button is sometimes unresponsive on mobile.

        **New Summary:**
        """)
    else:
        # Fallback for any other summary type
        prompt = dedent(f"""
        You are an expert summarizer. Your task is to update a running summary with new information.
        Combine the 'Previous Summary' with the 'New Content' to create a concise, updated 'New Summary'.

        **Previous Summary:**
        {previous_summary or "This is the first entry. No previous summary exists."}

        **New Content ({summary_type}):**
        {new_content}

        **Instructions:**
        - Read the previous summary and the new content.
        - Identify the most important new information.
        - Integrate this information into the previous summary to create a cohesive, updated summary.
        - The final output should be ONLY the new summary text, without any preamble.

        **New Summary:**
        """)

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        new_summary = response.content.strip()
        logger.info(f"Successfully generated new summary for '{summary_type}'.")
        return new_summary
    except Exception as e:
        logger.error(f"LLM summarization failed: {e}")
        # Fallback: in case of API error, append a note to the old summary
        return (previous_summary or "") + f"\n\n[Summarization failed, new content appended]\n{new_content}"

