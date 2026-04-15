"""
Step 1: Keyword & Subreddit Generation
Uses Anthropic SDK (Claude Sonnet)
Output: SUBREDDIT NAMES {product}.md + parsed data for Step 2
"""

import os
import re
import json

from lib.claude_client import call_claude, strip_preamble

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "keyword_cluster.md")


def load_prompt(product, industry, brand_url, extra_keywords):
    """Load and render the keyword cluster system prompt."""
    with open(PROMPT_PATH, "r") as f:
        prompt = f.read()

    prompt = prompt.replace("{{PRODUCT_OR_CATEGORY}}", product)
    prompt = prompt.replace("{{BRAND_URL_OR_NONE}}", brand_url or "None")
    prompt = prompt.replace("{{INDUSTRY}}", industry)
    prompt = prompt.replace("{{EXTRA_KEYWORDS_OR_NONE}}", extra_keywords or "None")

    return prompt


def parse_subreddits(text):
    """Extract subreddit names from the markdown output, grouped by tier."""
    tiers = {}
    current_tier = None

    tier_patterns = [
        "core niche",
        "adjacent problem",
        "identity/demographic",
        "identity",
        "demographic",
        "review & shopping",
        "review",
        "shopping",
        "general rant",
        "general discussion",
        "rant/discussion",
    ]

    for line in text.split("\n"):
        line_lower = line.lower().strip()

        # Detect tier headings
        for pattern in tier_patterns:
            if pattern in line_lower and (
                line_lower.startswith("#")
                or line_lower.startswith("**")
                or line_lower.startswith("-")
            ):
                if "core" in line_lower:
                    current_tier = "core"
                elif "adjacent" in line_lower:
                    current_tier = "adjacent"
                elif "identity" in line_lower or "demographic" in line_lower:
                    current_tier = "identity"
                elif "review" in line_lower or "shopping" in line_lower:
                    current_tier = "shopping"
                elif "rant" in line_lower or "general" in line_lower:
                    current_tier = "general"

                if current_tier and current_tier not in tiers:
                    tiers[current_tier] = []
                break

        # Extract subreddit names (r/SubredditName pattern)
        subreddit_matches = re.findall(r"r/([A-Za-z0-9_]+)", line)
        if subreddit_matches and current_tier:
            for sub in subreddit_matches:
                if sub not in tiers[current_tier]:
                    tiers[current_tier].append(sub)

    return tiers


def parse_keywords(text):
    """Extract keyword clusters from the markdown output, grouped by category."""
    categories = {}
    current_category = None

    category_markers = {
        "pain point": "pain_points",
        "product frustration": "product_frustrations",
        "skin/user-type": "user_type",
        "user-type": "user_type",
        "desired outcome": "desired_outcomes",
        "i wish": "desired_outcomes",
        "purchase hesitation": "objections",
        "objection": "objections",
        "competitor": "competitors",
        "adjacent product": "competitors",
        "shopping behavior": "shopping",
        "decision": "shopping",
    }

    for line in text.split("\n"):
        line_lower = line.lower().strip()

        # Detect category headings
        for marker, cat_key in category_markers.items():
            if marker in line_lower and (
                line_lower.startswith("#")
                or line_lower.startswith("**")
                or line_lower.startswith("a.")
                or line_lower.startswith("b.")
                or line_lower.startswith("c.")
                or line_lower.startswith("d.")
                or line_lower.startswith("e.")
                or line_lower.startswith("f.")
                or line_lower.startswith("g.")
            ):
                current_category = cat_key
                if current_category not in categories:
                    categories[current_category] = []
                break

        # Extract keywords from bullet points, numbered lists, and quoted phrases
        if current_category:
            stripped_line = line.strip()
            is_list_item = (
                stripped_line.startswith("-")
                or stripped_line.startswith("*")
                or stripped_line.startswith("\u2022")
                or re.match(r"^\d+[\.\)]\s", stripped_line)  # numbered lists: 1. or 1)
            )

            if is_list_item:
                # Remove list prefix (bullet or number)
                keyword = re.sub(r"^[\-\*\u2022]\s*", "", stripped_line)
                keyword = re.sub(r"^\d+[\.\)]\s*", "", keyword)
                # Remove markdown bold markers
                keyword = re.sub(r"\*\*(.+?)\*\*", r"\1", keyword)
                # Extract quoted phrase if present (e.g., "can't find my shade")
                quoted = re.findall(r'"([^"]+)"', keyword)
                if quoted:
                    # Use the quoted phrase(s) as keywords
                    for q in quoted:
                        q = q.strip()
                        if q and len(q) > 2:
                            categories[current_category].append(q)
                else:
                    # Use the whole line as a keyword
                    keyword = keyword.strip('"').strip("'").strip()
                    # Remove trailing descriptions after common separators
                    for sep in [" \u2014 ", " -- ", " (", " / "]:
                        if sep in keyword:
                            parts = keyword.split(sep)
                            keyword = parts[0].strip()
                            # Also add the alternate after /
                            if sep == " / " and len(parts) > 1:
                                alt = parts[1].strip().strip('"').strip("'")
                                if alt and len(alt) > 2:
                                    categories[current_category].append(alt)
                            break
                    if keyword and len(keyword) > 2:
                        categories[current_category].append(keyword)

    return categories


