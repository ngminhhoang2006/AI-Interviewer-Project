import json
import ollama
from pathlib import Path
from datetime import datetime
from collections import deque
import re
import unicodedata
import threading
import io
import wave
import numpy as np

try:
    import sounddevice as sd
    import numpy as np
    _VOICE_CORE_AVAILABLE = True
except ImportError:
    _VOICE_CORE_AVAILABLE = False

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

# Optional fallback denoiser: weak on non-stationary noise (voices, traffic), fine for steady hum.
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

VAD_FRAME_MS = 30
VAD_AGGRESSIVENESS = 3
VAD_MIN_SPEECH_FRAMES = 3
VAD_SILENCE_TOLERANCE = 0.15

_sherpa_asr_recognizer = None
_sherpa_tts_engine = None
_sherpa_tts_lock = threading.Lock()

# DPDFNet (ONNX export of DeepFilterNet) via sherpa_onnx, so no torch dependency.
_sherpa_denoiser = None

# Languages served by Parakeet-TDT 0.6B v3. Only add one that Parakeet v3 supports;
# Vietnamese is not supported and stays on Whisper.
PARAKEET_LANGUAGES = {
    "english", "spanish", "french", "german", "italian",
    "portuguese", "polish", "russian", "ukrainian",
}

# Whisper handles every language not in PARAKEET_LANGUAGES.
WHISPER_LANG_CODES = {
    "english": "en", "vietnamese": "vi", "spanish": "es", "french": "fr",
    "german": "de", "italian": "it", "portuguese": "pt", "russian": "ru",
    "hindi": "hi", "indonesian": "id", "chinese": "zh", "arabic": "ar",
    "turkish": "tr", "polish": "pl", "ukrainian": "uk",
    # No offline voice for these (browser voice is used), but Whisper can transcribe them
    "japanese": "ja", "korean": "ko", "thai": "th",
}

# Other languages use sherpa_models/tts_<language>/ if download_models.py installed it.
TTS_FOLDERS = {"english": "tts", "vietnamese": "tts_vi"}
# Languages without a dedicated Piper/MMS voice folder are spoken by the multilingual
# Supertonic 3 model (sherpa_models/tts_supertonic/) using these language codes.
SUPERTONIC_FOLDER = "tts_supertonic"
SUPERTONIC_LANG_CODES = {
    "japanese": "ja", "korean": "ko", "ukrainian": "uk", "arabic": "ar", "turkish": "tr",
    "polish": "pl", "spanish": "es", "french": "fr", "german": "de", "italian": "it",
    "portuguese": "pt", "russian": "ru", "hindi": "hi", "indonesian": "id",
    "vietnamese": "vi", "english": "en",
}
SUPERTONIC_SPEAKER = 6      # the model has 10 voices (0-9)


def flatten_text(text: str) -> str:
    """Strips diacritics and non-alphanumeric characters for comparisons."""
    text = text.replace("\u00a0", " ").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]", "", stripped.casefold())


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
            # Model files missing or failed to load; Whisper keeps the app working.
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
    target_lang = WHISPER_LANG_CODES.get(language.lower().strip(), "en")

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


# noisereduce can over-subtract on clean recordings and hurt accuracy, so it is off by default.
# Enable only if your recording environment is genuinely noisy.
FALL_BACK_TO_NOISEREDUCE = False


def _normalize_peak(samples: np.ndarray, target_peak: float = 0.98) -> np.ndarray:
    """Scales audio down when its peak exceeds target_peak. Unlike hard clipping, this keeps the waveform shape."""
    peak = float(np.abs(samples).max()) if samples.size else 0.0
    if peak > target_peak:
        samples = samples * (target_peak / peak)
    return samples


def _estimate_noise_floor(samples: np.ndarray, sample_rate: int, frame_ms: int = 20) -> float:
    """Average RMS of the quietest 10% of short frames. Used to skip denoising on clean
    recordings, where it over-suppresses consonants ('mathematics' became 'Mehemetic')."""
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


# Recordings with a noise floor below this skip denoising, because DPDFNet and noisereduce
# over-suppressed clean, close-mic audio. Raise it if noisy clips slip through, lower it if clean ones degrade.
NOISE_FLOOR_SKIP_THRESHOLD = 0.01

