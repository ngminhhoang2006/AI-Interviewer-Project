#!/usr/bin/env python3
"""
download_models.py - downloads the Sherpa-ONNX speech models the interview app needs
into system/sherpa_models/ (next to this file).

Standard library only, so it runs with any Python 3.8+ on Windows, macOS and Linux.
Models that are already in place are skipped, so it is safe to run repeatedly
(the installers run it every time).

    python download_models.py                      # the core set (see CORE below)
    python download_models.py --voices spanish french   # extra offline voices
    python download_models.py --whisper medium --force   # switch Whisper size (replaces the old one)
    python download_models.py --only asr tts       # just these folders
    python download_models.py --force              # re-download even if present
    python download_models.py --list               # show what would be installed

Folder layout produced (this is what chatbot.py expects):
    sherpa_models/asr/           Whisper (multilingual speech-to-text), int8 files only
    sherpa_models/asr_parakeet/  Parakeet-TDT 0.6B v3 (fast speech-to-text for en/es/fr/de/it/pt/ru)
    sherpa_models/tts/           English voice   (model.onnx, tokens.txt, espeak-ng-data/)
    sherpa_models/tts_vi/        Vietnamese voice
    sherpa_models/tts_<language>/  optional extra voices, e.g. tts_spanish
"""
import argparse
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
MODELS_DIR = Path(__file__).resolve().parent / "sherpa_models"


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------------------
# WHAT TO INSTALL  (edit here to change voices / models)
# ---------------------------------------------------------------------------
# Whisper size: tiny (110 MB download) < base (200 MB) < small (610 MB) < medium (1.8 GB).
# Larger is noticeably better for Vietnamese, Thai, Hindi, Indonesian, ...
WHISPER_SIZE = os.environ.get("AI_INTERVIEWER_WHISPER", "small")

ENGLISH_VOICE = "vits-piper-en_US-lessac-medium"
VIETNAMESE_VOICE = "vits-piper-vi_VN-vais1000-medium"

# Optional extra offline voices (folder becomes tts_<language>, which chatbot.py looks for).
# Chinese, Japanese, Korean and Thai use the browser voice instead (no Piper voice / different model type).
EXTRA_VOICES = {
    "spanish":    "vits-piper-es_ES-davefx-medium",
    "french":     "vits-piper-fr_FR-siwis-medium",
    "german":     "vits-piper-de_DE-thorsten-medium",
    "italian":    "vits-piper-it_IT-paola-medium",
    "portuguese": "vits-piper-pt_BR-faber-medium",
    "russian":    "vits-piper-ru_RU-irina-medium",
    "hindi":      "vits-piper-hi_IN-pratham-medium",
    "indonesian": "vits-piper-id_ID-news_tts-medium",
}


class Spec:
    def __init__(self, folder, archive, present, prefer_int8=False, rename_onnx=None, label=None, replace=False):
        self.folder = folder            # folder under sherpa_models/
        self.archive = archive          # path under the GitHub release download URL
        self.present = present          # glob patterns that must all match for it to count as installed
        self.prefer_int8 = prefer_int8  # drop fp32 .onnx files when an .int8.onnx twin exists
        self.rename_onnx = rename_onnx  # rename the single .onnx to this (Piper voices -> model.onnx)
        self.label = label or folder
        self.replace = replace          # wipe the old folder first (so two Whisper sizes never mix)

    @property
    def url(self):
        return f"{BASE_URL}/{self.archive}"


def piper(folder, voice):
    return Spec(folder, f"tts-models/{voice}.tar.bz2",
                present=["model.onnx", "tokens.txt", "espeak-ng-data"],
                rename_onnx="model.onnx", label=f"{folder} ({voice})")


def core_specs(whisper_size):
    return [
        Spec("asr", f"asr-models/sherpa-onnx-whisper-{whisper_size}.tar.bz2",
             present=["*encoder*.onnx", "*decoder*.onnx", "*tokens*.txt"],
             prefer_int8=True, replace=True, label=f"asr (Whisper {whisper_size})"),
        Spec("asr_parakeet", "asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2",
             present=["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"],
             label="asr_parakeet (Parakeet-TDT 0.6B v3)"),
        piper("tts", ENGLISH_VOICE),
        piper("tts_vi", VIETNAMESE_VOICE),
    ]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def is_installed(spec):
    d = MODELS_DIR / spec.folder
    return d.is_dir() and all(any(d.glob(p)) for p in spec.present)


