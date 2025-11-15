// main.js

// Глобальные переменные
let tg = window.Telegram.WebApp;
let videoEl;
let canvasEl;
let canvasCtx;
let stream = null;
let scanInterval = null;

const statusEl = () => document.getElementById("status");
const statusBoxEl = () => document.getElementById("statusBox");
const authWarningEl = () => document.getElementById("authWarning");
const resultBoxEl = () => document.getElementById("resultBox");
const qrResultEl = () => document.getElementById("qrResult");

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

// Инициализация WebApp
function initTelegramWebApp() {
  try {
    tg.ready();
    tg.expand();
  } catch (e) {
    console.error("Telegram WebApp not available:", e);
  }

  // Проверим, что мини-апп реально открыт из Telegram (есть user)
  if (!tg.initDataUnsafe || !tg.initDataUnsafe.user) {
    showAuthWarning();
    setStatus("WebApp не авторизован. Открой сканер через кнопку бота.");
  } else {
    setStatus("Нажми «Начать сканирование», затем наведи камеру на QR.");
  }
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
    // Запрашиваем основную камеру (обычно задняя на телефоне)
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: "environment"
      },
      audio: false
    });

    videoEl.srcObject = stream;

    await videoEl.play();
    setStatus("Идёт сканирование… Наведи камеру на QR.");

    // Настраиваем канвас под видео
    canvasEl.width = videoEl.videoWidth || 640;
    canvasEl.height = videoEl.videoHeight || 480;

    // Запускаем цикл сканирования
    scanInterval = setInterval(tickScan, 300);
  } catch (err) {
    console.error("Ошибка доступа к камере", err);
    setStatus("Не удалось получить доступ к камере. Разреши камеру в настройках.");
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
  // Пакуем данные для бота
  const payload = {
    type: "check_in",
    qr_payload: qrPayload,
    init_data: tg.initData || ""
  };

  try {
    tg.sendData(JSON.stringify(payload));
    setStatus("Данные отправлены в бота. Вернись в чат — бот напишет результат.");
    // Можно закрыть мини-апп через секунду, но не обязательно:
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
});
