#!/usr/bin/env python3
"""Generate still frames with the Gemini image API (nano banana).

Used to make reference stills for the Flow clips: approve a frame per shot cheaply,
then feed the approved still into Flow as the first frame of the generation.

The API key is read from %USERPROFILE%\\.gemini_api_key or $GEMINI_API_KEY.
It is deliberately NOT stored in this repo.

Usage:
    python scripts/genimg.py --page example-product --shot 1.1 --prompt "..."
    python scripts/genimg.py --page example-product --all           # from flow-prompts.json
    python scripts/genimg.py --page example-product --shot 7 --retry 2

Stills land in pages/<page>/stills/<shot>.png (retries as <shot>_r2.png etc).
"""

import argparse
import base64
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-3.1-flash-image"

# Appended to every prompt unless the page's flow-prompts.json sets its own "_suffix".
# The default bans lettering because generated text garbles — but a page about business
# signage NEEDS lettering, so those pages override it and every frame gets read
# letter-by-letter instead. See pages/example-product/flow-prompts.json.
SUFFIX = (
    "16:9, static camera, natural daylight, sharp focus, "
    "no text, no letters, no numbers, no logos, no signage, photorealistic."
)


def api_key() -> str:
    env = os.environ.get("GEMINI_API_KEY")
    if env:
        return env.strip()
    path = pathlib.Path.home() / ".gemini_api_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    sys.exit("No API key: set GEMINI_API_KEY or write ~/.gemini_api_key")


def generate(prompt: str, model: str, aspect: str = "16:9") -> bytes:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key()}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": aspect},
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        sys.exit(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:800]}")

    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    sys.exit(f"No image in response: {json.dumps(data)[:800]}")


def shot_prompts(page: str) -> tuple:
    """Read pages/<page>/flow-prompts.json -> ({shot: prompt}, suffix).

    An optional "_suffix" key overrides the module default for that page.
    """
    path = ROOT / "pages" / page / "flow-prompts.json"
    if not path.exists():
        sys.exit(f"No {path}. Write it, or pass --shot and --prompt.")
    data = json.loads(path.read_text(encoding="utf-8"))
    suffix = data.pop("_suffix", SUFFIX)
    return data, suffix


def write(page: str, shot: str, blob: bytes, retry: int) -> pathlib.Path:
    out_dir = ROOT / "pages" / page / "stills"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{shot}.png" if retry <= 1 else f"{shot}_r{retry}.png"
    out = out_dir / name
    out.write_bytes(blob)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True)
    ap.add_argument("--shot")
    ap.add_argument("--prompt")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--retry", type=int, default=1, help="suffixes the filename")
    ap.add_argument("--no-suffix", action="store_true")
    args = ap.parse_args()

    if args.all:
        prompts, suffix = shot_prompts(args.page)
        jobs = sorted(prompts.items())
    elif args.shot and args.prompt:
        jobs, suffix = [(args.shot, args.prompt)], SUFFIX
    elif args.shot:
        prompts, suffix = shot_prompts(args.page)
        jobs = [(args.shot, prompts[args.shot])]
    else:
        sys.exit("Pass --all, or --shot (with optional --prompt)")

    for shot, prompt in jobs:
        full = prompt if args.no_suffix else f"{prompt} {suffix}"
        blob = generate(full, args.model, args.aspect)
        out = write(args.page, shot, blob, args.retry)
        print(f"{shot}  {len(blob)//1024:>5} KB  {out}")


if __name__ == "__main__":
    main()
