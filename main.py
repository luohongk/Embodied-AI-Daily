import os
import sys
import time
import pytz
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import (
    get_daily_papers_by_keyword_with_retries,
    generate_table,
    generate_html,
    back_up_files,
    restore_files,
    remove_backups,
    get_daily_date,
    summarize_paper_with_ai,
    extract_arxiv_id,
    download_and_extract_pdf,
    summarize_fulltext_with_ai,
)
from summary_cache import get_cached_summary, save_summary


# 设置基本日志
logging.basicConfig(level=logging.INFO)

# 使用日志而不是打印
logging.info("脚本开始执行")
# 在每个关键步骤添加日志

beijing_timezone = pytz.timezone("Asia/Shanghai")

# NOTE: arXiv API seems to sometimes return an unexpected empty list.

# get current beijing time date in the format of "2021-08-01"
current_date = datetime.now(beijing_timezone).strftime("%Y-%m-%d")
# get last update date from README.md
with open("README.md", "r") as f:
    while True:
        line = f.readline()
        if "Last update:" in line:
            break
    last_update_date = line.split(": ")[1].strip()
    # if last_update_date == current_date:
    # sys.exit("Already updated today!")

logging.info("获取关键词列表")

keywords = [
    "Vision and Language Navigation",
    # "Vision Language Action",
    # "World Model",
    # "Visual SLAM",
    # "Visual Inertial SLAM",
    # "Visual Inertial Odometry",
    # "Lidar SLAM",
    # "LiDAR Odometry",
    # "GNSS",
    # "Graph Optimization",
    # "Dynamic SLAM",
    # "Semantic SLAM",
    # "Gaussian SLAM",
    # "Autonomous Driving",
    # "Kalman Filter",
    # "Loop Closure Detection",
    # "Visual Place Recognition",
    # "3D Gaussian Splatting",
    # "Deep Learning",
    # "LLM",
]  # TODO add more keywords

max_result = 80  # maximum query results from arXiv API for each keyword
readme_max_result = 20  # maximum papers to be included in README.md for each keyword
issues_result = 10  # maximum papers to be included in the issue

# AI summary configuration — read from environment variables
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
AI_SUMMARY_TOP_N = int(os.environ.get("AI_SUMMARY_TOP_N", "5"))
AI_FULLTEXT = os.environ.get("AI_FULLTEXT", "1") == "1"  # 1=read full PDF, 0=abstract only
AI_WORKERS = int(os.environ.get("AI_WORKERS", "4"))  # concurrent summary threads
if DEEPSEEK_API_KEY:
    mode = "全文深度阅读" if AI_FULLTEXT else "仅摘要"
    logging.info(f"DeepSeek AI 总结已启用（{mode}），每个关键词最多总结前 {AI_SUMMARY_TOP_N} 篇论文，并发 {AI_WORKERS} 线程")
else:
    logging.info("未设置 DEEPSEEK_API_KEY，仅复用已有缓存，不调用 API")


def process_paper_summary(paper):
    """Resolve one paper's AI summary (cache-first, then generate).

    Runs inside a thread pool. Mutates and returns the paper dict with
    an ``AI_Summary`` field when a summary is available.
    """
    title = paper.get("Title", "")
    abstract = paper.get("Abstract", "")
    link = paper.get("Link", "")
    arxiv_id = extract_arxiv_id(link)

    # 1. Cache hit -> reuse, zero cost.
    cached = get_cached_summary(arxiv_id)
    if cached:
        paper["AI_Summary"] = cached
        logging.info(f"  [缓存命中] {arxiv_id}")
        return paper

    # 2. No API key -> can only use cache, skip generation.
    if not DEEPSEEK_API_KEY:
        return paper

    # 3. Generate: full-text deep read when possible.
    summary = ""
    if AI_FULLTEXT and arxiv_id:
        logging.info(f"  [下载全文] {arxiv_id}")
        fulltext = download_and_extract_pdf(arxiv_id)
        if fulltext:
            summary = summarize_fulltext_with_ai(title, fulltext, DEEPSEEK_API_KEY)

    # 4. Fallback to abstract-based summary when full text is unavailable.
    if not summary and abstract:
        summary = summarize_paper_with_ai(title, abstract, DEEPSEEK_API_KEY)

    # 5. Store in cache ("database") and attach for HTML.
    if summary:
        paper["AI_Summary"] = summary
        save_summary(arxiv_id, title, link, summary)
    return paper


# all columns: Title, Authors, Abstract, Link, Tags, Comment, Date
# fixed_columns = ["Title", "Link", "Date"]

column_names = ["Title", "Link", "Abstract", "Date", "Comment"]

back_up_files()  # back up README.md and ISSUE_TEMPLATE.md

