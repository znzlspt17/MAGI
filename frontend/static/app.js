const elements = {
    newJob: document.getElementById("new-job"),
    jobList: document.getElementById("job-list"),
    jobCount: document.getElementById("job-count"),
    title: document.getElementById("workspace-title"),
    help: document.getElementById("workspace-help"),
    notice: document.getElementById("notice"),
    form: document.getElementById("request-form"),
    request: document.getElementById("request-text"),
    generate: document.getElementById("generate-button"),
    workspace: document.getElementById("job-workspace"),
    selectedText: document.getElementById("selected-request-text"),
    usage: document.getElementById("usage-summary"),
    summary: document.getElementById("status-summary"),
    summaryStatus: document.getElementById("summary-status"),
    summaryNext: document.getElementById("summary-next"),
    summaryIssues: document.getElementById("summary-issues"),
    summaryUsage: document.getElementById("summary-usage"),
    graph: document.getElementById("execution-graph"),
    graphNote: document.getElementById("execution-note"),
    detailTitle: document.getElementById("detail-title"),
    detailStatus: document.getElementById("detail-status"),
    detailTabs: document.getElementById("detail-tabs"),
    detailContent: document.getElementById("detail-content"),
    actions: document.getElementById("job-actions"),
};

let selectedId = null,
    selectedJob = null,
    listJobs = [],
    polling = false,
    refreshPending = false,
    requestSequence = 0,
    operationBusy = false;
let navigationSequence = 0;
let eventSocket = null,
    reconnectAttempt = 0,
    reconnectTimer = null,
    connectionProblem = false;
let selectedStepId = null,
    selectedStepDetail = null,
    selectedStepSignature = "",
    selectedTab = "result",
    manualStepSelection = false,
    stepRequestSequence = 0,
    actionSignature = "",
    graphSignature = "";
let documentLanguage = "ko", documentViewMode = "rendered", documentRequestSequence = 0;
const documentTranslations = new Map();
const answerDrafts = new Map(),
    feedbackDrafts = new Map();
const sessionViews = new Map();
function rememberSession() {
    if (selectedId) sessionViews.set(selectedId, {step: selectedStepId, tab: selectedTab, manual: manualStepSelection});
}

const statusText = {
    queued: "대기 중",
    running: "실행 중",
    completed: "완료",
    waiting: "답변 필요",
    waiting_approval: "승인 대기",
    needs_revision: "보완 필요",
    blocked: "명세 보완 실패",
    failed: "오류",
    interrupted: "중단됨",
    NEEDS_USER_INPUT: "요구사항 확인 필요",
    PASS_PENDING_USER_APPROVAL: "검토 완료",
    CRITICAL_BLOCKED: "명세 보완 실패",
    FINALIZED: "최종 완료",
    error: "오류"
};
const stageText = {
    request: "요청 접수",
    generate: "요청 접수",
    interview: "요청 분석",
    await_user: "요구사항 확인 필요",
    answer: "답변 저장",
    requirement_lock: "요구사항 확정",
    revise: "수정 의견",
    spec_compile: "명세 생성",
    checklist_critic: "명세 검토",
    review_resolution: "해결 방법 판단",
    approve: "최종 승인",
    compose_candidate: "검토본 준비",
    critical_report: "명세 보완 실패 보고"
};
const normalizationErrorCodes = new Set(["REQUIREMENT_NORMALIZATION_FAILED", "SOURCE_COVERAGE_MISSING"]);

function setNotice(message, tone = "neutral") {
    const styles = {
        neutral: "border-slate-200 bg-slate-50 text-slate-600",
        success: "border-emerald-200 bg-emerald-50 text-emerald-800",
        warning: "border-amber-200 bg-amber-50 text-amber-900",
        error: "border-rose-200 bg-rose-50 text-rose-800"
    };
    elements.notice.className = `rounded-xl border px-4 py-3 text-sm ${styles[tone]}`;
    elements.notice.textContent = message;
    elements.notice.hidden = !message;
}
async function api(path, options = {}) {
    const response = await (window.MagiPublic?.fetch || fetch)(path, {
        credentials: "same-origin",
        ...options
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "요청을 처리하지 못했습니다.");
    return data;
}

function post(path, payload) {
    return api(path, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });
}

function statusLabel(status) {
    return statusText[status] || "작업 상태";
}

function isNormalizationFailure(job) {
    return job?.status === "error" && normalizationErrorCodes.has(job.error_code);
}

function displayStatus(job) {
    return isNormalizationFailure(job) ? "요구사항 정리 실패" : statusLabel(job?.status);
}

function stageLabel(node) {
    return node?.title || stageText[node?.stage] || stageText[node?.action] || "실행 단계";
}

function nodeStatus(node) {
    return statusLabel(node?.status);
}

function formatTime(value) {
    if (!value) return "기록 없음";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? "기록 없음" : date.toLocaleString("ko-KR", {
        dateStyle: "short",
        timeStyle: "short"
    });
}

function formatDuration(value) {
    if (!Number.isFinite(value)) return "확인 불가";
    if (value < 1000) return `${value}ms`;
    return `${(value / 1000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}초`;
}

function escapeText(value) {
    return typeof value === "string" ? value : "";
}

function actionableStatus(job) {
    if (!job) return undefined;
    if (isNormalizationFailure(job)) return job.error_code;
    if (job.retry_action === "revise" && (job.status === "error" || job.status === "interrupted")) return "normalization_retry";
    return job.retry_status || job.state?.status || job.status;
}

function nextAction(job) {
    if (job?.can_continue) return '이어서 요청하기';
    const status = actionableStatus(job);
    if (status === "NEEDS_USER_INPUT" || status === "waiting") return "답변 제출";
    if (status === "PASS_PENDING_USER_APPROVAL" || status === "waiting_approval") return "명세 승인 또는 수정";
    if (status === "CRITICAL_BLOCKED" || status === "blocked" || status === "needs_revision") return "수정 의견 제출";
    if (status === "normalization_retry" || isNormalizationFailure(job)) return "요구사항 다시 정리";
    if (job?.status === "running" || job?.status === "queued") return "완료 대기";
    return "작업 기록 확인";
}

function questionDetails(question, index) {
    const match = question.match(/^\[([^\]]+)\]\s*([\s\S]*)$/);
    return {
        id: match ? match[1] : `question-${index + 1}`,
        label: match && match[2] ? match[2] : question,
        raw: question
    };
}

