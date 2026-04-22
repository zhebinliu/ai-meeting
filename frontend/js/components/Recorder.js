/* Recorder component */
var { Card, Button, Space, Input, Typography, Alert, Message } = arco;
var { Title, Text, Paragraph } = Typography;

function Recorder({ onMeetingCreated }) {
    const [isRecording, setIsRecording] = React.useState(false);
    const [isPaused, setIsPaused] = React.useState(false);
    const [transcript, setTranscript] = React.useState([]);
    const [meetingTitle, setMeetingTitle] = React.useState('');
    const [error, setError] = React.useState('');
    const [meetingId, setMeetingId] = React.useState(null);
    const [duration, setDuration] = React.useState(0);

    const wsRef = React.useRef(null);
    const audioCaptureRef = React.useRef(null);
    const transcriptEndRef = React.useRef(null);
    const timerRef = React.useRef(null);

    React.useEffect(() => {
        if (transcriptEndRef.current) transcriptEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }, [transcript]);

    React.useEffect(() => {
        if (isRecording && !isPaused) {
            timerRef.current = setInterval(() => setDuration(d => d + 1), 1000);
        } else {
            clearInterval(timerRef.current);
        }
        return () => clearInterval(timerRef.current);
    }, [isRecording, isPaused]);

    const fmt = (s) => {
        const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        return h > 0
            ? h + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0')
            : String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
    };

    const startRecording = async () => {
        setError(''); setTranscript([]); setDuration(0);
        try {
            const meeting = await window.api.createMeeting(meetingTitle || '未命名会议');
            setMeetingId(meeting.id);
            const ws = new WebSocket(`${window.WS_BASE}/ws/recording/${meeting.id}?token=${encodeURIComponent(window.WS_TOKEN)}`);
            wsRef.current = ws;
            ws.onmessage = (ev) => {
                try {
                    const data = JSON.parse(ev.data);
                    if (data.type === 'transcript') {
                        setTranscript(prev => {
                            if (!data.is_final && prev.length > 0 && !prev[prev.length - 1].isFinal) {
                                const u = [...prev];
                                u[u.length - 1] = { text: data.text, speaker: data.speaker || null, isFinal: false };
                                return u;
                            }
                            return [...prev, { text: data.text, speaker: data.speaker || null, isFinal: data.is_final }];
                        });
                    }
                } catch (ex) { console.error('[WS] parse error', ex); }
            };
            ws.onerror = () => setError('WebSocket 连接错误');
            audioCaptureRef.current = await createAudioCapture({
                onAudioData: (pcm) => { if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(pcm); }
            });
            setIsRecording(true);
        } catch (err) {
            setError(err.message || '无法启动录音，请检查麦克风权限');
        }
    };

    const pauseRecording = () => { audioCaptureRef.current?.pause(); setIsPaused(true); };
    const resumeRecording = () => { audioCaptureRef.current?.resume(); setIsPaused(false); };

    const stopRecording = async () => {
        audioCaptureRef.current?.stop(); audioCaptureRef.current = null;
        wsRef.current?.close(); wsRef.current = null;
        setIsRecording(false); setIsPaused(false);
        if (meetingId) {
            try { 
                await window.api.processMeeting(meetingId); 
                Message.success('后处理成功');
            } catch (err) { 
                Message.error('后处理失败，请稍后手动处理'); 
            }
            if (onMeetingCreated) onMeetingCreated(meetingId);
        }
    };

    return (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Card title="实时录音" bordered={false}
                extra={
                    isRecording && (
                        <Space>
                            <span className="pulse-dot" style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: isPaused ? 'orange' : 'red' }}></span>
                            <Text>{(isPaused ? '已暂停' : '录音中') + ' · ' + fmt(duration)}</Text>
                        </Space>
                    )
                }
            >
                <Space direction="vertical" size="large" style={{ width: '100%' }}>
                    {error && <Alert type="error" content={error} />}

                    <div>
                        <Text style={{ display: 'block', marginBottom: 8 }}>会议标题</Text>
                        <Input 
                            value={meetingTitle}
                            onChange={setMeetingTitle}
                            placeholder="会议标题（可选）"
                            disabled={isRecording}
                            style={{ maxWidth: 400 }}
                        />
                    </div>

                    <Space>
                        {!isRecording && (
                            <Button type="primary" status="danger" onClick={startRecording} size="large">
                                开始录音
                            </Button>
                        )}
                        {isRecording && !isPaused && (
                            <Button type="outline" status="warning" onClick={pauseRecording} size="large">
                                暂停
                            </Button>
                        )}
                        {isRecording && isPaused && (
                            <Button type="outline" status="success" onClick={resumeRecording} size="large">
                                继续
                            </Button>
                        )}
                        {isRecording && (
                            <Button type="primary" status="danger" onClick={stopRecording} size="large">
                                结束录音
                            </Button>
                        )}
                    </Space>
                </Space>
            </Card>

            <Card title="实时转写" bordered={false}>
                <div style={{ 
                    background: 'var(--color-bg-2)', 
                    border: '1px solid var(--color-border)',
                    borderRadius: 4,
                    padding: 16,
                    height: 400,
                    overflowY: 'auto'
                }}>
                    {transcript.length === 0 && !isRecording && (
                        <div style={{ textAlign: 'center', marginTop: 100, color: 'var(--color-text-3)' }}>
                            点击「开始录音」后，转写内容将实时显示在这里
                        </div>
                    )}
                    {transcript.length === 0 && isRecording && (
                        <div style={{ textAlign: 'center', marginTop: 100, color: 'var(--color-text-3)' }}>
                            正在聆听，请开始说话...
                        </div>
                    )}
                    {transcript.map((item, i) => (
                        <Paragraph key={i} style={{ 
                            marginBottom: 12, 
                            color: item.isFinal ? 'var(--color-text-1)' : 'var(--color-text-3)',
                            lineHeight: 1.6
                        }}>
                            {item.speaker && <Text bold style={{ color: 'var(--color-primary-light-4)', marginRight: 8 }}>{item.speaker}:</Text>}
                            {item.text}
                        </Paragraph>
                    ))}
                    <div ref={transcriptEndRef} />
                </div>
            </Card>
        </Space>
    );
}
