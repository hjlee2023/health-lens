"""
Server-side YouTube transcript fetching, using the youtube-transcript-api 1.x API.

From a residential IP this reliably pulls auto-generated (ASR) captions as well. Datacenter
IPs such as AWS are often blocked, so prefer the transcript the extension sends: main.py uses
that when present and only falls back to this module when it is missing.
"""

def fetch(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("[transcript] youtube-transcript-api is not installed")
        return None

    ytt = YouTubeTranscriptApi()

    # 1) Prefer ko, then en (manual or auto-generated, either is fine)
    try:
        fetched = ytt.fetch(video_id, languages=["ko", "en"])
        return _join(fetched)
    except Exception:
        pass

    # 2) Pick from the track list directly (includes ASR and translated tracks)
    try:
        tlist = ytt.list(video_id)
        for langs in (["ko"], ["en"]):
            try:
                return _join(tlist.find_transcript(langs).fetch())
            except Exception:
                continue
        # Last resort: take any track, translating it to Korean when possible
        for tr in tlist:
            try:
                if tr.is_translatable:
                    return _join(tr.translate("ko").fetch())
                return _join(tr.fetch())
            except Exception:
                continue
    except Exception as e:  # noqa: BLE001
        print(f"[transcript] failed ({video_id}): {e}")
    return None


def _join(fetched) -> str | None:
    text = " ".join(getattr(sn, "text", "") for sn in fetched).replace("\n", " ").strip()
    return text or None
