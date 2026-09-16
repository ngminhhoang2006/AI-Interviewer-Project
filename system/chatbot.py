import json
import ollama
from pathlib import Path
from datetime import datetime
from collections import deque
import re
import unicodedata
import os
import sys
import importlib.util
import tempfile
import threading


def _ensure_nvidia_lib_paths():
    """
    pip-installed nvidia-cublas-cu12 / nvidia-cudnn-cu12 wheels put their
    CUDA library files inside site-packages, but neither Linux nor modern
    Windows will find them there automatically - each OS needs a different
    fix, since they load shared libraries completely differently.
    """
    if sys.platform.startswith("linux"):
        _ensure_nvidia_lib_paths_linux()
    elif sys.platform.startswith("win"):
        _ensure_nvidia_lib_paths_windows()
    # macOS: NVIDIA dropped CUDA driver support there years ago, so GPU
    # acceleration isn't available regardless - nothing to do, CPU is used.


def _find_nvidia_pkg_dirs(pkg_names):
    """Return the on-disk folders (if any) for the given nvidia.* sub-packages."""
    dirs = []
    for pkg in pkg_names:
        try:
            spec = importlib.util.find_spec(pkg)
            if spec and spec.submodule_search_locations:
                dirs.extend(spec.submodule_search_locations)
        except (ImportError, ValueError, ModuleNotFoundError):
            continue
    return dirs


def _ensure_nvidia_lib_paths_linux():
    """
    Linux: pip puts the .so files in site-packages/nvidia/*/lib, but the
    dynamic linker only looks in LD_LIBRARY_PATH or system lib directories.

    IMPORTANT: glibc's dynamic linker parses LD_LIBRARY_PATH once, when a
    process starts, and caches it internally - so setting
    os.environ["LD_LIBRARY_PATH"] from *inside* an already-running Python
    process has NO effect on later dlopen() calls in that same process.
    The only reliable fix is to set the variable and then restart the
    process, so the new process's dynamic linker picks it up from the
    very start. We do that automatically, once, guarded by an env var
    so it can't loop.
    """
    if os.environ.get("_CHATBOT_NVIDIA_LIBS_PATCHED") == "1":
        return  # already patched and restarted once - don't do it again

    lib_dirs = _find_nvidia_pkg_dirs(["nvidia.cublas.lib", "nvidia.cudnn.lib"])
    if not lib_dirs:
        return  # packages not installed - nothing to add; CPU fallback handles the rest

    existing = os.environ.get("LD_LIBRARY_PATH", "")
    new_dirs = ":".join(lib_dirs)
    combined = f"{new_dirs}:{existing}" if existing else new_dirs

    if combined == existing:
        return  # already present somehow - nothing to fix

    os.environ["LD_LIBRARY_PATH"] = combined
    os.environ["_CHATBOT_NVIDIA_LIBS_PATCHED"] = "1"

    print("(Found local CUDA libraries for faster-whisper; restarting once to apply LD_LIBRARY_PATH...)")
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        pass  # if re-exec fails for any reason, keep going - CPU fallback still works


def _ensure_nvidia_lib_paths_windows():
    """
    Windows: pip puts the .dll files in site-packages\\nvidia\\*\\bin (a
    "bin" folder, unlike Linux's "lib"). Since Python 3.8, Windows no
    longer implicitly searches PATH for DLL dependencies (a security
    change) - directories must be explicitly registered with
    os.add_dll_directory(). Unlike Linux, this takes effect immediately
    for the current process, so no restart is needed here.
    """
    dll_dirs = _find_nvidia_pkg_dirs([
        "nvidia.cublas.bin",
        "nvidia.cudnn.bin",
        "nvidia.cuda_runtime.bin",
    ])

    for path in dll_dirs:
        try:
            os.add_dll_directory(path)
        except (FileNotFoundError, OSError):
            continue


_ensure_nvidia_lib_paths()

