"""
Streamlit frontend for search and adding videos.

Calls FastAPI over HTTP — no direct Chroma access.
"""

import sys
from pathlib import Path

import httpx
import streamlit as st
from dotenv import load_dotenv

# Ensure project root is importable and .env is loaded (Streamlit does not do this).
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from app.config import get_settings
from frontend.streamlit_helpers import format_http_error, parse_ingest_response

# Ingest can take many minutes on first run (yt-dlp + sentence-transformers model load).
INGEST_TIMEOUT = httpx.Timeout(connect=10.0, read=900.0, write=60.0, pool=10.0)
INGEST_TIMEOUT_SECONDS = 900
SEARCH_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


def _api_base_url() -> str:
    """Resolve FastAPI base URL from the same settings source as the backend."""
    url = get_settings().fastapi_url.strip().rstrip("/")
    if url.endswith("/api/v1"):
        url = url[: -len("/api/v1")]
    return url or "http://127.0.0.1:8000"


def _api_client(timeout: httpx.Timeout) -> httpx.Client:
    # trust_env=False: avoid routing localhost through HTTP_PROXY (common dev misconfig).
    return httpx.Client(timeout=timeout, trust_env=False)


def _api_post(path: str, payload: dict, *, timeout: httpx.Timeout = INGEST_TIMEOUT) -> dict:
    with _api_client(timeout) as client:
        response = client.post(f"{_api_base_url()}{path}", json=payload)
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            snippet = (response.text or "")[:200]
            raise ValueError(f"Response was not valid JSON: {snippet}") from exc
        return body


def _api_get(path: str, params: dict) -> dict:
    with _api_client(SEARCH_TIMEOUT) as client:
        response = client.get(f"{_api_base_url()}{path}", params=params)
        response.raise_for_status()
        return response.json()


from app.utils.youtube_urls import build_timestamp_url


def _format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return "0"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


st.set_page_config(page_title="AI Memory Search Agent", layout="wide")

st.title("AI Memory Search Agent")
st.caption("Remember less. Find more. Act on what matters.")

st.header("Add YouTube videos")

if "ingest_in_progress" not in st.session_state:
    st.session_state.ingest_in_progress = False
if "ingest_pending_urls" not in st.session_state:
    st.session_state.ingest_pending_urls = None
if "ingest_result" not in st.session_state:
    st.session_state.ingest_result = None
if "ingest_error" not in st.session_state:
    st.session_state.ingest_error = None

url_text = st.text_area(
    "Paste YouTube URLs (one per line)",
    height=140,
    placeholder="https://www.youtube.com/watch?v=...\nhttps://youtu.be/...",
    disabled=st.session_state.ingest_in_progress,
)

process_clicked = st.button(
    "Process URLs",
    type="primary",
    disabled=st.session_state.ingest_in_progress,
    key="process_urls_button",
)

if process_clicked:
    urls = [line.strip() for line in url_text.splitlines() if line.strip()]
    if not urls:
        st.warning("Add at least one YouTube URL.")
    elif not st.session_state.ingest_in_progress:
        st.session_state.ingest_in_progress = True
        st.session_state.ingest_pending_urls = urls
        st.session_state.ingest_result = None
        st.session_state.ingest_error = None
        st.rerun()

if st.session_state.ingest_in_progress and st.session_state.ingest_pending_urls:
    urls = st.session_state.ingest_pending_urls
    spinner_message = (
        f"Processing {len(urls)} URL(s)... "
        f"(timeout {INGEST_TIMEOUT_SECONDS // 60} min). "
        "First run may take several minutes while the embedding model loads."
    )
    with st.spinner(spinner_message):
        try:
            raw = _api_post("/api/v1/videos/ingest", {"urls": urls})
            st.session_state.ingest_result = parse_ingest_response(raw)
            st.session_state.ingest_error = None
        except Exception as exc:
            st.session_state.ingest_error = format_http_error(exc)
            st.session_state.ingest_result = None
        finally:
            st.session_state.ingest_in_progress = False
            st.session_state.ingest_pending_urls = None
    st.rerun()

if st.session_state.ingest_error:
    st.error(st.session_state.ingest_error)

if st.session_state.ingest_result:
    result = st.session_state.ingest_result
    st.success(
        f"Ingest complete — {result['succeeded']} succeeded, "
        f"{result['failed']} failed (total {result['total']})."
    )
    for item in result["results"]:
        if item.get("success"):
            st.markdown(
                f"✅ **{item.get('title') or item.get('url', 'Unknown')}** "
                f"({item.get('chunk_count', 0)} chunks)"
            )
        else:
            error_detail = item.get("error") or "Unknown error"
            st.markdown(
                f"❌ `{item.get('url', 'unknown url')}` — {error_detail}"
            )

