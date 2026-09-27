#!/usr/bin/env python3
"""Phase B leftover queries + repo-by-repo search lookups (10/min budget)."""
import json
import time
import urllib.parse
import urllib.request

QUERIES_B = [
    "linkedin content agent",
    "multi-agent marketing",
    "instagram automation agent",
    "douyin",
    "抖音 内容",
    "short video agent",
    "viral content",
    "video repurpose",
]

REPO_LOOKUPS = [
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
    "inovector/mixpost",
    "OpenClaw-ai/openclaw",
    "jfbfb/GrowthOS-AI-Agent-",
    "white0dew/XiaohongshuSkills",
    "openagents-inc/openagents",
    "socai-io/socai",
    "chenwr727/AI-Short-Video-Engine",
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


print("=== QUERIES B ===", flush=True)
for q in QUERIES_B:
    url = ("https://api.github.com/search/repositories?q=" +
           urllib.parse.quote(q) + "&sort=stars&order=desc&per_page=8")
    try:
        data = get(url)
        print(f"## QUERY: {q}  (total={data['total_count']})", flush=True)
        for item in data.get("items", []):
            print(fmt(item), flush=True)
    except Exception as e:
        print(f"## QUERY: {q}  ERROR: {e}", flush=True)
    time.sleep(8)

print("=== REPO LOOKUPS ===", flush=True)
for r in REPO_LOOKUPS:
    url = ("https://api.github.com/search/repositories?q=" +
           urllib.parse.quote("repo:" + r) + "&per_page=1")
    try:
        data = get(url)
        items = data.get("items", [])
        if items:
            print("## LOOKUP:", fmt(items[0]), flush=True)
        else:
            print(f"## LOOKUP {r} NOT FOUND", flush=True)
    except Exception as e:
        print(f"## LOOKUP {r} ERROR: {e}", flush=True)
    time.sleep(8)
print("=== DONE ===", flush=True)
