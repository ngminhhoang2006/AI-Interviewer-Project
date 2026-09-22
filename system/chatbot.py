import json
import ollama
from pathlib import Path
from datetime import datetime
from collections import deque
import re
import unicodedata
import os
import sys
import tempfile
import threading
import io
import wave
import numpy as np

# ------------------------------------------------------------
# Audio recording dependencies
# ------------------------------------------------------------
try:
    import sounddevice as sd
    import numpy as np
    _VOICE_CORE_AVAILABLE = True
except ImportError:
    _VOICE_CORE_AVAILABLE = False

# ------------------------------------------------------------
# Sherpa-ONNX dependency check
# ------------------------------------------------------------
try:
    import sherpa_onnx
    SHERPA_ONNX_AVAILABLE = True
except ImportError:
    SHERPA_ONNX_AVAILABLE = False

try:
    import webrtcvad
    VAD_AVAILABLE = True
except ImportError:
    VAD_AVAILABLE = False

# ------------------------------------------------------------
# noisereduce fallback (pure Python/numpy, no compiled deps).
# Used automatically if the Sherpa-ONNX denoiser model isn't present.
# Weaker on non-stationary noise (voices, traffic) but fine for
# steady hum/fan noise, and has no numpy version pin at all.
# ------------------------------------------------------------
try:
    import noisereduce as nr
    NOISEREDUCE_AVAILABLE = True
except ImportError:
    NOISEREDUCE_AVAILABLE = False

VOICE_AVAILABLE = _VOICE_CORE_AVAILABLE and SHERPA_ONNX_AVAILABLE

BASE_DIR = Path(__file__).resolve().parent
OLLAMA_MODEL = "qwen3:8b"
MAX_QUESTIONS = 10

VOICE_SAMPLE_RATE = 16000       # Required sample rate for Sherpa-ONNX ASR
SILENCE_DURATION = 1.5          # Seconds of quiet before assuming speaker is done
CHUNK_DURATION = 0.5            # Seconds per audio chunk analyzed for silence
MAX_RECORD_SECONDS = 120        # Maximum recording duration

# webrtcvad config
VAD_FRAME_MS = 30
VAD_AGGRESSIVENESS = 3
VAD_MIN_SPEECH_FRAMES = 3
VAD_SILENCE_TOLERANCE = 0.15

# Lazily initialized singletons
_sherpa_asr_recognizer = None
_sherpa_tts_engine = None
_sherpa_tts_lock = threading.Lock()

# Sherpa-ONNX's own speech denoiser (DPDFNet = ONNX export of DeepFilterNet).
# Uses the same sherpa_onnx package you already have installed for ASR/TTS —
# no torch/torchaudio, no numpy version pin, no dependency conflicts.
_sherpa_denoiser = None

# Languages served by NVIDIA Parakeet-TDT 0.6B v3 (loaded via Sherpa-ONNX's
# nemo_transducer backend). Only add a language here if you've actually
# downloaded the Parakeet model AND it's in Parakeet v3's supported set
# (en, es, fr, de, it, pt, nl, pl, ru, uk, and other EU languages — NOT
# Vietnamese, which stays on Whisper below).
PARAKEET_LANGUAGES = {"english", "spanish", "french"}


def flatten_text(text: str) -> str:
    """Strips diacritics and non-alphanumeric characters for comparisons."""
    text = text.replace("\u00a0", " ").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]", "", stripped.casefold())


# ============================================================
# SHERPA-ONNX: SPEECH-TO-TEXT (ASR)
# ============================================================

# Cache recognizers per language so we don't re-instantiate on every request
_sherpa_asr_recognizers = {}