function questionRow(rawQuestion, index, tag = "li") {
    const source = typeof rawQuestion === "string" ? rawQuestion : rawQuestion.text || rawQuestion.question || "";
    const question = questionDetails(source, index);
    const id = typeof rawQuestion === "object" && rawQuestion.question_id ? rawQuestion.question_id : question.id;
    const match = id.match(/^([A-Z][A-Z_]*?)-(\d+)$/);
    const sections = {
        PRODUCT: ["제품", "M4 7l8-4 8 4v10l-8 4-8-4V7zm0 0l8 4 8-4M12 11v10"],
        DONE: ["완료 기준", "M5 21V3m0 1h14l-3 4 3 4H5"],
        FORBIDDEN: ["보호 범위", "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3zM8 12h8"],
        FEATURE: ["기능", "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 17h6M17 14v6"],
        BUG: ["버그", "M8 9h8v7a4 4 0 01-8 0V9zM9 9V7a3 3 0 016 0v2M4 12h4M16 12h4M4 17h4M16 17h4"],
        REFACTOR: ["구조 개선", "M4 7h15l-4-4M20 17H5l4 4M19 7l-4 4M5 17l4-4"],
        INFRA: ["인프라", "M3 4h18v6H3zM3 14h18v6H3zM7 7h1M7 17h1"],
    };
    const [section, path] = sections[match?.[1]] || [match?.[1] || "질문", "M5 3h14v18H5zM9 8h6M9 12h6M9 16h4"];
    const row = documentCreate(tag, "question-row");
    const badge = documentCreate("span", "question-badge");
    badge.tabIndex = 0;
    badge.title = id;
    badge.setAttribute("aria-label", `${section} ${id}`);
    const marker = documentCreate("span", "question-marker");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.6");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const shape = document.createElementNS("http://www.w3.org/2000/svg", "path");
    shape.setAttribute("d", path);
    svg.append(shape);
    marker.append(svg, documentCreate("span", null, match?.[2] || String(index + 1).padStart(3, "0")));
    badge.append(marker, documentCreate("span", "question-section", section), documentCreate("span", "question-id", id));
    const body = documentCreate("span", "question-body");
    // 질문 문장 뒤의 안내 또는 명시적인 예시만 분리하고 원문과 식별자는 유지한다.
    const parts = question.label.match(/^([\s\S]*?[?？])\s*([\s\S]+)$/)
        || question.label.match(/^([\s\S]+?)\s*(\((?:예\s*[:：]|e\.g\.)[\s\S]+\))$/i);
    body.append(documentCreate("span", "question-title", parts ? parts[1] : question.label));
    if (parts) body.append(documentCreate("span", "question-hint", parts[2]));
    row.append(badge, body);
    return row;
}

function renderHistory() {
    elements.jobCount.textContent = String(listJobs.length);
    elements.jobList.replaceChildren();
    for (const job of listJobs) {
        const query = document.getElementById('history-query')?.value?.toLowerCase() || '';
        const status = document.getElementById('history-status')?.value;
        if (!job.request.toLowerCase().includes(query)
            || (status && (status === 'active' ? !['queued', 'running'].includes(job.status) : job.status !== status))) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = `rounded-xl px-3 py-3 text-left transition focus:outline-none focus:ring-2 focus:ring-violet-300 ${job.id === selectedId ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-900"}`;
        const title = document.createElement("span");
        title.className = "block truncate text-sm font-medium";
        title.textContent = job.request;
        const meta = document.createElement("span");
        meta.className = "mt-1 block text-xs text-slate-500";
        meta.textContent = job.status === "queued" && job.queue_position ? `${statusLabel(job.status)} · 순번 ${job.queue_position}` : displayStatus(job);
        meta.textContent += ` · ${formatTime(job.updated_at || job.created_at)}`;
        button.append(title, meta);
        button.addEventListener("click", () => selectJob(job.id));
        elements.jobList.append(button);
    }
}

function usageLabel(usage) {
    if (!usage) return "사용량: 아직 기록되지 않았습니다.";
    const token = (value) => Number.isInteger(value) ? value.toLocaleString("ko-KR") : "알 수 없음";
    const cache = usage.cache_rate || {};
    const coverage = (name) => {
        const value = usage[name];
        return Number.isInteger(value?.known_calls) && Number.isInteger(usage.successful_calls) ?
            ` (${value.known_calls}/${usage.successful_calls}개 알려짐)` : "";
    };
    const rate = typeof cache.value === "number" ? `${(cache.value * 100).toFixed(1)}%` : "알 수 없음";
    return `제공자 호출 ${Number.isInteger(usage.calls) ? usage.calls : "알 수 없음"}회 · 입력 ${token(usage.input_tokens)}${coverage("input_token_coverage")} · 출력 ${token(usage.output_tokens)}${coverage("output_token_coverage")} · OpenAI 캐시 ${token(usage.cached_tokens)} · 적중률 ${rate}${usage.recording_incomplete ? " · 일부 기록 누락" : ""}`;
}

function openIssueCount(job) {
    const graph = job?.execution_graph || {};
    const nodes = graphNodes(job);
    const counts = graph.unresolved_issue_counts || [...nodes].reverse().find((node) => node.issue_counts)?.issue_counts || {};
    return (Number(counts.blocking) || 0) + (Number(counts.major) || 0);
}

function renderHeader(job) {
    if (!job) {
        elements.title.textContent = "새 개발 요청";
        elements.help.textContent = "요청을 작성하면 검토 가능한 영어 Markdown 명세를 만듭니다.";
        elements.summary.hidden = true;
        return;
    }
    elements.title.textContent = (job.request || '대화 세션').slice(0, 80);
    elements.help.textContent = `${displayStatus(job)} · ${job.message || "작업 상태를 확인하고 있습니다."}`;
    elements.summary.hidden = false;
    elements.summaryStatus.textContent = displayStatus(job);
    elements.summaryNext.textContent = nextAction(job);
    const count = openIssueCount(job);
    elements.summaryIssues.textContent = count ? `${count}건` : "없음";
    elements.summaryUsage.textContent = job.usage ? `${job.usage.calls || 0}회` : "확인 불가";
    elements.selectedText.textContent = job.request || "";
    elements.usage.textContent = usageLabel(job.usage);
}

function legacyNodes(job) {
    const items = [{
        id: "legacy-request",
        execution_id: "legacy",
        stage: "request",
        status: "completed",
        title: "요청 접수",
        summary: job.request || "저장된 요청"
    }];
    if (job.status === "NEEDS_USER_INPUT") items.push({
        id: "legacy-wait",
        execution_id: "legacy",
        stage: "await_user",
        status: "waiting",
        title: "요구사항 확인 필요",
        summary: job.message || "답변을 기다리고 있습니다.",
        detail_available: true
    });
    else if (job.candidate || job.final || job.critical) items.push({
        id: "legacy-review",
        execution_id: "legacy",
        stage: "checklist_critic",
        status: job.status === "CRITICAL_BLOCKED" ? "blocked" : job.status === "PASS_PENDING_USER_APPROVAL" ? "waiting_approval" : job.status === "FINALIZED" ? "completed" : job.status === "error" ? "failed" : "completed",
        title: "명세 검토",
        summary: job.message || "저장된 결과",
        has_document: Boolean(job.candidate || job.final),
        has_issues: Boolean(job.critical),
        detail_available: false
    });
    return items;
}

function graphNodes(job) {
    const graph = job?.execution_graph;
    return Array.isArray(graph?.nodes) && graph.nodes.length ? graph.nodes : legacyNodes(job || {});
}

function graphIsLegacy(job) {
    return !Array.isArray(job?.execution_graph?.nodes) || job.execution_graph.legacy === true;
}

function graphIsAbsent(job) {
    return !Array.isArray(job?.execution_graph?.nodes);
}

function defaultStep(nodes) {
    // 이벤트는 단일 작업자가 실제 실행 순서대로 추가한다. 과거의 차단 노드보다
    // 뒤에 기록된 수정·재실행 단계를 현재 단계로 취급해야 한다.
    return nodes[nodes.length - 1] || null;
}

function iconFor(status) {
    return ({
        completed: "✓",
        running: "…",
        queued: "○",
        waiting: "?",
        waiting_approval: "!",
        needs_revision: "!",
        blocked: "×",
        failed: "×",
        interrupted: "—"
    })[status] || "○";
}

