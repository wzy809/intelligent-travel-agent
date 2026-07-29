const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8000" : window.location.origin;
const TOTAL_QUESTIONS = 9;

let sessionId = null;
let currentQuestion = null;
let questionIndex = 0;
let activePlan = "smooth";
let plansPayload = null;
let isRevisionMode = false;

const $ = (selector) => document.querySelector(selector);

async function apiPost(path, payload) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || data.error || "请求失败");
  }
  return data;
}

function showView(id) {
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  $(id).classList.add("active");
}

function addMessage(role, text, mode = "") {
  const message = document.createElement("div");
  message.className = `message ${role} ${mode}`;
  message.textContent = text;
  $("#chatLog").appendChild(message);
  $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
}

function getImportMode() {
  return document.querySelector(".import-tab.active")?.dataset.mode || "text";
}

function getSourcePayload() {
  const mode = getImportMode();
  if (mode === "image") {
    const file = $("#screenshotInput").files[0];
    return {
      type: "image",
      filename: file?.name || "",
      content: file ? `截图文件：${file.name}` : "",
      extracted_text: ""
    };
  }
  if (mode === "link") {
    const url = $("#linkInput").value.trim();
    return {
      type: "link",
      url,
      content: url
    };
  }
  return {
    type: "text",
    content: $("#startInput").value.trim()
  };
}

function getInitialInput() {
  const mode = getImportMode();
  if (mode === "link") {
    return $("#linkInput").value.trim();
  }
  if (mode === "image") {
    const file = $("#screenshotInput").files[0];
    return file ? `我上传了一张旅行收藏截图：${file.name}` : "";
  }
  return $("#startInput").value.trim();
}

function renderQuestion(question) {
  currentQuestion = question;
  $("#progressFill").style.width = `${Math.min(((questionIndex + 1) / TOTAL_QUESTIONS) * 100, 100)}%`;
  addMessage("agent", question.text);
  $("#quickReplies").innerHTML = question.quick_replies
    .map((reply) => `<button type="button" data-reply="${reply}">${reply}</button>`)
    .join("");
  $("#replyInput").placeholder = "也可以直接输入你的回答";
}

function confidenceClass(label) {
  if (label === "已确认") return "ok";
  if (label === "待确认") return "warn";
  return "risk";
}

function getPlanNotice(plan) {
  const diagnostic = plansPayload?.diagnostics?.[0];
  if (diagnostic) {
    return `${diagnostic.title}：${diagnostic.message}`;
  }
  return plan.summary || "已根据你的偏好生成路线。";
}

function renderPlans() {
  const plans = plansPayload?.plans || [];
  const plan = plans.find((item) => item.id === activePlan) || plans[0];
  if (!plan) return;

  $("#planTabs").innerHTML = plans
    .map(
      (item) => `
        <button class="plan-tab ${item.id === plan.id ? "active" : ""}" data-plan="${item.id}">
          ${item.role === "recommended" ? "推荐 · " : "备选 · "}${item.name}
        </button>
      `
    )
    .join("");

  $("#noticeTitle").textContent = `已按你的节奏优先展示：${plan.name}`;
  $(".notice-card p").textContent = getPlanNotice(plan);
  $("#dayPlans").innerHTML = plan.days
    .map(
      (day) => `
        <article class="day-card">
          <header>
            <div>
              <h3>${day.day} · ${day.title}</h3>
              <p>按区域顺路安排，并预留交通与休息时间。</p>
            </div>
            <span class="tag">${day.strength}</span>
          </header>
          <div class="place-list">
            ${day.items
              .map(
                (item) => `
                  <section class="place-card">
                    <div class="time">${item.time}</div>
                    <div>
                      <h4>${item.name}</h4>
                      <p>${item.note}</p>
                      <span class="confidence ${confidenceClass(item.confidence.label)}">${item.confidence.label}</span>
                    </div>
                  </section>
                `
              )
              .join("")}
          </div>
        </article>
      `
    )
    .join("");
}

async function importPlaces(source) {
  const payload =
    source.type === "image"
      ? {
          filename: source.filename,
          content: source.content,
          extracted_text: source.extracted_text
        }
      : source.type === "link"
        ? { url: source.url, content: source.content }
        : { content: source.content };
  return apiPost(`/api/import/${source.type}`, payload);
}

