"""
Evaluation script for the RAG pipeline on a given evaluation set.

This script performs the following steps:
1.  Loads a JSON evaluation set containing questions and correct answers.
2.  Initializes the RAG pipeline.
3.  For each question in the evaluation set:
    a.  Generates an answer using the RAG pipeline.
    b.  Parses the generated answer and the correct answer to extract the selected option (e.g., 'a', 'b', 'c', 'd').
4.  Stores the questions, generated answers, parsed predicted options, and correct options.
5.  Calculates evaluation metrics (accuracy, precision, recall, F1-score) using a classification report.
6.  Saves the detailed results to a CSV file and the classification report to a text file.

Usage:
    python gemini/evaluation/evaluate_rag.py \
        --eval-file gemini/evaluation_set/eval_set.json \
        --output-dir gemini/evaluation/results
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
import pandas as pd
import re
from sklearn.metrics import classification_report, accuracy_score
from tqdm import tqdm

# Add the parent directory to sys.path to allow imports from the 'gemini' folder
sys.path.append(str(Path(__file__).resolve().parent.parent))

from rag import RAGPipeline
from retrieval import Retriever

# --- Logging Setup ---
def setup_eval_logging(log_dir: Path):
    """Sets up logging for the evaluation script."""
    log_dir.mkdir(parents=True, exist_ok=True)
    eval_log_file = log_dir / 'evaluation.log'
    
    logger = logging.getLogger('evaluation')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Clear existing handlers to avoid duplicate logs
    if logger.hasHandlers():
        logger.handlers.clear()

    # File handler for logging to a file
    fh = logging.FileHandler(eval_log_file, mode='w', encoding='utf-8')
    fh.setLevel(logging.INFO)
    
    # Stream handler for logging to the console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger

# --- Answer Parsing ---
def parse_option(text: str) -> str:
    """
    Parses a string to find a multiple-choice option (e.g., (a), (b)).
    Returns the letter ('a', 'b', 'c', 'd') if found, otherwise 'not_found'.
    """
    if not isinstance(text, str):
        return 'not_found'

    # Regex to find patterns like (a), (b), a), b., Option (a), Option b
    match = re.search(r'(?:option\s*\(?|\b)([a-d])\)?', text, re.IGNORECASE)
    
    if match:
        return match.group(1).lower()
    
    return 'not_found'

# --- Main Evaluation Logic ---
def main():
    parser = argparse.ArgumentParser(description='Evaluate the RAG pipeline.')
    parser.add_argument('--eval-file', type=str, required=True, help="Path to the JSON evaluation file.")
    parser.add_argument('--output-dir', type=str, required=True, help="Directory to save evaluation results.")
    
    # Retriever args
    parser.add_argument('--es-host', type=str, default='http://localhost:9200', help="Elasticsearch host.")
    parser.add_argument('--index-name', type=str, default='periodic-table-hybrid-search', help="Elasticsearch index name.")
    parser.add_argument('--embed-model', type=str, default='BAAI/bge-base-en-v1.5', help="Embedding model name.")
    parser.add_argument('--reranker', type=str, default='BAAI/bge-reranker-base', help="Reranker model name.")
    
    # RAG args
    parser.add_argument('--gen-model', type=str, default=None, help="Generative model name (from .env or default).")
    parser.add_argument('--top-k', type=int, default=20, help="Number of initial results to fetch.")
    parser.add_argument('--rerank-top-n', type=int, default=5, help="Number of final results for context.")

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    logger = setup_eval_logging(output_dir)

    # --- Load Evaluation Data ---
    logger.info(f"Loading evaluation data from: {args.eval_file}")
    try:
        with open(args.eval_file, 'r', encoding='utf-8') as f:
            eval_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load or parse evaluation file: {e}")
        sys.exit(1)

    # --- Initialize RAG Pipeline ---
    logger.info("Initializing RAG pipeline...")
    try:
        retriever = Retriever(
            es_host=args.es_host,
            index_name=args.index_name,
            model_name=args.embed_model,
            reranker_name=args.reranker,
            log_dir=output_dir
        )
        rag_pipeline = RAGPipeline(
            retriever=retriever,
            gen_model_name=args.gen_model,
            log_dir=output_dir
        )
    except Exception as e:
        logger.error(f"Failed to initialize RAG pipeline: {e}")
        sys.exit(1)

    # --- Run Evaluation ---
    results = []
    logger.info(f"Starting evaluation on {len(eval_data)} questions...")

    for item in tqdm(eval_data, desc="Evaluating Questions"):
        question = item.get("question")
        correct_answer_text = item.get("correct_answer")

        if not question or not correct_answer_text:
            logger.warning(f"Skipping item due to missing 'question' or 'correct_answer': {item}")
            continue

        # Generate answer
        generated_answer, _ = rag_pipeline.generate_answer(
            query=question,
            top_k=args.top_k,
            rerank_top_n=args.rerank_top_n
        )

        # Parse options
        predicted_option = parse_option(generated_answer)
        correct_option = parse_option(correct_answer_text)

        results.append({
            "question": question,
            "correct_answer_text": correct_answer_text,
            "generated_answer": generated_answer,
            "correct_option": correct_option,
            "predicted_option": predicted_option,
            "is_correct": 1 if predicted_option == correct_option and correct_option != 'not_found' else 0
        })

    # --- Process and Save Results ---
    logger.info("Evaluation complete. Processing results...")
    results_df = pd.DataFrame(results)
    
    # Save detailed results to CSV
    results_csv_path = output_dir / "evaluation_results.csv"
    results_df.to_csv(results_csv_path, index=False, encoding='utf-8')
    logger.info(f"Detailed results saved to: {results_csv_path}")

    # --- Generate and Save Classification Report ---
    y_true = results_df["correct_option"]
    y_pred = results_df["predicted_option"]
    
    # Ensure labels are consistent
    labels = sorted(list(set(y_true) | set(y_pred)))
    
    report = classification_report(y_true, y_pred, labels=labels, zero_division=0)
    accuracy = accuracy_score(y_true, y_pred)

    report_str = f"Classification Report:\n\n{report}\n"
    report_str += f"Overall Accuracy: {accuracy:.4f}\n"

    report_path = output_dir / "classification_report.txt"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_str)

    logger.info(f"Classification report saved to: {report_path}")
    print("\n" + report_str)

if __name__ == '__main__':
    main()
