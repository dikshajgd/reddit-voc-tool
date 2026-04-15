"""
Google Doc Export
Creates a Google Doc from markdown content using Google Docs API.
Handles OAuth2 flow with token caching.
"""

import os
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]

TOKEN_PATH = os.path.join(os.path.dirname(__file__), "token.json")
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")


def get_credentials():
    """Get or refresh Google OAuth2 credentials."""
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"Missing {CREDENTIALS_PATH}. "
                    "Download OAuth2 credentials from Google Cloud Console:\n"
                    "1. Go to console.cloud.google.com\n"
                    "2. Create a project (or use existing)\n"
                    "3. Enable Google Docs API and Google Drive API\n"
                    "4. Create OAuth2 credentials (Desktop app)\n"
                    "5. Download the JSON and save as credentials.json in the reddit-voc-tool folder"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return creds


def markdown_to_doc_requests(markdown_text):
    """
    Convert markdown text to Google Docs API insert requests.
    Handles headings, bold, italic, bullet points.
    """
    requests = []
    lines = markdown_text.split("\n")
    current_index = 1  # Docs index starts at 1

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # Empty line
            text = "\n"
            requests.append({
                "insertText": {"location": {"index": current_index}, "text": text}
            })
            current_index += len(text)
            continue

        # Determine heading level
        heading_level = 0
        if stripped.startswith("### "):
            heading_level = 3
            stripped = stripped[4:]
        elif stripped.startswith("## "):
            heading_level = 2
            stripped = stripped[3:]
        elif stripped.startswith("# "):
            heading_level = 1
            stripped = stripped[2:]

        # Check for bullet point
        is_bullet = False
        if stripped.startswith("- ") or stripped.startswith("* "):
            is_bullet = True
            stripped = stripped[2:]
        elif stripped.startswith("• "):
            is_bullet = True
            stripped = stripped[2:]

        # Handle horizontal rules
        if stripped in ("---", "***", "___"):
            text = "─" * 40 + "\n"
            requests.append({
                "insertText": {"location": {"index": current_index}, "text": text}
            })
            current_index += len(text)
            continue

        text = stripped + "\n"
        start_index = current_index

        requests.append({
            "insertText": {"location": {"index": current_index}, "text": text}
        })
        current_index += len(text)

        # Apply heading style
        if heading_level > 0:
            heading_map = {1: "HEADING_1", 2: "HEADING_2", 3: "HEADING_3"}
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": start_index, "endIndex": current_index},
                    "paragraphStyle": {"namedStyleType": heading_map[heading_level]},
                    "fields": "namedStyleType",
                }
            })

        # Apply bullet style
        if is_bullet:
            requests.append({
                "createParagraphBullets": {
                    "range": {"startIndex": start_index, "endIndex": current_index - 1},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            })

        # Apply bold formatting for **text** patterns
        clean_text = stripped
        bold_matches = list(re.finditer(r"\*\*(.+?)\*\*", clean_text))
        offset = 0
        for match in bold_matches:
            # Calculate position in the inserted text (accounting for removed ** markers)
            bold_start = start_index + match.start() - offset * 4
            bold_end = bold_start + len(match.group(1))
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": bold_start, "endIndex": bold_end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            })
            offset += 1

    return requests


def export_to_google_doc(title, markdown_content):
    """
    Create a new Google Doc with the given markdown content.

    Args:
        title: Document title
        markdown_content: Markdown text to convert

    Returns:
        URL of the created Google Doc
    """
    creds = get_credentials()

    # Create the document
    docs_service = build("docs", "v1", credentials=creds)
    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    # Convert markdown to API requests and insert content
    insert_requests = markdown_to_doc_requests(markdown_content)

    if insert_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": insert_requests},
        ).execute()

    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    print(f"  → Created Google Doc: {doc_url}")

    return doc_url
