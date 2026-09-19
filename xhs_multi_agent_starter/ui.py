import os

import streamlit as st

from app.backend_http import create_backend_session

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
backend_http = create_backend_session(BACKEND_URL)

st.set_page_config(page_title="小红书多 Agent 内容工作台", layout="wide")
st.title("小红书多 Agent 内容工作台")
st.caption("受众洞察 → 素材研究 → 内容策略 → 创作 → 审核 → 改稿 → 人工确认")

with st.sidebar:
    st.subheader("连接状态")
    try:
        health_response = backend_http.get(f"{BACKEND_URL}/health", timeout=5)
        health_response.raise_for_status()
        health = health_response.json()
        st.success(f"后端正常｜模式：{health['llm_mode']}")
    except Exception:
        st.error("无法连接后端。请先启动 FastAPI。")

with st.form("brief_form"):
    left, right = st.columns(2)
    with left:
        topic = st.text_input("主题 *", placeholder="例如：零基础搭建个人知识库")
        niche = st.text_input("账号赛道", value="效率工具 / AI")
        audience = st.text_area("目标读者", value="没有编程经验、希望提高工作效率的上班族")
        account_persona = st.text_area("账号人设", value="真诚实操、会说明踩坑和适用边界")
        objective = st.selectbox("主要目标", ["提升收藏与评论", "建立专业信任", "吸引精准关注", "引导私信咨询"])
    with right:
        tone = st.text_input("语气", value="真诚、口语化、具体，不过度夸张")
        max_length = st.slider("正文目标长度", min_value=300, max_value=1800, value=900, step=100)
        key_points_text = st.text_area(
            "必须写入的真实要点（每行一条）",
            placeholder="我实际使用了两周\n第一版只用了三个工具\n最大的坑是没有先确定资料分类",
        )
        forbidden_text = st.text_area(
            "禁止使用的说法（每行一条）",
            value="保证爆款\n百分百有效\n未经核验的数据",
        )
        reference_text = st.text_area(
            "可核验资料 / 个人经历",
            placeholder="粘贴产品资料、采访记录、个人实验记录等。没有资料时，研究 Agent 会明确提示证据缺口。",
            height=160,
        )
    submitted = st.form_submit_button("让 Agent 团队开始工作", type="primary", use_container_width=True)

if submitted:
    if len(topic.strip()) < 2:
        st.warning("请先填写主题。")
        st.stop()

    payload = {
        "topic": topic.strip(),
        "niche": niche.strip() or "通用",
        "audience": audience.strip(),
        "account_persona": account_persona.strip(),
        "objective": objective,
        "tone": tone.strip(),
        "key_points": [line.strip() for line in key_points_text.splitlines() if line.strip()],
        "reference_text": reference_text.strip(),
        "forbidden_claims": [line.strip() for line in forbidden_text.splitlines() if line.strip()],
        "max_length": max_length,
    }

    with st.spinner("Agent 团队正在协作……"):
        response = backend_http.post(f"{BACKEND_URL}/api/runs", json=payload, timeout=300)
    if response.status_code >= 400:
        st.error(response.text)
        st.stop()
    result = response.json()
    st.session_state["latest_result"] = result

result = st.session_state.get("latest_result")
if result:
    draft = result.get("draft") or {}
    review = result.get("final_review") or {}

    st.divider()
    st.subheader("最终稿")
    st.markdown(f"### {draft.get('selected_title', '')}")
    st.code(draft.get("cover_text", ""), language=None)
    st.write(draft.get("body", ""))
    st.write(" ".join(draft.get("hashtags", [])))

    m1, m2, m3 = st.columns(3)
    m1.metric("主编评分", review.get("total_score", 0))
    m2.metric("返工轮数", result.get("revision_rounds", 0))
    m3.metric("是否通过", "是" if review.get("approved") else "需人工判断")

    with st.expander("标题候选"):
        for title in draft.get("title_candidates", []):
            st.write(f"- {title}")
    with st.expander("受众洞察"):
        st.json(result.get("audience"), expanded=True)
    with st.expander("研究与证据边界"):
        st.json(result.get("research"), expanded=True)
    with st.expander("内容策略"):
        st.json(result.get("strategy"), expanded=True)
    with st.expander("主编审核"):
        st.json(review, expanded=True)
    with st.expander("Agent 运行轨迹"):
        st.json(result.get("traces"), expanded=False)

    st.info("发布前请人工确认事实、经历、数据、品牌要求和平台规范。系统只能提高内容质量，不能保证流量。")

    with st.form("feedback_form"):
        st.subheader("发布后回填数据")
        cols = st.columns(6)
        views = cols[0].number_input("浏览", min_value=0, step=1)
        likes = cols[1].number_input("点赞", min_value=0, step=1)
        comments = cols[2].number_input("评论", min_value=0, step=1)
        saves = cols[3].number_input("收藏", min_value=0, step=1)
        shares = cols[4].number_input("分享", min_value=0, step=1)
        follows = cols[5].number_input("新增关注", min_value=0, step=1)
        feedback_submitted = st.form_submit_button("保存复盘数据")
        if feedback_submitted:
            feedback = {
                "views": views,
                "likes": likes,
                "comments": comments,
                "saves": saves,
                "shares": shares,
                "follows": follows,
            }
            feedback_response = backend_http.post(
                f"{BACKEND_URL}/api/runs/{result['run_id']}/feedback",
                json=feedback,
                timeout=30,
            )
            if feedback_response.status_code >= 400:
                st.error(feedback_response.text)
            else:
                metrics = feedback_response.json()
                st.success(
                    "已保存｜互动率 {:.2%}｜收藏率 {:.2%}｜评论率 {:.2%}｜关注转化 {:.2%}".format(
                        metrics["engagement_rate"],
                        metrics["save_rate"],
                        metrics["comment_rate"],
                        metrics["follow_rate"],
                    )
                )
