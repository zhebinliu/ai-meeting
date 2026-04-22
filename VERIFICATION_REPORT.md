# Meeting AI — Verification Report

**Reviewer:** Code Verifier Agent
**Date:** 2026-04-03
**Project:** Meeting AI Transcription Tool
**Verdict:** ❌ **FAIL**

---

## Executive Summary

The project has a well-organized structure and reasonable separation of concerns, but it contains **multiple critical issues that prevent it from functioning end-to-end**. The most severe problem is that the frontend calls three API endpoints (`/process`, `/export-feishu`, `/sync-requirements`) that **do not exist in the backend**, making the core workflow (recording → processing → exporting) completely broken. Additionally, the WebSocket endpoint has **zero authentication**, the Feishu retry logic contains a **potential infinite loop**, and there are **field name mismatches** between frontend and backend data contracts.

**Deployment is not possible in current state.**

---

## Critical Issues (Must Fix)

### C1. Missing API Endpoints — Complete Workflow Breakage
**Location:** `backend/routes/meeting.py`, `frontend/js/utils/api.js`
**Severity:** CRITICAL

The frontend calls three endpoints that have no corresponding backend routes:

| Frontend Call | Backend Route | Status |
|---|---|---|
| `POST /api/meetings/{id}/process` | ❌ Not defined | 405 Method Not Allowed |
| `POST /api/meetings/{id}/export-feishu` | ❌ Not defined | 404 Not Found |
| `POST /api/meetings/{id}/sync-requirements` | ❌ Not defined | 404 Not Found |

These endpoints are the core workflow — after recording stops, the frontend expects to trigger processing (polish, minutes, requirements extraction) and export to Feishu. **None of this works.**

**Fix:** Add the three route handlers in `backend/routes/meeting.py`:

```python
@router.post("/{meeting_id}/process", response_model=MeetingOut)
async def process_meeting(meeting_id: int, db: AsyncSession = Depends(get_session)):
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not meeting.raw_transcript:
        raise HTTPException(400, "No transcript to process")
    # Instantiate pipeline, run process(), update meeting fields
    ...

@router.post("/{meeting_id}/export-feishu")
async def export_to_feishu(meeting_id: int, db: AsyncSession = Depends(get_session)):
    ...

@router.post("/{meeting_id}/sync-requirements")
async def sync_requirements(meeting_id: int, db: AsyncSession = Depends(get_session)):
    ...
```

---

### C2. WebSocket Has Zero Authentication
**Location:** `backend/routes/websocket.py`
**Severity:** CRITICAL

The WebSocket endpoint `/ws/recording/{meeting_id}` accepts any connection without authentication. An attacker can:
- Connect to any meeting and inject fake audio
- Eavesdrop on transcription results
- Hijack any recording session

```python
@router.websocket("/ws/recording/{meeting_id}")
async def recording_websocket(websocket: WebSocket, meeting_id: int):
    await websocket.accept()  # No auth check at all
```

**Fix:** Add token-based authentication via query parameter or header:

```python
@router.websocket("/ws/recording/{meeting_id}")
async def recording_websocket(websocket: WebSocket, meeting_id: int, token: str = None):
    if not token or not verify_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return
    await websocket.accept()
```

---

### C3. Infinite Loop in 401 Retry Logic
**Location:** `services/feishu/doc_writer.py:73-95`, `services/feishu/bitable_writer.py:99-131`
**Severity:** CRITICAL

Both `_request_with_retry` methods retry on 401 by refreshing the token and continuing the `while True` loop **without a retry limit**:

```python
while True:
    headers = await self._authorized_headers()
    async with session.request(method, url, headers=headers, json=json_body) as resp:
        if resp.status == 401:
            await self._auth.refresh_token()
            continue  # ← No counter, no break condition = infinite loop
```

If credentials are invalid or the refresh itself fails silently, this loops forever, consuming resources and never returning.

**Fix:** Add a 401 retry counter:

```python
auth_retries = 0
MAX_AUTH_RETRIES = 2
while True:
    headers = await self._authorized_headers()
    async with session.request(...) as resp:
        if resp.status == 401:
            auth_retries += 1
            if auth_retries > MAX_AUTH_RETRIES:
                raise FeishuAuthError(code=401, message="Token refresh failed after retries")
            await self._auth.refresh_token()
            continue
        # ... rest of logic
```

---

### C4. Frontend-Backend Data Contract Mismatch (Meeting Minutes)
**Location:** `frontend/js/components/MeetingDetail.js:78-101`, `services/ai/minutes_generator.py`, `services/ai/prompts.py`
**Severity:** CRITICAL

