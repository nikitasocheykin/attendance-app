// main.js

let tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
let videoEl;
let canvasEl;
let canvasCtx;
let stream = null;
let scanInterval = null;

let zoom = 1.0;

const statusEl = () => document.getElementById("status");
const authWarningEl = () => document.getElementById("authWarning");
const resultBoxEl = () => document.getElementById("resultBox");
const qrResultEl = () => document.getElementById("qrResult");
const zoomValueEl = () => document.getElementById("zoomValue");

function setStatus(text) {
  statusEl().textContent = text;
}

function showAuthWarning() {
  authWarningEl().classList.remove("hidden");
}

function showResult(text) {
  qrResultEl().textContent = text;
  resultBoxEl().classList.remove("hidden");
}

function applyZoom() {
  if (videoEl) {
    videoEl.style.transformOrigin = "center center";
    videoEl.style.transform = `scale(${zoom})`;
  }
  if (zoomValueEl()) {
    zoomValueEl().textContent = `${zoom.toFixed(1)}x`;
  }
}

// Инициализация WebApp
function initTelegramWebApp() {
  if (!tg) {
    // Не в телеге
    showAuthWarning();
    setStatus("WebApp открыт не в Telegram. Открой через кнопку бота.");
    return;
  }

  try {
    tg.ready();
    tg.expand();
  } catch (e) {
    console.warn("Telegram WebApp init error:", e);
  }

  // При запуске через KeyboardButton initData может быть пустым — это нормально
  setStatus("Нажми «Начать сканирование», затем наведи камеру на QR.");
}

async function startScan() {
  videoEl = document.getElementById("video");
  canvasEl = document.getElementById("canvas");
  canvasCtx = canvasEl.getContext("2d");

  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");

  startBtn.disabled = true;
  stopBtn.disabled = false;
  setStatus("Запрашиваем доступ к камере…");

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: "environment"
      },
      audio: false
    });

    videoEl.srcObject = stream;

    await videoEl.play();
    setStatus("Идёт сканирование… Наведи камеру на QR.");
    zoom = 1.0;
    applyZoom();

    canvasEl.width = videoEl.videoWidth || 640;
    canvasEl.height = videoEl.videoHeight || 480;

    scanInterval = setInterval(tickScan, 300);
  } catch (err) {
    console.error("Ошибка доступа к камере", err);
    setStatus("Не удалось получить доступ к камере. Разреши камеру в настройках Telegram.");
    startBtn.disabled = false;
    stopBtn.disabled = true;
  }
}

function stopScan() {
  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");

  if (scanInterval) {
    clearInterval(scanInterval);
    scanInterval = null;
  }

  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  startBtn.disabled = false;
  stopBtn.disabled = true;
  setStatus("Сканирование остановлено.");
}

function tickScan() {
  if (!videoEl || videoEl.readyState !== videoEl.HAVE_ENOUGH_DATA) {
    return;
  }

  canvasEl.width = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;

  canvasCtx.drawImage(videoEl, 0, 0, canvasEl.width, canvasEl.height);

  const imageData = canvasCtx.getImageData(
    0,
    0,
    canvasEl.width,
    canvasEl.height
  );
  const code = jsQR(imageData.data, imageData.width, imageData.height);

  if (code && code.data) {
    const qrText = code.data.trim();
    stopScan();
    showResult(qrText);
    setStatus("QR-код распознан. Отправляем данные в бота…");
    sendCheckInToBot(qrText);
  }
}

function sendCheckInToBot(qrPayload) {
  if (!tg) {
    setStatus("Нет соединения с Telegram. Открой сканер через бота.");
    return;
  }

  const payload = {
    type: "check_in",
    qr_payload: qrPayload
    // init_data не используем, так как при запуске через KeyboardButton оно пустое
  };

  try {
    tg.sendData(JSON.stringify(payload));
    setStatus("Данные отправлены в бота. Вернись в чат — бот напишет результат.");
    setTimeout(() => {
      try {
        tg.close();
      } catch (e) {
        console.warn("Не удалось закрыть WebApp:", e);
      }
    }, 1000);
  } catch (err) {
    console.error("Ошибка при отправке данных в бота через sendData:", err);
    setStatus("Ошибка при отправке данных в бота. Попробуй ещё раз.");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initTelegramWebApp();

  document.getElementById("startBtn").addEventListener("click", () => {
    startScan();
  });

  document.getElementById("stopBtn").addEventListener("click", () => {
    stopScan();
  });

  document.getElementById("zoomInBtn").addEventListener("click", () => {
    zoom = Math.min(3.0, zoom + 0.2);
    applyZoom();
  });

  document.getElementById("zoomOutBtn").addEventListener("click", () => {
    zoom = Math.max(1.0, zoom - 0.2);
    applyZoom();
  });
});