# Recordings whose loudest sample is below this are treated as silence (no mic signal).
MIN_SPEECH_PEAK = 0.005


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
    """Suppresses noise on float32 mono audio in [-1, 1]. Tries DPDFNet, then noisereduce
    (only if FALL_BACK_TO_NOISEREDUCE), then returns the audio unmodified, so it is safe to call.
    Returns (samples, sample_rate) because the denoiser may change the rate."""
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

        # Whisper "hears" music/subtitles in silence, so check the level first.
        duration = samples_np.size / float(sample_rate or 16000)
        peak = float(np.abs(samples_np).max()) if samples_np.size else 0.0
        print(f"[STT] Audio: {duration:.1f}s, peak level {peak:.3f}, rms {_rms(samples_np):.4f}")
        if duration < 0.3 or peak < MIN_SPEECH_PEAK:
            print("[STT] Recording is empty or silent (check the microphone / input volume); skipping.")
            return ""

        if denoise:
            samples_np, sample_rate = denoise_audio(samples_np, sample_rate)

        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples_np)
        recognizer.decode_stream(stream)

        result_text = stream.result.text.strip()

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

        # Whisper labels non-speech in the language being decoded, e.g. "(音楽)", "[Música]",
        # "(Musik)", "♪". If nothing but such tags is left, there was no speech at all.
        if not re.sub(r"[\(\[（【][^\)\]）】]{0,40}[\)\]）】]|[♪♫♬\s.。…,、]", "", result_text):
            result_text = ""

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
    text = transcribe_audio_sherpa(audio, language=language)
    print(f"You said: {text}")
    return text


_sherpa_tts_engines = {}
# Why the offline voice was not used for a language (shown in the browser console via /api/tts)
TTS_LAST_ERROR = {}

_supertonic_engine = None
_tts_supertonic_lang = {}   # lang_key -> Supertonic language code, for languages served by Supertonic


def _load_vits_voice(model_dir, lang_key, language):
    """Piper / MMS voice folder (model.onnx + tokens.txt [+ espeak-ng-data]). Returns an engine or None."""
    model_path = model_dir / "model.onnx"
    tokens_path = model_dir / "tokens.txt"
    data_dir_path = model_dir / "espeak-ng-data"
    if not model_path.exists():
        return None

    # Character-based Piper voices ("phoneme_type": "text", e.g. the old Ukrainian one) can't be run
    # by sherpa-onnx's espeak frontend: they load but produce near-silent audio. Skip those.
    for cfg_file in model_dir.glob("*.onnx.json"):
        try:
            if json.loads(cfg_file.read_text(encoding="utf-8")).get("phoneme_type") == "text":
                print(f"[TTS] Voice in {model_dir} is character-based and unsupported; skipping it.")
                return None
        except (OSError, ValueError):
            pass

    try:
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
        print(f"[TTS Initialized] Loaded Sherpa-ONNX voice for '{language}' ({model_dir.name})")
        return engine
    except Exception as e:  # noqa: BLE001 - a broken voice must fall back, not crash the request
        TTS_LAST_ERROR[lang_key] = f"Could not load voice from {model_dir}: {e}"
        print(f"[TTS Error] Could not load the '{language}' voice from {model_dir}: {e}")
        return None


def _load_supertonic():
    """Multilingual Supertonic 3 model (shared by every language it serves). Returns an engine or None."""
    global _supertonic_engine
    if _supertonic_engine is not None:
        return _supertonic_engine
    d = (BASE_DIR / "sherpa_models" / SUPERTONIC_FOLDER).resolve()
    if not (d / "vocoder.int8.onnx").exists():
        return None
    if not hasattr(sherpa_onnx, "OfflineTtsSupertonicModelConfig"):
        print("[TTS] Installed sherpa-onnx is too old for Supertonic. Run: pip install -U sherpa-onnx")
        return None
    try:
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
                    duration_predictor=str(d / "duration_predictor.int8.onnx"),
                    text_encoder=str(d / "text_encoder.int8.onnx"),
                    vector_estimator=str(d / "vector_estimator.int8.onnx"),
                    vocoder=str(d / "vocoder.int8.onnx"),
                    tts_json=str(d / "tts.json"),
                    unicode_indexer=str(d / "unicode_indexer.bin"),
                    voice_style=str(d / "voice.bin"),
                ),
                num_threads=2,
                provider="cpu",
            )
        )
        _supertonic_engine = sherpa_onnx.OfflineTts(cfg)
        print("[TTS Initialized] Loaded Supertonic 3 multilingual voice")
        return _supertonic_engine
    except Exception as e:  # noqa: BLE001
        print(f"[TTS Error] Could not load Supertonic from {d}: {e}")
        return None