The backend generates minutes with these field names:
```json
{"key_points": [{"topic": "...", "content": "..."}], "action_items": [{"task": "...", "owner": "..."}]}
```

The frontend expects:
```json
{"topics": [{"title": "..."}], "action_items": [{"assignee": "...", "task": "...", "due": "..."}]}
```

Specific mismatches:
| Backend Field | Frontend Field | Impact |
|---|---|---|
| `key_points` | `topics` | Topics section always empty |
| `key_points[].content` | `topics[].title` | Content lost |
| `action_items[].owner` | `action_items[].assignee` | Owner not displayed |
| `action_items[].deadline` | `action_items[].due` | Deadline not displayed |

**Fix:** Align either the backend output or the frontend rendering. Prefer fixing the frontend to match the backend's actual output.

---

### C5. Hardcoded localhost in Frontend
**Location:** `frontend/js/utils/api.js:1`, `frontend/js/components/Recorder.js:52`
**Severity:** CRITICAL (blocks deployment)

```javascript
const API_BASE = 'http://localhost:8000/api';  // Won't work in production

const wsUrl = `${wsProtocol}//${window.location.hostname || 'localhost'}:8000/ws/recording/${meeting.id}`;
// Hardcoded port 8000, no reverse proxy support
```

**Fix:** Use environment-relative URLs:

```javascript
const API_BASE = `${window.location.origin}/api`;
const wsUrl = `${wsProtocol}//${window.location.host}/ws/recording/${meeting.id}`;
```

---

### C6. Transcript Never Saved to Database
**Location:** `backend/routes/websocket.py`
**Severity:** CRITICAL

The WebSocket handler receives audio chunks and sends back placeholder transcripts, but **never saves the transcript to the database**. The `meeting.raw_transcript` field remains empty forever. Even after implementing real ASR, there's no code path that accumulates transcript text and writes it to the `Meeting` record.

```python
# WebSocket handler — audio received but transcript never persisted
while True:
    data = await websocket.receive_bytes()
    transcript_message = {"type": "transcript", "text": "[ASR integration pending]", ...}
    await websocket.send_json(transcript_message)
    # ← Missing: accumulate transcript, save to DB on disconnect
