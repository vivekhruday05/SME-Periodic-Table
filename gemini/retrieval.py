"""
Reusable retrieval logic for querying the Elasticsearch index.

This module provides a `Retriever` class that encapsulates the logic for:
- Connecting to Elasticsearch.
- Loading embedding and reranking models.
- Performing hybrid search (vector + keyword).
- Implementing "small-to-big" retrieval to fetch parent documents for context.
"""

import os
import sys
import json
import torch
import logging
from pathlib import Path
from elasticsearch import Elasticsearch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel
from sentence_transformers import CrossEncoder

# ------------------- Logging setup -------------------

def setup_retrieval_logging(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    retrieval_log = log_dir / 'retrieval.log'
    error_log = log_dir / 'retrieval_errors.log'

    logger = logging.getLogger('retrieval')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        fh = logging.FileHandler(retrieval_log, encoding='utf-8')
        fh.setLevel(logging.INFO)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        logger.addHandler(fh)
        logger.addHandler(ch)

    err_logger = logging.getLogger('retrieval_errors')
    err_logger.setLevel(logging.WARNING)
    err_logger.propagate = False
    
    if not err_logger.handlers:
        efh = logging.FileHandler(error_log, encoding='utf-8')
        efh.setLevel(logging.WARNING)
        efh.setFormatter(formatter)
        err_logger.addHandler(efh)

    return logger, err_logger

class Retriever:
    """
    Handles retrieval from an Elasticsearch index, including "small-to-big" logic.
    """
    def __init__(
        self, 
        es_host: str = os.getenv("ES_HOST", "http://localhost:9200"), 
        index_name: str = os.getenv("ES_INDEX", "periodic-table-hybrid-search"), 
        model_name: str = os.getenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5"), 
        max_length: int = 512, 
        reranker_name: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base"),
        log_dir: Path = Path('logs')
    ):
        self.logger, self.err_logger = setup_retrieval_logging(log_dir)
        
        self.es_host = es_host
        self.index_name = index_name
        self.model_name = model_name
        self.max_length = max_length
        self.reranker_name = reranker_name

        self.logger.info(f"Setting up Elasticsearch client at: {self.es_host}")
        try:
            self.es = Elasticsearch(hosts=[self.es_host])
            if not self.es.ping():
                raise ConnectionError("Could not connect to Elasticsearch.")
        except Exception as e:
            self.logger.error(f"Failed to connect to Elasticsearch: {e}")
            raise

        # Preferred compute device; models will be loaded on CPU by default and moved just-in-time
        self.device = 'cuda' if torch.cuda.is_available() else ('mps' if torch.backends.mps.is_available() else 'cpu')
        self.logger.info(f"Preferred device: {self.device}")

        self._load_models()

    def _load_models(self):
        """Loads the embedding and reranker models."""
        try:
            self.logger.info(f"Loading tokenizer: {self.model_name}")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.logger.info(f"Loading embedding model on CPU: {self.model_name}")
            # Load on CPU to avoid occupying VRAM at startup
            self.embed_model = AutoModel.from_pretrained(self.model_name).to('cpu')
            self.embed_model.eval()
        except Exception as e:
            self.logger.error(f"Failed to load embedding model/tokenizer for '{self.model_name}': {e}")
            raise

        self.rerank_model = None
        if self.reranker_name:
            self.logger.info(f"Loading reranker model on CPU: {self.reranker_name}")
            try:
                # Initialize on CPU; we'll move to GPU just-in-time during reranking
                self.rerank_model = CrossEncoder(self.reranker_name, device='cpu')
            except Exception as e:
                self.logger.error(f"Failed to load CrossEncoder model '{self.reranker_name}': {e}")
                self.logger.error("Reranking will be disabled.")

    def _mean_pooling(self, model_output, attention_mask):
        token_embeddings = model_output.last_hidden_state
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
        sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        return sum_embeddings / sum_mask

    def _get_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # Send inputs to the same device as the embedding model
        model_device = next(self.embed_model.parameters()).device
        inputs = self.tokenizer(
            texts, padding=True, truncation=True, return_tensors='pt', max_length=self.max_length
        )
        inputs = {k: v.to(model_device) for k, v in inputs.items()}

        with torch.no_grad():
            model_output = self.embed_model(**inputs)

        embeddings = self._mean_pooling(model_output, inputs['attention_mask'])
        normalized_embeddings = F.normalize(embeddings, p=2, dim=1)
        return normalized_embeddings.cpu().tolist()

    # ------------------- Device management helpers -------------------
    def move_embed_to(self, device: str = 'cpu'):
        try:
            if self.embed_model is not None:
                self.embed_model.to(device)
        except Exception as e:
            self.err_logger.warning(f"Failed to move embedding model to {device}: {e}")

    def move_reranker_to(self, device: str = 'cpu'):
        try:
            if self.rerank_model is not None:
                # CrossEncoder wraps HF model at .model
                self.rerank_model.model.to(device)
                try:
                    # Keep internal target device in sync (used for tensor placement)
                    self.rerank_model._target_device = torch.device(device)
                except Exception:
                    pass
        except Exception as e:
            self.err_logger.warning(f"Failed to move reranker to {device}: {e}")

    def offload_models_to_cpu(self):
        """Move retriever models to CPU and clear CUDA cache to free VRAM."""
        self.move_embed_to('cpu')
        self.move_reranker_to('cpu')
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def search(self, query: str, top_k: int = 20, rerank_top_n: int = 5):
        """
        Performs a hybrid search and implements "small-to-big" retrieval.
        """
        self.logger.info(f"--- Query: '{query}' ---")

        if not self.es.indices.exists(index=self.index_name):
            self.logger.error(f"Index '{self.index_name}' does not exist. Run indexing first.")
            return []

        # 1. Embed the query (move embed model to preferred device just-in-time)
        self.logger.info("Moving embedding model to compute device for embedding...")
        self.move_embed_to(self.device)
        try:
            query_embedding = self._get_embeddings([query])[0]
        finally:
            # Offload embedding model back to CPU immediately after use
            self.logger.info("Offloading embedding model back to CPU...")
            self.move_embed_to('cpu')
            try:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        
        # 2. Construct the hybrid query
        es_query = {
            "knn": {
                "field": "embedding",
                "query_vector": query_embedding,
                "k": top_k,
                "num_candidates": top_k * 2
            },
            "query": {
                "match": {
                    "chunk_text": {
                        "query": query,
                        "boost": 0.1
                    }
                }
            }
        }
        
        self.logger.info(f"Step 1: Retrieving top {top_k} hybrid results from Elasticsearch...")
        try:
            results = self.es.search(
                index=self.index_name,
                body={"query": es_query["query"], "knn": es_query["knn"]},
                size=top_k
            )
        except Exception as e:
            self.logger.error(f"Error querying Elasticsearch: {e}")
            return []

        hits = results['hits']['hits']
        if not hits:
            self.logger.warning("No results found in the database for this query.")
            return []

        # 3. Rerank results
        initial_docs = [hit['_source']['chunk_text'] for hit in hits]
        if self.rerank_model:
            self.logger.info(f"Step 2: Reranking {len(initial_docs)} results...")
            pairs = [(query, doc) for doc in initial_docs]
            # Move reranker to GPU/MPS just-in-time
            self.logger.info("Moving reranker to compute device for reranking...")
            self.move_reranker_to(self.device)
            try:
                scores = self.rerank_model.predict(pairs, show_progress_bar=False)
            finally:
                self.logger.info("Offloading reranker back to CPU...")
                self.move_reranker_to('cpu')
                try:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass

            scored_results = list(zip(scores, hits))
            scored_results.sort(key=lambda x: x[0], reverse=True)

            final_hits = [hit for score, hit in scored_results[:rerank_top_n]]
        else:
            self.logger.info("Step 2: Reranker not enabled. Using Elasticsearch scores.")
            final_hits = hits[:rerank_top_n]

        # 4. "Small-to-Big" Retrieval
        self.logger.info("Step 3: Applying 'small-to-big' retrieval logic...")
        final_chunks = []
        fetched_parent_ids = set()

        for hit in final_hits:
            source = hit['_source']
            parent_chunk_id = source.get('parent_chunk_id')

            # If it's a sub-chunk and we haven't fetched its parent yet
            if parent_chunk_id and parent_chunk_id not in fetched_parent_ids:
                try:
                    self.logger.info(f"Fetching parent chunk '{parent_chunk_id}' for child '{hit['_id']}'")
                    parent_doc = self.es.get(index=self.index_name, id=parent_chunk_id)
                    final_chunks.append(parent_doc)
                    fetched_parent_ids.add(parent_chunk_id)
                except Exception as e:
                    self.err_logger.warning(f"Could not fetch parent chunk '{parent_chunk_id}': {e}")
                    # Fallback to using the small chunk
                    final_chunks.append(hit)
            elif not parent_chunk_id:
                # This is already a parent chunk, add it directly
                final_chunks.append(hit)
            # If parent was already fetched, we skip the small chunk to avoid duplication

        self.logger.info(f"Retrieved {len(final_chunks)} final context chunks.")
        return final_chunks

    def unload_reranker(self):
        """Moves the reranker off GPU and releases it to free VRAM."""
        if getattr(self, 'rerank_model', None) is None:
            return
        try:
            # CrossEncoder wraps a HF model at .model
            model = getattr(self.rerank_model, 'model', None)
            if model is not None and hasattr(model, 'to'):
                try:
                    model.to('cpu')
                except Exception:
                    pass
            # Remove strong refs and trigger GC
            self.rerank_model = None
            import gc
            gc.collect()
            if torch.cuda.is_available():
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
            self.logger.info("Reranker unloaded from GPU and memory cleared.")
        except Exception as e:
            self.err_logger.warning(f"Failed to unload reranker cleanly: {e}")
