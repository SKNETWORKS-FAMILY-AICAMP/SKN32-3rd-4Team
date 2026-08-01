// 고객용 쇼핑 화면
// 상품 그리드 + 검색/분류 + 장바구니 + 주문(로그인→미리보기→승인). 공통 submitLogin으로 2FA 지원.

const el = (id) => document.getElementById(id);
let products = [];
const cart = new Map(); // product_code -> {product, qty}

function won(n) { return (n || 0).toLocaleString() + "원"; }

// --- 상품 로드/렌더 ---
async function loadProducts() {
  const { ok, body } = await apiFetch("/api/products");
  if (!ok || !Array.isArray(body)) { el("gridEmpty").hidden = false; return; }
  products = body;
  const cats = [...new Set(products.map((p) => p.category))].sort();
  for (const c of cats) {
    const o = document.createElement("option");
    o.value = c; o.textContent = c;
    el("categoryFilter").appendChild(o);
  }
  renderGrid();
}

function renderGrid() {
  const q = el("searchInput").value.trim().toLowerCase();
  const cat = el("categoryFilter").value;
  const grid = el("productGrid");
  grid.innerHTML = "";
  const filtered = products.filter(
    (p) => (!cat || p.category === cat) &&
      (!q || p.name.toLowerCase().includes(q) || p.product_code.toLowerCase().includes(q))
  );
  el("gridEmpty").hidden = filtered.length > 0;
  for (const p of filtered) {
    const soldOut = p.stock !== null && p.stock <= 0;
    const card = document.createElement("div");
    card.className = "product-card";
    card.innerHTML =
      `<span class="cat-badge">${p.category}</span>` +
      `<div class="product-thumb" aria-hidden="true">${p.name.slice(0, 1)}</div>` +
      `<div class="product-name">${p.name}</div>` +
      `<div class="product-code">${p.product_code}</div>` +
      `<div class="product-price">${won(p.price)}</div>` +
      `<div class="product-stock ${soldOut ? "out" : ""}">${soldOut ? "품절" : "재고 " + (p.stock ?? "-")}</div>` +
      `<button class="add-btn" type="button" ${soldOut ? "disabled" : ""}>담기</button>`;
    card.querySelector(".add-btn").addEventListener("click", () => addToCart(p));
    grid.appendChild(card);
  }
}

el("searchInput").addEventListener("input", renderGrid);
el("categoryFilter").addEventListener("change", renderGrid);

// --- 장바구니 ---
function addToCart(p) {
  const entry = cart.get(p.product_code) || { product: p, qty: 0 };
  const max = p.stock ?? 99;
  entry.qty = Math.min(entry.qty + 1, max);
  cart.set(p.product_code, entry);
  renderCart();
}

function setQty(code, qty) {
  const entry = cart.get(code);
  if (!entry) return;
  const max = entry.product.stock ?? 99;
  entry.qty = Math.max(0, Math.min(qty, max));
  if (entry.qty === 0) cart.delete(code); else cart.set(code, entry);
  renderCart();
}

function renderCart() {
  const box = el("cartItems");
  box.innerHTML = "";
  let total = 0, count = 0;
  for (const [code, { product, qty }] of cart) {
    total += product.price * qty; count += qty;
    const row = document.createElement("div");
    row.className = "cart-row";
    row.innerHTML =
      `<div class="cart-row-name">${product.name}<span>${won(product.price)}</span></div>` +
      `<div class="qty-ctrl">` +
      `<button type="button" class="qminus">−</button><span class="qval">${qty}</span>` +
      `<button type="button" class="qplus">+</button>` +
      `<button type="button" class="qdel" title="삭제">🗑</button></div>`;
    row.querySelector(".qminus").addEventListener("click", () => setQty(code, qty - 1));
    row.querySelector(".qplus").addEventListener("click", () => setQty(code, qty + 1));
    row.querySelector(".qdel").addEventListener("click", () => setQty(code, 0));
    box.appendChild(row);
  }
  el("cartEmpty").hidden = cart.size > 0;
  el("cartCount").textContent = count;
  el("cartTotal").textContent = won(total);
  el("checkoutBtn").disabled = cart.size === 0;
}

// --- 주문 흐름 ---
el("checkoutBtn").addEventListener("click", async () => {
  if (!getToken()) { openLogin(); return; }
  await runPreview();
});

