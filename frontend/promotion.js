"use strict";
let editingServiceId = null;
const promotionGoals = {
  discovery: "被发现",
  trust: "建立信任",
  inquiry: "促成咨询",
};
const attributionLabels = {
  explicit: "明确来自一篇内容",
  multi_touch: "多篇内容共同影响",
  unknown: "来源未知",
};
const validityLabels = {
  pending: "待判断",
  valid: "有效咨询",
  invalid: "无效咨询",
};
const promotionSourceLabels = {
  manual: "真实人工记录",
  simulation: "模拟演示数据",
};

function promotionRows(key) {
  return (ops?.[key] || []).filter((row) => row.account_id === activeAccountId);
}
function serviceForm(service) {
  const value = (key, fallback = "") => esc(service?.[key] ?? fallback),
    pub = new Set(
      service?.public_fields || ["offering", "target_customer", "delivery"],
    );
  const check = (key, label) =>
    `<label class="checkbox"><input type="checkbox" name="public_fields" value="${key}" ${pub.has(key) ? "checked" : ""}> 允许公开${label}</label>`;
  return `<form id="serviceForm" class="panel"><div class="detail-heading"><div><span class="eyebrow">SERVICE PROFILE</span><h2>${service ? "更新服务档案 v" + service.version : "新建服务档案"}</h2></div>${service ? badge(service.active ? "使用中" : "已停用", "neutral") : ""}</div><input type="hidden" name="id" value="${value("id")}"><div class="two-col"><label>服务名称<input name="name" maxlength="100" value="${value("name")}" required placeholder="例如：校园毕业照"></label><label>服务地域或方式<input name="delivery" maxlength="500" value="${value("delivery")}" required placeholder="例如：本校校内线下拍摄"></label></div><label>提供的具体服务<textarea name="offering" maxlength="1200" rows="3" required>${value("offering")}</textarea></label><label>目标客户<textarea name="target_customer" maxlength="500" rows="2" required>${value("target_customer")}</textarea></label><div class="two-col"><label>价格或计价方式<input name="price" maxlength="300" value="${value("price")}" placeholder="不填则不生成报价"></label><label>可约时间<input name="availability" maxlength="300" value="${value("availability")}" placeholder="不填则不承诺档期"></label></div><label>允许公开的预约方式<input name="contact" maxlength="500" value="${value("contact")}" placeholder="不自动添加微信、电话等私人信息"></label><div class="public-field-grid">${check("offering", "具体服务")}${check("target_customer", "目标客户")}${check("delivery", "地域/方式")}${check("price", "价格")}${check("availability", "档期")}${check("contact", "预约方式")}</div><label class="checkbox"><input type="checkbox" name="active" ${service?.active === false ? "" : "checked"}> 用于新的推广任务</label><div class="buttons"><button class="primary">保存服务档案</button>${service ? '<button type="button" id="cancelServiceEdit" class="quiet">取消编辑</button>' : ""}</div><p class="helper">字段只有勾选为允许公开，才会进入推广简报和模型上下文。历史任务继续保留当时快照。</p></form>`;
}

