import os
import time
import pytz
import shutil
import datetime
from typing import List, Dict
import urllib, urllib.request
from urllib.error import URLError, HTTPError
import logging
import socket

import feedparser
from easydict import EasyDict


def remove_duplicated_spaces(text: str) -> str:
    return " ".join(text.split())

def escape_nunjucks(text: str) -> str:
    """Escape sequences that Nunjucks would try to interpret as template tags.
    {{ }} are variable tags, {% %} are block tags, {# #} are comment tags.
    Replace the opening brace-pairs so Nunjucks never starts parsing them."""
    text = text.replace("{{{", "{ { {")
    text = text.replace("{{", "{ {")
    text = text.replace("{%", "{ %")
    text = text.replace("{#", "{ #")
    return text

def request_paper_with_arXiv_api(keyword: str, max_results: int, link: str = "OR", retries: int = 3, delay: int = 10) -> List[Dict[str, str]]:
    assert link in ["OR", "AND"], "link should be 'OR' or 'AND'"
    keyword = f"\"{keyword}\""
    url = "http://export.arxiv.org/api/query?search_query=ti:{0}+{2}+abs:{0}&max_results={1}&sortBy=lastUpdatedDate".format(
        keyword, max_results, link
    )
    url = urllib.parse.quote(url, safe="%/:=&?~#+!$,;'@()*[]")

    headers = {'User-Agent': 'Mozilla/5.0 (compatible; ArxivFetcher/1.0)'}
    req = urllib.request.Request(url, headers=headers)

    MAX_RETRIES = 10
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req, timeout=20).read().decode('utf-8')
            break  # 成功则跳出循环
        except (ConnectionResetError, URLError, HTTPError, socket.timeout) as e:
            logging.warning(f"Attempt {attempt+1}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))  # 指数退避
            else:
                raise  # 重试结束后仍失败，抛出异常
    
    feed = feedparser.parse(response)
    papers = []
    for entry in feed.entries:
        entry = EasyDict(entry)
        paper = EasyDict()

        paper.Title = remove_duplicated_spaces(entry.title.replace("\n", " "))
        paper.Abstract = remove_duplicated_spaces(entry.summary.replace("\n", " "))
        paper.Authors = [remove_duplicated_spaces(_["name"].replace("\n", " ")) for _ in entry.authors]
        paper.Link = remove_duplicated_spaces(entry.link.replace("\n", " "))
        paper.Tags = [remove_duplicated_spaces(_["term"].replace("\n", " ")) for _ in entry.tags]
        paper.Comment = remove_duplicated_spaces(entry.get("arxiv_comment", "").replace("\n", " "))
        paper.Date = entry.updated

        papers.append(paper)

    return papers

def filter_tags(papers: List[Dict[str, str]], target_fileds: List[str]=["cs", "stat"]) -> List[Dict[str, str]]:
    # filtering tags: only keep the papers in target_fileds
    results = []
    for paper in papers:
        tags = paper.Tags
        for tag in tags:
            if tag.split(".")[0] in target_fileds:
                results.append(paper)
                break
    return results

def get_daily_papers_by_keyword_with_retries(keyword: str, column_names: List[str], max_result: int, link: str = "OR", retries: int = 6) -> List[Dict[str, str]]:
    for _ in range(retries):
        papers = get_daily_papers_by_keyword(keyword, column_names, max_result, link)
        if len(papers) > 0: return papers
        else:
            print("Unexpected empty list, retrying...")
            time.sleep(60 * 30) # wait for 30 minutes
    # failed
    return None

def get_daily_papers_by_keyword(keyword: str, column_names: List[str], max_result: int, link: str = "OR") -> List[Dict[str, str]]:
    # get papers
    papers = request_paper_with_arXiv_api(keyword, max_result, link) # NOTE default columns: Title, Authors, Abstract, Link, Tags, Comment, Date
    # NOTE filtering tags: only keep the papers in cs field
    # TODO filtering more
    papers = filter_tags(papers)
    # select columns for display
    papers = [{column_name: paper[column_name] for column_name in column_names} for paper in papers]
    return papers

def generate_table(papers: List[Dict[str, str]], ignore_keys: List[str] = []) -> str:
    formatted_papers = []
    keys = papers[0].keys()
    for paper in papers:
        # process fixed columns
        formatted_paper = EasyDict()
        ## Title and Link
        formatted_paper.Title = "**" + "[{0}]({1})".format(paper["Title"], paper["Link"]) + "**"
        ## Process Date (format: 2021-08-01T00:00:00Z -> 2021-08-01)
        formatted_paper.Date = paper["Date"].split("T")[0]
        
        # process other columns
        for key in keys:
            if key in ["Title", "Link", "Date"] or key in ignore_keys:
                continue
            elif key == "Abstract":
                # add show/hide button for abstract
                formatted_paper[key] = "<details><summary>Show</summary><p>{0}</p></details>".format(escape_nunjucks(paper[key]))
            elif key == "Authors":
                # NOTE only use the first author
                formatted_paper[key] = paper[key][0] + " et al."
            elif key == "Tags":
                tags = ", ".join(paper[key])
                if len(tags) > 10:
                    formatted_paper[key] = "<details><summary>{0}...</summary><p>{1}</p></details>".format(tags[:5], tags)
                else:
                    formatted_paper[key] = tags
            elif key == "Comment":
                if paper[key] == "":
                    formatted_paper[key] = ""
                elif len(paper[key]) > 20:
                    formatted_paper[key] = "<details><summary>{0}...</summary><p>{1}</p></details>".format(paper[key][:5], escape_nunjucks(paper[key]))
                else:
                    formatted_paper[key] = escape_nunjucks(paper[key])
        formatted_papers.append(formatted_paper)

    # generate header
    columns = formatted_papers[0].keys()
    # highlight headers
    columns = ["**" + column + "**" for column in columns]
    header = "| " + " | ".join(columns) + " |"
    header = header + "\n" + "| " + " | ".join(["---"] * len(formatted_papers[0].keys())) + " |"
    # generate the body
    body = ""
    for paper in formatted_papers:
        body += "\n| " + " | ".join(paper.values()) + " |"
    return header + body

def back_up_files():
    # back up README.md and ISSUE_TEMPLATE.md
    shutil.move("README.md", "README.md.bk")
    shutil.move(".github/ISSUE_TEMPLATE.md", ".github/ISSUE_TEMPLATE.md.bk")

def restore_files():
    # restore README.md and ISSUE_TEMPLATE.md
    shutil.move("README.md.bk", "README.md")
    shutil.move(".github/ISSUE_TEMPLATE.md.bk", ".github/ISSUE_TEMPLATE.md")

def remove_backups():
    # remove README.md and ISSUE_TEMPLATE.md
    os.remove("README.md.bk")
    os.remove(".github/ISSUE_TEMPLATE.md.bk")

def render_markdown(md_text: str) -> str:
    """Render markdown text to HTML for embedding in the page.

    Math expressions are protected BEFORE markdown conversion and restored
    afterwards, so markdown never mangles LaTeX (e.g. ``_``, ``*``, ``^``,
    ``\\(`` are inside formulas would otherwise be eaten as emphasis markers).
    MathJax then renders the restored, intact LaTeX.

    Supported delimiters: ``$$...$$``, ``\\[...\\]`` (display) and
    ``$...$``, ``\\(...\\)`` (inline).

    Uses the `markdown` library when available; falls back to a minimal
    escaped <pre> block so the build never fails if the dependency is missing.
    """
    if not md_text:
        return ""

    import re

    # 1. Extract math spans into placeholders that markdown will not touch.
    #    Order matters: match display delimiters before inline ones.
    math_store = []

    def _stash(match):
        math_store.append(match.group(0))
        # Pure-alphanumeric token: markdown leaves it untouched, and it
        # cannot be confused with emphasis/underscore syntax.
        return f"MATHJAXPLACEHOLDER{len(math_store) - 1}ENDPLACEHOLDER"

    patterns = [
        r"\$\$(?:.|\n)+?\$\$",   # $$ ... $$  (display)
        r"\\\[(?:.|\n)+?\\\]",    # \[ ... \]  (display)
        r"\$(?:[^$\n]|\n)+?\$",   # $ ... $    (inline)
        r"\\\((?:.|\n)+?\\\)",    # \( ... \)  (inline)
    ]
    protected = md_text
    for pat in patterns:
        protected = re.sub(pat, _stash, protected)

    # 2. Run markdown on the math-free text.
    try:
        import markdown as _markdown
        html = _markdown.markdown(
            protected,
            extensions=["extra", "sane_lists", "nl2br"],
        )
    except Exception as e:
        logging.warning(f"markdown render failed, falling back to <pre>: {e}")
        html = f"<pre style='white-space:pre-wrap'>{escape_nunjucks(protected)}</pre>"

    # 2b. Escape Nunjucks template markers in the prose ONLY. Math spans are
    #     still placeholders here, so LaTeX braces like {{ never get mangled.
    html = escape_nunjucks(html)

    # 3. Restore the original math spans verbatim for MathJax.
    for i, expr in enumerate(math_store):
        html = html.replace(f"MATHJAXPLACEHOLDER{i}ENDPLACEHOLDER", expr)

    return html


# ---------------------------------------------------------------------------
# Shared HTML building blocks for the split site (index + per-topic pages).
# ---------------------------------------------------------------------------

TOPIC_COLORS = [
    "#6366f1", "#8b5cf6", "#a855f7", "#d946ef", "#ec4899",
    "#f43f5e", "#ef4444", "#f97316", "#f59e0b", "#84cc16",
    "#22c55e", "#10b981", "#14b8a6", "#06b6d4", "#0ea5e9",
    "#3b82f6", "#6366f1", "#8b5cf6", "#a855f7", "#d946ef",
]


def _slug(keyword: str) -> str:
    """Stable file/anchor name for a keyword, e.g. 'Visual SLAM' -> 'Visual-SLAM'."""
    return keyword.replace(" ", "-")


# All CSS lives in a plain (non-f) string, so literal braces need no escaping.
_CSS = """    <style>
        :root {
            --bg: #f8fafc;
            --surface: #ffffff;
            --text: #1e293b;
            --text-secondary: #64748b;
            --border: #e2e8f0;
            --accent: #6366f1;
            --sidebar-width: 280px;
            --radius: 12px;
            --shadow: 0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
            --shadow-md: 0 4px 12px rgba(0,0,0,.08);
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --bg: #0f172a;
                --surface: #1e293b;
                --text: #e2e8f0;
                --text-secondary: #94a3b8;
                --border: #334155;
                --shadow: 0 1px 3px rgba(0,0,0,.3);
                --shadow-md: 0 4px 12px rgba(0,0,0,.4);
            }
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        html { scroll-behavior:smooth; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            display: flex;
            min-height: 100vh;
            line-height: 1.6;
        }

        /* Sidebar */
        .sidebar {
            position: fixed;
            top: 0; left: 0;
            width: var(--sidebar-width);
            height: 100vh;
            background: var(--surface);
            border-right: 1px solid var(--border);
            overflow-y: auto;
            padding: 24px 20px;
            z-index: 100;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .sidebar-header {
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 8px;
        }
        .sidebar-header h1 {
            font-size: 1.15rem;
            font-weight: 700;
            background: linear-gradient(135deg, #6366f1, #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 4px;
        }
        .sidebar-header h1 a { text-decoration: none; }
        .sidebar-header .update {
            font-size: .75rem;
            color: var(--text-secondary);
        }
        .nav-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 12px;
            border-radius: 8px;
            text-decoration: none;
            color: var(--text-secondary);
            font-size: .85rem;
            transition: all .15s;
        }
        .nav-item:hover {
            background: var(--bg);
            color: var(--text);
        }
        .nav-item.active {
            background: var(--bg);
            color: var(--text);
            font-weight: 600;
        }
        .nav-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        .nav-label {
            flex: 1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .nav-count {
            font-size: .72rem;
            background: var(--bg);
            padding: 2px 7px;
            border-radius: 10px;
            font-weight: 600;
        }

        /* Main content */
        .main {
            margin-left: var(--sidebar-width);
            flex: 1;
            padding: 40px 48px;
            max-width: calc(100% - var(--sidebar-width));
        }
        .hero {
            text-align: center;
            padding: 40px 0 48px;
        }
        .hero h2 {
            font-size: 2rem;
            font-weight: 800;
            margin-bottom: 8px;
        }
        .hero .subtitle {
            color: var(--text-secondary);
            font-size: 1.05rem;
            margin-bottom: 16px;
        }
        .author-line {
            margin-top: 14px;
            font-size: .88rem;
            color: var(--text-secondary);
        }
        .author-line a {
            color: var(--accent);
            text-decoration: none;
            font-weight: 500;
        }
        .author-line a:hover {
            text-decoration: underline;
        }
        .author-sep {
            color: var(--border);
            margin: 0 8px;
        }
        .badges {
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 8px;
        }
        .badges img {
            height: 20px;
        }

        /* Topic directory grid (index page) */
        .topic-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 40px;
        }
        .topic-card {
            display: flex;
            flex-direction: column;
            gap: 6px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 18px 20px;
            text-decoration: none;
            color: var(--text);
            box-shadow: var(--shadow);
            transition: box-shadow .2s, transform .15s;
        }
        .topic-card:hover {
            box-shadow: var(--shadow-md);
            transform: translateY(-2px);
        }
        .topic-card-name {
            font-weight: 700;
            font-size: 1rem;
        }
        .topic-card-count {
            font-size: .8rem;
            color: var(--text-secondary);
        }
        .topic-card-go {
            margin-top: 4px;
            font-size: .82rem;
            font-weight: 600;
            color: var(--accent);
        }

        /* Topic page header */
        .topic-section {
            margin-bottom: 48px;
        }
        .topic-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 2px solid var(--border);
            flex-wrap: wrap;
        }
        .topic-badge {
            display: inline-block;
            color: #fff;
            padding: 5px 14px;
            border-radius: 20px;
            font-size: .85rem;
            font-weight: 600;
            letter-spacing: .01em;
        }
        .topic-count {
            font-size: .82rem;
            color: var(--text-secondary);
            font-weight: 500;
        }
        .back-link {
            display: inline-block;
            margin-bottom: 18px;
            font-size: .85rem;
            color: var(--accent);
            text-decoration: none;
            font-weight: 500;
        }
        .back-link:hover { text-decoration: underline; }

        /* Paper cards */
        .paper-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .paper-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 16px 20px;
            box-shadow: var(--shadow);
            transition: box-shadow .2s, transform .15s;
        }
        .paper-card:hover {
            box-shadow: var(--shadow-md);
            transform: translateY(-1px);
        }
        .paper-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 16px;
            flex-wrap: wrap;
        }
        .paper-title {
            font-weight: 600;
            font-size: .95rem;
            color: var(--text);
            text-decoration: none;
            flex: 1;
            min-width: 0;
        }
        .paper-title:hover {
            color: var(--accent);
            text-decoration: underline;
        }
        .paper-date {
            font-size: .78rem;
            color: var(--text-secondary);
            white-space: nowrap;
            font-variant-numeric: tabular-nums;
        }
        .paper-comment {
            display: inline-block;
            margin-top: 6px;
            font-size: .78rem;
            color: var(--text-secondary);
            background: var(--bg);
            padding: 2px 10px;
            border-radius: 6px;
        }
        .paper-abstract {
            margin-top: 10px;
            font-size: .85rem;
            color: var(--text-secondary);
        }
        .paper-abstract summary {
            cursor: pointer;
            font-weight: 500;
            color: var(--accent);
            font-size: .82rem;
            user-select: none;
        }
        .paper-abstract summary:hover {
            text-decoration: underline;
        }
        .paper-abstract p {
            margin-top: 8px;
            line-height: 1.7;
            padding: 12px 16px;
            background: var(--bg);
            border-radius: 8px;
            border-left: 3px solid var(--accent);
        }

        /* AI Summary */
        .ai-summary {
            margin-top: 10px;
            padding: 10px 14px;
            background: linear-gradient(135deg, rgba(99,102,241,0.07), rgba(168,85,247,0.07));
            border-radius: 8px;
            border-left: 3px solid var(--accent);
        }
        .ai-label {
            font-size: .8rem;
            font-weight: 600;
            color: var(--accent);
            cursor: pointer;
            user-select: none;
            letter-spacing: .02em;
        }
        .ai-label:hover {
            text-decoration: underline;
        }
        .ai-content {
            font-size: .85rem;
            color: var(--text);
            line-height: 1.75;
            margin-top: 10px;
            max-height: 480px;
            overflow-y: auto;
            padding-right: 6px;
        }
        /* Rendered markdown inside AI summary */
        .markdown-body h2 {
            font-size: 1rem;
            margin: 14px 0 6px;
            padding-bottom: 4px;
            border-bottom: 1px solid var(--border);
            color: var(--text);
        }
        .markdown-body h3 {
            font-size: .9rem;
            margin: 10px 0 4px;
            color: var(--accent);
        }
        .markdown-body p { margin: 6px 0; }
        .markdown-body ul, .markdown-body ol { margin: 6px 0 6px 20px; }
        .markdown-body li { margin: 3px 0; }
        .markdown-body strong { color: var(--text); }
        .markdown-body code {
            background: var(--bg);
            padding: 1px 5px;
            border-radius: 4px;
            font-size: .82em;
        }
        .markdown-body pre {
            background: var(--bg);
            padding: 10px 12px;
            border-radius: 8px;
            overflow-x: auto;
            font-size: .8em;
        }
        .markdown-body table {
            border-collapse: collapse;
            margin: 8px 0;
            font-size: .82em;
        }
        .markdown-body th, .markdown-body td {
            border: 1px solid var(--border);
            padding: 4px 8px;
        }

        /* Footer */
        .footer {
            text-align: center;
            padding: 40px 0 20px;
            color: var(--text-secondary);
            font-size: .82rem;
            border-top: 1px solid var(--border);
            margin-top: 20px;
        }

        /* Sponsor banner */
        .sponsor {
            margin: 0 auto 8px;
            max-width: 640px;
            background: linear-gradient(135deg, rgba(16,185,129,0.10), rgba(99,102,241,0.10));
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 16px 20px;
            text-align: center;
        }
        .sponsor-title {
            font-size: .95rem;
            font-weight: 700;
            color: var(--text);
            margin-bottom: 6px;
        }
        .sponsor-desc {
            font-size: .82rem;
            color: var(--text-secondary);
            line-height: 1.6;
            margin-bottom: 10px;
        }
        .sponsor details { margin-top: 4px; }
        .sponsor summary {
            cursor: pointer;
            display: inline-block;
            background: #07c160;
            color: #fff;
            font-size: .82rem;
            font-weight: 600;
            padding: 7px 18px;
            border-radius: 20px;
            user-select: none;
            list-style: none;
        }
        .sponsor summary::-webkit-details-marker { display: none; }
        .sponsor summary:hover { opacity: .9; }
        .sponsor-qr {
            margin-top: 14px;
        }
        .sponsor-qr img {
            width: 220px;
            max-width: 80%;
            border-radius: 10px;
            box-shadow: var(--shadow-md);
        }

        /* Mobile top bar */
        .mobile-bar {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0;
            height: 52px;
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            z-index: 200;
            padding: 0 16px;
            align-items: center;
            justify-content: space-between;
        }
        .mobile-bar .mobile-title {
            font-weight: 700;
            font-size: .95rem;
            background: linear-gradient(135deg, #6366f1, #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .menu-toggle {
            background: none;
            border: none;
            font-size: 1.4rem;
            cursor: pointer;
            color: var(--text);
            padding: 4px 8px;
            border-radius: 6px;
            line-height: 1;
            transition: background .15s;
        }
        .menu-toggle:hover {
            background: var(--bg);
        }

        /* Mobile nav overlay */
        .mobile-nav-overlay {
            display: none;
            position: fixed;
            top: 52px; left: 0; right: 0; bottom: 0;
            background: var(--surface);
            z-index: 199;
            overflow-y: auto;
            padding: 8px 16px 24px;
            flex-direction: column;
        }
        .mobile-nav-overlay.open {
            display: flex;
        }
        .mobile-nav-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0 12px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 4px;
            font-weight: 600;
            font-size: .85rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: .04em;
        }
        .mobile-nav-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 13px 8px;
            border-radius: 8px;
            text-decoration: none;
            color: var(--text-secondary);
            font-size: .88rem;
            border-bottom: 1px solid var(--border);
            transition: background .1s;
        }
        .mobile-nav-item:active {
            background: var(--bg);
        }

        /* Responsive */
        @media (max-width: 900px) {
            .sidebar {
                display: none;
            }
            .mobile-bar {
                display: flex;
            }
            .main {
                margin-left: 0;
                max-width: 100%;
                padding: 68px 16px 20px;
            }
            .hero h2 {
                font-size: 1.4rem;
            }
            .hero {
                padding: 20px 0 32px;
            }
            .paper-header {
                flex-direction: column;
                gap: 4px;
            }
        }
    </style>"""


# MathJax config — raw string so backslashes in the delimiters stay literal.
_MATHJAX = r"""    <!-- MathJax for rendering LaTeX math in AI summaries -->
    <script>
        window.MathJax = {
            tex: {
                inlineMath: [['$', '$'], ['\\(', '\\)']],
                displayMath: [['$$', '$$'], ['\\[', '\\]']],
                processEscapes: true
            },
            options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'] }
        };
    </script>
    <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>"""


# Page scripts (menu toggle + lazy AI-summary renderer).
# marked.js renders markdown in the browser; MathJax handles math.
# Using a raw string so backslashes in regex literals stay literal.
_MENU_SCRIPT = r"""    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
        /* ── Mobile menu ── */
        function toggleMenu() {
            var overlay = document.getElementById('mobileNav');
            var btn = document.getElementById('menuToggle');
            var open = overlay.classList.toggle('open');
            btn.textContent = open ? '✕' : '☰';
            document.body.style.overflow = open ? 'hidden' : '';
        }
        function closeMenu() {
            var overlay = document.getElementById('mobileNav');
            var btn = document.getElementById('menuToggle');
            overlay.classList.remove('open');
            btn.textContent = '☰';
            document.body.style.overflow = '';
        }

        /* ── Lazy AI-summary renderer ── */
        // Render markdown + re-typeset MathJax only when a summary is opened.
        // Math spans ($...$, $$...$$, \(...\), \[...\]) are stashed as
        // placeholders before marked runs so Markdown never mangles LaTeX.
        function renderAISummary(details) {
            if (!details.dataset.lazy) return;   // already rendered
            var rawMd = details.dataset.md || '';

            // Decode HTML entities we encoded in Python.
            // Order matters: &amp; must be last (it re-encodes other entities).
            rawMd = rawMd
                .replace(/&#10;/g, '\n')
                .replace(/&quot;/g, '"')
                .replace(/&lt;/g, '<')
                .replace(/&gt;/g, '>')
                .replace(/&amp;/g, '&');

            // 1. Stash math spans.
            var store = [];
            function stash(m) { store.push(m); return '\x02MATH' + (store.length - 1) + 'END\x03'; }
            var protected_ = rawMd
                .replace(/\$\$[\s\S]+?\$\$/g, stash)
                .replace(/\\\[[\s\S]+?\\\]/g, stash)
                .replace(/\$[^$\n]+?\$/g, stash)
                .replace(/\\\([\s\S]+?\\\)/g, stash);

            // 2. Render markdown.
            var html = (typeof marked !== 'undefined')
                ? marked.parse(protected_)
                : '<pre>' + protected_.replace(/</g, '&lt;') + '</pre>';

            // 3. Restore math spans verbatim.
            store.forEach(function(expr, i) {
                html = html.split('\x02MATH' + i + 'END\x03').join(expr);
            });

            // 4. Inject into DOM.
            var container = details.querySelector('.ai-content');
            if (container) container.innerHTML = html;

            // 5. Ask MathJax to typeset just this element.
            if (window.MathJax && MathJax.typesetPromise) {
                MathJax.typesetPromise([container]).catch(function(e) {
                    console.warn('MathJax typeset error:', e);
                });
            }

            // Mark done so we never re-render.
            delete details.dataset.lazy;
            delete details.dataset.md;
        }

        // Wire up all existing .ai-summary elements.
        document.addEventListener('DOMContentLoaded', function () {
            document.querySelectorAll('details.ai-summary[data-lazy]').forEach(function(det) {
                det.addEventListener('toggle', function () {
                    if (det.open) renderAISummary(det);
                }, { once: true });
            });
        });
    </script>"""


def _build_head(title: str) -> str:
    """Return <!DOCTYPE> + <head>...</head> with shared CSS and MathJax."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '    <meta charset="UTF-8">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"    <title>{title}</title>\n"
        f"{_CSS}\n"
        f"{_MATHJAX}\n"
        "</head>"
    )


def _build_nav(all_keywords, counts, current_keyword, link_prefix):
    """Build desktop sidebar items + mobile overlay items (cross-page links)."""
    nav_items = ""
    mobile_nav_items = ""
    for i, kw in enumerate(all_keywords):
        slug = _slug(kw)
        color = TOPIC_COLORS[i % len(TOPIC_COLORS)]
        count = counts.get(kw, 0)
        href = f"{link_prefix}{slug}.html"
        active = " active" if kw == current_keyword else ""
        nav_items += f"""            <a href="{href}" class="nav-item{active}">
                <span class="nav-dot" style="background:{color}"></span>
                <span class="nav-label">{kw}</span>
                <span class="nav-count">{count}</span>
            </a>\n"""
        mobile_nav_items += f"""                <a href="{href}" class="mobile-nav-item" onclick="closeMenu()">
                    <span class="nav-dot" style="background:{color}"></span>
                    <span class="nav-label">{kw}</span>
                    <span class="nav-count">{count}</span>
                </a>\n"""
    return nav_items, mobile_nav_items


def _mobile_bar() -> str:
    return """    <!-- Mobile top bar -->
    <div class="mobile-bar">
        <span class="mobile-title">🚀 Embodied AI Daily</span>
        <button class="menu-toggle" id="menuToggle" onclick="toggleMenu()" aria-label="Toggle menu">☰</button>
    </div>"""


def _mobile_nav(mobile_nav_items: str) -> str:
    return f"""    <!-- Mobile nav overlay -->
    <div class="mobile-nav-overlay" id="mobileNav">
        <div class="mobile-nav-header">
            <span>Topics</span>
            <button class="menu-toggle" onclick="toggleMenu()" aria-label="Close menu">✕</button>
        </div>
{mobile_nav_items}    </div>"""


def _sidebar(nav_items: str, current_date: str, home_href: str) -> str:
    return f"""    <!-- Desktop sidebar -->
    <nav class="sidebar">
        <div class="sidebar-header">
            <h1><a href="{home_href}" style="background:linear-gradient(135deg,#6366f1,#ec4899);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">🚀 Embodied AI Daily</a></h1>
            <div class="update">by <a href="https://luohongkun.top/scholar/" target="_blank" style="color:var(--accent);text-decoration:none;font-weight:500;">Hongkun Luo</a> (罗宏昆)</div>
            <div class="update" style="margin-top:2px">Last update: {current_date}</div>
        </div>
{nav_items}    </nav>"""


def _sponsor_block(asset_prefix: str) -> str:
    return f"""            <div class="sponsor">
                <div class="sponsor-title">☕ 支持本项目 · Support this project</div>
                <div class="sponsor-desc">
                    每篇论文的 AI 深度总结都会调用大量 DeepSeek API（需付费）。<br>
                    如果这个项目对你有帮助，欢迎请作者喝杯咖啡，支持服务器与 API 开销 🙏
                </div>
                <details>
                    <summary>💚 微信赞助 / Sponsor via WeChat Pay</summary>
                    <div class="sponsor-qr">
                        <img src="{asset_prefix}images/wechat_pay.jpg" alt="WeChat Pay QR code">
                    </div>
                </details>
            </div>"""


def _footer(current_date: str) -> str:
    return f"""        <footer class="footer">
            <p>👤 <strong>Hongkun Luo (罗宏昆)</strong> · <a href="https://luohongkun.top/scholar/" target="_blank" style="color:var(--accent)">Academic Page</a> · <a href="https://github.com/luohongk" target="_blank" style="color:var(--accent)">GitHub</a></p>
            <p style="margin-top:8px">🤖 Generated automatically from <a href="https://arxiv.org" style="color:var(--accent)">arXiv</a> · <a href="https://github.com/luohongk/Embodied-AI-Daily" style="color:var(--accent)">GitHub Repo</a></p>
            <p style="margin-top:4px">Last update: {current_date} (Beijing Time)</p>
        </footer>"""


def _render_paper_card(paper: Dict[str, str]) -> str:
    """Render a single paper card (shared by topic pages)."""
    title = paper.get("Title", "")
    link = paper.get("Link", "")
    abstract = paper.get("Abstract", "")
    date_str = paper.get("Date", "").split("T")[0] if paper.get("Date") else ""
    comment = paper.get("Comment", "")
    ai_summary = paper.get("AI_Summary", "")

    abstract_html = ""
    if abstract:
        abstract_html = f"""                    <details class="paper-abstract">
                        <summary>Show abstract</summary>
                        <p>{escape_nunjucks(abstract)}</p>
                    </details>"""

    comment_html = ""
    if comment:
        comment_html = f'                    <span class="paper-comment">📝 {escape_nunjucks(comment)}</span>'

    ai_summary_html = ""
    if ai_summary:
        # Store raw markdown in a data attribute; JS renders on first expand.
        # Encode characters that would break the HTML attribute value.
        safe_md = (ai_summary
                   .replace("&", "&amp;")    # must be first
                   .replace("<", "&lt;")
                   .replace(">", "&gt;")
                   .replace('"', "&quot;")
                   .replace("\n", "&#10;"))
        # Protect Nunjucks template markers ({{ etc.) in case of SSG pipeline.
        safe_md = escape_nunjucks(safe_md)
        ai_summary_html = f"""                    <details class="ai-summary" data-lazy="1" data-md="{safe_md}">
                        <summary class="ai-label">🤖 AI 深度总结（DeepSeek 全文阅读）· 点击展开</summary>
                        <div class="ai-content markdown-body"></div>
                    </details>"""

    return f"""                <div class="paper-card">
                    <div class="paper-header">
                        <a href="{link}" target="_blank" class="paper-title">{escape_nunjucks(title)}</a>
                        <span class="paper-date">{date_str}</span>
                    </div>
                    {comment_html}
                    {ai_summary_html}
                    {abstract_html}
                </div>\n"""


def generate_index_html(all_papers: Dict[str, List[Dict[str, str]]], current_date: str) -> str:
    """Generate the lightweight directory/portal page linking to each topic page."""
    all_keywords = [k for k, v in all_papers.items() if v]
    counts = {k: len(v) for k, v in all_papers.items() if v}
    nav_items, mobile_nav_items = _build_nav(all_keywords, counts, None, "topics/")

    grid = ""
    for i, kw in enumerate(all_keywords):
        slug = _slug(kw)
        color = TOPIC_COLORS[i % len(TOPIC_COLORS)]
        grid += f"""            <a href="topics/{slug}.html" class="topic-card" style="border-top:4px solid {color}">
                <span class="topic-card-name">{kw}</span>
                <span class="topic-card-count">{counts[kw]} papers</span>
                <span class="topic-card-go">进入 →</span>
            </a>\n"""

    head = _build_head("Embodied AI Daily — Latest arXiv Papers")
    body = f"""<body>
{_mobile_bar()}

{_mobile_nav(mobile_nav_items)}

{_sidebar(nav_items, current_date, "index.html")}

    <main class="main">
        <section class="hero">
            <h2>📄 Latest arXiv Papers</h2>
            <p class="subtitle">VLN · VLA · SLAM · 3D · Embodied AI — auto-updated daily</p>
            <div class="badges">
                <img src="https://img.shields.io/badge/Update-Daily-brightgreen.svg" alt="Daily Update">
                <img src="https://img.shields.io/badge/Source-arXiv-red.svg" alt="Source: arXiv">
                <img src="https://img.shields.io/badge/Papers-VLN·VLA·SLAM·3D-blue.svg" alt="Topics">
                <img src="https://img.shields.io/github/stars/luohongk/Embodied-AI-Daily?style=social" alt="GitHub Stars">
            </div>
            <p class="author-line">
                👤 <a href="https://luohongkun.top/scholar/" target="_blank">Hongkun Luo (罗宏昆)</a>
                <span class="author-sep">·</span>
                🎓 <a href="https://luohongkun.top/scholar/" target="_blank">Academic Page</a>
                <span class="author-sep">·</span>
                🐙 <a href="https://github.com/luohongk/Embodied-AI-Daily" target="_blank">GitHub</a>
            </p>
{_sponsor_block("")}
        </section>

        <section class="topic-grid">
{grid}        </section>

{_footer(current_date)}
    </main>

{_MENU_SCRIPT}
</body>
</html>"""
    return head + "\n" + body


def generate_topic_html(keyword: str, papers: List[Dict[str, str]],
                        all_keywords: List[str], counts: Dict[str, int],
                        current_date: str) -> str:
    """Generate a single-keyword page with all its papers and AI summaries."""
    nav_items, mobile_nav_items = _build_nav(all_keywords, counts, keyword, "")
    color = TOPIC_COLORS[all_keywords.index(keyword) % len(TOPIC_COLORS)] if keyword in all_keywords else TOPIC_COLORS[0]
    count = len(papers)

    cards = ""
    for paper in papers:
        cards += _render_paper_card(paper)

    head = _build_head(f"{keyword} — Embodied AI Daily")
    body = f"""<body>
{_mobile_bar()}

{_mobile_nav(mobile_nav_items)}

{_sidebar(nav_items, current_date, "../index.html")}

    <main class="main">
        <a href="../index.html" class="back-link">← 返回汇总 / Back to all topics</a>
        <section class="hero" style="padding:20px 0 24px">
{_sponsor_block("../")}
        </section>
        <section class="topic-section">
            <div class="topic-header">
                <span class="topic-badge" style="background:{color}">{keyword}</span>
                <span class="topic-count">{count} papers</span>
            </div>
            <div class="paper-list">
{cards}            </div>
        </section>

{_footer(current_date)}
    </main>

{_MENU_SCRIPT}
</body>
</html>"""
    return head + "\n" + body


def _generate_html_unused(all_papers, current_date):
    """Deprecated single-page generator. Superseded by generate_index_html /
    generate_topic_html. Body kept below for reference but never executed."""
    return ""  # noqa: dead code below is unreachable and intentionally unused
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Embodied AI Daily — Latest arXiv Papers</title>
    <style>
        :root {{
            --bg: #f8fafc;
            --surface: #ffffff;
            --text: #1e293b;
            --text-secondary: #64748b;
            --border: #e2e8f0;
            --accent: #6366f1;
            --sidebar-width: 280px;
            --radius: 12px;
            --shadow: 0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
            --shadow-md: 0 4px 12px rgba(0,0,0,.08);
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg: #0f172a;
                --surface: #1e293b;
                --text: #e2e8f0;
                --text-secondary: #94a3b8;
                --border: #334155;
                --shadow: 0 1px 3px rgba(0,0,0,.3);
                --shadow-md: 0 4px 12px rgba(0,0,0,.4);
            }}
        }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        html {{ scroll-behavior:smooth; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            display: flex;
            min-height: 100vh;
            line-height: 1.6;
        }}

        /* Sidebar */
        .sidebar {{
            position: fixed;
            top: 0; left: 0;
            width: var(--sidebar-width);
            height: 100vh;
            background: var(--surface);
            border-right: 1px solid var(--border);
            overflow-y: auto;
            padding: 24px 20px;
            z-index: 100;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .sidebar-header {{
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 8px;
        }}
        .sidebar-header h1 {{
            font-size: 1.15rem;
            font-weight: 700;
            background: linear-gradient(135deg, #6366f1, #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 4px;
        }}
        .sidebar-header .update {{
            font-size: .75rem;
            color: var(--text-secondary);
        }}
        .nav-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 12px;
            border-radius: 8px;
            text-decoration: none;
            color: var(--text-secondary);
            font-size: .85rem;
            transition: all .15s;
        }}
        .nav-item:hover {{
            background: var(--bg);
            color: var(--text);
        }}
        .nav-dot {{
            width: 8px; height: 8px;
            border-radius: 50%;
            flex-shrink: 0;
        }}
        .nav-label {{
            flex: 1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .nav-count {{
            font-size: .72rem;
            background: var(--bg);
            padding: 2px 7px;
            border-radius: 10px;
            font-weight: 600;
        }}

        /* Main content */
        .main {{
            margin-left: var(--sidebar-width);
            flex: 1;
            padding: 40px 48px;
            max-width: calc(100% - var(--sidebar-width));
        }}
        .hero {{
            text-align: center;
            padding: 40px 0 48px;
        }}
        .hero h2 {{
            font-size: 2rem;
            font-weight: 800;
            margin-bottom: 8px;
        }}
        .hero .subtitle {{
            color: var(--text-secondary);
            font-size: 1.05rem;
            margin-bottom: 16px;
        }}
        .author-line {{
            margin-top: 14px;
            font-size: .88rem;
            color: var(--text-secondary);
        }}
        .author-line a {{
            color: var(--accent);
            text-decoration: none;
            font-weight: 500;
        }}
        .author-line a:hover {{
            text-decoration: underline;
        }}
        .author-sep {{
            color: var(--border);
            margin: 0 8px;
        }}
        .badges {{
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .badges img {{
            height: 20px;
        }}

        /* Topic sections */
        .topic-section {{
            margin-bottom: 48px;
        }}
        .topic-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 2px solid var(--border);
            position: sticky;
            top: 0;
            background: var(--bg);
            z-index: 10;
            padding-top: 8px;
        }}
        .topic-badge {{
            display: inline-block;
            color: #fff;
            padding: 5px 14px;
            border-radius: 20px;
            font-size: .85rem;
            font-weight: 600;
            letter-spacing: .01em;
        }}
        .topic-count {{
            font-size: .82rem;
            color: var(--text-secondary);
            font-weight: 500;
        }}

        /* Paper cards */
        .paper-list {{
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}
        .paper-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 16px 20px;
            box-shadow: var(--shadow);
            transition: box-shadow .2s, transform .15s;
        }}
        .paper-card:hover {{
            box-shadow: var(--shadow-md);
            transform: translateY(-1px);
        }}
        .paper-header {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 16px;
            flex-wrap: wrap;
        }}
        .paper-title {{
            font-weight: 600;
            font-size: .95rem;
            color: var(--text);
            text-decoration: none;
            flex: 1;
            min-width: 0;
        }}
        .paper-title:hover {{
            color: var(--accent);
            text-decoration: underline;
        }}
        .paper-date {{
            font-size: .78rem;
            color: var(--text-secondary);
            white-space: nowrap;
            font-variant-numeric: tabular-nums;
        }}
        .paper-comment {{
            display: inline-block;
            margin-top: 6px;
            font-size: .78rem;
            color: var(--text-secondary);
            background: var(--bg);
            padding: 2px 10px;
            border-radius: 6px;
        }}
        .paper-abstract {{
            margin-top: 10px;
            font-size: .85rem;
            color: var(--text-secondary);
        }}
        .paper-abstract summary {{
            cursor: pointer;
            font-weight: 500;
            color: var(--accent);
            font-size: .82rem;
            user-select: none;
        }}
        .paper-abstract summary:hover {{
            text-decoration: underline;
        }}
        .paper-abstract p {{
            margin-top: 8px;
            line-height: 1.7;
            padding: 12px 16px;
            background: var(--bg);
            border-radius: 8px;
            border-left: 3px solid var(--accent);
        }}

        /* AI Summary */
        .ai-summary {{
            margin-top: 10px;
            padding: 10px 14px;
            background: linear-gradient(135deg, rgba(99,102,241,0.07), rgba(168,85,247,0.07));
            border-radius: 8px;
            border-left: 3px solid var(--accent);
        }}
        .ai-label {{
            font-size: .8rem;
            font-weight: 600;
            color: var(--accent);
            cursor: pointer;
            user-select: none;
            letter-spacing: .02em;
        }}
        .ai-label:hover {{
            text-decoration: underline;
        }}
        .ai-content {{
            font-size: .85rem;
            color: var(--text);
            line-height: 1.75;
            margin-top: 10px;
            max-height: 480px;
            overflow-y: auto;
            padding-right: 6px;
        }}
        /* Rendered markdown inside AI summary */
        .markdown-body h2 {{
            font-size: 1rem;
            margin: 14px 0 6px;
            padding-bottom: 4px;
            border-bottom: 1px solid var(--border);
            color: var(--text);
        }}
        .markdown-body h3 {{
            font-size: .9rem;
            margin: 10px 0 4px;
            color: var(--accent);
        }}
        .markdown-body p {{ margin: 6px 0; }}
        .markdown-body ul, .markdown-body ol {{ margin: 6px 0 6px 20px; }}
        .markdown-body li {{ margin: 3px 0; }}
        .markdown-body strong {{ color: var(--text); }}
        .markdown-body code {{
            background: var(--bg);
            padding: 1px 5px;
            border-radius: 4px;
            font-size: .82em;
        }}
        .markdown-body pre {{
            background: var(--bg);
            padding: 10px 12px;
            border-radius: 8px;
            overflow-x: auto;
            font-size: .8em;
        }}
        .markdown-body table {{
            border-collapse: collapse;
            margin: 8px 0;
            font-size: .82em;
        }}
        .markdown-body th, .markdown-body td {{
            border: 1px solid var(--border);
            padding: 4px 8px;
        }}

        /* Footer */
        .footer {{
            text-align: center;
            padding: 40px 0 20px;
            color: var(--text-secondary);
            font-size: .82rem;
            border-top: 1px solid var(--border);
            margin-top: 20px;
        }}

        /* Sponsor banner */
        .sponsor {{
            margin: 0 auto 8px;
            max-width: 640px;
            background: linear-gradient(135deg, rgba(16,185,129,0.10), rgba(99,102,241,0.10));
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 16px 20px;
            text-align: center;
        }}
        .sponsor-title {{
            font-size: .95rem;
            font-weight: 700;
            color: var(--text);
            margin-bottom: 6px;
        }}
        .sponsor-desc {{
            font-size: .82rem;
            color: var(--text-secondary);
            line-height: 1.6;
            margin-bottom: 10px;
        }}
        .sponsor details {{ margin-top: 4px; }}
        .sponsor summary {{
            cursor: pointer;
            display: inline-block;
            background: #07c160;
            color: #fff;
            font-size: .82rem;
            font-weight: 600;
            padding: 7px 18px;
            border-radius: 20px;
            user-select: none;
            list-style: none;
        }}
        .sponsor summary::-webkit-details-marker {{ display: none; }}
        .sponsor summary:hover {{ opacity: .9; }}
        .sponsor-qr {{
            margin-top: 14px;
        }}
        .sponsor-qr img {{
            width: 220px;
            max-width: 80%;
            border-radius: 10px;
            box-shadow: var(--shadow-md);
        }}

        /* Mobile top bar */
        .mobile-bar {{
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0;
            height: 52px;
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            z-index: 200;
            padding: 0 16px;
            align-items: center;
            justify-content: space-between;
        }}
        .mobile-bar .mobile-title {{
            font-weight: 700;
            font-size: .95rem;
            background: linear-gradient(135deg, #6366f1, #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .menu-toggle {{
            background: none;
            border: none;
            font-size: 1.4rem;
            cursor: pointer;
            color: var(--text);
            padding: 4px 8px;
            border-radius: 6px;
            line-height: 1;
            transition: background .15s;
        }}
        .menu-toggle:hover {{
            background: var(--bg);
        }}

        /* Mobile nav overlay */
        .mobile-nav-overlay {{
            display: none;
            position: fixed;
            top: 52px; left: 0; right: 0; bottom: 0;
            background: var(--surface);
            z-index: 199;
            overflow-y: auto;
            padding: 8px 16px 24px;
            flex-direction: column;
        }}
        .mobile-nav-overlay.open {{
            display: flex;
        }}
        .mobile-nav-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0 12px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 4px;
            font-weight: 600;
            font-size: .85rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: .04em;
        }}
        .mobile-nav-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 13px 8px;
            border-radius: 8px;
            text-decoration: none;
            color: var(--text-secondary);
            font-size: .88rem;
            border-bottom: 1px solid var(--border);
            transition: background .1s;
        }}
        .mobile-nav-item:active {{
            background: var(--bg);
        }}

        /* Responsive */
        @media (max-width: 900px) {{
            .sidebar {{
                display: none;
            }}
            .mobile-bar {{
                display: flex;
            }}
            .main {{
                margin-left: 0;
                max-width: 100%;
                padding: 68px 16px 20px;
            }}
            .hero h2 {{
                font-size: 1.4rem;
            }}
            .hero {{
                padding: 20px 0 32px;
            }}
            .paper-header {{
                flex-direction: column;
                gap: 4px;
            }}
            .topic-header {{
                top: 52px;
            }}
        }}
    </style>
    <!-- MathJax for rendering LaTeX math in AI summaries -->
    <script>
        window.MathJax = {{
            tex: {{
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
                processEscapes: true
            }},
            options: {{ skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'] }}
        }};
    </script>
    <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
</head>
<body>
    <!-- Mobile top bar -->
    <div class="mobile-bar">
        <span class="mobile-title">🚀 Embodied AI Daily</span>
        <button class="menu-toggle" id="menuToggle" onclick="toggleMenu()" aria-label="Toggle menu">☰</button>
    </div>

    <!-- Mobile nav overlay -->
    <div class="mobile-nav-overlay" id="mobileNav">
        <div class="mobile-nav-header">
            <span>Topics</span>
            <button class="menu-toggle" onclick="toggleMenu()" aria-label="Close menu">✕</button>
        </div>
{mobile_nav_items}    </div>

    <!-- Desktop sidebar -->
    <nav class="sidebar">
        <div class="sidebar-header">
            <h1>🚀 Embodied AI Daily</h1>
            <div class="update">by <a href="https://luohongkun.top/scholar/" target="_blank" style="color:var(--accent);text-decoration:none;font-weight:500;">Hongkun Luo</a> (罗宏昆)</div>
            <div class="update" style="margin-top:2px">Last update: {current_date}</div>
        </div>
{nav_items}    </nav>

    <main class="main">
        <section class="hero">
            <h2>📄 Latest arXiv Papers</h2>
            <p class="subtitle">VLN · VLA · SLAM · 3D · Embodied AI — auto-updated daily</p>
            <div class="badges">
                <img src="https://img.shields.io/badge/Update-Daily-brightgreen.svg" alt="Daily Update">
                <img src="https://img.shields.io/badge/Source-arXiv-red.svg" alt="Source: arXiv">
                <img src="https://img.shields.io/badge/Papers-VLN·VLA·SLAM·3D-blue.svg" alt="Topics">
                <img src="https://img.shields.io/github/stars/luohongk/Embodied-AI-Daily?style=social" alt="GitHub Stars">
            </div>
            <p class="author-line">
                👤 <a href="https://luohongkun.top/scholar/" target="_blank">Hongkun Luo (罗宏昆)</a>
                <span class="author-sep">·</span>
                🎓 <a href="https://luohongkun.top/scholar/" target="_blank">Academic Page</a>
                <span class="author-sep">·</span>
                🐙 <a href="https://github.com/luohongk" target="_blank">GitHub</a>
            </p>
            <div class="sponsor">
                <div class="sponsor-title">☕ 支持本项目 · Support this project</div>
                <div class="sponsor-desc">
                    每篇论文的 AI 深度总结都会调用大量 DeepSeek API（需付费）。<br>
                    如果这个项目对你有帮助，欢迎请作者喝杯咖啡，支持服务器与 API 开销 🙏
                </div>
                <details>
                    <summary>💚 微信赞助 / Sponsor via WeChat Pay</summary>
                    <div class="sponsor-qr">
                        <img src="images/wechat_pay.jpg" alt="WeChat Pay QR code">
                    </div>
                </details>
            </div>
        </section>

{content_sections}
        <footer class="footer">
            <p>👤 <strong>Hongkun Luo (罗宏昆)</strong> · <a href="https://luohongkun.top/scholar/" target="_blank" style="color:var(--accent)">Academic Page</a> · <a href="https://github.com/luohongk" target="_blank" style="color:var(--accent)">GitHub</a></p>
            <p style="margin-top:8px">🤖 Generated automatically from <a href="https://arxiv.org" style="color:var(--accent)">arXiv</a> · <a href="https://github.com/luohongk/Embodied-AI-Daily" style="color:var(--accent)">GitHub Repo</a></p>
            <p style="margin-top:4px">Last update: {current_date} (Beijing Time)</p>
        </footer>
    </main>

    <script>
        function toggleMenu() {{
            var overlay = document.getElementById('mobileNav');
            var btn = document.getElementById('menuToggle');
            var open = overlay.classList.toggle('open');
            btn.textContent = open ? '✕' : '☰';
            if (open) {{
                document.body.style.overflow = 'hidden';
            }} else {{
                document.body.style.overflow = '';
            }}
        }}
        function closeMenu() {{
            var overlay = document.getElementById('mobileNav');
            var btn = document.getElementById('menuToggle');
            overlay.classList.remove('open');
            btn.textContent = '☰';
            document.body.style.overflow = '';
        }}
    </script>
</body>
</html>"""

    return html


def get_daily_date():
    # get beijing time in the format of "March 1, 2021"
    beijing_timezone = pytz.timezone('Asia/Shanghai')
    today = datetime.datetime.now(beijing_timezone)
    return today.strftime("%B %d, %Y")


def _call_deepseek_with_retry(client, model: str, messages: list,
                              max_tokens: int, temperature: float,
                              label: str) -> str:
    """Call the DeepSeek chat API with exponential back-off on 429 / transient errors."""
    import time as _time

    MAX_RETRIES = 4
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e).lower()
            is_rate_limit = "429" in err or "rate limit" in err or "too many" in err
            wait = (30 if is_rate_limit else 5) * (attempt + 1)
            if attempt < MAX_RETRIES - 1:
                logging.warning(f"DeepSeek call failed [{label}] attempt {attempt+1}/{MAX_RETRIES}: {e} — retrying in {wait}s")
                _time.sleep(wait)
            else:
                logging.warning(f"DeepSeek call gave up [{label}]: {e}")
                return ""
    return ""


