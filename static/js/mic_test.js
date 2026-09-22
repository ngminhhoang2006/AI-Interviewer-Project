document.addEventListener("DOMContentLoaded", () => {
    let activeStream = null;
    let audioContext = null;
    let analyser = null;
    let animationFrameId = null;

    const micSelect = document.getElementById('micSelect');
    const meterFill = document.getElementById('meterFill');
    const micStatus = document.getElementById('micStatus');
    const btnStartMic = document.getElementById('btnStartMic');
    const btnRecordTest = document.getElementById('btnRecordTest');
    const audioPlayback = document.getElementById('audioPlayback');

    async function loadAudioDevices() {
        try {
            const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            tempStream.getTracks().forEach(track => track.stop());

            const devices = await navigator.mediaDevices.enumerateDevices();
            const audioInputs = devices.filter(device => device.kind === 'audioinput');

            micSelect.innerHTML = '';
            audioInputs.forEach((device, index) => {
                const option = document.createElement('option');
                option.value = device.deviceId;
                option.text = device.label || `Microphone ${index + 1}`;
                micSelect.appendChild(option);
            });
        } catch (err) {
            console.error("Device Enumeration Error:", err);
            micSelect.innerHTML = '<option value="">Default Microphone</option>';
        }
    }

    loadAudioDevices();

    function updateMeter() {
        if (!analyser) return;
        const array = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(array);

        let values = 0;
        for (let i = 0; i < array.length; i++) {
            values += array[i];
        }

        const average = values / array.length;
        const pct = Math.min(100, Math.round((average / 128) * 100));
        meterFill.style.width = pct + '%';

        animationFrameId = requestAnimationFrame(updateMeter);
    }

    btnStartMic.onclick = async () => {
        try {
            if (activeStream) {
                activeStream.getTracks().forEach(track => track.stop());
            }

            const selectedDeviceId = micSelect.value;
            const constraints = {
                audio: selectedDeviceId ? { deviceId: { exact: selectedDeviceId } } : true
            };

            activeStream = await navigator.mediaDevices.getUserMedia(constraints);
            micStatus.innerText = "Microphone active. Speak to test volume.";
            btnStartMic.disabled = true;
            btnRecordTest.disabled = false;

            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioContext.createAnalyser();
            analyser.fftSize = 256;

            const microphone = audioContext.createMediaStreamSource(activeStream);
            microphone.connect(analyser);

            updateMeter();
        } catch (err) {
            console.error("Microphone Access Error:", err);
            micStatus.innerText = "Error: Microphone access denied or unavailable.";
            micStatus.style.color = "#ef4444";
        }
    };

    btnRecordTest.onclick = async () => {
        btnRecordTest.disabled = true;
        btnRecordTest.innerText = "Recording (3s)...";

        try {
            const selectedDeviceId = micSelect.value;
            const constraints = {
                audio: selectedDeviceId ? { deviceId: { exact: selectedDeviceId } } : true
            };

            const stream = await navigator.mediaDevices.getUserMedia(constraints);
            const mediaRecorder = new MediaRecorder(stream);
            const chunks = [];

            mediaRecorder.ondataavailable = e => chunks.push(e.data);
            mediaRecorder.onstop = () => {
                const blob = new Blob(chunks, { type: 'audio/webm' });
                audioPlayback.src = URL.createObjectURL(blob);
                btnRecordTest.innerText = "🎤 Record 3s Sample";
                btnRecordTest.disabled = false;
            };

            mediaRecorder.start();
            setTimeout(() => {
                mediaRecorder.stop();
                stream.getTracks().forEach(track => track.stop());
            }, 3000);
        } catch (err) {
            alert("Failed to record sample audio.");
            btnRecordTest.innerText = "🎤 Record 3s Sample";
            btnRecordTest.disabled = false;
        }
    };

    const btnProceed = document.getElementById('btnProceed');
    if (btnProceed) {
        btnProceed.onclick = () => {
            if (animationFrameId) cancelAnimationFrame(animationFrameId);
            if (activeStream) activeStream.getTracks().forEach(track => track.stop());
            if (audioContext) audioContext.close();
        };
    }
});
