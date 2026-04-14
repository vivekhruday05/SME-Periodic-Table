"""
End-to-end Retrieval-Augmented Generation (RAG) pipeline.

This script orchestrates the entire RAG process:
1. Takes a user query.
2. Uses the `Retriever` to fetch relevant context from Elasticsearch.
3. Constructs a prompt using the retrieved context and the query.
4. Feeds the prompt to a generative model (e.g., Gemma) to get an answer.
5. Prints the answer and the sources used.

Usage:
    python rag.py --query "Your question here"
"""

import os
import sys
import logging
import argparse
from pathlib import Path
from dotenv import load_dotenv
# REMOVED: import google.generativeai as genai
from langchain_google_genai import ChatGoogleGenerativeAI              # ADDED
from langchain_core.messages import HumanMessage, SystemMessage        # ADDED
from retrieval import Retriever

# Load environment variables from .env file
load_dotenv()

# ------------------- Logging setup -------------------

def setup_rag_logging(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    rag_log = log_dir / 'rag.log'
    error_log = log_dir / 'rag_errors.log'

    logger = logging.getLogger('rag')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        fh = logging.FileHandler(rag_log, encoding='utf-8')
        fh.setLevel(logging.INFO)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        logger.addHandler(fh)
        logger.addHandler(ch)

    err_logger = logging.getLogger('rag_errors')
    err_logger.setLevel(logging.WARNING)
    err_logger.propagate = False
    
    if not err_logger.handlers:
        efh = logging.FileHandler(error_log, encoding='utf-8')
        efh.setLevel(logging.WARNING)
        efh.setFormatter(formatter)
        err_logger.addHandler(efh)

    return logger, err_logger

# ------------------- RAG Pipeline -------------------

class RAGPipeline:
    def __init__(self, retriever: Retriever, gen_model_name: str = None, log_dir: Path = Path('logs'), quantize_8bit: bool = False):
        self.retriever = retriever
        self.gen_model_name = gen_model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
        self.logger, self.err_logger = setup_rag_logging(log_dir)

        # Initialize Gemini API client
        self.api_key = os.getenv("GEMINI_API_KEY") # CHANGED: Store API key
        if not self.api_key:
            self.logger.error("GEMINI_API_KEY not found in .env file!")
            raise ValueError("GEMINI_API_KEY not set in .env file")
        
        # REMOVED: genai.configure(api_key=api_key)
        self.logger.info(f"Gemini API key loaded. Model to be loaded: {self.gen_model_name}")
        
        self.gen_model = None  # Will be set when needed
    
    # ----- Gemini API Version -----
    def _load_generation_model(self):
        """Initialize LangChain ChatGoogleGenerativeAI model.""" # CHANGED
        self.logger.info(f"Loading generation model: {self.gen_model_name}")
        try:
            # CHANGED: Use ChatGoogleGenerativeAI
            self.gen_model = ChatGoogleGenerativeAI(
                model=self.gen_model_name,
                google_api_key=self.api_key # Use stored key
            )
            self.logger.info(f"Successfully loaded {self.gen_model_name}")
        except Exception as e:
            self.logger.error(f"Failed to load generation model '{self.gen_model_name}': {e}")
            raise

    def generate_answer(self, query: str, top_k: int = 20, rerank_top_n: int = 5):
        """
        Orchestrates the RAG pipeline from query to answer using Gemini API.
        """
        # 1. Retrieve context
        self.logger.info("Step 1: Retrieving context...")
        context_chunks = self.retriever.search(query, top_k=top_k, rerank_top_n=rerank_top_n)

        if not context_chunks:
            self.logger.warning("No context retrieved. Cannot generate an answer.")
            return "I couldn't find any relevant information to answer your question.", []

        # 1b. Offload retriever models to CPU to ensure only one model sits on GPU
        try:
            self.retriever.offload_models_to_cpu()
        except Exception:
            pass

        # 1c. Load the Gemini model if not already loaded
        if self.gen_model is None:
            self._load_generation_model()
        
        # 2. Format the context
        self.logger.info("Step 2: Formatting context...")
        context_str = "\n\n---\n\n".join([chunk['_source']['chunk_text'] for chunk in context_chunks])
        
        # Build the prompt using LangChain messages
        # CHANGED: Use SystemMessage
        system_message = SystemMessage(content=(
            "You are a helpful assistant for a K-12 student. "
            "You MUST answer the user's question only using the context provided. "
            "Do not use any outside knowledge. "
            "If the answer is not in the context, say: 'I'm sorry, but I couldn't find that information in the provided documents.' "
            "Be concise and clear."
        ))
        
        # CHANGED: Use HumanMessage
        human_message_content = f"""Context:
{context_str}

Question: {query}

Answer:"""
        human_message = HumanMessage(content=human_message_content)

        messages = [system_message, human_message] # ADDED

        # 3. Generate the answer using Gemini API
        self.logger.info("Step 3: Generating answer with Gemini API...")
        try:
            # CHANGED: Switched to model.invoke()
            response = self.gen_model.invoke(
                messages,
                generation_config={
                    "temperature": 0.7,
                    "top_p": 0.95,
                    "max_output_tokens": 2048,
                }
            )
            
            answer = response.content.strip() # CHANGED: from response.text
            self.logger.info(f"Successfully generated answer ({len(answer)} characters)")
            
        except Exception as e:
            self.err_logger.error(f"Error during text generation with Gemini: {e}")
            return "I encountered an error while trying to generate an answer.", []

        # 4. Collect sources
        sources = list(set([chunk['_source']['filename'] for chunk in context_chunks]))

        return answer, sources

    def _offload_generation_model(self):
        """Gemini API doesn't require manual memory management."""
        self.logger.info("No manual offloading needed for Gemini API")
        pass

# ------------------- CLI -------------------

def main():
    parser = argparse.ArgumentParser(description='Retrieval-Augmented Generation (RAG) Pipeline with Gemini API')
    parser.add_argument('--query', type=str, required=True, help="Search query.")
    # Retriever args
    parser.add_argument('--es-host', type=str, default='http://localhost:9200', help="Elasticsearch host.")
    parser.add_argument('--index-name', type=str, default='periodic-table-hybrid-search', help="Elasticsearch index name.")
    parser.add_argument('--embed-model', type=str, default='BAAI/bge-base-en-v1.5', help="Embedding model name.")
    parser.add_argument('--max-length', type=int, default=512, help="Max sequence length for embedding model.")
    parser.add_argument('--reranker', type=str, default='BAAI/bge-reranker-base', help="Reranker model name.")
    
    # RAG args (Gemini-specific)
    parser.add_argument('--gen-model', type=str, default=None, help="Generative model name (default from .env GEMINI_MODEL or gemini-2.5-flash-lite).")
    parser.add_argument('--top-k', type=int, default=20, help="Number of initial results to fetch.")
    parser.add_argument('--rerank-top-n', type=int, default=5, help="Number of final results to use for context.")

    args = parser.parse_args()
    
    log_dir = Path('logs')
    logger, err_logger = setup_rag_logging(log_dir)

    try:
        logger.info("--- Initializing RAG Pipeline with Gemini API ---")
        
        retriever = Retriever(
            es_host=args.es_host,
            index_name=args.index_name,
            model_name=args.embed_model,
            max_length=args.max_length,
            reranker_name=args.reranker,
            log_dir=log_dir
        )
        
        rag_pipeline = RAGPipeline(
            retriever=retriever,
            gen_model_name=args.gen_model,
            log_dir=log_dir
        )
        
        answer, sources = rag_pipeline.generate_answer(
            query=args.query,
            top_k=args.top_k,
            rerank_top_n=args.rerank_top_n
        )
        
        print("\n" + "="*50)
        print(f"Query: {args.query}\n")
        print(f"Answer: {answer}\n")
        if sources:
            print(f"Sources: {', '.join(sources)}")
        print("="*50)

    except Exception as e:
        logger.error(f"A critical error occurred in the RAG pipeline: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()