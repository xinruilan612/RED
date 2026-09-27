#!/usr/bin/env python3
"""Batch GitHub API search for social-media agent / content ops repos.
Unauthenticated: 10 search req/min, 60 core req/hr. Two phases with sleeps.
Output: compact TSV lines (full_name | stars | pushed_at | license | archived | description)
"""
import json
import time
import urllib.request

SEARCH_QUERIES = [
    "social media agent",
    "social media automation",
    "social media manager ai",
    "content creation ai agent",
    "xiaohongshu",
    "小红书",
    "tiktok agent",
    "twitter ai agent",
]

SEARCH_QUERIES_B = [
    "linkedin content agent",
    "multi-agent marketing",
    "instagram automation agent",
    "douyin",
    "抖音",
    "short video agent",
    "viral content",
    "video repurpose",
]

CORE_REPOS = [
    "gitroomhq/postiz-app",
    "langchain-ai/social-media-agent",
    "Klaudiusz321/social-media-agents",
    "NanmiCoder/MediaCrawler",
    "JoeanAmier/XHS-Downloader",
    "dreammis/social-auto-upload",
    "kvnZero/xhs-agent",
    "EthanYoQ/agent-xiaohongshu-workbench",
    "aravindprem17/local-agentic-social-architect",
    "inbharatai/SocialFlow",
    "samuellachisa/chimera",
    "openagents-inc/openagents",
    "HisMax/RedInk",
    "Aaronwn/ai-xiaohs",
]


def get(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "research-agent",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fmt(repo):
    lic = (repo.get("license") or {}).get("spdx_id") or ""
    desc = (repo.get("description") or "").replace("\t", " ").replace("\n", " ")
    return "\t".join([
        repo["full_name"],
        str(repo["stargazers_count"]),
        (repo.get("pushed_at") or "")[:10],
        lic,
        str(repo.get("archived")),
        desc[:220],
        repo["html_url"],
    ])


def run_phase(queries, per_page=12):
    for q in queries:
        url = ("https://api.github.com/search/repositories?q=" +
               urllib.parse.quote(q) +
               f"&sort=stars&order=desc&per_page={per_page}")
        try:
            data = get(url)
            print(f"## QUERY: {q}  (total={data['total_count']})")
            for item in data.get("items", []):
                print(fmt(item))
        except Exception as e:
            print(f"## QUERY: {q}  ERROR: {e}")
        time.sleep(7)


def run_core(repos):
    for r in repos:
        try:
            data = get(f"https://api.github.com/repos/{r}")
            print("## CORE:", fmt(data))
        except Exception as e:
            print(f"## CORE {r} ERROR: {e}")
        time.sleep(1)


import urllib.parse  # noqa: E402

if __name__ == "__main__":
    print("=== PHASE A ===", flush=True)
    run_phase(SEARCH_QUERIES)
    print("=== PHASE B (after 65s sleep) ===", flush=True)
    time.sleep(65)
    run_phase(SEARCH_QUERIES_B)
    print("=== CORE REPOS ===", flush=True)
    run_core(CORE_REPOS)
    print("=== DONE ===", flush=True)