st.divider()
st.header("Search your memories")
query = st.text_input(
    "Search by keyword or natural language",
    placeholder="healthy meal prep ideas",
)
limit = st.slider("Max results", min_value=1, max_value=20, value=5)

if st.button("Search"):
    if not query.strip():
        st.warning("Enter a search query.")
    else:
        with st.spinner("Searching..."):
            try:
                data = _api_get("/api/v1/search", {"q": query.strip(), "limit": limit})
            except httpx.TimeoutException:
                st.error(
                    "Search timed out. The embedding model may still be loading — "
                    "wait for an ingest to finish, then try again."
                )
            except httpx.HTTPError as exc:
                st.error(f"Search failed: {exc}")
            else:
                results = data.get("results", [])
                if not results:
                    st.info("No matches found.")
                for hit in results:
                    with st.container(border=True):
                        cols = st.columns([1, 3])
                        with cols[0]:
                            if hit.get("thumbnail"):
                                st.image(hit["thumbnail"], use_container_width=True)
                        with cols[1]:
                            st.subheader(hit.get("title") or "Untitled")
                            st.write(hit.get("channel") or "Unknown channel")
                            if hit.get("one_line_memory"):
                                st.markdown(f"**Memory:** {hit['one_line_memory']}")
                            st.markdown(f"**Why this matched:** {hit.get('why_matched')}")
                            st.caption(f"Relevance: {hit.get('relevance_score')}")

                            original_url = hit.get("original_url") or hit.get("url") or "#"
                            timestamp_url = hit.get("timestamp_url") or build_timestamp_url(
                                original_url,
                                hit.get("start_time"),
                            )

                            link_cols = st.columns(2)
                            with link_cols[0]:
                                st.link_button("Open original", original_url)
                            with link_cols[1]:
                                if hit.get("start_time") is not None:
                                    st.link_button(
                                        f"Open at matched timestamp ({_format_timestamp(hit.get('start_time'))})",
                                        timestamp_url,
                                    )

                            why_saved = hit.get("why_saved") or []
                            action_items = hit.get("action_items") or []
                            if why_saved or action_items or hit.get("matched_text"):
                                with st.expander("More details"):
                                    if why_saved:
                                        st.markdown("**Why you probably saved this**")
                                        for reason in why_saved:
                                            st.markdown(f"- {reason}")
                                    if action_items:
                                        st.markdown("**Action items**")
                                        for item in action_items:
                                            st.markdown(f"- {item}")
                                    if hit.get("matched_text"):
                                        st.markdown("**Matched transcript**")
                                        st.write(hit["matched_text"])

st.divider()
st.header("Ask your memories")
chat_question = st.text_input(
    "Question",
    placeholder="How do I install the GPU?",
    key="chat_question",
)

if st.button("Ask", key="ask_memories"):
    if not chat_question.strip():
        st.warning("Enter a question.")
    else:
        with st.spinner("Thinking from your saved memories..."):
            try:
                chat_data = _api_post(
                    "/api/v1/chat",
                    {"question": chat_question.strip(), "top_k": 6},
                )
            except httpx.TimeoutException:
                st.error("Chat request timed out. Try again in a moment.")
            except httpx.HTTPError as exc:
                st.error(f"Chat request failed: {exc}")
            else:
                st.markdown("**Based on your saved memories**")
                st.markdown(chat_data.get("answer", ""))
                if not chat_data.get("grounded", False):
                    st.caption("Answer confidence is low — review the sources below.")

                for source in chat_data.get("sources", []):
                    with st.container(border=True):
                        st.subheader(source.get("title") or "Untitled")
                        st.write(source.get("matched_text") or "")
                        st.caption(f"Relevance: {source.get('relevance_score')}")
                        original_url = source.get("url") or "#"
                        timestamp_url = source.get("timestamp_url") or build_timestamp_url(
                            original_url,
                            source.get("start_time"),
                        )
                        link_cols = st.columns(2)
                        with link_cols[0]:
                            st.link_button("Open original", original_url)
                        with link_cols[1]:
                            if source.get("start_time") is not None:
                                st.link_button(
                                    f"Open at timestamp ({_format_timestamp(source.get('start_time'))})",
                                    timestamp_url,
                                )