logging.info("获取每日论文")
# write to README.md
f_rm = open("README.md", "w", encoding="utf-8")
f_rm.write(
    """<div align="center">

# 🚀 Embodied-AI-Daily

_Automatically fetches the latest arXiv papers on **VLN · VLA · SLAM · 3D · Embodied AI**_

<p>
  <img src="https://img.shields.io/badge/Update-Daily-brightgreen.svg" alt="每日更新">
  <img src="https://img.shields.io/badge/Source-arXiv-red.svg" alt="来源：arXiv">
  <img src="https://img.shields.io/badge/Papers-VLN·VLA·SLAM·3D-blue.svg" alt="论文主题：VLN·VLA·SLAM·3D">
  <img src="https://img.shields.io/github/stars/luohongk/Embodied-AI-Daily?style=social" alt="GitHub Stars">
  <a href="https://github.com/luohongk" target="_blank">
    <img src="https://img.shields.io/badge/Author-luohongkun-blueviolet.svg" alt="作者：luohongk">
  </a
  <a href="https://luohongkun.top/scholar/" target="_blank">
    <img src="https://img.shields.io/badge/Homepage-www.luohongkun.top/scholar/-9cf.svg" alt="主页：GitHub">
  </a>
</p>

<p>
Embodied-AI-Daily Web:http://luohongkun.top/Embodied-AI-Daily/
</p>


</div>

---

## ☕ 支持本项目 / Support this project

每篇论文的 **AI 深度总结**都会调用大量 [DeepSeek](https://www.deepseek.com/) API（需付费）。如果这个项目对你有帮助，欢迎请作者喝杯咖啡，支持服务器与 API 开销 🙏

<div align="center">
  <img src="images/wechat_pay.jpg" alt="WeChat Pay QR code" width="240">
  <p><em>💚 微信赞助 / Sponsor via WeChat Pay</em></p>
</div>

---

## 📌 About
This project automatically fetches the latest papers from **arXiv** based on predefined keywords.  
- Each section in the README corresponds to a **search keyword** (up to **{1} per keyword**).
- The full list (up to **{2} per keyword**) is available in the [`papers/`](papers/) directory.
- Click **Watch** (👀) on the repo to get **daily email notifications**.

_Last update: {0}_

---
""".format(current_date, readme_max_result, max_result)
)
logging.info("生成readme")
# write to ISSUE_TEMPLATE.md
f_is = open(".github/ISSUE_TEMPLATE.md", "w")  # file for ISSUE_TEMPLATE.md
f_is.write("---\n")
f_is.write("title: Latest {0} Papers - {1}\n".format(issues_result, get_daily_date()))
f_is.write("labels: documentation\n")
f_is.write("---\n")
f_is.write(
    "**Please check the [Github](https://github.com/luohongk/DailyArXiv) page for a better reading experience and more papers.**\n\n"
)

# create papers directory if not exists
os.makedirs("papers", exist_ok=True)

# collect all papers for HTML generation
all_papers = {}

for keyword in keywords:
    logging.info(f"正在处理关键词: {keyword}")
    f_rm.write("## {0}\n".format(keyword))
    f_is.write("## {0}\n".format(keyword))
    if len(keyword.split()) == 1:
        link = "AND"  # for keyword with only one word, We search for papers containing this keyword in both the title and abstract.
    else:
        link = "OR"
    papers = get_daily_papers_by_keyword_with_retries(
        keyword, column_names, max_result, link
    )
    logging.info("成功获取论文")
    if papers is None:  # failed to get papers
        logging.error(f"未能获取关键词 '{keyword}' 的论文！")
        print("Failed to get papers!")
        f_rm.close()
        f_is.close()
        restore_files()
        sys.exit("Failed to get papers!")

    logging.info(f"成功获取 {len(papers)} 篇论文，正在生成表格。")

    # Generate / reuse AI summaries for top N papers, concurrently.
    # Cache-first: if summaries/<arxiv_id>.md exists, reuse it (no API call).
    if papers:
        n = min(AI_SUMMARY_TOP_N, len(papers))
        logging.info(f"正在并发处理 '{keyword}' 前 {n} 篇论文的 AI 总结（{AI_WORKERS} 线程）...")
        with ThreadPoolExecutor(max_workers=AI_WORKERS) as executor:
            # papers[i] dicts are mutated in place by process_paper_summary.
            futures = [executor.submit(process_paper_summary, papers[i]) for i in range(n)]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logging.warning(f"AI summary task failed: {e}")

    # Store papers for HTML generation
    all_papers[keyword] = papers

    # Write to README.md (only first `readme_max_result` papers)
    rm_table = generate_table(papers[:readme_max_result])
    f_rm.write(rm_table)
    # Add link to full topic page
    topic_filename = keyword.replace(" ", "-") + ".md"
    f_rm.write(f"\n\n> 📄 [View all {len(papers)} papers for {keyword}](papers/{topic_filename})\n\n")

    # Write full topic page to papers/{keyword}.md
    with open(f"papers/{topic_filename}", "w", encoding="utf-8") as f_topic:
        f_topic.write(f"# {keyword}\n\n")
        f_topic.write(f"> **{len(papers)} papers** fetched from arXiv for the keyword **{keyword}**.\n\n")
        f_topic.write(f"> Last update: {current_date}\n\n")
        f_topic.write(f"[← Back to README](../README.md)\n\n")
        f_topic.write("---\n\n")
        f_topic.write(generate_table(papers))
        f_topic.write("\n")

    # Write to ISSUE_TEMPLATE.md
    is_table = generate_table(papers[:issues_result], ignore_keys=["Abstract"])
    f_is.write(is_table)
    f_is.write("\n\n")
    time.sleep(7)  # avoid being blocked by arXiv API

# Generate index.html
logging.info("生成 index.html")
html_content = generate_html(all_papers, current_date)
with open("index.html", "w", encoding="utf-8") as f_html:
    f_html.write(html_content)

f_rm.close()
f_is.close()
remove_backups()
