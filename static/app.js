let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// Initialize Web Speech API Synthesizer as last-resort fallback
const synth = window.speechSynthesis;
let currentAudio = null;

/**
 * In-browser Kokoro TTS via kokoro-js (Transformers.js + WASM/ONNX).
 * Loaded from a CDN as an ES module through a dynamic import(), so this
 * works from a plain <script> tag with no bundler required.
 */
const KOKORO_MODEL_ID = "onnx-community/Kokoro-82M-v1.0-ONNX";
const KOKORO_CDN_URL = "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/+esm";

let kokoroTTSInstance = null;
let kokoroLoadPromise = null;
let kokoroClientUnavailable = false; // set after first failure so we stop retrying every question

async function getKokoroTTS() {
    if (kokoroClientUnavailable) return null;
    if (kokoroTTSInstance) return kokoroTTSInstance;

    if (!kokoroLoadPromise) {
        kokoroLoadPromise = (async () => {
            const { KokoroTTS } = await import(KOKORO_CDN_URL);
            return await KokoroTTS.from_pretrained(KOKORO_MODEL_ID, {
                dtype: "q8",     // ~86MB download, good quality/size tradeoff for a browser
                device: "wasm"   // works everywhere; swap to "webgpu" if you want to require it
            });
        })();
    }

    try {
        kokoroTTSInstance = await kokoroLoadPromise;
        return kokoroTTSInstance;
    } catch (err) {
        console.warn("kokoro-js unavailable in this browser, will use server-side TTS instead:", err);
        kokoroClientUnavailable = true;
        return null;
    }
}

// Kick off the model download as soon as the page loads, so it's ready
// by the time the first question needs to be spoken instead of stalling it.
getKokoroTTS();

function getKokoroVoiceForLanguage(language) {
    // Mirrors chatbot.py's get_kokoro_voice() on the server. Note: Kokoro's
    // model doesn't natively support Vietnamese phonemes, so this just
    // switches to a different English voice rather than truly speaking
    // Vietnamese - same limitation as the server-side path.
    const lang = (language || 'English').toLowerCase();
    return lang.includes('vietnamese') ? 'af_bella' : 'af_heart';
}

/**
 * 1. Text-to-Speech: Read the question aloud.
 * Chain: in-browser Kokoro (kokoro-js) -> server-side Kokoro/pyttsx3 (/api/tts) -> browser Web Speech API
 */
async function speakQuestion(text, language = 'English') {
    // Stop any ongoing HTML5 audio playback
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }

    // Stop any ongoing native browser speech synthesis
    if (synth) {
        synth.cancel();
    }

    if (!text || !text.trim()) return;

    // 1. Primary: kokoro-js running locally in the browser - no server round trip
    console.log("[TTS] Trying in-browser kokoro-js...");
    const tts = await getKokoroTTS();
    if (tts) {
        try {
            const audio = await tts.generate(text, { voice: getKokoroVoiceForLanguage(language) });
            const audioUrl = URL.createObjectURL(audio.toBlob());

            currentAudio = new Audio(audioUrl);
            await currentAudio.play();
            console.log("[TTS] Played via in-browser kokoro-js.");
            return;
        } catch (err) {
            console.warn("[TTS] In-browser Kokoro generation failed, falling back to server TTS:", err);
        }
    } else {
        console.warn("[TTS] kokoro-js was not available (see load error above, if any). Falling back to server TTS.");
    }

    // 2. Fallback: server-side Kokoro -> pyttsx3 chain, then browser Web Speech API
    await speakQuestionServerSide(text, language);
}

async function speakQuestionServerSide(text, language) {
    console.log("[TTS] Trying server-side /api/tts (Kokoro -> pyttsx3)...");
    try {
        const response = await fetch('/api/tts', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ text: text, language: language })
        });

        const contentType = response.headers.get("content-type");

        // If server returns audio stream (Kokoro or pyttsx3 WAV file)
        if (response.ok && contentType && contentType.includes("audio/wav")) {
            const audioBlob = await response.blob();
            const audioUrl = URL.createObjectURL(audioBlob);

            currentAudio = new Audio(audioUrl);
            await currentAudio.play();
            console.log("[TTS] Played via server-side /api/tts.");
            return;
        }

        // If server signals fallback to Web Speech API
        const data = await response.json();
        console.warn("[TTS] Server had no audio engine available, message:", data.message);
        if (data.use_browser_tts) {
            console.warn("[TTS] Falling back to browser Web Speech API.");
            triggerBrowserTTS(text, language);
        }
    } catch (err) {
        console.warn("[TTS] Server endpoint unreachable, falling back to Web Speech API:", err);
        triggerBrowserTTS(text, language);
    }
}

/**
 * Fallback Web Speech API engine
 */
function triggerBrowserTTS(text, language) {
    if (!synth) return;

    const utterance = new SpeechSynthesisUtterance(text);
    const langMap = {
        'English': 'en-US',
        'Vietnamese': 'vi-VN',
        'Spanish': 'es-ES',
        'French': 'fr-FR'
    };
    
    utterance.lang = langMap[language] || 'en-US';
    utterance.rate = 1.0;

    synth.speak(utterance);
}

/**
 * 2. Speech-to-Text: Handle Audio Recording
 */
async function toggleRecording() {
    const recordBtn = document.getElementById('recordBtn');
    const statusText = document.getElementById('recordingStatus');

    if (!isRecording) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) audioChunks.push(event.data);
            };

            mediaRecorder.onstop = async () => {
                statusText.innerText = "Transcribing audio with Whisper...";
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                
                await sendAudioToWhisper(audioBlob);
                statusText.innerText = "";
            };

            mediaRecorder.start();
            isRecording = true;
            recordBtn.classList.add('recording-active');
            recordBtn.innerText = "Stop Recording";
            statusText.innerText = "Listening...";
        } catch (err) {
            console.error("Microphone access denied or unsupported:", err);
            alert("Could not access microphone. Please check browser permissions.");
        }
    } else {
        mediaRecorder.stop();
        // Stop all audio tracks to release the microphone
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
        isRecording = false;
        recordBtn.classList.remove('recording-active');
        recordBtn.innerText = "Start Recording";
    }
}

/**
 * Send WebM blob to Flask /api/interview/transcribe-audio
 */
async function sendAudioToWhisper(audioBlob) {
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
            // Append transcribed text to text area
            answerInput.value = answerInput.value 
                ? `${answerInput.value} ${data.transcript}` 
                : data.transcript;
        } else if (data.error) {
            alert(`Transcription error: ${data.error}`);
        }
    } catch (err) {
        console.error("Failed to transcribe audio:", err);
    }
}

/**
 * Fetch Next Question & Automatically Read It Aloud
 */
async function loadNextQuestion() {
    const response = await fetch('/api/interview/next-question');
    const data = await response.json();

    if (data.completed) {
        window.location.href = '/report';
        return;
    }

    // Render question text in DOM
    document.getElementById('questionContainer').innerText = data.question;

    // Voice Interview Feature: Read Question Aloud
    speakQuestion(data.question, data.language);
}