import sys
import time
import pytz
from datetime import datetime
import logging

from utils import (
    get_daily_papers_by_keyword_with_retries,
    generate_table,
    back_up_files,
    restore_files,
    remove_backups,
    get_daily_date,
)


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
    "Vision Language Action",
    "World Model",
    "Visual SLAM",
    "Visual Inertial SLAM",
    "Visual Inertial Odometry",
    "Lidar SLAM",
    "LiDAR Odometry",
    "GNSS",
    "Graph Optimization",
    "Dynamic SLAM",
    "Semantic SLAM",
    "Gaussian SLAM",
    "Autonomous Driving",
    "Kalman Filter",
    "Loop Closure Detection",
    "Visual Place Recognition",
    "3D Gaussian Splatting",
    "Deep Learning",
    "LLM",
]  # TODO add more keywords

max_result = 80  # maximum query results from arXiv API for each keyword
issues_result = 10  # maximum papers to be included in the issue

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


</div>

---

## 📌 About
This project automatically fetches the latest papers from **arXiv** based on predefined keywords.  
- Each section in the README corresponds to a **search keyword**.  
- Only the most recent papers are kept (up to **100 per keyword**).  
- Click **Watch** (👀) on the repo to get **daily email notifications**.

_Last update: {0}_

---
""".format(current_date)
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
    rm_table = generate_table(papers)
    is_table = generate_table(papers[:issues_result], ignore_keys=["Abstract"])
    f_rm.write(rm_table)
    f_rm.write("\n\n")
    f_is.write(is_table)
    f_is.write("\n\n")
    time.sleep(7)  # avoid being blocked by arXiv API

f_rm.close()
f_is.close()
remove_backups()