# ------------------------------------------------------------
# Voice mode dependencies (all fully offline / local)
#
#   Recommended (GPU, faster + lets you use a bigger/more accurate model):
#     pip install faster-whisper sounddevice numpy pyttsx3 webrtcvad
#
#   Fallback (CPU-only or if faster-whisper doesn't install cleanly):
#     pip install openai-whisper sounddevice numpy pyttsx3 webrtcvad
#
# Notes:
#   - faster-whisper (CTranslate2) runs the same Whisper models several
#     times faster than openai-whisper on GPU, which means a bigger,
#     more accurate model (e.g. "small"/"medium") can run in about the
#     same time "base" took before. Requires an NVIDIA GPU + CUDA/cuDNN.
#     If GPU init fails for any reason, it automatically falls back to
#     CPU (int8) so the app still works, just slower.
#   - openai-whisper is used automatically instead if faster-whisper
#     isn't installed - same models, just slower, especially on CPU.
#   - pyttsx3 does text-to-speech using the OS's built-in voices
#     (SAPI5 on Windows, NSSpeechSynthesizer on macOS, espeak on Linux).
#     On Linux you may also need: sudo apt install espeak
#   - sounddevice/numpy are used to record from the microphone.
#   - webrtcvad detects when the candidate is actually speaking (as
#     opposed to just "loud"), so steady background noise like a fan
#     or AC unit doesn't get mistaken for speech and prevent the
#     recording from ever stopping. If it's not installed, we fall
#     back to a noise-adaptive loudness threshold instead. If
#     `pip install webrtcvad` fails to build on your platform, try
#     `pip install webrtcvad-wheels` instead (same API, prebuilt wheels).
# ------------------------------------------------------------
# ------------------------------------------------------------
# Voice mode dependencies
# ------------------------------------------------------------
try:
    import sounddevice as sd
    import numpy as np
    _VOICE_CORE_AVAILABLE = True
except ImportError:
    _VOICE_CORE_AVAILABLE = False

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False

try:
    from kokoro_onnx import Kokoro
    KOKORO_AVAILABLE = True
except ImportError:
    KOKORO_AVAILABLE = False

_tts_engine = None
_kokoro_engine = None
_USING_KOKORO = False

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False

OPENAI_WHISPER_AVAILABLE = False
if not FASTER_WHISPER_AVAILABLE:
    try:
        import whisper
        OPENAI_WHISPER_AVAILABLE = True
    except ImportError:
        OPENAI_WHISPER_AVAILABLE = False

VOICE_AVAILABLE = _VOICE_CORE_AVAILABLE and (FASTER_WHISPER_AVAILABLE or OPENAI_WHISPER_AVAILABLE)

try:
    import webrtcvad
    VAD_AVAILABLE = True
except ImportError:
    VAD_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent

OLLAMA_MODEL = "qwen3:8b"
MAX_QUESTIONS = 10

# Voice mode config
# "small" is noticeably more accurate than "base" and, via faster-whisper on
# GPU, transcribes about as fast (often faster). If you're on the openai-whisper
# CPU fallback, consider dropping this back to "base" for speed.
WHISPER_MODEL_SIZE = "small"    # tiny/base/small/medium/large-v3 - bigger = more accurate, slower
WHISPER_DEVICE = "cuda"         # faster-whisper only; automatically falls back to "cpu" if this fails
WHISPER_COMPUTE_TYPE = "float16"  # faster-whisper only; good default for GPU (use "int8" for CPU-only)
VOICE_SAMPLE_RATE = 16000       # required sample rate for whisper (also valid for webrtcvad)
SILENCE_DURATION = 1.5          # seconds of quiet before we assume the candidate is done talking
CHUNK_DURATION = 0.5            # seconds per audio chunk analyzed for silence (energy fallback only)
MAX_RECORD_SECONDS = 120        # hard cap so a stuck mic doesn't hang forever

