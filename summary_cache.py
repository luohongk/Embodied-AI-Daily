"""AI summary cache ("database").

Each paper is summarized only once. The result is persisted as
``summaries/<arxiv_id>.md`` and committed to git, so subsequent runs read
the cached markdown instead of re-calling the (paid) DeepSeek API.

The cache key is the version-stripped arXiv id (e.g. ``2606.07515``) so that
v1/v2/... of the same paper share one cache entry.
"""

import os
import logging

CACHE_DIR = "summaries"


def get_cached_summary(arxiv_id: str) -> str:
    """Return the cached markdown summary body if it exists, else ``""``.

    The stored file has a small header (title + links) followed by ``---`` and
    then the AI-generated note body. We strip the header so the caller gets the
    same markdown that ``summarize_fulltext_with_ai`` produced.
    """
    if not arxiv_id:
        return ""
    path = os.path.join(CACHE_DIR, f"{arxiv_id}.md")
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logging.warning(f"Failed to read cache {path}: {e}")
        return ""

    # Strip the header we wrote in save_summary (everything up to first '---').
    marker = "\n---\n\n"
    idx = content.find(marker)
    if idx != -1:
        return content[idx + len(marker):]
    return content


def save_summary(arxiv_id: str, title: str, link: str, summary_md: str) -> None:
    """Persist a summary as ``summaries/<arxiv_id>.md`` with a small header."""
    if not arxiv_id or not summary_md:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{arxiv_id}.md")
    header = (
        f"# {title}\n\n"
        f"- arXiv: {link}\n"
        f"- arXiv ID: {arxiv_id}\n\n"
        f"---\n\n"
    )
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + summary_md)
        logging.info(f"  [缓存写入] {path}")
    except Exception as e:
        logging.warning(f"Failed to write cache {path}: {e}")