def get_sherpa_tts_engine(language: str = "English"):
    """Loads and caches the offline voice for a language: its own folder first
    (tts, tts_vi, tts_spanish, tts_thai ...), then the multilingual Supertonic model.
    Returns None if neither exists, so the browser voice is used instead."""
    lang_key = language.lower().strip()
    if lang_key in _sherpa_tts_engines:
        return _sherpa_tts_engines[lang_key]

    if not SHERPA_ONNX_AVAILABLE:
        print("[TTS Error] sherpa_onnx package unavailable.")
        return None

    folder = TTS_FOLDERS.get(lang_key, f"tts_{lang_key}")
    engine = _load_vits_voice((BASE_DIR / "sherpa_models" / folder).resolve(), lang_key, language)

    if engine is None and lang_key in SUPERTONIC_LANG_CODES:
        engine = _load_supertonic()
        if engine is not None:
            _tts_supertonic_lang[lang_key] = SUPERTONIC_LANG_CODES[lang_key]

    if engine is None:
        if lang_key not in TTS_LAST_ERROR:
            TTS_LAST_ERROR[lang_key] = (f"No offline voice for {language} "
                                        f"(install with: python system/download_models.py)")
        print(f"[TTS] {TTS_LAST_ERROR[lang_key]}; using the browser voice.")
        return None

    TTS_LAST_ERROR.pop(lang_key, None)
    _sherpa_tts_engines[lang_key] = engine
    return engine


def _generate_audio(tts, lang_key, text):
    """Runs the right generate() call for a Piper/MMS voice or for Supertonic."""
    code = _tts_supertonic_lang.get(lang_key)
    if code:
        gen = sherpa_onnx.GenerationConfig()
        gen.sid = SUPERTONIC_SPEAKER
        gen.num_steps = 8
        gen.speed = 1.0
        gen.extra["lang"] = code
        return tts.generate(text, gen)
    return tts.generate(text, sid=0, speed=1.0)


def synthesize_sherpa_wav(text: str, language: str = "English") -> bytes:
    """Synthesizes text into 16-bit PCM WAV bytes using the requested language model."""
    tts = get_sherpa_tts_engine(language)
    if tts is None:
        return None

    try:
        audio = _generate_audio(tts, language.lower().strip(), text)
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
        TTS_LAST_ERROR[language.lower().strip()] = f"Synthesis failed: {e}"
        print(f"[Sherpa TTS Error] {e}")
        return None

def speak(text, language=None):
    """Speaks text using Sherpa-ONNX in CLI terminal mode."""
    if not text:
        return

    tts = get_sherpa_tts_engine(language or "English")
    if tts:
        try:
            audio = _generate_audio(tts, (language or "English").lower().strip(), text)
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
        keep_alive="30m"
    )

    result = response["message"]["content"].strip()
    if "<think>" in result:
        result = result.split("</think>")[-1].strip()

    return None if result == "NO_FOLLOW_UP" else result


def correct_transcript(raw_text: str, question_context: str = "", language: str = "English") -> str:
    """Fixes likely speech-recognition errors in a raw transcript (e.g. "Mehemetic" for
    "mathematics") without changing the candidate's meaning. Uses think=True so the model can
    reason about garbled words. Returns raw_text on any error so a failed cleanup never loses the answer."""
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
            # Ollama unloads idle models after 5 minutes; a reload mid-interview delays the next correction.
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
        get_sherpa_asr_recognizer(language)
        get_sherpa_tts_engine(language)  # Pre-load TTS engine during setup

    answers = run_interview(candidate_name, language, questions, voice_mode=voice_mode)
    save_answers(candidate_name, answers, question_file, language)


if __name__ == "__main__":
    main()