# webrtcvad config (used when VAD_AVAILABLE)
VAD_FRAME_MS = 30               # must be 10, 20, or 30 ms per webrtcvad's spec
VAD_AGGRESSIVENESS = 3          # 0 = catches more speech, 3 = filters more noise (max out if noise still leaks through)
VAD_MIN_SPEECH_FRAMES = 3       # ~90ms of continuous speech before we count the candidate as "started talking"
VAD_SILENCE_TOLERANCE = 0.15    # allow up to 15% of frames in the silence window to be misclassified as speech
                                 # (e.g. by a fan, computer hum, or AGC hiss) without resetting the whole countdown

# Best-effort mapping from language names (as typed by the user) to
# Whisper language codes. If not found, Whisper will auto-detect.
LANGUAGE_CODE_MAP = {
    "english": "en",
    "vietnamese": "vi",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "portuguese": "pt",
    "italian": "it",
    "russian": "ru",
    "thai": "th",
}

# Lazily-initialized singletons (loading these is slow, so only do it once)
_whisper_model = None
_whisper_device_used = None  # tracks which device the loaded model actually ended up on
_tts_engine = None

def flatten_text(text: str) -> str:
    """
    Strips diacritics, converts Vietnamese đ/Đ, handles non-breaking spaces,
    and removes ALL non-alphanumeric characters for clean string comparison.
    """
    # Replace non-breaking spaces and Vietnamese Đ/đ
    text = text.replace("\u00a0", " ").replace("Đ", "D").replace("đ", "d")
    
    # Strip diacritics
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    
    # Keep only pure lowercase letters and numbers
    return re.sub(r"[^a-z0-9]", "", stripped.casefold())


# ============================================================
# VOICE MODE: SPEECH-TO-TEXT (recording + Whisper)
# ============================================================

def get_whisper_model(force_device=None):
    """
    Load the local speech recognition model once and reuse it. Prefers
    faster-whisper on GPU (fast enough to afford a bigger/more accurate
    model); falls back to CPU, then to openai-whisper, automatically.

    force_device lets transcribe_audio() force a reload onto a different
    device (e.g. "cpu") if GPU inference fails partway through a session,
    which can happen even after a successful model load - CTranslate2
    loads some CUDA libraries (like cuBLAS) lazily, on first actual use.
    """
    global _whisper_model, _whisper_device_used

    if _whisper_model is not None and force_device is None:
        return _whisper_model

    if FASTER_WHISPER_AVAILABLE:
        device = force_device or WHISPER_DEVICE
        compute_type = WHISPER_COMPUTE_TYPE if device == "cuda" else "int8"
        try:
            print(f"\n(Loading faster-whisper model '{WHISPER_MODEL_SIZE}' on {device.upper()}...)")
            _whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device=device,
                compute_type=compute_type,
            )
            _whisper_device_used = device
        except Exception as e:
            if device != "cpu":
                print(f"(GPU load failed ({e}) - falling back to CPU...)")
                _whisper_model = WhisperModel(
                    WHISPER_MODEL_SIZE,
                    device="cpu",
                    compute_type="int8",
                )
                _whisper_device_used = "cpu"
            else:
                raise
    else:
        print(f"\n(Loading openai-whisper model '{WHISPER_MODEL_SIZE}', first time only...)")
        _whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
        _whisper_device_used = "cpu"  # openai-whisper picks its own device internally

    return _whisper_model


def _rms(audio_chunk):
    """Root-mean-square loudness of a float32 audio chunk."""
    if audio_chunk.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio_chunk))))


