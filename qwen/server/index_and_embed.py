"""
Embedding & Indexing Pipeline (Task C)

This script reads processed chunks, generates embeddings using Hugging Face
'AutoModel' and 'AutoTokenizer' (e.g., for Gemma), and indexes them
into a ChromaDB vector database.

This manual approach involves:
1. Tokenizing text.
2. Passing tokens to the model.
3. Performing mean pooling on the last hidden state.
4. Normalizing the resulting embedding.

It supports two modes:
1. 'index': Creates or updates the vector index.
2. 'query': Runs a query against the index with optional reranking.

Vector DB: ChromaDB (persistent, local)
Embedding Models: Hugging Face 'transformers' (e.g., 'google/embedding-gemma-2b')
Reranker Model: CrossEncoder (e.g., 'BAAI/bge-reranker-base')

Usage:
1. Install dependencies:
   pip install chromadb transformers torch tqdm sentence-transformers

2. To index with a model like embedding-gemma (note the high max_length):
   python indexing.py --mode index \
                      --model 'google/embedding-gemma-2b' \
                      --collection 'k12_gemma' \
                      --max-length 2048

3. To index with a model like BGE:
   python indexing.py --mode index \
                      --model 'BAAI/bge-base-en-v1.5' \
                      --collection 'k12_bge' \
                      --max-length 512

4. To query your data (model/collection must match!):
   python indexing.py --mode query \
                      --model 'google/embedding-gemma-2b' \
                      --collection 'k12_gemma' \
                      --max-length 2048 \
                      --query "What are the properties of alkali metals?"
"""

import os
import sys
import json
import torch
import logging
import argparse
import chromadb
import torch.nn.functional as F
from pathlib import Path
from tqdm import tqdm
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from transformers import AutoTokenizer, AutoModel
from sentence_transformers import CrossEncoder # Still used for reranking

from retrieval import Retriever

# ------------------- Logging setup -------------------

