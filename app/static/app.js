// 바로봄 에이전트 챗 UI
// 멀티턴은 백엔드 메모리가 아니라 화면 transcript 누적으로 표현한다.
// 에이전트 응답 스키마: {answer, steps:[{step,action,action_input,observation}], stopped_by}

const form = document.getElementById("chatForm");
const input = document.getElementById("question");
const transcript = document.getElementById("transcript");
const maxSteps = document.getElementById("maxSteps");
const sendBtn = form.querySelector("button[type=submit]");
const micBtn = document.getElementById("micBtn");
const ttsToggle = document.getElementById("ttsToggle");
const voiceStatus = document.getElementById("voiceStatus");

function addMessage(cls, text) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  transcript.appendChild(div);
  transcript.scrollTop = transcript.scrollHeight;
  return div;
}

function renderBot(data) {
  const div = addMessage("bot", data.answer || "(빈 응답)");
  if (Array.isArray(data.steps) && data.steps.length) {
    const steps = document.createElement("div");
    steps.className = "steps";
    for (const s of data.steps) {
      const el = document.createElement("div");
      el.className = "step";
      const obs = typeof s.observation === "object" ? JSON.stringify(s.observation) : s.observation;
      el.textContent = `#${s.step} action=${s.action} input=${JSON.stringify(s.action_input)} → ${obs}`;
      steps.appendChild(el);
    }
    div.appendChild(steps);
  }
  if (data.stopped_by) {
    const sb = document.createElement("div");
    sb.className = "stopped";
    sb.textContent = "stopped_by: " + data.stopped_by;
    div.appendChild(sb);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = input.value.trim();
  if (!question) return;
  addMessage("user", question);
  input.value = "";
  sendBtn.disabled = true;

  try {
    const resp = await fetch("/api/agent/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, max_steps: Number(maxSteps.value) || 3 }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      addMessage("bot", `오류(${resp.status}): ${data.message || JSON.stringify(data)}`);
    } else {
      renderBot(data);
      if (ttsToggle.checked && data.answer) {
        try {
          await synthesizeAndPlay(data.answer);
        } catch (err) {
          addMessage("bot", "🔇 음성 재생 실패: " + err.message);
        }
      }
    }
  } catch (err) {
    addMessage("bot", "요청 실패: " + err.message);
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
});

const voiceRecorder = createVoiceRecorder({
  onResult(text) {
    input.value = text;
    voiceStatus.textContent = "";
    input.focus();
  },
  onError(err) {
    voiceStatus.textContent = "🎤 " + err.message;
  },
  onStateChange(state) {
    if (state === "recording") {
      micBtn.classList.add("is-recording");
      micBtn.textContent = "⏹";
      voiceStatus.textContent = "녹음 중... 다시 누르면 인식합니다.";
    } else if (state === "transcribing") {
      micBtn.classList.remove("is-recording");
      micBtn.textContent = "🎤";
      voiceStatus.textContent = "음성 인식 중...";
    } else {
      micBtn.classList.remove("is-recording");
      micBtn.textContent = "🎤";
    }
  },
});

micBtn.addEventListener("click", () => voiceRecorder.toggle());
