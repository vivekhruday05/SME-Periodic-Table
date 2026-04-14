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
import torch
import logging
import argparse
from pathlib import Path
from transformers import AutoTokenizer, AutoModelForCausalLM
from retrieval import Retriever

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
    def __init__(self, retriever: Retriever, gen_model_name: str, log_dir: Path = Path('logs'), quantize_8bit: bool = False):
        self.retriever = retriever
        self.gen_model_name = gen_model_name
        self.logger, self.err_logger = setup_rag_logging(log_dir)
        self._is_qwen = 'qwen' in self.gen_model_name.lower()
        self.quantize_8bit = quantize_8bit

        self.device = 'cuda' if torch.cuda.is_available() else ('mps' if torch.backends.mps.is_available() else 'cpu')
        self.logger.info(f"Using device: {self.device}")

        # Defer loading the generation model until after retrieval and reranker unload
        self.gen_model = None
        self.gen_tokenizer = None

    def _load_generation_model(self):
        """Loads the generative language model."""
        self.logger.info(f"Loading generation model: {self.gen_model_name}")
        try:
            self.gen_tokenizer = AutoTokenizer.from_pretrained(self.gen_model_name)
            # Try to import bitsandbytes for 8-bit quantization support
            has_bnb = True
            try:
                import bitsandbytes as bnb  # noqa: F401
            except Exception:
                has_bnb = False

            if self._is_qwen:
                # Qwen recommended loading: device_map and auto dtype
                if self.quantize_8bit and has_bnb:
                    self.logger.info("Loading Qwen model in 8-bit mode using bitsandbytes.")
                    self.gen_model = AutoModelForCausalLM.from_pretrained(
                        self.gen_model_name,
                        load_in_8bit=True,
                        device_map="cuda",
                        torch_dtype="auto"
                    )
                else:
                    if self.quantize_8bit and not has_bnb:
                        self.logger.warning("Requested 8-bit quantization but 'bitsandbytes' is not installed. Loading full-precision model.")
                    self.gen_model = AutoModelForCausalLM.from_pretrained(
                        self.gen_model_name,
                        torch_dtype="auto",
                        device_map="auto"
                    )
            else:
                # Non-Qwen models: allow optional 8-bit loading when bitsandbytes is available
                if self.quantize_8bit and has_bnb:
                    self.logger.info("Loading model in 8-bit mode using bitsandbytes.")
                    self.gen_model = AutoModelForCausalLM.from_pretrained(
                        self.gen_model_name,
                        load_in_8bit=True,
                        device_map="auto"
                    )
                else:
                    self.gen_model = AutoModelForCausalLM.from_pretrained(
                        self.gen_model_name,
                        torch_dtype=torch.bfloat16 if self.device == 'cuda' else torch.float32
                    ).to(self.device)
        except Exception as e:
            self.logger.error(f"Failed to load generation model '{self.gen_model_name}': {e}")
            raise

    def generate_answer(self, query: str, top_k: int = 20, rerank_top_n: int = 5):
        """
        Orchestrates the RAG pipeline from query to answer.
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

        # 1c. Now load the generation model (possibly large) to use freed VRAM
        if self.gen_model is None or self.gen_tokenizer is None:
            self._load_generation_model()
        
    # 2. Format the prompt using the model's native chat template
        self.logger.info("Step 2: Formatting prompt with chat template...")
        context_str = "\n\n---\n\n".join([chunk['_source']['chunk_text'] for chunk in context_chunks])
        # Structured prompt via chat template
        messages = [
            {"role": "system", "content": (
                "You are a helpful assistant for a K-12 student. "
                "You MUST answer the user's question only using the context provided. "
                "Do not use any outside knowledge. "
                "If the answer is not in the context, say: 'I'm sorry, but I couldn't find that information in the provided documents.' "
                "Be concise and clear."
            )},
            {"role": "user", "content": f"Context:\n{context_str}\n\nQuestion: {query}"}
        ]
        
        # The tokenizer will apply the conversation template. For Qwen, enable_thinking per docs.
        if self._is_qwen:
            prompt = self.gen_tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=True
            )
        else:
            prompt = self.gen_tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )

    # 3. Generate the answer
        self.logger.info("Step 3: Generating answer...")
        try:
            # Re-tokenize the full templated prompt
            inputs = self.gen_tokenizer([prompt], return_tensors='pt')
            # Send to the correct device
            if self._is_qwen:
                inputs = inputs.to(self.gen_model.device)
                generated_ids = self.gen_model.generate(
                    **inputs,
                    max_new_tokens=2048
                )
                output_ids = generated_ids[0][len(inputs.input_ids[0]):].tolist()

                # Parse thinking content for Qwen (</think> token id 151668 per docs)
                try:
                    index = len(output_ids) - output_ids[::-1].index(151668)
                except ValueError:
                    index = 0

                thinking_content = self.gen_tokenizer.decode(output_ids[:index], skip_special_tokens=True).strip("\n")
                content = self.gen_tokenizer.decode(output_ids[index:], skip_special_tokens=True).strip("\n")
                answer = content
                if thinking_content:
                    self.logger.info("Model thinking content captured (truncated to 300 chars): " + thinking_content[:300])
            else:
                inputs = inputs.to(self.device)
                outputs = self.gen_model.generate(
                    **inputs,
                    max_new_tokens=2048,
                    do_sample=True,
                    temperature=0.7,
                    top_p=0.95
                )
                # Decode the output, skipping the prompt part
                answer = self.gen_tokenizer.decode(outputs[0][len(inputs['input_ids'][0]):], skip_special_tokens=True)

        except Exception as e:
            self.err_logger.error(f"Error during text generation: {e}")
            return "I encountered an error while trying to generate an answer.", []

        # 4. Collect sources
        sources = list(set([chunk['_source']['filename'] for chunk in context_chunks]))
        
        # 5. Offload generation model to free VRAM
        try:
            self._offload_generation_model()
        except Exception:
            pass

        return answer.strip(), sources

    def _offload_generation_model(self):
        """Move or unload the generation model to free GPU memory."""
        if self.gen_model is None:
            return
        try:
            try:
                # Attempt to move to CPU if supported
                self.gen_model.to('cpu')
            except Exception:
                pass
            # Drop strong reference and clear caches
            gm = self.gen_model
            self.gen_model = None
            del gm
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            self.err_logger.warning(f"Failed to offload generation model: {e}")

# ------------------- CLI -------------------

def main():
    parser = argparse.ArgumentParser(description='Retrieval-Augmented Generation (RAG) Pipeline')
    parser.add_argument('--query', type=str, required=True, help="Search query.")
    # Retriever args
    parser.add_argument('--es-host', type=str, default='http://localhost:9200', help="Elasticsearch host.")
    parser.add_argument('--index-name', type=str, default='periodic-table-hybrid-search', help="Elasticsearch index name.")
    parser.add_argument('--embed-model', type=str, default='BAAI/bge-base-en-v1.5', help="Embedding model name.")
    parser.add_argument('--max-length', type=int, default=512, help="Max sequence length for embedding model.")
    parser.add_argument('--reranker', type=str, default='BAAI/bge-reranker-base', help="Reranker model name.")
    
    # RAG args
    parser.add_argument('--gen-model', type=str, default='Qwen/Qwen3-1.7B', help="Generative model name.")
    parser.add_argument('--top-k', type=int, default=20, help="Number of initial results to fetch.")
    parser.add_argument('--rerank-top-n', type=int, default=5, help="Number of final results to use for context.")
    parser.add_argument('--quantize-8bit', action='store_true', help='Load the generation model in 8-bit (requires bitsandbytes).')

    args = parser.parse_args()
    
    log_dir = Path('logs')
    logger, err_logger = setup_rag_logging(log_dir)

    try:
        logger.info("--- Initializing RAG Pipeline ---")
        
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
            log_dir=log_dir,
            quantize_8bit=args.quantize_8bit
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
