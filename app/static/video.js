// 화상 상담 페이지 (Phase 12)
// 좌: 고객 웹캠 / 우: AI 아바타(TTS 재생 중 입 애니메이션).
// 음성입력→/api/voice/stt→/api/agent/chat→/api/voice/tts. STT/TTS/녹음 헬퍼는 common.js 재사용.
// 무폴백: 카메라 권한 거부는 조용히 넘기지 않고 사유별 안내 + "텍스트로 계속" 명시 선택.

const selfVideo = document.getElementById("selfVideo");
const cameraNotice = document.getElementById("cameraNotice");
const cameraNoticeText = document.getElementById("cameraNoticeText");
const cameraOnBtn = document.getElementById("cameraOnBtn");
const cameraOffBtn = document.getElementById("cameraOffBtn");
const textOnlyBtn = document.getElementById("textOnlyBtn");

const avatar = document.getElementById("avatar");
const avatarState = document.getElementById("avatarState");
const transcript = document.getElementById("videoTranscript");
const videoStatus = document.getElementById("videoStatus");
const form = document.getElementById("videoForm");
const input = document.getElementById("videoInput");
const sendBtn = form.querySelector("button[type=submit]");
const micBtn = document.getElementById("videoMicBtn");

let mediaStream = null;
let busy = false; // 녹음/전송/응답/재생 중 중복 요청 방지

function addMessage(cls, text) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  transcript.appendChild(div);
  transcript.scrollTop = transcript.scrollHeight;
  return div;
}

// --- 카메라 ---
function stopCamera() {
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }
  selfVideo.srcObject = null;
}

async function startCamera() {
  stopCamera(); // 재시작 시 기존 스트림부터 정리
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: true });
  } catch (err) {
    // 사유별 구분(무폴백 — 조용히 텍스트모드로 넘어가지 않음)
    let msg;
    if (err.name === "NotAllowedError") {
      msg = "카메라 권한이 거부되었습니다. 브라우저 주소창의 카메라 아이콘에서 허용하거나, 아래 '텍스트로 계속'을 선택하세요.";
    } else if (err.name === "NotFoundError") {
      msg = "연결된 카메라를 찾을 수 없습니다. '텍스트로 계속'을 선택하거나 카메라를 연결하세요.";
    } else if (err.name === "NotReadableError") {
      msg = "카메라가 다른 앱에서 사용 중입니다. 해당 앱을 종료하거나 '텍스트로 계속'을 선택하세요.";
    } else {
      msg = "카메라를 열 수 없습니다: " + err.message;
    }
    cameraNoticeText.textContent = msg;
    return;
  }
  mediaStream = stream;
  selfVideo.srcObject = stream;
  // 장치가 외부 요인으로 해제되면 UI를 원복
  stream.getVideoTracks().forEach((track) => {
    track.onended = () => {
      stopCamera();
      cameraNotice.hidden = false;
      cameraOffBtn.hidden = true;
      cameraNoticeText.textContent = "카메라 연결이 종료되었습니다. 다시 켜거나 텍스트로 계속하세요.";
    };
  });
  cameraNotice.hidden = true;
  cameraOffBtn.hidden = false;
}

cameraOnBtn.addEventListener("click", startCamera);
cameraOffBtn.addEventListener("click", () => {
  stopCamera();
  cameraNotice.hidden = false;
  cameraOffBtn.hidden = true;
  cameraNoticeText.textContent = "카메라를 껐습니다. 다시 켜거나 텍스트로 계속하세요.";
});
textOnlyBtn.addEventListener("click", () => {
  cameraNotice.hidden = true;
  cameraOffBtn.hidden = true;
  videoStatus.textContent = "텍스트/음성 모드로 진행합니다(카메라 없음).";
});
// 페이지 이탈 시 스트림 정리(beforeunload만 의존하지 않음)
window.addEventListener("pagehide", stopCamera);

// --- 아바타 ---
function setAvatarSpeaking(on) {
  avatar.classList.toggle("speaking", on);
  avatarState.textContent = on ? "말하는 중…" : "대기 중";
}

// --- 대화 흐름 ---
function setBusy(on) {
  busy = on;
  sendBtn.disabled = on;
  micBtn.disabled = on;
}

async function sendMessage(text) {
  const question = (text || "").trim();
  if (!question || busy) return;
  addMessage("user", question);
  input.value = "";
  setBusy(true);
  videoStatus.textContent = "AI 상담원이 답변 중…";

  try {
    const resp = await fetch("/api/agent/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, max_steps: 3 }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      addMessage("bot", `오류(${resp.status}): ${data.message || JSON.stringify(data)}`);
      videoStatus.textContent = "";
      return;
    }
    addMessage("bot", data.answer || "(빈 응답)");
    videoStatus.textContent = "";
    if (data.answer) {
      try {
        await synthesizeAndPlay(data.answer, {
          onSpeakStart: () => setAvatarSpeaking(true),
          onSpeakEnd: () => setAvatarSpeaking(false),
        });
      } catch (err) {
        setAvatarSpeaking(false);
        addMessage("bot", "🔇 음성 재생 실패: " + err.message);
      }
    }
  } catch (err) {
    addMessage("bot", "요청 실패: " + err.message);
    videoStatus.textContent = "";
  } finally {
    setBusy(false);
    input.focus();
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage(input.value);
});

// --- 음성 입력(녹음→STT) ---
const recorder = createVoiceRecorder({
  onResult(text) {
    videoStatus.textContent = "";
    sendMessage(text); // 인식 즉시 상담 전송
  },
  onError(err) {
    videoStatus.textContent = "🎤 " + err.message;
  },
  onStateChange(state) {
    if (state === "recording") {
      micBtn.classList.add("is-recording");
      micBtn.textContent = "⏹";
      videoStatus.textContent = "녹음 중… 다시 누르면 인식합니다.";
    } else if (state === "transcribing") {
      micBtn.classList.remove("is-recording");
      micBtn.textContent = "🎤";
      videoStatus.textContent = "음성 인식 중…";
    } else {
      micBtn.classList.remove("is-recording");
      micBtn.textContent = "🎤";
    }
  },
});

micBtn.addEventListener("click", () => {
  if (busy && !recorder.isRecording()) return; // 응답/재생 중 새 녹음 방지(녹음 종료는 허용)
  recorder.toggle();
});