function renderPromotion() {
  const services = promotionRows("services"),
    portfolio = promotionRows("portfolio_items"),
    briefs = promotionRows("promotion_briefs"),
    inquiries = promotionRows("inquiries"),
    analyses = promotionRows("promotion_analyses");
  const active = services.filter((row) => row.active),
    editing = services.find((row) => row.id === editingServiceId);
  const serviceOptions = active
    .map(
      (row) =>
        `<option value="${row.id}">${esc(row.name)} · v${row.version}</option>`,
    )
    .join("");
  const published = accountRows("publications").filter(
    (row) => row.published_at && row.promotion,
  );
  $("operationsContent").innerHTML =
    `<div class="ops-hero promotion-hero"><div><span class="eyebrow">SERVICE PROMOTION / 接单推广</span><h2>用真实作品获得合适咨询，而不是批量制造营销话术。</h2><p>服务事实 → 客户问题 → 有依据的内容 → 人工发布 → 匿名咨询 → 下一轮建议。</p></div>${badge(services.length + " 个服务 · " + inquiries.filter((x) => x.status === "active").length + " 条咨询")}</div><div class="stats ops-stats">${stat("有效服务", active.length, "按当前账号隔离")}${stat("可公开作品", portfolio.filter((x) => x.active && x.public_confirmed).length, "未经确认不进入稿件")}${stat("有效咨询", inquiries.filter((x) => x.status === "active" && x.validity === "valid").length, "用户回填 · 非平台认证")}</div><div class="promotion-layout"><section><div class="section-toolbar"><div><h2>服务与作品证据</h2><p class="muted">先明确什么可以公开；价格、档期和联系方式不会被默认加入文案。</p></div><button id="newService" class="secondary">＋ 新建服务</button></div>${serviceForm(editing || null)}<div class="service-list">${services.map((s) => `<article class="panel service-card"><div class="card-top"><div>${badge(s.active ? "使用中" : "已停用", s.active ? "" : "neutral")} ${badge("v" + s.version, "neutral")}</div><button class="quiet" data-edit-service="${s.id}">编辑</button></div><h2>${esc(s.name)}</h2><p>${esc(s.offering)}</p><p class="muted">面向 ${esc(s.target_customer)} · ${esc(s.delivery)}</p><small>允许公开：${esc(s.public_fields.join("、") || "仅服务名称")}</small></article>`).join("")}</div>${active.length ? `<form id="portfolioForm" class="panel"><h2>添加作品记录</h2><label>关联服务<select name="service_id">${serviceOptions}</select></label><div class="two-col"><label>作品标题<input name="title" maxlength="120" required></label><label>作品链接（可选，不自动抓取）<input name="link" type="url"></label></div><label>用户确认的案例描述<textarea name="description" maxlength="1500" rows="2" required></textarea></label><div class="two-col"><label>本人承担的工作<textarea name="role" maxlength="500" rows="2" required></textarea></label><label>可支持的事实<textarea name="facts" maxlength="1500" rows="2" required></textarea></label></div><label class="checkbox"><input name="public_confirmed" type="checkbox"> 已确认作品及描述可用于公开推广</label><button class="secondary">保存作品</button></form>` : empty("先建立一个服务档案", "没有服务时，不生成接单推广文案。")}<div class="portfolio-list">${portfolio.map((p) => `<article class="panel"><div>${badge(p.public_confirmed ? "已确认公开" : "仅内部参考", p.public_confirmed ? "" : "amber")} ${badge(p.active ? "可用" : "已停用", "neutral")}</div><h3>${esc(p.title)}</h3><p>${esc(p.facts)}</p><small>${esc(services.find((s) => s.id === p.service_id)?.name || "服务已变更")} · v${p.version}</small></article>`).join("")}</div></section><section><div class="section-toolbar"><div><h2>客户问题与推广简报</h2><p class="muted">问题来源必须明确；模型假设不会冒充真实咨询。</p></div></div>${
      active.length
        ? `<form id="promotionBriefForm" class="panel"><label>选择服务<select name="service_id">${serviceOptions}</select></label><div class="two-col"><label>目标<select name="goal"><option value="discovery">被发现</option><option value="trust">建立信任</option><option value="inquiry">促成咨询</option></select></label><label>客户问题来源<select name="problem_source"><option value="user_provided">用户提供</option><option value="consultation_summary">真实咨询汇总</option><option value="model_hypothesis">待验证假设</option></select></label></div><label>客户正在担心或询问什么<textarea name="customer_problem" maxlength="500" rows="2" required placeholder="例如：第一次拍毕业照不会摆姿势怎么办"></textarea></label><fieldset class="portfolio-choice"><legend>可引用作品</legend>${
            portfolio
              .filter((p) => p.active && p.public_confirmed)
              .map(
                (p) =>
                  `<label class="checkbox" data-service="${p.service_id}"><input type="checkbox" name="portfolio_ids" value="${p.id}"> ${esc(p.title)} · v${p.version}</label>`,
              )
              .join("") ||
            '<p class="helper">暂无确认可公开作品；可以生成简报，但不能虚构案例。</p>'
          }</fieldset><button class="primary">生成可追溯推广简报</button></form>`
        : ""
    }<div class="brief-list">${briefs.map((b) => `<article class="panel memory-card"><div class="card-top"><div>${badge(promotionGoals[b.goal])} ${badge(b.problem_source_label, "amber")}</div>${badge(b.status === "active" ? "可用于创作" : "需重新确认", b.status === "active" ? "" : "neutral")}</div><h2>${esc(b.topic)}</h2><p>${esc(b.customer_problem)}</p>${b.missing.map((x) => `<p class="helper">缺口：${esc(x)}</p>`).join("")}<details><summary>查看服务与作品快照</summary><pre class="source-text">${esc(b.material)}</pre><p class="helper">服务 v${b.service_version} · 作品 ${b.portfolio_ids.length} 个 · ${esc(b.invalid_reason)}</p></details>${b.status === "active" ? `<button class="primary" data-use-promotion="${b.id}">带着这份证据创作 →</button>` : ""}</article>`).join("") || empty("还没有推广简报", "填写一个真实客户问题，系统只使用允许公开的服务与作品事实。")}</div></section></div><div class="section-toolbar"><div><h2>匿名咨询与确定性复盘</h2><p class="muted">不收集姓名、电话或微信号；来源未知不会被算成某篇内容转化。</p></div></div>${active.length ? `<div class="promotion-feedback"><form id="inquiryForm" class="panel"><h3>记录一次咨询</h3><label>服务<select name="service_id">${serviceOptions}</select></label><div class="two-col"><label>咨询时间<input name="occurred_at" type="datetime-local" value="${dateInput()}" required></label><label>问题分类<input name="problem_category" maxlength="100" required placeholder="例如：是否提供服装"></label></div><label>归因方式<select name="attribution"><option value="unknown">来源未知</option><option value="explicit">咨询者明确提到一篇内容</option><option value="multi_touch">多篇内容共同影响</option></select></label><label>明确关联的已发布推广内容<select name="publication_id"><option value="">不绑定单篇内容</option>${published.map((p) => `<option value="${p.id}">${esc(p.content.selected_title)}</option>`).join("")}</select></label><label>归因依据<input name="attribution_basis" maxlength="500" placeholder="例如：咨询者自述看到该篇内容"></label><label>脱敏摘要<textarea name="summary" maxlength="1000" rows="2" placeholder="不要填写姓名、电话、微信号"></textarea></label><label>有效性<select name="validity"><option value="pending">待判断</option><option value="valid">有效咨询</option><option value="invalid">无效咨询</option></select></label><button class="secondary">保存匿名咨询</button></form><form id="promotionAnalysisForm" class="panel"><h3>生成观察窗口复盘</h3><label>服务<select name="service_id">${serviceOptions}</select></label><div class="two-col"><label>窗口开始<input name="window_start" type="datetime-local" required></label><label>窗口结束<input name="window_end" type="datetime-local" value="${dateInput()}" required></label></div><label class="checkbox"><input name="confirmed_complete" type="checkbox"> 已完整回填这个窗口内的咨询</label><label class="checkbox"><input name="zero_confirmed" type="checkbox"> 明确确认本窗口无咨询（只有确实无记录时勾选）</label><button class="primary">生成规则复盘</button><p class="helper">不调用模型，不计算订单、收入或虚构转化率。</p></form></div>` : ""}<div class="inquiry-list">${inquiries.map((i) => `<article class="panel inquiry-row"><div><b>${esc(i.problem_category)}</b><p>${esc(i.summary || "未填写摘要")}</p><small>${esc(dateText(i.occurred_at))} · ${esc(attributionLabels[i.attribution])} · ${esc(validityLabels[i.validity])} · v${i.version}</small></div>${i.status === "active" ? `<div class="buttons"><button class="quiet" data-inquiry="${i.id}" data-validity="valid">标为有效</button><button class="quiet" data-inquiry="${i.id}" data-validity="invalid">标为无效</button><button class="quiet" data-inquiry="${i.id}" data-revoke="true">撤销</button></div>` : badge("已撤销", "neutral")}</article>`).join("")}</div><div class="analysis-list">${analyses.map((a) => `<article class="panel analysis-card"><div class="card-top"><div>${badge("规则复盘 · 无模型调用")} ${badge(a.confirmed_complete ? "窗口已确认" : "回填未确认", "amber")}</div>${badge(a.status === "valid" ? "有效" : "依赖已修正 · 失效", "neutral")}</div><h2>${esc(services.find((s) => s.id === a.service_id)?.name || "历史服务")}</h2><p>咨询 ${a.counts.total} · 明确关联 ${a.counts.explicit} · 有效 ${a.counts.valid} · 来源未知 ${a.counts.unknown} · 多触点 ${a.counts.multi_touch}</p><p class="memory-advice">${esc(a.suggestion)}</p>${a.repeated_questions.map((q) => `<p>${esc(q.category)}：${q.count} 次</p>`).join("")}<p class="helper">${esc(a.limitation)} ${esc(a.invalid_reason)}</p></article>`).join("")}</div>`;
  addPromotionSourceControls(inquiries, analyses);
  bindPromotionForms();
}

