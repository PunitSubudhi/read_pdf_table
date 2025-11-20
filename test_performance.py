#!/usr/bin/env python3
"""
Test script to verify the optimized PDF parsing performance.
"""
import time
from pathlib import Path
from main import BankStatementParser

def test_parser(pdf_path: str, use_parallel: bool = True):
    """Test the parser with timing."""
    print(f"\n{'='*60}")
    print(f"Testing {'PARALLEL' if use_parallel else 'SEQUENTIAL'} mode")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    parser = BankStatementParser(
        pdf_path, 
        use_parallel=use_parallel,
        chunk_size=15,
        max_workers=4
    )
    
    metadata, transactions, totals, legends = parser.parse()
    
    end_time = time.time()
    elapsed = end_time - start_time
    
    print(f"\n{'='*60}")
    print(f"RESULTS - {'PARALLEL' if use_parallel else 'SEQUENTIAL'} MODE")
    print(f"{'='*60}")
    print(f"Total Pages:        {parser.total_pages}")
    print(f"Transactions Found: {len(transactions)}")
    print(f"Legends Found:      {len(legends)}")
    print(f"Execution Time:     {elapsed:.2f} seconds")
    print(f"Pages/Second:       {parser.total_pages/elapsed:.2f}")
    print(f"{'='*60}\n")
    
    return elapsed, len(transactions)


if __name__ == "__main__":
    # Use the default test PDF or specify your own
    pdf_path = "data/ingest/test (dragged).pdf"
    
    if not Path(pdf_path).exists():
        print(f"Error: PDF not found at {pdf_path}")
        print("Please update the pdf_path variable to point to your PDF file.")
        exit(1)
    
    # Test both modes for comparison
    print("\n" + "🚀 PERFORMANCE TEST - Optimized PDF Parser" + "\n")
    
    # Parallel mode (optimized)
    time_parallel, count_parallel = test_parser(pdf_path, use_parallel=True)
    
    # Sequential mode (for comparison on large PDFs)
    # Uncomment to compare with sequential processing
    # time_sequential, count_sequential = test_parser(pdf_path, use_parallel=False)
    # 
    # print(f"\n{'='*60}")
    # print("PERFORMANCE COMPARISON")
    # print(f"{'='*60}")
    # print(f"Sequential Time:  {time_sequential:.2f}s")
    # print(f"Parallel Time:    {time_parallel:.2f}s")
    # print(f"Speedup:          {time_sequential/time_parallel:.2f}x faster")
    # print(f"{'='*60}\n")
