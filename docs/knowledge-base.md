# Knowledge base (RAG)

Users upload PDF, text, Markdown and CSV files; the assistant searches them and cites what it finds. Everything runs
locally: parsing in Python, embeddings from Ollama (`nomic-embed-text`), vectors in Chroma. All file types share one
registry and one Chroma collection, so a single search covers guidance PDFs, project notes and uploaded tables together.

## CSV files (tables)

A CSV is read with the standard `csv` module (delimiter detected among `, ; tab |`; UTF-8 only). The first row is the
header unless every cell in it is a number, in which case columns are named `column_1`, `column_2`, ... Each data row
becomes one line, `row 12: station=Anand Vihar; pm25=312.5`, with empty cells left out. Lines are grouped into blocks of
about `KB_CHUNK_CHARS` and **every block starts with `Columns: a, b, c`**, so a retrieved block is self-describing. A block
is one chunk and is never split again; its location is shown as `section 'rows 9-16'`. The upload category `dataset`
("Dataset (table)") labels citations so a table row is never mistaken for guidance or research.

Limits: `KB_CSV_MAX_ROWS` (20,000 data rows), `KB_CSV_MAX_COLUMNS` (100), the usual upload size and chunk limits; cells are
clipped at 300 characters and a row line at 700. Ragged rows are accepted (missing cells left out) and counted in the
document's notes.

Search over a table returns the best-matching rows only, so the search tool tells the model that dataset passages are a
sample and that it must not state totals or averages from them. Computation is done by the table store below.

## Research use: tables, exact words, tags and the relationship test

These four additions make the knowledge base useful for studying pollution, not only for quoting documents. None of them
changes, retrains or activates the forecasting model; the only route into the model remains the Training page.

### 1. Tables are real, queryable data (`app/kb/tables.py`, `KB_DIR/tables.sqlite`)
Every CSV is also loaded into SQLite with typed columns. A column is `integer`, `real`, `datetime` or `text` only if every
non-empty value parses as that type (`NA`, `-`, `null` ... are missing; `007` stays text). Timestamps without an offset are
read in `KB_DATASET_TIMEZONE` (default Asia/Kolkata), stored as UTC, and the assumption is shown in the profile and in every
query result. Units are never inferred or converted.

* `GET /api/kb/documents/{id}/profile`: rows, typed columns with ranges and examples, time column, period, resolution
  (hourly / daily / irregular), detected pollutant, station and zone columns, warnings.
