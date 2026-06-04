#!/bin/zsh
set -e
echo "Setting up Tesla Regional Sales Dashboard venv..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo ""
echo "✅ Done. To run the dashboard:"
echo "  source .venv/bin/activate"
echo "  streamlit run tesla_sales_dashboard.py"
echo ""
echo "On Mac: double-click TeslaSalesDashboard.command"
echo ""
echo "First time: open the dashboard, click the sidebar 'Seed with recent examples' button."
