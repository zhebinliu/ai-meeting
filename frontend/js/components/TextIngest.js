/* TextIngest component — paste or upload transcript text, then generate minutes */
var { Card, Input, Button, Space, Message, Typography, Upload } = arco;

function TextIngest({ onMeetingCreated }) {
    const [title, setTitle] = React.useState('');
    const [transcript, setTranscript] = React.useState('');
    const [fileName, setFileName] = React.useState('');
    const [submitting, setSubmitting] = React.useState(false);

    const charCount = transcript.length;
    const canSubmit = !!transcript.trim() && !submitting;

    const readTextFile = (file) => {
        if (!file) return;
        const sizeMB = file.size / (1024 * 1024);
        if (sizeMB > 10) {
            Message.error('文件过大，请控制在 10MB 以内');
            return;
        }
        const reader = new FileReader();
        reader.onload = (e) => {
            const text = String(e.target.result || '');
            setTranscript(text);
            setFileName(file.name);
            if (!title) {
                setTitle(file.name.replace(/\.[^.]+$/, ''));
            }
            Message.success(`已载入 ${file.name}（${text.length} 字）`);
        };
        reader.onerror = () => Message.error('读取文件失败，请重试');
        reader.readAsText(file, 'utf-8');
    };

    const handleSubmit = async () => {
        if (!transcript.trim()) {
            Message.warning('请先粘贴或上传会议转录文字');
            return;
        }
        setSubmitting(true);
        try {
            const meeting = await window.api.createMeetingFromText(
                title.trim() || '未命名会议',
                transcript
            );
            Message.success('已提交，AI 正在生成纪要');
            if (onMeetingCreated) onMeetingCreated(meeting.id);
        } catch (err) {
            Message.error(err.message || '提交失败，请稍后重试');
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Card
            title="文本生成纪要"
            bordered={false}
            style={{ maxWidth: 820, margin: '0 auto', boxShadow: '0 4px 16px rgba(0,0,0,0.08)' }}
        >
            <Typography.Paragraph type="secondary" style={{ marginBottom: 24 }}>
                上传 .txt / .md 文字转录文件，或直接粘贴会议笔记，AI 将自动润色并生成结构化会议纪要（概要、要点、决策、待办、需求）。
            </Typography.Paragraph>

            <Space direction="vertical" size="large" style={{ width: '100%' }}>
                <div>
                    <Typography.Text style={{ display: 'block', marginBottom: 8, fontWeight: 500 }}>
                        上传文字转录（可选）
                    </Typography.Text>
                    <Upload
                        drag
                        accept=".txt,.md,.markdown,text/plain"
                        limit={1}
                        autoUpload={false}
                        showUploadList={false}
                        onChange={(_, currentFile) => {
                            if (currentFile && currentFile.originFile) {
                                readTextFile(currentFile.originFile);
                            }
                        }}
                    >
                        <div style={{ padding: '24px 0', color: 'var(--color-text-2)' }}>
                            <div style={{ fontSize: 28, marginBottom: 8 }}>📄</div>
                            <div style={{ marginBottom: 4 }}>点击或拖拽 .txt / .md 文件到此处</div>
                            <div style={{ fontSize: 12, opacity: 0.6 }}>
                                {fileName ? `当前文件：${fileName}` : '上传后会自动填充下方文本框，仍可修改'}
                            </div>
                        </div>
                    </Upload>
                </div>

                <div>
                    <Typography.Text style={{ display: 'block', marginBottom: 8, fontWeight: 500 }}>
                        会议标题
                    </Typography.Text>
                    <Input
                        placeholder="输入会议标题以便后续查找"
                        value={title}
                        onChange={(val) => setTitle(val)}
                        disabled={submitting}
                    />
                </div>

                <div>
                    <Typography.Text style={{ display: 'block', marginBottom: 8, fontWeight: 500 }}>
                        会议文字内容
                    </Typography.Text>
                    <Input.TextArea
                        placeholder="在此粘贴完整的会议转录、语音转文字结果或会议笔记..."
                        value={transcript}
                        onChange={(val) => setTranscript(val)}
                        disabled={submitting}
                        autoSize={{ minRows: 12, maxRows: 24 }}
                        style={{ fontSize: 14, lineHeight: 1.6 }}
                    />
                    <div style={{ marginTop: 6, display: 'flex', justifyContent: 'space-between' }}>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            建议 200 字以上，效果更佳
                        </Typography.Text>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {charCount} 字
                        </Typography.Text>
                    </div>
                </div>

                <Button
                    type="primary"
                    long
                    size="large"
                    onClick={handleSubmit}
                    disabled={!canSubmit}
                    loading={submitting}
                    style={{ height: 48, borderRadius: 8 }}
                >
                    {submitting ? '提交中...' : '生成会议纪要'}
                </Button>
            </Space>
        </Card>
    );
}