* `POST /api/kb/documents/{id}/query`: a validated specification, never SQL: `select`, `aggregates` (`count`,
  `count_distinct`, `mean`, `sum`, `min`, `max`), `where` (`= != > >= < <= contains in`), `group_by` (a column, or
  `date_column:hour|day|month|year` in the dataset's time zone), `order_by`, `limit` (at most 200). Column names are matched
  against the profile and bound as identifiers; values are bound as parameters. The result states its own definition and how
  many of the table's rows it used.
* Assistant tool `query_dataset`: call it with no arguments to list tables and columns, then with strings such as
  `aggregates=["mean:pm25"]`, `where=["zone=Delhi","date>=2024-11-01"]`, `group_by=["date:month"]`. The result is a numbered
  source `[K#]`. Because cell text comes from an uploaded file it is treated as untrusted, exactly like search passages
  (no further tools are offered that turn).
* `GET /api/kb/datasets`: every indexed table with its columns, for pickers and for the assistant.

### 2. Exact-word search fused with the embedding search (`app/kb/lexical.py`)
Embeddings are good at meaning and weak at names and numbers. A BM25 index over the same chunks finds passages that literally
contain the words asked for. A passage is admitted if its cosine similarity clears `KB_MIN_SCORE`, **or** it contains at
least 60% of the query's distinctive words (and at least two of them for multi-word queries) and its similarity is within
`KB_LEXICAL_RELAX` (0.20) of the threshold. Order is by reciprocal-rank fusion; the score shown to users is still the cosine
similarity. Passages with no shared words and a low similarity are still refused.

### 3. Research tags (`app/kb/meta.py`)
Each document gets `meta`: pollutants, places (NCR cities and aliases) and topics (stubble burning, fireworks, vehicles,
industry, construction dust, meteorology, health, standards) found by pattern matching, with counts. A table also gets its
row count, column names, period and resolution. A tag says the word appears, not that the source is authoritative on it.

### 4. Relationship to measured pollution (`app/kb/research.py`)
`GET /api/kb/documents/{id}/relationship?column=&pollutant=&zone=&max_lag=&known_in_advance=`

Aligns one numeric column with the network mean of real station observations from the history store (usable readings only;
daily values need at least 18 hourly network values) and reports:

1. Pearson and Spearman correlation at lags 0..7 days (or 0..24 h), with a 95% interval that uses an autocorrelation-adjusted
   sample size (Bartlett);
2. a chronological 70/30 held-out check: does adding the series reduce the error of a one-step linear forecast that already
   uses yesterday's value? The lag is chosen on the training part only; the test part is scored once. A series is allowed at
   lag 0 only if the caller marks it `known_in_advance` (a weather forecast or a calendar).

It is a screening test to decide whether a dataset deserves to become a feature in a proper training run. It is not causal
evidence, uses a linear model with one extra feature, and one split. The response repeats these caveats, states the time
zone assumption and says that the active model was not changed.

**Worked example (real data, 2026-10-11).** A daily table of boundary-layer height and 10 m wind speed (network mean of the
stored weather-model values, 1,560 days) against Delhi PM2.5: boundary-layer height r = -0.40 (95% interval -0.52 to -0.27)
and wind speed r = -0.30, as expected from ventilation. On the held-out period neither improved a yesterday-only forecast
(relative error change -2.3% and -1.8%; marked known-in-advance, wind speed -7.6%), consistent with the trained model's
finding that the station's own recent history dominates.

## Configuration added

`KB_CSV_MAX_ROWS` (20,000), `KB_CSV_MAX_COLUMNS` (100), `KB_DATASET_TIMEZONE` (Asia/Kolkata), `KB_LEXICAL_RELAX` (0.20).

## Setup

```bash
ollama pull nomic-embed-text      # on the Ollama host
```

Settings live in `api/.env` (all optional): `OLLAMA_EMBED_MODEL`, `KB_DIR` (default `./data/kb`, git-ignored),
`KB_MAX_UPLOAD_MB` (10), `KB_MAX_PDF_PAGES` (400), `KB_CHUNK_CHARS` (1000), `KB_CHUNK_OVERLAP` (150),
`KB_MIN_SCORE` (0.62), `KB_TOP_K_DEFAULT` (4). The **Knowledge Base** page shows whether embeddings are available.

## Pipeline

1. **Validate** (before anything is stored): extension allow-list (`.pdf .txt .md .markdown`), size limit (checked from
   the declared length *before* the body is parsed, and again while reading), file signature (a `.pdf` must be a PDF),
   UTF-8 text without binary data, PDF page and text limits, password-protected or damaged PDFs rejected, a PDF with no
   extractable text (a scan; OCR is not supported) rejected. Each rejection has a stable error code.
2. **Extract**: PDFs with `pypdf` (pure Python; nothing in the file is executed), one text block per page so page numbers
   are kept; layout line breaks are joined. Text is cleaned of control characters.
3. **Chunk**: ~1000 characters with 150 overlap, split on paragraphs, then sentences, then words. A PDF chunk records
   its page; a Markdown chunk records its nearest heading; no overlap crosses a heading.
4. **Embed** in batches through the `Embedder` interface (Ollama today; another provider is one class). `nomic-embed-text`
   gets its documented `search_document:` / `search_query:` prefixes.
5. **Index** into a Chroma collection named for the embedding model, so vectors from different models are never mixed.
6. **Duplicates** are detected by SHA-256 of the file content (HTTP 409 with the existing document's id).

Upload returns immediately (HTTP 202); indexing runs in the background and the page polls. A failure is stored on the
document and shown in the list (nothing half-indexed is kept). A document left "indexing" by a restart is shown as
failed with a prompt to re-index. **Re-index** re-reads the stored original; **Delete** removes the row, the stored file
and every chunk (in every model's collection).

## Retrieval

Cosine similarity, `top_k` results, and a relevance threshold (`KB_MIN_SCORE`). Only `ready` documents indexed with the
current embedding model are searched; after a model change, documents show "Re-index needed". Search can be limited by
document type or by (loosely matched) document name. Results carry type, publisher, licence, link, page or section and
the similarity score.

**Threshold calibration (measured, small corpus).** On the real CPCB PDF plus the project docs: questions the documents
answer scored 0.68–0.80; off-topic questions scored up to 0.58 (e.g. "quantum entanglement" 0.58). 0.62 separates those
cleanly. A similarity score cannot tell "on topic" from "answers the question": asking for a WHO figure that is not in
the corpus still retrieved the CPCB document at 0.72. That gap is closed by the assistant instructions (below), not by
the threshold. Re-tune `KB_MIN_SCORE` when the corpus grows.

## Assistant integration

`search_knowledge_base(query, top_k, document?)` returns passages, each with a citation id (`K1`...), document type
(Official guidance / Scientific publication / Project documentation), location, publisher, licence and relevance. The
answer's source list shows the type, location and the retrieved excerpt, with a link to the document. The assistant is
told to name the document type, to put its own reasoning in a sentence starting "My interpretation:", to cite only
passages that actually answer the question, and to say so plainly when nothing relevant exists.

**Retrieved text is untrusted.** Document text is cleaned and labelled as untrusted in the tool result, and the system
prompt forbids following instructions inside it. Beyond prompting, there is a hard rule in code: **once document text is
in the model's context, no further tools are offered for that turn**, and any tool call the model emits anyway is ignored.
A poisoned document therefore cannot cause a tool call, because tool calls only happen before the text is seen. (Tools
requested in the same step as the search were decided before the text was visible, so they still run.) Citations in an
answer that match no retrieved source are flagged in the UI.

## Storage and decisions

* **Vectors and chunk text:** Chroma, in `KB_DIR/chroma`. Telemetry is disabled.
* **Document registry** (status, error, content hash, provenance): a SQLite file, `KB_DIR/registry.sqlite`. You listed
  PostgreSQL "where required"; the database host is not set up yet and this is a few rows, so the standard-library
  SQLite file avoids adding infrastructure. It sits behind `DocumentRegistry`, so moving it to PostgreSQL later is a
  contained change.
* **Original files:** `KB_DIR/files/<id>.<ext>` under generated names (the uploaded name is only displayed, after
  sanitising).

## Known limitations

* **No authentication.** Like every other endpoint, upload, re-index and delete are open to anyone who can reach the
  API. Do not expose the API beyond a trusted network until access control is added.
* No OCR: scanned PDFs are rejected. Tables in PDFs are flattened to text.
* Large PDFs are parsed in a worker thread with a timeout, but Python cannot kill a thread, so a pathological file can
  keep a thread busy after the request has been refused.
* Embedding runs one document at a time on the Ollama host; on CPU it took 4–5 s for a 2-page PDF.
* Similarity search cannot judge whether a passage answers the question (see calibration).
