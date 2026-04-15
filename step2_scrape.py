"""
Step 2: Reddit Scraping via Apify
Uses trudax/reddit-scraper-lite actor for reliable Reddit data.
"""

import hashlib
import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error

from dotenv import load_dotenv

load_dotenv()

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN", "")
APIFY_ACTOR = "trudax~reddit-scraper-lite"
APIFY_BASE = "https://api.apify.com/v2"

MAX_TOTAL_THREADS = 200
MAX_BATCHES = 8


# ── Apify API Helpers ──────────────────────────────────────────


def apify_request(url, method="GET", body=None, timeout=180):
    """Make an authenticated request to the Apify API."""
    headers = {
        "Authorization": f"Bearer {APIFY_TOKEN}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")[:500]
        print(f"     ⚠ Apify API error {e.code}: {error_body}")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"     ⚠ Apify request failed: {e}")
        return None


def run_apify_scraper(start_urls, max_posts=25, max_comments=50):
    """
    Run the Apify Reddit scraper.
    Starts an async run, polls for completion, then fetches results.
    """
    # Start async run
    run_url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs"
    body = {
        "startUrls": [{"url": u} for u in start_urls],
        "maxItems": max_posts + (max_posts * max_comments),
        "maxPostCount": max_posts,
        "maxComments": max_comments,
    }

    print(f"     → Starting Apify run ({len(start_urls)} URLs, max {max_posts} posts)...")
    result = apify_request(run_url, method="POST", body=body, timeout=30)

    if result is None:
        return []

    # Extract run info
    run_data = result.get("data", result)
    run_id = run_data.get("id")
    dataset_id = run_data.get("defaultDatasetId")

    if not run_id or not dataset_id:
        print(f"     ⚠ Could not get run ID from Apify response")
        return []

    return _poll_and_fetch(run_id, dataset_id)


def _poll_and_fetch(run_id, dataset_id, timeout=300):
    """Poll a running Apify actor and fetch results when done."""
    print(f"     → Waiting for Apify run {run_id}...")
    start = time.time()

    while time.time() - start < timeout:
        status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
        status = apify_request(status_url)
        if not status:
            time.sleep(5)
            continue

        run_status = status.get("data", {}).get("status", "")
        if run_status == "SUCCEEDED":
            break
        elif run_status in ("FAILED", "ABORTED", "TIMED-OUT"):
            print(f"     ⚠ Apify run {run_status}")
            return []

        time.sleep(5)
    else:
        print(f"     ⚠ Apify polling timed out after {timeout}s")
        return []

    # Fetch dataset items
    items_url = f"{APIFY_BASE}/datasets/{dataset_id}/items?limit=1000"
    items = apify_request(items_url)
    return items if isinstance(items, list) else []


def normalize_apify_results(items):
    """
    Convert Apify output (flat list of posts + comments) into
    our pipeline's thread dict format with nested comments.
    """
    # Separate posts and comments
    posts = {}
    comments_by_post = {}

    for item in items:
        dtype = item.get("dataType", "")
        if dtype == "post":
            post_id = item.get("id", "")
            posts[post_id] = item
            if post_id not in comments_by_post:
                comments_by_post[post_id] = []
        elif dtype == "comment":
            post_id = item.get("postId", "")
            if post_id not in comments_by_post:
                comments_by_post[post_id] = []
            comments_by_post[post_id].append(item)

    # Build thread dicts
    threads = []
    for post_id, post in posts.items():
        raw_comments = comments_by_post.get(post_id, [])
        thread = {
            "id": post.get("parsedId", post_id),
            "title": post.get("title", ""),
            "selfText": post.get("body", ""),
            "author": post.get("username", "unknown"),
            "subreddit": post.get("parsedCommunityName", post.get("communityName", "unknown")).lstrip("r/"),
            "score": post.get("upVotes", 0),
            "upVotes": post.get("upVotes", 0),
            "url": post.get("url", ""),
            "numComments": post.get("numberOfComments", 0),
            "created": _parse_timestamp(post.get("createdAt", "")),
            "comments": [
                {
                    "author": c.get("username", "unknown"),
                    "body": c.get("body", ""),
                    "score": c.get("upVotes", 0),
                    "upVotes": c.get("upVotes", 0),
                }
                for c in raw_comments
                if c.get("body") and c.get("body") != "[removed]" and c.get("body") != "[deleted]"
            ],
        }
        if thread["title"]:
            threads.append(thread)

    return threads


def _parse_timestamp(ts_str):
    """Parse ISO timestamp to unix epoch (best effort)."""
    if not ts_str:
        return 0
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return 0


