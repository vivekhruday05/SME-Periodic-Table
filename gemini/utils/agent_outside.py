"""
Orchestration Agent for Educational Multi-Agent System

This agent acts as an intelligent orchestrator that:
1. Understands user requests (e.g., "prepare quiz for 8th grade and email it")
2. Decomposes complex tasks into sub-tasks
3. Routes each sub-task to the appropriate tool(s)
4. Manages task flow and error handling
5. Generates coherent responses to the user

Task Flow Example:
    User: "Prepare a chemistry quiz for 8th grade students about periodic table and email it to student@example.com"
    
    Agent Decision Flow:
    1. Parse Request → Identify intent: "prepare quiz + email"
    2. Extract Entities → topic: "periodic table", grade: "8th", email: "student@example.com"
    3. Route to Tools:
       - knowledge_retrieval("periodic table chemistry for grade 8")
       - quiz_generator(context, "grade 8, 10 questions, multiple choice")
       - pdf_generator(quiz_content, "periodic_table_quiz_grade8")
       - email_tool("student@example.com", "Chemistry Quiz", body, pdf_path)
    4. Monitor → Handle errors, provide fallbacks
    5. Report → Return status to user

Supported Task Patterns:
- [prepare/create] [quiz] [about X] [for Y grade] → Retrieval → Quiz Generation → PDF → Email
- [generate] [content/notes/summary] [about X] → Retrieval → PDF
- [email] [file] [to] [recipient] → Email with attachment
- [retrieve/search] [query] → Knowledge Retrieval
- [quiz] [about X] → Knowledge Retrieval → Quiz Generation
"""

import os
import json
import logging
import re
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

# LangChain imports
from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI

# Import multitools
from multitools import (
    knowledge_retrieval,
    quiz_generator,
    pdf_generator,
    email_tool
)

# ======================== LOGGING CONFIGURATION ========================

