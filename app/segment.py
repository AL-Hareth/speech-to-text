"""Topic segmentation by embedding shift (TextTiling-style depth scores) + topic titles."""
from __future__ import annotations

import re
from collections import Counter

import numpy as np

from app.export import fmt_mmss

MIN_TOPIC_PARAS = 3
MIN_TOPIC_SECONDS = 90.0
WINDOW = 2

_STOP_EN = set("""a an the and or but if then so of to in on at for with by from as is are was were be been
being this that these those it its we you they he she i our your their there here what which who whom how
why when where not no yes do does did done can could will would should may might must also just very more
most some any all each other into over under about than too only own same such now okay ok right like
let lets get got going go one two three first second next thing things way well actually basically""".split())
_STOP_AR = set("""في من على الى إلى عن مع هذا هذه هاد هاي هيك يعني اللي الي هو هي هم انا أنا احنا إحنا انتو
انتم كان كانت بس لا ما مش كمان طيب عشان لانه لأنه شو ليش وين كيف هلأ هلق رح راح بدي بدنا فيه فيها
اذا إذا لما او أو ثم و يا قد كل بعض ال ولا الا إلا هون هناك عند لازم كثير كتير شي شوي""".split())
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}|[ء-ي]{3,}")


def _boundaries(vecs: np.ndarray, paragraphs: list[dict]) -> list[int]:
    n = len(paragraphs)
    if n < 2 * MIN_TOPIC_PARAS:
        return [0]
    gaps = np.zeros(n - 1)
    for i in range(n - 1):
        left = vecs[max(0, i - WINDOW + 1): i + 1].mean(axis=0)
        right = vecs[i + 1: i + 1 + WINDOW].mean(axis=0)
        denom = (np.linalg.norm(left) * np.linalg.norm(right)) or 1.0
        gaps[i] = float(left @ right / denom)
    depth = np.zeros_like(gaps)
    for i in range(len(gaps)):
        # local peaks (TextTiling): climb while similarity rises
        l = i
        while l > 0 and gaps[l - 1] >= gaps[l]:
            l -= 1
        r = i
        while r < len(gaps) - 1 and gaps[r + 1] >= gaps[r]:
            r += 1
        depth[i] = (gaps[l] - gaps[i]) + (gaps[r] - gaps[i])
    thr = depth.mean() + 0.5 * depth.std()
    cands = sorted(np.where(depth > max(thr, 1e-6))[0], key=lambda i: -depth[i])
    starts = [0]
    for i in cands:
        b = int(i) + 1
        ok = all(abs(b - s) >= MIN_TOPIC_PARAS for s in starts) and \
            all(abs(paragraphs[b]["start"] - paragraphs[s]["start"]) >= MIN_TOPIC_SECONDS for s in starts)
        if ok and n - b >= MIN_TOPIC_PARAS:
            starts.append(b)
    return sorted(starts)


def _keywords(texts: list[str], all_texts: list[str], k: int = 3) -> list[str]:
    def toks(t: str) -> list[str]:
        out = []
        for w in _TOKEN.findall(t):
            lw = w.lower()
            if lw in _STOP_EN or w in _STOP_AR:
                continue
            out.append(lw if w.isascii() else w)
        return out

    local = Counter(w for t in texts for w in toks(t))
    df = Counter(w for t in all_texts for w in set(toks(t)))
    n = max(1, len(all_texts))
    score = {w: c * np.log(1 + n / df[w]) * (1.5 if w.isascii() else 1.0) for w, c in local.items()}
    return [w for w, _ in sorted(score.items(), key=lambda x: -x[1])[:k]]


def segment_topics(paragraphs: list[dict], vecs: np.ndarray,
                   sections: list[dict] | None = None) -> list[dict]:
    """Return [{title, start_para, end_para, start, end}] — usable as PDF TOC sections."""
    if not paragraphs:
        return []
    starts = _boundaries(vecs, paragraphs)
    all_texts = [p.get("text", "") for p in paragraphs]
    topics = []
    for j, s in enumerate(starts):
        e = (starts[j + 1] if j + 1 < len(starts) else len(paragraphs)) - 1
        span = paragraphs[s:e + 1]
        title = None
        if sections:
            ids = Counter(p["link"]["section_id"] for p in span
                          if isinstance(p.get("link"), dict) and p["link"].get("section_id") is not None
                          and not p.get("unsure"))
            if ids:
                sid = ids.most_common(1)[0][0]
                title = sections[sid]["title"]
        if not title:
            kw = _keywords([p.get("text", "") for p in span], all_texts)
            title = " · ".join(kw) if kw else f"Topic {j + 1}"
        t0, t1 = span[0]["start"], span[-1]["end"]
        topics.append({"title": f"{title}  ({fmt_mmss(t0)}–{fmt_mmss(t1)})", "start_para": s,
                       "end_para": e, "start": t0, "end": t1})
    return topics