# ── Batch Building ─────────────────────────────────────────────


def format_search_term(keyword):
    """Clean a keyword for Reddit search."""
    keyword = keyword.strip("*").strip("`").strip()
    keyword = keyword.strip('"').strip("'").strip()

    for sep in [" — ", " -- ", ": "]:
        if sep in keyword:
            keyword = keyword.split(sep)[0].strip()

    if not keyword or len(keyword) < 3:
        return None

    return keyword


def build_search_urls(parsed_data):
    """
    Build Reddit search URLs for Apify from parsed Step 1 data.
    Each URL searches across a group of subreddits for specific keywords.
    """
    subreddits = parsed_data.get("subreddits", {})
    keywords = parsed_data.get("keywords", {})

    # Priority pairings: (subreddit tier, keyword category)
    priority_pairs = [
        ("core", "pain_points"),
        ("core", "product_frustrations"),
        ("adjacent", "desired_outcomes"),
        ("adjacent", "pain_points"),
        ("shopping", "objections"),
        ("identity", "user_type"),
        ("shopping", "shopping"),
        ("general", "pain_points"),
    ]

    urls = []
    done = set()

    for tier, category in priority_pairs:
        if len(urls) >= MAX_BATCHES * 3:  # 3 keywords per batch
            break
        if tier not in subreddits or category not in keywords:
            continue

        key = (tier, category)
        if key in done:
            continue
        done.add(key)

        # Multi-subreddit join (max 5 subs per URL)
        multi = "+".join(subreddits[tier][:5])

        # Top 3 keywords from this category
        search_terms = [
            t for t in (format_search_term(kw[:80]) for kw in keywords[category])
            if t is not None
        ]

        for term in search_terms[:3]:
            encoded = urllib.parse.quote(term)
            url = (
                f"https://www.reddit.com/r/{multi}/search/"
                f"?q={encoded}&restrict_sr=1&sort=relevance&t=year"
            )
            urls.append(url)

    return urls


def deduplicate_threads(all_items):
    """Deduplicate threads by Reddit post ID."""
    seen = set()
    unique = []
    for item in all_items:
        thread_id = item.get("id", "")
        if thread_id and thread_id not in seen:
            seen.add(thread_id)
            unique.append(item)
    return unique


# ── Web Search Fallback ────────────────────────────────────────


def search_reddit_via_web(parsed_data, product, max_threads=50):
    """
    Fallback: Use Claude CLI with web search to find Reddit threads
    when Apify is unavailable.
    """
    print("\n  🔍 Falling back to web search for Reddit threads...")

    subreddits = parsed_data.get("subreddits", {})
    keywords = parsed_data.get("keywords", {})

    # Build search queries from top keywords
    search_queries = []
    for category in ["pain_points", "desired_outcomes", "objections", "shopping"]:
        if category in keywords:
            for kw in keywords[category][:3]:
                cleaned = format_search_term(kw[:60])
                if cleaned:
                    search_queries.append(cleaned)

    if not search_queries:
        search_queries = [product]

    # Get top subreddits for context
    top_subs = []
    for tier in ["core", "adjacent", "shopping"]:
        if tier in subreddits:
            top_subs.extend(subreddits[tier][:5])
    top_subs = top_subs[:10]

    sub_list = ", ".join(f"r/{s}" for s in top_subs) if top_subs else "relevant subreddits"

    prompt = f"""Search the web for Reddit discussions about "{product}". I need you to find real Reddit threads with genuine user discussions.

Search for these queries (use site:reddit.com in your searches):
{chr(10).join(f'- site:reddit.com {q}' for q in search_queries[:8])}

Focus on threads from these subreddits: {sub_list}

For EACH thread you find (aim for at least 15-20 threads), output this EXACT JSON format, one per line:
{{"url": "https://reddit.com/r/...", "title": "thread title", "subreddit": "subredditname", "selfText": "post body text", "score": 10, "comments": [{{"body": "comment text", "score": 5}}]}}

Rules:
- Output ONLY the JSON lines, nothing else
- Include the actual post body text and top comments you can see
- Each line must be valid JSON
- Include real comment text, not placeholders
- Aim for 15-30 threads total across all searches"""

    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--model", "opus",
             "--output-format", "text",
             "--allowedTools", "mcp__web_search,WebSearch,web_search"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            print(f"     ⚠ Claude CLI web search failed: {result.stderr[:200]}")
            return []

        return _parse_web_search_results(result.stdout.strip(), max_threads)

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"     ⚠ Web search fallback failed: {e}")
        return []


