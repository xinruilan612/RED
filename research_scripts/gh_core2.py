#!/usr/bin/env python3
"""Second batch: core repo lookups for newly found repos."""
import json
import time
import urllib.request

CORE_REPOS_B = [
    "ZJU-REAL/Easel",
    "xuboboo/xiaohongshu-viral-note-agent-skill",
    "alanl1234/xiaohongshu-matrices-cli",
    "Admin6016/xhs_matrix_system",
    "BetaStreetOmnis/xhs_ai_publisher",
    "Jamailar/Beav",
    "magicCzc/Little-Red-Ant",
    "Xiangyu-CAS/xiaohongshu-ops-skill",
    "gainubi/wechat-skills",
    "paragbml/open-clip-studio",
    "yukitorido/short-video-generator-AI",
    "rayane-rhsn/autopost-ai",
    "kisinad/langgraph-mem0-ai-social-media-manager",
    "MukhammadIbrokhimov/Ai-Assistant",
    "liangdabiao/deep_search_write",
    "leaperone/MultiPost-Extension",
    "growchief/growchief",
    "white0dew/XiaohongshuSkills",
    "inovector/mixpost",
    "OpenClaw-ai/openclaw",
    "jfbfb/GrowthOS-AI-Agent-",
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


for r in CORE_REPOS_B:
    try:
        print("## CORE:", fmt(get(f"https://api.github.com/repos/{r}")), flush=True)
    except Exception as e:
        print(f"## CORE {r} ERROR: {e}", flush=True)
    time.sleep(1)
print("=== DONE ===", flush=True)