def get_sherpa_asr_recognizer(language: str = "english"):
    """Routes to Parakeet (fast/accurate, limited languages) or Whisper
    (slower, but covers Vietnamese and everything else) depending on
    the requested interview language."""
    global _sherpa_asr_recognizers
    lang_key = language.lower()

    if lang_key in _sherpa_asr_recognizers:
        return _sherpa_asr_recognizers[lang_key]

    if not SHERPA_ONNX_AVAILABLE:
        print("[STT Error] sherpa_onnx package is not available.")
        return None

    if lang_key in PARAKEET_LANGUAGES:
        recognizer = _load_parakeet_recognizer()
        if recognizer is None:
            # Parakeet model files aren't downloaded yet (or failed to load) —
            # fall back to Whisper rather than returning nothing, so the app
            # keeps working while Parakeet is being set up.
            print(f"[STT Fallback] Parakeet unavailable for '{lang_key}', falling back to Whisper")
            recognizer = _load_whisper_recognizer(lang_key)
    else:
        recognizer = _load_whisper_recognizer(lang_key)

    if recognizer is not None:
        _sherpa_asr_recognizers[lang_key] = recognizer

    return recognizer


def _load_parakeet_recognizer():
    """Loads NVIDIA Parakeet-TDT 0.6B v3 (int8, exported for Sherpa-ONNX).
    Download the model files from:
    https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8
    into sherpa_models/asr_parakeet/ before this will work."""
    model_dir = (BASE_DIR / "sherpa_models" / "asr_parakeet").resolve()
    encoder_path = model_dir / "encoder.int8.onnx"
    decoder_path = model_dir / "decoder.int8.onnx"
    joiner_path = model_dir / "joiner.int8.onnx"
    tokens_path = model_dir / "tokens.txt"

    if not all(p.exists() for p in (encoder_path, decoder_path, joiner_path, tokens_path)):
        print(f"[STT Error] Missing Parakeet model files in directory: {model_dir}")
        return None

    try:
        recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(encoder_path),
            decoder=str(decoder_path),
            joiner=str(joiner_path),
            tokens=str(tokens_path),
            model_type="nemo_transducer",
            num_threads=2,
            decoding_method="greedy_search",
        )
        print("[STT Initialized] Loaded Parakeet-TDT 0.6B v3 recognizer")
        return recognizer
    except Exception as e:
        print(f"[STT Initialization Failed - Parakeet] {e}")
        return None


def _load_whisper_recognizer(language: str):
    """Loads Whisper via Sherpa-ONNX. Used for Vietnamese and any language
    Parakeet doesn't cover."""
    lang_map = {
        "vietnamese": "vi",
        "english": "en",
        "spanish": "es",
        "french": "fr"
    }
    target_lang = lang_map.get(language, "en")

    model_dir = (BASE_DIR / "sherpa_models" / "asr").resolve()

    # Match non-int8 or int8 models dynamically
    encoder_path = next(model_dir.glob("*encoder*.onnx"), None)
    decoder_path = next(model_dir.glob("*decoder*.onnx"), None)
    tokens_path = next(model_dir.glob("*tokens*.txt"), None)

    if not encoder_path or not decoder_path or not tokens_path:
        print(f"[STT Error] Missing Whisper models in directory: {model_dir}")
        return None

    try:
        recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=str(encoder_path),
            decoder=str(decoder_path),
            tokens=str(tokens_path),
            language=target_lang,  # Hard-locks the decoding language to 'vi' or 'en'
            task="transcribe",
            num_threads=2
        )
        print(f"[STT Initialized] Loaded Whisper recognizer for language code: '{target_lang}'")
        return recognizer
    except Exception as e:
        print(f"[STT Initialization Failed - Whisper] {e}")
        return None


def _rms(audio_chunk):
    """Root-mean-square loudness of a float32 audio chunk."""
    if audio_chunk.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio_chunk))))


# If the DPDFNet model isn't downloaded yet, should we fall back to
# noisereduce? On already-clean recordings (quiet room, decent mic),
# noisereduce can over-subtract and *hurt* transcription accuracy rather
# than help. Default is False: skip denoising entirely until DPDFNet is
# set up, rather than risk degrading otherwise-good audio. Flip to True
# only if your actual recording environment is genuinely noisy and you've
# confirmed noisereduce helps more than it hurts for your mic/room.
FALL_BACK_TO_NOISEREDUCE = False


