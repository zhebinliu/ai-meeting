var { Upload, Input, Button, Card, Spin, Space, Message, Typography, Progress, Radio } = arco;

function Uploader({ onMeetingCreated }) {
    const [file, setFile] = React.useState(null);
    const [title, setTitle] = React.useState('');
    const [engine, setEngine] = React.useState('whisper');
    const [uploadStatus, setUploadStatus] = React.useState('idle'); // idle, uploading, done, error
    const [percent, setPercent] = React.useState(0);
    const [stats, setStats] = React.useState({ loaded: 0, total: 0 });
    
    // Ref to store the active upload request for cancellation
    const activeUploadRef = React.useRef(null);

    const applyFile = (f) => {
        setFile(f);
        setTitle(prev => prev || f.name.replace(/\.[^.]+$/, ''));
    };

    const handleCancel = () => {
        if (activeUploadRef.current) {
            activeUploadRef.current.abort();
            activeUploadRef.current = null;
            setUploadStatus('idle');
            setPercent(0);
            Message.info('上传已取消');
        }
    };

    const handleSubmit = async () => {
        if (!file) {
            Message.warning('请先选择音频文件');
            return;
        }
        setUploadStatus('uploading');
        setPercent(0);
        setStats({ loaded: 0, total: file.size });

        try {
            const { promise, abort } = window.api.uploadAudio(file, title, (progress) => {
                setPercent(progress.percent);
                setStats({ loaded: progress.loaded, total: progress.total });
            }, engine);

            
            activeUploadRef.current = { abort };
            const meeting = await promise;
            
            setUploadStatus('done');
            Message.success('上传成功，已开始后台转写');
            if (onMeetingCreated) onMeetingCreated(meeting.id);
        } catch (err) {
            if (err.message === 'Upload cancelled by user') return;
            setUploadStatus('error');
            Message.error(err.message || '上传失败，请重试');
        } finally {
            activeUploadRef.current = null;
        }
    };

    const formatSize = (bytes) => {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    const isUploading = uploadStatus === 'uploading';

    return (
        <Card 
            title={isUploading ? "文件传输中" : "上传音频"} 
            bordered={false} 
            style={{ maxWidth: 600, margin: '0 auto', boxShadow: '0 4px 16px rgba(0,0,0,0.08)' }}
        >
            {isUploading ? (
                <div style={{ padding: '20px 0', textAlign: 'center' }}>
                    <Progress
                        type="circle"
                        percent={percent}
                        size="large"
                        status={percent >= 100 ? 'success' : 'normal'}
                        formatText={(val) => `${val}%`}
                        style={{ marginBottom: 24 }}
                    />
                    <Typography.Title heading={6}>正在极速上传音频文件...</Typography.Title>
                    <Typography.Paragraph type="secondary">
                        {percent < 100 
                            ? `已上传 ${formatSize(stats.loaded)} / ${formatSize(stats.total)}` 
                            : "上传完成，正在初始化后台工作流..."}
                    </Typography.Paragraph>
                    <div style={{ marginTop: 24, padding: '12px', background: 'var(--color-fill-2)', borderRadius: '4px', marginBottom: 24 }}>
                        <Typography.Text bold>{title}</Typography.Text>
                    </div>
                    {percent < 100 && (
                        <Button type="outline" status="danger" onClick={handleCancel}>
                            取消上传
                        </Button>
                    )}
                </div>
            ) : (
                <>
                    <Typography.Paragraph type="secondary" style={{ marginBottom: 24 }}>
                        支持 WAV、MP3、M4A、OGG、FLAC 等格式，大文件建议在稳定的 WiFi 下上传
                    </Typography.Paragraph>

                    <Space direction="vertical" size="large" style={{ width: '100%' }}>
                        <Upload
                            drag
                            accept=".wav,.mp3,.m4a,.ogg,.flac,.aac,.wma"
                            limit={1}
                            autoUpload={false}
                            onChange={(_, currentFile) => {
                                if (currentFile.originFile) {
                                    applyFile(currentFile.originFile);
                                }
                            }}
                            onRemove={() => { setFile(null); setTitle(''); }}
                        >
                            <div style={{ padding: '40px 0', color: 'var(--color-text-2)' }}>
                                <div style={{ fontSize: 32, marginBottom: 16 }}>☁️</div>
                                <div style={{ marginBottom: 8 }}>点击或拖拽音频文件到此处</div>
                                <div style={{ fontSize: 12, opacity: 0.6 }}>单个文件建议不超过 500MB</div>
                            </div>
                        </Upload>

                        <div>
                            <Typography.Text style={{ display: 'block', marginBottom: 8, fontWeight: 500 }}>会议标题</Typography.Text>
                            <Input
                                placeholder="输入会议标题以便后续查找"
                                value={title}
                                onChange={(val) => setTitle(val)}
                                disabled={isUploading}
                            />
                        </div>

                        <div>
                            <Typography.Text style={{ display: 'block', marginBottom: 8, fontWeight: 500 }}>转写引擎</Typography.Text>
                            <Radio.Group 
                                type="button" 
                                value={engine} 
                                onChange={(val) => setEngine(val)}
                                disabled={isUploading}
                                style={{ width: '100%' }}
                            >
                                <Radio value="whisper">本地 Faster-Whisper (隐私优先)</Radio>
                                <Radio value="xiaomi">小米大模型 (极速转写)</Radio>
                            </Radio.Group>
                        </div>

                        <Button 
                            type="primary" 
                            long 
                            size="large" 
                            onClick={handleSubmit} 
                            disabled={!file || isUploading}
                            include-icon="true"
                            style={{ height: 48, borderRadius: 8 }}
                        >
                            开始转写
                        </Button>
                    </Space>
                </>
            )}
        </Card>
    );
}
