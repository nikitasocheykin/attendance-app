(function () {
  const tg = window.Telegram.WebApp;
  tg.expand();

  const qrVideo = document.getElementById("qr-video");
  const qrCanvas = document.getElementById("qr-canvas");
  const qrStatus = document.getElementById("qr-status");
  const btnStartQr = document.getElementById("btn-start-qr");
  const qrZoomContainer = document.getElementById("qr-zoom-container");
  const qrZoomSlider = document.getElementById("qr-zoom-slider");

  let qrStream = null;
  let qrScanActive = false;
  let qrPayload = null;
  let qrVideoTrack = null;

  async function startQrScanner() {
    try {
      qrStatus.textContent = "Запрашиваем доступ к камере...";
      qrVideo.classList.remove("hidden");

      qrStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      qrVideo.srcObject = qrStream;

      qrVideoTrack = qrStream.getVideoTracks()[0];
      const capabilities = qrVideoTrack.getCapabilities
        ? qrVideoTrack.getCapabilities()
        : {};

      if (capabilities.zoom) {
        qrZoomContainer.classList.remove("hidden");
        const { min, max, step } = capabilities.zoom;
        qrZoomSlider.min = min;
        qrZoomSlider.max = max;
        qrZoomSlider.step = step || 0.1;
        qrZoomSlider.value = min;

        qrZoomSlider.addEventListener("input", async () => {
          try {
            await qrVideoTrack.applyConstraints({
              advanced: [{ zoom: parseFloat(qrZoomSlider.value) }],
            });
          } catch (e) {
            console.warn("Не удалось применить zoom:", e);
          }
        });
      } else {
        qrZoomContainer.classList.add("hidden");
      }

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
            qrStatus.textContent = "QR распознан, отправляем данные...";
            stopQrScanner();
            sendCheckIn();
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
      qrVideoTrack = null;
    }
    qrVideo.classList.add("hidden");
    qrZoomContainer.classList.add("hidden");
  }

  function sendCheckIn() {
    if (!qrPayload) {
      tg.showPopup({
        title: "Ошибка",
        message: "QR-код не распознан.",
        buttons: [{ id: "ok", type: "close", text: "Ок" }],
      });
      return;
    }

    const data = {
      type: "check_in",
      qr_payload: qrPayload,
      init_data: tg.initData || "",
    };
    tg.sendData(JSON.stringify(data));
    tg.close();
  }

  if (btnStartQr) {
    btnStartQr.addEventListener("click", () => {
      qrPayload = null;
      startQrScanner();
    });
  }
})();
