# Script launching and utils
import json
import os
import re
import signal
import sys
import threading
from pathlib import Path
from subprocess import PIPE, STDOUT, Popen
from typing import Dict, List, Optional, Tuple

CONFIG_PATH = Path(os.path.expanduser("~")) / ".script_aliases.json"


def load_config() -> Dict[str, str]:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()}
        except Exception:
            print(
                f"[warn] Failed to parse {CONFIG_PATH}. "
                "Starting with empty mapping."
            )
            return {}
    return {}


def save_config(aliases: Dict[str, str]) -> None:
    CONFIG_PATH.write_text(
        json.dumps(aliases, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def normalize_phrase(p: str) -> str:
    p = p.strip().lower()
    p = re.sub(r"\b(the|a|an)\b", " ", p)
    p = re.sub(r"\b(program|script|app)\b", " ", p)
    p = re.sub(r"\s+", " ", p).strip()
    return p


def best_match(
    aliases: Dict[str, str],
    raw_phrase: str
) -> Optional[Tuple[str, str]]:
    if not aliases:
        return None
    norm_to_key = {normalize_phrase(k): k for k in aliases.keys()}
    norm_raw = normalize_phrase(raw_phrase)

    if norm_raw in norm_to_key:
        key = norm_to_key[norm_raw]
        return key, aliases[key]

    tokens = set(norm_raw.split())
    candidates: List[Tuple[int, int, str]] = []

    for k in aliases.keys():
        norm_k = normalize_phrase(k)
        ktokens = set(norm_k.split())
        overlap = len(tokens & ktokens)
        if overlap > 0:
            candidates.append((overlap, len(norm_k), k))

    if candidates:
        candidates.sort(key=lambda t: (t[0], -t[1]), reverse=True)
        key = candidates[0][2]
        return key, aliases[key]

    for k in aliases.keys():
        if normalize_phrase(k) in norm_raw or norm_raw in normalize_phrase(k):
            return k, aliases[k]

    return None


def ensure_python_script(path: str) -> str:
    p = Path(os.path.expanduser(path)).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Script not found: {p}")
    if p.is_dir():
        raise IsADirectoryError(f"Expected a file, got directory: {p}")
    if p.suffix.lower() != ".py":
        print(
            f"[warn] '{p}' does not end with .py; "
            "attempting to run with Python anyway."
        )
    return str(p)


def _stream_output(proc: Popen, label: str) -> None:
    assert proc.stdout is not None
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        print(f"[{label} {proc.pid}] {line.rstrip()}")
    proc.stdout.close()


def run_script(script_path: str, attach: bool = True) -> int:
    py_exe = sys.executable
    cmd = [py_exe, script_path]
    cwd = str(Path(script_path).resolve().parent)

    if attach:
        proc = Popen(cmd, cwd=cwd, stdout=PIPE, stderr=STDOUT, text=True)
        t = threading.Thread(target=_stream_output, args=(proc, Path(script_path).name), daemon=True)
        t.start()
        try:
            return_code = proc.wait()
            t.join(timeout=0.5)
            if return_code == 0:
                print(
                    f"[ok] {Path(script_path).name} finished with exit code 0."
                )
            else:
                print(
                    f"[err] {Path(script_path).name} exited with code {return_code}."
                )
            return return_code
        except KeyboardInterrupt:
            try:
                proc.send_signal(signal.SIGINT)
                print("[info] Sent SIGINT to child process...")
                return proc.wait(timeout=5)
            except Exception:
                proc.kill()
                return proc.wait()
    else:
        kwargs = {}
        if os.name == "nt":
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            proc = Popen(
                cmd, cwd=cwd, stdout=PIPE, stderr=STDOUT, text=True, **kwargs
            )
        else:
            proc = Popen(
                cmd, cwd=cwd, stdout=PIPE, stderr=STDOUT,
                text=True, start_new_session=True, **kwargs
            )
        print(f"[bg] Started {Path(script_path).name} in background (pid={proc.pid}).")
        return proc.pid


def interactive_map(aliases: Dict[str, str]) -> None:
    phrase = input("Phrase (e.g., Scrape Program): ").strip()
    path = input("Full path to script (e.g., ~/scripts/scrape.py): ").strip()
    if not phrase or not path:
        print("[err] Phrase and path are required.")
        return
    try:
        real = ensure_python_script(path)
    except Exception as e:
        print(f"[err] {e}")
        return
    aliases[phrase] = real
    save_config(aliases)
    print(f"[ok] Mapped '{phrase}' → {real}")


def handle_map(args: List[str], aliases: Dict[str, str]) -> None:
    if not args:
        interactive_map(aliases)
        return
    if len(args) < 2:
        print("[err] Usage: map \"<phrase>\" <path>")
        return
    phrase = args[0]
    path = args[1]
    try:
        real = ensure_python_script(path)
    except Exception as e:
        print(f"[err] {e}")
        return
    aliases[phrase] = real
    save_config(aliases)
    print(f"[ok] Mapped '{phrase}' → {real}")


def handle_unmap(args: List[str], aliases: Dict[str, str]) -> None:
    if not args:
        print("[err] Usage: unmap \"<phrase>\"")
        return
    phrase = args[0]
    if phrase in aliases:
        del aliases[phrase]
        save_config(aliases)
        print(f"[ok] Removed mapping '{phrase}'")
        return
    bm = best_match(aliases, phrase)
    if bm:
        key, _ = bm
        del aliases[key]
        save_config(aliases)
        print(f"[ok] Removed mapping '{key}'")
    else:
        print(f"[warn] No mapping found for '{phrase}'")


def handle_list(aliases: Dict[str, str]) -> None:
    if not aliases:
        print("(no mappings yet) Use: map \"<phrase>\" <path>")
        return
    widest = max(len(k) for k in aliases.keys())
    for k, v in sorted(aliases.items(), key=lambda kv: kv[0].lower()):
        print(f"{k.ljust(widest)}  ->  {v}")


def parse_run_command(user_input: str) -> Tuple[str, bool]:
    bg = user_input.strip().endswith("&")
    s = user_input.strip().removesuffix("&").strip()
    m = re.match(r"^run\s+(.*)$", s, flags=re.I)
    phrase = m.group(1) if m else s
    return phrase.strip().strip("\"'"), bg


def handle_run(rest: str, aliases: Dict[str, str]) -> None:
    phrase, bg = parse_run_command(rest)
    if not phrase:
        print("[err] Nothing to run. Try: run <phrase>")
        return
    bm = best_match(aliases, phrase)
    if not bm:
        print(
            f"[warn] No mapping matched '{phrase}'. "
            "Use 'list' to see options or 'map' to add one."
        )
        return
    key, script = bm
    print(f"[info] Launching '{key}' → {script}")
    try:
        _ = run_script(script, attach=not bg)
    except FileNotFoundError:
        print(f"[err] Script not found: {script}")
    except Exception as e:
        print(f"[err] Failed to run: {e}")
