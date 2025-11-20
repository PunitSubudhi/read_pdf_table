# Copilot Instructions

## Architecture Snapshot
- `main.py` houses `BankStatementParser`, which coordinates all PDF parsing steps (metadata → transactions → page totals → legends) using PyMuPDF for text and Camelot for tables.
- CLI flow: `main()` hardcodes `data/ingest/test (dragged).pdf`, instantiates the parser, calls `save_to_csv()`, then prints a console summary using the returned dicts/DataFrames.
- UI flow: `app.py` wraps the parser inside a Streamlit app; uploads are written to temp files, parsed, and the in-memory DataFrames feed dashboards, Plotly charts, and download buttons.
- Outputs are always persisted (or streamed to users) as four CSVs stored under `data/output/` with stable schemas documented in `README.md`.

## Key Components & Patterns
- `BankStatementParser.extract_account_metadata()` relies on tightly scoped regex patterns against the first page; extend by adding new regex entries to the `patterns` dict.
- `extract_transactions()` always tries Camelot's `stream` flavor with `edge_tol=50` and `row_tol=10`, falling back to `lattice` on failure; it aggressively filters header/footer rows and enforces numeric `Sl No` to isolate true transactions.
- Column handling: the parser expects ten columns (`expected_columns`), truncates extras, and names only the detected columns when fewer are present; keep this aligned when introducing new PDF layouts.
- Amount cleanup happens through `_clean_amount()` which strips commas/whitespace and normalizes trailing negatives ("1234-"); reuse this helper for any new monetary fields.
- `extract_page_totals()` assumes the second-to-last page hosts totals; adjust logic carefully if future statements relocate summaries.
- Legends parsing scans the final two pages using regex `(\d+)\. CODE - Description`; non-conforming text should be normalized before reaching this function.
- Streamlit layer stores results in `st.session_state.processed_results`; any new UI controls should update this structure to keep download buttons and dashboards in sync.
- Zip bundling (`create_zip_download`) mirrors per-file CSV downloads; add new artifacts there if the parser starts emitting more tables.

## Developer Workflows
- Dependency management uses `uv`; install everything with `uv sync` (Python 3.13+, see `pyproject.toml`).
- Run the Streamlit UI via `uv run streamlit run app.py` for interactive parsing, previews, and downloads.
- Execute the CLI parser with `uv run python main.py`; it will read the default ingest PDF and refresh the CSVs under `data/output/`.
- When pointing at new PDFs programmatically, pass the path into `BankStatementParser(...)` and call `parse()` or `save_to_csv()`; avoid reusing parser instances after `__del__` closes the document.

## Conventions & Tips
- Treat `BankStatementParser` as the single source of truth for parsing logic; both CLI and UI depend on its stable interface `(metadata, transactions, totals, legends)`.
- Maintain consistent CSV schemas so downstream dashboards and download helpers in `app.py` stay functional.
- Session and temp-file cleanup is manual (`Path(tmp_path).unlink()`); ensure new async/background work also deletes temporary PDFs.
- No automated tests exist; validate changes by running both CLI and Streamlit flows against real sample PDFs in `data/ingest/`.
- Visual components use Plotly/Streamlit defaults; keep figures lightweight to avoid blocking multi-file processing.
