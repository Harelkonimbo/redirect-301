"""
ga4.py — pull page-level data from GA4 via the Data API (v1beta).

Auth: accepts either
  - {"token": "ya29..."}  or  {"access_token": "ya29..."}  (Windmill OAuth2 resource)
  - a service-account JSON dict  {"type": "service_account", ...}  (Windmill secret)

Returns [{url: str, title: str, pageviews: int}], ordered by pageviews desc.
"""
import json

import requests

GA4_ENDPOINT = "https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
LOOKBACK_DAYS = 90
MIN_PAGEVIEWS = 5
MAX_ROWS = 10_000
_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def _bearer_token(credentials: dict) -> str:
    """Resolve a raw Bearer token from any supported credential format."""
    if not isinstance(credentials, dict):
        raise TypeError("credentials must be a dict")

    # Windmill OAuth2 resource
    for key in ("token", "access_token"):
        if credentials.get(key):
            return credentials[key]

    # Service-account JSON — use google-auth to mint a token
    if credentials.get("type") == "service_account":
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_info(
                credentials, scopes=_SCOPES
            )
            creds.refresh(Request())
            return creds.token
        except ImportError as exc:
            raise ImportError(
                "google-auth is required for service-account credentials: pip install google-auth"
            ) from exc

    raise ValueError(
        "credentials must contain 'token', 'access_token', or be a service-account JSON dict"
    )


def run_report(property_id: str, site_url: str, credentials: dict) -> list:
    """
    Fetch GA4 pageviews for the given property and site.

    property_id : GA4 numeric property ID (string or int)
    site_url    : base URL of the old site (e.g. 'https://example.co.il')
    credentials : see module docstring

    Returns [{url, title, pageviews}] sorted by pageviews desc.
    """
    token = _bearer_token(credentials)
    base = site_url.rstrip("/")

    endpoint = GA4_ENDPOINT.format(property_id=str(property_id))
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "dateRanges": [{"startDate": f"{LOOKBACK_DAYS}daysAgo", "endDate": "today"}],
        "dimensions": [{"name": "pagePath"}, {"name": "pageTitle"}],
        "metrics": [{"name": "screenPageViews"}],
        "metricFilter": {
            "filter": {
                "fieldName": "screenPageViews",
                "numericFilter": {
                    "operation": "GREATER_THAN_OR_EQUAL",
                    "value": {"int64Value": str(MIN_PAGEVIEWS)},
                },
            }
        },
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        "limit": MAX_ROWS,
    }

    resp = requests.post(endpoint, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    seen: set = set()
    for row in data.get("rows", []):
        path = row["dimensionValues"][0]["value"]
        title = row["dimensionValues"][1]["value"]
        views = int(row["metricValues"][0]["value"])

        full_url = base + path
        if full_url in seen:
            continue
        seen.add(full_url)

        rows.append({"url": full_url, "title": title, "pageviews": views})

    return rows