def _normalize_peak(samples: np.ndarray, target_peak: float = 0.98) -> np.ndarray:
    """Scales audio down proportionally if its peak exceeds target_peak,
    preserving waveform shape (unlike hard clipping, which flattens peaks
    and introduces its own distortion). Leaves audio under the target
    peak untouched."""
    peak = float(np.abs(samples).max()) if samples.size else 0.0
    if peak > target_peak:
        samples = samples * (target_peak / peak)
    return samples


def _estimate_noise_floor(samples: np.ndarray, sample_rate: int, frame_ms: int = 20) -> float:
    """Rough noise-floor estimate: average RMS of the quietest 10% of
    short frames. Used to decide whether a recording is already clean
    enough that denoising would do more harm (over-suppressed consonants,
    the kind of artifact that turns 'mathematics' into 'Mehemetic') than
    good."""
    if samples.size == 0:
        return 0.0
    frame_len = max(int(sample_rate * frame_ms / 1000), 1)
    n_frames = max(len(samples) // frame_len, 1)
    frame_rms = np.array([
        _rms(samples[i * frame_len:(i + 1) * frame_len])
        for i in range(n_frames)
    ])
    frame_rms.sort()
    quietest = frame_rms[: max(len(frame_rms) // 10, 1)]
    return float(np.mean(quietest))


# RMS noise-floor below which a recording is considered "already clean"
# and denoising is skipped entirely. Both DPDFNet and noisereduce showed
# real evidence of over-suppression artifacts on clean, close-mic audio
# (see chat history) — they help genuinely noisy recordings but can hurt
# already-quiet ones. Tune this against your actual interview conditions:
# raise it if noisy clips are slipping through undenoised, lower it if
# clean clips are still getting degraded.
NOISE_FLOOR_SKIP_THRESHOLD = 0.01


def _load_sherpa_denoiser():
    """Lazily loads Sherpa-ONNX's DPDFNet speech denoiser (cached across
    requests). Download the model from:
    https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/dpdfnet2.onnx
    into sherpa_models/dpdfnet2.onnx before this will work."""
    global _sherpa_denoiser
    if _sherpa_denoiser is not None:
        return _sherpa_denoiser

    if not SHERPA_ONNX_AVAILABLE:
        return None

    model_path = (BASE_DIR / "sherpa_models" / "dpdfnet2.onnx").resolve()
    if not model_path.exists():
        print(f"[Denoiser Error] Missing DPDFNet model at: {model_path}")
        return None

    try:
        config = sherpa_onnx.OfflineSpeechDenoiserConfig(
            model=sherpa_onnx.OfflineSpeechDenoiserModelConfig(
                dpdfnet=sherpa_onnx.OfflineSpeechDenoiserDpdfNetModelConfig(
                    model=str(model_path),
                ),
                num_threads=1,
                debug=False,
                provider="cpu",
            )
        )
        _sherpa_denoiser = sherpa_onnx.OfflineSpeechDenoiser(config)
        print("[Denoiser Initialized] Loaded Sherpa-ONNX DPDFNet denoiser")
        return _sherpa_denoiser
    except Exception as e:
        print(f"[Denoiser Initialization Failed] {e}")
        return None


def denoise_audio(samples: np.ndarray, sample_rate: int):
    """Runs neural noise suppression on float32 mono audio in [-1, 1].
    Prefers Sherpa-ONNX's built-in DPDFNet denoiser (same runtime as your
    ASR/TTS, no extra dependencies). Falls back to noisereduce (pure
    Python, weaker on non-stationary noise) if the DPDFNet model isn't
    downloaded yet. Falls back to the original, unmodified audio if
    neither is available or either errors out, so this is always safe
    to call. Returns (samples, sample_rate) since the denoiser may hand
    back audio at its own native rate."""
    if samples.size == 0:
        return samples, sample_rate

    noise_floor = _estimate_noise_floor(samples, sample_rate)
    print(f"[Denoiser] Measured noise floor: {noise_floor:.5f} "
          f"(skip threshold: {NOISE_FLOOR_SKIP_THRESHOLD})")
    if noise_floor < NOISE_FLOOR_SKIP_THRESHOLD:
        print("[Denoiser] Recording already clean — skipping denoising to avoid artifacts.")
        return samples, sample_rate

    denoiser = _load_sherpa_denoiser()
    if denoiser is not None:
        try:
            denoised = denoiser.run(samples.astype(np.float32), sample_rate)
            denoised_samples = _normalize_peak(np.array(denoised.samples, dtype=np.float32))
            return denoised_samples, denoised.sample_rate
        except Exception as e:
            print(f"[DPDFNet Denoise Error] {e}")
            # fall through to noisereduce/raw below

    if not FALL_BACK_TO_NOISEREDUCE:
        print("[Denoiser] DPDFNet unavailable and noisereduce fallback is "
              "disabled — using raw audio unmodified.")
        return samples, sample_rate

    if NOISEREDUCE_AVAILABLE and FALL_BACK_TO_NOISEREDUCE:
        try:
            reduced = nr.reduce_noise(y=samples.astype(np.float32), sr=sample_rate)
            reduced = _normalize_peak(reduced.astype(np.float32))
            return reduced, sample_rate
        except Exception as e:
            print(f"[noisereduce Error] {e}")

    return samples, sample_rate


def calibrate_ambient_noise(duration=1.0):
    print("Calibrating microphone... please stay quiet for a moment.")
    recording = sd.rec(
        int(duration * VOICE_SAMPLE_RATE),
        samplerate=VOICE_SAMPLE_RATE,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    baseline = _rms(recording.flatten())
    return max(baseline * 4, 0.01)


def record_until_silence():
    if VAD_AVAILABLE:
        return _record_until_silence_vad()
    return _record_until_silence_energy()


def _record_until_silence_vad():
    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
    frame_size = int(VOICE_SAMPLE_RATE * VAD_FRAME_MS / 1000)
    window_size = max(1, int((SILENCE_DURATION * 1000) / VAD_FRAME_MS))
    max_frames = int((MAX_RECORD_SECONDS * 1000) / VAD_FRAME_MS)

    recorded_frames = []
    speech_streak = 0
    has_spoken = False
    recent_frames = deque(maxlen=window_size)

    stream = sd.InputStream(samplerate=VOICE_SAMPLE_RATE, channels=1, dtype="int16")
    stream.start()
    try:
        for _ in range(max_frames):
            data, _ = stream.read(frame_size)
            data = data.flatten()
            recorded_frames.append(data)

            is_speech = vad.is_speech(data.tobytes(), VOICE_SAMPLE_RATE)
            recent_frames.append(is_speech)

            if is_speech:
                speech_streak += 1
                if speech_streak >= VAD_MIN_SPEECH_FRAMES:
                    has_spoken = True
            else:
                speech_streak = 0

            if has_spoken and len(recent_frames) == window_size:
                speech_ratio = sum(recent_frames) / window_size
                if speech_ratio <= VAD_SILENCE_TOLERANCE:
                    break
    finally:
        stream.stop()
        stream.close()

    if not recorded_frames:
        return np.array([], dtype=np.float32)

    audio_int16 = np.concatenate(recorded_frames)
    return (audio_int16.astype(np.float32) / 32768.0)


def _record_until_silence_energy():
    silence_threshold = calibrate_ambient_noise()
    noise_floor = silence_threshold / 4
    chunk_size = int(VOICE_SAMPLE_RATE * CHUNK_DURATION)
    window_size = max(1, int(SILENCE_DURATION / CHUNK_DURATION))
    max_chunks = int(MAX_RECORD_SECONDS / CHUNK_DURATION)

    recorded_chunks = []
    loud_streak = 0
    has_spoken = False
    recent_chunks = deque(maxlen=window_size)

    stream = sd.InputStream(samplerate=VOICE_SAMPLE_RATE, channels=1, dtype="float32")
    stream.start()
    try:
        for _ in range(max_chunks):
            data, _ = stream.read(chunk_size)
            data = data.flatten()
            recorded_chunks.append(data)

            loudness = _rms(data)
            if not has_spoken or loudness < noise_floor * 2:
                noise_floor = 0.95 * noise_floor + 0.05 * loudness

            dynamic_threshold = max(noise_floor * 3, silence_threshold)
            is_loud = loudness > dynamic_threshold
            recent_chunks.append(is_loud)

            if is_loud:
                loud_streak += 1
                if loud_streak >= 2:
                    has_spoken = True
            else:
                loud_streak = 0

            if has_spoken and len(recent_chunks) == window_size:
                if (sum(recent_chunks) / window_size) <= VAD_SILENCE_TOLERANCE:
                    break
    finally:
        stream.stop()
        stream.close()

    if not recorded_chunks:
        return np.array([], dtype=np.float32)

    return np.concatenate(recorded_chunks)


def transcribe_audio_sherpa(samples, sample_rate: int = 16000, language: str = "English", denoise: bool = True) -> str:
    """Transcribes float32 PCM samples into text, routing to Parakeet or
    Whisper depending on language. When denoise=True (default), audio is
    passed through Sherpa-ONNX's DPDFNet speech denoiser first."""
    recognizer = get_sherpa_asr_recognizer(language=language)
    if recognizer is None:
        return ""

    try:
        samples_np = np.array(samples, dtype=np.float32)

        if denoise:
            samples_np, sample_rate = denoise_audio(samples_np, sample_rate)

        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples_np)
        recognizer.decode_stream(stream)

        result_text = stream.result.text.strip()

        # Clean common Whisper subtitle hallucination artifacts
        hallucinations = [
            r"\(speaking in foreign language\)",
            r"\(speaking foreign language\)",
            r"\(foreign language\)",
            r"\[speaking foreign language\]",
            r"\(music\)",
            r"\(blank_audio\)"
        ]
        for pattern in hallucinations:
            result_text = re.sub(pattern, "", result_text, flags=re.IGNORECASE).strip()

        print(f"[STT Success] Recognized ({language}): '{result_text}'")
        return result_text

    except Exception as e:
        print(f"[Sherpa ASR Runtime Error] {e}")
        return ""


def listen_for_answer(language):
    print("\n🎙️  Listening... speak your answer, then pause when you're done.")
    audio = record_until_silence()

    if audio.size == 0:
        return ""

    print("Transcribing with Sherpa-ONNX...")
    text = transcribe_audio_sherpa(audio)
    print(f"You said: {text}")
    return text


# ============================================================
# SHERPA-ONNX: TEXT-TO-SPEECH (TTS)
# ============================================================

# Cache for multi-language TTS engines
_sherpa_tts_engines = {}

def get_sherpa_tts_engine(language: str = "English"):
    """Loads and caches language-specific Sherpa-ONNX TTS engines."""
    global _sherpa_tts_engines
    
    lang_key = language.lower()
    if lang_key in _sherpa_tts_engines:
        return _sherpa_tts_engines[lang_key]

    if not SHERPA_ONNX_AVAILABLE:
        print("[TTS Error] sherpa_onnx package unavailable.")
        return None

    # Switch directories based on language parameter
    if lang_key == "vietnamese":
        model_dir = (BASE_DIR / "sherpa_models" / "tts_vi").resolve()
    else:
        model_dir = (BASE_DIR / "sherpa_models" / "tts").resolve()

    model_path = model_dir / "model.onnx"
    tokens_path = model_dir / "tokens.txt"
    data_dir_path = model_dir / "espeak-ng-data"

    if not model_path.exists():
        print(f"[TTS Error] Model file missing at: {model_path}")
        return None

    # VITS Piper configuration with espeak-ng data support
    tts_config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(model_path),
                tokens=str(tokens_path),
                lexicon="",
                data_dir=str(data_dir_path) if data_dir_path.exists() else "",
            )
        )
    )

    engine = sherpa_onnx.OfflineTts(tts_config)
    _sherpa_tts_engines[lang_key] = engine
    print(f"[TTS Initialized] Loaded Sherpa-ONNX model for '{language}'")
    return engine