def calibrate_ambient_noise(duration=1.0):
    """
    Record a short snippet of ambient silence so we can set a mic-specific
    silence threshold instead of a hardcoded number that may not fit
    everyone's microphone/room. Only used by the energy-based fallback -
    the VAD path doesn't need this.
    """
    print("Calibrating microphone... please stay quiet for a moment.")
    recording = sd.rec(
        int(duration * VOICE_SAMPLE_RATE),
        samplerate=VOICE_SAMPLE_RATE,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    baseline = _rms(recording.flatten())
    # Require noticeably louder than ambient noise to count as "speech"
    threshold = max(baseline * 4, 0.01)
    return threshold


def record_until_silence():
    """
    Records from the microphone until the candidate has stopped talking.
    Returns a float32 numpy array of audio samples at VOICE_SAMPLE_RATE
    (ready for Whisper).

    Uses webrtcvad when available: it classifies each audio frame as
    speech / not-speech based on voice-like spectral patterns, so a
    steady background noise (fan, AC, hum) doesn't get misread as
    "still talking" the way a pure loudness threshold would. Falls back
    to a noise-adaptive loudness threshold if webrtcvad isn't installed.
    """
    if VAD_AVAILABLE:
        return _record_until_silence_vad()
    return _record_until_silence_energy()


def _record_until_silence_vad():
    """Primary recording method: frame-by-frame speech/silence classification."""
    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

    frame_size = int(VOICE_SAMPLE_RATE * VAD_FRAME_MS / 1000)
    window_size = max(1, int((SILENCE_DURATION * 1000) / VAD_FRAME_MS))
    max_frames = int((MAX_RECORD_SECONDS * 1000) / VAD_FRAME_MS)

    recorded_frames = []
    speech_streak = 0
    has_spoken = False
    recent_frames = deque(maxlen=window_size)

    # webrtcvad needs raw 16-bit PCM, not float32
    stream = sd.InputStream(
        samplerate=VOICE_SAMPLE_RATE,
        channels=1,
        dtype="int16",
    )
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

            # Stop once the candidate has spoken and the recent window is
            # "mostly" quiet - a stray frame misclassified as speech
            # (fan noise, computer hum, mic hiss) won't reset this back
            # to zero the way a strict "all frames must be silent" rule would.
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
    """
    Fallback recording method when webrtcvad isn't installed. Tracks a
    continuously-updated noise floor (rather than one fixed calibration)
    so it can adapt if background noise drifts, requires several
    consecutive loud chunks (not just one) before counting the candidate
    as "started talking", and tolerates a small fraction of noise-triggered
    loud chunks in the silence window instead of resetting on any single one.
    """
    silence_threshold = calibrate_ambient_noise()
    noise_floor = silence_threshold / 4

    chunk_size = int(VOICE_SAMPLE_RATE * CHUNK_DURATION)
    window_size = max(1, int(SILENCE_DURATION / CHUNK_DURATION))
    max_chunks = int(MAX_RECORD_SECONDS / CHUNK_DURATION)
    loud_chunks_to_start = 2
    silence_tolerance = VAD_SILENCE_TOLERANCE

    recorded_chunks = []
    loud_streak = 0
    has_spoken = False
    recent_chunks = deque(maxlen=window_size)

    stream = sd.InputStream(
        samplerate=VOICE_SAMPLE_RATE,
        channels=1,
        dtype="float32",
    )
    stream.start()
    try:
        for _ in range(max_chunks):
            data, _ = stream.read(chunk_size)
            data = data.flatten()
            recorded_chunks.append(data)

            loudness = _rms(data)

            # Slowly track the ambient noise floor so it can adapt if it
            # drifts (e.g. a fan cycling between speeds), but only learn
            # from chunks that don't look like speech.
            if not has_spoken or loudness < noise_floor * 2:
                noise_floor = 0.95 * noise_floor + 0.05 * loudness

            dynamic_threshold = max(noise_floor * 3, silence_threshold)
            is_loud = loudness > dynamic_threshold
            recent_chunks.append(is_loud)

            if is_loud:
                loud_streak += 1
                if loud_streak >= loud_chunks_to_start:
                    has_spoken = True
            else:
                loud_streak = 0

            if has_spoken and len(recent_chunks) == window_size:
                loud_ratio = sum(recent_chunks) / window_size
                if loud_ratio <= silence_tolerance:
                    break
    finally:
        stream.stop()
        stream.close()

    if not recorded_chunks:
        return np.array([], dtype=np.float32)

    return np.concatenate(recorded_chunks)


def transcribe_audio(audio, language=None):
    """Transcribe a float32 numpy audio array using the local speech model."""
    if audio.size == 0:
        return ""

    model = get_whisper_model()
    lang_code = LANGUAGE_CODE_MAP.get(flatten_text(language)) if language else None

    if FASTER_WHISPER_AVAILABLE:
        try:
            segments, _info = model.transcribe(audio, language=lang_code, beam_size=5)
            return " ".join(segment.text.strip() for segment in segments).strip()
        except RuntimeError as e:
            # CTranslate2 loads some CUDA libraries (e.g. cuBLAS/cuDNN) lazily,
            # on first real use - so this can fail here even after the model
            # loaded successfully. If that happens, fall back to CPU for the
            # rest of the session instead of crashing the interview.
            error_text = str(e)
            looks_like_cuda_issue = _whisper_device_used == "cuda" and any(
                token in error_text.lower() for token in ("cublas", "cudnn", "cuda")
            )
            if not looks_like_cuda_issue:
                raise

            print("\n(GPU transcription failed - missing/incompatible CUDA libraries for faster-whisper.)")
            print(f"  Error: {error_text}")
            print("  Falling back to CPU for the rest of this session.")
            nvidia_pkgs_found = any(
                importlib.util.find_spec(pkg) for pkg in ("nvidia.cublas.lib", "nvidia.cudnn.lib")
            )
            if nvidia_pkgs_found:
                print("  nvidia-cublas-cu12/nvidia-cudnn-cu12 appear to be installed, so this is")
                print("  likely a VERSION MISMATCH with your ctranslate2 version (some versions")
                print("  need cuDNN 8, not 9). Try:")
                print("    pip show ctranslate2")
                print("    pip install \"nvidia-cudnn-cu12==8.9.6.50\" \"nvidia-cublas-cu12==12.1.3.1\"")
            else:
                print("  Try: pip install nvidia-cublas-cu12 nvidia-cudnn-cu12")

            model = get_whisper_model(force_device="cpu")
            segments, _info = model.transcribe(audio, language=lang_code, beam_size=5)
            return " ".join(segment.text.strip() for segment in segments).strip()
    else:
        result = model.transcribe(audio, language=lang_code, fp16=False)
        return result.get("text", "").strip()


def listen_for_answer(language):
    """Record the candidate's spoken answer and transcribe it to text."""
    print("\n🎙️  Listening... speak your answer, then pause when you're done.")
    audio = record_until_silence()

    if audio.size == 0:
        return ""

    print("Transcribing...")
    text = transcribe_audio(audio, language=language)
    print(f"You said: {text}")
    return text


# ============================================================
# VOICE MODE: TEXT-TO-SPEECH
# ============================================================

def get_tts_engine():
    """
    Attempts to load the Kokoro-82M TTS engine first.
    Returns the Kokoro engine instance if loaded, or None if unavailable.
    """
    global _kokoro_engine, _USING_KOKORO

    if _kokoro_engine is not None:
        return _kokoro_engine

    if KOKORO_AVAILABLE:
        model_path = BASE_DIR / "kokoro-v0_19.onnx"
        voices_path = BASE_DIR / "voices-v1.0.bin"

        if not voices_path.exists():
            voices_path = BASE_DIR / "voices.bin"

        if model_path.exists() and voices_path.exists():
            try:
                print("\n(Initializing Kokoro-ONNX neural voice engine...)")
                _kokoro_engine = Kokoro(str(model_path), str(voices_path))
                _USING_KOKORO = True
                return _kokoro_engine
            except Exception as e:
                print(f"\n(Failed to initialize Kokoro-ONNX: {e})")
        else:
            print(f"\n(Kokoro ONNX model/voice files not found at {BASE_DIR})")

    _USING_KOKORO = False
    return None


def get_kokoro_voice(language=None):
    """
    Shared voice-selection logic for Kokoro, used by both the CLI `speak()`
    path and the Flask `/api/tts` web route, so they never drift apart.
    """
    lang_clean = flatten_text(language) if language else "english"
    if "vietnamese" in lang_clean or lang_clean == "vi":
        return "af_bella"
    return "af_heart"


def get_pyttsx3_engine():
    """
    Lazy initialization for pyttsx3, isolated strictly for desktop/CLI mode.
    """
    global _tts_engine
    if _tts_engine is not None:
        return _tts_engine

    if PYTTSX3_AVAILABLE:
        try:
            _tts_engine = pyttsx3.init()
            return _tts_engine
        except Exception as e:
            print(f"\n(Failed to initialize pyttsx3: {e})")
    return None

# pyttsx3's underlying drivers (SAPI5 / NSSpeechSynthesizer / espeak) are not
# reliably safe to run concurrently from multiple threads, and Flask's dev
# server can handle requests on separate threads. This lock serializes all
# pyttsx3 calls so two overlapping /api/tts requests can't corrupt each other.
_pyttsx3_lock = threading.Lock()


def synthesize_pyttsx3_wav(text, language=None):
    """
    Render text to WAV bytes using pyttsx3, for use as the web app's
    server-side audio fallback (Kokoro's HTTP-friendly cousin).

    Unlike the CLI's speak(), which reuses one long-lived engine instance
    across a whole terminal session, this creates a fresh engine per call.
    pyttsx3 engines aren't guaranteed to run save_to_file() reliably more
    than once on some platforms/drivers, so a throwaway instance per HTTP
    request is the safer choice here.

    Returns the WAV file's raw bytes, or None if pyttsx3 is unavailable
    or synthesis fails for any reason.
    """
    if not PYTTSX3_AVAILABLE:
        return None

    tmp_path = None
    with _pyttsx3_lock:
        try:
            engine = pyttsx3.init()
            _select_voice_for_language(engine, language)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            engine.save_to_file(text, tmp_path)
            engine.runAndWait()
            try:
                engine.stop()
            except Exception:
                pass

            with open(tmp_path, "rb") as f:
                data = f.read()

            return data if data else None

        except Exception as e:
            print(f"\n(pyttsx3 web-fallback synthesis failed: {e})")
            return None

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)