function renderGraph(job) {
    const nodes = graphNodes(job);
    const signature = JSON.stringify(nodes.map((node) => [node.id, node.status, node.summary, node.started_at, node.completed_at, node.issue_counts]));
    const focusedId = document.activeElement?.dataset?.stepId;
    elements.graphNote.textContent = graphIsLegacy(job) ? "이전 기록 · 상세 이력 없음" : job.execution_graph?.recording_incomplete ? "일부 이력 기록 누락" : `${nodes.length}개 단계`;
    if (signature === graphSignature) {
        elements.graph.querySelectorAll(".graph-node").forEach((button) => {
            const selected = button.dataset.stepId === selectedStepId;
            button.classList.toggle("is-selected", selected);
            button.setAttribute("aria-selected", String(selected));
        });
        return;
    }
    graphSignature = signature;
    elements.graph.replaceChildren();
    if (!nodes.length) {
        elements.graph.append(documentCreate("p", "empty-detail", "아직 기록된 실행 단계가 없습니다."));
        return;
    }
    for (let index = 0; index < nodes.length; index += 1) {
        const node = nodes[index];
        const wrap = document.createElement("div");
        wrap.className = "graph-node-wrap";
        if (index < nodes.length - 1) wrap.append(documentCreate("div", "graph-line"));
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.stepId = node.id;
        button.className = `graph-node graph-${node.status} ${node.id === selectedStepId ? "is-selected" : ""}`;
        button.setAttribute("aria-selected", String(node.id === selectedStepId));
        const icon = documentCreate("span", "graph-icon", iconFor(node.status));
        icon.setAttribute("aria-hidden", "true");
        const info = documentCreate("span", "graph-info");
        info.append(documentCreate("strong", null, stageLabel(node)), documentCreate("small", null, `${nodeStatus(node)} · ${node.completed_at ? formatTime(node.completed_at) : node.started_at ? formatTime(node.started_at) : "시각 기록 없음"}`));
        const issues = node.issue_counts || {};
        const issueTotal = (Number(issues.blocking) || 0) + (Number(issues.major) || 0);
        const badge = documentCreate("span", "graph-badge", node.status === "needs_revision" ? "보완 필요" : issueTotal ? `검토 ${issueTotal}건` : node.status === "blocked" ? "보완 실패" : nodeStatus(node));
        button.append(icon, info, badge);
        button.addEventListener("click", () => selectStep(node.id, true));
        wrap.append(button);
        elements.graph.append(wrap);
    }
    if (focusedId) {
        const focusTarget = [...elements.graph.querySelectorAll(".graph-node")].find((button) => button.dataset.stepId === focusedId);
        focusTarget?.focus({
            preventScroll: true
        });
    }
}

function nodeById(id) {
    const node = graphNodes(selectedJob).find((node) => node.id === id);
    if (node) return node;
    const completed = selectedJob?.completed_documents?.find(item => item.id === id);
    return completed ? {...completed, stage: 'completed_document', status: 'completed', detail_available: true, has_document: true} : null;
}

function stepSignature(node) {
    return JSON.stringify([
        node?.id,
        node?.status,
        node?.summary,
        node?.started_at,
        node?.completed_at,
        node?.duration_ms,
        node?.detail_available,
        node?.issue_counts,
    ]);
}
async function selectStep(stepId, manual = false) {
    if (!selectedJob || !stepId) return;
    const node = nodeById(stepId);
    if (!node) return;
    const targetJobId = selectedJob.id;
    const current = ++stepRequestSequence;
    selectedStepId = stepId;
    selectedStepSignature = stepSignature(node);
    if (manual) manualStepSelection = true;
    selectedStepDetail = null;
    renderGraph(selectedJob);
    actionSignature = "";
    renderActions(selectedJob);
    renderStepDetail(node);
    if (graphIsAbsent(selectedJob)) {
        selectedStepDetail = legacyDetail(selectedJob, node);
        renderStepDetail(node);
        return;
    }
    if (!node.detail_available) {
        selectedStepDetail = {
            unavailable: true,
            message: "이 단계의 상세 기록이 저장되지 않았습니다."
        };
        renderStepDetail(node);
        return;
    }
    try {
        const raw = await api(`/api/jobs/${encodeURIComponent(selectedJob.id)}/steps/${encodeURIComponent(stepId)}`);
        if (current !== stepRequestSequence || selectedId !== targetJobId || selectedStepId !== stepId) return;
        selectedStepDetail = raw.step || raw.detail || raw;
        renderStepDetail(node);
    } catch (error) {
        if (current !== stepRequestSequence || selectedId !== targetJobId || selectedStepId !== stepId) return;
        selectedStepDetail = {
            unavailable: true,
            message: error.message
        };
        renderStepDetail(node);
    }
}

function legacyDetail(job, node) {
    const document = job.final || job.candidate;
    return {
        result: {
            purpose: stageLabel(node),
            summary: node.summary,
            questions: job.state?.blocking_questions,
            question_forms: job.state?.question_forms,
            report: job.critical
        },
        document: document ? {
            content: document,
            filename: job.final ? "FINAL_AGENT_SPEC.md" : "approval_candidate_spec.en.md",
            kind: job.final ? "final" : "candidate"
        } : null,
        usage: job.usage
    };
}

function createTab(key, label, active) {
    const button = document.createElement("button");
    button.type = "button";
    button.role = "tab";
    button.id = `detail-tab-${key}`;
    button.setAttribute("aria-controls", "detail-content");
    button.className = active ? "is-active" : "";
    button.setAttribute("aria-selected", String(active));
    button.textContent = label;
    button.addEventListener("click", () => {
        selectedTab = key;
        renderStepDetail(nodeById(selectedStepId));
    });
    return button;
}

function renderStepDetail(node) {
    elements.detailTabs.replaceChildren();
    elements.detailContent.replaceChildren();
    if (!node) return;
    elements.detailTitle.textContent = stageLabel(node);
    elements.detailStatus.textContent = nodeStatus(node);
    const detail = selectedStepDetail;
    if (!detail) {
        elements.detailTabs.hidden = true;
        elements.detailContent.append(documentCreate('p', 'empty-detail', '단계 상세를 불러오는 중입니다.'));
        return;
    }
    const result = detail?.result || {};
    const issues = Array.isArray(result.issues) ? result.issues : Array.isArray(detail?.issues) ? detail.issues : [];
    const resolved = Array.isArray(result.resolved_issues) ? result.resolved_issues : Array.isArray(detail?.resolved_issues) ? detail.resolved_issues : [];
    const document = detail?.document;
    const tabs = [{
        key: "result",
        label: "결과"
    }];
    if (issues.length || resolved.length || result.report) tabs.push({
        key: "issues",
        label: `검토 항목${issues.length ? ` ${issues.length}` : ""}`
    });
    if (document?.content) tabs.push({
        key: "document",
        label: "명세"
    });
    const preferred = typeof window !== 'undefined' ? window.MagiWorkspace?.preferredTab() : null;
    if (preferred && tabs.some(tab => tab.key === preferred)) selectedTab = preferred;
    if (!tabs.some((tab) => tab.key === selectedTab)) selectedTab = "result";
    elements.detailContent.setAttribute("aria-labelledby", `detail-tab-${selectedTab}`);
    elements.detailTabs.hidden = false;
    for (const tab of tabs) elements.detailTabs.append(createTab(tab.key, tab.label, tab.key === selectedTab));
    if (detail.unavailable) {
        elements.detailContent.append(documentCreate("p", "empty-detail", `기록 확인 불가: ${detail.message || "상세를 불러오지 못했습니다."}`));
        return;
    }
    if (detail.recording_incomplete) {
        elements.detailContent.append(documentCreate("p", "detail-warning", "일부 상세 기록이 누락되었습니다. 표시 가능한 결과만 제공합니다."));
    }
    if (selectedTab === "issues") renderIssues(result, issues, resolved);
    else if (selectedTab === "document") renderDocument(document);
    else renderResult(node, detail, result);
}

