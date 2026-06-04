"""
Tesla Regional Sales Dashboard
================================

Mimics the structure of Signal Lab for consistency.

Run with:
    # first time
    ./setup.sh

    # every time
    source .venv/bin/activate
    streamlit run tesla_sales_dashboard.py

Or on Mac, double-click TeslaSalesDashboard.command (after setup).

See README.md for details on ingesting new X posts about Tesla sales.

Also deployed publicly on Streamlit Cloud (see README).
"""

from app.dashboard import main

if __name__ == "__main__":
    main()