def _parse_web_search_results(output, max_threads=50):
    """Parse Claude's web search output into thread dicts."""
    threads = []

    for line in output.split("\n"):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue

        try:
            data = json.loads(line)
            thread = {
                "id": hashlib.md5(data.get("url", str(time.time())).encode()).hexdigest()[:10],
                "title": data.get("title", ""),
                "selfText": data.get("selfText", data.get("body", "")),
                "author": data.get("author", "unknown"),
                "subreddit": data.get("subreddit", "unknown"),
                "score": data.get("score", 0),
                "upVotes": data.get("score", 0),
                "url": data.get("url", ""),
                "numComments": len(data.get("comments", [])),
                "created": data.get("created", 0),
                "comments": [
                    {
                        "author": c.get("author", "unknown"),
                        "body": c.get("body", c.get("text", "")),
                        "score": c.get("score", 0),
                        "upVotes": c.get("score", 0),
                    }
                    for c in data.get("comments", [])
                    if isinstance(c, dict) and (c.get("body") or c.get("text"))
                ],
            }
            if thread["title"] or thread["selfText"]:
                threads.append(thread)
        except (json.JSONDecodeError, TypeError):
            continue

    print(f"     → Parsed {len(threads)} threads from web search")
    return threads[:max_threads]


# ── Upload Parsing ─────────────────────────────────────────────


def parse_uploaded_threads(text, file_type="md"):
    """
    Parse user-uploaded Reddit data into thread dicts.
    Handles JSON, markdown, and plain text formats.
    """
    import re
    text = text.strip()

    # Try JSON first regardless of extension
    if text.startswith("[") or text.startswith("{"):
        try:
            return _parse_json_threads(text)
        except (json.JSONDecodeError, TypeError):
            pass

    if file_type == "json":
        try:
            return _parse_json_threads(text)
        except (json.JSONDecodeError, TypeError):
            pass

    # Markdown format
    if file_type in ("md", "markdown") or "###" in text or "---" in text:
        return _parse_markdown_threads(text)

    # Plain text fallback
    return _parse_plaintext_threads(text)


def _parse_json_threads(text):
    """Parse JSON thread data."""
    data = json.loads(text)

    if isinstance(data, dict):
        data = data.get("threads", data.get("data", data.get("posts", [data])))

    if not isinstance(data, list):
        data = [data]

    threads = []
    for item in data:
        if not isinstance(item, dict):
            continue
        thread = {
            "id": item.get("id", hashlib.md5(str(item).encode()).hexdigest()[:10]),
            "title": item.get("title", ""),
            "selfText": item.get("selfText", item.get("selftext", item.get("body", item.get("text", "")))),
            "author": item.get("author", "unknown"),
            "subreddit": item.get("subreddit", item.get("communityName", "unknown")),
            "score": item.get("score", item.get("upVotes", item.get("ups", 0))),
            "upVotes": item.get("upVotes", item.get("score", item.get("ups", 0))),
            "url": item.get("url", item.get("permalink", "")),
            "numComments": item.get("numComments", item.get("num_comments", 0)),
            "created": item.get("created", item.get("created_utc", 0)),
            "comments": _normalize_comments(item.get("comments", [])),
        }
        if thread["title"] or thread["selfText"]:
            threads.append(thread)

    return threads


def _normalize_comments(comments):
    """Normalize comment format from various sources."""
    if not isinstance(comments, list):
        return []
    result = []
    for c in comments:
        if isinstance(c, str):
            result.append({"author": "unknown", "body": c, "score": 0, "upVotes": 0})
        elif isinstance(c, dict):
            result.append({
                "author": c.get("author", "unknown"),
                "body": c.get("body", c.get("text", c.get("content", ""))),
                "score": c.get("score", c.get("upVotes", 0)),
                "upVotes": c.get("upVotes", c.get("score", 0)),
            })
    return result