function documentCreate(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}

function appendInlineMarkdown(target, text) {
    const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    for (const part of parts) {
        if (part.startsWith("**") && part.endsWith("**")) target.append(documentCreate("strong", null, part.slice(2, -2)));
        else if (part.startsWith("`") && part.endsWith("`")) target.append(documentCreate("code", null, part.slice(1, -1)));
        else target.append(document.createTextNode(part));
    }
}

function renderResult(node, detail, result) {
    const summary = document.createElement("dl");
    summary.className = "result-summary";
    const rows = [
        ["목적", result.purpose || stagePurpose(node)],
        ["수행 결과", result.summary || node.summary || "기록된 요약이 없습니다."],
        ["시작", formatTime(node.started_at)],
        ["완료", formatTime(node.completed_at)],
        ["소요 시간", formatDuration(node.duration_ms)]
    ];
    if (node.stage === "review_resolution") {
        rows.push(["다음 처리", { ask_user: "요구사항 확인", repair: "명세 자동 보완", stop: "보완 실패 보고", approve: "승인 후보 준비" }[result.action] || "기록 없음"]);
        rows.push(["반복 결함 진단", result.diagnosed_keys?.length ? "수행함" : "없음"]);
    }
    for (const [term, description] of rows) summary.append(documentCreate("dt", null, term), documentCreate("dd", null, description));
    elements.detailContent.append(summary);
    if (typeof result.request === "string") elements.detailContent.append(documentCreate("h4", "detail-subtitle", "원 요청"), documentCreate("p", "detail-value", result.request));
    if (Array.isArray(result.answers) && result.answers.length) {
        const list = document.createElement("ul");
        list.className = "detail-list";
        result.answers.forEach((answer) => list.append(documentCreate("li", null, `${answer.question_id ? `[${answer.question_id}] ` : ""}${answer.question || "답변"}: ${answer.answer || ""}`)));
        elements.detailContent.append(documentCreate("h4", "detail-subtitle", "저장된 답변"), list);
    }
    if (typeof result.feedback === "string" && result.feedback) elements.detailContent.append(documentCreate("h4", "detail-subtitle", "수정 의견"), documentCreate("p", "detail-value", result.feedback));
    const questions = Array.isArray(result.questions) ? result.questions : result.blocking_questions;
    if (Array.isArray(questions) && questions.length) {
        const list = document.createElement("ul");
        list.className = "question-list";
        questions.forEach((question, index) => {
            const row = questionRow(question, index);
            const questionId = typeof question === "string" ? questionDetails(question, index).id : question.question_id;
            const form = result.question_forms?.[questionId];
            if (form?.options?.length) row.append(documentCreate('span', 'question-hint', form.options.map(o => o.label).join(' · ') + ' · 직접 입력'));
            const context = reviewQuestionContext(questionId, result.review_questions);
            if (context) row.append(context);
            list.append(row);
        });
        elements.detailContent.append(documentCreate("h4", "detail-subtitle", `질문 · ${questions.length}개`), list);
    }
    const requirementGroups = requirementsByGroup(result);
    for (const [label, requirements] of requirementGroups) {
        if (!requirements.length) continue;
        const list = document.createElement("ul");
        list.className = "detail-list";
        requirements.forEach((requirement) => list.append(documentCreate("li", null, `${requirement.id ? `[${requirement.id}] ` : ""}${requirement.text || requirement}`)));
        elements.detailContent.append(documentCreate("h4", "detail-subtitle", label), list);
    }
    if (detail.usage) elements.detailContent.append(documentCreate("p", "usage-detail", usageLabel(detail.usage)));
}

function stagePurpose(node) {
    if (graphIsLegacy(selectedJob)) {
        return "저장된 현재 결과를 확인합니다. 과거 단계의 실행 이력은 없습니다.";
    }
    const purpose = {
        request: "사용자가 요청한 목표와 범위를 기록합니다.",
        generate: "새 명세 작성 작업을 시작합니다.",
        interview: "명세에 필요한 미결정을 확인합니다.",
        await_user: "명세를 확정하기 위한 답변을 기다립니다.",
        answer: "제출한 답변을 작업 기록에 저장합니다.",
        requirement_lock: "답변을 반영해 확정 요구사항을 정리합니다.",
        revise: "수정 의견을 기록하고 재검토를 준비합니다.",
        spec_compile: "확정 요구사항으로 Markdown 명세를 생성합니다.",
        checklist_critic: "명세가 요구사항과 검토 기준을 충족하는지 확인합니다.",
        approve: "검토 완료 명세를 최종 문서로 확정합니다.",
    };
    return purpose[node?.stage] || purpose[node?.action] || stageLabel(node);
}

function requirementsByGroup(result) {
    const source = result.requirements;
    if (Array.isArray(source)) return [
        ["확정 요구사항", source]
    ];
    const requirementSheet = source && typeof source === "object" ? source : result;
    return [
        ["필수 요구사항", Array.isArray(requirementSheet.mandatory_requirements) ? requirementSheet.mandatory_requirements : []],
        ["권장 요구사항", Array.isArray(requirementSheet.recommended_requirements) ? requirementSheet.recommended_requirements : []],
        ["선택 요구사항", Array.isArray(requirementSheet.optional_requirements) ? requirementSheet.optional_requirements : []],
        ["제약 조건", Array.isArray(requirementSheet.constraints) ? requirementSheet.constraints : []],
    ];
}

function issueKey(issue) {
    return `${issue?.checklist_id || ""}:${issue?.requirement_id || ""}`;
}