def synthesize_sherpa_wav(text: str, language: str = "English") -> bytes:
    """Synthesizes text into 16-bit PCM WAV bytes using the requested language model."""
    tts = get_sherpa_tts_engine(language)
    if tts is None:
        return None

    try:
        audio = tts.generate(text, sid=0, speed=1.0)
        if not audio or len(audio.samples) == 0:
            return None

        samples = np.array(audio.samples, dtype=np.float32)
        samples_int16 = (samples * 32767).clip(-32768, 32767).astype(np.int16)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(audio.sample_rate)
            wav_file.writeframes(samples_int16.tobytes())

        buffer.seek(0)
        return buffer.read()

    except Exception as e:
        print(f"[Sherpa TTS Error] {e}")
        return None

def speak(text, language=None):
    """Speaks text using Sherpa-ONNX in CLI terminal mode."""
    if not text:
        return

    tts = get_sherpa_tts_engine()
    if tts:
        try:
            audio = tts.generate(text, sid=0, speed=1.0)
            samples = np.array(audio.samples, dtype=np.float32)
            sd.play(samples, audio.sample_rate)
            sd.wait()
            return
        except Exception as e:
            print(f"\n(Sherpa-ONNX TTS playback failed: {e})")


def ask_interview_mode():
    print("\nInterview mode:")
    print("  1. Text  (type answers)")
    print("  2. Voice (Sherpa-ONNX STT/TTS local offline mode)")

    if not VOICE_AVAILABLE:
        print("  (Voice mode unavailable. Install dependencies with: pip install sherpa-onnx sounddevice numpy)")
        return False

    choice = input("Choose mode [1/2]: ").strip()
    return choice == "2"