async function startPlanning() {
  const initialInput = getInitialInput();
  const source = getSourcePayload();
  $("#chatLog").innerHTML = "";
  $("#quickReplies").innerHTML = "";
  $("#replyInput").value = "";
  $("#progressFill").style.width = "0%";
  questionIndex = 0;
  isRevisionMode = false;
  $("#confirmBtn").textContent = "确认行程";
  $("#confirmBtn").disabled = false;
  showView("#chatView");
  addMessage("user", initialInput || "我想规划一次自由行。");

  try {
    addMessage("agent", "我正在识别你的收藏来源，并创建旅行规划会话。");
    const imported = await importPlaces(source);
    const recognizedCount = imported.recognized_places?.length || 0;
    if (recognizedCount > 0) {
      addMessage("agent", `已识别 ${recognizedCount} 个收藏地点。接下来我会补齐关键信息。`);
    } else if (source.type === "image") {
      addMessage("agent", "截图已收到。当前 Demo 还没有接真实 OCR，我会先通过追问补齐地点信息。");
    } else {
      addMessage("agent", imported.message || "我会通过追问补齐地点信息。");
    }

    const created = await apiPost("/api/sessions", {
      initial_input: initialInput,
      source
    });
    sessionId = created.session_id;
    renderQuestion(created.next_question);
  } catch (error) {
    addMessage("system", `后端连接失败：${error.message}。请先启动后端服务：python server.py`);
  }
}

async function submitAnswer(text) {
  const value = text.trim();
  if (!value) return;
  addMessage("user", value);
  $("#replyInput").value = "";

  if (isRevisionMode) {
    await revisePlan(value);
    return;
  }

  if (!sessionId || !currentQuestion) {
    addMessage("system", "当前会话不存在，请返回首页重新开始。");
    return;
  }

  try {
    const result = await apiPost(`/api/sessions/${sessionId}/answers`, { answer: value });
    questionIndex += 1;
    if (!result.is_complete && result.next_question) {
      renderQuestion(result.next_question);
      return;
    }

    $("#quickReplies").innerHTML = "";
    $("#progressFill").style.width = "100%";
    addMessage("system", "信息已完整。我会保留必去地点，检查相似景点、距离、营业时间和价格置信状态。");
    plansPayload = await apiPost(`/api/sessions/${sessionId}/plans`, {});
    activePlan = plansPayload.recommended_plan_id;
    renderPlans();
    isRevisionMode = true;
    setTimeout(() => showView("#resultView"), 500);
  } catch (error) {
    addMessage("system", `提交失败：${error.message}`);
  }
}

async function revisePlan(instruction) {
  if (!sessionId) {
    addMessage("system", "当前会话不存在，请返回首页重新开始。");
    return;
  }
  try {
    const revised = await apiPost(`/api/sessions/${sessionId}/revise`, {
      instruction,
      plan_id: activePlan
    });
    plansPayload = revised;
    activePlan = revised.recommended_plan_id;
    addMessage("agent", revised.revision_summary);
    renderPlans();
    showView("#resultView");
  } catch (error) {
    addMessage("system", `修改失败：${error.message}`);
  }
}

async function confirmPlan() {
  if (!sessionId) {
    $("#confirmBtn").textContent = "请先规划";
    return;
  }
  try {
    await apiPost(`/api/sessions/${sessionId}/confirm`, { plan_id: activePlan });
    $("#confirmBtn").textContent = "已确认";
    $("#confirmBtn").disabled = true;
  } catch (error) {
    $("#confirmBtn").textContent = "确认失败";
    setTimeout(() => {
      $("#confirmBtn").textContent = "确认行程";
    }, 1600);
  }
}

$("#startBtn").addEventListener("click", startPlanning);
$("#startInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    startPlanning();
  }
});

$("#replyBtn").addEventListener("click", () => submitAnswer($("#replyInput").value));

$("#replyInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    submitAnswer($("#replyInput").value);
  }
});

$("#quickReplies").addEventListener("click", (event) => {
  if (event.target.matches("button")) {
    submitAnswer(event.target.dataset.reply);
  }
});

document.addEventListener("click", (event) => {
  if (event.target.matches(".import-tab")) {
    const mode = event.target.dataset.mode;
    document.querySelectorAll(".import-tab").forEach((tab) => tab.classList.remove("active"));
    event.target.classList.add("active");
    $("#startInput").classList.toggle("hidden", mode !== "text");
    $("#imageImport").classList.toggle("hidden", mode !== "image");
    $("#linkImport").classList.toggle("hidden", mode !== "link");
  }
  if (event.target.matches(".plan-tab")) {
    activePlan = event.target.dataset.plan;
    renderPlans();
  }
});

$("#screenshotInput").addEventListener("change", () => {
  const file = $("#screenshotInput").files[0];
  $("#screenshotStatus").textContent = file
    ? `已选择截图：${file.name}。Demo 会把文件名发给后端，后续可接 OCR 服务识别图片内容。`
    : "上传小红书、抖音、携程截图后，Demo 会模拟识别其中的地点。";
});

$("#backHomeBtn").addEventListener("click", () => showView("#homeView"));
$("#backChatBtn").addEventListener("click", () => showView("#chatView"));
$("#adjustBtn").addEventListener("click", () => {
  showView("#chatView");
  addMessage("agent", "你可以继续说：第二天太累、两个夜景点都要去、预算降一点，或者不要早起。我会调用后端重新调整方案。");
});
$("#confirmBtn").addEventListener("click", confirmPlan);