def summarize_paper_with_ai(title: str, abstract: str, api_key: str,
                             model: str = "deepseek-chat") -> str:
    """Call DeepSeek API (OpenAI-compatible) to generate a concise Chinese summary."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        prompt = (
            "请为以下学术论文提供简洁的中文总结。\n\n"
            f"论文标题：{title}\n"
            f"英文摘要：{abstract}\n\n"
            "请按以下格式输出（每部分1-2句，简洁明了）：\n"
            "🔍 **核心问题**：（解决什么问题）\n"
            "🛠 **方法**：（采用什么技术/方法）\n"
            "✨ **主要贡献**：（关键创新或结果）"
        )
        messages = [
            {"role": "system", "content": "你是计算机视觉、机器人与AI领域的学术论文阅读助手，请用中文提供简洁准确的论文总结。"},
            {"role": "user", "content": prompt},
        ]
        return _call_deepseek_with_retry(client, model, messages, 350, 0.3, title[:40])
    except Exception as e:
        logging.warning(f"AI summary setup failed for '{title[:50]}': {e}")
        return ""


def extract_arxiv_id(link: str) -> str:
    """Extract version-stripped arXiv id used as the cache key.

    https://arxiv.org/abs/2606.07515v1 -> 2606.07515
    """
    import re
    m = re.search(r"arxiv\.org/abs/([0-9]+\.[0-9]+)", link)
    return m.group(1) if m else ""


def download_and_extract_pdf(arxiv_id: str, max_chars: int = 50000) -> str:
    """Download an arXiv PDF and extract its text.

    Retries up to 4 times with exponential back-off; respects 429 rate-limit
    responses by waiting longer before retrying.
    Returns empty string on any failure (caller falls back to abstract).
    """
    import io
    import time as _time
    from urllib.error import HTTPError

    url = f"https://arxiv.org/pdf/{arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ArxivFetcher/1.0)"})

    MAX_RETRIES = 4
    for attempt in range(MAX_RETRIES):
        try:
            data = urllib.request.urlopen(req, timeout=60).read()
            break
        except HTTPError as e:
            if e.code == 429:
                wait = 30 * (attempt + 1)   # 30s, 60s, 90s, 120s
                logging.warning(f"PDF 429 rate-limited for {arxiv_id}, waiting {wait}s (attempt {attempt+1}/{MAX_RETRIES})")
                _time.sleep(wait)
            else:
                logging.warning(f"PDF download failed for {arxiv_id}: {e}")
                return ""
        except Exception as e:
            wait = 5 * (attempt + 1)
            logging.warning(f"PDF download error for {arxiv_id}: {e}, retrying in {wait}s")
            _time.sleep(wait)
    else:
        logging.warning(f"PDF download gave up after {MAX_RETRIES} attempts for {arxiv_id}")
        return ""

    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        text = remove_duplicated_spaces(text)
        if not text.strip():
            logging.warning(f"PDF {arxiv_id} produced empty text after extraction")
            return ""
        return text[:max_chars]
    except Exception as e:
        logging.warning(f"PDF parse failed for {arxiv_id}: {e}")
        return ""


# Structured reading prompt adapted from Research-Paper-Skills
# (skills/paper-reading-summary/references/reading-report-prompt.md).
FULLTEXT_READING_PROMPT = """你是人工智能研究与学术论文分析专家。请仔细阅读并分析下面这篇论文的全文，给出详细的中文解读，严格按照以下章节顺序与标题输出（Markdown 格式）：