function issueCard(issue, lifecycle) {
    const card = document.createElement("article");
    const severity = String(issue?.severity || "minor").toLowerCase();
    const severityLabel = {
        blocking: "차단",
        critical: "차단",
        major: "중대",
        minor: "경미"
    } [severity] || "기록 없음";
    card.className = `issue-card issue-${severity}`;
    card.append(
        documentCreate("span", "issue-lifecycle", lifecycle === "resolved" ? "해소됨" : lifecycle === "persistent" ? "계속 남음" : "새 지적"),
        documentCreate("h4", null, issue?.problem || issue?.title || "검토 항목"),
    );
    const rows = [
        ["심각도", severityLabel],
        ["요구사항", issue?.requirement_id || "연결 없음"],
        ["섹션", issue?.section || "기록 없음"],
        ["결함 유형", { requirements_gap: "요구사항 미확정", spec_omission: "명세 반영 누락", verification_gap: "검증 누락", confirmed_conflict: "확정 내용 간 충돌" }[issue?.defect_kind] || "기록 없음"],
        ["해결 판단", issue?.resolution_reason || "기록 없음"],
        ["미확정 내용", issue?.missing_information || "없음"],
        ["결정 주제", issue?.decision_key || "기록 없음"],
        ["확정 근거", (issue?.basis_refs || []).join(", ") || "기록 없음"],
        ["필요한 수정", issue?.required_change || issue?.change || "기록 없음"]
    ];
    for (const [label, value] of rows) {
        const row = documentCreate("p");
        row.append(documentCreate("strong", null, `${label}: `), document.createTextNode(escapeText(value)));
        card.append(row);
    }
    const evidence = Array.isArray(issue?.evidence) ? issue.evidence : issue?.evidence ? [issue.evidence] : [];
    const evidenceTitle = documentCreate("p");
    evidenceTitle.append(documentCreate("strong", null, "근거: "));
    if (!evidence.length) evidenceTitle.append(document.createTextNode("기록 없음"));
    card.append(evidenceTitle);
    for (const item of evidence) {
        const quote = typeof item === "string" ? item : [item?.source, item?.quote].filter(Boolean).join(" · ");
        card.append(documentCreate("blockquote", "issue-evidence", quote || "기록 없음"));
    }
    card.dataset.issueKey = issueKey(issue);
    return card;
}

function renderIssues(result, issues, resolved) {
    const open = [...issues].sort((a, b) => severityRank(a) - severityRank(b));
    if (open.length) {
        const title = documentCreate("h4", "detail-subtitle", "해결이 필요한 항목");
        elements.detailContent.append(title);
        open.forEach((issue) => elements.detailContent.append(issueCard(issue, issue.lifecycle === "persistent" ? "persistent" : "new")));
    } else elements.detailContent.append(documentCreate("p", "empty-detail", "현재 단계에서 열린 검토 항목이 없습니다."));
    if (resolved.length) {
        const details = document.createElement("details");
        details.className = "resolved-issues";
        const summary = documentCreate("summary", null, `다음 검토에서 해소됨 · ${resolved.length}건`);
        details.append(summary);
        resolved.forEach((issue) => details.append(issueCard(issue, "resolved")));
        elements.detailContent.append(details);
    }
    if (result.report) {
        const details = document.createElement("details");
        details.className = "supplementary-report";
        details.append(documentCreate("summary", null, "원본 검토 보고서 보기"));
        details.append(documentCreate("pre", null, result.report));
        elements.detailContent.append(details);
    }
}

function severityRank(issue) {
    return ({
        blocking: 0,
        critical: 0,
        major: 1,
        minor: 2
    })[String(issue?.severity || "minor").toLowerCase()] ?? 3;
}

function renderDocument(documentData) {
    const controls = document.createElement("div");
    controls.className = "document-controls";
    const korean = documentCreate("button", "document-mode", "한국어");
    const english = documentCreate("button", "document-mode", "English");
    const mode = documentCreate("button", "document-mode", "문서 보기");
    const raw = documentCreate("button", "document-mode", "Markdown 보기");
    const download = documentCreate("button", "document-download", "Markdown 다운로드");
    const retry = documentCreate("button", "document-mode", "한국어본 다시 생성");
    retry.hidden = true;
    controls.append(korean, english, mode, raw, download, retry);
    for (const button of controls.children) button.type = "button";
    const note = documentCreate("p", "document-language-note");
    note.setAttribute("role", "status");
    const view = document.createElement("article");
    view.className = "markdown-view";
    const jobId = selectedJob?.id, stepId = selectedStepId;
    const source = String(documentData.content || "");
    const key = `${jobId}:${stepId}`;
    let entry = documentTranslations.get(key);
    if (!entry || entry.source !== source) {
        entry = { source, variants: { en: { ...documentData, language: "en", content: source } } };
        documentTranslations.set(key, entry);
    }
    let activeDocument = null;
    const paint = () => {
        mode.classList.toggle("is-active", documentViewMode === "rendered");
        raw.classList.toggle("is-active", documentViewMode === "raw");
        if (!activeDocument) return;
        if (documentViewMode === "raw") view.replaceChildren(documentCreate("pre", "markdown-raw", activeDocument.content));
        else renderMarkdown(view, activeDocument.content);
    };
    const loadLanguage = async (language, force = false) => {
        documentLanguage = language;
        const sequence = ++documentRequestSequence;
        const current = () => sequence === documentRequestSequence && selectedJob?.id === jobId && selectedStepId === stepId && selectedTab === "document";
        for (const [button, lang] of [[korean, "ko"], [english, "en"]]) {
            button.classList.toggle("is-active", language === lang);
            button.setAttribute("aria-pressed", String(language === lang));
        }
        activeDocument = null;
        download.disabled = true;
        retry.hidden = true;
        view.replaceChildren();
        note.textContent = language === "ko" ? "한국어본을 준비하고 있습니다. 처음 열 때 번역본을 생성하며, 이후에는 저장된 번역본을 사용합니다." : "영어 원문";
        if (force) delete entry.error;
        try {
            if (language === "ko" && !entry.variants.ko) {
                if (entry.error) throw new Error(entry.error);
                if (!entry.pending) entry.pending = api(`/api/jobs/${encodeURIComponent(jobId)}/steps/${encodeURIComponent(stepId)}/document`, {
                    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language: "ko" })
                });
                const translated = await entry.pending;
                if (typeof translated?.content !== "string" || translated.language !== "ko") throw new Error("한국어 번역본을 확인할 수 없습니다.");
                if (documentData.source_hash && translated.source_hash !== documentData.source_hash) throw new Error("원문이 변경되었습니다. 해당 단계를 다시 열어주세요.");
                entry.variants.ko = translated;
                delete entry.pending;
            }
            if (!current()) return;
            activeDocument = entry.variants[language];
            note.textContent = language === "ko" ? "한국어 번역본 · 현재 보이는 한국어본이 다운로드됩니다." : "영어 원문 · 현재 보이는 영어본이 다운로드됩니다.";
            download.disabled = false;
            paint();
        } catch (error) {
            entry.error = error.message;
            delete entry.pending;
            if (!current()) return;
            note.textContent = `한국어본을 준비하지 못했습니다. ${error.message} 영어 원문은 English에서 확인할 수 있습니다.`;
            retry.hidden = false;
        }
    };
    korean.addEventListener("click", () => loadLanguage("ko"));
    english.addEventListener("click", () => loadLanguage("en"));
    retry.addEventListener("click", () => loadLanguage("ko", true));
    mode.addEventListener("click", () => {
        documentViewMode = "rendered";
        paint();
    });
    raw.addEventListener("click", () => {
        documentViewMode = "raw";
        paint();
    });
    download.addEventListener("click", () => {
        if (!activeDocument) return;
        const blob = new Blob([activeDocument.content], {
            type: "text/markdown;charset=utf-8"
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = activeDocument.filename || `MAGI_SPEC.${documentLanguage}.md`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 0);
    });
    elements.detailContent.append(controls, note, view);
    loadLanguage(documentLanguage);
}

