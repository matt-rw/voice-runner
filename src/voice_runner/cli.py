# ----------------------- CLI / Main -----------------------
import argparse
import shlex
from typing import Dict

from runner import (CONFIG_PATH, handle_list, handle_map, handle_run,
                    handle_unmap, load_config)
from voice import list_audio_devices, start_voice_listener


def print_help() -> None:
    import textwrap as _tw
    print(_tw.dedent("""\
        Commands:
          map                             interactive mapping wizard
          map "<phrase>" <path>           create/update mapping
          unmap "<phrase>"                remove mapping
          list                            show mappings
          run <phrase> [&]                run mapped script; '&' = background
          help                            show this help
          exit | quit                     exit program

        Natural phrases also work:
          "run the scrape program"
          "run scrape script &"
    """))


def repl(aliases: Dict[str, str]) -> None:
    print("Phrase→Script Runner (type 'help' for commands)")
    print(f"Config file: {CONFIG_PATH}")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            break

        if not raw:
            continue

        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = raw.split()

        cmd = parts[0].lower()

        if cmd in ("exit", "quit", ":q"):
            print("bye.")
            break
        elif cmd == "help":
            print_help()
        elif cmd == "map":
            handle_map(parts[1:], aliases)
        elif cmd == "unmap":
            handle_unmap(parts[1:], aliases)
        elif cmd == "list":
            handle_list(aliases)
        elif cmd == "run" or raw.lower().startswith("run "):
            rest = raw[len("run "):] if cmd == "run" else raw
            handle_run(rest, aliases)
        else:
            if raw.lower().startswith("run "):
                handle_run(raw, aliases)
            else:
                print(f"[??] Unknown command: {cmd!r} — try 'help'")


def main():
    parser = argparse.ArgumentParser(
        description="Phrase→script runner with optional voice mode (Vosk)."
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Enable voice mode (requires vosk + sounddevice)."
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Path to Vosk model directory."
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Audio input device index for sounddevice."
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List audio input/output devices and exit."
    )
    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
        return

    aliases = load_config()

    voice_thread = None
    if args.voice:
        voice_thread = start_voice_listener(
            aliases, args.model, args.device
        )

    # Start the REPL regardless;
    # you can interact while voice listens in the background
    repl(aliases)

    # On exit, the voice thread (daemon) will stop with the process.


if __name__ == "__main__":
    main()