async function runPreview() {
  el("cartStatus").textContent = "";
  const items = [...cart.values()].map(({ product, qty }) => ({ product_code: product.product_code, quantity: qty }));
  const resp = await fetch("/api/orders/preview", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ items }),
  });
  const body = await resp.json().catch(() => null);
  if (resp.status === 401) { openLogin(); return; }
  if (!resp.ok) { el("cartStatus").textContent = (body && body.message) || `미리보기 실패 (HTTP ${resp.status})`; return; }
  renderPreview(body);
  el("checkoutModal").hidden = false;
}

function renderPreview(pv) {
  const rows = pv.lines.map((l) =>
    `<tr class="${l.sufficient ? "" : "insufficient"}">` +
    `<td>${l.name || l.product_code}</td><td>${l.quantity}</td>` +
    `<td>${won(l.unit_price)}</td><td>${won(l.subtotal)}</td>` +
    `<td>${l.sufficient ? "✅" : "재고부족(" + (l.available ?? 0) + ")"}</td></tr>`
  ).join("");
  el("previewBody").innerHTML =
    `<table class="data"><thead><tr><th>상품</th><th>수량</th><th>단가</th><th>소계</th><th>재고</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>` +
    `<p class="preview-total">합계 <strong>${won(pv.total)}</strong></p>` +
    (pv.issues && pv.issues.length ? `<p class="voice-status">${pv.issues.join(" · ")}</p>` : "");
  el("confirmOrderBtn").disabled = !pv.feasible;
}

el("cancelCheckoutBtn").addEventListener("click", () => { el("checkoutModal").hidden = true; });

el("confirmOrderBtn").addEventListener("click", async () => {
  el("confirmOrderBtn").disabled = true;
  el("checkoutStatus").textContent = "결제 승인 중…";
  try {
    const items = [...cart.values()].map(({ product, qty }) => ({ product_code: product.product_code, quantity: qty }));
    const key = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now());
    const resp = await fetch("/api/orders", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json", "Idempotency-Key": key }),
      body: JSON.stringify({ items }),
    });
    const body = await resp.json().catch(() => null);
    if (resp.ok && body && body.order_no) {
      el("checkoutModal").hidden = true;
      cart.clear(); renderCart(); await loadProducts();
      el("cartStatus").textContent = `✅ 주문 완료: ${body.order_no} · ${won(body.total_amount)} (상태 ${body.status})`;
    } else {
      el("checkoutStatus").textContent = (body && body.message) || `주문 실패 (HTTP ${resp.status})`;
    }
  } catch (err) {
    el("checkoutStatus").textContent = "주문 요청 실패: " + err.message;
  } finally {
    el("confirmOrderBtn").disabled = false;
  }
});

// --- 로그인 모달(공통 2FA 헬퍼 사용) ---
function openLogin() { el("loginModal").hidden = false; el("shopUser").focus(); }
el("cancelLoginBtn").addEventListener("click", () => { el("loginModal").hidden = true; });

async function doShopLogin(signup) {
  const username = el("shopUser").value.trim();
  const password = el("shopPass").value;
  if (!username || !password) { el("shopLoginStatus").textContent = "아이디·비밀번호를 입력하세요."; return; }
  el("shopLoginBtn").disabled = true; el("shopSignupBtn").disabled = true;
  try {
    if (signup) {
      const r = await apiFetch("/auth/signup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (r.ok && r.body.access_token) { setAuth(r.body.access_token, username); }
      else { el("shopLoginStatus").textContent = (r.body && r.body.message) || "가입 실패"; return; }
    } else {
      await submitLogin(username, password); // 얼굴 등록 계정이면 웹캠 2차 인증 오버레이
    }
    updateAuthStatusBar();
    el("loginModal").hidden = true;
    await runPreview(); // 로그인 끝나면 바로 주문 미리보기로
  } catch (err) {
    el("shopLoginStatus").textContent = err.message || "로그인 실패";
  } finally {
    el("shopLoginBtn").disabled = false; el("shopSignupBtn").disabled = false;
  }
}
el("shopLoginBtn").addEventListener("click", () => doShopLogin(false));
el("shopSignupBtn").addEventListener("click", () => doShopLogin(true));

renderCart();
loadProducts();
