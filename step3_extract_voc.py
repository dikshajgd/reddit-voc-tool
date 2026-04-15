"""
Step 3: VOC Extraction & Classification
Uses Anthropic SDK (Claude Sonnet)
Input: Raw scraped Reddit threads + comments
Output: REDDIT VOC {product}.md
"""

import os

from lib.claude_client import call_claude, strip_preamble

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "voc_extraction.md")

# Character limit per API call (~100K tokens worth)
MAX_INPUT_CHARS = 400_000
CHUNK_SIZE = 50  # threads per chunk


def load_prompt(product, industry):
    """Load and render the VOC extraction system prompt."""
    with open(PROMPT_PATH, "r") as f:
        prompt = f.read()

    prompt = prompt.replace("{{BRAND_OR_PRODUCT}}", product)
    prompt = prompt.replace("{{INDUSTRY}}", industry)

    return prompt


def format_thread(item):
    """Format a single scraped thread/comment for the prompt."""
    parts = []

    title = item.get("title", "")
    body = item.get("body") or item.get("text") or item.get("selfText") or ""
    author = item.get("author", "unknown")
    subreddit = item.get("subreddit") or item.get("communityName", "unknown")
    upvotes = item.get("upVotes") or item.get("score") or item.get("numberOfUpvotes", 0)
    url = item.get("url", "")

    parts.append(f"### Thread: {title}")
    parts.append(f"**Subreddit:** r/{subreddit} | **Upvotes:** {upvotes} | **Author:** u/{author}")
    if url:
        parts.append(f"**URL:** {url}")
    if body:
        parts.append(f"\n{body}\n")

    # Include comments
    comments = item.get("comments", [])
    if comments:
        parts.append("**Comments:**")
        for comment in comments[:20]:  # Cap comments per thread
            c_author = comment.get("author", "anonymous")
            c_body = comment.get("body") or comment.get("text", "")
            c_upvotes = comment.get("upVotes") or comment.get("score", 0)
            if c_body:
                parts.append(f"- u/{c_author} ({c_upvotes} upvotes): {c_body}")

    parts.append("---")
    return "\n".join(parts)


def format_scraped_data(items):
    """Format all scraped items into a single text block."""
    formatted = []
    for item in items:
        formatted.append(format_thread(item))
    return "\n\n".join(formatted)


def chunk_items(items, chunk_size=CHUNK_SIZE):
    """Split items into chunks for separate API calls."""
    chunks = []
    for i in range(0, len(items), chunk_size):
        chunks.append(items[i : i + chunk_size])
    return chunks


def merge_chunks(chunk_results, product, industry, system_prompt):
    """Merge multiple chunk results into a single cohesive VOC document."""
    combined = "\n\n---\n\n".join(chunk_results)

    merge_system = (
        f"{system_prompt}\n\n"
        "IMPORTANT: Output ONLY the requested document. "
        "No introductory text, no preamble, no conversational filler. "
        "Start directly with the document content."
    )

    merge_user = (
        f"You previously analyzed Reddit data about {product} in the {industry} space "
        f"in {len(chunk_results)} separate batches. Below are all the partial results.\n\n"
        f"Your job is to merge and deduplicate these into a SINGLE cohesive VOC document "
        f"following the exact format specified above.\n\n"
        f"Rules for merging:\n"
        f"- Combine all quotes from all batches\n"
        f"- Remove exact duplicate quotes\n"
        f"- Re-rank the TOP 15 COPY-READY PHRASES across all batches\n"
        f"- Update frequency tags based on combined data ([HIGH] if 3+ across all batches)\n"
        f"- Write a unified RECURRING THEMES SUMMARY and COMPETITOR PERCEPTION MAP\n\n"
        f"Here are the partial results:\n\n{combined}"
    )

    print(f"  \u2192 Running merge call for {len(chunk_results)} chunks...")
    result = call_claude(merge_system, merge_user, max_tokens=16000)
    return strip_preamble(result)


def run_step3(scraped_data, product, industry, brand_url=None, output_dir="./outputs"):
    """
    Run Step 3: Extract and classify VOC insights from scraped data.

    Args:
        scraped_data: list of scraped thread dicts from Step 2
        product: product name
        industry: industry/niche
        brand_url: optional brand URL for context
        output_dir: output directory

    Returns:
        path to the generated VOC markdown file
    """
    print("\n" + "=" * 60)
    print("STEP 3: VOC Extraction & Classification (Claude Sonnet via API)")
    print("=" * 60)

    if not scraped_data:
        raise ValueError(
            "No scraped data to analyze. Step 2 returned no threads. "
            "Check your Apify token and try again."
        )

    system_prompt = load_prompt(product, industry)

    # Add preamble suppression
    system_with_instruction = (
        f"{system_prompt}\n\n"
        "IMPORTANT: Output ONLY the requested document. "
        "No introductory text, no preamble, no conversational filler. "
        "Start directly with the document content."
    )

    # Format all scraped data
    full_text = format_scraped_data(scraped_data)
    print(f"  \u2192 Formatted {len(scraped_data)} threads ({len(full_text)} chars)")

    # Decide: single call or chunked
    if len(full_text) <= MAX_INPUT_CHARS:
        # Single call
        print(f"  \u2192 Data fits in single call. Sending to Claude Sonnet via API...")

        user_content = "Here are the raw Reddit threads and comments to analyze.\n\n"
        if brand_url:
            user_content += f"Brand context: {brand_url}\n\n"
        user_content += full_text

        raw_output = call_claude(system_with_instruction, user_content, max_tokens=16000)
        voc_output = strip_preamble(raw_output)
    else:
        # Chunked processing
        chunks = chunk_items(scraped_data)
        print(f"  \u2192 Data too large for single call. Splitting into {len(chunks)} chunks...")

        chunk_results = []
        for i, chunk in enumerate(chunks):
            chunk_text = format_scraped_data(chunk)
            print(f"  \u2192 Processing chunk {i + 1}/{len(chunks)} ({len(chunk)} threads)...")

            user_content = f"Analyze this batch of Reddit threads (batch {i + 1} of {len(chunks)}).\n\n"
            if brand_url:
                user_content += f"Brand context: {brand_url}\n\n"
            user_content += chunk_text

            result = call_claude(system_with_instruction, user_content, max_tokens=16000)
            result = strip_preamble(result)
            chunk_results.append(result)
            print(f"     Got {len(result)} chars of analysis")

        # Merge all chunks
        voc_output = merge_chunks(chunk_results, product, industry, system_prompt)

    # Save output
    os.makedirs(output_dir, exist_ok=True)
    output_filename = f"REDDIT VOC {product}.md"
    output_path = os.path.join(output_dir, output_filename)

    with open(output_path, "w") as f:
        f.write(voc_output)

    print(f"  \u2192 Saved: {output_path}")
    print(f"  \u2192 Output size: {len(voc_output)} chars")
    print(f"  \u2713 Step 3 complete\n")

    return output_path
