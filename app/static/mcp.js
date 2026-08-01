document.getElementById("listToolsBtn").addEventListener("click", async () => {
  const btn = document.getElementById("listToolsBtn");
  btn.disabled = true;
  try {
    const { status, body } = await apiFetch("/api/mcp/tools", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    renderResult(document.getElementById("toolsResult"), status, body);
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("callToolBtn").addEventListener("click", async () => {
  const btn = document.getElementById("callToolBtn");
  btn.disabled = true;
  btn.textContent = "호출 중...";
  try {
    const product_code = document.getElementById("mcpProductCode").value.trim();
    const { status, body } = await apiFetch("/api/mcp/call", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "get_price", arguments: { product_code } }),
    });
    renderResult(document.getElementById("callResult"), status, body);
  } finally {
    btn.disabled = false;
    btn.textContent = "get_price 호출";
  }
});
