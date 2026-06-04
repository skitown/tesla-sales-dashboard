#!/bin/bash
# Double-click this on Mac to launch the dashboard.
# Make sure you've run ./setup.sh at least once.

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "No .venv found. Run ./setup.sh first in Terminal."
  read -p "Press Enter to close..."
  exit 1
fi

source .venv/bin/activate
streamlit run tesla_sales_dashboard.py

# Keep terminal open on error
read -p "Press Enter to close..."
