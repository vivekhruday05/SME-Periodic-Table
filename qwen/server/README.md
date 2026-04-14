# LMA Major Project - Team Aurors
## Vysishtya Karanam - 2022102044
## Vivek Hruday Kavuri - 2022114012

This repository contains the source code of submission of `Team Aurors` for the Major Project of the course `Language Models and Agents`.

## Progress
- Gathered data and Metadata in a semi-automated manner.

High-level steps for ingestion:
- Extract text from each source file (PDF/DOCX/PPTX/TXT/MD). PDFs use `pdfplumber` when available and optionally `pytesseract` for OCR fallback for scanned pages.
- Clean and normalize text (whitespace normalization, heuristic removal of headers/footers, optional lowercasing, unicode fixes).
- Deduplicate documents by SHA256 of the cleaned text.
- Chunk documents at multiple token granularities (default: 2048, 512, 128) using either paragraph-aware packing or sliding-window tokenization, with configurable overlap.
- Emit two main outputs:
	- `processed/chunks.jsonl` — one JSON object per chunk with text, metadata, and parent-child relationships (source doc id, start/end paragraph indices)
	- `processed/docs_manifest.jsonl` — one JSON object per source document with original metadata and ingestion info
- While the ingestion is happening, logs are logged to the `logs` folder

High-level steps for indexing and embedding:
- Read `processed/chunks.jsonl` and generate embeddings using a Hugging Face model (manual tokenization + mean pooling) or a sentence-transformers wrapper.
- Store embeddings and chunk metadata into a local ChromaDB persistent collection (`db/`).
- Support reranking with a CrossEncoder-style model for improved result ranking.
- Provide two modes: `index` (build/update collection) and `query` (search + optional rerank).

## Files and folders

- `ingestion.py` — Main preprocessing and chunking pipeline. Implements text extraction (PDF/DOCX/PPTX/TXT/MD), optional OCR fallback, cleaning, deduplication, paragraph-aware and sliding-window chunking, batching and multiprocessing support, logging, and JSONL outputs.
- `data/` — Root data folder containing source documents and a `metadata.jsonl` manifest that describes the source files.
	- `data/Textbook_data/` — Collection of textbook PDFs used as ingestion sources.
	- `data/Website_Data/` — PDFs collected from web sources (articles, guides) used as ingestion sources.
- `logs/` — Contains runtime logs produced by the ingestion pipeline.
	- `logs/ingest.log` — Informational logs for successful processing steps.
	- `logs/errors.log` — Warning and error logs captured during extraction and processing.
- `processed/` — Outputs produced by the ingestion pipeline.
	- `processed/chunks.jsonl` — Chunk-level JSONL output; each line is a chunk with metadata and links to its parent document.
	- `processed/docs_manifest.jsonl` — Document-level JSONL manifest containing metadata for each ingested source document.
- `utils/get_metadata.py` — Utility to read/prepare `data/metadata.jsonl` entries. Helps standardize metadata fields used by the pipeline.

Additional indexing files
- `index_and_embed.py` — Indexing and query pipeline that loads `processed/chunks.jsonl`, computes embeddings (Hugging Face `AutoModel` + `AutoTokenizer`), and stores them in a ChromaDB collection; includes a query mode with optional CrossEncoder reranking.

`db/` (local ChromaDB files)
- `db/` — Persistent ChromaDB database directory created by the indexing pipeline. Contains SQLite DB file and collection-level binary/index files.


## Repository tree (high level)

Below is a concise view of the repository layout. Data files are elided with "..." for brevity.

