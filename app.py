import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import tempfile
import zipfile
import io
from datetime import datetime
from main import BankStatementParser

# Page configuration
st.set_page_config(
    page_title="Bank Statement Parser",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
    <style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .stAlert {
        margin-top: 10px;
    }
    </style>
""", unsafe_allow_html=True)


def parse_pdf_file(uploaded_file):
    """Parse a single PDF file and return extracted data."""
    try:
        # Save uploaded file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name

        # Parse the PDF
        parser = BankStatementParser(tmp_path)
        metadata, transactions, totals, legends = parser.parse()

        # Clean up temp file
        Path(tmp_path).unlink()

        return {
            'success': True,
            'filename': uploaded_file.name,
            'metadata': metadata,
            'transactions': transactions,
            'totals': totals,
            'legends': legends,
            'error': None
        }
    except Exception as e:
        return {
            'success': False,
            'filename': uploaded_file.name,
            'error': str(e)
        }


def create_summary_metrics(all_results):
    """Create summary metrics from all processed statements."""
    total_statements = len([r for r in all_results if r['success']])
    total_transactions = sum(len(r['transactions']) for r in all_results if r['success'])
    total_withdrawals = sum(r['totals'].get('withdrawals', 0) for r in all_results if r['success'])
    total_deposits = sum(r['totals'].get('deposits', 0) for r in all_results if r['success'])

    return {
        'statements': total_statements,
        'transactions': total_transactions,
        'withdrawals': total_withdrawals,
        'deposits': total_deposits,
        'net_change': total_deposits - total_withdrawals
    }


def create_transaction_chart(transactions_df):
    """Create a transaction timeline chart."""
    if transactions_df.empty or 'Transaction Date' not in transactions_df.columns:
        return None

    # Count transactions by date
    trans_by_date = transactions_df.groupby('Transaction Date').size().reset_index(name='Count')

    fig = px.line(
        trans_by_date,
        x='Transaction Date',
        y='Count',
        title='Transactions Over Time',
        labels={'Transaction Date': 'Date', 'Count': 'Number of Transactions'}
    )
    fig.update_traces(mode='lines+markers')
    return fig


def create_amount_comparison_chart(totals):
    """Create a bar chart comparing withdrawals and deposits."""
    fig = go.Figure(data=[
        go.Bar(name='Withdrawals', x=['Total'], y=[totals.get('withdrawals', 0)], marker_color='red'),
        go.Bar(name='Deposits', x=['Total'], y=[totals.get('deposits', 0)], marker_color='green')
    ])
    fig.update_layout(
        title='Withdrawals vs Deposits',
        yaxis_title='Amount (INR)',
        barmode='group'
    )
    return fig


def create_balance_chart(totals):
    """Create a simple balance change visualization."""
    opening = totals.get('opening_balance', 0)
    closing = totals.get('closing_balance', 0)

    fig = go.Figure(data=[
        go.Bar(
            x=['Opening Balance', 'Closing Balance'],
            y=[opening, closing],
            marker_color=['lightblue', 'darkblue']
        )
    ])
    fig.update_layout(title='Account Balance', yaxis_title='Amount (INR)')
    return fig


def create_zip_download(all_results):
    """Create a ZIP file containing all CSVs."""
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for result in all_results:
            if not result['success']:
                continue

            filename_base = Path(result['filename']).stem

            # Add metadata CSV
            metadata_csv = pd.DataFrame([result['metadata']]).to_csv(index=False)
            zip_file.writestr(f"{filename_base}_metadata.csv", metadata_csv)

            # Add transactions CSV
            transactions_csv = result['transactions'].to_csv(index=False)
            zip_file.writestr(f"{filename_base}_transactions.csv", transactions_csv)

            # Add totals CSV
            totals_csv = pd.DataFrame([result['totals']]).to_csv(index=False)
            zip_file.writestr(f"{filename_base}_totals.csv", totals_csv)

            # Add legends CSV
            legends_csv = result['legends'].to_csv(index=False)
            zip_file.writestr(f"{filename_base}_legends.csv", legends_csv)

    zip_buffer.seek(0)
    return zip_buffer


def main():
    # Header
    st.title("🏦 Bank Statement Parser")
    st.markdown("Upload and parse ICICI Bank detailed statements with ease")

    # Sidebar
    with st.sidebar:
        st.header("📤 Upload PDFs")
        uploaded_files = st.file_uploader(
            "Choose PDF files",
            type=['pdf'],
            accept_multiple_files=True,
            help="Upload one or more bank statement PDFs"
        )

        if uploaded_files:
            st.success(f"✅ {len(uploaded_files)} file(s) uploaded")
            for file in uploaded_files:
                st.text(f"• {file.name} ({file.size / 1024:.1f} KB)")

        st.markdown("---")
        st.markdown("### About")
        st.info("This app extracts:\n- Account metadata\n- Transaction details\n- Summary totals\n- Transaction codes")

    # Initialize session state
    if 'processed_results' not in st.session_state:
        st.session_state.processed_results = []

    # Process button
    if uploaded_files:
        col1, col2 = st.columns([1, 4])
        with col1:
            process_button = st.button("🔄 Process All PDFs", type="primary", use_container_width=True)
        with col2:
            if st.button("🗑️ Clear All", use_container_width=True):
                st.session_state.processed_results = []
                st.rerun()

        if process_button:
            st.session_state.processed_results = []

            # Progress bar
            progress_bar = st.progress(0)
            status_text = st.empty()

            for idx, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"Processing {uploaded_file.name}...")
                result = parse_pdf_file(uploaded_file)
                st.session_state.processed_results.append(result)
                progress_bar.progress((idx + 1) / len(uploaded_files))

            status_text.empty()
            progress_bar.empty()
            st.success(f"✅ Processed {len(uploaded_files)} file(s)!")

    # Display results
    if st.session_state.processed_results:
        # Show errors if any
        errors = [r for r in st.session_state.processed_results if not r['success']]
        if errors:
            st.error(f"⚠️ {len(errors)} file(s) failed to process:")
            for error in errors:
                st.warning(f"• {error['filename']}: {error['error']}")

        # Summary Dashboard
        successful_results = [r for r in st.session_state.processed_results if r['success']]

        if successful_results:
            st.markdown("## 📊 Summary Dashboard")

            summary = create_summary_metrics(successful_results)

            # Metrics row
            col1, col2, col3, col4, col5 = st.columns(5)

            with col1:
                st.metric("Statements", summary['statements'])
            with col2:
                st.metric("Total Transactions", summary['transactions'])
            with col3:
                st.metric("Total Withdrawals", f"₹{summary['withdrawals']:,.2f}")
            with col4:
                st.metric("Total Deposits", f"₹{summary['deposits']:,.2f}")
            with col5:
                delta_color = "normal" if summary['net_change'] >= 0 else "inverse"
                st.metric("Net Change", f"₹{summary['net_change']:,.2f}")

            st.markdown("---")

            # Bulk download
            st.markdown("## 📥 Download All Data")

            zip_buffer = create_zip_download(successful_results)
            st.download_button(
                label="⬇️ Download All as ZIP",
                data=zip_buffer,
                file_name=f"bank_statements_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                mime="application/zip",
                use_container_width=True
            )

            st.markdown("---")

            # Per-statement tabs
            st.markdown("## 📄 Statement Details")

            tabs = st.tabs([f"📋 {r['filename']}" for r in successful_results])

            for tab, result in zip(tabs, successful_results):
                with tab:
                    # Account metadata
                    st.subheader("Account Information")

                    meta = result['metadata']
                    col1, col2 = st.columns(2)

                    with col1:
                        st.write("**Account Holder:**", meta.get('name', 'N/A'))
                        st.write("**Account Number:**", meta.get('account_number', 'N/A'))
                        st.write("**Account Type:**", meta.get('account_type', 'N/A'))
                        st.write("**Customer ID:**", meta.get('customer_id', 'N/A'))

                    with col2:
                        st.write("**Branch:**", meta.get('branch', 'N/A'))
                        st.write("**IFSC Code:**", meta.get('ifsc_code', 'N/A'))
                        st.write("**Period:**", meta.get('transaction_period', 'N/A'))
                        st.write("**Currency:**", meta.get('currency', 'N/A'))

                    st.markdown("---")

                    # Page totals
                    st.subheader("Summary Totals")

                    totals = result['totals']
                    col1, col2, col3, col4 = st.columns(4)

                    with col1:
                        st.metric("Opening Balance", f"₹{totals.get('opening_balance', 0):,.2f}")
                    with col2:
                        st.metric("Withdrawals", f"₹{totals.get('withdrawals', 0):,.2f}")
                    with col3:
                        st.metric("Deposits", f"₹{totals.get('deposits', 0):,.2f}")
                    with col4:
                        st.metric("Closing Balance", f"₹{totals.get('closing_balance', 0):,.2f}")

                    # Visualizations
                    st.markdown("---")
                    st.subheader("Visualizations")

                    viz_col1, viz_col2 = st.columns(2)

                    with viz_col1:
                        amount_chart = create_amount_comparison_chart(totals)
                        if amount_chart:
                            st.plotly_chart(amount_chart, use_container_width=True)

                    with viz_col2:
                        balance_chart = create_balance_chart(totals)
                        if balance_chart:
                            st.plotly_chart(balance_chart, use_container_width=True)

                    transaction_chart = create_transaction_chart(result['transactions'])
                    if transaction_chart:
                        st.plotly_chart(transaction_chart, use_container_width=True)

                    # Transactions table
                    st.markdown("---")
                    st.subheader("Transactions")

                    if not result['transactions'].empty:
                        st.dataframe(
                            result['transactions'],
                            use_container_width=True,
                            height=400
                        )

                        # Download individual CSV
                        csv = result['transactions'].to_csv(index=False)
                        st.download_button(
                            label="📊 Download Transactions CSV",
                            data=csv,
                            file_name=f"{Path(result['filename']).stem}_transactions.csv",
                            mime="text/csv"
                        )
                    else:
                        st.warning("No transactions found")

                    # Legends
                    st.markdown("---")
                    with st.expander("📖 Transaction Code Legends"):
                        if not result['legends'].empty:
                            st.dataframe(result['legends'], use_container_width=True)
                        else:
                            st.info("No legends found")

                    # Individual downloads
                    st.markdown("---")
                    st.subheader("Download Individual Files")

                    dl_col1, dl_col2, dl_col3, dl_col4 = st.columns(4)

                    with dl_col1:
                        metadata_csv = pd.DataFrame([result['metadata']]).to_csv(index=False)
                        st.download_button(
                            label="📄 Metadata",
                            data=metadata_csv,
                            file_name=f"{Path(result['filename']).stem}_metadata.csv",
                            mime="text/csv",
                            use_container_width=True
                        )

                    with dl_col2:
                        trans_csv = result['transactions'].to_csv(index=False)
                        st.download_button(
                            label="📊 Transactions",
                            data=trans_csv,
                            file_name=f"{Path(result['filename']).stem}_transactions.csv",
                            mime="text/csv",
                            use_container_width=True
                        )

                    with dl_col3:
                        totals_csv = pd.DataFrame([result['totals']]).to_csv(index=False)
                        st.download_button(
                            label="💰 Totals",
                            data=totals_csv,
                            file_name=f"{Path(result['filename']).stem}_totals.csv",
                            mime="text/csv",
                            use_container_width=True
                        )

                    with dl_col4:
                        legends_csv = result['legends'].to_csv(index=False)
                        st.download_button(
                            label="📖 Legends",
                            data=legends_csv,
                            file_name=f"{Path(result['filename']).stem}_legends.csv",
                            mime="text/csv",
                            use_container_width=True
                        )

    else:
        # Welcome screen
        st.markdown("""
        ## 👋 Welcome!

        Upload your ICICI Bank statement PDFs using the sidebar to get started.

        ### Features:
        - 📤 **Batch Upload**: Process multiple statements at once
        - 📊 **Interactive Tables**: View and explore your transaction data
        - 📈 **Visualizations**: Charts and graphs for better insights
        - 💾 **Bulk Download**: Download all data as a ZIP file
        - 🎯 **Individual Downloads**: Get specific CSV files per statement

        ### Supported Data:
        - Account metadata (name, number, branch, etc.)
        - Complete transaction history
        - Summary totals (opening/closing balance, withdrawals, deposits)
        - Transaction code legends
        """)


if __name__ == "__main__":
    main()
