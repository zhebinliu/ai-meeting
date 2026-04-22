# Meeting AI — Verification Report V2

**Reviewer:** Code Verifier Agent (V2)
**Date:** 2026-04-03
**Project:** Meeting AI Transcription Tool
**Context:** Re-check after 7 issues were supposedly fixed
**Previous Verdict:** ❌ FAIL
**Current Verdict:** 🟡 **NEEDS REVISION**

---

## Fix Verification Summary

| # | Issue | Status | Notes |
|---|---|---|---|
| 1 | 3 Missing API Endpoints | ✅ **FIXED** | All 3 routes implemented with proper logic |
| 2 | WebSocket Authentication | ✅ **FIXED** | Token auth added, 4001 close on failure |
| 3 | Infinite Retry Loop | ✅ **FIXED** | MAX_RETRIES=3 with counters in both writers |
| 4 | Frontend-Backend Data Contract | ✅ **FIXED** | Frontend uses `key_points`, `owner`, `deadline` |
| 5 | Transcript Not Saved to DB | ✅ **FIXED** | Persists to `raw_transcript` on each final segment |
| 6 | Hardcoded localhost:8000 | ✅ **FIXED** | `window.API_BASE`/`WS_BASE` with config in index.html |
| 7 | Dependencies Split | ✅ **FIXED** | `backend/requirements.txt` has all 11 deps |

---

## Detailed Fix Verification

### Issue 1: 3 Missing API Endpoints ✅ FIXED
**File:** `backend/routes/meeting.py`

All three endpoints are now defined:
- `POST /{meeting_id}/process` (line ~113) — Imports `MeetingAIPipeline`, runs processing, saves results + requirements
- `POST /{meeting_id}/export-feishu` (line ~168) — Imports `FeishuAuth` + `FeishuDocWriter`, creates doc
- `POST /{meeting_id}/sync-requirements` (line ~210) — Imports `FeishuAuth` + `FeishuBitableWriter`, syncs to Bitable

All imports are correct. Error handling with try/except and proper HTTP status codes (404, 400, 500).

### Issue 2: WebSocket Authentication ✅ FIXED
**File:** `backend/routes/websocket.py`

- `token: str = Query(...)` parameter added (required query param)
- Validated against `settings.WS_AUTH_TOKEN`
- Closes with code 4001 on invalid token
- Meeting existence check also added after auth

### Issue 3: Infinite Retry Loop ✅ FIXED
**Files:** `services/feishu/doc_writer.py`, `services/feishu/bitable_writer.py`

Both files now have:
- `MAX_RETRIES = 3` class constant
- `auth_retries` counter with `> self.MAX_RETRIES` guard → raises `FeishuAuthError`
- `rate_limit_retries` counter with same guard → raises `FeishuRateLimitError`

### Issue 4: Frontend-Backend Data Contract ✅ FIXED
**File:** `frontend/js/components/MeetingDetail.js`

Frontend now uses the correct field names:
- `minutes.key_points` (not `topics`)
- `point.topic` and `point.content` for key_points
- `d.owner` (not `assignee`)
- `item.owner` and `item.deadline` (not `due`)
- `item.task` for action items

### Issue 5: Transcript Not Saved to DB ✅ FIXED
**File:** `backend/routes/websocket.py`

Inside the WebSocket loop, after each final transcript:
```python
if is_final and transcript_text:
    async with async_session_factory() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting:
            existing = meeting.raw_transcript or ""
            meeting.raw_transcript = existing + transcript_text + "\n"
            await db.commit()
```

### Issue 6: Hardcoded localhost:8000 ✅ FIXED
**Files:** `frontend/index.html`, `frontend/js/utils/api.js`, `frontend/js/components/Recorder.js`

- `index.html` has config block: `window.API_BASE` and `window.WS_BASE`
- `api.js` uses `window.API_BASE || 'http://localhost:8000/api'`
- `Recorder.js` constructs WS URL using `WS_BASE`

### Issue 7: Dependencies Split ✅ FIXED
**File:** `backend/requirements.txt`

Contains all 11 dependencies: fastapi, uvicorn, websockets, sqlalchemy, aiosqlite, python-dotenv, pydantic, python-multipart, aiohttp, openai, pydub. Root `requirements.txt` has only 3 (openai, aiohttp, pydub) — still a minor inconsistency but backend is self-sufficient.

---

## New Issues Introduced by Fixes

### N1. 🔴 CRITICAL — `meeting_minutes` Returned as String, Frontend Expects Object
**Location:** `backend/routes/meeting.py` (MeetingOut schema), `frontend/js/components/MeetingDetail.js`

The `MeetingOut` response model declares `meeting_minutes: str`. The pipeline stores minutes as `json.dumps(result)` → a JSON string in the DB. When the frontend fetches `api.getMeeting(id)`, it receives `meeting_minutes` as a **string**, not a parsed object.

