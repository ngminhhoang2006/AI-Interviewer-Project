let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

const synth = window.speechSynthesis;
let currentAudio = null;

/**
 * Reads question text aloud using the Sherpa-ONNX server endpoint.
 */
async function speakQuestion(text, language = 'English') {
    if (!text || !text.trim()) return;

    // Stop any playing audio
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }

    console.log("[TTS] Requesting Sherpa-ONNX voice for:", text.substring(0, 30));

    try {
        const response = await fetch('/api/tts', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ text: text, language: language })
        });

        const data = await response.json();

        if (data.status === "success" && data.audio_data) {
            console.log("[TTS] Audio received from Sherpa-ONNX. Playing...");
            currentAudio = new Audio(data.audio_data);
            await currentAudio.play();
            return;
        }

        console.warn("[TTS] Server returned fallback flag:", data.message);
        triggerBrowserTTS(text, language);

    } catch (err) {
        console.error("[TTS Error] Failed to reach /api/tts endpoint:", err);
        triggerBrowserTTS(text, language);
    }
}

function triggerBrowserTTS(text, language) {
    const synth = window.speechSynthesis;
    if (!synth) return;
    synth.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    const langMap = {
        'English': 'en-US',
        'Vietnamese': 'vi-VN',
        'Spanish': 'es-ES',
        'French': 'fr-FR'
    };
    
    utterance.lang = langMap[language] || 'en-US';
    synth.speak(utterance);
}

/**
 * Speech-to-Text Recording and Submission to Sherpa-ONNX
 */
async function toggleRecording() {
    const recordBtn = document.getElementById('recordBtn');
    const statusText = document.getElementById('recordingStatus');

    if (!isRecording) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            // Determine supported mimeType for cross-browser compatibility
            let mimeType = 'audio/webm';
            if (!MediaRecorder.isTypeSupported('audio/webm')) {
                if (MediaRecorder.isTypeSupported('audio/mp4')) {
                    mimeType = 'audio/mp4';
                } else if (MediaRecorder.isTypeSupported('audio/ogg')) {
                    mimeType = 'audio/ogg';
                } else {
                    mimeType = '';
                }
            }

            mediaRecorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) audioChunks.push(event.data);
            };

            mediaRecorder.onstop = async () => {
                if (statusText) statusText.innerText = "Transcribing audio with Sherpa-ONNX...";
                
                const blobType = mediaRecorder.mimeType || 'audio/webm';
                const audioBlob = new Blob(audioChunks, { type: blobType });
                
                await sendAudioToSherpa(audioBlob);
                if (statusText) statusText.innerText = "";
            };

            mediaRecorder.start();
            isRecording = true;

            if (recordBtn) {
                recordBtn.classList.add('recording-active');
                recordBtn.innerText = "Stop Recording";
            }
            if (statusText) statusText.innerText = "Listening...";

        } catch (err) {
            console.error("Microphone access error:", err);
            alert("Could not access microphone. Please ensure microphone permissions are granted.");
        }
    } else {
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
            mediaRecorder.stream.getTracks().forEach(track => track.stop());
        }
        isRecording = false;

        if (recordBtn) {
            recordBtn.classList.remove('recording-active');
            recordBtn.innerText = "Start Recording";
        }
    }
}

async function sendAudioToSherpa(audioBlob) {
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');

    try {
        const response = await fetch('/api/interview/transcribe-audio', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        if (data.transcript) {
            const answerInput = document.getElementById('answerInput');
            if (answerInput) {
                answerInput.value = answerInput.value 
                    ? `${answerInput.value} ${data.transcript}` 
                    : data.transcript;
            }
        } else if (data.error) {
            console.error(`Transcription error: ${data.error}`);
        }
    } catch (err) {
        console.error("Transcription submission failed:", err);
    }
}

async function loadNextQuestion() {
    const response = await fetch('/api/interview/next-question');
    const data = await response.json();

    if (data.completed) {
        window.location.href = '/report';
        return;
    }

    const questionContainer = document.getElementById('questionContainer');
    if (questionContainer) {
        questionContainer.innerText = data.question;
    }
    speakQuestion(data.question, data.language);
}