def _select_voice_for_language(engine, language):
    """
    Best-effort: try to pick an installed system voice that matches the
    interview language. Offline TTS voice availability depends entirely
    on what's installed on the OS, so this may silently fall back to
    whatever the default voice is if no match is found.
    """
    if not language:
        return

    lang_code = LANGUAGE_CODE_MAP.get(flatten_text(language))
    if not lang_code:
        return

    try:
        for voice in engine.getProperty("voices"):
            voice_langs = " ".join(str(l) for l in getattr(voice, "languages", []))
            haystack = f"{voice.id} {voice.name} {voice_langs}".lower()
            if lang_code in haystack or flatten_text(language) in flatten_text(haystack):
                engine.setProperty("voice", voice.id)
                return
    except Exception:
        pass


def speak(text, language=None):
    """
    Speak text aloud in CLI terminal mode.
    Tries Kokoro first -> Falls back to pyttsx3 if running locally.
    """
    if not text:
        return

    # 1. Primary path: Kokoro-ONNX
    kokoro = get_tts_engine()
    if kokoro and _USING_KOKORO:
        try:
            voice = get_kokoro_voice(language)
            samples, sample_rate = kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
            sd.play(samples, sample_rate)
            sd.wait()
            return
        except Exception as e:
            print(f"\n(Kokoro speech generation failed: {e}. Falling back to pyttsx3...)")

    # 2. Desktop Fallback path: pyttsx3 (terminal/CLI mode only)
    engine = get_pyttsx3_engine()
    if engine:
        try:
            _select_voice_for_language(engine, language)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"\n(pyttsx3 TTS Error: {e})")


