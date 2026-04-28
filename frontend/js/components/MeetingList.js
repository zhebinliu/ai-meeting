/* MeetingList — DS-styled list page with running-tasks banner, status bar,
   duration / action-count columns, and CTA-rich empty state. */

var { Button, Table, Space, Tag, Popconfirm, Message, Typography, Tooltip, Dropdown, Menu } = arco;
var { Paragraph } = Typography;

const _mlIcons = window.arcoIcon || window.ArcoIcon || {};
const {
    IconFile = () => null,
    IconApps = () => null,
    IconSearch = () => null,
    IconDelete = () => null,
    IconRefresh = () => null,
    IconMore = () => null,
    IconCommon = () => null,
    IconPlus = () => null,
} = _mlIcons;

// ---------------------------------------------------------------
// Status tone / progress mapping. Keep the whole concept of
// "what's happening with this meeting" in one place so the table
// and the top banner share the exact same vocabulary.
// ---------------------------------------------------------------
const ACTIVE_STATUSES = new Set(['recording', 'transcribing', 'processing', 'polishing']);

function statusMeta(record) {
    const { status, total_chunks = 0, done_chunks = 0 } = record;
    const progress = total_chunks > 0 ? Math.min(100, Math.floor((done_chunks / total_chunks) * 100)) : null;
    switch (status) {
        case 'completed':
            return { tone: 'green', label: '已完成', fill: 100, fillClass: 'is-green' };
        case 'failed':
            return { tone: 'red', label: '失败', fill: 100, fillClass: 'is-red' };
        case 'recording':
            return { tone: 'red', label: '录音中', fill: null, fillClass: '', spinning: true };
        case 'transcribing':
            return {
                tone: 'blue',
                label: progress != null ? `转写中 ${progress}%` : '转写中',
                fill: progress,
                fillClass: '',
                spinning: true,
            };
        case 'polishing':
            return { tone: 'amber', label: 'AI 润色中', fill: null, fillClass: '', spinning: true };
        case 'processing':
            return { tone: 'orange', label: '生成纪要中', fill: null, fillClass: '', spinning: true };
        default:
            return { tone: 'gray', label: status || '未知', fill: null, fillClass: '' };
    }
}