def find_question_file(candidate_name, language):
    target_candidate = flatten_text(candidate_name)
    target_language = flatten_text(language)

    search_roots = [BASE_DIR, BASE_DIR.parent, BASE_DIR.parent.parent]
    matching_dirs = []
    for root in search_roots:
        if root.exists():
            for d in root.rglob("*"):
                if d.is_dir():
                    folder_flat = flatten_text(d.name)
                    if folder_flat and (folder_flat == target_candidate or target_candidate in folder_flat):
                        matching_dirs.append(d)

    matching_dirs = list(set(matching_dirs))
    if not matching_dirs:
        return None

    for folder in matching_dirs:
        for file in folder.rglob("*.json"):
            file_flat = flatten_text(file.name)
            if target_candidate in file_flat and target_language in file_flat and "questions" in file_flat:
                return file

    return None


def get_question_file():
    print("=== AI Interview Chatbot ===\n")
    candidate_name = input("Candidate name: ").strip()
    language = input("Interview language: ").strip()

    question_file = find_question_file(candidate_name, language)
    if question_file is None:
        print(f"\nERROR: Question file not found for {candidate_name}.")
        return None, candidate_name, language

    print(f"\nQuestion file found: {question_file.name}")
    return question_file, candidate_name, language


def load_questions(question_file):
    try:
        with open(question_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Question file not found: {question_file}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in question file: {question_file}\nError: {e}")


def extract_questions(data):
    questions = data.get("questions", [])
    all_questions = []

    if isinstance(questions, list):
        for index, question in enumerate(questions, start=1):
            all_questions.append({
                "question_number": index,
                "category": question.get("category"),
                "question": question.get("question"),
                "difficulty": question.get("difficulty"),
                "topic": question.get("topic")
            })
    elif isinstance(questions, dict):
        for category, category_questions in questions.items():
            for question in category_questions:
                all_questions.append({
                    "category": category,
                    "question": question.get("question"),
                    "difficulty": question.get("difficulty"),
                    "topic": question.get("topic")
                })
    else:
        raise ValueError("Invalid 'questions' format in interview_questions.json")

    return all_questions


def generate_follow_up(candidate_name, language, current_question, answer, previous_answers):
    history = "\n".join(f"Q: {item['question']}\nA: {item['answer']}" for item in previous_answers)
    prompt = f"""
You are conducting a professional technical interview.
Candidate: {candidate_name}
Interview language: {language}
Previous interview history:
{history}
Current question:
{current_question}
Candidate's answer:
{answer}

Based on the candidate's answer, decide whether a follow-up question would meaningfully improve the interview.
If a follow-up is useful:
- Ask exactly ONE follow-up question.
- Make it directly related to the candidate's answer.
- Keep it concise.
- Write the question entirely in {language}.

If no follow-up is useful, respond with exactly: NO_FOLLOW_UP
Otherwise, respond with ONLY the follow-up question.
"""

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": "You are a professional technical interviewer."},
            {"role": "user", "content": prompt}
        ],
        think=False,
        keep_alive="30m"  # Same model as correct_transcript — keep it warm between the two call sites too.
    )

    result = response["message"]["content"].strip()
    if "<think>" in result:
        result = result.split("</think>")[-1].strip()

    return None if result == "NO_FOLLOW_UP" else result