def ask_interview_mode():
    """Ask the user whether to run the interview in text or voice mode."""
    print("\nInterview mode:")
    print("  1. Text  (type answers)")
    print("  2. Voice (speak answers, fully offline speech recognition + text-to-speech)")

    if not VOICE_AVAILABLE:
        print("  (Voice mode unavailable - missing packages. Install with:")
        print("   pip install faster-whisper sounddevice numpy pyttsx3")
        print("   or: pip install openai-whisper sounddevice numpy pyttsx3)")
        return False

    if not VAD_AVAILABLE:
        print("  (Tip: 'pip install webrtcvad' makes silence detection much more")
        print("   reliable in noisy rooms - e.g. with a fan or AC running.)")

    choice = input("Choose mode [1/2]: ").strip()
    return choice == "2"


def find_question_file(candidate_name, language):
    """
    Find the candidate's question JSON file inside their folder regardless of 
    casing, diacritics, or search depth.
    """
    target_candidate = flatten_text(candidate_name)
    target_language = flatten_text(language)

    # Roots to search (current dir and parent directories)
    search_roots = [BASE_DIR, BASE_DIR.parent, BASE_DIR.parent.parent]

    matching_dirs = []
    for root in search_roots:
        if root.exists():
            for d in root.rglob("*"):
                if d.is_dir():
                    folder_flat = flatten_text(d.name)
                    # Match folder name against candidate name
                    if folder_flat and (folder_flat == target_candidate or target_candidate in folder_flat):
                        matching_dirs.append(d)

    # Deduplicate matching folders
    matching_dirs = list(set(matching_dirs))

    if not matching_dirs:
        return None

    # Search for question file inside matched applicant folder(s)
    for folder in matching_dirs:
        for file in folder.rglob("*.json"):
            file_flat = flatten_text(file.name)
            # Check if file contains both the candidate name and interview language
            if target_candidate in file_flat and target_language in file_flat and "questions" in file_flat:
                return file

    return None


