let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// Initialize Web Speech API Synthesizer
const synth = window.speechSynthesis;

/**
 * 1. Text-to-Speech: Read the question aloud
 */
function speakQuestion(text, language = 'English') {
    if (!synth) return;

    // Cancel any ongoing speech
    synth.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    
    // Set speech voice language based on context
    const langMap = {
        'English': 'en-US',
        'Vietnamese': 'vi-VN',
        'Spanish': 'es-ES',
        'French': 'fr-FR'
    };
    utterance.lang = langMap[language] || 'en-US';
    utterance.rate = 1.0; // Normal speech speed

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