def download(url, dest, name, attempts=4):
    """Download with retries and resume (GitHub's CDN supports Range requests)."""
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            have = dest.stat().st_size if dest.exists() else 0
            headers = {"User-Agent": "ai-interviewer-installer"}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status == 206:
                    mode, done = "ab", have
                    total = have + int(resp.headers.get("Content-Length") or 0)
                else:
                    mode, done = "wb", 0
                    total = int(resp.headers.get("Content-Length") or 0)
                next_pct = (done * 100 // total // 10 + 1) * 10 if total else 101
                with open(dest, mode) as f:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if total and done * 100 // total >= next_pct:
                            log(f"  downloading {name}: {next_pct}% ({done >> 20}/{total >> 20} MB)")
                            next_pct += 10
            if total and dest.stat().st_size < total:
                raise IOError(f"incomplete download ({dest.stat().st_size} of {total} bytes)")
            return
        except (urllib.error.URLError, IOError, OSError) as e:
            last_err = e
            log(f"  [warn] download attempt {attempt}/{attempts} failed: {e}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"could not download {url}: {last_err}")


def safe_extract(tar, dest):
    """Extract a tar archive, refusing members that would escape `dest`."""
    dest = dest.resolve()
    for m in tar.getmembers():
        if m.name.split("/", 1)[-1].startswith("test_wavs") or "/test_wavs" in m.name:
            continue   # sample audio we don't need
        target = (dest / m.name).resolve()
        if dest != target and dest not in target.parents:
            raise RuntimeError(f"unsafe path in archive: {m.name}")
        if m.issym() or m.islnk():
            continue
        tar.extract(m, dest)


def install(spec, force=False):
    target = MODELS_DIR / spec.folder
    if is_installed(spec) and not force:
        log(f"[skip] {spec.label}: already installed")
        return True

    log(f"[get ] {spec.label}")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".download_", dir=MODELS_DIR))
    try:
        archive = work / "model.tar.bz2"
        download(spec.url, archive, spec.folder)

        log(f"  extracting {spec.folder} ...")
        extract_dir = work / "x"
        extract_dir.mkdir()
        with tarfile.open(archive, "r:bz2") as tar:
            safe_extract(tar, extract_dir)
        archive.unlink()

        roots = [p for p in extract_dir.iterdir()]
        root = roots[0] if len(roots) == 1 and roots[0].is_dir() else extract_dir

        if spec.prefer_int8:   # keep only the smaller, faster int8 files
            for f in list(root.glob("*.onnx")):
                if not f.name.endswith(".int8.onnx") and (root / (f.stem + ".int8.onnx")).exists():
                    f.unlink()

        if spec.rename_onnx:   # Piper voices ship as <voice>.onnx; the app expects model.onnx
            onnx = [f for f in root.glob("*.onnx")]
            if len(onnx) != 1:
                raise RuntimeError(f"expected one .onnx file, found {[f.name for f in onnx]}")
            if onnx[0].name != spec.rename_onnx:
                onnx[0].rename(root / spec.rename_onnx)

        if spec.replace and target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        for item in root.iterdir():           # merge into the target, replacing same-named items
            dest = target / item.name
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            elif dest.exists() or dest.is_symlink():
                dest.unlink()
            shutil.move(str(item), str(dest))

        if not is_installed(spec):
            raise RuntimeError("files are missing after install - the archive layout may have changed")
        log(f"[ ok ] {spec.label}")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"[FAIL] {spec.label}: {e}")
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    global MODELS_DIR
    ap = argparse.ArgumentParser(description="Download Sherpa-ONNX speech models for the AI Interviewer.")
    ap.add_argument("--whisper", default=WHISPER_SIZE, help="Whisper size: tiny, base, small, medium (default: %(default)s)")
    ap.add_argument("--voices", nargs="*", default=[], metavar="LANG",
                    help=f"extra offline voices: {', '.join(EXTRA_VOICES)}, or 'all'")
    ap.add_argument("--only", nargs="*", default=None, metavar="FOLDER", help="only these folders, e.g. asr tts")
    ap.add_argument("--force", action="store_true", help="re-download even if already installed")
    ap.add_argument("--list", action="store_true", help="show the plan and exit")
    ap.add_argument("--models-dir", type=Path, default=None, help=f"default: {MODELS_DIR}")
    args = ap.parse_args()

    if args.models_dir:
        MODELS_DIR = args.models_dir.resolve()

    specs = core_specs(args.whisper)
    wanted = list(EXTRA_VOICES) if "all" in [v.lower() for v in args.voices] else [v.lower() for v in args.voices]
    for lang in wanted:
        if lang not in EXTRA_VOICES:
            ap.error(f"no extra voice for '{lang}'. Available: {', '.join(EXTRA_VOICES)}")
        specs.append(piper(f"tts_{lang}", EXTRA_VOICES[lang]))
    if args.only is not None:
        specs = [s for s in specs if s.folder in args.only]

    log(f"Speech models folder: {MODELS_DIR}")
    if args.list:
        for s in specs:
            log(f"  {'installed' if is_installed(s) else 'missing  '}  {s.label}  <- {s.url}")
        return 0

    results = [install(s, force=args.force) for s in specs]
    failed = [s.folder for s, ok in zip(specs, results) if not ok]
    if failed:
        log(f"\nSome models could not be installed: {', '.join(failed)}")
        log("Check your internet connection and run this script again; finished models are kept.")
        return 1
    log("\nAll speech models are ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
