/* Audio capture utilities */

/**
 * Convert Float32 audio samples to Int16 PCM.
 * @param {Float32Array} float32Array - Raw audio from AudioContext
 * @returns {ArrayBuffer} - Int16 PCM buffer ready for WebSocket streaming
 */
function convertFloat32ToInt16(float32Array) {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Array[i]));
        int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16Array.buffer;
}

/**
 * Create an audio capture pipeline that streams PCM data via a callback.
 * @param {Object} options
 * @param {Function} options.onAudioData - Called with ArrayBuffer chunks
 * @param {number} [options.sampleRate=16000] - Target sample rate
 * @param {number} [options.bufferSize=4096] - ScriptProcessor buffer size
 * @returns {Promise<{ stop: Function, pause: Function, resume: Function }>}
 */
async function createAudioCapture({ onAudioData, sampleRate = 16000, bufferSize = 4096 }) {
    const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true
        }
    });

    const audioContext = new AudioContext({ sampleRate });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(bufferSize, 1, 1);

    let paused = false;

    processor.onaudioprocess = (e) => {
        if (paused) return;
        const audioData = e.inputBuffer.getChannelData(0);
        const pcmData = convertFloat32ToInt16(audioData);
        onAudioData(pcmData);
    };

    source.connect(processor);
    processor.connect(audioContext.destination);

    return {
        stop: () => {
            processor.disconnect();
            source.disconnect();
            stream.getTracks().forEach(t => t.stop());
            audioContext.close();
        },
        pause: () => { paused = true; },
        resume: () => { paused = false; }
    };
}
