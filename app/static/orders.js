function randomSuffix() { return Math.random().toString(16).slice(2, 8); }

document.getElementById("signupBtn").addEventListener("click", async () => {
  const btn = document.getElementById("signupBtn");
  btn.disabled = true;
  try {
    let username = document.getElementById("username").value.trim();
    if (!username) {
      username = "user_" + randomSuffix();
      document.getElementById("username").value = username;
    }
    const password = document.getElementById("password").value;

    const signup = await apiFetch("/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (signup.ok && signup.body && signup.body.access_token) {
      // 신규 가입: 얼굴 미등록이라 2차 인증 없이 바로 토큰.
      setAuth(signup.body.access_token, username);
      updateAuthStatusBar();
      renderResult(document.getElementById("authResult"), signup.status, signup.body);
    } else {
      // 이미 있는 아이디 → 공통 헬퍼로 로그인(얼굴 등록 계정이면 웹캠 2차 인증까지).
      try {
        await submitLogin(username, password);
        updateAuthStatusBar();
        renderResult(document.getElementById("authResult"), 200, { logged_in: username });
      } catch (err) {
        renderResult(document.getElementById("authResult"), err.status || 400, { message: err.message });
      }
    }
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("loadProductsBtn").addEventListener("click", async () => {
  const { body } = await apiFetch("/api/products");
  const el = document.getElementById("productsTable");
  if (!Array.isArray(body)) { el.textContent = "불러오기 실패"; return; }
  const rows = body.map(p =>
    `<tr><td>${p.product_code}</td><td>${p.name}</td><td>${p.category}</td>` +
    `<td>${p.price.toLocaleString()}원</td><td>${p.stock ?? "-"}</td></tr>`
  ).join("");
  el.innerHTML = `<table class="data"><thead><tr><th>코드</th><th>이름</th><th>분류</th>` +
    `<th>가격</th><th>재고</th></tr></thead><tbody>${rows}</tbody></table>`;
});

document.getElementById("previewBtn").addEventListener("click", async () => {
  const product_code = document.getElementById("pvCode").value.trim();
  const quantity = Number(document.getElementById("pvQty").value) || 1;
  const { status, body } = await apiFetch("/api/orders/preview", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ items: [{ product_code, quantity }] }),
  });
  renderResult(document.getElementById("previewResult"), status, body);
});

let lastKey = null;
let lastPayload = null;

async function placeOrder(key, items) {
  return apiFetch("/api/orders", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json", "Idempotency-Key": key }),
    body: JSON.stringify({ items }),
  });
}

document.getElementById("approveBtn").addEventListener("click", async () => {
  const product_code = document.getElementById("pvCode").value.trim();
  const quantity = Number(document.getElementById("pvQty").value) || 1;
  lastKey = crypto.randomUUID();
  lastPayload = [{ product_code, quantity }];
  const { status, body } = await placeOrder(lastKey, lastPayload);
  renderResult(document.getElementById("approveResult"), status, body);
});

document.getElementById("replayBtn").addEventListener("click", async () => {
  const el = document.getElementById("approveResult");
  if (!lastKey) { el.textContent = "먼저 ①정상 승인을 눌러 키를 만드세요."; return; }
  const { status, body } = await placeOrder(lastKey, lastPayload);
  renderResult(el, status, body);
});

document.getElementById("noKeyBtn").addEventListener("click", async () => {
  const product_code = document.getElementById("pvCode").value.trim();
  const quantity = Number(document.getElementById("pvQty").value) || 1;
  const { status, body } = await apiFetch("/api/orders", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }), // Idempotency-Key 없음
    body: JSON.stringify({ items: [{ product_code, quantity }] }),
  });
  renderResult(document.getElementById("approveResult"), status, body);
});

document.getElementById("conflictBtn").addEventListener("click", async () => {
  const el = document.getElementById("approveResult");
  if (!lastKey) { el.textContent = "먼저 ①정상 승인을 눌러 키를 만드세요."; return; }
  const product_code = document.getElementById("pvCode").value.trim();
  const differentQty = (Number(document.getElementById("pvQty").value) || 1) + 1;
  const { status, body } = await placeOrder(lastKey, [{ product_code, quantity: differentQty }]);
  renderResult(el, status, body);
});

document.getElementById("oversellBtn").addEventListener("click", async () => {
  const product_code = document.getElementById("pvCode").value.trim();
  const key = crypto.randomUUID();
  const { status, body } = await placeOrder(key, [{ product_code, quantity: 999999 }]);
  renderResult(document.getElementById("approveResult"), status, body);
});

document.getElementById("loadOrdersBtn").addEventListener("click", async () => {
  const { body } = await apiFetch("/api/orders", { headers: authHeaders() });
  const el = document.getElementById("ordersTable");
  if (!Array.isArray(body)) { el.textContent = "불러오기 실패(로그인 필요)"; return; }
  const rows = body.map(o =>
    `<tr><td>${o.order_no}</td><td>${o.status}</td><td>${o.total_amount.toLocaleString()}원</td>` +
    `<td>${o.items.length}건</td></tr>`
  ).join("");
  el.innerHTML = `<table class="data"><thead><tr><th>주문번호</th><th>상태</th>` +
    `<th>총액</th><th>품목수</th></tr></thead><tbody>${rows}</tbody></table>`;
});
