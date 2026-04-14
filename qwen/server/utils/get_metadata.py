"""
collect_metadata.py
====================
Automatically detect file types in `data/` and generate a metadata file.

This script corresponds to Section A: Document Collection & Organization.
"""

import os
import hashlib
import json
from datetime import datetime
import mimetypes
from tqdm import tqdm

# ====== CONFIGURATION ======
DATA_DIR = "./Textbook_data"       # your folder containing all documents
OUTPUT_FILE = "./metadata.jsonl"


# ====== HELPERS ======

def compute_sha1(file_path, block_size=65536):
    """Compute a SHA-1 hash for deduplication and integrity checking."""
    sha1 = hashlib.sha1()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(block_size), b""):
            sha1.update(block)
    return sha1.hexdigest()


def detect_filetype(file_path):
    """Infer file type based on extension and mimetype."""
    ext = os.path.splitext(file_path)[-1].lower()
    mime_type, _ = mimetypes.guess_type(file_path)
    
    if ext == ".pdf":
        return "PDF"
    elif ext == ".docx":
        return "DOCX"
    elif ext == ".pptx":
        return "PPTX"
    elif ext in [".txt", ".md"]:
        return "TEXT"
    elif mime_type and "text" in mime_type:
        return "TEXT"
    else:
        return "UNKNOWN"


def generate_metadata(file_path):
    """Generate structured metadata for one document."""
    stats = os.stat(file_path)
    file_info = {
        "filename": os.path.basename(file_path),
        "filepath": os.path.abspath(file_path),
        "filetype": detect_filetype(file_path),
        "size_kb": round(stats.st_size / 1024, 2),
        "created_time": datetime.fromtimestamp(stats.st_ctime).isoformat(),
        "modified_time": datetime.fromtimestamp(stats.st_mtime).isoformat(),
        "sha1": compute_sha1(file_path),
        "source": detect_source(file_path),
        "subject": "Chemistry",
        "context": detect_context(file_path),
        "timestamp": datetime.now().isoformat(),
        "class": 00, # Placeholder for class/grade level
        "title": "Add Manually", # Placeholder for title
    }
    return file_info


def detect_source(filename):
    """Heuristic for identifying content source from filename."""
    name = filename.lower()
    if "ncert" in name:
        return "NCERT"
    elif "khan" in name:
        return "Khan Academy"
    elif "britannica" in name:
        return "Britannica Kids"
    elif "byjus" in name:
        return "BYJU'S"
    else:
        return "Unknown"


def detect_context(filename):
    """Infer document context/topic from filename."""
    name = filename.lower()
    if "periodic" in name or "element" in name:
        return "Periodic Table"
    elif "atom" in name:
        return "Structure of Atom"
    elif "bond" in name:
        return "Chemical Bonding"
    else:
        return "General Chemistry"


# ====== MAIN PIPELINE ======

def collect_all_metadata():
    """Walk through DATA_DIR and build metadata records."""
    records = []
    for root, _, files in os.walk(DATA_DIR):
        for file in tqdm(files, desc="Collecting metadata"):
            file_path = os.path.join(root, file)
            try:
                record = generate_metadata(file_path)
                records.append(record)
            except Exception as e:
                print(f"Error processing {file}: {e}")
    return records


def save_metadata(records, output_file=OUTPUT_FILE):
    """Save metadata list as JSONL."""
    with open(output_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"Metadata saved: {len(records)} records → {output_file}")


if __name__ == "__main__":
    all_metadata = collect_all_metadata()
    save_metadata(all_metadata)
