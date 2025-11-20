import camelot
import pymupdf as fitz  # PyMuPDF
import pathlib
import pandas as pd
import re
from typing import Dict, List, Tuple


class BankStatementParser:
    """Parser for ICICI Bank detailed statement PDFs."""

    EXPECTED_TRANSACTION_COLUMNS = [
        'Sl No', 'Tran Id', 'Value Date', 'Transaction Date',
        'Transaction Posted Date', 'Cheque no / Ref No',
        'Transaction Remarks', 'Withdrawal (Dr)', 'Deposit (Cr)', 'Balance'
    ]

    TRANSACTION_COLUMN_ALIASES = {
        'Sl No': ['Sl No', 'SlNo', 'S No', 'Sr No', 'Serial No'],
        'Tran Id': ['Tran Id', 'Transaction Id', 'Txn Id', 'TxnId', 'TranID'],
        'Value Date': ['Value Date', 'Value Dt', 'Val Dt'],
        'Transaction Date': ['Transaction Date', 'Tran Date', 'Txn Date'],
        'Transaction Posted Date': ['Transaction Posted Date', 'Posting Date', 'Post Date'],
        'Cheque no / Ref No': ['Cheque no / Ref No', 'Cheque No/Ref No', 'Chq/Ref No', 'Ref No', 'Cheque No'],
        'Transaction Remarks': ['Transaction Remarks', 'Remarks', 'Description', 'Narration'],
        'Withdrawal (Dr)': ['Withdrawal (Dr)', 'Withdrawal', 'Withdrawals', 'Dr Amount', 'Debit'],
        'Deposit (Cr)': ['Deposit (Cr)', 'Deposit', 'Deposits', 'Cr Amount', 'Credit'],
        'Balance': ['Balance', 'Running Balance', 'Closing Balance']
    }

    def __init__(self, pdf_path: str):
        self.pdf_path = pathlib.Path(pdf_path)
        self.doc = fitz.open(str(self.pdf_path))
        self.total_pages = len(self.doc)

    def extract_account_metadata(self) -> Dict[str, str]:
        """Extract account information from the first page."""
        first_page = self.doc[0]
        text = first_page.get_text()

        metadata = {}

        # Extract key fields using regex patterns
        patterns = {
            'name': r'Name:\s*(.+?)(?=\s+A/C Branch:)',
            'address': r'Address:\s*(.+?)(?=A/C No:)',
            'account_number': r'A/C No:\s*(\d+)',
            'account_type': r'A/C Type:\s*(\w+)',
            'customer_id': r'Cust ID:\s*(\d+)',
            'branch': r'A/C Branch:\s*(.+?)(?=Branch Address:)',
            'branch_address': r'Branch Address:\s*(.+?)(?=A/C Type:)',
            'branch_code': r'Branch Code:\s*(\d+)',
            'ifsc_code': r'IFSC Code:\s*(\w+)',
            'transaction_period': r'Transaction Period:\s*(.+?)(?=IFSC Code:)',
            'statement_date': r'Statement\s+Request/Download\s+Date:\s*(\d{2}/\d{2}/\d{4})',
            'currency': r'Account Currency:\s*(\w+)',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.DOTALL)
            if match:
                metadata[key] = match.group(1).strip().replace('\n', ' ')

        return metadata

    def extract_transactions(self) -> pd.DataFrame:
        """Extract transaction table from all pages using Camelot."""
        print(f"Extracting tables from {self.total_pages} pages...")

        # Use Camelot to extract tables from all pages
        # lattice flavor works better for column preservation
        try:
            tables = camelot.read_pdf(
                str(self.pdf_path),
                pages=f'1-{self.total_pages}',
                flavor='lattice'
            )
        except:
            # Fallback to stream if lattice fails
            tables = camelot.read_pdf(
                str(self.pdf_path),
                pages=f'1-{self.total_pages}',
                flavor='stream',
                edge_tol=50,
                row_tol=10
            )

        print(f"Found {len(tables)} tables")

        # Combine all transaction tables
        all_transactions = []

        for i, table in enumerate(tables):
            raw_df = table.df

            if raw_df.shape[0] == 0:
                continue

            df, header_lookup = self._separate_header(raw_df)

            if df.shape[0] == 0:
                continue

            # Remove rows that are headers, footers, or summaries
            df = df[~df.iloc[:, 0].astype(str).str.contains('Sl', na=False, case=False)]
            df = df[~df.iloc[:, 0].astype(str).str.contains('No', na=False, case=False)]
            df = df[~df.iloc[:, 0].astype(str).str.contains('Page Total', na=False)]
            df = df[~df.iloc[:, 0].astype(str).str.contains('Opening Bal', na=False)]
            df = df[~df.iloc[:, 0].astype(str).str.contains('Legends', na=False)]
            df = df[~df.iloc[:, 0].astype(str).str.contains('Tran', na=False, case=False)]

            # Remove empty rows
            df = df[df.iloc[:, 0].astype(str).str.strip() != '']

            # Only keep rows that start with a number (transaction rows)
            df = df[df.iloc[:, 0].astype(str).str.match(r'^\d+$')]

            if len(df) > 0:
                canonical_df = self._map_to_canonical_transactions(df, header_lookup)
                if not canonical_df.empty:
                    all_transactions.append(canonical_df)

        # Concatenate all transactions
        if all_transactions:
            transactions_df = pd.concat(all_transactions, ignore_index=True)

            print(f"Table has {transactions_df.shape[1]} columns")

            # Camelot lattice merges Withdrawal/Deposit into one column
            # Need to manually assign based on actual positions:
            # Col 0-5: Sl No through Cheque no/Ref No
            # Col 6: Transaction Remarks  
            # Col 7: Empty placeholder (Camelot artifact)
            # Col 8: Amount (either withdrawal or deposit)
            # Col 9: Balance
            
            if transactions_df.shape[1] == 10:
                # Standard 10-column Camelot output
                # Col 0-5: Sl No through Cheque no/Ref No
                # Col 6: Transaction Remarks  
                # Col 7: Withdrawal (Dr) - may contain withdrawal amount
                # Col 8: Deposit (Cr) - may contain deposit amount
                # Col 9: Balance
                
                transactions_df.columns = [
                    'Sl No', 'Tran Id', 'Value Date', 'Transaction Date',
                    'Transaction Posted Date', 'Cheque no / Ref No',
                    'Transaction Remarks', 'Withdrawal (Dr)', 'Deposit (Cr)', 'Balance'
                ]
                
                # Camelot lattice DOES preserve separate Withdrawal/Deposit columns!
                # Just need to clean them
                transactions_df['Withdrawal (Dr)'] = transactions_df['Withdrawal (Dr)'].apply(self._clean_amount)
                transactions_df['Deposit (Cr)'] = transactions_df['Deposit (Cr)'].apply(self._clean_amount)
            else:
                # Fallback: ensure all canonical columns exist
                missing_cols = [
                    col for col in self.EXPECTED_TRANSACTION_COLUMNS
                    if col not in transactions_df.columns
                ]
                for col in missing_cols:
                    transactions_df[col] = pd.NA

            # Reorder to the canonical schema
            transactions_df = transactions_df[self.EXPECTED_TRANSACTION_COLUMNS]

            # Clean numeric columns
            for col in ['Withdrawal (Dr)', 'Deposit (Cr)', 'Balance']:
                if col in transactions_df.columns:
                    transactions_df[col] = transactions_df[col].apply(self._clean_amount)

            # Clean text in all columns (remove extra newlines)
            for col in transactions_df.columns:
                if transactions_df[col].dtype == 'object':
                    transactions_df[col] = transactions_df[col].astype(str).str.replace('\n', ' ', regex=False).str.strip()

            return transactions_df

        return pd.DataFrame()

    def _clean_amount(self, amount_str: str) -> float:
        """Clean and convert amount strings to float."""
        # Handle already-converted floats
        if isinstance(amount_str, (int, float)):
            return float(amount_str) if not pd.isna(amount_str) else 0.0
            
        if pd.isna(amount_str) or str(amount_str).strip() in ['', '-']:
            return 0.0

        # Remove commas, whitespace, AND newlines
        cleaned = str(amount_str).replace(',', '').replace(' ', '').replace('\n', '').strip()

        # Handle negative amounts (some might have - at the end or start)
        if cleaned.startswith('-'):
            cleaned = cleaned  # Already negative
        elif cleaned.endswith('-'):
            cleaned = '-' + cleaned[:-1]

        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def _map_to_canonical_transactions(self, df: pd.DataFrame, header_lookup: Dict[str, str]) -> pd.DataFrame:
        alias_lookup = self._get_transaction_alias_lookup()
        column_map: Dict[str, str] = {}

        for col_label, header_text in header_lookup.items():
            normalized = self._normalize_header(header_text)
            canonical = alias_lookup.get(normalized)
            if canonical and canonical not in column_map and col_label in df.columns:
                column_map[canonical] = col_label

        if not column_map:
            column_map = {
                canonical: df.columns[idx]
                for idx, canonical in enumerate(self.EXPECTED_TRANSACTION_COLUMNS)
                if idx < len(df.columns)
            }

        canonical_df = pd.DataFrame(index=df.index)

        for canonical in self.EXPECTED_TRANSACTION_COLUMNS:
            source_col = column_map.get(canonical)
            if source_col in df.columns:
                canonical_df[canonical] = df[source_col]
            else:
                canonical_df[canonical] = pd.Series(pd.NA, index=df.index)

        return canonical_df

    def _normalize_header(self, header: str) -> str:
        if header is None:
            return ''
        return re.sub(r'[^a-z0-9]', '', str(header).lower())

    def _get_transaction_alias_lookup(self) -> Dict[str, str]:
        if not hasattr(self, '_transaction_alias_lookup'):
            lookup: Dict[str, str] = {}
            for canonical, aliases in self.TRANSACTION_COLUMN_ALIASES.items():
                for alias in aliases:
                    normalized = self._normalize_header(alias)
                    if normalized:
                        lookup[normalized] = canonical
            self._transaction_alias_lookup = lookup
        return self._transaction_alias_lookup

    def _separate_header(self, table_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str]]:
        header_indices = table_df[
            table_df.iloc[:, 0].astype(str).str.contains('Sl', na=False, case=False)
        ].index

        if len(header_indices) > 0:
            header_idx = header_indices[0]
            header_row = table_df.iloc[header_idx].fillna('').astype(str)
            body_df = table_df.iloc[header_idx + 1:].reset_index(drop=True)
        else:
            header_row = pd.Series([''] * table_df.shape[1])
            body_df = table_df.copy().reset_index(drop=True)

        header_lookup = {
            table_df.columns[idx]: header_row.iloc[idx]
            for idx in range(len(table_df.columns))
        }

        return body_df, header_lookup

    def extract_page_totals(self) -> Dict[str, float]:
        """Extract page totals from the second-to-last page."""
        # Get the second-to-last page (which should have the totals)
        if self.total_pages >= 2:
            page = self.doc[self.total_pages - 2]
            text = page.get_text()

            totals = {}

            # Extract totals using regex
            patterns = {
                'opening_balance': r'Opening Bal:\s*([-]?[\d,]+\.[\d]+)',
                'withdrawals': r'Withdrawls:\s*([\d,]+\.[\d]+)',
                'deposits': r'Deposits:\s*([\d,]+\.[\d]+)',
                'closing_balance': r'Closing Bal:\s*([-]?[\d,]+\.[\d]+)',
            }

            for key, pattern in patterns.items():
                match = re.search(pattern, text)
                if match:
                    totals[key] = self._clean_amount(match.group(1))

            return totals

        return {}

    def extract_legends(self) -> pd.DataFrame:
        """Extract transaction code legends from the last two pages."""
        legends = []

        # Extract from the last two pages
        start_page = max(0, self.total_pages - 2)
        for page_num in range(start_page, self.total_pages):
            page = self.doc[page_num]
            text = page.get_text()

            # Find all legend entries (number. CODE - Description)
            pattern = r'(\d+)\.\s+([A-Z/\s]+?)\s+-\s+(.+?)(?=\n\d+\.|$)'
            matches = re.findall(pattern, text, re.DOTALL)

            for match in matches:
                legends.append({
                    'number': match[0].strip(),
                    'code': match[1].strip(),
                    'description': match[2].strip().replace('\n', ' ')
                })

        return pd.DataFrame(legends)

    def parse(self) -> Tuple[Dict, pd.DataFrame, Dict, pd.DataFrame]:
        """
        Parse the entire PDF and return all extracted data.

        Returns:
            Tuple of (metadata_dict, transactions_df, totals_dict, legends_df)
        """
        print("Parsing bank statement PDF...")

        print("\n1. Extracting account metadata...")
        metadata = self.extract_account_metadata()

        print("\n2. Extracting transactions...")
        transactions = self.extract_transactions()

        print("\n3. Extracting page totals...")
        totals = self.extract_page_totals()

        print("\n4. Extracting legends...")
        legends = self.extract_legends()

        print("\nParsing complete!")
        return metadata, transactions, totals, legends

    def save_to_csv(self, output_dir: str = "data/output"):
        """Parse and save all data to separate CSV files."""
        output_path = pathlib.Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        metadata, transactions, totals, legends = self.parse()

        # Save metadata
        metadata_df = pd.DataFrame([metadata])
        metadata_df.to_csv(output_path / "account_metadata.csv", index=False)
        print(f"\nSaved account metadata to {output_path / 'account_metadata.csv'}")

        # Save transactions
        transactions.to_csv(output_path / "transactions.csv", index=False)
        print(f"Saved {len(transactions)} transactions to {output_path / 'transactions.csv'}")

        # Save totals
        totals_df = pd.DataFrame([totals])
        totals_df.to_csv(output_path / "page_totals.csv", index=False)
        print(f"Saved page totals to {output_path / 'page_totals.csv'}")

        # Save legends
        legends.to_csv(output_path / "legends.csv", index=False)
        print(f"Saved {len(legends)} legends to {output_path / 'legends.csv'}")

        return metadata, transactions, totals, legends

    def __del__(self):
        """Close the PDF document."""
        if hasattr(self, 'doc'):
            self.doc.close()


def main():
    """Main function to parse the bank statement PDF."""
    pdf_path = "data/ingest/test (dragged).pdf"

    parser = BankStatementParser(pdf_path)
    metadata, transactions, totals, legends = parser.save_to_csv()

    # Display summary
    print("\n" + "="*60)
    print("PARSING SUMMARY")
    print("="*60)
    print(f"\nAccount: {metadata.get('name', 'N/A')}")
    print(f"Account Number: {metadata.get('account_number', 'N/A')}")
    print(f"Period: {metadata.get('transaction_period', 'N/A')}")
    print(f"\nTotal Transactions: {len(transactions)}")
    print(f"Opening Balance: {totals.get('opening_balance', 0):,.2f}")
    print(f"Total Withdrawals: {totals.get('withdrawals', 0):,.2f}")
    print(f"Total Deposits: {totals.get('deposits', 0):,.2f}")
    print(f"Closing Balance: {totals.get('closing_balance', 0):,.2f}")
    print("\n" + "="*60)


if __name__ == "__main__":
    main()