```
.
├── data
│   ├── metadata.jsonl         # source manifest describing data files and metadata
│   ├── Textbook_data
│   │   └── ...                # collection of textbook PDFs (multiple .pdf files)
│   └── Website_Data
│       └── ...                # web-scraped or downloaded PDFs
├── ingestion.py               # main ingestion/preprocessing & chunking pipeline script
├── index_and_embed.py         # indexing & embedding pipeline (build/query ChromaDB)
├── db                        # persistent ChromaDB data (created by indexing)
│   ├── chroma.sqlite3
│   └── <collection-id>/       # binary/index files for Chroma collections
│       └── ...
├── logs
│   ├── errors.log             # warnings and extraction errors
│   ├── indexing_errors.log    # warnings/errors during indexing
│   ├── indexing.log           # informational logs for indexing
│   └── ingest.log             # informational ingestion logs
├── processed
│   ├── chunks.jsonl           # chunk-level JSONL output (one JSON object per chunk)
│   └── docs_manifest.jsonl    # document-level JSONL manifest (one JSON object per source doc)
├── README.md                  # this file — methodology, repo tree, and run instructions
└── utils
	└── get_metadata.py        # utilities for reading/preparing metadata entries
```


## Example query:

```bash
python3 index_and_embed.py --mode query --reranker "" --query "smallest element in the periodic table" 
```

