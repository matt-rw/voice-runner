import queue
import re
import threading
from typing import Dict, Optional

from runner import handle_run


def have_vosk() -> bool:
    try:
        import sounddevice  # noqa: F401
        import vosk  # noqa: F401
        return True
    except Exception:
        return False


def list_audio_devices() -> None:
    try:
        import sounddevice as sd
        print(sd.query_devices())
    except Exception as e:
        print(f"[err] Failed to list devices: {e}")


def start_voice_listener(
    aliases: Dict[str, str],
    model_dir: Optional[str],
    device: Optional[int],
    sample_rate: int = 16000
) -> threading.Thread:
    """
    Start a background thread that listens on the microphone
    and triggers runs on phrases like:
    "run scrape program" or "run the backup script &"
    """
    if not have_vosk():
        print(
            "[err] Voice mode requires 'vosk' and 'sounddevice'. "
            "Install with: pip install vosk sounddevice"
        )
        return None  # type: ignore

    import json as _json

    import sounddevice as sd
    from vosk import KaldiRecognizer, Model

    # Load model
    if model_dir is None:
        print(
            "[warn] No Vosk model provided. "
            "Use --model /path/to/vosk-model-small-en-us"
        )
        print("      Voice mode will not start.")
        return None  # type: ignore

    try:
        model = Model(model_dir)
    except Exception as e:
        print(f"[err] Could not load Vosk model at '{model_dir}': {e}")
        return None  # type: ignore

    q = queue.Queue()

    def audio_callback(indata, frames, time_, status):
        if status:
            print(f"[audio] {status}", flush=True)
        q.put(bytes(indata))

    # Create recognizer
    rec = KaldiRecognizer(model, sample_rate)
    rec.SetWords(False)

    def worker():
        print(
            "[voice] Listening... say something like: "
            "'run scrape program'  (Ctrl+C to stop)"
        )
        try:
            with sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=8000,
                device=device,
                dtype='int16',
                channels=1,
                callback=audio_callback
            ):
                while True:
                    data = q.get()
                    if rec.AcceptWaveform(data):
                        result = rec.Result()
                        try:
                            text = _json.loads(result).get("text", "")
                        except Exception:
                            text = ""
                        _maybe_run_from_voice(text, aliases)
                    else:
                        # partial = _json.loads(
                        # rec.PartialResult()).get("partial", "")
                        pass
        except KeyboardInterrupt:
            print("\n[voice] stopped.")
        except Exception as e:
            print(f"[voice err] {e}")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def _maybe_run_from_voice(text: str, aliases: Dict[str, str]) -> None:
    if not text:
        return
    # try to find a "run ..." segment
    m = re.search(r"\brun\s+(.+)$", text)
    if not m:
        return
    phrase_raw = m.group(1).strip()
    # allow saying "and" or "ampersand" / "background"
    bg = False
    if (
        phrase_raw.endswith("and") or
        phrase_raw.endswith("ampersand") or
        phrase_raw.endswith("background")
    ):
        bg = True
        phrase_raw = \
            re.sub(r"(and|ampersand|background)$", "", phrase_raw).strip()

    # Normalize and try to run
    print(
        f"[voice] heard: '{text}' → interpreted phrase: "
        "'{phrase_raw}'{' (bg)' if bg else ''}"
    )
    phrase = "run " + phrase_raw + (" &" if bg else "")
    handle_run(phrase, aliases)