def correct_transcript(raw_text: str, question_context: str = "", language: str = "English") -> str:
    """Runs a raw STT transcript through Ollama to fix likely speech-recognition
    errors — including words the ASR mangled into something nonsensical
    (e.g. "Mehemetic" instead of "mathematics") — without changing the
    candidate's actual meaning. Uses reasoning mode (think=True) since
    catching a garbled word and inferring the real one benefits from
    actual deliberation, not a single fast pass. Always falls back to the
    raw text on any error, since a failed cleanup pass should never lose
    the answer."""
    if not raw_text or not raw_text.strip():
        return raw_text

    prompt = f"""You are cleaning up a speech-to-text transcript from a job interview.

The speech recognizer sometimes outputs a real-looking but nonsensical or
made-up word in place of what the candidate actually said — for example
"Mehemetic" instead of "mathematics", or "artificial incoming sense"
instead of "artificial intelligence". Your job is to catch these and
repair them.

Question asked: {question_context or "(not provided)"}
Raw transcript: {raw_text}

Work through this carefully:
1. Scan the transcript for any word or short phrase that is NOT a real,
   dictionary-recognized word in {language}, or that doesn't make sense
   in context — even if it looks superficially plausible at a glance.
2. For each one you find, work out what the candidate most likely actually
   said, based on (a) how it would sound if mispronounced or misheard by
   an ASR system, and (b) what fits the meaning of the surrounding
   sentence and the question asked.
3. Replace it with that word. Do not change anything else about the
   candidate's meaning, and do not invent new content beyond what the
   original transcript implied.
4. Also fix missing punctuation and run-on sentences, and remove filler
   words like "um" or "uh" — but never alter substantive content.

Respond entirely in {language}. Output ONLY the corrected transcript, with
no preamble, explanation, reasoning, or quotation marks."""

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": "You are a careful transcript editor. You reason step by step before answering, but your final output is only the corrected transcript — never your reasoning."},
                {"role": "user", "content": prompt}
            ],
            think=True,
            # Keeps the model resident in memory between requests. Without this,
            # Ollama's default 5-minute idle timeout can unload an 8B model
            # between answers (candidate is still talking/thinking), and the
            # *next* correction pays a full reload before it even starts
            # reasoning. This only affects memory residency, not reasoning
            # depth or output quality.
            keep_alive="30m"
        )
        result = response["message"]["content"].strip()
        if "<think>" in result:
            result = result.split("</think>")[-1].strip()
        return result or raw_text
    except Exception as e:
        print(f"[Transcript Correction Error] {e}")
        return raw_text