def get_question_file():
    print("=== AI Interview Chatbot ===\n")

    candidate_name = input("Candidate name: ").strip()
    language = input("Interview language: ").strip()

    question_file = find_question_file(candidate_name, language)

    if question_file is None:
        expected_filename = f"{candidate_name}_questions_{language}.json"

        print("\nERROR: Question file not found.")
        print(f"Expected file: {expected_filename}")
        print(f"Directory searched: {BASE_DIR}")

        return None, candidate_name, language

    print(f"\nQuestion file found: {question_file.name}")

    return question_file, candidate_name, language


# ============================================================
# LOAD QUESTIONS
# ============================================================

def load_questions(question_file):
    """Load interview questions from the selected JSON file."""
    try:
        with open(question_file, "r", encoding="utf-8") as f:
            return json.load(f)

    except FileNotFoundError:
        raise FileNotFoundError(
            f"Question file not found: {question_file}"
        )

    except json.JSONDecodeError as e:
        raise ValueError(
            f"Invalid JSON in question file: {question_file}\n"
            f"Error: {e}"
        )


# ============================================================
# EXTRACT QUESTIONS
# ============================================================

def extract_questions(data):

    questions = data.get("questions", [])

    all_questions = []

    # Current JSON format: list
    if isinstance(questions, list):

        for index, question in enumerate(questions, start=1):

            all_questions.append({
                "question_number": index,
                "category": question.get("category"),
                "question": question.get("question"),
                "difficulty": question.get("difficulty"),
                "topic": question.get("topic")
            })

    # Older JSON format: dictionary
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

        raise ValueError(
            "Invalid 'questions' format in interview_questions.json"
        )

    return all_questions


# ============================================================
# OLLAMA FOLLOW-UP QUESTION GENERATOR
# ============================================================

def generate_follow_up(
    candidate_name,
    language,
    current_question,
    answer,
    previous_answers
):
    history = "\n".join(
        f"Q: {item['question']}\nA: {item['answer']}"
        for item in previous_answers
    )

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

Based on the candidate's answer, decide whether a follow-up
question would meaningfully improve the interview.

If a follow-up is useful:
- Ask exactly ONE follow-up question.
- Make it directly related to the candidate's answer.
- Do not repeat the original question.
- Keep it concise.
- Write the question entirely in {language}.

If no follow-up is useful, respond with exactly:

NO_FOLLOW_UP