def _setup_agent_logger():
    """Configure logger for orchestration agent."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger("orchestration_agent")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(log_dir / "agent.log", encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # Console handler for important messages
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger

logger = _setup_agent_logger()

# ======================== ENUMS & DATA CLASSES ========================

class TaskType(Enum):
    """Enumeration of supported task types."""
    RETRIEVE = "retrieve"
    QUIZ = "quiz"
    NOTES = "notes"
    EMAIL = "email"
    COMBINED = "combined"  # Multiple tasks chained
    UNKNOWN = "unknown"

@dataclass
class ParsedTask:
    """Structured representation of user request."""
    task_type: TaskType
    topic: Optional[str] = None
    grade_level: Optional[str] = None
    recipient_email: Optional[str] = None
    file_path: Optional[str] = None
    subject: Optional[str] = None
    additional_constraints: Optional[str] = None
    raw_request: Optional[str] = None
    confidence: float = 0.5

# ======================== TASK PARSER ========================

class TaskParser:
    """Parse natural language requests into structured tasks."""
    
    # Common keywords for different task types
    RETRIEVE_KEYWORDS = {
        "retrieve", "search", "find", "lookup", "show", "get", "fetch",
        "what is", "tell me about", "information about"
    }
    
    QUIZ_KEYWORDS = {
        "quiz", "test", "questions", "exercise", "assessment", "exam",
        "prepare quiz", "generate questions", "create quiz"
    }
    
    NOTES_KEYWORDS = {
        "notes", "summary", "content", "material", "document", "summary",
        "prepare notes", "create notes", "generate content"
    }
    
    EMAIL_KEYWORDS = {
        "email", "send", "mail", "forward", "share via email"
    }
    
    # Grade level patterns
    GRADE_PATTERN = r'(?:grade\s+)?(\d+)(?:th|st|nd|rd)?'
    
    # Email pattern
    EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    
    @staticmethod
    def parse(user_request: str) -> ParsedTask:
        """
        Parse user request into structured task.
        
        Args:
            user_request: Natural language user request
            
        Returns:
            ParsedTask with extracted information and confidence score
        """
        request_lower = user_request.lower()
        
        # Extract email addresses
        emails = re.findall(TaskParser.EMAIL_PATTERN, user_request)
        recipient_email = emails[0] if emails else None
        
        # Extract grade levels
        grades = re.findall(TaskParser.GRADE_PATTERN, request_lower)
        grade_level = grades[0] if grades else None
        
        # Extract topic (simple heuristic: words between "about" and other keywords)
        topic = TaskParser._extract_topic(user_request)
        
        # Determine task type(s)
        has_retrieve = any(kw in request_lower for kw in TaskParser.RETRIEVE_KEYWORDS)
        has_quiz = any(kw in request_lower for kw in TaskParser.QUIZ_KEYWORDS)
        has_notes = any(kw in request_lower for kw in TaskParser.NOTES_KEYWORDS)
        has_email = any(kw in request_lower for kw in TaskParser.EMAIL_KEYWORDS) or recipient_email is not None
        
        # Determine primary task type
        task_count = sum([has_retrieve, has_quiz, has_notes])
        
        if has_quiz and has_email:
            task_type = TaskType.COMBINED
            confidence = 0.9
        elif has_quiz:
            task_type = TaskType.QUIZ
            confidence = 0.85
        elif has_notes and has_email:
            task_type = TaskType.COMBINED
            confidence = 0.85
        elif has_notes:
            task_type = TaskType.NOTES
            confidence = 0.80
        elif has_retrieve:
            task_type = TaskType.RETRIEVE
            confidence = 0.75
        elif has_email and recipient_email:
            task_type = TaskType.EMAIL
            confidence = 0.8
        else:
            task_type = TaskType.UNKNOWN
            confidence = 0.3
        
        parsed = ParsedTask(
            task_type=task_type,
            topic=topic,
            grade_level=grade_level,
            recipient_email=recipient_email,
            additional_constraints=user_request,
            raw_request=user_request,
            confidence=confidence
        )
        
        logger.info(
            f"Parsed task - Type: {task_type.value}, Topic: {topic}, "
            f"Grade: {grade_level}, Email: {recipient_email}, Confidence: {confidence}"
        )
        
        return parsed
    
    @staticmethod
    def _extract_topic(text: str) -> Optional[str]:
        """Extract topic from request using common patterns."""
        patterns = [
            r'about\s+([^,\.]*?)(?:\s+(?:for|and|to)|$)',
            r'on\s+([^,\.]*?)(?:\s+(?:for|and|to)|$)',
            r'(?:quiz|questions?|notes?|content)\s+(?:on|about)\s+([^,\.]*?)(?:\s+(?:for|and|to)|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text.lower())
            if match:
                topic = match.group(1).strip()
                if topic and len(topic) > 3:
                    return topic
        
        return None

# ======================== TASK EXECUTOR ========================

class TaskExecutor:
    """Execute parsed tasks using multitools."""
    
    def __init__(self):
        """Initialize task executor."""
        self.execution_log: List[Dict[str, Any]] = []
        logger.info("TaskExecutor initialized")
    
    def execute_retrieve_task(self, parsed_task: ParsedTask) -> Dict[str, Any]:
        """
        Execute knowledge retrieval task.
        
        Args:
            parsed_task: Parsed task information
            
        Returns:
            Dictionary with retrieval results
        """
        if not parsed_task.topic:
            return {
                "status": "error",
                "message": "No topic specified for retrieval",
                "tool": "knowledge_retrieval"
            }
        
        query = parsed_task.topic
        if parsed_task.grade_level:
            query += f" for grade {parsed_task.grade_level} students"
        
        logger.info(f"Executing retrieval task: {query}")
        
        try:
            result = knowledge_retrieval.invoke({"query": query})
            result_dict = json.loads(result) if isinstance(result, str) else result
            
            self.execution_log.append({
                "task": "retrieve",
                "query": query,
                "status": result_dict.get("status", "unknown"),
                "timestamp": datetime.now().isoformat()
            })
            
            return {
                "status": "success",
                "tool": "knowledge_retrieval",
                "result": result_dict,
                "query": query
            }
        except Exception as e:
            logger.error(f"Retrieval task failed: {e}", exc_info=True)
            self.execution_log.append({
                "task": "retrieve",
                "query": query,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return {
                "status": "error",
                "tool": "knowledge_retrieval",
                "message": f"Retrieval failed: {e}"
            }
    
    def execute_quiz_task(self, context: str, parsed_task: ParsedTask) -> Dict[str, Any]:
        """
        Execute quiz generation task.
        
        Args:
            context: Knowledge context for quiz
            parsed_task: Parsed task information
            
        Returns:
            Dictionary with generated quiz
        """
        constraints = self._build_quiz_constraints(parsed_task)
        
        logger.info(f"Executing quiz task with constraints: {constraints}")
        
        try:
            result = quiz_generator.invoke({
                "context": context,
                "constraints": constraints
            })
            result_dict = json.loads(result) if isinstance(result, str) else result
            
            self.execution_log.append({
                "task": "quiz_generation",
                "constraints": constraints,
                "status": result_dict.get("status", "unknown"),
                "timestamp": datetime.now().isoformat()
            })
            
            return {
                "status": "success",
                "tool": "quiz_generator",
                "result": result_dict,
                "constraints": constraints
            }
        except Exception as e:
            logger.error(f"Quiz task failed: {e}", exc_info=True)
            self.execution_log.append({
                "task": "quiz_generation",
                "constraints": constraints,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return {
                "status": "error",
                "tool": "quiz_generator",
                "message": f"Quiz generation failed: {e}"
            }
    
    def execute_pdf_task(self, content: str, filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute PDF generation task.
        
        Args:
            content: Content to save in PDF
            filename: Optional custom filename
            
        Returns:
            Dictionary with PDF file path
        """
        if not filename:
            filename = f"document_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        logger.info(f"Executing PDF task: {filename}")
        
        try:
            result = pdf_generator.invoke({
                "content": content,
                "filename": filename
            })
            result_dict = json.loads(result) if isinstance(result, str) else result
            
            self.execution_log.append({
                "task": "pdf_generation",
                "filename": filename,
                "status": result_dict.get("status", "unknown"),
                "timestamp": datetime.now().isoformat()
            })
            
            return {
                "status": "success",
                "tool": "pdf_generator",
                "result": result_dict,
                "filename": filename
            }
        except Exception as e:
            logger.error(f"PDF task failed: {e}", exc_info=True)
            self.execution_log.append({
                "task": "pdf_generation",
                "filename": filename,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return {
                "status": "error",
                "tool": "pdf_generator",
                "message": f"PDF generation failed: {e}"
            }
    
    def execute_email_task(
        self,
        to_email: str,
        subject: str,
        body: str,
        attachment_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute email delivery task.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            body: Email body
            attachment_path: Optional file to attach
            
        Returns:
            Dictionary with email delivery status
        """
        logger.info(f"Executing email task to: {to_email}")
        
        try:
            result = email_tool.invoke({
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "attachment_path": attachment_path
            })
            result_dict = json.loads(result) if isinstance(result, str) else result
            
            self.execution_log.append({
                "task": "email_delivery",
                "recipient": to_email,
                "status": result_dict.get("status", "unknown"),
                "timestamp": datetime.now().isoformat()
            })
            
            return {
                "status": "success",
                "tool": "email_tool",
                "result": result_dict,
                "recipient": to_email
            }
        except Exception as e:
            logger.error(f"Email task failed: {e}", exc_info=True)
            self.execution_log.append({
                "task": "email_delivery",
                "recipient": to_email,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return {
                "status": "error",
                "tool": "email_tool",
                "message": f"Email delivery failed: {e}"
            }
    
    @staticmethod
    def _build_quiz_constraints(parsed_task: ParsedTask) -> str:
        """Build quiz constraints string from parsed task."""
        constraints_parts = []
        
        if parsed_task.grade_level:
            constraints_parts.append(f"Grade {parsed_task.grade_level}")
        
        if parsed_task.topic:
            constraints_parts.append(f"Topic: {parsed_task.topic}")
        
        # Default constraints if none specified
        if not constraints_parts:
            constraints_parts = ["Grade 8", "10 questions", "Multiple choice format"]
        else:
            constraints_parts.extend(["10 questions", "Multiple choice format"])
        
        return ", ".join(constraints_parts)

# ======================== ORCHESTRATION AGENT ========================

class OrchestrationAgent:
    """Main orchestration agent for coordinating multi-tool workflows."""
    
    def __init__(self, llm_model: str = "gpt-3.5-turbo"):
        """
        Initialize orchestration agent.
        
        Args:
            llm_model: LLM model to use for decision-making
        """
        self.llm = ChatOpenAI(model=llm_model, temperature=0.7)
        self.parser = TaskParser()
        self.executor = TaskExecutor()
        logger.info(f"OrchestrationAgent initialized with model: {llm_model}")
    
    def process_request(self, user_request: str) -> Dict[str, Any]:
        """
        Process user request end-to-end.
        
        Workflow:
        1. Parse request into structured task
        2. Route to appropriate handler based on task type
        3. Execute tool chain
        4. Return results to user
        
        Args:
            user_request: Natural language user request
            
        Returns:
            Dictionary with final results and status
        """
        logger.info(f"Processing user request: {user_request}")
        
        # Step 1: Parse request
        parsed_task = self.parser.parse(user_request)
        
        if parsed_task.confidence < 0.3:
            logger.warning(f"Low confidence parse (confidence: {parsed_task.confidence})")
            return {
                "status": "error",
                "message": "Could not understand request. Please provide more details.",
                "suggestions": [
                    "Try: 'Prepare a chemistry quiz about periodic table for 8th grade'",
                    "Try: 'Generate notes on chemical bonding'",
                    "Try: 'Search for information about d-block elements'"
                ]
            }
        
        # Step 2: Route to handler
        if parsed_task.task_type == TaskType.COMBINED:
            return self._handle_combined_task(parsed_task)
        elif parsed_task.task_type == TaskType.QUIZ:
            return self._handle_quiz_task(parsed_task)
        elif parsed_task.task_type == TaskType.NOTES:
            return self._handle_notes_task(parsed_task)
        elif parsed_task.task_type == TaskType.RETRIEVE:
            return self._handle_retrieve_task(parsed_task)
        elif parsed_task.task_type == TaskType.EMAIL:
            return self._handle_email_task(parsed_task)
        else:
            return {
                "status": "error",
                "message": "Task type not recognized"
            }
    
    def _handle_retrieve_task(self, parsed_task: ParsedTask) -> Dict[str, Any]:
        """Handle knowledge retrieval task."""
        logger.info("Handling RETRIEVE task")
        
        result = self.executor.execute_retrieve_task(parsed_task)
        
        return {
            "status": result["status"],
            "task_type": "retrieve",
            "message": f"Retrieved information about {parsed_task.topic}",
            "data": result.get("result"),
            "query": result.get("query")
        }
    
    def _handle_quiz_task(self, parsed_task: ParsedTask) -> Dict[str, Any]:
        """Handle quiz generation task (retrieve + generate quiz)."""
        logger.info("Handling QUIZ task")
        
        # Step 1: Retrieve context
        retrieval_result = self.executor.execute_retrieve_task(parsed_task)
        
        if retrieval_result["status"] != "success":
            return {
                "status": "error",
                "task_type": "quiz",
                "message": "Failed to retrieve knowledge for quiz generation"
            }
        
        # Extract context from retrieval result
        retrieved_data = retrieval_result.get("result", {})
        if isinstance(retrieved_data, dict) and "result" in retrieved_data:
            context = retrieved_data["result"]
        else:
            context = str(retrieved_data)
        
        # Step 2: Generate quiz
        quiz_result = self.executor.execute_quiz_task(context, parsed_task)
        
        if quiz_result["status"] != "success":
            return {
                "status": "error",
                "task_type": "quiz",
                "message": "Failed to generate quiz"
            }
        
        return {
            "status": "success",
            "task_type": "quiz",
            "message": f"Generated quiz about {parsed_task.topic} for grade {parsed_task.grade_level}",
            "data": quiz_result.get("result")
        }
    
    def _handle_notes_task(self, parsed_task: ParsedTask) -> Dict[str, Any]:
        """Handle notes/content generation task (retrieve + pdf)."""
        logger.info("Handling NOTES task")
        
        # Step 1: Retrieve context
        retrieval_result = self.executor.execute_retrieve_task(parsed_task)
        
        if retrieval_result["status"] != "success":
            return {
                "status": "error",
                "task_type": "notes",
                "message": "Failed to retrieve knowledge for notes generation"
            }
        
        # Extract context
        retrieved_data = retrieval_result.get("result", {})
        if isinstance(retrieved_data, dict) and "result" in retrieved_data:
            context = retrieved_data["result"]
        else:
            context = str(retrieved_data)
        
        # Step 2: Generate PDF
        filename = f"notes_{parsed_task.topic}_{datetime.now().strftime('%Y%m%d')}.pdf"
        pdf_result = self.executor.execute_pdf_task(context, filename)
        
        if pdf_result["status"] != "success":
            return {
                "status": "error",
                "task_type": "notes",
                "message": "Failed to generate PDF"
            }
        
        return {
            "status": "success",
            "task_type": "notes",
            "message": f"Generated notes about {parsed_task.topic}",
            "file_path": pdf_result.get("result", {}).get("result")
        }
    
    def _handle_email_task(self, parsed_task: ParsedTask) -> Dict[str, Any]:
        """Handle email delivery task."""
        logger.info("Handling EMAIL task")
        
        if not parsed_task.recipient_email:
            return {
                "status": "error",
                "task_type": "email",
                "message": "No recipient email specified"
            }
        
        email_result = self.executor.execute_email_task(
            to_email=parsed_task.recipient_email,
            subject="Educational Content",
            body="Please find your educational content attached.",
            attachment_path=parsed_task.file_path
        )
        
        return {
            "status": email_result["status"],
            "task_type": "email",
            "message": email_result.get("result", {}).get("result", "Email sent"),
            "recipient": parsed_task.recipient_email
        }
    
    def _handle_combined_task(self, parsed_task: ParsedTask) -> Dict[str, Any]:
        """
        Handle combined tasks (e.g., quiz + email).
        
        Workflow:
        1. Retrieve context
        2. Generate quiz
        3. Create PDF
        4. Send email with attachment
        """
        logger.info("Handling COMBINED task")
        
        # Step 1: Retrieve context
        logger.info("Step 1/4: Retrieving knowledge context")
        retrieval_result = self.executor.execute_retrieve_task(parsed_task)
        
        if retrieval_result["status"] != "success":
            return {
                "status": "error",
                "task_type": "combined",
                "current_step": "retrieval",
                "message": "Failed at retrieval step"
            }
        
        retrieved_data = retrieval_result.get("result", {})
        if isinstance(retrieved_data, dict) and "result" in retrieved_data:
            context = retrieved_data["result"]
        else:
            context = str(retrieved_data)
        
        # Step 2: Generate quiz
        logger.info("Step 2/4: Generating quiz")
        quiz_result = self.executor.execute_quiz_task(context, parsed_task)
        
        if quiz_result["status"] != "success":
            return {
                "status": "error",
                "task_type": "combined",
                "current_step": "quiz_generation",
                "message": "Failed at quiz generation step"
            }
        
        quiz_content = quiz_result.get("result", {}).get("result", "")
        
        # Step 3: Generate PDF
        logger.info("Step 3/4: Creating PDF")
        filename = f"quiz_{parsed_task.topic}_{parsed_task.grade_level}_{datetime.now().strftime('%Y%m%d')}.pdf"
        pdf_result = self.executor.execute_pdf_task(quiz_content, filename)
        
        if pdf_result["status"] != "success":
            return {
                "status": "error",
                "task_type": "combined",
                "current_step": "pdf_generation",
                "message": "Failed at PDF generation step"
            }
        
        pdf_path = pdf_result.get("result", {}).get("result")
        
        # Step 4: Send email
        logger.info("Step 4/4: Sending email")
        if parsed_task.recipient_email:
            email_result = self.executor.execute_email_task(
                to_email=parsed_task.recipient_email,
                subject=f"Chemistry Quiz - {parsed_task.topic} (Grade {parsed_task.grade_level})",
                body=f"Dear Student,\n\nPlease find your personalized chemistry quiz attached.\n\nTopic: {parsed_task.topic}\nGrade Level: {parsed_task.grade_level}\n\nBest regards,\nEducational System",
                attachment_path=pdf_path
            )
            
            if email_result["status"] != "success":
                return {
                    "status": "partial",
                    "task_type": "combined",
                    "current_step": "email_delivery",
                    "message": "Quiz created but email delivery failed",
                    "file_path": pdf_path
                }
            
            return {
                "status": "success",
                "task_type": "combined",
                "message": f"Successfully created and emailed quiz to {parsed_task.recipient_email}",
                "details": {
                    "topic": parsed_task.topic,
                    "grade_level": parsed_task.grade_level,
                    "recipient": parsed_task.recipient_email,
                    "file_path": pdf_path
                }
            }
        else:
            return {
                "status": "success",
                "task_type": "combined",
                "message": f"Successfully created quiz (no email recipient specified)",
                "file_path": pdf_path,
                "details": {
                    "topic": parsed_task.topic,
                    "grade_level": parsed_task.grade_level
                }
            }

# ======================== MAIN INTERFACE ========================

def create_agent(llm_model: str = "gpt-3.5-turbo") -> OrchestrationAgent:
    """
    Factory function to create orchestration agent.
    
    Args:
        llm_model: LLM model name
        
    Returns:
        Initialized OrchestrationAgent instance
    """
    return OrchestrationAgent(llm_model=llm_model)

def process_user_request(user_request: str, llm_model: str = "gpt-3.5-turbo") -> Dict[str, Any]:
    """
    Simple interface to process user request.
    
    Args:
        user_request: User's natural language request
        llm_model: LLM model to use
        
    Returns:
        Result dictionary
    """
    agent = create_agent(llm_model=llm_model)
    return agent.process_request(user_request)

# ======================== EXAMPLE USAGE ========================

if __name__ == "__main__":
    """
    Example usage of orchestration agent.
    
    Try these requests:
    1. "Prepare a chemistry quiz about periodic table for 8th grade students and email it to student@example.com"
    2. "Generate notes on chemical bonding"
    3. "Create a quiz about d-block elements for 10th graders"
    4. "Search for information on redox reactions"
    """
    
    # Example request
    user_request = "Prepare a chemistry quiz about periodic table for 8th grade and email it to student@example.com"
    
    print(f"User Request: {user_request}\n")
    print("Processing...\n")
    
    result = process_user_request(user_request)
    
    print(json.dumps(result, indent=2))