```
2025-10-25 21:10:46,209 - INFO - --- Starting mode: QUERY ---
2025-10-25 21:10:46,210 - INFO - Setting up ChromaDB client from: db
2025-10-25 21:10:47,245 - INFO - Using device: cuda
2025-10-25 21:10:47,245 - INFO - Loading tokenizer: BAAI/bge-base-en-v1.5
2025-10-25 21:10:48,061 - INFO - Loading embedding model: BAAI/bge-base-en-v1.5
2025-10-25 21:10:49,118 - INFO - --- Query: 'smallest element in the periodic table' ---
2025-10-25 21:10:49,283 - INFO - Step 1: Retrieving top 20 results from ChromaDB...
2025-10-25 21:10:49,366 - INFO - Retrieved 20 initial results.
2025-10-25 21:10:49,367 - INFO - Step 2: Reranker not enabled. Displaying top results by similarity.

--- Top Similarity Results (No Reranking) ---

Result 1 (Cosine Distance: 0.2144)
Source: kech103.pdf (Chunk Size: 128)
Parent ID: 7b6d7161-643f-4165-bf20-3c139f7ce12b
Chunk ID: 2876ffe2-6e10-4aa7-b676-16d8b0abc068
--------------------
metals of s-block elements and the the compounds of the s-block elements, with less active elements of groups 13 and 14 and thus take their familiar name "transition the exception of those of lithium and beryllium are predominantly ionic. 3.6.4 the f-block elements 3.6.2 the p-block elements the p-block elements comprise those the two rows of elements at the bottom of belonging to group 13 to 18 and these the periodic table, called the lanthanoids, together with the s-block elements are ce(z = 58) - lu(z = 71) and actinoids, called the representative elements or main th(z = 90) - lr (z = 103) are characterised by group elements. the outermost electronic the outer electronic configuration (n-2)f1-14 configuration varies from ns2np1 to ns2np6 (n-1)d0-1ns2. the last electron added
========================================

Result 2 (Cosine Distance: 0.2347)
Source: Fascinating Facts About the Periodic Table.pdf (Chunk Size: 128)
Parent ID: a437a96f-aa59-41d8-aa0a-9443450876b0
Chunk ID: 3a33243f-ef3a-4d31-a37b-1811ed4b5633
--------------------
atomic number (z) atomic mass (in amu) facts about periodic table the periodic table now contains a total of 118 elements. here are some facts about the periodic table. learn live online + hydrogen (h) is the first element and oganesson (0) is the last element (og). * the first periodic table was produced by russian chemist dmitri mendeleev. the contemporary periodic table groups elements with increasing atomic numbers as opposed to mendeleev's table, which arranges elements according to their rising atomic weight. «the periodic table is controlled by the international union of pure applied + the element that is most prevalent in the universe is hydrogen (h). it accounts for roughly 75% of the entire observable cosmos. * the second most prevalent element in the universe is
========================================

Result 3 (Cosine Distance: 0.2384)
Source: kech103.pdf (Chunk Size: 512)
Parent ID: 7b6d7161-643f-4165-bf20-3c139f7ce12b
Chunk ID: c1d1a2af-360e-4be6-baef-2ce832d090c5
--------------------
same element to be the same or different? justify your answer. 3.26 what are the major differences between metals and non-metals? 3.27 use the periodic table to answer the following questions. (a) identify an element with five electrons in the outer subshell. (b) identify an element that would tend to lose two electrons. (c) identify an element that would tend to gain two electrons. (d) identify the group having metal, non-metal, liquid as well as gas at the room 3.28 the increasing order of reactivity among group 1 elements is li < na < k < rb <cs whereas that among group 17 elements is f > ci > br > i. explain. 3.29 write the general outer electronic configuration of s-, p-, d- and f- block elements. 3.30 assign the position of the element having outer electronic configuration (i) ns2np4 for n=3 (ii) (n-1)d2ns2 for n=4, and (iii) (n-2) f 7 (n-1)d1ns2 for n=6, in the unit 3.indd 97 9/9/2022 4:36:15 pm 3.31 the first (∆h ) and the second (∆h ) ionization enthalpies (in kj mol-1) and the (∆ h) i 1 i 2 eg electron gain enthalpy (in kj mol-1) of a few elements are given below: elements ∆h ∆h ∆ h 1 2 eg i 520 7300 -60 ii 419 3051 -48 iii 1681 3374 -328 iv 1008 1846 -295 v 2372 5251 +48 vi 738 1451 -40 which of the above elements is likely to be : (a) the least reactive element. (b) the most reactive metal. (c) the most reactive non-metal. (d) the least reactive non-metal. (e) the metal which can form a stable binary halide of the formula mx (x=halogen). (f) the metal which can form a predominantly stable covalent halide of the formula 3.32 predict the formulas of the stable binary compounds that would be formed by the combination of the following pairs of elements. (a) lithium and oxygen (b) magnesium and nitrogen (c) aluminium and iodine (d) silicon and oxygen (e) phosphorus and fluorine (f) element 71 and fluorine 3.33 in the modern periodic table, the period indicates the value of : (a) atomic number (b) atomic mass (c) principal quantum number (d) azimuthal quantum number. 3.34 which of the following statements related to the modern periodic table is incorrect? (a) the p-block has 6 columns, because a maximum of 6 electrons can occupy all the orbitals in a p-shell. (b) the d-block has 8 columns, because a maximum of 8 electrons can occupy all the orbitals in a d-subshell. (c) each block contains a number of columns equal to the number of electrons that can occupy that subshell. (d) the block indicates value of azimuthal quantum number (l) for the last subshell that received electrons in building up the electronic configuration. unit 3.indd 98 9/9/2022 4:36:15 pm classification of elements and periodicity in properties 99 3.35 anything that influences the valence electrons will affect the chemistry of the element. which one of the following factors does not affect the valence shell? (a) valence principal quantum number (n) (b) nuclear charge (z) (c)
========================================

Result 4 (Cosine Distance: 0.2398)
Source: iesc104.pdf (Chunk Size: 128)
Parent ID: 82153ced-8b1f-4c2a-bb9b-c14030f034a8
Chunk ID: 76d6834c-41fb-4bbe-bc2c-3fb37b33f34e
--------------------
______________4.2 accommodate a maximum of 8 electrons. it was observed that the atoms of elements, completely filled with 8 electrons in the * make a static atomic model displaying outermost shell show little chemical activity. electronic configuration of the first in other words, their combining capacity or eighteen elements. valency is zero. of these inert elements, the table 4.1: composition of atoms of the first eighteen elements with electron distribution in various shells name of symbol atomic number number number distribution of vale- element number of of of electrons ncy protons neutrons electrons k l m n hydrogen h 1 1 - 1 1 - - - 1 helium he 2 2 2 2 2 - - - 0 lithium li 3 3 4 3 2 1 -
========================================

Result 5 (Cosine Distance: 0.2402)
Source: ___V_K_Jaiswal_Inorganic_Chemistry__Periodic_Table_with_anno.pdf (Chunk Size: 128)
Parent ID: c667dfac-763e-4d68-aded-e328eee8af07
Chunk ID: a6354c61-cc84-40ff-880b-66c6c64d6074
--------------------
a pair of s-electrons in their outermost energy level (s ) all the atoms contain a pair of p-electrons in their outermost energy level 7 rn (c) all of them ar alkaline earth metals (d) all are of second group of the periodic table use the referral code : "krsir" for 10% vkj series ah ee kapil rana (iit kgp) q.2 the elements with atomic number 117 and 120 are yet to be discovered. in which group would you place these elements when discovered ? (b) 16, 4 (c) 15, 3 (d) 18, 2 sol tap wet gp nol ~u " oo "wk) series" use the referral code : "krsir" for 10% kapil rana (iit kgp) off on plus (a) [he]2s' -- (b) [ne]3s? (d) [xe]6s? q.3 the
========================================
```

