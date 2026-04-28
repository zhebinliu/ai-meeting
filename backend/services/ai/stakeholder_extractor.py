"""Extract a stakeholder graph from meeting + project KB material.

The output is a small structured graph::

    {
        "stakeholders": [
            {
                "name": str,
                "aliases": [str],
                "role": str,
                "organization": str,
                "side": "internal" | "customer" | "vendor" | "unknown",
                "contact": str,
                "key_points": [str],
                "responsibilities": [str],
                "sources": [{"type": "meeting" | "kb_doc", "ref": str, "snippet": str}],
            }
        ],
        "relations": [
            {"from": str, "to": str, "type": str, "description": str}
        ],
    }

We treat people identification as fuzzy: the LLM is responsible for deduping
within a single extraction run, and a separate :func:`merge_stakeholder_maps`
helper merges across runs (e.g. on re-extraction with new KB material).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .llm_client import LLMClient
from .prompts import STAKEHOLDER_SYSTEM, STAKEHOLDER_USER

logger = logging.getLogger(__name__)


# Cap per-document text injected into the prompt — we don't need full
# 50k-char Markdown bodies, summaries + first ~1500 chars usually contain
# all the people-relevant info and keep the LLM context size sane.
_PER_DOC_CHAR_LIMIT = 1800
# Hard cap on the combined KB-context size sent to the LLM.
_TOTAL_KB_CHAR_LIMIT = 12000


class StakeholderExtractor:
    """LLM-backed extractor that produces a stakeholder graph."""

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    # ------------------------------------------------------------------
    # KB doc summarisation (input prep)
    # ------------------------------------------------------------------

    @staticmethod
    def format_kb_docs(docs: list[dict[str, Any]]) -> str:
        """Compact KB documents into a prompt-friendly string.

        Each item is summarised into "## Doc <id> - <filename>" header
        followed by the document's ``summary`` (if present) and the head
        of ``markdown_content``. Documents without textual content are
        skipped to avoid wasting tokens.
        """
        if not docs:
            return "(无参考材料)"

        chunks: list[str] = []
        used = 0
        for doc in docs:
            doc_id = str(doc.get("id") or "")
            filename = str(doc.get("filename") or "")
            summary = (doc.get("summary") or "").strip()
            body = (doc.get("markdown_content") or "").strip()
            if not (summary or body):
                continue
            head = body[:_PER_DOC_CHAR_LIMIT].strip()
            kind = (doc.get("source_kind") or "kb_doc").strip().lower()
            if kind == "internal_meeting":
                header = f"## internal_meeting:{doc_id} — {filename}"
            else:
                header = f"## kb_doc:{doc_id} — {filename}"
            piece_parts = [header]
            if summary:
                piece_parts.append(f"摘要：{summary}")
            if head:
                piece_parts.append(head)
            piece = "\n".join(piece_parts)
            if used + len(piece) > _TOTAL_KB_CHAR_LIMIT:
                # Truncate this last piece to fit within the cap, then stop.
                room = max(0, _TOTAL_KB_CHAR_LIMIT - used)
                if room > 200:
                    chunks.append(piece[:room].rstrip() + "\n...[truncated]")
                break
            chunks.append(piece)
            used += len(piece)
        return "\n\n".join(chunks) if chunks else "(参考段落均无有效文本)"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract(
        self,
        *,
        meeting_id: int,
        meeting_title: str,
        transcript: str,
        minutes: dict[str, Any] | None = None,
        kb_docs: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Run the extraction once and return the parsed graph.

        ``transcript`` should be the polished transcript when available
        (raw ASR works too, just noisier). ``minutes`` is the structured
        minutes dict (already parsed). ``kb_docs`` is a list of
        documents fetched via ``KBClient.get_document``.
        """
        if not (transcript or "").strip() and not minutes:
            raise ValueError("Need either transcript or minutes to extract stakeholders.")

        minutes_text = (
            json.dumps(minutes, ensure_ascii=False, indent=2)
            if minutes else "(无)"
        )
        kb_text = self.format_kb_docs(kb_docs or [])

        # Trim transcript so we don't blow up the context for very long meetings.
        # 30k chars covers ~3-4 hour meetings; beyond that we tail-truncate so
        # the LLM still sees the last (often most decision-rich) parts.
        max_transcript = 28000
        if len(transcript) > max_transcript:
            transcript = (
                transcript[: max_transcript // 2]
                + "\n...[中段省略以控制长度]...\n"
                + transcript[-max_transcript // 2 :]
            )

        user = STAKEHOLDER_USER.format(
            meeting_title=meeting_title or f"meeting-{meeting_id}",
            meeting_id=meeting_id,
            transcript=transcript or "(无转录)",
            minutes=minutes_text,
            kb_docs=kb_text,
        )
        messages = [
            {"role": "system", "content": STAKEHOLDER_SYSTEM},
            {"role": "user", "content": user},
        ]

        logger.info(
            "Stakeholder extract — meeting=%s, transcript=%d chars, kb_docs=%d",
            meeting_id, len(transcript), len(kb_docs or []),
        )
        raw = await self._llm.chat(messages, temperature=temperature)
        return self._parse(raw)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse(raw: str) -> dict[str, Any]:
        """Parse the LLM JSON response into a stakeholder graph dict.

        Defensive: strips Markdown fences if present, extracts the first
        balanced `{...}` block on JSON failure, and finally falls back to
        an empty graph rather than raising.
        """
        text = (raw or "").strip()
        if text.startswith("```"):
            # Strip the first fence line and the trailing fence.
            lines = text.splitlines()
            if len(lines) >= 2:
                text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:]).strip()

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            # Try to recover the largest balanced object.
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    logger.error("Failed to parse stakeholder JSON; raw head=%r", text[:300])
                    return {"stakeholders": [], "relations": []}
            else:
                logger.error("Stakeholder LLM returned no JSON object; raw head=%r", text[:300])
                return {"stakeholders": [], "relations": []}

        if not isinstance(data, dict):
            logger.warning("Stakeholder JSON is not an object: %s", type(data))
            return {"stakeholders": [], "relations": []}
        # Normalise shape so downstream code can rely on the keys.
        stakeholders = data.get("stakeholders") or []
        relations = data.get("relations") or []
        return {
            "stakeholders": [_normalise_person(p) for p in stakeholders if isinstance(p, dict)],
            "relations": [_normalise_relation(r) for r in relations if isinstance(r, dict)],
        }


