"""Private encoder service for phase D (NLI cross-encoder) and phase R (embeddings), CPU only.

    python -m assureops_ai.encoder_server --port 8730

TEI-compatible routes: POST /embed {"model", "inputs": [text]} and POST /predict
{"model", "inputs": [[premise, hypothesis]]}. Models load from a local,
pinned snapshot (`ENCODER_MODELS_DIR`); /info reports the exact revision and a
SHA-256 over the weight files so qualification records name the artifact.
One request is processed at a time (bounded concurrency on a small host).
"""

import argparse
import hashlib
import json
import os
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

PINS = Path(__file__).with_name("encoder_pins.json")
MODELS_DIR = Path(os.environ.get("ENCODER_MODELS_DIR", "D:/AssureOpsModels/hf"))
MAX_INPUTS = 32
MAX_CHARS = 4000

app = FastAPI(title="AssureOps private encoders")
_lock = threading.Lock()
_loaded: dict[str, tuple] = {}


def pins() -> dict:
    return json.loads(PINS.read_text(encoding="utf-8"))


def _artifact_digest(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(path.rglob("*")):
        if f.is_file() and f.suffix in (".safetensors", ".bin", ".json", ".model", ".txt"):
            h.update(f.name.encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def _load(model: str):
    if model in _loaded:
        return _loaded[model]
    pin = pins().get(model)
    if pin is None:
        raise HTTPException(404, f"model {model} is not pinned on this host")
    import torch
    from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(4)
    org, name = model.split("/")
    path = MODELS_DIR / f"models--{org}--{name}" / "snapshots" / pin["revision"]
    if _artifact_digest(path) != pin["artifact_digest"]:
        raise HTTPException(409, f"weights for {model} do not match the pinned digest")
    tok = AutoTokenizer.from_pretrained(path, local_files_only=True)
    cls = AutoModelForSequenceClassification if pin["kind"] == "classify" else AutoModel
    net = cls.from_pretrained(path, local_files_only=True).eval()
    _loaded[model] = (tok, net, pin)
    return _loaded[model]


class EmbedIn(BaseModel):
    model: str
    inputs: list[str] = Field(min_length=1, max_length=MAX_INPUTS)
    truncate: bool = True


class PredictIn(BaseModel):
    model: str
    inputs: list[list[str]] = Field(min_length=1, max_length=MAX_INPUTS)
    raw_scores: bool = False


@app.get("/info")
def info():
    return {name: {k: v for k, v in pin.items() if k != "path"} for name, pin in pins().items()}


@app.post("/embed")
def embed(body: EmbedIn):
    import torch

    with _lock:
        tok, net, pin = _load(body.model)
        if pin["kind"] != "embed":
            raise HTTPException(422, "model is not an embedding model")
        batch = tok([t[:MAX_CHARS] for t in body.inputs], padding=True, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad():
            out = net(**batch).last_hidden_state[:, 0]  # BGE uses the CLS vector
        vectors = torch.nn.functional.normalize(out, dim=-1)
    return vectors.tolist()


@app.post("/predict")
def predict(body: PredictIn):
    import torch

    if any(len(pair) != 2 for pair in body.inputs):
        raise HTTPException(422, "each input must be [premise, hypothesis]")
    with _lock:
        tok, net, pin = _load(body.model)
        if pin["kind"] != "classify":
            raise HTTPException(422, "model is not a classifier")
        batch = tok([p[0][:MAX_CHARS] for p in body.inputs], [p[1][:MAX_CHARS] for p in body.inputs],
                    padding=True, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad():
            probs = torch.softmax(net(**batch).logits, dim=-1)
    labels = net.config.id2label
    return [[{"label": labels[i].lower(), "score": round(float(p[i]), 6)} for i in range(len(labels))] for p in probs]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8730)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