Otherwise, respond with ONLY the follow-up question.
"""

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional technical interviewer. "
                    "Ask concise, relevant and natural questions."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        think=False
    )

    result = response["message"]["content"].strip()

    if "<think>" in result:
        result = result.split("</think>")[-1].strip()

    if result == "NO_FOLLOW_UP":
        return None

    return result


# ============================================================
# ANSWER CONFIRMATION
# ============================================================

def get_confirmed_answer(voice_mode=False, language=None):

    while True:

        if voice_mode:
            answer = listen_for_answer(language)

            if not answer.strip():
                print("\nI couldn't hear a clear answer.")
                fallback = input(
                    "Press Enter to try speaking again, or type your answer (or 'quit'): "
                ).strip()

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

        print()
        print(f"Your answer: {answer}")
        print()

        # Confirmation stays typed even in voice mode - it's quick and
        # avoids misrecognizing a spoken "yes"/"no" as something else.
        confirmation = input(
            "Are you sure this is your answer? (yes/no): "
        ).strip().lower()

        if confirmation in ["yes", "y"]:

            return answer

        elif confirmation in ["no", "n"]:

            print("\nOkay, please enter your answer again.\n")

        else:

            print(
                "\nPlease enter 'yes' or 'no'.\n"
            )


# ============================================================
# RUN INTERVIEW
# ============================================================

def run_interview(candidate_name, language, questions, voice_mode=False):
    answers = []

    base_question_index = 0
    total_question_count = 0

    while (
        total_question_count < MAX_QUESTIONS
        and base_question_index < len(questions)
    ):
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

        # Don't generate a follow-up if we've reached the limit
        if total_question_count >= MAX_QUESTIONS:
            break

        # Ask Ollama whether a follow-up is appropriate
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


# ============================================================
# SAVE ANSWERS
# ============================================================

def get_output_file(candidate_name):

    normalized_name = normalize_text(candidate_name)

    filename = f"{normalized_name}_answers.json"

    return BASE_DIR / filename


def save_answers(candidate_name, answers, questions_file, interview_language):

    output = {
        "candidate": candidate_name,
        "source_questions": questions_file.name,
        "interview_language": interview_language,
        "interview_date": datetime.now().isoformat(),
        "total_answered": len(answers),
        "answers": answers
    }

    # Save output into the same folder as questions_file
    output_filename = f"{flatten_text(candidate_name)}_answers.json"
    output_path = questions_file.parent / output_filename

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(
            output,
            file,
            indent=4,
            ensure_ascii=False
        )

    print("\nAnswers saved to:")
    print(output_path)

    return output_path


# ============================================================
# MAIN
# ============================================================

def main():
    question_file, candidate_name, language = get_question_file()

    if question_file is None:
        return

    print(f"\nLoading questions for {candidate_name}...")

    questions_data = load_questions(question_file)
    questions = extract_questions(questions_data)

    if not questions:
        print("ERROR: No questions found in the JSON file.")
        return

    print(f"Loaded {len(questions)} questions.")
    print(f"Interview language: {language}")

    voice_mode = ask_interview_mode()

    if voice_mode:
        # Warm up the whisper model once up front so the first
        # question doesn't have an awkward multi-second delay.
        get_whisper_model()

        if VAD_AVAILABLE:
            print(f"(Using webrtcvad for silence detection, aggressiveness={VAD_AGGRESSIVENESS})")
        else:
            print("(webrtcvad not installed - using the less noise-robust energy-based fallback. "
                  "Run 'pip install webrtcvad' for better results in noisy rooms.)")

        if FASTER_WHISPER_AVAILABLE:
            print(f"(Speech recognition: faster-whisper, model='{WHISPER_MODEL_SIZE}', device={_whisper_device_used})")
        else:
            print(f"(Speech recognition: openai-whisper, model='{WHISPER_MODEL_SIZE}'. "
                  "Install 'faster-whisper' for GPU-accelerated, more accurate transcription.)")

    answers = run_interview(
        candidate_name,
        language,
        questions,
        voice_mode=voice_mode
    )

    save_answers(
        candidate_name,
        answers,
        question_file,
        language
    )


if __name__ == "__main__":
    main()