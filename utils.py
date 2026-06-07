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

def generate_html(all_papers: Dict[str, List[Dict[str, str]]], current_date: str) -> str:
    """Generate a beautiful self-contained HTML page from all papers data."""

    # Build topic navigation items
    nav_items = ""
    content_sections = ""

    # Color palette for topic tags
    topic_colors = [
        "#6366f1", "#8b5cf6", "#a855f7", "#d946ef", "#ec4899",
        "#f43f5e", "#ef4444", "#f97316", "#f59e0b", "#84cc16",
        "#22c55e", "#10b981", "#14b8a6", "#06b6d4", "#0ea5e9",
        "#3b82f6", "#6366f1", "#8b5cf6", "#a855f7", "#d946ef",
    ]

    for i, (keyword, papers) in enumerate(all_papers.items()):
        if not papers:
            continue
        topic_id = keyword.replace(" ", "-")
        color = topic_colors[i % len(topic_colors)]
        count = len(papers)

        # Navigation item
        nav_items += f"""            <a href="#{topic_id}" class="nav-item">
                <span class="nav-dot" style="background:{color}"></span>
                <span class="nav-label">{keyword}</span>
                <span class="nav-count">{count}</span>
            </a>\n"""

        # Build paper cards
        cards = ""
        for paper in papers:
            title = paper.get("Title", "")
            link = paper.get("Link", "")
            abstract = paper.get("Abstract", "")
            date_str = paper.get("Date", "").split("T")[0] if paper.get("Date") else ""
            comment = paper.get("Comment", "")

            abstract_html = ""
            if abstract:
                abstract_html = f"""                    <details class="paper-abstract">
                        <summary>Show abstract</summary>
                        <p>{escape_nunjucks(abstract)}</p>
                    </details>"""

            comment_html = ""
            if comment:
                comment_html = f'                    <span class="paper-comment">📝 {escape_nunjucks(comment)}</span>'

            cards += f"""                <div class="paper-card">
                    <div class="paper-header">
                        <a href="{link}" target="_blank" class="paper-title">{escape_nunjucks(title)}</a>
                        <span class="paper-date">{date_str}</span>
                    </div>
                    {comment_html}
                    {abstract_html}
                </div>\n"""

        # Content section
        content_sections += f"""        <section id="{topic_id}" class="topic-section">
            <div class="topic-header">
                <span class="topic-badge" style="background:{color}">{keyword}</span>
                <span class="topic-count">{count} papers</span>
            </div>
            <div class="paper-list">
{cards}            </div>
        </section>\n"""

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

        /* Footer */
        .footer {{
            text-align: center;
            padding: 40px 0 20px;
            color: var(--text-secondary);
            font-size: .82rem;
            border-top: 1px solid var(--border);
            margin-top: 20px;
        }}

        /* Responsive */
        @media (max-width: 900px) {{
            .sidebar {{
                display: none;
            }}
            .main {{
                margin-left: 0;
                max-width: 100%;
                padding: 20px 16px;
            }}
            .hero h2 {{
                font-size: 1.4rem;
            }}
            .paper-header {{
                flex-direction: column;
                gap: 4px;
            }}
        }}
    </style>
</head>
<body>
    <nav class="sidebar">
        <div class="sidebar-header">
            <h1>🚀 Embodied AI Daily</h1>
            <div class="update">Last update: {current_date}</div>
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
        </section>

{content_sections}
        <footer class="footer">
            <p>🤖 Generated automatically from <a href="https://arxiv.org" style="color:var(--accent)">arXiv</a> · <a href="https://github.com/luohongk/Embodied-AI-Daily" style="color:var(--accent)">GitHub Repo</a></p>
            <p style="margin-top:4px">Last update: {current_date} (Beijing Time)</p>
        </footer>
    </main>
</body>
</html>"""

    return html


def get_daily_date():
    # get beijing time in the format of "March 1, 2021"
    beijing_timezone = pytz.timezone('Asia/Shanghai')
    today = datetime.datetime.now(beijing_timezone)
    return today.strftime("%B %d, %Y")