def get_confirmed_answer(voice_mode=False, language=None):
    while True:
        if voice_mode:
            answer = listen_for_answer(language)
            if not answer.strip():
                fallback = input("Could not hear an answer. Press Enter to retry or type answer: ").strip()
                if fallback.lower() == "quit":
                    return None
                if fallback:
                    answer = fallback
                else:
                    continue
        else:
            answer = input("Your answer: ")

        if answer.strip().lower() == "quit":
            return None

        print(f"\nYour answer: {answer}\n")
        confirmation = input("Are you sure this is your answer? (yes/no): ").strip().lower()
        if confirmation in ["yes", "y"]:
            return answer
        elif confirmation in ["no", "n"]:
            print("\nPlease enter your answer again.\n")


def run_interview(candidate_name, language, questions, voice_mode=False):
    answers = []
    base_question_index = 0
    total_question_count = 0

    while total_question_count < MAX_QUESTIONS and base_question_index < len(questions):
        question_data = questions[base_question_index]
        question = question_data["question"]

        print(f"\nQuestion {total_question_count + 1}:")
        print(question)
        speak(question, language)

        answer = get_confirmed_answer(voice_mode=voice_mode, language=language)

        answers.append({
            "question_number": total_question_count + 1,
            "type": "predefined",
            "category": question_data.get("category"),
            "difficulty": question_data.get("difficulty"),
            "topic": question_data.get("topic"),
            "question": question,
            "answer": answer
        })

        total_question_count += 1
        base_question_index += 1

        if total_question_count >= MAX_QUESTIONS:
            break

        follow_up = generate_follow_up(
            candidate_name=candidate_name,
            language=language,
            current_question=question,
            answer=answer,
            previous_answers=answers[:-1]
        )

        if follow_up:
            print("\nFollow-up question:")
            print(follow_up)
            speak(follow_up, language)

            follow_up_answer = get_confirmed_answer(voice_mode=voice_mode, language=language)
            answers.append({
                "question_number": total_question_count + 1,
                "type": "follow_up",
                "category": question_data.get("category"),
                "difficulty": question_data.get("difficulty"),
                "topic": question_data.get("topic"),
                "question": follow_up,
                "answer": follow_up_answer
            })
            total_question_count += 1

    return answers


def save_answers(candidate_name, answers, questions_file, interview_language):
    output = {
        "candidate": candidate_name,
        "source_questions": questions_file.name,
        "interview_language": interview_language,
        "interview_date": datetime.now().isoformat(),
        "total_answered": len(answers),
        "answers": answers
    }

    output_filename = f"{flatten_text(candidate_name)}_answers.json"
    output_path = questions_file.parent / output_filename

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=4, ensure_ascii=False)

    print(f"\nAnswers saved to: {output_path}")
    return output_path


def main():
    question_file, candidate_name, language = get_question_file()
    if question_file is None:
        return

    questions_data = load_questions(question_file)
    questions = extract_questions(questions_data)
    if not questions:
        print("ERROR: No questions found.")
        return

    voice_mode = ask_interview_mode()
    if voice_mode:
        get_sherpa_asr_recognizer()
        get_sherpa_tts_engine()  # Pre-load TTS engine during setup

    answers = run_interview(candidate_name, language, questions, voice_mode=voice_mode)
    save_answers(candidate_name, answers, question_file, language)


if __name__ == "__main__":
    main()