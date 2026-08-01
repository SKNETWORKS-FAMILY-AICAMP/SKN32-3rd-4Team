const searchBtn = document.getElementById("searchBtn");
const searchResult = document.getElementById("searchResult");
searchBtn.addEventListener("click", async () => {
  searchBtn.disabled = true;
  const query = document.getElementById("searchQuery").value.trim();
  const top_k = Number(document.getElementById("searchTopK").value) || 3;
  try {
    const { status, body } = await apiFetch("/api/rag/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k }),
    });
    renderResult(searchResult, status, body);
  } finally {
    searchBtn.disabled = false;
  }
});

const qaBtn = document.getElementById("qaBtn");
const qaResult = document.getElementById("qaResult");
qaBtn.addEventListener("click", async () => {
  qaBtn.disabled = true;
  qaBtn.textContent = "생성 중...";
  const question = document.getElementById("qaQuery").value.trim();
  const backend = document.getElementById("qaBackend").value;
  try {
    const { status, body } = await apiFetch("/api/rag/qa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, backend, top_k: 3 }),
    });
    renderResult(qaResult, status, body);
  } finally {
    qaBtn.disabled = false;
    qaBtn.textContent = "답변 생성";
  }
});
