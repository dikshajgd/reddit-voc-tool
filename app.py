"""
Reddit VOC Research Pipeline — Web UI
Run with: streamlit run app.py
"""

import os
import time

import streamlit as st
from dotenv import load_dotenv

from step1_keyword_gen import run_step1, parse_subreddits, parse_keywords
from step2_scrape import run_step2, parse_uploaded_threads
from step3_extract_voc import run_step3
from step4_persona_cluster import run_step4

# Load env — .env for local, st.secrets for Streamlit Cloud
load_dotenv()

# Bridge Streamlit Cloud secrets into os.environ for SDK compatibility
try:
    for key in ["ANTHROPIC_API_KEY", "APIFY_API_TOKEN"]:
        if key in st.secrets:
            val = st.secrets[key].strip()
            os.environ[key] = val
except Exception:
    pass  # st.secrets not available locally

# ── Page Config ─────────────────────────────────────────────
st.set_page_config(
    page_title="Reddit VOC Pipeline",
    page_icon="🔍",
    layout="wide",
)

# DEBUG: show key info in sidebar (remove after confirming)
_k = os.environ.get("ANTHROPIC_API_KEY", "")
if _k:
    st.sidebar.info(f"API key loaded: {_k[:12]}...{_k[-4:]} (len={len(_k)})")
else:
    st.sidebar.warning("No ANTHROPIC_API_KEY found in env")

