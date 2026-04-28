/* API utilities for backend communication.
 *
 * NOTE: this file is loaded as a classic <script>, NOT a module — so the
 * top-level `const api = {...}` would otherwise stay inside the script's
 * own lexical scope. The `window.api = api;` line at the bottom is what
 * actually exposes it to the rest of the components. We also seed an
 * empty `window.api` placeholder up-front so a half-loaded cache or a
 * partial parse error here surfaces as a clearly-named "missing method"
 * instead of the cryptic "Cannot read properties of undefined". */

window.api = window.api || {};

const API_BASE = window.API_BASE || 'http://localhost:8000/api';
const WS_BASE = window.WS_BASE || 'ws://localhost:8000';
const WS_TOKEN = window.WS_TOKEN || '';

const api = {
    /**
     * Create a new meeting record on the backend.
     * @param {string} title - Meeting title (optional)
     * @returns {Promise<Object>} - Meeting object with id
     */
    createMeeting: async (title) => {
        const res = await fetch(`${API_BASE}/meetings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
        if (!res.ok) throw new Error(`Create meeting failed: ${res.status}`);
        return res.json();
    },

    /**
     * Create a meeting directly from pasted transcript text.
     * Skips ASR and runs the AI pipeline in background on the server.
     * @param {string} title - Meeting title
     * @param {string} transcript - Raw transcript text
     * @param {{kb_project_id?: string|null, kb_project_name?: string|null}} [extra] - optional KB project so stakeholder extraction merges project docs
     * @returns {Promise<Object>} - Meeting object with id
     */
    createMeetingFromText: async (title, transcript, extra = {}) => {
        const res = await fetch(`${API_BASE}/meetings/from-text`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title,
                transcript,
                kb_project_id: extra.kb_project_id || null,
                kb_project_name: extra.kb_project_name || null,
            })
        });
        if (!res.ok) {
            let detail = `Create from text failed: ${res.status}`;
            try {
                const data = await res.json();
                if (data.detail) detail = data.detail;
            } catch (e) {}
            throw new Error(detail);
        }
        return res.json();
    },

    /**
     * Fetch all meetings.
     * @returns {Promise<Array>} - List of meeting objects
     */
    getMeetings: async () => {
        const res = await fetch(`${API_BASE}/meetings`);
        if (!res.ok) throw new Error(`Get meetings failed: ${res.status}`);
        return res.json();
    },

    /**
     * Fetch a single meeting by ID.
     * @param {string} id - Meeting ID
     * @returns {Promise<Object>} - Meeting detail object
     */
    getMeeting: async (id) => {
        const res = await fetch(`${API_BASE}/meetings/${id}`);
        if (!res.ok) throw new Error(`Get meeting failed: ${res.status}`);
        return res.json();
    },

    /**
     * Trigger post-recording processing (polish, minutes, requirements extraction).
     * @param {string} id - Meeting ID
     * @returns {Promise<Object>}
     */
    processMeeting: async (id) => {
        const res = await fetch(`${API_BASE}/meetings/${id}/process`, {
            method: 'POST'
        });
        if (!res.ok) throw new Error(`Process meeting failed: ${res.status}`);
        return res.json();
    },

    /**
     * Export meeting to Feishu doc.
     * @param {string} id - Meeting ID
     * @returns {Promise<Object>}
     */
    exportToFeishu: async (id) => {
        const res = await fetch(`${API_BASE}/meetings/${id}/export-feishu`, {
            method: 'POST'
        });
        if (!res.ok) throw new Error(`Export failed: ${res.status}`);
        return res.json();
    },

    /**
     * Sync requirements to Feishu Bitable.
     * @param {string} id - Meeting ID
     * @returns {Promise<Object>}
     */
    syncRequirements: async (id) => {
        const res = await fetch(`${API_BASE}/meetings/${id}/sync-requirements`, {
            method: 'POST'
        });
        if (!res.ok) throw new Error(`Sync failed: ${res.status}`);
        return res.json();
    },

    /**
     * Delete a meeting by ID.
     * @param {string|number} id - Meeting ID
     */
    deleteMeeting: async (id) => {
        const res = await fetch(`${API_BASE}/meetings/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
    },

    /**
     * Upload an audio file for transcription and processing.
     * @param {File} file - Audio file object
     * @param {string} title - Meeting title (optional)
     * @param {Function} onProgress - Callback for upload progress ({percent, loaded, total})
     * @param {string} asrEngine - ASR engine to use
     * @returns {Object} - { promise, abort }
     */
    uploadAudio: (file, title = '', onProgress = null, asrEngine = 'whisper') => {
        let xhr;
        const promise = new Promise((resolve, reject) => {
            const form = new FormData();
            form.append('file', file);
            form.append('title', title);
            form.append('asr_engine', asrEngine);

            xhr = new XMLHttpRequest();
            xhr.open('POST', `${API_BASE}/meetings/upload`);

            if (xhr.upload && onProgress) {
                xhr.upload.onprogress = (e) => {
                    if (e.lengthComputable) {
                        const percent = Math.round((e.loaded / e.total) * 100);
                        onProgress({
                            percent,
                            loaded: e.loaded,
                            total: e.total
                        });
                    }
                };
            }

            xhr.onload = () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        resolve(JSON.parse(xhr.responseText));
                    } catch (e) {
                        resolve(xhr.responseText);
                    }
                } else {
                    let errorMessage = `Upload failed: ${xhr.status}`;
                    try {
                        const response = JSON.parse(xhr.responseText);
                        errorMessage = response.detail || errorMessage;
                    } catch (e) {}
                    reject(new Error(errorMessage));
                }
            };

            xhr.onabort = () => reject(new Error('Upload cancelled by user'));
            xhr.onerror = () => reject(new Error('Network error or upload failed'));
            xhr.send(form);
        });

        return {
            promise,
            abort: () => xhr && xhr.abort()
        };
    },

    /**
     * Manually trigger transcript polishing.
     */
    manualPolish: async (id) => {
        const res = await fetch(`${API_BASE}/meetings/${id}/actions/polish`, { method: 'POST' });
        if (!res.ok) throw new Error(`Polish failed: ${res.status}`);
        return res.json();
    },

    /**
     * Manually trigger meeting minutes generation.
     */
    manualSummarize: async (id) => {
        const res = await fetch(`${API_BASE}/meetings/${id}/actions/summarize`, { method: 'POST' });
        if (!res.ok) throw new Error(`Summarize failed: ${res.status}`);
        return res.json();
    },

    /**
     * Manually trigger requirement extraction.
     */
    manualExtractRequirements: async (id) => {
        const res = await fetch(`${API_BASE}/meetings/${id}/actions/extract_requirements`, { method: 'POST' });
        if (!res.ok) throw new Error(`Extraction failed: ${res.status}`);
        return res.json();
    },

    /**
     * Resume a failed or interrupted meeting.
     */
    resumeMeeting: async (id) => {
        const res = await fetch(`${API_BASE}/meetings/${id}/resume`, { method: 'POST' });
        if (!res.ok) throw new Error(`Resume failed: ${res.status}`);
        return res.json();
    },

    /**
     * Fetch the project list from the external Knowledge Base.
     * Used by the "Sync to KB" project picker.
     * @returns {Promise<Array<{id, name, customer, industry, document_count}>>}
     */
    listKbProjects: async () => {
        const res = await fetch(`${API_BASE}/meetings/kb/projects`);
        if (!res.ok) {
            let detail = `KB projects failed: ${res.status}`;
            try {
                const d = await res.json();
                if (d.detail) detail = d.detail;
            } catch (e) {}
            throw new Error(detail);
        }
        return res.json();
    },

    /**
     * Sync this meeting's minutes (Markdown) to the Knowledge Base.
     * @param {string|number} id - Meeting ID
     * @param {{project_id?: string, doc_type?: string}} options
     */
    syncMeetingToKb: async (id, options = {}) => {
        const res = await fetch(`${API_BASE}/meetings/${id}/sync-kb`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_id: options.project_id || null,
                doc_type: options.doc_type || null,
            }),
        });
        if (!res.ok) {
            let detail = `KB sync failed: ${res.status}`;
            try {
                const d = await res.json();
                if (d.detail) detail = d.detail;
            } catch (e) {}
            throw new Error(detail);
        }
        return res.json();
    },

    /**
     * Associate (or clear) a KB project with a meeting. Optionally
     * triggers re-extraction of the stakeholder graph using the new
     * project's KB documents.
     * @param {string|number} id - Meeting ID
     * @param {{project_id?: string|null, project_name?: string|null, rerun_stakeholders?: boolean}} options
     */
    setMeetingProject: async (id, options = {}) => {
        const res = await fetch(`${API_BASE}/meetings/${id}/project`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_id: options.project_id || null,
                project_name: options.project_name || null,
                rerun_stakeholders: options.rerun_stakeholders !== false,
            }),
        });
        if (!res.ok) {
            let detail = `Set project failed: ${res.status}`;
            try { const d = await res.json(); if (d.detail) detail = d.detail; } catch (e) {}
            throw new Error(detail);
        }
        return res.json();
    },

    /**
     * Manually trigger stakeholder extraction for a meeting.
     * The backend runs it in a background task and updates the
     * meeting's stakeholder_map field on completion.
     */
    extractStakeholders: async (id) => {
        const res = await fetch(
            `${API_BASE}/meetings/${id}/actions/extract_stakeholders`,
            { method: 'POST' }
        );
        if (!res.ok) {
            let detail = `Extract stakeholders failed: ${res.status}`;
            try { const d = await res.json(); if (d.detail) detail = d.detail; } catch (e) {}
            throw new Error(detail);
        }
        return res.json();
    },

    /**
     * Save a manually edited stakeholder graph.
     * @param {string|number} id
     * @param {{ stakeholders: Array, relations: Array }} graph
     */
    updateStakeholderMap: async (id, graph) => {
        const res = await fetch(`${API_BASE}/meetings/${id}/stakeholder-map`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                stakeholders: graph.stakeholders || [],
                relations: graph.relations || [],
            }),
        });
        if (!res.ok) {
            let detail = `Save stakeholder map failed: ${res.status}`;
            try { const d = await res.json(); if (d.detail) detail = d.detail; } catch (e) {}
            throw new Error(detail);
        }
        return res.json();
    },

    /**
     * Push the stakeholder graph (as Markdown) to the KB.
     * Replaces any previously-uploaded stakeholder doc for this meeting.
     */
    syncStakeholderMapToKb: async (id, options = {}) => {
        const res = await fetch(
            `${API_BASE}/meetings/${id}/sync-stakeholder-map-kb`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_id: options.project_id || null,
                    doc_type: options.doc_type || null,
                }),
            }
        );
        if (!res.ok) {
            let detail = `Stakeholder KB sync failed: ${res.status}`;
            try { const d = await res.json(); if (d.detail) detail = d.detail; } catch (e) {}
            throw new Error(detail);
        }
        return res.json();
    },
};

window.api = api;
// Quick smoke-test marker — open DevTools console and look for this line
// to confirm the freshest api.js actually loaded (not a stale cache).
console.info('[api.js] loaded v1.9 — methods:', Object.keys(api).length);