function addPromotionSourceControls(inquiries, analyses) {
  const field =
    '<label>数据来源<select name="source_type"><option value="manual">真实人工记录</option><option value="simulation">模拟演示数据</option></select></label>';
  for (const identity of ["inquiryForm", "promotionAnalysisForm"]) {
    const form = $(identity);
    const serviceField = form?.querySelector('[name="service_id"]')?.closest("label");
    if (serviceField) serviceField.insertAdjacentHTML("afterend", field);
  }
  const helper = $("serviceForm")?.querySelector(".helper");
  if (helper)
    helper.textContent =
      "服务名称默认公开；其他字段只有勾选为允许公开，才会进入推广简报和模型上下文。历史任务继续保留当时快照。";
  document.querySelectorAll(".inquiry-row small").forEach((node, index) => {
    node.textContent += ` · ${promotionSourceLabels[inquiries[index].source_type] || "来源待确认"}`;
  });
  document.querySelectorAll(".analysis-card .card-top > div:first-child").forEach((node, index) => {
    node.insertAdjacentHTML(
      "beforeend",
      ` ${badge(promotionSourceLabels[analyses[index].source_type] || "来源待确认", "neutral")}`,
    );
  });
}

function bindPromotionForms() {
  $("newService").onclick = () => {
    editingServiceId = null;
    renderPromotion();
    $("serviceForm").scrollIntoView({ behavior: "smooth" });
  };
  document.querySelectorAll("[data-edit-service]").forEach(
    (button) =>
      (button.onclick = () => {
        editingServiceId = button.dataset.editService;
        renderPromotion();
        $("serviceForm").scrollIntoView({ behavior: "smooth" });
      }),
  );
  if ($("cancelServiceEdit"))
    $("cancelServiceEdit").onclick = () => {
      editingServiceId = null;
      renderPromotion();
    };
  $("serviceForm").onsubmit = async (event) => {
    event.preventDefault();
    const f = event.target.elements;
    const publicFields = [
      ...event.target.querySelectorAll('[name="public_fields"]:checked'),
    ].map((x) => x.value);
    if (
      await operate("save_service", {
        id: f.id.value,
        account_id: activeAccountId,
        name: f.name.value,
        offering: f.offering.value,
        target_customer: f.target_customer.value,
        delivery: f.delivery.value,
        price: f.price.value,
        availability: f.availability.value,
        contact: f.contact.value,
        public_fields: publicFields,
        active: f.active.checked,
      })
    ) {
      editingServiceId = null;
      toast("服务档案已保存；公开字段将进入新简报");
    }
  };
  if ($("portfolioForm"))
    $("portfolioForm").onsubmit = async (event) => {
      event.preventDefault();
      const f = event.target.elements;
      await operate("save_portfolio", {
        id: "",
        service_id: f.service_id.value,
        title: f.title.value,
        description: f.description.value,
        role: f.role.value,
        facts: f.facts.value,
        link: f.link.value,
        public_confirmed: f.public_confirmed.checked,
        active: true,
      });
    };
  if ($("promotionBriefForm"))
    $("promotionBriefForm").onsubmit = async (event) => {
      event.preventDefault();
      const f = event.target.elements;
      const ids = [
        ...event.target.querySelectorAll('[name="portfolio_ids"]:checked'),
      ]
        .filter(
          (x) =>
            x.closest("[data-service]").dataset.service === f.service_id.value,
        )
        .map((x) => x.value);
      await operate("create_promotion_brief", {
        account_id: activeAccountId,
        service_id: f.service_id.value,
        goal: f.goal.value,
        customer_problem: f.customer_problem.value,
        problem_source: f.problem_source.value,
        portfolio_ids: ids,
      });
    };
  if ($("inquiryForm")) {
    $("inquiryForm").elements.attribution.onchange = (event) => {
      const explicit = event.target.value === "explicit";
      $("inquiryForm").elements.publication_id.required = explicit;
      if (!explicit) $("inquiryForm").elements.publication_id.value = "";
    };
    $("inquiryForm").elements.publication_id.onchange = (event) => {
      const publication = (ops.publications || []).find((row) => row.id === event.target.value);
      if (publication) $("inquiryForm").elements.source_type.value = publication.provenance;
    };
    $("inquiryForm").onsubmit = async (event) => {
      event.preventDefault();
      const f = event.target.elements;
      await operate("record_inquiry", {
        event_key: crypto.randomUUID(),
        service_id: f.service_id.value,
        publication_id:
          f.attribution.value === "explicit" ? f.publication_id.value : null,
        occurred_at: new Date(f.occurred_at.value).toISOString(),
        problem_category: f.problem_category.value,
        summary: f.summary.value,
        attribution: f.attribution.value,
        attribution_basis: f.attribution_basis.value,
        validity: f.validity.value,
        source_type: f.source_type.value,
      });
    };
  }
  if ($("promotionAnalysisForm"))
    $("promotionAnalysisForm").onsubmit = async (event) => {
      event.preventDefault();
      const f = event.target.elements;
      await operate("analyze_promotion", {
        account_id: activeAccountId,
        service_id: f.service_id.value,
        source_type: f.source_type.value,
        window_start: new Date(f.window_start.value).toISOString(),
        window_end: new Date(f.window_end.value).toISOString(),
        confirmed_complete: f.confirmed_complete.checked,
        zero_confirmed: f.zero_confirmed.checked,
      });
    };
  document
    .querySelectorAll("[data-use-promotion]")
    .forEach(
      (button) =>
        (button.onclick = () => choosePromotion(button.dataset.usePromotion)),
    );
  document
    .querySelectorAll("[data-inquiry]")
    .forEach(
      (button) =>
        (button.onclick = () =>
          operate("update_inquiry", {
            id: button.dataset.inquiry,
            validity: button.dataset.validity || "pending",
            status: button.dataset.revoke ? "revoked" : "active",
          })),
    );
}

function choosePromotion(id) {
  const brief = ops.promotion_briefs.find((row) => row.id === id);
  if (!brief || brief.status !== "active" || busy || !dirtyGuard()) return;
  chosenPromotion = brief;
  chosenTrend = null;
  chosenExperiment = null;
  showPage("studio");
  $("newRun").click();
  $("topic").value = brief.topic;
  $("audience").value = brief.audience;
  $("tone").value = currentAccount()?.profile.tone || "真实、清楚、不夸大承诺";
  $("material").value = "";
  $("workflow").value = "professional";
  $("mode").value = "simulation";
  $("mode").onchange();
  $("selectedTrend").textContent =
    `接单推广 · ${brief.goal_label} · ${brief.problem_source_label} · 服务 v${brief.service_version}`;
  $("selectedTrend").hidden = false;
  $("clearTrend").hidden = false;
}