def setup_logging(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    ingest_log = log_dir / 'indexing.log'
    error_log = log_dir / 'indexing_errors.log'

    logger = logging.getLogger('index')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        fh = logging.FileHandler(ingest_log, encoding='utf-8')
        fh.setLevel(logging.INFO)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        logger.addHandler(fh)
        logger.addHandler(ch)

    err_logger = logging.getLogger('index_errors')
    err_logger.setLevel(logging.WARNING)
    err_logger.propagate = False
    
    if not err_logger.handlers:
        efh = logging.FileHandler(error_log, encoding='utf-8')
        efh.setLevel(logging.WARNING)
        efh.setFormatter(formatter)
        err_logger.addHandler(efh)

    return logger, err_logger


# ------------------- Manual Embedding Helper Functions -------------------

def mean_pooling(model_output, attention_mask):
    """
    Performs mean pooling on the last hidden state.
    This averages all token embeddings, ignoring padding tokens.
    """
    # model_output[0] is the last_hidden_state
    token_embeddings = model_output.last_hidden_state
    
    # Expand attention mask to match the shape of token_embeddings
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    
    # Sum embeddings, masked by the attention mask
    sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
    
    # Sum the attention mask (to get the number of non-padding tokens)
    sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
    
    # Return the average
    return sum_embeddings / sum_mask

def get_embeddings(
    texts: list[str], 
    model, 
    tokenizer, 
    device, 
    max_length: int
) -> list[list[float]]:
    """
    Generates normalized embeddings for a list of texts using
    manual tokenization, pooling, and normalization.
    """
    if not texts:
        return []
        
    # Tokenize the texts
    inputs = tokenizer(
        texts, 
        padding=True, 
        truncation=True, 
        return_tensors='pt', 
        max_length=max_length
    ).to(device)
    
    # Run model inference
    with torch.no_grad():
        model_output = model(**inputs)
    
    # Perform mean pooling
    embeddings = mean_pooling(model_output, inputs['attention_mask'])
    
    # Normalize embeddings
    normalized_embeddings = F.normalize(embeddings, p=2, dim=1)
    
    # Move to CPU and convert to list
    return normalized_embeddings.cpu().tolist()


# ------------------- Indexing Function -------------------

def run_indexing(
    chunks_file: Path, 
    es_host: str,
    index_name: str, 
    model_name: str, 
    max_length: int,
    batch_size: int,
    logger, 
    err_logger,
    delete_existing: bool = False
):
    """Reads chunks, creates embeddings, and indexes them into Elasticsearch."""
    
    logger.info(f"Setting up Elasticsearch client at: {es_host}")
    try:
        es = Elasticsearch(hosts=[es_host])
        if not es.ping():
            raise ConnectionError("Could not connect to Elasticsearch.")
    except Exception as e:
        logger.error(f"Failed to connect to Elasticsearch: {e}")
        return

    # Determine device
    device = 'cuda' if torch.cuda.is_available() else ('mps' if torch.backends.mps.is_available() else 'cpu')
    logger.info(f"Using device: {device}")
    
    logger.info(f"Loading tokenizer: {model_name}")
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        logger.info(f"Loading embedding model: {model_name}")
        embed_model = AutoModel.from_pretrained(model_name).to(device)
        embed_model.eval()
        
        # Get embedding dimension from model config
        embed_dim = embed_model.config.hidden_size
        logger.info(f"Embedding dimension for '{model_name}': {embed_dim}")

    except Exception as e:
        logger.error(f"Failed to load model/tokenizer for '{model_name}': {e}")
        return

    # --- Create Elasticsearch Index with Mapping ---
    index_mapping = {
        "properties": {
            "embedding": {
                "type": "dense_vector",
                "dims": embed_dim,
                "index": "true",
                "similarity": "cosine" 
            },
            "chunk_text": {
                "type": "text" # For BM25 keyword search
            },
            "parent_id": {"type": "keyword"},
            "parent_chunk_id": {"type": "keyword"},
            "source_path": {"type": "keyword"},
            "filename": {"type": "keyword"},
            "chunk_size": {"type": "integer"},
            "start_pos": {"type": "integer"},
            "end_pos": {"type": "integer"}
        }
    }
    
    try:
        # If the index already exists and the user requested deletion, remove it
        # and recreate it with the desired mapping. Otherwise, create the index
        # if it doesn't exist or keep it as-is.
        if es.indices.exists(index=index_name):
            if delete_existing:
                logger.info(f"Index '{index_name}' exists and --delete-existing specified. Deleting index.")
                try:
                    es.indices.delete(index=index_name, ignore=[400, 404])
                    logger.info(f"Recreating Elasticsearch index '{index_name}' with mapping.")
                    es.indices.create(index=index_name, mappings=index_mapping)
                except Exception as e:
                    logger.error(f"Failed to delete/recreate index '{index_name}': {e}")
                    return
            else:
                logger.info(f"Index '{index_name}' already exists. Will add/update documents.")
        else:
            logger.info(f"Creating Elasticsearch index '{index_name}' with mapping.")
            es.indices.create(index=index_name, mappings=index_mapping)
    except Exception as e:
        logger.error(f"Failed to create/check/delete index '{index_name}': {e}")
        return

    actions = []
    total_chunks = 0
    
    logger.info(f"Starting to read chunks from: {chunks_file}")
    
    try:
        with open(chunks_file, 'r', encoding='utf-8') as f:
            for line in f:
                total_chunks += 1
                
        with open(chunks_file, 'r', encoding='utf-8') as f:
            pbar = tqdm(f, total=total_chunks, desc="Preparing batches for Elasticsearch")
            for line in pbar:
                try:
                    chunk = json.loads(line)
                    
                    # The document to be indexed in ES
                    doc = {
                        "chunk_text": chunk['chunk_text'],
                        "parent_id": chunk['parent_id'],
                        "parent_chunk_id": chunk.get('parent_chunk_id'), # Use .get for safety
                        "source_path": chunk['source_path'],
                        "filename": chunk['filename'],
                        "chunk_size": chunk['chunk_size_tokens'],
                        "start_pos": chunk['start_position'],
                        "end_pos": chunk['end_position']
                    }
                    
                    # Action for the bulk helper
                    action = {
                        "_op_type": "index",
                        "_index": index_name,
                        "_id": chunk['chunk_id'],
                        "_source": doc
                    }
                    actions.append(action)
                    
                    if len(actions) >= batch_size:
                        process_es_batch(
                            es, actions, embed_model, tokenizer, 
                            device, max_length, logger
                        )
                        actions = []
                        
                except json.JSONDecodeError:
                    err_logger.warning(f"Skipping malformed line in {chunks_file}")
                except Exception as e:
                    err_logger.warning(f"Error processing chunk: {e}")

            # Process any remaining actions
            if actions:
                process_es_batch(
                    es, actions, embed_model, tokenizer, 
                    device, max_length, logger
                )
                
    except FileNotFoundError:
        logger.error(f"FATAL: Chunks file not found at {chunks_file}")
        logger.error("Please run the ingestion pipeline first.")
        return
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

    logger.info(f"--- Indexing complete ---")
    es.indices.refresh(index=index_name)
    doc_count = es.count(index=index_name)['count']
    logger.info(f"Total documents in index '{index_name}': {doc_count}")

def process_es_batch(
    es: Elasticsearch, actions: list, embed_model, tokenizer, 
    device, max_length: int, logger
):
    """Helper to embed and bulk index a batch into Elasticsearch."""
    try:
        texts_to_embed = [action['_source']['chunk_text'] for action in actions]
        
        embeddings = get_embeddings(
            texts_to_embed, embed_model, tokenizer, device, max_length
        )
        
        # Add the embedding to each document in the batch
        for i, action in enumerate(actions):
            action['_source']['embedding'] = embeddings[i]
            
        # Use the bulk helper
        success, failed = bulk(es, actions, raise_on_error=False, raise_on_exception=False)
        
        if failed:
            logger.warning(f"Bulk indexing failed for {len(failed)} documents.")
            for item in failed:
                logging.getLogger('index_errors').warning(f"Failed item: {item}")

    except Exception as e:
        logger.error(f"Failed to process batch for Elasticsearch: {e}")
        for action in actions:
            logging.getLogger('index_errors').warning(f"Failed to index chunk_id: {action.get('_id')}")




# ------------------- CLI -------------------

def main():
    parser = argparse.ArgumentParser(description='Embedding & Indexing Pipeline for Elasticsearch')
    parser.add_argument('--mode', type=str, required=True, choices=['index'],
                        help="Mode to run: 'index' to build the DB.")
    parser.add_argument('--chunks-file', type=Path, default='processed/chunks.jsonl',
                        help="Path to the input JSONL file with processed chunks.")
    parser.add_argument('--es-host', type=str, default='http://localhost:9200',
                        help="URL of the Elasticsearch host.")
    parser.add_argument('--index-name', type=str, default='periodic-table-hybrid-search',
                        help="Name of the Elasticsearch index.")
    parser.add_argument('--model', type=str, default='BAAI/bge-base-en-v1.5',
                        help="Name of the Hugging Face model for embeddings.")
    parser.add_argument('--max-length', type=int, default=512,
                        help="Max sequence length for the tokenizer.")
    parser.add_argument('--batch-size', type=int, default=100,
                        help="Batch size for indexing.")
    parser.add_argument('--delete-existing', action='store_true', default=False,
                        help="If set, delete the Elasticsearch index with the same name before recreating it.")
    
    args = parser.parse_args()
    
    log_dir = Path('logs')
    logger, err_logger = setup_logging(log_dir)

    if args.mode == 'index':
        logger.info(f"--- Starting mode: INDEX ---")
        run_indexing(
            chunks_file=args.chunks_file,
            es_host=args.es_host,
            index_name=args.index_name,
            model_name=args.model,
            max_length=args.max_length,
            batch_size=args.batch_size,
            logger=logger,
            err_logger=err_logger,
            delete_existing=args.delete_existing
        )

if __name__ == '__main__':
    main()