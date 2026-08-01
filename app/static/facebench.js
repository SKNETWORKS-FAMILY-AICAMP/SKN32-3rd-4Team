// 얼굴인식 백엔드 성능 비교 페이지
// A(기준)·B(비교) 얼굴을 웹캠 촬영 또는 파일 업로드 → /api/face/benchmark → 3백엔드 실측 표.

const slots = { A: { blob: null, stream: null }, B: { blob: null, stream: null } };

function el(id) { return document.getElementById(id); }

// --- 활성 인식 백엔드 선택 메뉴 ---
async function loadBackends() {
  const { ok, body } = await apiFetch("/api/face/backend");
  if (!ok || !body) { el("backendStatus").textContent = "백엔드 정보를 불러오지 못했습니다."; return; }
  const sel = el("backendSelect");
  sel.innerHTML = "";
  for (const b of body.backends) {
    const opt = document.createElement("option");
    opt.value = b.name;
    opt.textContent = `${b.name} — ${b.note}` + (b.available ? "" : " (모델 없음)");
    opt.disabled = !b.available;
    if (b.name === body.active) opt.selected = true;
    sel.appendChild(opt);
  }
  el("backendStatus").textContent = `현재 사용 중: ${body.active} · 매칭 임계값 ${body.match_threshold}`;
}

el("applyBackendBtn").addEventListener("click", async () => {
  const backend = el("backendSelect").value;
  el("applyBackendBtn").disabled = true;
  try {
    const resp = await fetch("/api/face/backend", {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ backend }),
    });
    const body = await resp.json().catch(() => null);
    if (resp.ok) {
      el("backendStatus").textContent = `변경됨 → ${body.active} (기존 등록 얼굴은 재등록 필요)`;
      el("backendStatus").style.color = "var(--success, #218c74)";
    } else if (resp.status === 401 || resp.status === 403) {
      el("backendStatus").textContent = "변경은 관리자만 가능합니다. 관리자로 로그인하세요.";
      el("backendStatus").style.color = "#c23616";
    } else {
      el("backendStatus").textContent = (body && body.message) || `변경 실패 (HTTP ${resp.status})`;
      el("backendStatus").style.color = "#c23616";
    }
  } catch (err) {
    el("backendStatus").textContent = "요청 실패: " + err.message;
  } finally {
    el("applyBackendBtn").disabled = false;
  }
});

loadBackends();

function setSlot(which, blob, label) {
  slots[which].blob = blob;
  el("status" + which).textContent = label;
  const url = URL.createObjectURL(blob);
  const t = el("thumb" + which);
  t.src = url;
  t.hidden = false;
  updateRunEnabled();
}

function updateRunEnabled() {
  const ready = slots.A.blob && slots.B.blob;
  el("runBtn").disabled = !ready;
  el("runHint").textContent = ready ? "준비 완료 — 실행하세요." : "A·B 둘 다 준비되면 활성화됩니다.";
}

async function startCam(which) {
  const video = el("video" + which);
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true });
    slots[which].stream = stream;
    video.srcObject = stream;
    el("shot" + which).hidden = false;
    el("status" + which).textContent = "카메라 켜짐 — 촬영하세요.";
  } catch (err) {
    let msg = "카메라 오류: " + err.name;
    if (err.name === "NotAllowedError") msg = "카메라 권한 거부됨 — 파일 업로드를 쓰세요.";
    else if (err.name === "NotReadableError") msg = "카메라 사용 중 — 파일 업로드를 쓰세요.";
    el("status" + which).textContent = msg;
  }
}

async function shoot(which) {
  const blob = await captureFrameBlob(el("video" + which));
  if (!blob) { el("status" + which).textContent = "프레임 캡처 실패"; return; }
  setSlot(which, blob, "촬영됨(웹캠)");
}

["A", "B"].forEach((w) => {
  el("cam" + w).addEventListener("click", () => startCam(w));
  el("shot" + w).addEventListener("click", () => shoot(w));
  el("file" + w).addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (f) setSlot(w, f, "업로드됨: " + f.name);
  });
});

el("runBtn").addEventListener("click", async () => {
  el("runBtn").disabled = true;
  el("runHint").textContent = "실측 중… (모델 최초 호출은 로딩 포함으로 느릴 수 있음)";
  try {
    const fd = new FormData();
    fd.append("image_a", slots.A.blob, "a.jpg");
    fd.append("image_b", slots.B.blob, "b.jpg");
    // 벤치마크는 3개 모델을 모두 도는 무거운 연산이라 관리자 전용(운영 도구).
    const resp = await fetch("/api/face/benchmark", { method: "POST", headers: authHeaders(), body: fd });
    const body = await resp.json().catch(() => null);
    if (!resp.ok) {
      if (resp.status === 401 || resp.status === 403) {
        el("runHint").textContent = "벤치마크는 관리자만 실행할 수 있습니다. 관리자로 로그인하세요.";
        return;
      }
      el("runHint").textContent = (body && body.message) || `실패 (HTTP ${resp.status})`;
      return;
    }
    renderResults(body);
    el("runHint").textContent = "완료.";
  } catch (err) {
    el("runHint").textContent = "요청 실패: " + err.message;
  } finally {
    el("runBtn").disabled = false;
  }
});

function renderResults(body) {
  const tbody = el("resultBody");
  tbody.innerHTML = "";
  const labels = { insightface: "insightface (r50)", adaface: "AdaFace (IR-101)", lvface: "LVFace (ViT-S)" };
  // 코사인 최고 백엔드 강조
  const valid = body.results.filter((r) => r.cosine != null);
  const best = valid.length ? Math.max(...valid.map((r) => r.cosine)) : null;
  for (const r of body.results) {
    const tr = document.createElement("tr");
    if (r.error) {
      tr.innerHTML = `<td>${labels[r.backend] || r.backend}</td><td colspan="4" class="err-cell">모델 없음/오류: ${r.error}</td>`;
    } else {
      const isBest = r.cosine === best;
      const verdict = r.match ? '<span class="badge ok">동일인 판정</span>' : '<span class="badge warn">불일치</span>';
      tr.innerHTML =
        `<td>${labels[r.backend] || r.backend}${r.backend === body.active_backend ? " ⭐(현재 사용)" : ""}</td>` +
        `<td><strong>${r.cosine.toFixed(4)}</strong>${isBest ? " 🏆" : ""}</td>` +
        `<td>${verdict}</td>` +
        `<td>${r.ms_per_embed} ms</td>` +
        `<td>${r.backend === "adaface" ? "저품질 강함" : r.backend === "lvface" ? "고품질·빠름" : "기준선"}</td>`;
    }
    tbody.appendChild(tr);
  }
  el("resultTable").hidden = false;
  el("resultMeta").textContent =
    `현재 로그인 사용 백엔드: ${body.active_backend} · 매칭 임계값: ${body.match_threshold} ` +
    `(코사인이 임계값 이상이면 동일인 판정). 지연은 최초 호출 시 모델 로딩 포함.`;
}

window.addEventListener("pagehide", () => {
  ["A", "B"].forEach((w) => { if (slots[w].stream) slots[w].stream.getTracks().forEach((t) => t.stop()); });
});