def run_step1(product, industry, brand_url=None, extra_keywords=None, output_dir="./outputs"):
    """
    Run Step 1: Generate subreddit targeting map + keyword clusters.

    Returns:
        dict with 'subreddits' (by tier) and 'keywords' (by category)
    """
    print("\n" + "=" * 60)
    print("STEP 1: Keyword & Subreddit Generation (Claude Sonnet via API)")
    print("=" * 60)

    # Load and render system prompt
    system_prompt = load_prompt(product, industry, brand_url, extra_keywords)

    # Add preamble suppression to system prompt
    system_prompt += (
        "\n\nIMPORTANT: Output ONLY the requested document. "
        "No introductory text, no preamble, no conversational filler. "
        "Start directly with the document content."
    )

    user_message = (
        f"Generate a comprehensive Reddit keyword and subreddit targeting plan for:\n\n"
        f"Product/Category: {product}\n"
        f"Industry: {industry}\n"
    )
    if brand_url:
        user_message += f"Brand URL: {brand_url}\n"
    if extra_keywords:
        user_message += f"Extra Keywords: {extra_keywords}\n"

    user_message += (
        "\nBe thorough and exhaustive. Include all subreddit tiers and all 7 keyword categories "
        "with 15-30 keywords each. Also include non-obvious angles."
    )

    print(f"  \u2192 Calling Claude Sonnet via API...")
    raw_output = call_claude(system_prompt, user_message)
    raw_output = strip_preamble(raw_output)
    print(f"  \u2192 Received {len(raw_output)} characters of output")

    # Save raw markdown
    os.makedirs(output_dir, exist_ok=True)
    output_filename = f"SUBREDDIT NAMES {product}.md"
    output_path = os.path.join(output_dir, output_filename)

    with open(output_path, "w") as f:
        f.write(raw_output)

    print(f"  \u2192 Saved: {output_path}")

    # Parse structured data for Step 2
    subreddits = parse_subreddits(raw_output)
    keywords = parse_keywords(raw_output)

    total_subs = sum(len(v) for v in subreddits.values())
    total_kws = sum(len(v) for v in keywords.values())

    print(f"  \u2192 Parsed {total_subs} subreddits across {len(subreddits)} tiers")
    print(f"  \u2192 Parsed {total_kws} keywords across {len(keywords)} categories")

    for tier, subs in subreddits.items():
        print(f"     {tier}: {', '.join(subs[:5])}{'...' if len(subs) > 5 else ''}")

    parsed_data = {
        "subreddits": subreddits,
        "keywords": keywords,
    }

    # Save parsed JSON for internal use
    json_path = os.path.join(output_dir, f".parsed_{product.replace(' ', '_')}.json")
    with open(json_path, "w") as f:
        json.dump(parsed_data, f, indent=2)

    print(f"  \u2192 Saved parsed data: {json_path}")
    print(f"  \u2713 Step 1 complete\n")

    return parsed_data