def _parse_markdown_threads(text):
    """Parse markdown-formatted Reddit thread data."""
    import re
    threads = []

    blocks = re.split(r"\n---+\n|(?=^### )", text, flags=re.MULTILINE)

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 20:
            continue

        title_match = re.search(r"^###?\s*(?:Thread:\s*)?(.+?)$", block, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else ""

        sub_match = re.search(r"r/(\w+)", block)
        subreddit = sub_match.group(1) if sub_match else "unknown"

        score_match = re.search(r"(?:upvotes?|score)\s*:?\s*(\d+)", block, re.IGNORECASE)
        score = int(score_match.group(1)) if score_match else 0

        url_match = re.search(r"(https?://(?:www\.|old\.)?reddit\.com/r/\S+)", block)
        url = url_match.group(1) if url_match else ""

        body_lines = []
        comments = []
        in_comments = False

        for line in block.split("\n"):
            stripped = line.strip()
            if title_match and stripped == title_match.group(0).strip():
                continue
            if re.match(r"^[-*•]\s*(?:u/|\*\*u/)", stripped):
                in_comments = True
                comment_text = re.sub(r"^[-*•]\s*(?:\*\*)?u/\S+(?:\*\*)?\s*(?:\(\d+\s*upvotes?\))?\s*:?\s*", "", stripped)
                author_match = re.search(r"u/(\S+)", stripped)
                cscore_match = re.search(r"\((\d+)\s*upvotes?\)", stripped)
                if comment_text:
                    comments.append({
                        "author": author_match.group(1) if author_match else "unknown",
                        "body": comment_text,
                        "score": int(cscore_match.group(1)) if cscore_match else 0,
                        "upVotes": int(cscore_match.group(1)) if cscore_match else 0,
                    })
                continue
            if not in_comments and not stripped.startswith("**") and stripped:
                body_lines.append(stripped)

        body = "\n".join(body_lines).strip()

        if title or body:
            threads.append({
                "id": hashlib.md5(f"{title}{body[:100]}".encode()).hexdigest()[:10],
                "title": title,
                "selfText": body,
                "author": "unknown",
                "subreddit": subreddit,
                "score": score,
                "upVotes": score,
                "url": url,
                "numComments": len(comments),
                "created": 0,
                "comments": comments,
            })

    return threads


def _parse_plaintext_threads(text):
    """Parse plain text — each double-newline-separated block becomes a thread."""
    import re
    threads = []
    blocks = re.split(r"\n\n+", text)

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 20:
            continue

        lines = block.split("\n")
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        sub_match = re.search(r"r/(\w+)", block)
        subreddit = sub_match.group(1) if sub_match else "unknown"

        threads.append({
            "id": hashlib.md5(title.encode()).hexdigest()[:10],
            "title": title,
            "selfText": body,
            "author": "unknown",
            "subreddit": subreddit,
            "score": 0,
            "upVotes": 0,
            "url": "",
            "numComments": 0,
            "created": 0,
            "comments": [],
        })

    return threads


# ── Main Runner ────────────────────────────────────────────────


def run_step2(parsed_data, max_threads=50, max_comments=50, product=""):
    """
    Run Step 2: Scrape Reddit via Apify (primary) or web search (fallback).

    Returns:
        tuple: (list of thread dicts, method string)
        method is "apify", "web_search", or "none"
    """
    print("\n" + "=" * 60)
    print("STEP 2: Reddit Scraping (Apify)")
    print("=" * 60)

    # ── Primary: Apify ─────────────────────────────────────
    if not APIFY_TOKEN:
        print("  ⚠ No APIFY_API_TOKEN set — skipping Apify, trying web search...")
    else:
        search_urls = build_search_urls(parsed_data)

        if not search_urls:
            print("  ⚠ No search URLs to scrape. Check Step 1 output.")
        else:
            print(f"  → Built {len(search_urls)} search URLs from Step 1 data")

            # Process in batches of 6 URLs per Apify call (to stay within limits)
            all_items = []
            batch_size = 6

            for i in range(0, len(search_urls), batch_size):
                batch_urls = search_urls[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (len(search_urls) + batch_size - 1) // batch_size

                print(f"  → Apify batch {batch_num}/{total_batches} ({len(batch_urls)} URLs)...")

                raw_items = run_apify_scraper(
                    batch_urls,
                    max_posts=min(25, max_threads),
                    max_comments=max_comments,
                )

                if raw_items:
                    threads = normalize_apify_results(raw_items)
                    all_items.extend(threads)
                    print(f"     Got {len(threads)} threads (total: {len(all_items)})")
                else:
                    print(f"     Got 0 items from this batch")

                if len(all_items) >= MAX_TOTAL_THREADS:
                    print(f"  → Hit {MAX_TOTAL_THREADS} thread cap.")
                    break

                # Small delay between batches
                if i + batch_size < len(search_urls):
                    time.sleep(2)

            unique_items = deduplicate_threads(all_items)
            print(f"\n  → Total: {len(all_items)}, after dedup: {len(unique_items)}")

            if unique_items:
                print(f"  ✓ Step 2 complete (Apify)\n")
                return unique_items[:MAX_TOTAL_THREADS], "apify"

    # ── No results ────────────────
    print("  ✗ Apify returned 0 results. Use the retry button or upload Reddit data manually.\n")
    return [], "none"