# ── Custom CSS ──────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 2rem;
    }
    .stDownloadButton > button {
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

# ── Session State Init ──────────────────────────────────────
defaults = {
    "pipeline_running": False,
    "step1_result": None,
    "step1_md": None,
    "step1_skipped": False,
    "step2_result": None,
    "step2_method": None,
    "step3_md": None,
    "step4_md": None,
    "current_step": 0,
    "step2_failed": False,
    "step3_failed": False,
    "step4_failed": False,
    "logs": [],
    "error": None,
    "elapsed": None,
    "run_product": None,
    "review_submitted": False,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ── Header ──────────────────────────────────────────────────
st.markdown('<p class="main-header">Reddit VOC Research Pipeline</p>', unsafe_allow_html=True)

# ── Sidebar: Settings ──────────────────────────────────────
with st.sidebar:
    st.header("Settings")

    st.subheader("Scraping Limits")

    max_threads = st.slider("Max threads per keyword", 10, 200, 50)
    max_comments = st.slider("Max comments per thread", 10, 200, 100)

    output_dir = st.text_input("Output directory", value="./outputs")

    st.divider()
    st.caption("Pipeline uses Claude Sonnet via Anthropic API.")


# ── Main Form ───────────────────────────────────────────────
col1, col2 = st.columns(2)

with col1:
    product = st.text_input(
        "Product / Category *",
        placeholder="e.g., tone adapting foundation, standing desk, greens powder",
    )
    brand_url = st.text_input(
        "Brand URL (optional)",
        placeholder="e.g., https://smooche.com",
    )

with col2:
    industry = st.text_input(
        "Industry / Niche *",
        placeholder="e.g., beauty/cosmetics, office furniture, health supplements",
    )
    keywords = st.text_input(
        "Extra Keywords (optional)",
        placeholder="e.g., color changing, self-adjusting, pH reactive",
    )


# ── Step 1 Upload Bypass ───────────────────────────────────
have_map = st.checkbox("Already have a subreddit map?", key="have_subreddit_map")

uploaded_step1_data = None
uploaded_step1_text = None

if have_map:
    uploaded_file = st.file_uploader(
        "Upload your subreddit map (.md file)",
        type=["md", "txt"],
        help="Upload a previously generated SUBREDDIT NAMES file to skip Step 1.",
        key="step1_uploader",
    )
    if uploaded_file is not None:
        uploaded_step1_text = uploaded_file.read().decode("utf-8")
        subs = parse_subreddits(uploaded_step1_text)
        kws = parse_keywords(uploaded_step1_text)
        total_subs = sum(len(v) for v in subs.values())
        total_kws = sum(len(v) for v in kws.values())

        if total_subs > 0 and total_kws > 0:
            uploaded_step1_data = {"subreddits": subs, "keywords": kws}
            st.success(f"Parsed **{total_subs} subreddits** across {len(subs)} tiers and **{total_kws} keywords** across {len(kws)} categories. Step 1 will be skipped.")
        else:
            st.warning(
                f"Could only parse {total_subs} subreddits and {total_kws} keywords. "
                "Make sure the file follows the expected format with subreddit tiers and keyword categories."
            )


# ── Pipeline Resume Helpers (must be defined before use) ────


def _run_from_step2(max_threads, max_comments, industry, brand_url, output_dir):
    """Resume pipeline from Step 2 using saved Step 1 result."""
    start = time.time()
    progress = st.empty()
    parsed_data = st.session_state.step1_result
    run_product = st.session_state.run_product

    # ── Step 2 ──
    progress.info("⏳ **Step 2/4** — Retrying Reddit scraping...")
    st.session_state.logs.append("Retrying Step 2: Reddit Scraping...")
    try:
        scraped_data, method = run_step2(
            parsed_data=parsed_data,
            max_threads=max_threads, max_comments=max_comments,
            product=run_product or "",
        )
        st.session_state.step2_result = scraped_data
        st.session_state.step2_method = method
        if len(scraped_data) == 0:
            st.session_state.step2_failed = True
            st.session_state.error = (
                "Reddit still returned no results. "
                "You can retry again or upload your own Reddit data."
            )
            st.session_state.logs.append("Retry: Still 0 threads scraped.")
            st.session_state.current_step = 2
            st.session_state.pipeline_running = False
            st.rerun()
        method_label = {"json_api": "JSON API", "web_search": "web search", "apify": "Apify"}.get(method, method)
        st.session_state.logs.append(
            f"Step 2 complete via {method_label} (retry). Scraped {len(scraped_data)} threads."
        )
        st.session_state.current_step = 3
    except Exception as e:
        st.session_state.step2_failed = True
        st.session_state.error = str(e)
        st.session_state.logs.append(f"Step 2 retry failed: {e}")
        st.session_state.pipeline_running = False
        st.rerun()

    _run_steps_3_and_4(scraped_data, industry, brand_url, output_dir, progress, start)


def _run_from_step3(scraped_data, industry, brand_url, output_dir):
    """Resume pipeline from Step 3 using provided scraped data."""
    start = time.time()
    progress = st.empty()

    _run_steps_3_and_4(scraped_data, industry, brand_url, output_dir, progress, start)


def _run_steps_3_and_4(scraped_data, industry, brand_url, output_dir, progress, start):
    """Run Steps 3 and 4, then finalize."""
    run_product = st.session_state.run_product

    # ── Step 3 ──
    progress.info("⏳ **Step 3/4** — Extracting VOC insights (Claude Opus)...")
    st.session_state.logs.append("Starting Step 3: VOC Extraction & Classification...")
    try:
        voc_path = run_step3(
            scraped_data=scraped_data,
            product=run_product, industry=industry,
            brand_url=brand_url or None, output_dir=output_dir,
        )
        if voc_path and os.path.exists(voc_path):
            with open(voc_path, "r") as f:
                st.session_state.step3_md = f.read()
            st.session_state.logs.append("Step 3 complete. VOC document generated.")
        else:
            st.session_state.step3_failed = True
            st.session_state.logs.append("Step 3 finished but no VOC file was created.")
    except Exception as e:
        st.session_state.step3_failed = True
        st.session_state.logs.append(f"Step 3 failed: {e}")
    st.session_state.current_step = 4

    # ── Step 4 ──
    if st.session_state.step3_md:
        progress.info("⏳ **Step 4/4** — Clustering personas & awareness levels (Claude Opus)...")
        st.session_state.logs.append("Starting Step 4: Persona & Awareness Level Clustering...")
        try:
            persona_path = run_step4(
                voc_md=st.session_state.step3_md,
                product=run_product, industry=industry,
                output_dir=output_dir,
            )
            if persona_path and os.path.exists(persona_path):
                with open(persona_path, "r") as f:
                    st.session_state.step4_md = f.read()
                st.session_state.logs.append("Step 4 complete. Personas & awareness levels generated.")
            else:
                st.session_state.step4_failed = True
                st.session_state.logs.append("Step 4 finished but no persona file was created.")
        except Exception as e:
            st.session_state.step4_failed = True
            st.session_state.logs.append(f"Step 4 failed: {e}")

    st.session_state.elapsed = (st.session_state.elapsed or 0) + (time.time() - start)
    st.session_state.current_step = 5 if st.session_state.step4_md else 4
    st.session_state.pipeline_running = False
    progress.empty()
    st.rerun()


# ── Step Status Helpers ─────────────────────────────────────
def step_status(step_num):
    current = st.session_state.current_step
    if step_num == 1 and st.session_state.step1_skipped:
        return "skipped"
    if step_num == 2 and st.session_state.step2_failed:
        return "failed"
    if step_num == 3 and st.session_state.step3_failed:
        return "failed"
    if step_num == 4 and st.session_state.step4_failed:
        return "failed"
    if step_num == 5:
        # Manual review step
        if st.session_state.review_submitted:
            return "complete"
        elif st.session_state.current_step >= 5:
            return "active"
        return "pending"
    if step_num < current:
        return "complete"
    elif step_num == current and st.session_state.pipeline_running:
        return "active"
    return "pending"


def step_icon(status):
    icons = {
        "complete": "✅",
        "active": "⏳",
        "failed": "❌",
        "pending": "⬜",
        "skipped": "⏭️",
    }
    return icons.get(status, "⬜")


# ── Launch Button ───────────────────────────────────────────
st.divider()

col_btn, col_space = st.columns([1, 3])
with col_btn:
    run_clicked = st.button(
        "🚀 Run Pipeline",
        disabled=st.session_state.pipeline_running,
        use_container_width=True,
        type="primary",
    )

if run_clicked:
    if not product or not industry:
        st.error("Product and Industry are required.")
    else:
        # Reset state
        st.session_state.pipeline_running = True
        st.session_state.step1_result = None
        st.session_state.step1_md = None
        st.session_state.step1_skipped = False
        st.session_state.step2_result = None
        st.session_state.step2_method = None
        st.session_state.step3_md = None
        st.session_state.step4_md = None
        st.session_state.step2_failed = False
        st.session_state.step3_failed = False
        st.session_state.step4_failed = False
        st.session_state.current_step = 1
        st.session_state.logs = []
        st.session_state.error = None
        st.session_state.elapsed = None
        st.session_state.review_submitted = False
        st.session_state.run_product = product

        start = time.time()
        progress = st.empty()

        # ── Step 1 ──────────────────────────────────────────
        if uploaded_step1_data:
            # Skip Step 1 — use uploaded subreddit map
            parsed_data = uploaded_step1_data
            st.session_state.step1_result = parsed_data
            st.session_state.step1_md = uploaded_step1_text
            st.session_state.step1_skipped = True
            total_subs = sum(len(v) for v in parsed_data.get("subreddits", {}).values())
            total_kws = sum(len(v) for v in parsed_data.get("keywords", {}).values())
            st.session_state.logs.append(
                f"Step 1 skipped (uploaded). Using {total_subs} subreddits, {total_kws} keywords."
            )
            st.session_state.current_step = 2
        else:
            progress.info("⏳ **Step 1/4** — Generating keywords & subreddit map (Claude Opus)...")
            st.session_state.logs.append("Starting Step 1: Keyword & Subreddit Generation...")
            try:
                parsed_data = run_step1(
                    product=product, industry=industry,
                    brand_url=brand_url or None, extra_keywords=keywords or None,
                    output_dir=output_dir,
                )
                st.session_state.step1_result = parsed_data
                md_path = os.path.join(output_dir, f"SUBREDDIT NAMES {product}.md")
                if os.path.exists(md_path):
                    with open(md_path, "r") as f:
                        st.session_state.step1_md = f.read()
                total_subs = sum(len(v) for v in parsed_data.get("subreddits", {}).values())
                total_kws = sum(len(v) for v in parsed_data.get("keywords", {}).values())
                st.session_state.logs.append(f"Step 1 complete. Found {total_subs} subreddits, {total_kws} keywords.")
                st.session_state.current_step = 2
            except Exception as e:
                st.session_state.error = str(e)
                st.session_state.logs.append(f"Step 1 failed: {e}")
                st.session_state.pipeline_running = False
                st.rerun()

        # ── Step 2 ──────────────────────────────────────────
        progress.info("⏳ **Step 2/4** — Scraping Reddit threads...")
        st.session_state.logs.append("Starting Step 2: Reddit Scraping...")
        try:
            scraped_data, method = run_step2(
                parsed_data=parsed_data,
                max_threads=max_threads, max_comments=max_comments,
                product=product,
            )
            st.session_state.step2_result = scraped_data
            st.session_state.step2_method = method
            if len(scraped_data) == 0:
                st.session_state.step2_failed = True
                st.session_state.error = (
                    "Reddit returned no results even after web search fallback. "
                    "You can **retry**, or **upload** your own Reddit data below."
                )
                st.session_state.logs.append(
                    "Step 2 finished but scraped 0 threads (JSON API + web search both failed)."
                )
                st.session_state.current_step = 2
                st.session_state.pipeline_running = False
                st.rerun()
            method_label = {"json_api": "JSON API", "web_search": "web search fallback", "apify": "Apify"}.get(method, method)
            st.session_state.logs.append(
                f"Step 2 complete via {method_label}. Scraped {len(scraped_data)} threads."
            )
            st.session_state.current_step = 3
        except Exception as e:
            st.session_state.step2_failed = True
            st.session_state.error = str(e)
            st.session_state.logs.append(f"Step 2 failed: {e}")
            st.session_state.pipeline_running = False
            st.rerun()

        # ── Step 3 ──────────────────────────────────────────
        progress.info("⏳ **Step 3/4** — Extracting VOC insights (Claude Opus)...")
        st.session_state.logs.append("Starting Step 3: VOC Extraction & Classification...")
        try:
            voc_path = run_step3(
                scraped_data=scraped_data, product=product, industry=industry,
                brand_url=brand_url or None, output_dir=output_dir,
            )
            if voc_path and os.path.exists(voc_path):
                with open(voc_path, "r") as f:
                    st.session_state.step3_md = f.read()
                st.session_state.logs.append("Step 3 complete. VOC document generated.")
            else:
                st.session_state.step3_failed = True
                st.session_state.logs.append("Step 3 finished but no VOC file was created.")
        except Exception as e:
            st.session_state.step3_failed = True
            st.session_state.logs.append(f"Step 3 failed: {e}")
        st.session_state.current_step = 4

        # ── Step 4 ──────────────────────────────────────────
        if st.session_state.step3_md:
            progress.info("⏳ **Step 4/4** — Clustering personas & awareness levels (Claude Opus)...")
            st.session_state.logs.append("Starting Step 4: Persona & Awareness Level Clustering...")
            try:
                persona_path = run_step4(
                    voc_md=st.session_state.step3_md,
                    product=product, industry=industry, output_dir=output_dir,
                )
                if persona_path and os.path.exists(persona_path):
                    with open(persona_path, "r") as f:
                        st.session_state.step4_md = f.read()
                    st.session_state.logs.append("Step 4 complete. Personas & awareness levels generated.")
                else:
                    st.session_state.step4_failed = True
                    st.session_state.logs.append("Step 4 finished but no persona file was created.")
            except Exception as e:
                st.session_state.step4_failed = True
                st.session_state.logs.append(f"Step 4 failed: {e}")

        st.session_state.elapsed = time.time() - start
        st.session_state.current_step = 5 if st.session_state.step4_md else 4
        st.session_state.pipeline_running = False
        progress.empty()
        st.rerun()


# ── Progress Display ────────────────────────────────────────
if st.session_state.current_step > 0:
    st.divider()

    steps = [
        ("Step 1", "Keyword & Subreddit Generation", "Claude Opus generates subreddit map + keyword clusters"),
        ("Step 2", "Reddit Scraping", "Scraping threads and comments from targeted subreddits"),
        ("Step 3", "VOC Extraction", "Claude Opus classifies insights into pain points, phrases, objections, outcomes"),
        ("Step 4", "Persona Clustering", "Claude Opus clusters VOC data into buyer personas + awareness levels"),
        ("Step 5", "Manual Review", "Review and remove irrelevant or low-quality inputs"),
    ]

    prog_cols = st.columns(5)
    for i, (label, title, desc) in enumerate(steps):
        step_num = i + 1
        status = step_status(step_num)
        icon = step_icon(status)

        with prog_cols[i]:
            st.markdown(f"#### {icon} {label}")
            st.caption(title)
            if status == "active" and step_num != 5:
                st.info("Running...")
            elif status == "active" and step_num == 5:
                st.info("Your turn")
            elif status == "complete":
                st.success("Done")
            elif status == "skipped":
                st.info("Skipped (uploaded)")
            elif status == "failed":
                st.warning("Failed")

    # Metrics
    if not st.session_state.pipeline_running and st.session_state.current_step >= 2:
        st.divider()
        m1, m2, m3, m4 = st.columns(4)

        total_subs = sum(len(v) for v in st.session_state.step1_result.get("subreddits", {}).values()) if st.session_state.step1_result else 0
        total_kws = sum(len(v) for v in st.session_state.step1_result.get("keywords", {}).values()) if st.session_state.step1_result else 0
        total_threads = len(st.session_state.step2_result) if st.session_state.step2_result else 0
        elapsed_str = f"{int(st.session_state.elapsed // 60)}m {int(st.session_state.elapsed % 60)}s" if st.session_state.elapsed else "-"

        m1.metric("Subreddits Found", total_subs)
        m2.metric("Keywords Generated", total_kws)
        m3.metric("Threads Scraped", total_threads)
        m4.metric("Total Time", elapsed_str)


# ── Error Display ───────────────────────────────────────────
if st.session_state.error:
    st.error(f"Pipeline error: {st.session_state.error}")


# ── Step 2 Recovery: Retry + Upload ─────────────────────────
if st.session_state.step2_failed and st.session_state.step1_result and not st.session_state.pipeline_running:

    col_retry, col_upload_label, _ = st.columns([1, 2, 1])
    with col_retry:
        retry_clicked = st.button("🔄 Retry from Step 2", type="primary", use_container_width=True)

    st.markdown("**— or upload your own Reddit data —**")

    uploaded_reddit_file = st.file_uploader(
        "Upload scraped Reddit data",
        type=["md", "txt", "json"],
        help="Upload a file with Reddit threads and comments. Accepts .json (thread array), .md (markdown formatted), or .txt (plain text).",
        key="step2_uploader",
    )

    upload_clicked = False
    if uploaded_reddit_file is not None:
        reddit_text = uploaded_reddit_file.read().decode("utf-8")
        ext = uploaded_reddit_file.name.rsplit(".", 1)[-1] if "." in uploaded_reddit_file.name else "txt"
        parsed_threads = parse_uploaded_threads(reddit_text, ext)

        if parsed_threads:
            total_comments = sum(len(t.get("comments", [])) for t in parsed_threads)
            subs_found = set(t.get("subreddit", "unknown") for t in parsed_threads)
            st.success(
                f"Parsed **{len(parsed_threads)} threads** with **{total_comments} comments** "
                f"from **{len(subs_found)} subreddits**."
            )
            upload_clicked = st.button("✅ Use Uploaded Data & Continue", type="primary")
        else:
            st.warning("Could not parse any threads from the uploaded file. Try a different format.")

    # Handle retry click
    if retry_clicked:
        st.session_state.step2_failed = False
        st.session_state.step2_result = None
        st.session_state.step2_method = None
        st.session_state.step3_md = None
        st.session_state.step4_md = None
        st.session_state.step3_failed = False
        st.session_state.step4_failed = False
        st.session_state.error = None
        st.session_state.pipeline_running = True
        st.session_state.current_step = 2

        _run_from_step2(max_threads, max_comments, industry, brand_url, output_dir)

    # Handle upload click
    if upload_clicked and parsed_threads:
        st.session_state.step2_failed = False
        st.session_state.step2_result = parsed_threads
        st.session_state.step2_method = "uploaded"
        st.session_state.step3_md = None
        st.session_state.step4_md = None
        st.session_state.step3_failed = False
        st.session_state.step4_failed = False
        st.session_state.error = None
        st.session_state.pipeline_running = True
        st.session_state.current_step = 3
        st.session_state.logs.append(
            f"Step 2 bypassed (uploaded). Using {len(parsed_threads)} threads."
        )

        _run_from_step3(parsed_threads, industry, brand_url, output_dir)


# ── Results Tabs ────────────────────────────────────────────
display_product = st.session_state.run_product or product

has_results = st.session_state.step1_md or st.session_state.step3_md or st.session_state.step4_md

if has_results:
    st.divider()
    st.header("Results")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 Subreddit Map",
        "📊 VOC Document",
        "🧑‍🤝‍🧑 Personas & Awareness",
        "✏️ Manual Review",
        "📝 Logs",
    ])

    # ── Tab 1: Subreddit Map ────────────────────────────────
    with tab1:
        if st.session_state.step1_md:
            st.download_button(
                "⬇️  Download Subreddit Map (.md)",
                data=st.session_state.step1_md,
                file_name=f"SUBREDDIT NAMES {display_product}.md",
                mime="text/markdown",
            )
            st.markdown("---")
            st.markdown(st.session_state.step1_md)
        else:
            st.info("Subreddit map will appear here after Step 1 completes.")

    # ── Tab 2: VOC Document ─────────────────────────────────
    with tab2:
        if st.session_state.step3_md:
            st.download_button(
                "⬇️  Download VOC Document (.md)",
                data=st.session_state.step3_md,
                file_name=f"REDDIT VOC {display_product}.md",
                mime="text/markdown",
            )
            st.markdown("---")
            st.markdown(st.session_state.step3_md)
        elif st.session_state.step3_failed:
            st.warning(
                "Step 3 could not generate a VOC document. "
                "This usually means Step 2 returned no scraped threads. "
                "Check the Logs tab for details."
            )
        else:
            st.info("VOC document will appear here after Step 3 completes.")

    # ── Tab 3: Personas & Awareness ─────────────────────────
    with tab3:
        if st.session_state.step4_md:
            st.download_button(
                "⬇️  Download Personas (.md)",
                data=st.session_state.step4_md,
                file_name=f"PERSONAS {display_product}.md",
                mime="text/markdown",
            )
            st.markdown("---")
            st.markdown(st.session_state.step4_md)
        elif st.session_state.step4_failed:
            st.warning(
                "Step 4 could not generate personas. "
                "Check the Logs tab for details."
            )
        else:
            st.info("Persona clustering will appear here after Step 4 completes.")

    # ── Tab 4: Manual Review ────────────────────────────────
    with tab4:
        if st.session_state.step4_md:
            st.subheader("Review & Clean Up")
            st.caption(
                "Review the personas and VOC data below. "
                "Remove any irrelevant or low-quality entries, then save your cleaned version."
            )

            # Editable text area with the persona output
            edited_personas = st.text_area(
                "Edit Personas & Awareness Levels",
                value=st.session_state.step4_md,
                height=500,
                key="persona_editor",
            )

            # Also allow editing VOC if needed
            with st.expander("Edit VOC Document (optional)"):
                edited_voc = st.text_area(
                    "Edit VOC Data",
                    value=st.session_state.step3_md or "",
                    height=400,
                    key="voc_editor",
                )

            col_save, col_dl, _ = st.columns([1, 1, 2])

            with col_save:
                if st.button("💾 Save Changes", type="primary"):
                    st.session_state.step4_md = edited_personas
                    if edited_voc:
                        st.session_state.step3_md = edited_voc

                    # Save to disk
                    out = st.session_state.get("run_product", display_product)
                    os.makedirs(output_dir, exist_ok=True)

                    persona_path = os.path.join(output_dir, f"PERSONAS {out}.md")
                    with open(persona_path, "w") as f:
                        f.write(edited_personas)

                    if edited_voc:
                        voc_path = os.path.join(output_dir, f"REDDIT VOC {out}.md")
                        with open(voc_path, "w") as f:
                            f.write(edited_voc)

                    st.session_state.review_submitted = True
                    st.success("Changes saved!")
                    st.rerun()

            with col_dl:
                st.download_button(
                    "⬇️  Download Cleaned Personas (.md)",
                    data=edited_personas,
                    file_name=f"PERSONAS {display_product} - cleaned.md",
                    mime="text/markdown",
                )

        elif st.session_state.current_step < 5:
            st.info("Manual review will be available after Step 4 (Persona Clustering) completes.")
        else:
            st.warning("No persona data to review. Check earlier steps.")

    # ── Tab 5: Logs ─────────────────────────────────────────
    with tab5:
        if st.session_state.logs:
            for log in st.session_state.logs:
                if "ERROR" in log or "failed" in log.lower():
                    st.error(log)
                elif "complete" in log.lower() or "skipped" in log.lower():
                    st.success(log)
                else:
                    st.text(log)
        else:
            st.info("Pipeline logs will appear here.")