function renderMarkdown(container, source) {
    container.replaceChildren();
    const lines = source.replace(/\r/g, "").split("\n");
    let list = null,
        code = null,
        table = null;
    const flush = () => {
        list = null;
        code = null;
        table = null;
    };
    const inlineElement = (tag, text) => {
        const element = document.createElement(tag);
        appendInlineMarkdown(element, text);
        return element;
    };
    for (const line of lines) {
        if (line.startsWith("```")) {
            if (code) code = null;
            else {
                flush();
                code = documentCreate("pre", "markdown-code");
                code.append(document.createElement("code"));
                container.append(code);
            }
            continue;
        }
        if (code) {
            code.firstChild.textContent += `${code.firstChild.textContent ? "\n" : ""}${line}`;
            continue;
        }
        const heading = line.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
            flush();
            container.append(inlineElement(`h${heading[1].length}`, heading[2]));
            continue;
        }
        const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
        const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
        if (unordered || ordered) {
            const tag = ordered ? "ol" : "ul";
            if (!list || list.tagName.toLowerCase() !== tag) {
                flush();
                list = document.createElement(tag);
                container.append(list);
            }
            list.append(inlineElement("li", (unordered || ordered)[1]));
            continue;
        }
        // Markdown 표의 구분 행은 같은 표를 유지한 채 건너뛴다.
        if (table && /^\|(?:\s*:?-{3,}:?\s*\|)+\s*$/.test(line)) {
            continue;
        }
        if (/^\|.*\|\s*$/.test(line)) {
            if (!table) {
                flush();
                table = document.createElement("table");
                container.append(table);
            }
            const tr = document.createElement("tr");
            const cellTag = table.children.length === 0 ? "th" : "td";
            line.split("|").slice(1, -1).forEach((cell) => tr.append(inlineElement(cellTag, cell.trim())));
            table.append(tr);
            continue;
        }
        if (!line.trim()) {
            flush();
            continue;
        }
        flush();
        container.append(inlineElement("p", line));
    }
    if (!container.childNodes.length) container.append(documentCreate("p", "empty-detail", "표시할 문서가 없습니다."));
}

function applyBusyState() {
    elements.actions.querySelectorAll("button, textarea").forEach((control) => {
        control.disabled = operationBusy;
    });
}

function createButton(label, variant = "primary") {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.disabled = operationBusy;
    button.className = `inline-flex items-center justify-center rounded-xl px-4 py-3 text-sm font-semibold shadow-sm transition focus:outline-none focus:ring-4 disabled:cursor-not-allowed disabled:opacity-50 ${variant === "primary" ? "bg-violet-600 text-white hover:bg-violet-500 focus:ring-violet-200" : "bg-slate-900 text-white hover:bg-slate-700 focus:ring-slate-200"}`;
    return button;
}

function isCurrentNode() {
    const current = defaultStep(graphNodes(selectedJob));
    return selectedStepId === current?.id;
}

function questionFormDraft(job, form) {
    const key = `${job.id}:${form.question_id}:${form.form_version}`;
    if (!answerDrafts.has(key)) {
        const saved = (job.state?.saved_answers || []).find(a => a.question_id === form.question_id);
        const selection = saved?.selection;
        answerDrafts.set(key, selection?.form_version === form.form_version && Array.isArray(selection.selected_option_ids)
            ? {ids: [...selection.selected_option_ids], custom: selection.custom_text !== null, text: selection.custom_text || ''}
            : {ids: [], custom: !!saved?.answer, text: saved?.answer || ''});
    }
    return answerDrafts.get(key);
}

function appendQuestionForm(parent, job, form) {
    const group = documentCreate('fieldset', 'question-form');
    const legend = documentCreate('legend', null, form.question);
    group.append(legend);
    const context = reviewQuestionContext(form.question_id, job.state?.review_questions);
    if (context) group.append(context);
    const draft = questionFormDraft(job, form);
    const controls = [], name = `choice-${form.question_id}`;
    const text = document.createElement('textarea');
    text.rows = 3; text.maxLength = 20000; text.value = draft.text;
    text.setAttribute('aria-label', `${form.question} · 직접 입력`);
    const error = documentCreate('p', 'question-form-error');
    error.id = `question-error-${form.question_id}`; error.setAttribute('role', 'alert');
    text.setAttribute('aria-describedby', error.id);
    function sync() {
        for (const [control, id] of controls) control.checked = id === null ? draft.custom : draft.ids.includes(id);
        text.hidden = form.input_type !== 'text' && !draft.custom;
        error.textContent = '';
    }
    if (form.input_type !== 'text') {
        for (const option of [...form.options, {id: null, label: '직접 입력'}]) {
            const label = documentCreate('label', 'question-option');
            const input = document.createElement('input');
            input.type = form.input_type === 'single_choice' ? 'radio' : 'checkbox';
            input.name = name;
            input.addEventListener('change', () => {
                if (option.id === null) {
                    draft.custom = input.checked;
                    if (input.checked && form.input_type === 'single_choice') draft.ids = [];
                } else if (form.input_type === 'single_choice') {
                    draft.ids = [option.id]; draft.custom = false;
                } else draft.ids = input.checked ? [...draft.ids.filter(id => id !== option.id), option.id] : draft.ids.filter(id => id !== option.id);
                sync();
                if (option.id === null && draft.custom) text.focus();
            });
            controls.push([input, option.id]);
            label.append(input, documentCreate('span', null, option.label)); group.append(label);
        }
    }
    text.addEventListener('input', () => { draft.text = text.value; error.textContent = ''; });
    group.append(text, error); parent.append(group); sync();
}

function formAnswer(job, form) {
    const draft = questionFormDraft(job, form), custom = form.input_type === 'text' || draft.custom;
    if (custom && !draft.text.trim()) {
        if (draft.custom) {
            document.getElementById(`question-error-${form.question_id}`).textContent = '직접 입력 내용을 작성해주세요.';
            throw new Error('직접 입력 내용을 작성해주세요.');
        }
        return null;
    }
    if (!draft.ids.length && !custom) return null;
    return {question_id: form.question_id, question: form.question,
        answer: [...form.options.filter(o => draft.ids.includes(o.id)).map(o => o.label), ...(custom ? [draft.text] : [])].join('\n'),
        selected_option_ids: draft.ids, custom_text: custom ? draft.text : null, form_version: form.form_version};
}

function reviewQuestionContext(questionId, records) {
    const record = Array.isArray(records) ? records.find((item) => item.question_id === questionId) : null;
    if (!record) return null;
    const context = documentCreate("div", "question-hint");
    for (const id of record.requirement_ids || []) context.append(documentCreate("p", null, `관련 요구사항: ${id}`));
    for (const missing of record.missing_information || []) context.append(documentCreate("p", null, `미확정 내용: ${missing}`));
    for (const reason of record.resolution_reasons || []) context.append(documentCreate("p", null, `결정이 필요한 이유: ${reason}`));
    for (const problem of record.problems || []) context.append(documentCreate("p", null, `검토에서 발견한 문제: ${problem}`));
    for (const reason of record.required_changes || []) context.append(documentCreate("p", null, `확인이 필요한 이유: ${reason}`));
    for (const evidence of record.evidence || []) context.append(documentCreate("p", null, `관련 명세 (${evidence.source}): ${evidence.quote}`));
    return context;
}

