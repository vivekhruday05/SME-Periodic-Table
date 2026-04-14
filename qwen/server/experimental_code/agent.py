import os
from langchain_community.llms import HuggingFaceHub
from langchain.agents import AgentExecutor, create_react_agent
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_experimental.tools import PythonREPLTool
from langchain import hub

# --- 1. Set Your Hugging Face API Token ---
# !! PASTE YOUR HUGGING FACE TOKEN HERE
# (Best practice is to set this in your environment variables)
if "HUGGINGFACEHUB_API_TOKEN" not in os.environ:
    os.environ["HUGGINGFACEHUB_API_TOKEN"] = "YOUR_HF_TOKEN_HERE"

# --- 2. Initialize the LLM from Hugging Face Hub ---
# We use a model that is good at following instructions (ReAct style)
# google/flan-t5-xxl is a reliable free-tier choice for this.
#
# NOTE: Free HF models can be slow, rate-limited, or may
# struggle with complex reasoning compared to paid models.
print("Loading Hugging Face LLM...")
llm = HuggingFaceHub(
    repo_id="google/flan-t5-xxl",
    model_kwargs={"temperature": 0.2, "max_new_tokens": 250}
)

# --- 3. Define the Tools ---
# The agent will decide which tool to use.
#
# 1. PythonREPLTool: This is a powerful "calculator" that
#    can execute Python code.
# 2. DuckDuckGoSearchRun: A simple search tool.
print("Loading tools...")
tools = [
    PythonREPLTool(),       # Our "calculator"
    DuckDuckGoSearchRun()     # Our search tool
]

# --- 4. Create the Agent ---
# We pull a pre-built ReAct (Reasoning and Acting) prompt from LangChain Hub.
# This prompt is a template that instructs the LLM how to think,
# act (use a tool), and observe the result.
prompt = hub.pull("hwchase17/react")

# Create the agent by combining the LLM, tools, and prompt
agent = create_react_agent(
    llm=llm,
    tools=tools,
    prompt=prompt,
)

# --- 5. Create the Agent Executor ---
# This is the runtime that will actually "run" the agent loop.
# `verbose=True` shows the agent's thought process (very useful!)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    handle_parsing_errors=True # Helps with flaky LLM outputs
)

# --- 6. Run the Agent! ---
print("\n--- Starting Agent Test ---")

# Test 1: Using the calculator (PythonREPLTool)
print("\n--- Test 1: Calculator Query ---")
question_1 = "What is 12.3 * (4 + 5.6)?"
response_1 = agent_executor.invoke({
    "input": question_1
})
print(f"\nFinal Answer: {response_1['output']}")


# Test 2: Using the search tool
print("\n--- Test 2: Search Query ---")
question_2 = "What is the largest mammal?"
response_2 = agent_executor.invoke({
    "input": question_2
})
print(f"\nFinal Answer: {response_2['output']}")


# Test 3: Using both tools (multi-step reasoning)
print("\n--- Test 3: Multi-step Query ---")
question_3 = "What is the age of the current US president divided by 3?"
response_3 = agent_executor.invoke({
    "input": question_3
})
print(f"\nFinal Answer: {response_3['output']}")