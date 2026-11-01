"""Speaker identification: silero VAD (bundled with faster-whisper) + ECAPA-TDNN embeddings
(speechbrain) + agglomerative clustering. No tokens, all local.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from app import cache, config, media

log = logging.getLogger(__name__)
SR = 16000
WIN_S, HOP_S = 1.5, 0.75
AUTO_DISTANCE = 0.65          # cosine distance threshold when the number of speakers is unknown
MIN_CLUSTER_WINDOWS = 3


class SpeakerEmbedder(Protocol):
    name: str

    def embed(self, windows: np.ndarray) -> np.ndarray: ...   # (n, WIN samples) -> (n, d)


class EcapaEmbedder:
    name = "ecapa-voxceleb"

    def __init__(self) -> None:
        import torch
        from speechbrain.lobes.features import Fbank
        from speechbrain.lobes.models.ECAPA_TDNN import ECAPA_TDNN

        from app.transcribe import ensure_model

        ckpt = ensure_model("ecapa") / "embedding_model.ckpt"
        self.torch = torch
        self.fbank = Fbank(n_mels=80)
        self.model = ECAPA_TDNN(80, channels=[1024, 1024, 1024, 1024, 3072], kernel_sizes=[5, 3, 3, 3, 1],
                                dilations=[1, 2, 3, 4, 1], attention_channels=128, lin_neurons=192)
        state = torch.load(str(ckpt), map_location="cpu", weights_only=True)   # tensors only, no code
        self.model.load_state_dict(state)
        self.model.eval()

    def embed(self, windows: np.ndarray) -> np.ndarray:
        torch = self.torch
        out = []
        with torch.inference_mode():
            for i in range(0, len(windows), 32):
                wav = torch.from_numpy(np.ascontiguousarray(windows[i:i + 32], dtype=np.float32))
                feats = self.fbank(wav)
                feats = feats - feats.mean(dim=1, keepdim=True)        # sentence mean normalisation
                out.append(self.model(feats).squeeze(1).cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 192), dtype=np.float32)


_DEFAULT: SpeakerEmbedder | None = None
_LOCK = threading.Lock()


def default_speaker_embedder() -> SpeakerEmbedder:
    global _DEFAULT
    with _LOCK:
        if _DEFAULT is None:
            _DEFAULT = EcapaEmbedder()
        return _DEFAULT


def silero_regions(audio: np.ndarray) -> list[tuple[float, float]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    ts = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300, speech_pad_ms=100))
    return [(t["start"] / SR, t["end"] / SR) for t in ts]


def make_windows(audio: np.ndarray, regions: list[tuple[float, float]]):
    win, hop = int(WIN_S * SR), int(HOP_S * SR)
    chunks, spans = [], []
    for a, b in regions:
        s, e = int(a * SR), min(len(audio), int(b * SR))
        if e - s < int(0.5 * SR):
            continue
        pos = s
        while True:
            seg = audio[pos:pos + win]
            if len(seg) < win:
                seg = np.pad(seg, (0, win - len(seg)))
            chunks.append(seg)
            spans.append((pos / SR, min(e, pos + win) / SR))
            if pos + win >= e:
                break
            pos += hop
    return (np.stack(chunks) if chunks else np.zeros((0, win), np.float32)), spans


def cluster(emb: np.ndarray, num_speakers: int | None) -> np.ndarray:
    from sklearn.cluster import AgglomerativeClustering

    n = len(emb)
    if n == 0:
        return np.zeros(0, dtype=int)
    if n == 1 or num_speakers == 1:
        return np.zeros(n, dtype=int)
    emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    if num_speakers:
        k = min(num_speakers, n)
        labels = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(emb)
    else:
        labels = AgglomerativeClustering(n_clusters=None, distance_threshold=AUTO_DISTANCE,
                                         metric="cosine", linkage="average").fit_predict(emb)
        # merge tiny clusters into the nearest large one; cap the speaker count
        counts = np.bincount(labels)
        big = [c for c in np.argsort(-counts) if counts[c] >= MIN_CLUSTER_WINDOWS][:config.MAX_SPEAKERS]
        if big:
            cents = np.stack([emb[labels == c].mean(0) for c in big])
            for i in range(n):
                if labels[i] not in big:
                    labels[i] = big[int(np.argmax(cents @ emb[i]))]
    # median-like smoothing: isolated single-window flips take neighbours' label
    for i in range(1, n - 1):
        if labels[i - 1] == labels[i + 1] != labels[i]:
            labels[i] = labels[i - 1]
    return labels


def turns_from(spans, labels) -> list[dict]:
    """Merge consecutive windows -> [{start, end, speaker}] with speakers named by first appearance."""
    names: dict[int, str] = {}
    turns: list[dict] = []
    for (a, b), lab in zip(spans, labels):
        lab = int(lab)
        names.setdefault(lab, f"Speaker {len(names) + 1}")
        spk = names[lab]
        if turns and turns[-1]["speaker"] == spk and a <= turns[-1]["end"] + 0.5:
            turns[-1]["end"] = max(turns[-1]["end"], b)
        else:
            if turns and a < turns[-1]["end"]:          # overlapping hop: split the difference
                mid = (a + turns[-1]["end"]) / 2
                turns[-1]["end"], a = mid, mid
            turns.append({"start": round(a, 2), "end": round(b, 2), "speaker": spk})
    return turns


def diarize_audio(audio: np.ndarray, embedder: SpeakerEmbedder, num_speakers: int | None = None,
                  vad: Callable[[np.ndarray], list] = silero_regions) -> list[dict]:
    windows, spans = make_windows(audio, vad(audio))
    if not spans:
        return []
    return turns_from(spans, cluster(embedder.embed(windows), num_speakers))


def speaker_at(turns: list[dict], t: float) -> str | None:
    best, dist = None, 1e9
    for tr in turns:
        if tr["start"] <= t <= tr["end"]:
            return tr["speaker"]
        d = min(abs(t - tr["start"]), abs(t - tr["end"]))
        if d < dist:
            best, dist = tr["speaker"], d
    return best if dist <= 2.0 else None


def apply_speakers(result: dict, turns: list[dict]) -> None:
    """Assign speakers to words/segments, split segments on speaker change, rebuild paragraphs."""
    from app.paragraphs import build_paragraphs

    new_segs: list[dict] = []
    for s in result.get("segments", []):
        words = s.get("words") or []
        if not words:
            new_segs.append({**s, "speaker": speaker_at(turns, (s["start"] + s["end"]) / 2)})
            continue
        cur: list[dict] = []
        cur_spk = None
        for w in words:
            spk = speaker_at(turns, (w["start"] + w["end"]) / 2) or cur_spk
            if cur and spk != cur_spk:
                new_segs.append(_seg_from_words(cur, cur_spk))
                cur = []
            cur.append(w)
            cur_spk = spk
        if cur:
            new_segs.append(_seg_from_words(cur, cur_spk))
    result["segments"] = new_segs
    result["paragraphs"] = build_paragraphs(new_segs)
    result["speakers"] = sorted({s["speaker"] for s in new_segs if s.get("speaker")},
                                key=lambda x: (len(x), x))


def _seg_from_words(words: list[dict], spk: str | None) -> dict:
    return {"start": words[0]["start"], "end": words[-1]["end"],
            "text": "".join(w["word"] for w in words).strip(), "words": words, "speaker": spk}


def diarize_file(src: str | Path, result: dict, embedder: SpeakerEmbedder,
                 num_speakers: int | None = None, vad=silero_regions) -> list[dict]:
    """Turns for a media file (cached per file hash + settings)."""
    name = f"diar_{embedder.name}_{int(num_speakers or 0)}".replace("-", "_")
    hit = cache.read_json(result["file_hash"], name)
    if isinstance(hit, list) and all(isinstance(t, dict) and {"start", "end", "speaker"} <= t.keys() for t in hit):
        return hit
    from app.pipeline import read_wav

    with media.temp_audio(src) as wav:
        audio = read_wav(wav)
    turns = diarize_audio(audio, embedder, num_speakers, vad)
    cache.write_json(result["file_hash"], name, turns)
    log.info("Diarization: %d turns, %d speakers", len(turns), len({t["speaker"] for t in turns}))
    return turns