```

**Fix:** Accumulate transcript text in memory during the session, then save to `meeting.raw_transcript` on disconnect.

---

### C7. Python Dependency Inconsistency
**Location:** `backend/requirements.txt`, `requirements.txt`
**Severity:** CRITICAL (runtime crash)

The `backend/requirements.txt` is missing critical dependencies used by the `services/` directory:
- `openai` (used by `services/ai/llm_client.py`)
- `aiohttp` (used by `services/feishu/*`, `services/asr/websocket_client.py`)

These are in the root `requirements.txt` but if someone installs only `backend/requirements.txt` (as the project structure suggests), the app crashes on import.

**Fix:** Merge into a single `requirements.txt` or ensure `backend/requirements.txt` includes all dependencies.

---

## Warnings (Should Fix)

### W1. CORS Configuration Too Permissive
**Location:** `backend/main.py:33-38`
```python
allow_methods=["*"],
allow_headers=["*"],
```
Should restrict to specific methods and headers the frontend actually uses.

### W2. No Pagination on List Endpoint
**Location:** `backend/routes/meeting.py:79-86`
```python
result = await db.execute(select(Meeting).order_by(Meeting.created_at.desc()))
```
Returns all meetings without limit. Will degrade with many meetings.

### W3. `datetime.utcnow()` is Deprecated
**Location:** `backend/models/meeting.py:16`, `backend/models/requirement.py:18`, `backend/routes/meeting.py:52`, `backend/services/storage.py:37,72`
Should use `datetime.now(datetime.UTC)` instead.

### W4. Unbounded Frontend Transcript Array
**Location:** `frontend/js/components/Recorder.js:45-58`
During long meetings (2+ hours), the transcript array grows without limit, consuming increasing memory. Should virtualize or paginate.

### W5. `ScriptProcessorNode` is Deprecated
**Location:** `frontend/js/utils/audio.js:29`
```javascript
const processor = audioContext.createScriptProcessor(bufferSize, 1, 1);
```
Deprecated in favor of `AudioWorkletNode`. Works in current browsers but may break in future versions.

### W6. Duration Timer Doesn't Subtract Paused Time
**Location:** `frontend/js/components/Recorder.js:27-34`
The timer increments every second while recording, but doesn't pause the counter when recording is paused. Displayed duration will be longer than actual recording time.

### W7. No WebSocket Reconnection on Disconnect
**Location:** `frontend/js/components/Recorder.js:61-85`
If the WebSocket drops during recording (network hiccup), there's no reconnection logic. The user loses the session silently.

### W8. Meeting Detail Assumes `minutes` is an Object
**Location:** `frontend/js/components/MeetingDetail.js:81`
```javascript
const minutes = meetingData?.minutes;
```
The backend stores `meeting_minutes` as `Text` in the DB. If the LLM returns a JSON string, the frontend receives a string, not an object. Accessing `.summary` on a string returns `undefined` silently.

### W9. Shared Duplicate Code for `_request_with_retry`
**Location:** `services/feishu/doc_writer.py`, `services/feishu/bitable_writer.py`
The retry logic is duplicated verbatim in both classes. Should be extracted into a shared base class or utility.

### W10. No `Content-Type` Validation on WebSocket Binary Messages
**Location:** `backend/routes/websocket.py`
The handler blindly calls `receive_bytes()` and assumes valid PCM audio. No validation of audio format, sample rate, or chunk size.

---

## Info (Nice to Have)

### I1. Missing Type Hints in Frontend
The JavaScript code has no TypeScript or JSDoc type definitions. The API contract between frontend and backend is implicit and error-prone (as demonstrated by C4).

### I2. No React Error Boundaries
`frontend/js/app.js` — a component crash takes down the entire app with no fallback UI.

### I3. No Health Check Before WebSocket Connection
`frontend/js/components/Recorder.js` connects directly to WebSocket without checking if the backend is available.

### I4. Unused Imports
- `services/ai/llm_client.py`: `List`, `Dict`, `Any` imported but `List` unused in class methods (used only in type hints via `List[Dict[str, str]]`)
- `services/ai/text_polisher.py`: `Optional` imported but unused

### I5. `audio_utils.py` Module-Level Variable Shadowing
The variable name `exc` in `convert_to_pcm()` shadows the exception import conceptually. Minor readability issue.

### I6. No Logging Configuration for `services/` Modules
The `logging.basicConfig()` is only configured in `backend/main.py`. If `services/` modules are used standalone (e.g., in tests or scripts), logs won't appear.

---

## Test Results

| Test Case | Result | Notes |
|---|---|---|
| Create meeting via POST /api/meetings | ✅ PASS | Route exists, works |
| List meetings via GET /api/meetings | ✅ PASS | Route exists, works |
| Get single meeting | ✅ PASS | 404 handling works |
| Update meeting | ✅ PASS | Partial update works |
| List requirements for meeting | ✅ PASS | Route exists |
| WebSocket connect (valid meeting) | ⚠️ PARTIAL | Connects but no real ASR |
| WebSocket connect (invalid meeting) | ✅ PASS | Returns 404 + closes |
| POST /api/meetings/{id}/process | ❌ FAIL | Route does not exist |
| POST /api/meetings/{id}/export-feishu | ❌ FAIL | Route does not exist |
| POST /api/meetings/{id}/sync-requirements | ❌ FAIL | Route does not exist |
| Frontend record → stop → process flow | ❌ FAIL | Process endpoint 404 |
| Frontend export to Feishu | ❌ FAIL | Export endpoint 404 |
| Frontend minutes display | ❌ FAIL | Field name mismatch |
| WebSocket auth bypass attempt | ❌ FAIL | No auth = easy bypass |
| Feishu 401 infinite loop | ❌ FAIL | No retry limit on 401 |
| Long recording (simulated 3hr) | ⚠️ WARN | Transcript array unbounded |
| Audio pause → resume duration | ❌ FAIL | Duration includes paused time |

---

## Recommended Fixes (Priority Order)

1. **Add the three missing route handlers** (`/process`, `/export-feishu`, `/sync-requirements`) — the app is non-functional without them.

2. **Add WebSocket authentication** — critical security fix.

3. **Fix the 401 infinite loop** in `doc_writer.py` and `bitable_writer.py`.

4. **Align frontend minutes field names** with backend output (or vice versa).

5. **Save WebSocket transcript to database** on disconnect.

6. **Fix hardcoded localhost/port** in frontend for production deployment.

7. **Merge `requirements.txt`** into a single authoritative file.

8. **Add pagination** to list endpoints.

9. **Add WebSocket reconnection** logic in frontend.

10. **Extract shared Feishu retry logic** into a common utility.

---

## Final Verdict

# ❌ FAIL

The project cannot be deployed or used end-to-end in its current state. Three critical API endpoints are missing from the backend, the WebSocket has no authentication, the frontend-backend data contracts are misaligned, and the recording-to-processing pipeline has no path to persist transcripts. While individual components (ASR client, AI pipeline, Feishu writers) are well-structured in isolation, the integration layer that connects them is incomplete.

**Minimum viable fix:** ~2-3 hours of work to add missing routes, fix contract mismatches, and implement transcript persistence.