## Email setup and testing

The `email_tool` in `multitools.py` can send emails (with optional PDF attachments). To enable it:

1) Create a `.env` from the example and fill in values

```bash
cp .env.example .env
# edit .env and set EMAIL_USERNAME, EMAIL_PASSWORD, and optionally server/port
```

Typical settings for Gmail:
- EMAIL_SMTP_SERVER=smtp.gmail.com
- EMAIL_SMTP_PORT=587
- EMAIL_USERNAME=your_address@gmail.com
- EMAIL_PASSWORD=App Password (recommended; requires 2FA)

2) Ensure the server loads environment variables

`app.py` already calls `load_dotenv()` so `.env` is picked up automatically.

3) Run the API and test the tool via the agent

```bash
python3 app.py
```

Send a request to the `/agent_query` endpoint asking the agent to use the email tool, for example:

- "Generate a short quiz on hydrogen, save it as a PDF named hydrogen_quiz, and email it to me at you@example.com"

Under the hood the agent can:
- retrieve knowledge (`knowledge_retrieval`)
- generate a quiz (`quiz_generator`)
- export to PDF (`pdf_generator` -> writes to `generated_documents/`)
- email the file (`email_tool`)

Troubleshooting tips:
- Authentication errors: verify EMAIL_USERNAME/EMAIL_PASSWORD; for Gmail, use an App Password
- Firewalls/blocked ports: port 587 must be reachable
- Attachment missing: ensure the file path returned by `pdf_generator` exists before calling `email_tool`

## Further Timeline:

Proposed 2-week timeline structured around the remaining project phases:

### Phase D: Generative Model Integration & Initial Evaluation (Week 1)
- **Days 1-3:** Integrate a generative language model (e.g., from Hugging Face) to produce answers based on retrieved context. This completes the core RAG pipeline.
- **Days 4-5:** Develop a small, focused evaluation dataset (Question/Context/Answer triples) to benchmark system performance.
- **Days 6-7:** Implement an initial evaluation pipeline using metrics like RAGAs (e.g., faithfulness, answer relevance) to score the generator's output and establish a baseline performance score.

### Phase E & F: Iterative Improvement, UI, and Finalization (Week 2)
- **Days 8-10:** Experiment with different embedding models, chunking strategies, and reranking to improve retrieval quality. Use the evaluation pipeline to measure the impact of each change.
- **Days 11-12:** Fine-tune the generation prompts and model parameters to enhance the quality and coherence of the final answers.
- **Day 13:** Build a simple interactive UI for the RAG system using Streamlit or Gradio for demonstration.
- **Day 14:** Finalize the project report, clean up the codebase, and document the experimental results and final architecture for submission.

# Running ES Instance
```bash
sudo docker run -p 9200:9200 -p 9300:9300 -e "discovery.type=single-node" -e "xpack.security.enabled=false" docker.elastic.co/elasticsearch/elasticsearch:8.11.1
```