function formatDuration(start, end) {
    if (!start) return '-';
    const s = new Date(start).getTime();
    const e = end ? new Date(end).getTime() : null;
    if (!e || e <= s) return '-';
    const sec = Math.floor((e - s) / 1000);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const r = sec % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${r}s`;
    return `${r}s`;
}

function actionCount(record) {
    // The list API exposes minutes either as a parsed object or as a
    // JSON string (field name: meeting_minutes). Cover both.
    const obj = record.minutes ?? (() => {
        const raw = record.meeting_minutes;
        if (!raw) return null;
        try { return JSON.parse(raw); } catch { return null; }
    })();
    if (!obj) return 0;
    return Array.isArray(obj.action_items) ? obj.action_items.length : 0;
}

// ---------------------------------------------------------------
// Small progress bar used inside the "状态" table column.
// ---------------------------------------------------------------
function StatusCell({ record }) {
    const meta = statusMeta(record);
    const fillWidth =
        meta.fill != null ? `${meta.fill}%` :
        meta.spinning ? '40%' : '0%';
    const cls = `ds-progress-fill ${meta.fillClass} ${meta.spinning ? 'is-indeterminate' : ''}`.trim();

    return (
        <div>
            <span className={`ds-badge tone-${meta.tone} ${meta.spinning ? 'is-spinning' : ''}`}>
                {meta.label}
            </span>
            {(meta.fill != null || meta.spinning) && (
                <div className="ds-progress-track" style={{ marginTop: 6 }}>
                    <div className={cls} style={{ width: fillWidth }} />
                </div>
            )}
        </div>
    );
}

// ---------------------------------------------------------------
// Banner shown at the top of the list whenever any meeting is still
// being processed, so users don't have to scan the table for 35%.
// ---------------------------------------------------------------
function RunningBanner({ activeMeetings, onSelect }) {
    if (!activeMeetings.length) return null;
    return (
        <div className="ds-running-banner">
            <div className="ds-running-banner-head">
                <span>🔄 &nbsp;正在处理 {activeMeetings.length} 个会议</span>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    每 5 秒自动刷新
                </Typography.Text>
            </div>
            {activeMeetings.slice(0, 4).map((m) => {
                const meta = statusMeta(m);
                const fill = meta.fill != null ? `${meta.fill}%` : '40%';
                return (
                    <div key={m.id} className="ds-running-banner-row">
                        <span className="ds-banner-name" onClick={() => onSelect(m)}>
                            {m.title || '未命名会议'}
                        </span>
                        <span className={`ds-badge tone-${meta.tone} ${meta.spinning ? 'is-spinning' : ''}`}>
                            {meta.label}
                        </span>
                        <div className="ds-progress-track" style={{ width: 160 }}>
                            <div
                                className={`ds-progress-fill ${meta.spinning ? 'is-indeterminate' : ''}`}
                                style={{ width: fill }}
                            />
                        </div>
                    </div>
                );
            })}
            {activeMeetings.length > 4 && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    还有 {activeMeetings.length - 4} 个进行中...
                </Typography.Text>
            )}
        </div>
    );
}

// ---------------------------------------------------------------
// Empty state that actively tells first-time users what to do next.
// ---------------------------------------------------------------
function EmptyCTA({ onNavigate }) {
    return (
        <div className="ds-empty">
            <div className="ds-empty-icon">🎙</div>
            <div className="ds-empty-title">还没有会议记录，从这里开始你的第一个</div>
            <div className="ds-empty-actions">
                <Button type="primary" onClick={() => onNavigate('/new/record')}>
                    🎙 实时录音
                </Button>
                <Button type="outline" onClick={() => onNavigate('/new/upload')}>
                    📁 上传音频
                </Button>
                <Button type="outline" onClick={() => onNavigate('/new/text')}>
                    📝 粘贴 / 上传文本
                </Button>
            </div>
        </div>
    );
}

function MeetingList({ meetings, onSelect, onRefresh, onNavigate }) {
    const [loading, setLoading] = React.useState(false);

    const activeMeetings = React.useMemo(
        () => meetings.filter((m) => ACTIVE_STATUSES.has(m.status)),
        [meetings]
    );

    React.useEffect(() => {
        if (!activeMeetings.length || !onRefresh) return;
        const id = setInterval(() => onRefresh(), 5000);
        return () => clearInterval(id);
    }, [activeMeetings.length, onRefresh]);

    const handleRefresh = async () => {
        if (!onRefresh) return;
        setLoading(true);
        try { await onRefresh(); } finally { setLoading(false); }
    };

    const handleDelete = async (id) => {
        try {
            await window.api.deleteMeeting(id);
            Message.success('删除成功');
            onRefresh && (await onRefresh());
        } catch (err) {
            Message.error('删除失败：' + err.message);
        }
    };

    const rowActionsMenu = (record) => (
        <Menu onClickMenuItem={(key) => {
            if (key === 'feishu' && record.feishu_url) window.open(record.feishu_url, '_blank');
            if (key === 'bitable' && record.bitable_url) window.open(record.bitable_url, '_blank');
            if (key === 'kb' && record.kb_url) window.open(record.kb_url, '_blank');
        }}>
            {record.feishu_url && <Menu.Item key="feishu"><IconFile /> &nbsp;打开飞书文档</Menu.Item>}
            {record.bitable_url && <Menu.Item key="bitable"><IconApps /> &nbsp;打开多维表格</Menu.Item>}
            {record.kb_url && <Menu.Item key="kb">📚 &nbsp;打开实施知识库文档</Menu.Item>}
        </Menu>
    );

    /** Renders a small green "已同步实施知识库" badge alongside the title.
     *  Clicking it opens the KB doc directly without entering the detail page. */
    const renderKbBadge = (record) => {
        if (!record.kb_synced_at) return null;
        const tip = `已于 ${new Date(record.kb_synced_at).toLocaleString('zh-CN')} 同步到实施知识库`;
        return (
            <Tooltip content={tip} key="kb">
                <span
                    className="ds-badge tone-green"
                    style={{ marginLeft: 8, fontSize: 11, cursor: record.kb_url ? 'pointer' : 'default' }}
                    onClick={(e) => {
                        if (!record.kb_url) return;
                        e.stopPropagation();
                        window.open(record.kb_url, '_blank');
                    }}
                >
                    📚 已同步实施知识库
                </span>
            </Tooltip>
        );
    };

    const columns = [
        {
            title: '会议标题',
            dataIndex: 'title',
            render: (col, record) => (
                <span style={{ display: 'inline-flex', alignItems: 'center', flexWrap: 'wrap', gap: 4 }}>
                    <span
                        onClick={() => onSelect(record)}
                        style={{ cursor: 'pointer', color: 'var(--ds-text)', fontWeight: 500 }}
                    >
                        {col || '未命名会议'}
                    </span>
                    {renderKbBadge(record)}
                </span>
            ),
        },
        {
            title: '状态',
            dataIndex: 'status',
            width: 180,
            render: (_, record) => <StatusCell record={record} />,
        },
        {
            title: '开始时间',
            dataIndex: 'start_time',
            width: 160,
            render: (col) => col ? new Date(col).toLocaleString('zh-CN') : '-',
        },
        {
            title: '时长',
            dataIndex: 'duration',
            width: 80,
            render: (_, record) => (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {formatDuration(record.start_time, record.end_time)}
                </Typography.Text>
            ),
        },
        {
            title: '待办',
            dataIndex: 'actions_count',
            width: 70,
            render: (_, record) => {
                const n = actionCount(record);
                if (!n) return <Typography.Text type="secondary" style={{ fontSize: 12 }}>-</Typography.Text>;
                return <span className="ds-badge tone-orange">{n}</span>;
            },
        },
        {
            title: '',
            dataIndex: 'ops',
            width: 120,
            align: 'right',
            render: (_, record) => (
                <Space size={4}>
                    <Tooltip content="查看详情">
                        <Button type="text" size="small" icon={<IconSearch />} onClick={() => onSelect(record)} />
                    </Tooltip>
                    {(record.feishu_url || record.bitable_url || record.kb_url) && (
                        <Dropdown droplist={rowActionsMenu(record)} trigger="click" position="br">
                            <Button type="text" size="small" icon={<IconMore />} />
                        </Dropdown>
                    )}
                    <Popconfirm title="确认删除该会议记录？" onOk={() => handleDelete(record.id)}>
                        <Tooltip content="删除">
                            <Button type="text" size="small" status="danger" icon={<IconDelete />} />
                        </Tooltip>
                    </Popconfirm>
                </Space>
            ),
        },
    ];

    const newMenu = (
        <Menu onClickMenuItem={(key) => onNavigate && onNavigate(`/new/${key}`)}>
            <Menu.Item key="record">🎙 &nbsp;实时录音</Menu.Item>
            <Menu.Item key="upload">📁 &nbsp;上传音频</Menu.Item>
            <Menu.Item key="text">📝 &nbsp;粘贴 / 上传文本</Menu.Item>
        </Menu>
    );

    return (
        <div className="meeting-list-view">
            <div className="ds-page-head">
                <div>
                    <h1>历史会议</h1>
                    <div className="ds-subtitle">
                        共 {meetings.length} 条记录
                        {activeMeetings.length > 0 && ` · ${activeMeetings.length} 个正在处理`}
                        {meetings.length > 0 && ' · 点击标题进入详情，或双击整行'}
                    </div>
                </div>
                <Space>
                    <Button type="outline" icon={<IconRefresh />} onClick={handleRefresh} loading={loading}>
                        刷新
                    </Button>
                    <Dropdown droplist={newMenu} position="br" trigger="click">
                        <Button type="primary" icon={<IconPlus />}>新建会议</Button>
                    </Dropdown>
                </Space>
            </div>

            <RunningBanner activeMeetings={activeMeetings} onSelect={onSelect} />

            {meetings.length === 0 ? (
                <div className="arco-card" style={{ padding: 0 }}>
                    <EmptyCTA onNavigate={onNavigate || (() => {})} />
                </div>
            ) : (
                <div className="arco-card" style={{ padding: 0, overflow: 'hidden' }}>
                    <Table
                        loading={loading}
                        columns={columns}
                        data={meetings}
                        rowKey="id"
                        pagination={{ pageSize: 10, showTotal: true }}
                        border={{ wrapper: false, cell: false }}
                        onRow={(record) => ({
                            onDoubleClick: () => onSelect(record),
                            style: { cursor: 'pointer' },
                        })}
                    />
                </div>
            )}
        </div>
    );
}