function renderActions(job) {
    const currentAllowed = isCurrentNode();
    const questions = job?.state?.blocking_questions || [];
    const reviewQuestions = job?.state?.review_questions || [];
    const savedAnswers = Array.isArray(job?.state?.saved_answers) ? job.state.saved_answers : [];
    const saved = new Map(savedAnswers
        .filter((item) => typeof item?.question_id === "string" && typeof item?.answer === "string")
        .map((item) => [item.question_id, item.answer]));
    const signature = [job?.id, job?.status, job?.execution_id, job?.can_continue, selectedStepId, currentAllowed, questions.join("\0"), JSON.stringify(reviewQuestions), JSON.stringify(job?.state?.question_forms || {})].join("|");
    if (signature === actionSignature) return;
    actionSignature = signature;
    elements.actions.replaceChildren();
    if (!job || !currentAllowed || job.status === "queued" || job.status === "running") return;

    const effective = actionableStatus(job);
    if (job.read_only) {
        elements.actions.append(documentCreate('p', 'action-warning', job.continuation_error || '이 기록은 열람만 가능합니다. 새 작업을 생성하세요.'));
        return;
    }
    if (effective === "NEEDS_USER_INPUT" || effective === "waiting") {
        const section = documentCreate("section", "action-card action-answer");
        section.append(documentCreate('p', 'session-input-target', `입력 대상: ${(job.request || '').slice(0, 70)} · 질문에 답변`));
        section.append(
            documentCreate("h3", null, `${job.state?.awaiting_input_reason === "review" ? "요구사항 확인 필요" : "답변이 필요한 질문"} · ${questions.length}개`),
            documentCreate("p", null, "답변한 항목만 제출할 수 있습니다. 남은 질문은 다음 단계에서 다시 표시됩니다."),
        );
        questions.forEach((rawQuestion, index) => {
            const question = questionDetails(rawQuestion, index);
            const form = job.state?.question_forms?.[question.id];
            if (form) { appendQuestionForm(section, job, form); return; }
            const label = document.createElement("label");
            const textarea = document.createElement("textarea");
            const key = `${job.id}:${question.id}`;
            const row = questionRow(rawQuestion, index, "span");
            const inputId = `question-answer-${index}`;
            const title = row.querySelector(".question-title");
            const hint = row.querySelector(".question-hint");
            title.id = `${inputId}-title`;
            label.htmlFor = inputId;
            label.append(row);
            const context = reviewQuestionContext(question.id, reviewQuestions);
            if (context) {
                context.id = `${inputId}-context`;
                label.append(context);
            }
            textarea.id = inputId;
            textarea.setAttribute("aria-labelledby", title.id);
            if (hint) {
                hint.id = `${inputId}-hint`;
                textarea.setAttribute("aria-describedby", hint.id);
            }
            if (context) textarea.setAttribute("aria-describedby", [hint?.id, context.id].filter(Boolean).join(" "));
            textarea.rows = 3;
            textarea.maxLength = 20000;
            textarea.value = answerDrafts.has(key) ? answerDrafts.get(key) : saved.get(question.id) || "";
            textarea.addEventListener("input", () => answerDrafts.set(key, textarea.value));
            label.append(textarea);
            section.append(label);
        });
        const submit = createButton("답변 제출");
        submit.addEventListener("click", () => {
            let payload;
            try {
                payload = questions.map(questionDetails).map(question => {
                    const form = job.state?.question_forms?.[question.id];
                    if (form) return formAnswer(job, form);
                    return {question_id: question.id, question: question.raw,
                        answer: (answerDrafts.has(`${job.id}:${question.id}`) ? answerDrafts.get(`${job.id}:${question.id}`) : saved.get(question.id) || '').trim()};
                }).filter(item => item?.answer);
            } catch (error) { setNotice(error.message, 'warning'); return; }
            if (!payload.length) return setNotice("제출할 답변을 하나 이상 입력하세요.", "warning");
            performAction(job.id, "answer", payload);
        });
        section.append(submit);
        elements.actions.append(section);
        return;
    }

    if (job.status === 'FINALIZED' && !job.can_continue) {
        elements.actions.append(documentCreate('p', 'action-warning', job.continuation_error || '이 기록은 열람만 가능합니다. 새 작업을 생성하세요.'));
        return;
    }
    const continuing = Boolean(job.can_continue);
    const recovery = continuing || isNormalizationFailure(job) ||
        job.retry_action === "revise" || ["PASS_PENDING_USER_APPROVAL", "waiting_approval", "CRITICAL_BLOCKED", "blocked", "needs_revision"].includes(effective);
    if (!recovery) return;
    const section = documentCreate("section", "action-card");
    if (isNormalizationFailure(job)) {
        section.append(documentCreate("p", "action-warning", "요구사항 정리 실패: 답변 부족과는 별개인 내부 처리 문제입니다. 수정 의견을 유지해 다시 정리할 수 있습니다."));
    }
    const label = document.createElement("label");
    const textarea = document.createElement("textarea");
    label.textContent = continuing ? '이어서 요청하기' : '수정 의견 보내기';
    section.append(documentCreate('p', 'session-input-target', `입력 대상: ${(job.request || '').slice(0, 70)} · 같은 세션에서 이어집니다.`));
    textarea.rows = 4;
    textarea.maxLength = 20000;
    textarea.placeholder = continuing ? '이 세션에서 추가하거나 변경할 요구사항을 입력하세요.' : "보완할 요구사항이나 검토 의견을 작성하세요.";
    textarea.value = feedbackDrafts.get(job.id) || "";
    textarea.addEventListener("input", () => feedbackDrafts.set(job.id, textarea.value));
    label.append(textarea);
    const revise = createButton(continuing ? '이어서 요청하기' : '수정 요청', "neutral");
    revise.addEventListener("click", () => {
        const feedback = (feedbackDrafts.get(job.id) || "").trim();
        if (!feedback) return setNotice("수정 의견을 입력하세요.", "warning");
        performAction(job.id, continuing ? 'continue' : "revise", feedback);
    });
    section.append(label, revise);
    const approvalReady = !isNormalizationFailure(job) && ["PASS_PENDING_USER_APPROVAL", "waiting_approval"].includes(effective) &&
        (job.state ? job.state.status === "PASS_PENDING_USER_APPROVAL" : true);
    if (approvalReady) {
        const approve = createButton("이 명세 승인");
        approve.addEventListener("click", () => performAction(job.id, "approve", null));
        section.append(approve);
    }
    elements.actions.append(section);
}

