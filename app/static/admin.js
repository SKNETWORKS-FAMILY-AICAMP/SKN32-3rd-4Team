(() => {
  "use strict";

  const REFRESH_INTERVAL_MS = 30_000;

  const state = {
    orders: [],
    events: [],
    knowledgeGaps: [],
    indexStatus: null,
    loading: false,
    refreshTimer: null
  };

  const elements = {};

  const ORDER_STATUS_LABELS = {
    pending: "대기",
    paid: "결제 완료",
    confirmed: "주문 확인",
    processing: "처리 중",
    shipped: "배송 중",
    delivered: "배송 완료",
    completed: "완료",
    cancelled: "취소",
    canceled: "취소",
    refunded: "환불",
    failed: "실패"
  };

  document.addEventListener("DOMContentLoaded", initialize);

  function initialize() {
    cacheElements();
    bindEvents();
    bindLoginEvents();
    synchronizeAuthentication();

    if (hasToken()) {
      refreshDashboard();
      startAutoRefresh();
    }
  }

  function cacheElements() {
    elements.refreshButton = document.getElementById("refreshButton");
    elements.reportButton = document.getElementById("reportButton");
    elements.printButton = document.getElementById("printButton");
    elements.lastUpdated = document.getElementById("lastUpdated");
    elements.authNotice = document.getElementById("authNotice");
    elements.errorBanner = document.getElementById("errorBanner");
    elements.errorMessage = document.getElementById("errorMessage");
    elements.dismissErrorButton =
      document.getElementById("dismissErrorButton");

    elements.readinessCard = document.getElementById("readinessCard");
    elements.readinessValue = document.getElementById("readinessValue");
    elements.readinessDescription =
      document.getElementById("readinessDescription");
    elements.componentStatuses =
      document.getElementById("componentStatuses");

    elements.orderCount = document.getElementById("orderCount");
    elements.unresolvedGapCount =
      document.getElementById("unresolvedGapCount");
    elements.gapSummaryCard =
      document.getElementById("gapSummaryCard");

    elements.ordersPanelCount =
      document.getElementById("ordersPanelCount");
    elements.ordersTableBody =
      document.getElementById("ordersTableBody");

    elements.eventsPanelCount =
      document.getElementById("eventsPanelCount");
    elements.eventTimeline =
      document.getElementById("eventTimeline");

    elements.gapStatusFilter =
      document.getElementById("gapStatusFilter");
    elements.gapSearchInput =
      document.getElementById("gapSearchInput");
    elements.gapsPanelCount =
      document.getElementById("gapsPanelCount");
    elements.knowledgeGapList =
      document.getElementById("knowledgeGapList");

    elements.adminUsername = document.getElementById("adminUsername");
    elements.adminPassword = document.getElementById("adminPassword");
    elements.adminLoginBtn = document.getElementById("adminLoginBtn");
    elements.logoutBtn = document.getElementById("logoutBtn");
    elements.loginStatus = document.getElementById("loginStatus");

    elements.loggedOutGate = document.getElementById("loggedOutGate");
    elements.dashboardHeader = document.getElementById("dashboardHeader");
    elements.dashboardMain = document.getElementById("dashboardMain");
  }

  /*
   * 로그인/로그아웃 — 이 프로젝트 공용 common.js(setAuth/clearAuth/apiFetch)를 그대로 쓴다.
   * 성공하면 auth:changed 이벤트를 쏴서 대시보드가 폴링을 기다리지 않고 바로 새로고침한다.
   */
  function bindLoginEvents() {
    if (elements.adminLoginBtn) {
      elements.adminLoginBtn.addEventListener("click", handleLogin);
    }
    if (elements.logoutBtn) {
      elements.logoutBtn.addEventListener("click", handleLogout);
    }
  }

  async function handleLogin() {
    const username = (elements.adminUsername.value || "").trim();
    const password = elements.adminPassword.value || "";
    elements.adminLoginBtn.disabled = true;

    try {
      // 공통 헬퍼: 얼굴 등록 계정이면 웹캠 2차 인증 오버레이까지 처리하고 최종 토큰을 준다.
      await submitLogin(username, password);
      elements.loginStatus.textContent = `로그인됨: ${username}`;
      elements.loginStatus.style.color = "var(--success)";
      document.dispatchEvent(new CustomEvent("auth:changed"));
      maybePromptFaceEnroll();
    } catch (err) {
      elements.loginStatus.textContent = err.message || "로그인 실패";
      elements.loginStatus.style.color = "var(--danger)";
    } finally {
      elements.adminLoginBtn.disabled = false;
    }
  }

  // 관리자 얼굴 등록 유도: 로그인 후 얼굴 미등록이면 마이페이지 등록을 안내(무강제).
  async function maybePromptFaceEnroll() {
    try {
      const { ok, body } = await apiFetch("/api/face/status", { headers: authHeaders() });
      if (ok && body && body.registered === false) {
        elements.loginStatus.innerHTML =
          `로그인됨 · <strong>얼굴 미등록</strong> — ` +
          `<a href="/static/mypage.html">마이페이지에서 얼굴을 등록</a>하면 다음 로그인부터 2차 인증이 적용됩니다.`;
        elements.loginStatus.style.color = "var(--warning)";
      }
    } catch { /* 상태 조회 실패는 무시(로그인 자체는 성공) */ }
  }

  function handleLogout() {
    clearAuth();
    elements.loginStatus.textContent = "로그아웃됨";
    elements.loginStatus.style.color = "var(--muted)";
    document.dispatchEvent(new CustomEvent("auth:changed"));
  }

  async function downloadReport() {
    elements.reportButton.disabled = true;
    try {
      const resp = await fetch("/api/admin/report", { headers: authHeaders() });
      if (!resp.ok) {
        handlePossibleAuthenticationError({ status: resp.status });
        showError(`보고서 생성 실패 (HTTP ${resp.status})`);
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "admin_report.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      showError("보고서 요청 실패: " + err.message);
    } finally {
      elements.reportButton.disabled = false;
    }
  }

  function bindEvents() {
    elements.refreshButton.addEventListener("click", () => {
      refreshDashboard();
    });
    elements.reportButton.addEventListener("click", downloadReport);
    elements.printButton.addEventListener("click", () => window.print());

    elements.dismissErrorButton.addEventListener("click", hideError);

    elements.gapStatusFilter.addEventListener(
      "change",
      renderKnowledgeGaps
    );

    elements.gapSearchInput.addEventListener(
      "input",
      renderKnowledgeGaps
    );

    window.addEventListener("storage", handleAuthenticationChange);
    window.addEventListener("focus", handleAuthenticationChange);

    document.addEventListener(
      "auth:changed",
      handleAuthenticationChange
    );

    /*
     * 기존 로그인 폼이 페이지 안에 있는 경우, 기존 submit 핸들러를
     * 방해하지 않고 토큰 저장 이후 대시보드를 자동 갱신한다.
     */
    const loginForm = document.querySelector(
      "#loginForm, #login-form, [data-login-form]"
    );

    if (loginForm) {
      loginForm.addEventListener("submit", () => {
        window.setTimeout(handleAuthenticationChange, 500);
        window.setTimeout(handleAuthenticationChange, 1200);
      });
    }
  }

  function hasToken() {
    return typeof getToken === "function" && Boolean(getToken());
  }

  function synchronizeAuthentication() {
    const authenticated = hasToken();

    // 토큰이 없으면 대시보드 본문(헤더+패널) 자체를 렌더링하지 않는다 — 로그인 전
    // "확인 중" 같은 빈 카드가 마치 동작 중인 것처럼 보이는 걸 막는다(무폴백: 미인증 상태를
    // 스켈레톤 UI로 가리지 않고 명시적인 로그인 게이트로 보여준다).
    elements.loggedOutGate.hidden = authenticated;
    elements.dashboardHeader.hidden = !authenticated;
    elements.dashboardMain.hidden = !authenticated;

    elements.authNotice.hidden = authenticated;
    elements.refreshButton.disabled = !authenticated || state.loading;

    return authenticated;
  }

  function handleAuthenticationChange() {
    const authenticated = synchronizeAuthentication();

    if (authenticated) {
      refreshDashboard();
      startAutoRefresh();
    } else {
      stopAutoRefresh();
      showAuthenticationRequired();
    }
  }

  function startAutoRefresh() {
    stopAutoRefresh();

    state.refreshTimer = window.setInterval(() => {
      if (
        hasToken() &&
        !state.loading &&
        document.visibilityState === "visible"
      ) {
        refreshDashboard({ silent: true });
      }
    }, REFRESH_INTERVAL_MS);
  }

  function stopAutoRefresh() {
    if (state.refreshTimer !== null) {
      window.clearInterval(state.refreshTimer);
      state.refreshTimer = null;
    }
  }

  async function refreshDashboard({ silent = false } = {}) {
    if (state.loading) {
      return;
    }

    if (!hasToken()) {
      showAuthenticationRequired();
      return;
    }

    state.loading = true;
    elements.refreshButton.disabled = true;
    elements.refreshButton.textContent = "갱신 중";

    if (!silent) {
      hideError();
    }

    const requests = await Promise.allSettled([
      fetchApi("/api/admin/index"),
      fetchApi("/api/admin/orders"),
      fetchApi("/api/admin/events"),
      fetchApi("/api/admin/knowledge-gaps")
    ]);

    const [
      indexResult,
      ordersResult,
      eventsResult,
      gapsResult
    ] = requests;

    const failures = [];

    if (indexResult.status === "fulfilled") {
      state.indexStatus = normalizeObject(indexResult.value);
      renderReadiness();
    } else {
      state.indexStatus = null;
      renderReadinessError();
      failures.push("준비 상태");
      handlePossibleAuthenticationError(indexResult.reason);
    }

    if (ordersResult.status === "fulfilled") {
      state.orders = normalizeList(ordersResult.value, "orders");
      renderOrders();
    } else {
      state.orders = [];
      renderOrdersError();
      failures.push("주문");
      handlePossibleAuthenticationError(ordersResult.reason);
    }

    if (eventsResult.status === "fulfilled") {
      state.events = normalizeList(eventsResult.value, "events");
      renderEvents();
    } else {
      state.events = [];
      renderEventsError();
      failures.push("이벤트");
      handlePossibleAuthenticationError(eventsResult.reason);
    }

    if (gapsResult.status === "fulfilled") {
      state.knowledgeGaps = normalizeList(
        gapsResult.value,
        "knowledge_gaps",
        "knowledgeGaps",
        "gaps"
      );
      renderKnowledgeGaps();
      renderGapSummary();
    } else {
      state.knowledgeGaps = [];
      renderKnowledgeGapsError();
      renderGapSummaryError();
      failures.push("지식갭");
      handlePossibleAuthenticationError(gapsResult.reason);
    }

    state.loading = false;
    elements.refreshButton.disabled = !hasToken();
    elements.refreshButton.textContent = "새로고침";

    if (failures.length > 0) {
      showError(
        `${failures.join(", ")} 데이터를 불러오지 못했습니다.`
      );
    }

    if (requests.some((result) => result.status === "fulfilled")) {
      elements.lastUpdated.textContent =
        `마지막 갱신 ${formatDateTime(new Date())}`;
    }
  }

  async function fetchApi(path) {
    if (typeof apiFetch !== "function") {
      throw new Error("common.js의 apiFetch를 찾을 수 없습니다.");
    }

    const headers =
      typeof authHeaders === "function"
        ? authHeaders()
        : {
            Authorization: `Bearer ${getToken()}`
          };

    // 이 프로젝트의 apiFetch(common.js)는 {status, ok, body}를 반환한다
    // (fetch Response도, .json()이 있는 객체도 아니다 — 항상 이 형태로 온다).
    const result = await apiFetch(path, {
      method: "GET",
      headers
    });

    if (!result || !result.ok) {
      const status = result ? result.status : 0;
      const error = new Error(`API 요청 실패: HTTP ${status}`);
      error.status = status;
      throw error;
    }

    return result.body;
  }

  function normalizeObject(payload) {
    if (!payload || typeof payload !== "object") {
      return {};
    }

    if (
      payload.data &&
      !Array.isArray(payload.data) &&
      typeof payload.data === "object"
    ) {
      return payload.data;
    }

    return payload;
  }

  function normalizeList(payload, ...candidateKeys) {
    if (Array.isArray(payload)) {
      return payload;
    }

    if (!payload || typeof payload !== "object") {
      return [];
    }

    if (Array.isArray(payload.data)) {
      return payload.data;
    }

    const root =
      payload.data &&
      typeof payload.data === "object" &&
      !Array.isArray(payload.data)
        ? payload.data
        : payload;

    for (const key of candidateKeys) {
      if (Array.isArray(root[key])) {
        return root[key];
      }
    }

    if (Array.isArray(root.items)) {
      return root.items;
    }

    if (Array.isArray(root.results)) {
      return root.results;
    }

    return [];
  }

  function renderReadiness() {
    const index = state.indexStatus || {};
    const ready = toBoolean(index.ready);
    const databaseReady = toBoolean(index.db_tables_ready);
    const vectorReady = toBoolean(index.vector_index_ready);
    const missingTables = Array.isArray(index.missing_tables)
      ? index.missing_tables
      : [];

    clearCardState(elements.readinessCard);

    if (ready) {
      elements.readinessCard.classList.add("is-success");
      elements.readinessValue.textContent = "정상 운영";
      elements.readinessDescription.textContent =
        "데이터베이스와 벡터 인덱스가 모두 준비되었습니다.";
    } else {
      elements.readinessCard.classList.add("is-warning");
      elements.readinessValue.textContent = "점검 필요";

      elements.readinessDescription.textContent =
        missingTables.length > 0
          ? `누락 테이블: ${missingTables.join(", ")}`
          : "일부 백엔드 구성요소가 아직 준비되지 않았습니다.";
    }

    elements.componentStatuses.replaceChildren(
      createComponentChip("데이터베이스", databaseReady),
      createComponentChip("벡터 인덱스", vectorReady)
    );
  }

  function renderReadinessError() {
    clearCardState(elements.readinessCard);
    elements.readinessCard.classList.add("is-danger");
    elements.readinessValue.textContent = "확인 실패";
    elements.readinessDescription.textContent =
      "인덱스 상태 API에 연결할 수 없습니다.";

    elements.componentStatuses.replaceChildren(
      createComponentChip("데이터베이스", null),
      createComponentChip("벡터 인덱스", null)
    );
  }

  function createComponentChip(label, ready) {
    const chip = document.createElement("span");
    chip.className = "component-chip";

    if (ready === true) {
      chip.classList.add("is-ready");
      chip.textContent = `${label} 준비`;
    } else if (ready === false) {
      chip.classList.add("is-not-ready");
      chip.textContent = `${label} 미준비`;
    } else {
      chip.textContent = `${label} 확인 불가`;
    }

    return chip;
  }

  function clearCardState(card) {
    card.classList.remove("is-success", "is-warning", "is-danger");
  }

  function renderOrders() {
    const orders = [...state.orders];

    elements.orderCount.textContent =
      formatInteger(orders.length);
    elements.ordersPanelCount.textContent =
      `${formatInteger(orders.length)}건`;

    elements.ordersTableBody.replaceChildren();

    if (orders.length === 0) {
      elements.ordersTableBody.appendChild(
        createTableMessage("표시할 주문이 없습니다.")
      );
      return;
    }

    const fragment = document.createDocumentFragment();

    for (const order of orders) {
      const row = document.createElement("tr");

      row.appendChild(
        createCell(
          valueOrFallback(order.order_no),
          "order-number"
        )
      );

      row.appendChild(
        createCell(valueOrFallback(order.user_id))
      );

      const statusCell = document.createElement("td");
      statusCell.appendChild(createOrderStatusBadge(order.status));
      row.appendChild(statusCell);

      row.appendChild(
        createCell(
          formatInteger(toFiniteNumber(order.item_count, 0))
        )
      );

      row.appendChild(
        createCell(formatCurrency(order.total_amount))
      );

      fragment.appendChild(row);
    }

    elements.ordersTableBody.appendChild(fragment);
  }

  function renderOrdersError() {
    elements.orderCount.textContent = "-";
    elements.ordersPanelCount.textContent = "불러오기 실패";
    elements.ordersTableBody.replaceChildren(
      createTableMessage("주문 데이터를 불러오지 못했습니다.")
    );
  }

  function createCell(value, className = "") {
    const cell = document.createElement("td");
    cell.textContent = String(value);

    if (className) {
      cell.className = className;
    }

    return cell;
  }

  function createTableMessage(message) {
    const row = document.createElement("tr");
    row.className = "loading-row";

    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.textContent = message;

    row.appendChild(cell);
    return row;
  }

  function createOrderStatusBadge(status) {
    const normalized = normalizeStatus(status);
    const badge = document.createElement("span");

    badge.className =
      `status-badge ${statusClassName(normalized)}`;

    badge.textContent =
      ORDER_STATUS_LABELS[normalized] ||
      valueOrFallback(status, "알 수 없음");

    return badge;
  }

  function renderEvents() {
    const events = [...state.events].sort(compareEventsNewestFirst);

    elements.eventsPanelCount.textContent =
      `${formatInteger(events.length)}건`;

    elements.eventTimeline.replaceChildren();

    if (events.length === 0) {
      elements.eventTimeline.appendChild(
        createEmptyState(
          "관측 이벤트가 없습니다.",
          "에이전트가 동작하면 trace 이벤트가 여기에 표시됩니다."
        )
      );
      return;
    }

    const fragment = document.createDocumentFragment();

    for (const event of events) {
      fragment.appendChild(createTimelineItem(event));
    }

    elements.eventTimeline.appendChild(fragment);
  }

  function renderEventsError() {
    elements.eventsPanelCount.textContent = "불러오기 실패";
    elements.eventTimeline.replaceChildren(
      createEmptyState(
        "이벤트를 불러오지 못했습니다.",
        "인증 상태와 API 연결을 확인해주세요."
      )
    );
  }

  function createTimelineItem(event) {
    const detail = parseEventDetail(event.detail);
    const item = document.createElement("li");
    item.className = "timeline-item";

    const dot = document.createElement("span");
    dot.className = `timeline-dot ${eventToneClass(event.kind)}`;
    dot.setAttribute("aria-hidden", "true");

    const heading = document.createElement("div");
    heading.className = "timeline-heading";

    const headingLeft = document.createElement("div");

    const kind = document.createElement("p");
    kind.className = "timeline-kind";
    kind.textContent = valueOrFallback(event.kind, "unknown");

    const trace = document.createElement("code");
    trace.className = "trace-id";
    trace.textContent =
      `trace ${valueOrFallback(event.trace_id, "-")}`;

    const time = document.createElement("time");
    time.className = "timeline-time";

    const eventDate = extractEventDate(event, detail.parsed);

    if (eventDate) {
      time.dateTime = eventDate.toISOString();
      time.textContent = formatDateTime(eventDate);
    } else {
      time.textContent =
        event.id !== undefined && event.id !== null
          ? `이벤트 #${event.id}`
          : "시각 정보 없음";
    }

    headingLeft.append(kind, trace);
    heading.append(headingLeft, time);

    const summary = document.createElement("p");
    summary.className = "event-summary";
    summary.textContent = summarizeEventDetail(detail.parsed);

    const details = document.createElement("details");
    details.className = "event-detail";

    const detailsSummary = document.createElement("summary");
    detailsSummary.textContent = "상세 데이터 보기";

    const raw = document.createElement("pre");
    raw.textContent = detail.pretty;

    details.append(detailsSummary, raw);
    item.append(dot, heading, summary, details);

    return item;
  }

  function parseEventDetail(rawDetail) {
    if (
      rawDetail &&
      typeof rawDetail === "object"
    ) {
      return {
        parsed: rawDetail,
        pretty: JSON.stringify(rawDetail, null, 2)
      };
    }

    if (typeof rawDetail !== "string") {
      return {
        parsed: {},
        pretty: valueOrFallback(rawDetail)
      };
    }

    try {
      const parsed = JSON.parse(rawDetail);

      return {
        parsed,
        pretty: JSON.stringify(parsed, null, 2)
      };
    } catch {
      return {
        parsed: { message: rawDetail },
        pretty: rawDetail
      };
    }
  }

  function summarizeEventDetail(detail) {
    if (detail === null || detail === undefined) {
      return "상세 정보가 없습니다.";
    }

    if (typeof detail !== "object") {
      return truncateText(String(detail), 180);
    }

    const preferredKeys = [
      "message",
      "summary",
      "action",
      "status",
      "question",
      "query",
      "tool",
      "model",
      "error"
    ];

    const parts = [];

    for (const key of preferredKeys) {
      if (
        detail[key] !== undefined &&
        detail[key] !== null &&
        detail[key] !== ""
      ) {
        parts.push(
          `${humanizeKey(key)}: ${compactValue(detail[key])}`
        );
      }

      if (parts.length >= 3) {
        break;
      }
    }

    if (parts.length === 0) {
      for (const [key, value] of Object.entries(detail).slice(0, 3)) {
        if (isTimestampKey(key)) {
          continue;
        }

        parts.push(`${humanizeKey(key)}: ${compactValue(value)}`);
      }
    }

    return parts.length > 0
      ? truncateText(parts.join(" · "), 240)
      : "상세 정보가 없습니다.";
  }

  function compareEventsNewestFirst(a, b) {
    const detailA = parseEventDetail(a.detail).parsed;
    const detailB = parseEventDetail(b.detail).parsed;

    const dateA = extractEventDate(a, detailA);
    const dateB = extractEventDate(b, detailB);

    if (dateA && dateB) {
      return dateB.getTime() - dateA.getTime();
    }

    if (dateA) {
      return -1;
    }

    if (dateB) {
      return 1;
    }

    return compareIdsDescending(a.id, b.id);
  }

  function extractEventDate(event, detail) {
    const candidates = [
      event.created_at,
      event.timestamp,
      event.occurred_at,
      event.time,
      detail && detail.created_at,
      detail && detail.timestamp,
      detail && detail.occurred_at,
      detail && detail.event_time,
      detail && detail.time
    ];

    for (const value of candidates) {
      const date = parseDate(value);

      if (date) {
        return date;
      }
    }

    return null;
  }

  function parseDate(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }

    let timestamp;

    if (typeof value === "number") {
      timestamp = value < 10_000_000_000 ? value * 1000 : value;
    } else {
      timestamp = Date.parse(String(value));
    }

    const date = new Date(timestamp);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function eventToneClass(kind) {
    const normalized = String(kind || "").toLowerCase();

    if (
      normalized.includes("error") ||
      normalized.includes("fail") ||
      normalized.includes("exception")
    ) {
      return "is-error";
    }

    if (
      normalized.includes("success") ||
      normalized.includes("complete") ||
      normalized.includes("finish")
    ) {
      return "is-success";
    }

    if (
      normalized.includes("warn") ||
      normalized.includes("retry") ||
      normalized.includes("gap")
    ) {
      return "is-warning";
    }

    return "";
  }

  function renderGapSummary() {
    const unresolvedCount = state.knowledgeGaps.filter(
      (gap) => !toBoolean(gap.resolved)
    ).length;

    elements.unresolvedGapCount.textContent =
      formatInteger(unresolvedCount);

    clearCardState(elements.gapSummaryCard);

    if (unresolvedCount === 0) {
      elements.gapSummaryCard.classList.add("is-success");
    } else {
      elements.gapSummaryCard.classList.add("is-warning");
    }
  }

  function renderGapSummaryError() {
    elements.unresolvedGapCount.textContent = "-";
    clearCardState(elements.gapSummaryCard);
    elements.gapSummaryCard.classList.add("is-danger");
  }

  function renderKnowledgeGaps() {
    const statusFilter = elements.gapStatusFilter.value;
    const query = elements.gapSearchInput.value
      .trim()
      .toLowerCase();

    const filteredGaps = state.knowledgeGaps
      .filter((gap) => {
        const resolved = toBoolean(gap.resolved);

        if (statusFilter === "resolved" && !resolved) {
          return false;
        }

        if (statusFilter === "unresolved" && resolved) {
          return false;
        }

        if (!query) {
          return true;
        }

        const searchableText = [
          gap.id,
          gap.question,
          gap.trace_id
        ]
          .map((value) => String(value ?? "").toLowerCase())
          .join(" ");

        return searchableText.includes(query);
      })
      .sort(compareKnowledgeGaps);

    elements.gapsPanelCount.textContent =
      `전체 ${formatInteger(state.knowledgeGaps.length)}건 · ` +
      `표시 ${formatInteger(filteredGaps.length)}건`;

    elements.knowledgeGapList.replaceChildren();

    if (filteredGaps.length === 0) {
      elements.knowledgeGapList.appendChild(
        createEmptyState(
          "조건에 맞는 지식갭이 없습니다.",
          "필터나 검색어를 변경해보세요."
        )
      );
      return;
    }

    const fragment = document.createDocumentFragment();

    for (const gap of filteredGaps) {
      fragment.appendChild(createKnowledgeGapItem(gap));
    }

    elements.knowledgeGapList.appendChild(fragment);
  }

  function renderKnowledgeGapsError() {
    elements.gapsPanelCount.textContent = "불러오기 실패";
    elements.knowledgeGapList.replaceChildren(
      createEmptyState(
        "지식갭을 불러오지 못했습니다.",
        "인증 상태와 API 연결을 확인해주세요."
      )
    );
  }

  function createKnowledgeGapItem(gap) {
    const resolved = toBoolean(gap.resolved);
    const item = document.createElement("li");
    item.className = "gap-item";

    const heading = document.createElement("div");
    heading.className = "gap-heading";

    const question = document.createElement("p");
    question.className = "gap-question";
    question.textContent =
      valueOrFallback(gap.question, "질문 내용 없음");

    const badge = document.createElement("span");
    badge.className = resolved
      ? "status-badge status-resolved"
      : "status-badge status-unresolved";
    badge.textContent = resolved ? "해결됨" : "미해결";

    heading.append(question, badge);

    const meta = document.createElement("div");
    meta.className = "gap-meta";

    const id = document.createElement("span");
    id.textContent = `ID ${valueOrFallback(gap.id)}`;

    const trace = document.createElement("code");
    trace.textContent =
      `trace ${valueOrFallback(gap.trace_id)}`;

    meta.append(id, trace);
    item.append(heading, meta);

    return item;
  }

  function compareKnowledgeGaps(a, b) {
    const resolvedDifference =
      Number(toBoolean(a.resolved)) -
      Number(toBoolean(b.resolved));

    if (resolvedDifference !== 0) {
      return resolvedDifference;
    }

    return compareIdsDescending(a.id, b.id);
  }

  function compareIdsDescending(a, b) {
    const numberA = Number(a);
    const numberB = Number(b);

    if (Number.isFinite(numberA) && Number.isFinite(numberB)) {
      return numberB - numberA;
    }

    return String(b ?? "").localeCompare(String(a ?? ""));
  }

  function createEmptyState(title, description = "") {
    const item = document.createElement("li");
    item.className = "empty-state";

    const strong = document.createElement("strong");
    strong.textContent = title;
    item.appendChild(strong);

    if (description) {
      const text = document.createElement("span");
      text.textContent = description;
      item.appendChild(text);
    }

    return item;
  }

  function showAuthenticationRequired() {
    synchronizeAuthentication();
    elements.authNotice.hidden = false;
    elements.lastUpdated.textContent = "로그인 필요";
    showError("관리자 인증 토큰이 없거나 만료되었습니다.");
  }

  function handlePossibleAuthenticationError(error) {
    const status = Number(error && error.status);

    if (status === 401) {
      showAuthenticationRequired();
      stopAutoRefresh();
    } else if (status === 403) {
      // 로그인은 됐지만 관리자가 아님 — "로그인하라"는 문구는 부정확하므로 구분한다.
      elements.authNotice.hidden = false;
      elements.authNotice.textContent =
        "관리자 권한이 없는 계정입니다. 관리자로 승격된 계정으로 다시 로그인해주세요.";
      elements.lastUpdated.textContent = "권한 없음";
      showError("관리자 권한이 없습니다(403). role은 매 요청 DB에서 조회되므로 강등되면 즉시 반영됩니다.");
      stopAutoRefresh();
    }
  }

  function showError(message) {
    elements.errorMessage.textContent = message;
    elements.errorBanner.hidden = false;
  }

  function hideError() {
    elements.errorBanner.hidden = true;
    elements.errorMessage.textContent = "";
  }

  function normalizeStatus(value) {
    return String(value || "unknown")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "_");
  }

  function statusClassName(status) {
    const supportedStatuses = new Set([
      "pending",
      "paid",
      "confirmed",
      "processing",
      "shipped",
      "delivered",
      "completed",
      "cancelled",
      "canceled",
      "failed",
      "refunded"
    ]);

    return supportedStatuses.has(status)
      ? `status-${status}`
      : "status-unknown";
  }

  function toBoolean(value) {
    if (typeof value === "boolean") {
      return value;
    }

    if (typeof value === "number") {
      return value !== 0;
    }

    return ["true", "1", "yes", "y", "resolved"].includes(
      String(value ?? "").trim().toLowerCase()
    );
  }

  function toFiniteNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function formatInteger(value) {
    return new Intl.NumberFormat("ko-KR", {
      maximumFractionDigits: 0
    }).format(toFiniteNumber(value));
  }

  function formatCurrency(value) {
    const amount = Number(value);

    if (!Number.isFinite(amount)) {
      return "-";
    }

    return new Intl.NumberFormat("ko-KR", {
      style: "currency",
      currency: "KRW",
      maximumFractionDigits: 0
    }).format(amount);
  }

  function formatDateTime(date) {
    return new Intl.DateTimeFormat("ko-KR", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false
    }).format(date);
  }

  function valueOrFallback(value, fallback = "-") {
    if (value === null || value === undefined || value === "") {
      return fallback;
    }

    return String(value);
  }

  function compactValue(value) {
    if (typeof value === "string") {
      return value;
    }

    if (
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      return String(value);
    }

    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }

  function truncateText(value, maximumLength) {
    const text = String(value);

    if (text.length <= maximumLength) {
      return text;
    }

    return `${text.slice(0, maximumLength - 1)}…`;
  }

  function humanizeKey(key) {
    return String(key)
      .replace(/_/g, " ")
      .replace(/\b\w/g, (character) => character.toUpperCase());
  }

  function isTimestampKey(key) {
    return [
      "created_at",
      "timestamp",
      "occurred_at",
      "event_time",
      "time"
    ].includes(String(key).toLowerCase());
  }
})();