# ---------------------------------------------------------------------------
# Cross-run merge helpers
# ---------------------------------------------------------------------------


def _normalise_person(p: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw person dict from the LLM into a canonical shape."""
    name = (p.get("name") or "").strip()
    aliases = [str(a).strip() for a in (p.get("aliases") or []) if str(a).strip()]
    return {
        "name": name,
        "aliases": _dedupe_preserve_order(aliases),
        "role": (p.get("role") or "").strip(),
        "organization": (p.get("organization") or "").strip(),
        "side": (p.get("side") or "unknown").strip().lower() or "unknown",
        "contact": (p.get("contact") or "").strip(),
        "key_points": [
            str(x).strip() for x in (p.get("key_points") or []) if str(x).strip()
        ],
        "responsibilities": [
            str(x).strip() for x in (p.get("responsibilities") or []) if str(x).strip()
        ],
        "sources": _normalise_sources(p.get("sources") or []),
    }


def _normalise_relation(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": (r.get("from") or "").strip(),
        "to": (r.get("to") or "").strip(),
        "type": (r.get("type") or "").strip() or "works_with",
        "description": (r.get("description") or "").strip(),
    }


def _normalise_sources(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    allowed = {"meeting", "kb_doc", "prior_meeting"}
    for s in raw:
        if not isinstance(s, dict):
            continue
        raw_t = (s.get("type") or "meeting").strip().lower()
        if raw_t not in allowed:
            raw_t = "meeting"
        out.append({
            "type": raw_t,
            "ref": (s.get("ref") or "").strip(),
            "snippet": (s.get("snippet") or "").strip(),
        })
    return out


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        key = x.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def _identity_keys(person: dict[str, Any]) -> set[str]:
    """Return a set of normalised name-keys identifying this person.

    Two persons are considered the same iff their key sets intersect.
    """
    keys: set[str] = set()
    for raw in [person.get("name", ""), *person.get("aliases", [])]:
        s = (raw or "").strip().lower()
        if s:
            keys.add(s)
    return keys


def merge_stakeholder_maps(*maps: dict[str, Any]) -> dict[str, Any]:
    """Union-merge multiple stakeholder graphs into one.

    People are matched by overlapping ``name``/``aliases`` (case-insensitive
    string equality, post-trim). Sources are concatenated and deduped.
    Relations are deduped by ``(from, to, type)`` triple.
    """
    merged_people: list[dict[str, Any]] = []

    def _find(person: dict[str, Any]) -> dict[str, Any] | None:
        person_keys = _identity_keys(person)
        if not person_keys:
            return None
        for existing in merged_people:
            if _identity_keys(existing) & person_keys:
                return existing
        return None

    for graph in maps:
        if not graph:
            continue
        for p in graph.get("stakeholders", []) or []:
            if not isinstance(p, dict):
                continue
            p = _normalise_person(p)
            if not p["name"]:
                continue
            existing = _find(p)
            if existing is None:
                merged_people.append(p)
                continue
            # Merge into existing.
            existing["aliases"] = _dedupe_preserve_order(
                existing["aliases"] + ([p["name"]] if p["name"] != existing["name"] else []) + p["aliases"]
            )
            for field in ("role", "organization", "contact"):
                if not existing.get(field) and p.get(field):
                    existing[field] = p[field]
            # Side: prefer non-unknown.
            if existing.get("side", "unknown") == "unknown" and p.get("side") and p["side"] != "unknown":
                existing["side"] = p["side"]
            existing["key_points"] = _dedupe_preserve_order(
                existing.get("key_points", []) + p.get("key_points", [])
            )
            existing["responsibilities"] = _dedupe_preserve_order(
                existing.get("responsibilities", []) + p.get("responsibilities", [])
            )
            # Sources: dedupe by (type, ref, snippet) triple.
            seen = {(s["type"], s["ref"], s["snippet"]) for s in existing.get("sources", [])}
            for s in p.get("sources", []):
                key = (s["type"], s["ref"], s["snippet"])
                if key in seen:
                    continue
                seen.add(key)
                existing.setdefault("sources", []).append(s)

    merged_relations: list[dict[str, Any]] = []
    seen_rel: set[tuple[str, str, str]] = set()
    for graph in maps:
        if not graph:
            continue
        for r in graph.get("relations", []) or []:
            if not isinstance(r, dict):
                continue
            r = _normalise_relation(r)
            if not (r["from"] and r["to"]):
                continue
            key = (r["from"].lower(), r["to"].lower(), r["type"].lower())
            if key in seen_rel:
                continue
            seen_rel.add(key)
            merged_relations.append(r)

    return {"stakeholders": merged_people, "relations": merged_relations}
