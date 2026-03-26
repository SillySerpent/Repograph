"""Mixed-language fixture: Python backend + JS frontend entrypoint."""


def process_request(payload: dict) -> dict:
    """Handle an incoming request from the JS frontend."""
    validated = validate_payload(payload)
    result = run_pipeline(validated)
    return {"status": "ok", "result": result}


def validate_payload(payload: dict) -> dict:
    """Validate the incoming payload structure."""
    if "data" not in payload:
        raise ValueError("Missing data field")
    return payload


def run_pipeline(payload: dict) -> str:
    """Execute the main processing pipeline."""
    data = payload.get("data", "")
    return transform(data)


def transform(data: str) -> str:
    """Transform raw data into output format."""
    return data.upper()
