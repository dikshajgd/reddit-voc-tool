#!/usr/bin/env python3
"""
Reddit VOC Research Pipeline
=============================
Automated pipeline that takes a brand/product as input and outputs:
1. SUBREDDIT NAMES {product}.md — Subreddit targeting map + keyword clusters
2. REDDIT VOC {product}.md — Extracted pain points, phrases, objections, and desired outcomes

Usage:
    python main.py --product "tone adapting foundation" --industry "beauty/cosmetics" \
        --brand-url "https://smooche.com" --keywords "color changing, self-adjusting"

    python main.py --product "greens powder" --industry "health supplements" \
        --keywords "AG1, gut health"

    python main.py --product "standing desk" --industry "office furniture"
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv

from step1_keyword_gen import run_step1
from step2_scrape import run_step2
from step3_extract_voc import run_step3


def main():
    parser = argparse.ArgumentParser(
        description="Reddit VOC Research Pipeline — automated voice-of-customer extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--product",
        required=True,
        help="Product name or category (e.g., 'tone adapting foundation')",
    )
    parser.add_argument(
        "--industry",
        required=True,
        help="Industry or niche (e.g., 'beauty/cosmetics')",
    )
    parser.add_argument(
        "--brand-url",
        default=None,
        help="Brand website URL for competitor/positioning context",
    )
    parser.add_argument(
        "--keywords",
        default=None,
        help="Comma-separated extra keywords (e.g., 'color changing, self-adjusting')",
    )
    parser.add_argument(
        "--output-dir",
        default="./outputs",
        help="Output folder (default: ./outputs/)",
    )
    parser.add_argument(
        "--max-threads",
        type=int,
        default=50,
        help="Max Reddit threads per keyword cluster (default: 50)",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=100,
        help="Max comments per thread (default: 100)",
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    # Pipeline banner
    print("\n" + "=" * 60)
    print("  REDDIT VOC RESEARCH PIPELINE")
    print("=" * 60)
    print(f"  Product:    {args.product}")
    print(f"  Industry:   {args.industry}")
    print(f"  Brand URL:  {args.brand_url or 'None'}")
    print(f"  Keywords:   {args.keywords or 'None'}")
    print(f"  Output Dir: {args.output_dir}")
    print(f"  Max Threads: {args.max_threads}")
    print(f"  Max Comments: {args.max_comments}")
    print("=" * 60)

    start_time = time.time()

    # ── Step 1: Keyword & Subreddit Generation ──────────────────
    try:
        parsed_data = run_step1(
            product=args.product,
            industry=args.industry,
            brand_url=args.brand_url,
            extra_keywords=args.keywords,
            output_dir=args.output_dir,
        )
    except Exception as e:
        print(f"\n✗ Step 1 failed: {e}")
        sys.exit(1)

    # ── Step 2: Reddit Scraping via Apify ───────────────────────
    try:
        scraped_data = run_step2(
            parsed_data=parsed_data,
            max_threads=args.max_threads,
            max_comments=args.max_comments,
        )
    except Exception as e:
        print(f"\n✗ Step 2 failed: {e}")
        sys.exit(1)

    # ── Step 3: VOC Extraction & Classification ─────────────────
    try:
        voc_path = run_step3(
            scraped_data=scraped_data,
            product=args.product,
            industry=args.industry,
            brand_url=args.brand_url,
            output_dir=args.output_dir,
        )
    except Exception as e:
        print(f"\n✗ Step 3 failed: {e}")
        sys.exit(1)

    # ── Done ────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Time: {minutes}m {seconds}s")
    print(f"  Threads scraped: {len(scraped_data)}")
    print(f"  Output files:")
    print(f"    1. {args.output_dir}/SUBREDDIT NAMES {args.product}.md")
    if voc_path:
        print(f"    2. {voc_path}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
