"""Download and pin the private encoder models (phase D, phase R) for the local encoder service.

    python scripts/fetch_models.py [--dir D:/AssureOpsModels/hf]

Records the exact Hugging Face revision and a weight-file digest in
packages/ai/assureops_ai/encoder_pins.json. Generation models (phases A, B/E,
C, F) are pulled into Ollama by scripts/pull_generation_models.ps1.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "ai"))

MODELS = {
    "cross-encoder/nli-deberta-v3-small": {"phase": "D", "kind": "classify", "license": "Apache-2.0"},
    "BAAI/bge-small-en-v1.5": {"phase": "R", "kind": "embed", "license": "MIT"},
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="D:/AssureOpsModels/hf")
    args = parser.parse_args()
    from huggingface_hub import HfApi, snapshot_download

    from assureops_ai.encoder_server import _artifact_digest

    api = HfApi()
    pins = {}
    for repo, meta in MODELS.items():
        revision = api.model_info(repo).sha
        path = snapshot_download(repo, revision=revision, cache_dir=args.dir,
                                 allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "spm.model", "tokenizer*"])
        pins[repo] = {**meta, "revision": revision, "artifact_digest": _artifact_digest(Path(path))}
        print(f"{repo}: revision {revision[:12]}, digest {pins[repo]['artifact_digest'][:16]}")
    out = ROOT / "packages" / "ai" / "assureops_ai" / "encoder_pins.json"
    out.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"pins written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