## 0. 概览（Concise Summary）
- **主题（Topic）**：论文所属的 AI 领域/任务/问题设定
- **问题（Problem）**：所解决的关键挑战或空白
- **方法（Method）**：提出的方法或框架
- **创新（Innovation）**：相较已有工作的新意
- **意义（Significance）**：为什么重要、带来什么价值
- **一句话总结**：用一句中文概括全文

## 1. 研究动机（Motivation）
说明研究动机：解决领域中的什么问题或空白？为什么重要？挑战在哪里？

## 2. 创新点（Innovation）
识别并描述论文的关键创新或新贡献：提出了什么新方法/技术？与现有方案有何不同？为什么能奏效？

## 3. 主要内容（Main Content）【重点】
### 3.1 设计架构与方法
### 3.2 关键算法与数学推导（公式用 LaTeX，行内用 $...$，独立公式用 $$...$$）
### 3.3 模型、训练与数据集
### 3.4 实验设置与结果
### 3.5 技术细节

## 4. 意义与影响（Significance and Impact）
解决了什么问题、贡献是什么？对未来研究/应用的影响？作者提到的局限与开放问题？

## 5. 澄清与简化（Clarifications and Simplifications）
对高度技术性或复杂的部分用通俗解释或类比帮助理解。

## 6. 补充说明（Additional Notes）
简述相关工作的关联；指出对理解论文最重要的图表。

要求：全程用中文；数学公式用 LaTeX 并加 $ 或 $$；尽量提及重要的图与表。若论文文本被截断或缺失，基于已有内容合理解读并注明假设。"""


def summarize_fulltext_with_ai(title: str, fulltext: str, api_key: str,
                                model: str = "deepseek-chat") -> str:
    """Call DeepSeek API to generate a full 0-6 section deep reading note in Chinese."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        user_content = (
            f"论文标题：{title}\n\n"
            f"论文全文（可能被截断）：\n{fulltext}"
        )
        messages = [
            {"role": "system", "content": FULLTEXT_READING_PROMPT},
            {"role": "user", "content": user_content},
        ]
        return _call_deepseek_with_retry(client, model, messages, 4000, 0.3, title[:40])
    except Exception as e:
        logging.warning(f"AI fulltext summary setup failed for '{title[:50]}': {e}")
        return ""
