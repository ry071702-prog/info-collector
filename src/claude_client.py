"""DEPRECATED: Use llm_client instead. Re-exported for backward compatibility."""
from .llm_client import call_json, call_text, daily_request_count, quota_status  # noqa: F401


def monthly_cost() -> float:
    """Always 0 on free Gemini tier."""
    return 0.0
