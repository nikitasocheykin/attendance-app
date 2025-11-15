(function () {
  const tg = window.Telegram.WebApp;
  tg.expand();

  const urlParams = new URLSearchParams(window.location.search);
  const roleParam = urlParams.get("role") || "student";

  const userInfoEl = document.getElementById("user-info");
  const roleLabelEl = document.getElementById("role-label");

  const studentPanel = document.getElementById("student-panel");
  const speakerPanel = document.getElementById("speaker-panel");
  const adminPanel = document.getElementById("admin-panel");

  function showPanel(role) {
    studentPanel.classList.add("hidden");
    speakerPanel.classList.add("hidden");
    adminPanel.classList.add("hidden");

    if (role === "student") {
      studentPanel.classList.remove("hidden");
      roleLabelEl.textContent = "Студент";
    } else if (role === "speaker") {
      speakerPanel.classList.remove("hidden");
      roleLabelEl.textContent = "Спикер";
    } else if (role === "master_admin") {
      adminPanel.classList.remove("hidden");
      roleLabelEl.textContent = "Мастер-админ";
    } else {
      studentPanel.classList.remove("hidden");
      roleLabelEl.textContent = "Студент (по умолчанию)";
    }
  }

const u = tg.initDataUnsafe?.user;
if (u) {
  userInfoEl.innerHTML =
    "Вы: <b>" +
    (u.first_name || "") +
    " " +
    (u.last_name || "") +
    "</b> @" +
    (u.username || "") +
    "<br />ID: " +
    u.id;
} else {
  userInfoEl.innerHTML =
    "WebApp запущен через кнопку клавиатуры.<br>" +
    "initData недоступен — это нормально для такого режима.";
}

  showPanel(roleParam);

  // STUDENT

  const lectureIdInput = document.getElementById("student-lecture-id");
  const qrVideo = document.getElementById("qr-video");
  const qrCanvas = document.getElementById("qr-canvas");
  const qrStatus = document.getElementById("qr-status");
  const btnStartQr = document.getElementById("btn-start-qr");
  const btnSendCheckin = document.getElementById("btn-send-checkin");

  let qrStream = null;
  let qrScanActive = false;
  let qrPayload = null;

  async function startQrScanner() {
    try {
      qrStatus.textContent = "Запрашиваем доступ к камере...";
      qrVideo.classList.remove("hidden");

      qrStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      qrVideo.srcObject = qrStream;

      const canvas = qrCanvas;
      const ctx = canvas.getContext("2d");

      qrScanActive = true;
      qrStatus.textContent = "Сканируйте QR-код...";

      function tick() {
        if (!qrScanActive) return;
        if (qrVideo.readyState === qrVideo.HAVE_ENOUGH_DATA) {
          canvas.width = qrVideo.videoWidth;
          canvas.height = qrVideo.videoHeight;
          ctx.drawImage(qrVideo, 0, 0, canvas.width, canvas.height);
          const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
          const code = jsQR(imageData.data, canvas.width, canvas.height);
          if (code) {
            qrScanActive = false;
            qrPayload = code.data;
            qrStatus.textContent = "QR распознан!";
            stopQrScanner();
            return;
          }
        }
        requestAnimationFrame(tick);
      }

      requestAnimationFrame(tick);
    } catch (e) {
      console.error(e);
      qrStatus.textContent =
        "Ошибка доступа к камере. Разреши доступ в браузере/Telegram.";
    }
  }

  function stopQrScanner() {
    if (qrStream) {
      qrStream.getTracks().forEach((t) => t.stop());
      qrStream = null;
    }
    qrVideo.classList.add("hidden");
  }

  if (btnStartQr) {
    btnStartQr.addEventListener("click", () => {
      qrPayload = null;
      startQrScanner();
    });
  }

  if (btnSendCheckin) {
    btnSendCheckin.addEventListener("click", () => {
      const lectureId = parseInt(lectureIdInput.value, 10);
      if (!lectureId) {
        tg.showPopup({
          title: "Ошибка",
          message: "Укажи ID лекции.",
          buttons: [{ id: "ok", type: "close", text: "Ок" }],
        });
        return;
      }
      if (!qrPayload) {
        tg.showPopup({
          title: "Ошибка",
          message: "Сначала отсканируй QR-код лекции.",
          buttons: [{ id: "ok", type: "close", text: "Ок" }],
        });
        return;
      }

      const data = {
        type: "check_in",
        role: "student",
        lecture_id: lectureId,
        qr_payload: qrPayload,
        init_data: tg.initData || "",
      };
      tg.sendData(JSON.stringify(data));
      tg.close();
    });
  }

  // SPEAKER

  const speakerLectureIdInput = document.getElementById("speaker-lecture-id");
  const speakerLatInput = document.getElementById("speaker-lat");
  const speakerLonInput = document.getElementById("speaker-lon");
  const btnOpenCheckin = document.getElementById("btn-open-checkin");
  const btnCloseCheckin = document.getElementById("btn-close-checkin");
  const btnSetLocation = document.getElementById("btn-set-location");

  function sendSpeakerToggle(isActive) {
    const lectureId = parseInt(speakerLectureIdInput.value, 10);
    if (!lectureId) {
      tg.showPopup({
        title: "Ошибка",
        message: "Укажи ID лекции.",
        buttons: [{ id: "ok", type: "close", text: "Ок" }],
      });
      return;
    }
    const data = {
      type: "speaker_toggle",
      role: "speaker",
      lecture_id: lectureId,
      is_active: isActive,
      init_data: tg.initData || "",
    };
    tg.sendData(JSON.stringify(data));
    tg.close();
  }

  if (btnOpenCheckin) {
    btnOpenCheckin.addEventListener("click", () => sendSpeakerToggle(true));
  }
  if (btnCloseCheckin) {
    btnCloseCheckin.addEventListener("click", () => sendSpeakerToggle(false));
  }

  if (btnSetLocation) {
    btnSetLocation.addEventListener("click", () => {
      const lectureId = parseInt(speakerLectureIdInput.value, 10);
      const lat = parseFloat(speakerLatInput.value);
      const lon = parseFloat(speakerLonInput.value);
      if (!lectureId || Number.isNaN(lat) || Number.isNaN(lon)) {
        tg.showPopup({
          title: "Ошибка",
          message: "Укажи корректный ID лекции и координаты.",
          buttons: [{ id: "ok", type: "close", text: "Ок" }],
        });
        return;
      }
      const data = {
        type: "speaker_set_location",
        role: "speaker",
        lecture_id: lectureId,
        lat: lat,
        lon: lon,
        init_data: tg.initData || "",
      };
      tg.sendData(JSON.stringify(data));
      tg.close();
    });
  }

  // ADMIN

  const adminRatingChatInput = document.getElementById("admin-rating-chat-id");
  const adminSheetIdInput = document.getElementById("admin-sheet-id");
  const btnAdminSetRatingChat = document.getElementById(
    "btn-admin-set-rating-chat"
  );
  const btnAdminSetSheetId = document.getElementById("btn-admin-set-sheet-id");

  if (btnAdminSetRatingChat) {
    btnAdminSetRatingChat.addEventListener("click", () => {
      const chatId = parseInt(adminRatingChatInput.value, 10);
      if (!chatId) {
        tg.showPopup({
          title: "Ошибка",
          message: "Укажи корректный ID чата.",
          buttons: [{ id: "ok", type: "close", text: "Ок" }],
        });
        return;
      }
      const data = {
        type: "admin_set_rating_chat",
        role: "master_admin",
        rating_chat_id: chatId,
        init_data: tg.initData || "",
      };
      tg.sendData(JSON.stringify(data));
      tg.close();
    });
  }

  if (btnAdminSetSheetId) {
    btnAdminSetSheetId.addEventListener("click", () => {
      const sheetId = adminSheetIdInput.value.trim();
      if (!sheetId) {
        tg.showPopup({
          title: "Ошибка",
          message: "Укажи ID Google Sheets.",
          buttons: [{ id: "ok", type: "close", text: "Ок" }],
        });
        return;
      }
      const data = {
        type: "admin_set_sheet_id",
        role: "master_admin",
        sheet_id: sheetId,
        init_data: tg.initData || "",
      };
      tg.sendData(JSON.stringify(data));
      tg.close();
    });
  }
})();
