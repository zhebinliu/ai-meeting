var { Button, Tabs, Card, Space, Table, Spin, Message, Descriptions, Typography, Progress, Popconfirm, Tag, Tooltip } = arco;
// Robust icon recovery
const _icons = window.arcoIcon || window.ArcoIcon || {};
const { 
    IconFile = () => null, 
    IconApps = () => null, 
    IconLeft = () => null, 
    IconCheckCircle = () => null, 
    IconRefresh = () => null, 
    IconOrderedList = () => null, 
    IconBulb = () => null, 
    IconPlayArrow = () => null
} = _icons;
var TabPane = Tabs.TabPane;

function MeetingDetail({ meeting, onBack }) {
    const [activeTab, setActiveTab] = React.useState('transcription');
    const [loading, setLoading] = React.useState(false);
    const [meetingData, setMeetingData] = React.useState(meeting);
    const [displayedText, setDisplayedText] = React.useState(meeting?.raw_transcript || '');
    const scrollRef = React.useRef(null);
    const typingTimer = React.useRef(null);

    // Auto-scroll logic: only scroll if the user is near bottom or we just typed
    const scrollToBottom = (behavior = 'smooth') => {
        if (scrollRef.current) {
            const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
            const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
            if (isNearBottom) {
                scrollRef.current.scrollTo({ top: scrollHeight, behavior });
            }
        }
    };

    // Typewriter effect logic
    React.useEffect(() => {
        const targetText = meetingData?.raw_transcript || '';
        if (displayedText.length < targetText.length) {
            if (typingTimer.current) return;
            
            const startTyping = () => {
                const diff = targetText.length - displayedText.length;
                // Faster typing if we are lagging behind a lot
                const speed = diff > 100 ? 5 : diff > 20 ? 20 : 50;
                
                typingTimer.current = setTimeout(() => {
                    setDisplayedText(prev => {
                        const nextChar = targetText[prev.length];
                        if (nextChar !== undefined) {
                            return prev + nextChar;
                        }
                        return prev;
                    });
                    typingTimer.current = null;
                }, speed);
            };
            startTyping();
        }
        scrollToBottom();
    }, [meetingData?.raw_transcript, displayedText]);

    const fetchMeeting = React.useCallback(async () => {
        if (!meeting?.id) return;
        try {
            const data = await window.api.getMeeting(meeting.id);
            setMeetingData(data);
        } catch (err) {
            console.error('Failed to load meeting:', err);
        }
    }, [meeting?.id]);

    React.useEffect(() => {
        // Initial fetch
        fetchMeeting();
        
        let intervalId = null;
        const isProcessing = meetingData && (
            meetingData.status === 'transcribing' || 
            meetingData.status === 'processing' || 
            meetingData.status === 'polishing'
        );

        if (isProcessing) {
            intervalId = setInterval(fetchMeeting, 5000);
        } else if (meetingData && (meetingData.status === 'completed' || meetingData.status === 'failed')) {
            // If we just finished, do one more fetch to be 100% sure we have final data
            // (especially for minutes/polished transcript)
            const timer = setTimeout(fetchMeeting, 1000);
            return () => clearTimeout(timer);
        }

        return () => {
            if (intervalId) {
                clearInterval(intervalId);
            }
        };
    }, [meeting?.id, meetingData?.status, fetchMeeting]);


    const handleExportFeishu = async () => {
        try { 
            setLoading(true); 
            const r = await window.api.exportToFeishu(meetingData.id); 
            Message.success({
                content: '已导出到飞书文档',
                footer: r.url ? <Button type="text" size="small" onClick={() => window.open(r.url, '_blank')}>点击打开文档</Button> : null,
                duration: 10000
            }); 
        }
        catch (err) { Message.error('导出失败：' + err.message); }
        finally { setLoading(false); }
    };

    const handleSyncRequirements = async () => {
        try { 
            setLoading(true); 
            const r = await window.api.syncRequirements(meetingData.id); 
            Message.success('已同步到多维表格'); 
        }
        catch (err) { Message.error('同步失败：' + err.message); }
        finally { setLoading(false); }
    };

    const handleManualAction = async (action) => {
        try {
            setLoading(true);
            let res;
            if (action === 'polish') {
                res = await window.api.manualPolish(meetingData.id);
                Message.success('润色任务已重新启动');
            } else if (action === 'summarize') {
                res = await window.api.manualSummarize(meetingData.id);
                Message.success('纪要生成已重新启动');
            } else if (action === 'extract') {
                res = await window.api.manualExtractRequirements(meetingData.id);
                Message.success('任务已启动，请稍候...');
            }
            // Immediate fetch to update status to "polishing/processing"
            fetchMeeting();
        } catch (err) {
            Message.error('操作失败：' + err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleResume = async () => {
        try {
            setLoading(true);
            await window.api.resumeMeeting(meetingData.id);
            Message.success('任务已尝试恢复');
        } catch (err) {
            Message.error('恢复失败：' + err.message);
        } finally {
            setLoading(false);
        }
    };

    if (!meetingData) {
        return <div style={{ padding: 40, textAlign: 'center' }}><Spin tip="数据加载中..." /></div>;
    }

    const renderMinutes = () => {
        const m = meetingData?.minutes;
        if (!m) return (
            <div style={{ padding: '40px 0', textAlign: 'center' }}>
                <Spin tip={meetingData.status === 'processing' ? "AI 正在分析并生成纪要..." : "暂无纪要数据"} />
            </div>
        );
        return (
            <div className="minutes-content">
                {m.summary && (
                    <Card title="会议摘要" bordered={false} style={{ marginBottom: 16 }}>
                        <Typography.Paragraph>{m.summary}</Typography.Paragraph>
                    </Card>
                )}
                {m.key_points?.length > 0 && (
                    <Card title="讨论要点" bordered={false} style={{ marginBottom: 16 }}>
                        <ul>
                            {m.key_points.map((p, i) => (
                                <li key={i} style={{ marginBottom: 8 }}>
                                    {p.topic && <strong>{p.topic}：</strong>}
                                    {typeof p === 'string' ? p : p.content}
                                </li>
                            ))}
                        </ul>
                    </Card>
                )}
                {m.decisions?.length > 0 && (
                    <Card title="决策事项" bordered={false} style={{ marginBottom: 16 }}>
                        <ul>
                            {m.decisions.map((d, i) => (
                                <li key={i} style={{ marginBottom: 8 }}>
                                    {typeof d === 'string' ? d : d.content}
                                    {d.owner && <span style={{ color: 'var(--color-text-3)', marginLeft: 8 }}>(负责人: {d.owner})</span>}
                                </li>
                            ))}
                        </ul>
                    </Card>
                )}
                {m.action_items?.length > 0 && (
                    <Card title="待办事项" bordered={false} style={{ marginBottom: 16 }}>
                        <ul>
                            {m.action_items.map((item, i) => (
                                <li key={i} style={{ marginBottom: 8 }}>
                                    {item.owner && <strong>{item.owner}：</strong>}
                                    {item.task || item.content || (typeof item === 'string' ? item : '')}
                                    {item.deadline && <span style={{ color: 'var(--color-danger-light-4)', marginLeft: 8 }}>(截止: {item.deadline})</span>}
                                </li>
                            ))}
                        </ul>
                    </Card>
                )}
            </div>
        );
    };

    const renderTranscript = () => {
        const polished = meetingData?.polished_transcript;
        const raw = meetingData?.raw_transcript;
        return (
            <div className="transcript-root">
                {raw && (
                    <Card title="实时转写预览 (Raw)" bordered={false} style={{ marginBottom: 16 }}>
                        <div 
                            ref={scrollRef}
                            style={{ 
                                background: 'var(--color-fill-2)', 
                                padding: 16, 
                                borderRadius: 4, 
                                whiteSpace: 'pre-wrap', 
                                color: 'var(--color-text-2)', 
                                maxHeight: 400, 
                                overflowY: 'auto',
                                position: 'relative'
                            }}
                        >
                            {displayedText}
                            {meetingData.status === 'transcribing' && <span className="typewriter-cursor">|</span>}
                        </div>
                        {meetingData.status === 'transcribing' && (
                            <div style={{ marginTop: 16 }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                                    <Typography.Text type="secondary">
                                        <Spin size="small" style={{ marginRight: 8 }} />
                                        {meetingData.asr_engine === 'whisper' ? '本地 Faster-Whisper' : (meetingData.asr_engine === 'xunfei' ? '讯飞 ASR' : '系统默认转译')} 正在持续转写中...
                                    </Typography.Text>
                                    <Typography.Text type="secondary">
                                        进度: {meetingData.done_chunks || 0} / {meetingData.total_chunks || 0}
                                    </Typography.Text>
                                </div>
                                <Progress 
                                    percent={meetingData.total_chunks ? Math.floor((meetingData.done_chunks / meetingData.total_chunks) * 100) : 0} 
                                    status={meetingData.done_chunks >= meetingData.total_chunks ? 'success' : 'active'}
                                />
                            </div>
                        )}
                        {meetingData.status === 'polishing' && (
                             <Typography.Text type="success" style={{ marginTop: 8, display: 'block' }}>
                                <IconCheckCircle style={{ marginRight: 8 }} />
                                转写已完成，交给 AI 进行智能润色...
                            </Typography.Text>
                        )}
                    </Card>
                )}

                {polished ? (
                    <Card title="润色后转写" bordered={false} style={{ marginBottom: 16 }}>
                        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{polished}</Typography.Paragraph>
                    </Card>
                ) : (
                    (meetingData.status === 'polishing' || meetingData.status === 'processing') && (
                        <div style={{ padding: '40px 0', textAlign: 'center' }}>
                            <Spin tip="AI 正在分段润色并整理纪要中..." />
                        </div>
                    )
                )}
                
                {!raw && (meetingData.status === 'transcribing' || meetingData.status === 'processing') && (
                    <div style={{ padding: '40px 0', textAlign: 'center' }}>
                        <Spin tip="正在建立语音流或等待首片转写..." />
                    </div>
                )}
            </div>
        );
    };

    const renderRequirements = () => {
        const reqs = meetingData?.requirements || [];
        if (meetingData.status === 'polishing' && !reqs.length) {
            return (
                <div style={{ padding: '40px 0', textAlign: 'center' }}>
                    <Spin tip="正在从全文中提取需求模块..." />
                </div>
            );
        }
        if (!reqs.length) return <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--color-text-3)' }}>暂无需求清单</div>;
        
        // Define LTO Order
        const LTO_ORDER = ['线索', '客户', '商机', '报价', '合同', '订单', '回款', '回访', '其他'];
        
        // Group by module
        const groups = {};
        reqs.forEach(r => {
            const m = r.module || '其他';
            if (!groups[m]) groups[m] = [];
            groups[m].push(r);
        });

        // Sort modules by LTO
        const sortedModules = Object.keys(groups).sort((a, b) => {
            let idxA = LTO_ORDER.indexOf(a);
            let idxB = LTO_ORDER.indexOf(b);
            if (idxA === -1) idxA = 99;
            if (idxB === -1) idxB = 99;
            return idxA - idxB;
        });

        const columns = [
            { title: 'ID', dataIndex: 'req_id', width: 100 },
            { title: '需求描述', dataIndex: 'description' },
            { title: '优先级', dataIndex: 'priority', width: 100, render: (p) => <Tag color={p === 'P0' ? 'red' : p === 'P1' ? 'orange' : 'blue'}>{p}</Tag> },
            { title: '提出人', dataIndex: 'speaker', width: 120 },
            { title: '状态', dataIndex: 'status', width: 100 }
        ];

        return (
            <div className="requirements-view">
                {sortedModules.map(module => (
                    <Card 
                        key={module} 
                        title={<Space><IconOrderedList /><span>{module} 模块</span></Space>}
                        style={{ marginBottom: 20 }}
                        className="module-card"
                    >
                        <Table 
                            columns={columns} 
                            data={groups[module]} 
                            pagination={false} 
                            rowKey="id"
                        />
                    </Card>
                ))}
            </div>
        );
    };

    return (
        <div className="meeting-detail">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, paddingBottom: 16, borderBottom: '1px solid var(--color-border-1)' }}>
                <Space>
                    <Button 
                        onClick={onBack} 
                        type="outline" 
                        icon={<IconLeft />}
                        style={{ borderRadius: '20px', padding: '0 20px' }}
                    >
                        返回
                    </Button>
                    <Typography.Title heading={3} style={{ margin: 0, marginLeft: 12 }}>
                        {meetingData?.title || '未命名会议'}
                    </Typography.Title>
                    {meetingData?.feishu_url && (
                        <Button 
                            type="text" 
                            size="small" 
                            icon={<IconFile />}
                            onClick={() => window.open(meetingData.feishu_url, '_blank')}
                            style={{ color: '#3370ff', marginLeft: '8px' }}
                        >
                            飞书文档
                        </Button>
                    )}
                    {meetingData?.bitable_url && (
                        <Button 
                            type="text" 
                            size="small" 
                            icon={<IconApps />}
                            onClick={() => window.open(meetingData.bitable_url, '_blank')}
                            style={{ color: '#00b42a', marginLeft: '8px' }}
                        >
                            多维表格
                        </Button>
                    )}
                </Space>
                <Space size="medium">
                    {/* ASR Engine Indicator - Top Right */}
                    <Tag 
                        color={(!meetingData.asr_engine || meetingData.asr_engine === 'whisper') ? 'arcoblue' : 'orange'} 
                        bordered 
                        style={{ borderRadius: '4px', fontWeight: 'bold' }}
                    >
                        ASR: {(!meetingData.asr_engine || meetingData.asr_engine === 'whisper') ? '本地 Faster-Whisper (INT8)' : (meetingData.asr_engine === 'xunfei' ? '讯飞 ASR' : '系统默认')}
                    </Tag>

                    <Button type="primary" status="success" onClick={handleSyncRequirements} loading={loading} disabled={meetingData.status !== 'completed'}>同步需求</Button>
                    <Button type="primary" onClick={handleExportFeishu} loading={loading} disabled={meetingData.status !== 'completed'}>导出到飞书</Button>
                    
                    <div style={{ height: '20px', width: '1px', background: 'var(--color-border-2)', margin: '0 8px' }} />

                    {meetingData.status !== 'completed' && (
                        <Popconfirm title="确定要从断点处恢复任务吗？" onOk={handleResume}>
                            <Tooltip content="恢复中断的转写任务">
                                <Button type="outline" status="warning" icon={<IconPlayArrow />} loading={loading} />
                            </Tooltip>
                        </Popconfirm>
                    )}
                    
                    <Popconfirm title="确定要重新运行 AI 润色吗？" onOk={() => handleManualAction('polish')}>
                        <Tooltip content="手动触发 AI 智能润色">
                            <Button type="outline" icon={<IconBulb />} disabled={!meetingData.raw_transcript} />
                        </Tooltip>
                    </Popconfirm>
                    <Popconfirm title="确定要重新提取需求吗？" onOk={() => handleManualAction('extract')}>
                        <Tooltip content="手动重新提取业务需求">
                            <Button type="outline" icon={<IconRefresh />} disabled={!meetingData.raw_transcript} />
                        </Tooltip>
                    </Popconfirm>
                </Space>
            </div>
            
            <Descriptions layout="inline" style={{ marginBottom: 24 }}>
                <Descriptions.Item label="日期">{meetingData?.start_time ? new Date(meetingData.start_time).toLocaleDateString() : '-'}</Descriptions.Item>
                <Descriptions.Item label="状态">
                    {meetingData.status === 'completed' ? <Typography.Text type="success">已完成</Typography.Text> : 
                     meetingData.status === 'processing' ? <Typography.Text type="warning">正在处理</Typography.Text> : 
                     <Typography.Text type="danger">失败</Typography.Text>}
                </Descriptions.Item>
            </Descriptions>

            <Tabs activeTab={activeTab} onChange={setActiveTab} size="large" type="card">
                <TabPane key="minutes" title="会议纪要">
                    {renderMinutes()}
                </TabPane>
                <TabPane key="transcript" title="完整转写">
                    {renderTranscript()}
                </TabPane>
                <TabPane key="requirements" title="需求清单">
                    {renderRequirements()}
                </TabPane>
            </Tabs>
        </div>
    );
}
