# PDF Bank Statement Parser

A Python parser for extracting data from ICICI Bank detailed statement PDFs using Camelot and PyMuPDF, with a beautiful Streamlit web interface.

## Features

- **Account Metadata Extraction**: Extracts account holder information, account number, branch details, IFSC code, transaction period, etc.
- **Transaction Table Parsing**: Extracts all transaction records with details like transaction ID, dates, amounts, and remarks
- **Page Totals**: Extracts opening balance, closing balance, total withdrawals, and deposits
- **Legend Extraction**: Parses transaction code definitions
- **Streamlit UI**: Interactive web interface for batch processing and data visualization

## Installation

```bash
uv sync
```

## Usage

### Option 1: Streamlit Web Interface (Recommended)

Launch the interactive web app:

```bash
uv run streamlit run app.py
```

Then open your browser to `http://localhost:8501`

**Features:**
- 📤 Upload multiple PDFs at once (batch processing)
- 📊 Interactive data tables with sorting and filtering
- 📈 Visual charts for transactions and balances
- 💾 Bulk download all data as ZIP
- 📥 Individual CSV downloads per statement
- 📋 Summary dashboard with key metrics

### Option 2: Command Line

Run the parser directly on a PDF:

```bash
uv run python main.py
```

The parser will:
1. Read the PDF from `data/ingest/test (dragged).pdf`
2. Extract all data
3. Save four CSV files to `data/output/`:
   - `account_metadata.csv` - Account information
   - `transactions.csv` - All transaction records
   - `page_totals.csv` - Summary totals
   - `legends.csv` - Transaction code definitions

## Customization

To parse a different PDF, modify the `pdf_path` in `main.py`:

```python
pdf_path = "path/to/your/statement.pdf"
```

Or use the parser programmatically:

```python
from main import BankStatementParser

parser = BankStatementParser("path/to/statement.pdf")
metadata, transactions, totals, legends = parser.parse()

# Or save directly to CSV
metadata, transactions, totals, legends = parser.save_to_csv("output/directory")
```

## Output Format

### account_metadata.csv
- name, address, account_number, account_type, customer_id
- branch, branch_address, branch_code, ifsc_code
- transaction_period, statement_date, currency

### transactions.csv
- Sl No, Tran Id, Value Date, Transaction Date
- Transaction Posted Date, Cheque no / Ref No
- Transaction Remarks, Withdrawal (Dr), Deposit (Cr)

### page_totals.csv
- opening_balance, withdrawals, deposits, closing_balance

### legends.csv
- number, code, description

## Dependencies

- camelot-py: PDF table extraction
- pymupdf: PDF text extraction
- pandas: Data manipulation
- opencv-python: Image processing for Camelot

## Notes

- The parser uses Camelot's 'stream' flavor for better table detection
- Numeric values are automatically cleaned (commas removed, negatives handled)
- Text fields have newlines replaced with spaces for cleaner CSV output
- Works with multi-page statements