MeetingDetail.js then does:
```javascript
const minutes = meetingData?.minutes;  // This is a JSON string!
minutes.summary  // → undefined (accessing property on string)
minutes.key_points  // → undefined
```

The minutes tab will **always show "会议纪要正在生成中..."** even when data exists, because all `.summary`, `.key_points`, etc. accesses on a string return `undefined`.

**Fix:** Either:
- Parse in the backend before returning: `meeting_minutes` should be a dict/object in the response
- Or parse in the frontend: `const minutes = JSON.parse(meetingData?.meeting_minutes || '{}')`

### N2. ⚠️ WARNING — WebSocket Race Condition on Transcript Writes
**Location:** `backend/routes/websocket.py`

Each final transcript segment opens a new DB session (`async with async_session_factory() as db:`). Under rapid audio chunks, multiple concurrent sessions could read-modify-write `raw_transcript` simultaneously, causing lost updates.

**Fix:** Accumulate transcript in memory during the session, write once on disconnect. Or use a lock per meeting_id.

### N3. ⚠️ WARNING — Hardcoded Default WS Auth Token
**Location:** `backend/config.py`

```python
WS_AUTH_TOKEN: str = os.getenv("WS_AUTH_TOKEN", "default_ws_token_change_me")
```

The default token is `default_ws_token_change_me`. If deployed without setting the env var, anyone can authenticate. The frontend also hardcodes this value:
```javascript
const wsUrl = `${WS_BASE}/ws/recording/${meeting.id}?token=default_ws_token_change_me`;
```

**Fix:** Require the env var (no default or raise on startup). Token should not be in frontend source.

### N4. ⚠️ WARNING — `export-feishu` Creates New Bitable Every Call
**Location:** `backend/routes/meeting.py` (sync-requirements endpoint)

```python
bitable_url = await writer.sync_requirements(app_token="", requirements=requirements)
```

`app_token=""` causes `FeishuBitableWriter.sync_requirements` to create a **new Bitable on every sync call**. Multiple calls create multiple orphaned Bitables.

**Fix:** Store the app_token in the meeting record or a config, and reuse it.

### N5. ℹ️ INFO — Root `requirements.txt` Still Has Only 3 Deps
**Location:** `/Users/bot/.openclaw/workspace/meeting-ai/requirements.txt`

Root file has only `openai`, `aiohttp`, `pydub`. While `backend/requirements.txt` is now complete, someone following a README that references the root file will get an incomplete install.

**Fix:** Delete the root file or make it reference/superset the backend one.

---

## Remaining Issues from Original Report

### W1. CORS Configuration Too Permissive (Still Present)
**Location:** `backend/main.py`
```python
allow_methods=["*"],
allow_headers=["*"],
```
No change. Should restrict to specific methods/headers.

### W2. No Pagination on List Endpoint (Still Present)
**Location:** `backend/routes/meeting.py`
Returns all meetings without limit.

### W3. `datetime.utcnow()` Deprecated (Still Present)
**Location:** Multiple files. Should use `datetime.now(datetime.UTC)`.

### W4. Unbounded Frontend Transcript Array (Still Present)
**Location:** `frontend/js/components/Recorder.js`

### W5. `ScriptProcessorNode` Deprecated (Still Present)
**Location:** `frontend/js/utils/audio.js`

### W6. Duration Timer Doesn't Subtract Paused Time (Still Present)
**Location:** `frontend/js/components/Recorder.js`

### W7. No WebSocket Reconnection on Disconnect (Still Present)
**Location:** `frontend/js/components/Recorder.js`

### W9. Duplicated `_request_with_retry` Code (Still Present)
**Location:** `services/feishu/doc_writer.py`, `services/feishu/bitable_writer.py`

---

## Final Assessment

### What's Better
All 7 critical issues from the original report have been **correctly fixed**. The backend now has all required endpoints, WebSocket auth works, retry loops are bounded, data contracts are aligned, transcripts persist, URLs are configurable, and dependencies are consolidated.

### What's Still Broken
**N1 is a showstopper.** The meeting minutes display feature is non-functional because `meeting_minutes` is returned as a JSON string but the frontend treats it as an object. The most visible feature of the app (viewing meeting minutes) doesn't work.

### Verdict

# 🟡 NEEDS REVISION

**Not FAIL** — the major structural issues are fixed. But **N1 must be resolved** before the app is functional. The minutes tab is the primary user-facing feature, and it silently fails.

**Minimum fix:** Parse `meeting_minutes` JSON string in the frontend (`JSON.parse(meetingData.meeting_minutes)`) or change the backend response to return it as a dict.

**Time to fix:** ~15 minutes for N1, ~30 minutes for N3+N4.
