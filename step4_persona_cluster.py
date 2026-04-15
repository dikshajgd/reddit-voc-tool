"""
Step 4: Persona & Awareness Level Clustering
Uses Anthropic SDK (Claude Sonnet)
Input: VOC document from Step 3
Output: PERSONAS {product}.md — personas + awareness levels
"""

import os

from lib.claude_client import call_claude, strip_preamble

SYSTEM_PROMPT = """You are a customer research strategist. You have been given a Voice-of-Customer (VOC) document extracted from Reddit threads about {{BRAND_OR_PRODUCT}} in the {{INDUSTRY}} space.

Your job is to cluster the raw VOC data into **buyer personas** and map each persona to an **awareness level**.

## 1. BUYER PERSONAS

Create 4-8 distinct personas based on patterns in the data. For each persona:

- **Persona Name** — a short, memorable label (e.g., "The Frustrated Switcher", "The Skeptical First-Timer")
- **Who they are** — demographics, lifestyle, key identifiers (2-3 sentences)
- **Core problem** — the #1 thing driving them to search (1 sentence)
- **Language they use** — 5-10 exact quotes from the VOC data that are characteristic of this persona
- **Objections** — their specific hesitations and doubts (with exact quotes)
- **What would convert them** — the message, proof, or feature that would tip them over (2-3 bullets)
- **Subreddits where they live** — which communities this persona is most active in

## 2. AWARENESS LEVEL MAPPING

Map each persona to Eugene Schwartz's 5 awareness levels:

| Level | Definition |
|-------|-----------|
| **Unaware** | Doesn't know they have a problem |
| **Problem Aware** | Knows the problem, doesn't know solutions exist |
| **Solution Aware** | Knows solutions exist, doesn't know your product |
| **Product Aware** | Knows your product, hasn't bought yet |
| **Most Aware** | Knows your product, just needs the right offer |

For each persona:
- Assign their **primary awareness level**
- Include 3-5 exact quotes that prove this level
- Note if the persona spans multiple levels (e.g., some are Solution Aware, some are Product Aware)

## 3. PERSONA \u00d7 AWARENESS MATRIX

Create a summary matrix:

| Persona | Awareness Level | Volume (High/Med/Low) | Conversion Difficulty | Best Channel |
|---------|----------------|----------------------|----------------------|-------------|

## 4. MESSAGING RECOMMENDATIONS

For each persona \u00d7 awareness level combination:
- **Hook angle** — what grabs their attention (1 sentence)
- **Key proof point** — what evidence convinces them
- **CTA style** — soft vs. hard, direct vs. educational

## Rules:
- Use EXACT quotes from the VOC document. Do not paraphrase.
- Every persona must be grounded in actual data — no invented segments.
- If a persona doesn't have enough evidence (< 5 quotes), merge it with another.
- Flag the 2-3 highest-opportunity personas (largest volume + easiest to convert).
- Note any personas that represent ANTI-audiences (people who will never buy)."""


def run_step4(voc_md, product, industry, output_dir="./outputs"):
    """
    Run Step 4: Cluster VOC data into personas and awareness levels.

    Args:
        voc_md: the full VOC markdown text from Step 3
        product: product name
        industry: industry/niche
        output_dir: output directory

    Returns:
        path to the generated personas markdown file
    """
    print("\n" + "=" * 60)
    print("STEP 4: Persona & Awareness Level Clustering (Claude Sonnet via API)")
    print("=" * 60)

    if not voc_md:
        raise ValueError("No VOC document to analyze. Step 3 must complete first.")

    # Render the system prompt
    system_prompt = SYSTEM_PROMPT.replace("{{BRAND_OR_PRODUCT}}", product)
    system_prompt = system_prompt.replace("{{INDUSTRY}}", industry)
    system_prompt += (
        "\n\nIMPORTANT: Output ONLY the requested document. "
        "No introductory text, no preamble, no conversational filler. "
        "Start directly with the document content."
    )

    user_content = (
        f"Here is the complete Voice-of-Customer document to analyze.\n"
        f"Cluster all data into buyer personas and map to awareness levels.\n\n"
        f"{voc_md}"
    )

    print(f"  \u2192 Sending VOC data ({len(voc_md)} chars) to Claude Sonnet via API...")
    raw_output = call_claude(system_prompt, user_content, max_tokens=16000)
    persona_output = strip_preamble(raw_output)

    # Save output
    os.makedirs(output_dir, exist_ok=True)
    output_filename = f"PERSONAS {product}.md"
    output_path = os.path.join(output_dir, output_filename)

    with open(output_path, "w") as f:
        f.write(persona_output)

    print(f"  \u2192 Saved: {output_path}")
    print(f"  \u2192 Output size: {len(persona_output)} chars")
    print(f"  \u2713 Step 4 complete\n")

    return output_path
