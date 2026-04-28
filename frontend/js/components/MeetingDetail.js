var { Button, Tabs, Card, Space, Table, Spin, Message, Descriptions, Typography, Progress, Popconfirm, Tag, Tooltip, Dropdown, Menu, Alert, Radio, Modal, Select, Empty, Link } = arco;
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
    IconPlayArrow = () => null,
    IconMore = () => null,
    IconDownload = () => null,
    IconEdit = () => null,
    IconDown = () => <span style={{ fontSize: 10, lineHeight: 1 }} aria-hidden>▾</span>,
} = _icons;
var TabPane = Tabs.TabPane;

const SvgCalendar = () => React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none' },
    React.createElement('rect', { x: 1, y: 3, width: 14, height: 11, rx: 2, stroke: 'currentColor', strokeWidth: 1.5 }),
    React.createElement('path', { d: 'M5 1V4M11 1V4', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' }),
    React.createElement('path', { d: 'M1 7H15', stroke: 'currentColor', strokeWidth: 1.5 })
);
const SvgClock = () => React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none' },
    React.createElement('circle', { cx: 8, cy: 8, r: 6.5, stroke: 'currentColor', strokeWidth: 1.5 }),
    React.createElement('path', { d: 'M8 5V8.5L10.5 10', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round' })
);
const SvgDoc = () => React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none' },
    React.createElement('rect', { x: 2, y: 1.5, width: 12, height: 13, rx: 1.5, stroke: 'currentColor', strokeWidth: 1.5 }),
    React.createElement('path', { d: 'M5 5.5H11M5 8H11M5 10.5H9', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' })
);
const SvgTask = () => React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none' },
    React.createElement('rect', { x: 1.5, y: 1.5, width: 13, height: 13, rx: 2, stroke: 'currentColor', strokeWidth: 1.5 }),
    React.createElement('path', { d: 'M5 8L7 10L11 6', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round' })
);
const SvgMic = () => React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none' },
    React.createElement('rect', { x: 5.5, y: 1.5, width: 5, height: 7, rx: 2.5, stroke: 'currentColor', strokeWidth: 1.5 }),
    React.createElement('path', { d: 'M2.5 8C2.5 10.761 4.961 13 8 13C11.039 13 13.5 10.761 13.5 8', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' }),
    React.createElement('path', { d: 'M8 13V15', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' })
);
const SvgFolder = () => React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none' },
    React.createElement('path', { d: 'M1.5 4C1.5 3.172 2.172 2.5 3 2.5H6.5L8 4.5H13C13.828 4.5 14.5 5.172 14.5 6V12C14.5 12.828 13.828 13.5 13 13.5H3C2.172 13.5 1.5 12.828 1.5 12V4Z', stroke: 'currentColor', strokeWidth: 1.5, strokeLinejoin: 'round' })
);

const VALID_TABS = new Set(['minutes', 'transcript', 'requirements', 'stakeholders']);

function pickDefaultTab(status, preferred) {
    if (preferred && VALID_TABS.has(preferred)) return preferred;
    if (status === 'recording' || status === 'transcribing') return 'transcript';
    return 'minutes';
}

function MeetingDetail({ meeting, onBack, initialTab, onTabChange }) {
    const [activeTab, setActiveTab] = React.useState(() =>
        pickDefaultTab(meeting?.status, initialTab)
    );
    const [loading, setLoading] = React.useState(false);
    const [meetingData, setMeetingData] = React.useState(meeting);
    const [displayedText, setDisplayedText] = React.useState(meeting?.raw_transcript || '');
    const [viewMode, setViewMode] = React.useState('read'); // 'read' | 'edit'
    const scrollRef = React.useRef(null);
    const typingTimer = React.useRef(null);
    const templateRef = React.useRef(null);
    const [exporting, setExporting] = React.useState(false);

    // ----------------------------------------------------------------------
    // KB sync state — modal-driven flow:
    //   1. user clicks "同步到 KB" → open modal & fetch project list lazily
    //   2. user picks a project (or skips) → POST /sync-kb
    //   3. on success: persist returned doc id/url, show "已同步" badge
    // ----------------------------------------------------------------------
    const [kbModalOpen, setKbModalOpen] = React.useState(false);
    const [kbProjects, setKbProjects] = React.useState(null); // null = not loaded yet
    const [kbProjectsLoading, setKbProjectsLoading] = React.useState(false);
    const [kbProjectsError, setKbProjectsError] = React.useState(null);
    const [kbSelectedProject, setKbSelectedProject] = React.useState(() => {
        // Remember the last picked project across sessions for convenience.
        try { return localStorage.getItem('kb:lastProjectId') || ''; } catch (e) { return ''; }
    });
    const [kbSyncing, setKbSyncing] = React.useState(false);

    // ----------------------------------------------------------------------
    // Project association modal — used both by "干系人图谱" tab (to pick the
    // KB project for stakeholder enrichment) and from the legacy KB-sync
    // modal (which now also persists the choice as the meeting's project).
    // We keep the modal logic centralised here so both call sites stay in
    // sync. ``projectModalReason`` lets the modal show context-appropriate
    // copy ("attach project for stakeholders" vs "pick a project to sync").
    // ----------------------------------------------------------------------
    const [projectModalOpen, setProjectModalOpen] = React.useState(false);
    const [projectModalReason, setProjectModalReason] = React.useState('stakeholders');
    const [projectChoice, setProjectChoice] = React.useState(
        meeting?.kb_project_id || ''
    );
    const [projectSubmitting, setProjectSubmitting] = React.useState(false);

    // ------------------------------------------------------------------
    // In-place edits made inside the editable template are committed to
    // this local override whenever the user switches back to read mode
    // (or clicks export). Read view + exports always prefer this copy
    // over the server-side minutes, so nothing the user typed gets lost.
    // ------------------------------------------------------------------
    const [editedMinutes, setEditedMinutes] = React.useState(null);

    /** Read the current live DOM and return a minutes-shaped object. */
    const snapshotFromDom = () => {
        if (!templateRef.current || !window.minutesExport) return null;
        const data = window.minutesExport.collect(templateRef.current);
        if (!data) return null;
        return {
            title: data.title,
            summary: data.summary,
            key_points: data.keyPoints,
            decisions: data.decisions,
            action_items: data.actionItems,
        };
    };

    /** Persist live DOM edits into state + propagate title to header. */
    const commitEdits = () => {
        const snap = snapshotFromDom();
        if (!snap) return;
        setEditedMinutes(snap);
        if (snap.title && snap.title !== meetingData.title) {
            // Reflect edited title in the detail page header/metrics.
            setMeetingData((prev) => ({ ...prev, title: snap.title }));
        }
    };

    const handleViewModeChange = (next) => {
        if (viewMode === 'edit' && next === 'read') commitEdits();
        setViewMode(next);
    };

    const handleTabChange = (key) => {
        // Switching away from the minutes tab while in edit mode also
        // means those pending DOM edits should be captured first.
        if (viewMode === 'edit') commitEdits();
        setActiveTab(key);
        if (onTabChange) onTabChange(key);
    };

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

    // A ref lets fetchMeeting see the latest editedMinutes without being
    // re-created on every edit (which would otherwise thrash the polling
    // useEffect below).
    const editedRef = React.useRef(null);
    React.useEffect(() => { editedRef.current = editedMinutes; }, [editedMinutes]);

    const fetchMeeting = React.useCallback(async () => {
        if (!meeting?.id) return;
        try {
            const data = await window.api.getMeeting(meeting.id);
            const edited = editedRef.current;
            // Preserve the locally edited title across polling refreshes,
            // otherwise every 5s poll would clobber what the user typed.
            if (edited && edited.title) {
                setMeetingData({ ...data, title: edited.title });
            } else {
                setMeetingData(data);
            }
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
                // User explicitly asked for a fresh summary — drop local edits
                // so the newly generated minutes become visible again.
                setEditedMinutes(null);
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

    /** The effective minutes object used by the read view and exports:
     *  local edits take priority over the server copy so switching back
     *  to read view (or exporting) always reflects what the user typed. */
    const getEffectiveMinutes = () => editedMinutes || meetingData?.minutes || null;

    const renderMinutesTab = () => (
        <div className="minutes-tab">
            <div className="minutes-tab-toolbar">
                <div className="minutes-tab-toolbar-hint">
                    <Typography.Text style={{ fontSize: 13, color: 'var(--ds-text-3)' }}>
                        {viewMode === 'edit'
                            ? '✏️ 编辑：直接改文字，切回「只读」会保存到本页'
                            : editedMinutes
                                ? '只读（含你在本机编辑后的版本）'
                                : '只读'}
                    </Typography.Text>
                    {meetingData.status === 'completed' && (
                        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                            导出多种格式、同步到实施知识库：请使用<strong>页面上方工具栏</strong>。
                        </Typography.Text>
                    )}
                </div>
                <Radio.Group type="button" size="small" value={viewMode} onChange={handleViewModeChange}>
                    <Radio value="read">只读</Radio>
                    <Radio value="edit">编辑</Radio>
                </Radio.Group>
            </div>
            {viewMode === 'edit' ? renderEditableMinutes() : renderMinutes()}
        </div>
    );

    const renderMinutes = () => {
        const m = getEffectiveMinutes();
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

    // --- Exportable / editable minutes ------------------------------------
    const exportHelpers = window.minutesExport || null;
    // Use the effective minutes object (local edits win) so the editable
    // template re-renders with the user's saved edits when they toggle
    // back into edit mode, instead of snapping back to the server copy.
    const minutesObj = getEffectiveMinutes() || {};
    const keyPointsArr = Array.isArray(minutesObj.key_points) ? minutesObj.key_points : [];
    const decisionsArr = Array.isArray(minutesObj.decisions) ? minutesObj.decisions : [];
    const actionsArr = Array.isArray(minutesObj.action_items) ? minutesObj.action_items : [];

    const plainFromKeyPoint = (p) => {
        if (typeof p === 'string') return p;
        if (!p) return '';
        return [p.topic ? `${p.topic}：` : '', p.content || ''].join('');
    };
    const plainFromDecision = (d) => {
        if (typeof d === 'string') return d;
        if (!d) return '';
        const owner = d.owner ? `（负责人：${d.owner}）` : '';
        return `${d.content || ''}${owner}`;
    };
    const plainFromAction = (a) => {
        if (typeof a === 'string') return a;
        if (!a) return '';
        const who = a.owner ? `${a.owner}：` : '';
        const task = a.task || a.content || '';
        const due = a.deadline ? `（截止：${a.deadline}）` : '';
        return `${who}${task}${due}`;
    };

    const baseFileName = () => {
        const stamp = exportHelpers ? exportHelpers.todayStamp() : '';
        const title = (meetingData?.title || '会议纪要').replace(/[\\/:*?"<>|]/g, '_');
        return `${title}_${stamp}`;
    };

    /** Build a DS-exporter-compatible data object from any source:
     *  - edit mode: read live DOM (captures not-yet-committed typing);
     *  - read mode: use the effective minutes (local edits win over server). */
    const readExportData = () => {
        if (!exportHelpers) return null;
        if (viewMode === 'edit' && templateRef.current) {
            return exportHelpers.collect(templateRef.current);
        }
        const eff = getEffectiveMinutes() || {};
        return {
            title: meetingData?.title || '会议纪要',
            date: meetingData?.start_time
                ? new Date(meetingData.start_time).toLocaleDateString('zh-CN')
                : '',
            status:
                meetingData.status === 'completed' ? '已完成' :
                meetingData.status === 'failed' ? '失败' : '处理中',
            summary: eff.summary || '',
            keyPoints: (Array.isArray(eff.key_points) ? eff.key_points : []).map(plainFromKeyPoint).filter(Boolean),
            decisions: (Array.isArray(eff.decisions) ? eff.decisions : []).map(plainFromDecision).filter(Boolean),
            actionItems: (Array.isArray(eff.action_items) ? eff.action_items : []).map(plainFromAction).filter(Boolean),
        };
    };

    const doExportMarkdown = () => {
        const data = readExportData();
        if (!data) return;
        exportHelpers.downloadBlob(
            exportHelpers.buildMarkdown(data),
            `${baseFileName()}.md`,
            'text/markdown;charset=utf-8'
        );
        Message.success('已导出 Markdown 文件');
    };

    const doExportPlainText = () => {
        const data = readExportData();
        if (!data) return;
        exportHelpers.downloadBlob(
            exportHelpers.buildPlainText(data),
            `${baseFileName()}.txt`,
            'text/plain;charset=utf-8'
        );
        Message.success('已导出纯文本文件');
    };

    const doExportHtml = async () => {
        const data = readExportData();
        if (!data) return;
        // HTML export needs a live DOM root to clone styled markup from.
        // If we're in read mode, flip to edit briefly so the template
        // mounts, export, then restore the user's original mode.
        const wasRead = viewMode === 'read';
        if (wasRead) {
            setViewMode('edit');
            // Wait for template to render.
            await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        }
        if (!templateRef.current) {
            if (wasRead) setViewMode('read');
            Message.warning('模板未就绪，请切换到编辑模式后重试');
            return;
        }
        exportHelpers.downloadBlob(
            exportHelpers.buildStandaloneHtml(templateRef.current, data),
            `${baseFileName()}.html`,
            'text/html;charset=utf-8'
        );
        Message.success('已导出 HTML 文件');
        if (wasRead) setViewMode('read');
    };

    const doExportPng = async () => {
        if (!exportHelpers) return;
        setExporting(true);
        // PNG has to rasterise a real DOM node, so force edit mode first.
        const wasRead = viewMode === 'read';
        if (wasRead) {
            setViewMode('edit');
            await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        }
        try {
            if (!templateRef.current) throw new Error('模板未就绪');
            await exportHelpers.exportPng(templateRef.current, `${baseFileName()}.png`);
            Message.success('已导出 PNG 图片');
        } catch (err) {
            Message.error('导出图片失败：' + (err.message || err));
        } finally {
            setExporting(false);
            if (wasRead) setViewMode('read');
        }
    };

    // ----- KB sync handlers ------------------------------------------------

    const ensureKbProjects = async () => {
        if (kbProjects !== null || kbProjectsLoading) return;
        setKbProjectsLoading(true);
        setKbProjectsError(null);
        try {
            const list = await window.api.listKbProjects();
            setKbProjects(list || []);
        } catch (err) {
            setKbProjectsError(err.message || String(err));
            setKbProjects([]);
        } finally {
            setKbProjectsLoading(false);
        }
    };

    const openKbModal = async () => {
        if (viewMode === 'edit') commitEdits();
        setKbModalOpen(true);
        ensureKbProjects();
    };

    const openProjectModal = async (reason = 'stakeholders') => {
        setProjectModalReason(reason);
        setProjectChoice(meetingData?.kb_project_id || '');
        setProjectModalOpen(true);
        ensureKbProjects();
    };

    const refreshMeetingData = async () => {
        try {
            const fresh = await window.api.getMeeting(meetingData.id);
            setMeetingData(fresh);
        } catch (err) {
            console.warn('refresh meeting failed', err);
        }
    };

    const submitProjectChoice = async () => {
        setProjectSubmitting(true);
        try {
            const chosen = projectChoice || null;
            const projectName = (kbProjects || []).find((p) => p.id === chosen)?.name || null;
            const res = await window.api.setMeetingProject(meetingData.id, {
                project_id: chosen,
                project_name: projectName,
                rerun_stakeholders: true,
            });
            setMeetingData((prev) => ({
                ...prev,
                kb_project_id: res.kb_project_id,
                kb_project_name: res.kb_project_name,
            }));
            if (chosen) {
                if (res.stakeholder_extraction === 'scheduled') {
                    Message.success('已关联项目，AI 正在重新抽取干系人，约 30-60 秒后自动刷新');
                    setTimeout(refreshMeetingData, 12000);
                    setTimeout(refreshMeetingData, 35000);
                } else {
                    Message.success('已关联项目');
                }
            } else {
                Message.success('已清除项目关联');
            }
            setProjectModalOpen(false);
        } catch (err) {
            Message.error('保存失败：' + (err.message || err));
        } finally {
            setProjectSubmitting(false);
        }
    };

    const doSyncToKb = async () => {
        setKbSyncing(true);
        try {
            const res = await window.api.syncMeetingToKb(meetingData.id, {
                project_id: kbSelectedProject || null,
            });
            // Persist the user's last choice for next time.
            try {
                if (kbSelectedProject) localStorage.setItem('kb:lastProjectId', kbSelectedProject);
            } catch (e) {}
            // Optimistically update local state without a full refetch.
            setMeetingData((prev) => ({
                ...prev,
                kb_doc_id: res.kb_doc_id,
                kb_url: res.kb_url,
                kb_synced_at: res.kb_synced_at || new Date().toISOString(),
            }));
            Message.success({
                content: res.replaced_old_doc
                    ? '已重新同步到实施知识库（旧版本已替换）'
                    : '已同步到实施知识库',
                footer: res.kb_url ? (
                    <Button size="mini" type="text" onClick={() => window.open(res.kb_url, '_blank')}>
                        打开文档
                    </Button>
                ) : null,
            });
            setKbModalOpen(false);
        } catch (err) {
            Message.error('同步失败：' + (err.message || err));
        } finally {
            setKbSyncing(false);
        }
    };

    const renderEditableMinutes = () => {
        const dateStr = meetingData?.start_time
            ? new Date(meetingData.start_time).toLocaleDateString('zh-CN')
            : '';

        const statusStr =
            meetingData.status === 'completed' ? '已完成' :
            meetingData.status === 'failed' ? '失败' : '处理中';

        return (
            <div className="exportable-minutes-wrapper">
                <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                    下方模板内的文字可直接点击编辑；使用顶部「导出」按钮按最新内容导出文件。
                </Typography.Text>

                {/* Styles for the exportable template. Kept inline so the
                    cloned DOM used in the standalone HTML export still works. */}
                <style>{`
                    .minutes-template { background:#fff; border-radius:20px; box-shadow:0 10px 30px -15px rgba(0,0,0,0.15); overflow:hidden; max-width:960px; margin:0 auto; color:#1f2d3d; font-family: 'PingFang SC','Microsoft YaHei',-apple-system,BlinkMacSystemFont,sans-serif; }
                    .minutes-template .mt-header { padding:28px 36px; background: linear-gradient(135deg,#0b2b3f 0%,#123d55 100%); color:#fff; }
                    .minutes-template .mt-title { font-size:24px; font-weight:700; margin-bottom:16px; border-left:4px solid #ffc107; padding-left:14px; outline:none; }
                    .minutes-template .mt-meta { display:flex; flex-wrap:wrap; gap:10px 20px; font-size:13px; }
                    .minutes-template .mt-meta-item { background:rgba(255,255,255,0.14); padding:5px 12px; border-radius:999px; }
                    .minutes-template .mt-body { padding:24px 36px 30px; }
                    .minutes-template .mt-section { margin-bottom:26px; padding-bottom:20px; border-bottom:1px solid #e4e9f0; }
                    .minutes-template .mt-section:last-child { border-bottom:none; margin-bottom:0; padding-bottom:0; }
                    .minutes-template .mt-section-title { font-size:17px; font-weight:700; margin-bottom:12px; padding-left:10px; border-left:4px solid #2c7da0; }
                    .minutes-template .mt-summary { background:#f8fbfe; padding:14px 18px; border-radius:12px; font-size:14.5px; line-height:1.7; border:1px solid #e2edf7; outline:none; }
                    .minutes-template .mt-list { list-style:none; padding:0; margin:0; }
                    .minutes-template .mt-list li { background:#fafcff; border:1px solid #e9f0f5; border-radius:10px; padding:10px 14px; margin-bottom:8px; font-size:14px; line-height:1.6; outline:none; }
                    .minutes-template .mt-list li:last-child { margin-bottom:0; }
                    .minutes-template .mt-empty { color:#9ca3af; font-size:13px; }
                    .minutes-template [contenteditable="true"]:hover { background:#f0f9ff; transition: background 0.15s; }
                    .minutes-template [contenteditable="true"]:focus { background:#e0f2fe; box-shadow: inset 0 0 0 1px #2c7da0; }
                `}</style>

                <div
                    ref={templateRef}
                    className="minutes-template"
                    key={`mt-${meetingData?.id || 0}-${meetingData?.status || ''}`}
                >
                    <div className="mt-header">
                        <div
                            className="mt-title"
                            data-field="title"
                            contentEditable
                            suppressContentEditableWarning
                        >
                            {meetingData?.title || '会议纪要'}
                        </div>
                        <div className="mt-meta">
                            <span className="mt-meta-item">
                                <span style={{ opacity: 0.8, marginRight: 6 }}>日期</span>
                                <span data-field="date" contentEditable suppressContentEditableWarning>
                                    {dateStr || '未填写'}
                                </span>
                            </span>
                            <span className="mt-meta-item">
                                <span style={{ opacity: 0.8, marginRight: 6 }}>状态</span>
                                <span data-field="status" contentEditable suppressContentEditableWarning>
                                    {statusStr}
                                </span>
                            </span>
                        </div>
                    </div>

                    <div className="mt-body">
                        <div className="mt-section">
                            <div className="mt-section-title">会议概要</div>
                            <div
                                className="mt-summary"
                                data-field="summary"
                                contentEditable
                                suppressContentEditableWarning
                            >
                                {minutesObj.summary || '（暂无摘要，可直接在此处填写）'}
                            </div>
                        </div>

                        <div className="mt-section">
                            <div className="mt-section-title">讨论要点</div>
                            {keyPointsArr.length ? (
                                <ul className="mt-list">
                                    {keyPointsArr.map((p, i) => (
                                        <li
                                            key={`kp-${i}`}
                                            data-field="key-point"
                                            contentEditable
                                            suppressContentEditableWarning
                                        >
                                            {plainFromKeyPoint(p)}
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="mt-empty">暂无讨论要点</div>
                            )}
                        </div>

                        <div className="mt-section">
                            <div className="mt-section-title">决策事项</div>
                            {decisionsArr.length ? (
                                <ul className="mt-list">
                                    {decisionsArr.map((d, i) => (
                                        <li
                                            key={`ds-${i}`}
                                            data-field="decision"
                                            contentEditable
                                            suppressContentEditableWarning
                                        >
                                            {plainFromDecision(d)}
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="mt-empty">暂无决策事项</div>
                            )}
                        </div>

                        <div className="mt-section">
                            <div className="mt-section-title">待办事项</div>
                            {actionsArr.length ? (
                                <ul className="mt-list">
                                    {actionsArr.map((a, i) => (
                                        <li
                                            key={`ac-${i}`}
                                            data-field="action-item"
                                            contentEditable
                                            suppressContentEditableWarning
                                        >
                                            {plainFromAction(a)}
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="mt-empty">暂无待办事项</div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        );
    };

    // -----------------------------------------------------------------
    // Metric row helpers — compact stats displayed under the title bar.
    // -----------------------------------------------------------------
    const computeDuration = () => {
        const s = meetingData?.start_time ? new Date(meetingData.start_time).getTime() : null;
        const e = meetingData?.end_time ? new Date(meetingData.end_time).getTime() : null;
        if (!s || !e || e <= s) return '-';
        const sec = Math.floor((e - s) / 1000);
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        if (h > 0) return `${h}h ${m}m`;
        return `${m || 1}m`;
    };
    const charCount = (meetingData?.polished_transcript || meetingData?.raw_transcript || '').length;

    const stepState = (key, afterKeys) => {
        const s = meetingData.status;
        if (s === 'completed' || afterKeys.includes(s)) return 'done';
        if (s === key) return 'active';
        return 'locked';
    };

    const renderStepper = () => {
        const s = meetingData.status;
        if (s === 'completed' || s === 'failed') return null;
        const steps = [
            { label: '录音 / 上传', state: s === 'recording' ? 'active' : 'done' },
            { label: 'AI 转写',    state: stepState('transcribing', ['polishing', 'processing']) },
            { label: '润色转写',   state: stepState('polishing',    ['processing']) },
            { label: '生成纪要',   state: stepState('processing',   []) },
        ];
        return (
            <div className="ds-stepper" style={{ marginTop: 12 }}>
                {steps.map((step, i) => (
                    <React.Fragment key={i}>
                        {i > 0 && <div className="ds-step-sep" />}
                        <div className={`ds-step ${step.state}`}>
                            <div className="ds-step-dot" />
                            {step.label}
                        </div>
                    </React.Fragment>
                ))}
            </div>
        );
    };

    const statusBadge = () => {
        const s = meetingData?.status;
        if (s === 'completed') return <span className="ds-badge tone-green">已完成</span>;
        if (s === 'failed') return <span className="ds-badge tone-red">失败</span>;
        if (s === 'recording') return <span className="ds-badge tone-red is-spinning">录音中</span>;
        if (s === 'transcribing') return <span className="ds-badge tone-blue is-spinning">转写中</span>;
        if (s === 'polishing') return <span className="ds-badge tone-amber is-spinning">润色中</span>;
        if (s === 'processing') return <span className="ds-badge tone-orange is-spinning">生成纪要中</span>;
        return <span className="ds-badge tone-gray">{s}</span>;
    };

    const asrLabel =
        !meetingData.asr_engine || meetingData.asr_engine === 'whisper'
            ? '本地 Whisper'
            : meetingData.asr_engine === 'xunfei'
                ? '讯飞 ASR'
                : meetingData.asr_engine;

    // -----------------------------------------------------------------
    // Top-right action dropdowns. All exports and all manual reruns are
    // collapsed here so the header reads as "title + state" first.
    // -----------------------------------------------------------------
    const canExport = meetingData.status === 'completed';
    const canRerun = !!meetingData.raw_transcript;

    const exportMenu = (
        <Menu onClickMenuItem={(key) => {
            if (key === 'md') doExportMarkdown();
            else if (key === 'txt') doExportPlainText();
            else if (key === 'html') doExportHtml();
            else if (key === 'png') doExportPng();
            else if (key === 'feishu') handleExportFeishu();
            else if (key === 'bitable') handleSyncRequirements();
            else if (key === 'feishu-open' && meetingData.feishu_url) window.open(meetingData.feishu_url, '_blank');
            else if (key === 'bitable-open' && meetingData.bitable_url) window.open(meetingData.bitable_url, '_blank');
        }}>
            <Menu.Item key="md" disabled={!canExport}>📥 &nbsp;下载 Markdown</Menu.Item>
            <Menu.Item key="txt" disabled={!canExport}>📄 &nbsp;下载纯文本</Menu.Item>
            <Menu.Item key="html" disabled={!canExport}>🌐 &nbsp;下载 HTML</Menu.Item>
            <Menu.Item key="png" disabled={!canExport}>🖼 &nbsp;导出为 PNG 图片</Menu.Item>
            <Menu.Item key="divider-1" disabled style={{ height: 1, padding: 0, margin: '4px 0', background: 'var(--ds-line)' }} />
            <Menu.Item key="feishu" disabled={!canExport}>☁️ &nbsp;导出到飞书文档</Menu.Item>
            <Menu.Item key="bitable" disabled={!canExport}>📊 &nbsp;同步需求到多维表格</Menu.Item>
            {meetingData.feishu_url && (
                <Menu.Item key="feishu-open">🔗 &nbsp;打开已导出的飞书文档</Menu.Item>
            )}
            {meetingData.bitable_url && (
                <Menu.Item key="bitable-open">🔗 &nbsp;打开已同步的多维表格</Menu.Item>
            )}
        </Menu>
    );

    const moreMenu = (
        <Menu onClickMenuItem={(key) => {
            if (key === 'polish') handleManualAction('polish');
            else if (key === 'summarize') handleManualAction('summarize');
            else if (key === 'extract') handleManualAction('extract');
            else if (key === 'resume') handleResume();
        }}>
            <Menu.Item key="polish" disabled={!canRerun}>🔆 &nbsp;重新润色转写</Menu.Item>
            <Menu.Item key="summarize" disabled={!canRerun}>📝 &nbsp;重新生成纪要</Menu.Item>
            <Menu.Item key="extract" disabled={!canRerun}>🗂 &nbsp;重新提取需求</Menu.Item>
            {meetingData.status !== 'completed' && (
                <Menu.Item key="resume">▶️ &nbsp;从断点恢复转写</Menu.Item>
            )}
        </Menu>
    );

    const kbSplitMenu = (
        <Menu onClickMenuItem={(key) => {
            if (key === 'stakeholders') {
                handleTabChange('stakeholders');
                Message.info({
                    content: '打开「干系人」后，在工具栏点击「同步图谱到知识库」上传干系人 Markdown。',
                    duration: 5000,
                });
            }
        }}>
            <Menu.Item key="stakeholders" disabled={!canExport}>
                👥 &nbsp;去「干系人」同步图谱到知识库…
            </Menu.Item>
        </Menu>
    );

    // -----------------------------------------------------------------
    // Status alert: shown above tabs when the meeting is processing or
    // failed, so the error never hides inside a table column.
    // -----------------------------------------------------------------
    const stateAlert = meetingData.status === 'failed' ? (
        <Alert
            type="error"
            banner
            content={
                <Space>
                    <span>处理失败。你可以尝试从断点恢复，或手动重新运行润色 / 纪要步骤。</span>
                    <Button size="mini" type="outline" status="danger" onClick={handleResume}>重试</Button>
                </Space>
            }
            style={{ marginBottom: 16 }}
        />
    ) : null;

    const kbBtnType = canExport ? 'primary' : 'outline';
    const kbBtnDisabled = kbSyncing;

    return (
        <div className="meeting-detail">
            {/* ---- Hero Card -------------------------------------------- */}
            <div className="ds-hero-card">
                <div className="ds-hero-card-inner">
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                <Button onClick={onBack} type="text" icon={<IconLeft />} size="small" />
                                <span className="ds-hero-kicker">会议详情</span>
                                {statusBadge()}
                            </div>
                            <div className="ds-hero-title" title={meetingData?.title || ''}>
                                {meetingData?.title || '未命名会议'}
                            </div>
                            <div className="ds-hero-meta">
                                {[
                                    meetingData?.start_time ? new Date(meetingData.start_time).toLocaleDateString('zh-CN') : null,
                                    computeDuration() !== '-' ? computeDuration() : null,
                                    charCount > 0 ? `${charCount.toLocaleString()} 字` : null,
                                ].filter(Boolean).join(' · ')}
                            </div>
                        </div>
                        <div className="meeting-detail-toolbar">
                            <Space wrap size={10}>
                                <Tooltip content={
                                    !canExport
                                        ? '会议处理完成后即可同步'
                                        : meetingData.kb_synced_at
                                            ? `已于 ${new Date(meetingData.kb_synced_at).toLocaleString('zh-CN')} 同步纪要到实施知识库。下拉可跳转干系人图谱同步。`
                                            : '将会议纪要以 Markdown 同步到实施知识库（可选归属项目）。下拉可去干系人页同步图谱。'
                                }>
                                    <span className="meeting-detail-kb-split">
                                        <Button
                                            type={kbBtnType}
                                            status={meetingData.kb_synced_at ? 'success' : undefined}
                                            className="meeting-detail-kb-main"
                                            onClick={openKbModal}
                                            loading={kbSyncing}
                                            disabled={kbBtnDisabled}
                                        >
                                            {meetingData.kb_synced_at ? '✓ 纪要已同步' : '同步纪要'}
                                        </Button>
                                        <Dropdown droplist={kbSplitMenu} trigger="click" position="br" disabled={kbBtnDisabled}>
                                            <Button
                                                type={kbBtnType}
                                                status={meetingData.kb_synced_at ? 'success' : undefined}
                                                className="meeting-detail-kb-caret"
                                                icon={<IconDown />}
                                                disabled={kbBtnDisabled}
                                            />
                                        </Dropdown>
                                    </span>
                                </Tooltip>
                                <Dropdown droplist={exportMenu} position="br" trigger="click" disabled={!canExport && !meetingData.feishu_url && !meetingData.bitable_url}>
                                    <Button type="outline" icon={<IconDownload />} loading={exporting}>导出</Button>
                                </Dropdown>
                                <Dropdown droplist={moreMenu} position="br" trigger="click">
                                    <Button type="outline" icon={<IconMore />} loading={loading}>更多</Button>
                                </Dropdown>
                            </Space>
                        </div>
                    </div>
                    {renderStepper()}
                </div>
            </div>

            {/* ---- Stat Grid ------------------------------------------- */}
            <div className="ds-stat-grid">
                <div className="ds-stat-card">
                    <div className="ds-stat-icon orange"><SvgCalendar /></div>
                    <div className="ds-stat-body">
                        <div className="ds-stat-label">日期</div>
                        <div className="ds-stat-value">
                            {meetingData?.start_time ? new Date(meetingData.start_time).toLocaleDateString('zh-CN') : '—'}
                        </div>
                    </div>
                </div>
                <div className="ds-stat-card">
                    <div className="ds-stat-icon blue"><SvgClock /></div>
                    <div className="ds-stat-body">
                        <div className="ds-stat-label">总时长</div>
                        <div className="ds-stat-value">{computeDuration()}</div>
                    </div>
                </div>
                <div className="ds-stat-card">
                    <div className="ds-stat-icon green"><SvgDoc /></div>
                    <div className="ds-stat-body">
                        <div className="ds-stat-label">字数</div>
                        <div className="ds-stat-value">{charCount.toLocaleString()}</div>
                    </div>
                </div>
                <div className="ds-stat-card">
                    <div className="ds-stat-icon purple"><SvgTask /></div>
                    <div className="ds-stat-body">
                        <div className="ds-stat-label">待办事项</div>
                        <div className="ds-stat-value">
                            {Array.isArray(meetingData?.minutes?.action_items) ? meetingData.minutes.action_items.length : 0}
                        </div>
                    </div>
                </div>
                <div className="ds-stat-card">
                    <div className="ds-stat-icon teal"><SvgMic /></div>
                    <div className="ds-stat-body">
                        <div className="ds-stat-label">ASR 引擎</div>
                        <div className="ds-stat-value" style={{ fontSize: 13 }}>{asrLabel}</div>
                    </div>
                </div>
                <div
                    className="ds-stat-card"
                    style={{ cursor: 'pointer' }}
                    onClick={() => openProjectModal('stakeholders')}
                    title="点击关联或更换项目"
                >
                    <div className="ds-stat-icon rose"><SvgFolder /></div>
                    <div className="ds-stat-body">
                        <div className="ds-stat-label">关联项目</div>
                        <div className="ds-stat-value" style={{ fontSize: 13 }}>
                            {meetingData?.kb_project_name || <span style={{ color: 'var(--ds-accent)' }}>＋ 关联</span>}
                        </div>
                    </div>
                </div>
            </div>

            {/* ---- Status alert (failed only) -------------------------- */}
            {stateAlert}

            {/* ---- Tabs ------------------------------------------------ */}
            <Tabs activeTab={activeTab} onChange={handleTabChange} size="large" type="card">
                <TabPane key="minutes" title="会议纪要">
                    {renderMinutesTab()}
                </TabPane>
                <TabPane key="transcript" title="完整转写">
                    {renderTranscript()}
                </TabPane>
                <TabPane key="requirements" title="需求清单">
                    {renderRequirements()}
                </TabPane>
                <TabPane
                    key="stakeholders"
                    title={
                        <span>
                            干系人图谱
                            {Array.isArray(meetingData?.stakeholders?.stakeholders) && meetingData.stakeholders.stakeholders.length > 0 && (
                                <span style={{ marginLeft: 6, fontSize: 12, color: 'var(--ds-text-3)' }}>
                                    ({meetingData.stakeholders.stakeholders.length})
                                </span>
                            )}
                        </span>
                    }
                >
                    {window.StakeholderTab ? (
                        <window.StakeholderTab
                            meeting={meetingData}
                            onRefresh={refreshMeetingData}
                            onProjectClick={() => openProjectModal('stakeholders')}
                            onSyncedKb={(res) => setMeetingData((prev) => ({
                                ...prev,
                                stakeholder_kb_doc_id: res.kb_doc_id,
                                stakeholder_kb_url: res.kb_url,
                                stakeholder_kb_synced_at: res.kb_synced_at || new Date().toISOString(),
                            }))}
                        />
                    ) : (
                        <Spin />
                    )}
                </TabPane>
            </Tabs>

            {/* ---- KB sync Modal --------------------------------------- */}
            <Modal
                title={meetingData.kb_synced_at ? '重新同步到实施知识库' : '同步到实施知识库'}
                visible={kbModalOpen}
                onCancel={() => setKbModalOpen(false)}
                onOk={doSyncToKb}
                okText={kbSyncing ? '同步中...' : (meetingData.kb_synced_at ? '替换并重新同步' : '同步')}
                cancelText="取消"
                confirmLoading={kbSyncing}
                okButtonProps={{ disabled: kbProjectsLoading }}
                style={{ width: 520 }}
            >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <Typography.Paragraph style={{ marginBottom: 0, color: 'var(--ds-text-2)' }}>
                        将本会议纪要以 <strong>Markdown</strong> 形式上传到实施知识库（自动归类为「会议纪要」）。
                        如选择项目，文档会挂在该项目下；不选则进入未归属池。
                    </Typography.Paragraph>

                    {kbProjectsError && (
                        <Alert
                            type="error"
                            content={`项目列表加载失败：${kbProjectsError}（仍可不选项目直接同步）`}
                        />
                    )}

                    <div>
                        <Typography.Text style={{ fontSize: 13, color: 'var(--ds-text-3)' }}>
                            归属项目（可选）
                        </Typography.Text>
                        <Select
                            allowClear
                            showSearch
                            placeholder="不选则不归属任何项目"
                            value={kbSelectedProject || undefined}
                            onChange={(v) => setKbSelectedProject(v || '')}
                            loading={kbProjectsLoading}
                            style={{ marginTop: 6, width: '100%' }}
                            filterOption={(input, option) => {
                                const txt = (option && option.props && option.props.children) || '';
                                return String(txt).toLowerCase().includes(String(input).toLowerCase());
                            }}
                        >
                            {(kbProjects || []).map((p) => (
                                <Select.Option key={p.id} value={p.id}>
                                    {p.name}{p.customer && p.customer !== p.name ? ` · ${p.customer}` : ''}
                                </Select.Option>
                            ))}
                        </Select>
                    </div>

                    {meetingData.kb_synced_at && (
                        <Alert
                            type="warning"
                            content={
                                <Space size={4} wrap>
                                    <span>已于 {new Date(meetingData.kb_synced_at).toLocaleString('zh-CN')} 同步过。</span>
                                    {meetingData.kb_url && (
                                        <Link href={meetingData.kb_url} target="_blank">查看旧文档</Link>
                                    )}
                                    <span>确认后会先 <strong>删除旧文档</strong>，再上传当前最新的版本。</span>
                                </Space>
                            }
                        />
                    )}
                </div>
            </Modal>

            {/* ---- Project association Modal ---------------------------- */}
            <Modal
                title={meetingData.kb_project_id ? '更换关联项目' : '关联项目'}
                visible={projectModalOpen}
                onCancel={() => setProjectModalOpen(false)}
                onOk={submitProjectChoice}
                okText={projectSubmitting ? '保存中...' : '保存'}
                cancelText="取消"
                confirmLoading={projectSubmitting}
                style={{ width: 520 }}
            >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <Typography.Paragraph style={{ marginBottom: 0, color: 'var(--ds-text-2)' }}>
                        关联实施知识库中的项目后，系统会自动拉取该项目下的所有文档，
                        从中识别人员信息并合并到本会议的<strong>干系人图谱</strong>中。
                    </Typography.Paragraph>

                    {kbProjectsError && (
                        <Alert
                            type="error"
                            content={`项目列表加载失败：${kbProjectsError}`}
                        />
                    )}

                    <div>
                        <Typography.Text style={{ fontSize: 13, color: 'var(--ds-text-3)' }}>
                            选择项目（留空可清除关联）
                        </Typography.Text>
                        <Select
                            allowClear
                            showSearch
                            placeholder="搜索项目名称 / 客户"
                            value={projectChoice || undefined}
                            onChange={(v) => setProjectChoice(v || '')}
                            loading={kbProjectsLoading}
                            style={{ marginTop: 6, width: '100%' }}
                            filterOption={(input, option) => {
                                const txt = (option && option.props && option.props.children) || '';
                                return String(txt).toLowerCase().includes(String(input).toLowerCase());
                            }}
                        >
                            {(kbProjects || []).map((p) => (
                                <Select.Option key={p.id} value={p.id}>
                                    {p.name}{p.customer && p.customer !== p.name ? ` · ${p.customer}` : ''}{p.document_count ? ` (${p.document_count} 文档)` : ''}
                                </Select.Option>
                            ))}
                        </Select>
                    </div>

                    {projectChoice && (
                        <Alert
                            type="info"
                            content="保存后会自动重新抽取干系人，融合项目知识库里的人员信息（约 30-60 秒）"
                        />
                    )}
                </div>
            </Modal>
        </div>
    );
}