function renderSelectedJob(job) {
    selectedJob = job;
    if (typeof window !== 'undefined') window.MagiWorkspace?.rendered(job);
    elements.form.hidden = true;
    elements.workspace.hidden = false;
    renderHeader(job);
    const nodes = graphNodes(job);
    const current = defaultStep(nodes);
    const selectedExists = Boolean(nodeById(selectedStepId));
    const shouldFollowCurrent = !manualStepSelection && current?.id !== selectedStepId;
    if (!selectedExists || shouldFollowCurrent) {
        selectedStepId = current?.id || null;
        selectedStepDetail = null;
        selectedStepSignature = "";
        if (!selectedExists) manualStepSelection = false;
    }
    const selectedNode = nodeById(selectedStepId);
    if (selectedNode && selectedStepSignature !== stepSignature(selectedNode)) {
        selectedStepDetail = null;
        selectedStepSignature = "";
    }
    renderGraph(job);
    renderActions(job);
    if (selectedStepId && !selectedStepDetail) selectStep(selectedStepId, false);
    else if (selectedStepId) renderStepDetail(nodeById(selectedStepId));
}
async function loadSelectedJob() {
    if (!selectedId) return;
    const target = selectedId,
        sequence = ++requestSequence,
        job = await api(`/api/jobs/${encodeURIComponent(target)}`);
    if (sequence !== requestSequence || selectedId !== target) return;
    renderSelectedJob(job);
}
async function selectJob(id) {
    if (id === selectedId) return;
    navigationSequence++;
    rememberSession();
    selectedId = id;
    if (window.MagiPublic?.public && location.pathname !== `/jobs/${id}`) history.pushState({},'',`/jobs/${id}`);
    selectedJob = null;
    selectedStepId = null;
    selectedStepDetail = null;
    selectedStepSignature = "";
    stepRequestSequence += 1;
    manualStepSelection = false;
    selectedTab = "result";
    const savedView = sessionViews.get(id);
    if (savedView) { selectedStepId = savedView.step; selectedTab = savedView.tab; manualStepSelection = savedView.manual; }
    actionSignature = "";
    renderHistory();
    setNotice("", "neutral");
    try {
        await loadSelectedJob();
    } catch (error) {
        if (selectedId === id) setNotice(error.message, "error");
    }
}
async function performAction(id, action, payload) {
    if (operationBusy) return;
    operationBusy = true;
    renderActions(selectedJob);
    applyBusyState();
    try {
        await post(`/api/jobs/${encodeURIComponent(id)}/${action}`, {
            payload, execution_id: selectedJob?.execution_id
        });
        if (action === 'continue' || action === 'revise') feedbackDrafts.delete(id);
        if (action === 'answer') for (const item of payload) {
            answerDrafts.delete(`${id}:${item.question_id}`);
            if (item.form_version) answerDrafts.delete(`${id}:${item.question_id}:${item.form_version}`);
        }
        if (selectedId === id) setNotice("작업을 대기열에 넣었습니다.", "success");
        actionSignature = "";
        if (selectedId === id) { manualStepSelection = false; selectedStepDetail = null; }
        await refresh();
    } catch (error) {
        setNotice(error.message, "error");
    } finally {
        operationBusy = false;
        actionSignature = "";
        renderActions(selectedJob);
        applyBusyState();
    }
}
async function refresh() {
    if (polling) {
        refreshPending = true;
        return;
    }
    polling = true;
    try {
        listJobs = await api("/api/jobs");
        renderHistory();
        if (selectedId) await loadSelectedJob();
    } catch (error) {
        setNotice(error.message, "error");
    } finally {
        polling = false;
        if (refreshPending) {
            refreshPending = false;
            refresh();
        }
    }
}

function connectEvents() {
    if (window.MagiPublic?.public && !window.MagiPublic.authenticated) return;
    if (eventSocket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(eventSocket.readyState)) return;
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    eventSocket = new WebSocket(`${scheme}://${window.location.host}/ws/events`);
    eventSocket.addEventListener("open", () => refresh());
    eventSocket.addEventListener("message", (message) => {
        let event;
        try {
            event = JSON.parse(message.data);
        } catch {
            return;
        }
        if (event.event === "ready") {
            reconnectAttempt = 0;
            if (connectionProblem) {
                connectionProblem = false;
                setNotice("", "neutral");
            }
            refresh();
        } else if (event.event === "job.changed") refresh();
        else if (event.event === 'records.deleted') {
            window.MagiWorkspace?.deleted(event.ids || []);
            refresh();
        }
        else if (event.event === 'service.status') window.MagiPublic?.renderStatus(event.status);
        else if (event.event === "server_error") {
            connectionProblem = true;
            setNotice("작업 서버 연결이 끊어졌습니다. 작업 기록을 확인하세요.", "warning");
            eventSocket?.close();
        }
    });
    eventSocket.addEventListener("close", () => {
        eventSocket = null;
        if (window.MagiPublic?.public && !window.MagiPublic.authenticated) return;
        if (!connectionProblem) {
            connectionProblem = true;
            setNotice("작업 서버 연결이 끊어졌습니다. 작업 기록을 확인하세요.", "warning");
        }
        const delays = [1000, 2000, 4000, 8000, 10000];
        const delay = delays[Math.min(reconnectAttempt, delays.length - 1)];
        reconnectAttempt += 1;
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connectEvents, delay);
    });
    eventSocket.addEventListener("error", () => eventSocket?.close());
}
elements.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (operationBusy) return;
    const request = elements.request.value.trim();
    if (!request) {
        setNotice("개발 요청을 입력하세요.", "warning");
        elements.request.focus();
        return;
    }
    operationBusy = true;
    elements.generate.disabled = true;
    const submittedNavigation = navigationSequence;
    try {
        const job = await post("/api/jobs", {
            request,
            provider: "openai",
            project_id: null
        });
        if (submittedNavigation === navigationSequence) {
            selectedId = job.id;
            selectedJob = null;
            selectedStepId = null;
            selectedStepDetail = null;
            selectedStepSignature = "";
            stepRequestSequence += 1;
            manualStepSelection = false;
            actionSignature = "";
            elements.request.value = "";
            if (window.MagiPublic?.authenticated) {
                sessionStorage.removeItem(`magi:draft:${window.MagiPublic.user.id}`);
                history.pushState({},'',`/jobs/${job.id}`);
            }
            setNotice("새 작업을 대기열에 넣었습니다.", "success");
        }
        await refresh();
    } catch (error) {
        setNotice(error.message, "error");
    } finally {
        operationBusy = false;
        elements.generate.disabled = false;
    }
});
elements.newJob.addEventListener("click", () => {
    if (window.MagiPublic?.public) history.pushState({},'','/');
    navigationSequence++;
    rememberSession();
    selectedId = null;
    selectedJob = null;
    selectedStepId = null;
    selectedStepDetail = null;
    selectedStepSignature = "";
    stepRequestSequence += 1;
    documentRequestSequence += 1;
    documentTranslations.clear();
    manualStepSelection = false;
    requestSequence += 1;
    actionSignature = "";
    elements.form.reset();
    elements.form.hidden = false;
    elements.workspace.hidden = true;
    elements.summary.hidden = true;
    elements.title.textContent = "새 개발 요청";
    elements.help.textContent = "요청을 작성하면 검토 가능한 영어 Markdown 명세를 만듭니다.";
    setNotice("", "neutral");
    renderHistory();
    elements.request.focus();
});
async function startWorkspace() {
    if (window.MagiPublic) {
        await window.MagiPublic.ready;
        if (window.MagiPublic.public && !window.MagiPublic.authenticated) return;
        const match = location.pathname.match(/^\/jobs\/([0-9a-f]{32})$/);
        if (match) selectedId = match[1];
    }
    connectEvents();
    refresh();
}
window.addEventListener('popstate', () => {
    const match = location.pathname.match(/^\/jobs\/([0-9a-f]{32})$/);
    if (match) selectJob(match[1]);
    else { selectedId=null; elements.workspace.hidden=true; elements.form.hidden=false; elements.summary.hidden=true; }
});
document.addEventListener('magi:signed-out', () => {
    clearTimeout(reconnectTimer); eventSocket?.close(); eventSocket=null;
    listJobs=[]; selectedId=null; selectedJob=null;
    sessionViews.clear(); answerDrafts.clear(); feedbackDrafts.clear(); documentTranslations.clear();
    elements.jobList.replaceChildren(); elements.detailContent.replaceChildren();
    elements.actions.replaceChildren(); document.getElementById('session-events').replaceChildren();
});
startWorkspace();
