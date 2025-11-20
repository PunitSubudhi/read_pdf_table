import camelot
import pymupdf as fitz  # PyMuPDF
import pathlib
import pandas as pd
import re
from typing import Dict, List, Tuple, Optional, Callable
from multiprocessing import Pool, cpu_count
from functools import partial
import numpy as np
from tqdm import tqdm


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

    def __init__(self, pdf_path: str, max_workers: Optional[int] = None, 
                 chunk_size: int = 15, use_parallel: bool = True,
                 progress_callback: Optional[Callable[[int, int], None]] = None):
        self.pdf_path = pathlib.Path(pdf_path)
        self.doc = fitz.open(str(self.pdf_path))
        self.total_pages = len(self.doc)
        self.max_workers = max_workers or min(cpu_count(), 8)
        self.chunk_size = chunk_size
        self.use_parallel = use_parallel and self.total_pages > 20
        self.progress_callback = progress_callback

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
        """Extract transaction table from all pages using Camelot with parallel processing."""
        if self.use_parallel:
            return self._extract_transactions_parallel()
        else:
            return self._extract_transactions_sequential()

    def _extract_transactions_sequential(self) -> pd.DataFrame:
        """Sequential extraction for smaller PDFs."""
        print(f"Extracting tables from {self.total_pages} pages (sequential mode)...")
        all_transactions = self._process_page_range(1, self.total_pages, show_progress=True)
        return self._combine_and_clean_transactions(all_transactions)

    def _extract_transactions_parallel(self) -> pd.DataFrame:
        """Parallel extraction for large PDFs."""
        print(f"Extracting tables from {self.total_pages} pages (parallel mode with {self.max_workers} workers)...")
        
        # Split pages into chunks
        page_chunks = []
        for i in range(1, self.total_pages + 1, self.chunk_size):
            end_page = min(i + self.chunk_size - 1, self.total_pages)
            page_chunks.append((i, end_page))
        
        print(f"Processing {len(page_chunks)} chunks of ~{self.chunk_size} pages each...")
        
        # Process chunks in parallel
        process_func = partial(self._process_page_chunk_static, str(self.pdf_path))
        
        all_transactions = []
        with Pool(processes=self.max_workers) as pool:
            # Use imap for progress tracking
            with tqdm(total=len(page_chunks), desc="Processing chunks", unit="chunk") as pbar:
                for chunk_transactions in pool.imap(process_func, page_chunks):
                    all_transactions.extend(chunk_transactions)
                    pbar.update(1)
                    if self.progress_callback:
                        self.progress_callback(pbar.n, len(page_chunks))
        
        return self._combine_and_clean_transactions(all_transactions)

    @staticmethod
    def _process_page_chunk_static(pdf_path: str, page_range: Tuple[int, int]) -> List[pd.DataFrame]:
        """Static method for parallel processing of page chunks."""
        start_page, end_page = page_range
        
        # Try lattice first, fallback to stream
        try:
            tables = camelot.read_pdf(
                pdf_path,
                pages=f'{start_page}-{end_page}',
                flavor='lattice'
            )
        except:
            try:
                tables = camelot.read_pdf(
                    pdf_path,
                    pages=f'{start_page}-{end_page}',
                    flavor='stream',
                    edge_tol=50,
                    row_tol=10
                )
            except:
                return []
        
        chunk_transactions = []
        parser = BankStatementParser.__new__(BankStatementParser)
        
        for table in tables:
            raw_df = table.df
            if raw_df.shape[0] == 0:
                continue
            
            df, header_lookup = parser._separate_header(raw_df)
            if df.shape[0] == 0:
                continue
            
            # Optimized filtering: combined regex pattern
            df = parser._filter_non_transaction_rows(df)
            
            if len(df) > 0:
                canonical_df = parser._map_to_canonical_transactions(df, header_lookup)
                if not canonical_df.empty:
                    chunk_transactions.append(canonical_df)
        
        return chunk_transactions

    def _process_page_range(self, start_page: int, end_page: int, show_progress: bool = False) -> List[pd.DataFrame]:
        """Process a range of pages sequentially."""
        try:
            tables = camelot.read_pdf(
                str(self.pdf_path),
                pages=f'{start_page}-{end_page}',
                flavor='lattice'
            )
        except:
            tables = camelot.read_pdf(
                str(self.pdf_path),
                pages=f'{start_page}-{end_page}',
                flavor='stream',
                edge_tol=50,
                row_tol=10
            )
        
        all_transactions = []
        iterator = tqdm(tables, desc="Processing tables") if show_progress else tables
        
        for table in iterator:
            raw_df = table.df
            if raw_df.shape[0] == 0:
                continue
            
            df, header_lookup = self._separate_header(raw_df)
            if df.shape[0] == 0:
                continue
            
            # Optimized filtering
            df = self._filter_non_transaction_rows(df)
            
            if len(df) > 0:
                canonical_df = self._map_to_canonical_transactions(df, header_lookup)
                if not canonical_df.empty:
                    all_transactions.append(canonical_df)
        
        return all_transactions

    def _filter_non_transaction_rows(self, df: pd.DataFrame) -> pd.DataFrame:
        """Optimized row filtering with combined regex pattern."""
        if df.shape[0] == 0:
            return df
        
        first_col = df.iloc[:, 0].astype(str)
        
        # Combined regex pattern for all exclusions (3-5x faster than separate contains)
        # Use non-capturing groups to avoid warning
        exclusion_pattern = r'(?:Sl|No|Page Total|Opening Bal|Legends|Tran)'
        mask = ~first_col.str.contains(exclusion_pattern, na=False, case=False, regex=True)
        
        # Remove empty rows
        mask &= (first_col.str.strip() != '')
        
        # Only keep rows starting with a number
        mask &= first_col.str.match(r'^\d+$', na=False)
        
        return df[mask]

    def _combine_and_clean_transactions(self, all_transactions: List[pd.DataFrame]) -> pd.DataFrame:
        """Combine and clean all transaction DataFrames."""
        if not all_transactions:
            return pd.DataFrame()
        
        # Concatenate all transactions
        transactions_df = pd.concat(all_transactions, ignore_index=True)
        
        # Handle column standardization
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
            
            # Vectorized amount cleaning (much faster than apply)
            transactions_df['Withdrawal (Dr)'] = self._clean_amount_vectorized(transactions_df['Withdrawal (Dr)'])
            transactions_df['Deposit (Cr)'] = self._clean_amount_vectorized(transactions_df['Deposit (Cr)'])
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
        
        # Vectorized numeric column cleaning
        for col in ['Withdrawal (Dr)', 'Deposit (Cr)', 'Balance']:
            if col in transactions_df.columns:
                transactions_df[col] = self._clean_amount_vectorized(transactions_df[col])
        
        # Vectorized text cleaning (single pass for all object columns)
        object_cols = transactions_df.select_dtypes(include=['object']).columns
        for col in object_cols:
            # Combined operation: convert, replace, strip in one chain
            transactions_df[col] = transactions_df[col].astype(str).str.replace('\n', ' ', regex=False).str.strip()
        
        return transactions_df

    def _clean_amount(self, amount_str: str) -> float:
        """Clean and convert amount strings to float (kept for backward compatibility)."""
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

    def _clean_amount_vectorized(self, series: pd.Series) -> pd.Series:
        """Vectorized amount cleaning - much faster than apply for large datasets."""
        # Convert to string, handle NaN
        s = series.astype(str)
        
        # Replace empty/NaN values
        s = s.replace(['nan', 'None', '', '-'], '0')
        
        # Vectorized string operations: remove commas, spaces, newlines
        s = s.str.replace(',', '', regex=False)
        s = s.str.replace(' ', '', regex=False)
        s = s.str.replace('\n', '', regex=False)
        s = s.str.strip()
        
        # Handle trailing negatives (amount-) -> (-amount)
        trailing_neg = s.str.endswith('-')
        s.loc[trailing_neg] = '-' + s.loc[trailing_neg].str[:-1]
        
        # Convert to numeric, coerce errors to 0
        result = pd.to_numeric(s, errors='coerce').fillna(0.0)
        
        return result

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
        tasks = ['Metadata', 'Transactions', 'Totals', 'Legends']
        
        with tqdm(total=len(tasks), desc="Parsing PDF", unit="task") as pbar:
            pbar.set_description("Extracting metadata")
            metadata = self.extract_account_metadata()
            pbar.update(1)
            
            pbar.set_description("Extracting transactions")
            transactions = self.extract_transactions()
            pbar.update(1)
            
            pbar.set_description("Extracting totals")
            totals = self.extract_page_totals()
            pbar.update(1)
            
            pbar.set_description("Extracting legends")
            legends = self.extract_legends()
            pbar.update(1)
        
        print("\n✓ Parsing complete!")
        return metadata, transactions, totals, legends

    def save_to_csv(self, output_dir: str = "data/output"):
        """Parse and save all data to separate CSV files."""
        output_path = pathlib.Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        metadata, transactions, totals, legends = self.parse()

        # Save all files with progress tracking
        files_to_save = [
            ('account_metadata.csv', pd.DataFrame([metadata]), 'metadata'),
            ('transactions.csv', transactions, f'{len(transactions)} transactions'),
            ('page_totals.csv', pd.DataFrame([totals]), 'totals'),
            ('legends.csv', legends, f'{len(legends)} legends')
        ]
        
        with tqdm(files_to_save, desc="Saving CSV files", unit="file") as pbar:
            for filename, df, description in pbar:
                pbar.set_description(f"Saving {description}")
                df.to_csv(output_path / filename, index=False)
        
        print(f"\n✓ All files saved to {output_path}/")
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
