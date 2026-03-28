#!/bin/bash

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Check for dependencies
echo "Checking dependencies..."
pip install -q -r requirements.txt

# Get port from .env file or use 5001 as default
PORT=5001
if grep -q "FLASK_RUN_PORT" .env; then
    PORT=$(grep "FLASK_RUN_PORT" .env | cut -d '=' -f2)
fi

# Run Flask on the specified port
echo "Starting Flask server on port $PORT..."
python -m flask run --host=0.0.0.0 --port=$PORT 