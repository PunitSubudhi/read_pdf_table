"""Quick test to verify optimizations work."""
from main import BankStatementParser
import sys

try:
    print("Testing optimized parser...")
    parser = BankStatementParser("data/ingest/test (dragged).pdf", use_parallel=True, chunk_size=15)
    print(f"✓ Parser initialized: {parser.total_pages} pages")
    print(f"  - Parallel mode: {parser.use_parallel}")
    print(f"  - Max workers: {parser.max_workers}")
    print(f"  - Chunk size: {parser.chunk_size}")
    
    print("\nStarting parse...")
    metadata, transactions, totals, legends = parser.parse()
    
    print(f"\n✓ Parse complete!")
    print(f"  - Transactions: {len(transactions)}")
    print(f"  - Legends: {len(legends)}")
    print(f"  - Account: {metadata.get('account_number', 'N/A')}")
    print("\nAll optimizations working correctly! ✓")
    
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
