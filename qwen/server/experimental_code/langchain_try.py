import os
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from multitools import (
    knowledge_retrieval,
    quiz_generator,
    pdf_generator,
    email_tool
)
from experimental_code.ReAct_system_prompt import system_prompt


tools = [knowledge_retrieval, quiz_generator, pdf_generator, email_tool]
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-pro",
    temperature=0.3,
    google_api_key=GOOGLE_API_KEY,
)

agent = create_agent(
    llm,
    tools=tools,
    system_prompt=system_prompt
)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Periodic Table Educational Agent")
    parser.add_argument(
        "--prompt",
        "-p",
        required=True,
        help="Instruction or query for the agent (e.g., 'Generate a quiz on periodic table basics and email it to me')"
    )
    args = parser.parse_args()

    print("Processing request via ChemAssist (Gemini ReAct Agent)...\n")

    try:
        # Create a standard message structure for LangChain ReAct agent
        response = agent.invoke({
            "messages": [
                {"role": "user", "content": args.prompt}
            ]
        })

        # The ReAct agent returns an AIMessage object
        print("\n=== AGENT RESPONSE ===")
        if hasattr(response, "content"):
            print(response.content)
        else:
            print(response)

    except Exception as e:
        print(f"\nError during agent execution: {e}")
