/* API utilities for backend communication */

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
     * @returns {Promise<Object>} - Meeting object with id
     */
    createMeetingFromText: async (title, transcript) => {
        const res = await fetch(`${API_BASE}/meetings/from-text`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, transcript })
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
};
window.api = api;
