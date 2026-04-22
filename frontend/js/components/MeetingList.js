/* MeetingList component */
var { Button, Table, Space, Tag, Popconfirm, Message, Card, Typography, Tooltip } = arco;
var { Title, Paragraph } = Typography;
// Safe icon recovery logic
const _icons = window.arcoIcon || window.ArcoIcon || {};
const { 
    IconFile = () => null, 
    IconApps = () => null, 
    IconSearch = () => null, 
    IconDelete = () => null, 
    IconRefresh = () => null,
    IconLeft = () => null,
    IconBulb = () => null,
    IconPlayArrow = () => null,
    IconCheckCircle = () => null,
    IconOrderedList = () => null
} = _icons;

function MeetingList({ meetings, onSelect, onRefresh }) {
    const [loading, setLoading] = React.useState(false);

    // Auto-refresh logic: poll every 5 seconds if there are active tasks
    React.useEffect(() => {
        const hasActiveTasks = meetings.some(m => m.status === 'transcribing' || m.status === 'processing' || m.status === 'polishing');
        let intervalId = null;

        if (hasActiveTasks && onRefresh) {
            intervalId = setInterval(() => {
                onRefresh();
            }, 5000);
        }

        return () => {
            if (intervalId) clearInterval(intervalId);
        };
    }, [meetings, onRefresh]);

    const handleRefresh = async () => {
        if (!onRefresh) return;
        setLoading(true);
        try { await onRefresh(); } finally { setLoading(false); }
    };

    const handleDelete = async (id) => {
        try {
            await window.api.deleteMeeting(id);
            Message.success('删除成功');
            if (onRefresh) await onRefresh();
        } catch (err) {
            Message.error('删除失败：' + err.message);
        }
    };

    const getStatusTag = (record) => {
        const { status, total_chunks, done_chunks } = record;
        const config = {
            completed: { color: 'green', text: '已完成' },
            recording: { color: 'red', text: '录音中' },
            processing: { color: 'arcoblue', text: '处理中' },
            transcribing: { color: 'blue', text: '转写中' },
            polishing: { color: 'gold', text: '润色中' },
            failed: { color: 'red', text: '失败' }
        };
        const st = config[status] || { color: 'gray', text: status };
        const progressStr = (status === 'transcribing' && total_chunks > 0) 
            ? ` (${Math.floor((done_chunks / total_chunks) * 100)}%)` 
            : '';
            
        return <Tag color={st.color}>{st.text}{progressStr}</Tag>;
    };

    const columns = [
        {
            title: '会议标题',
            dataIndex: 'title',
            render: (col) => col || '未命名会议'
        },
        {
            title: '状态',
            dataIndex: 'status',
            render: (_, record) => getStatusTag(record)
        },
        {
            title: '开始时间',
            dataIndex: 'start_time',
            render: (col) => col ? new Date(col).toLocaleString('zh-CN') : '-'
        },
        {
            title: '操作',
            dataIndex: 'actions',
            render: (_, record) => (
                <Space>
                    <Tooltip content="详情查看">
                        <Button type="text" icon={<IconSearch />} onClick={() => onSelect(record)} />
                    </Tooltip>
                    {record.feishu_url && (
                        <Tooltip content="查看飞书文档">
                            <Button 
                                type="text" 
                                size="small" 
                                icon={<IconFile />}
                                onClick={(e) => { e.stopPropagation(); window.open(record.feishu_url, '_blank'); }}
                                style={{ color: '#3370ff' }}
                            />
                        </Tooltip>
                    )}
                    {record.bitable_url && (
                        <Tooltip content="查看多维表格">
                            <Button 
                                type="text" 
                                size="small" 
                                icon={<IconApps />}
                                onClick={(e) => { e.stopPropagation(); window.open(record.bitable_url, '_blank'); }}
                                style={{ color: '#00b42a' }}
                            />
                        </Tooltip>
                    )}
                    <Popconfirm
                        title="确认删除该会议记录？"
                        onOk={() => handleDelete(record.id)}
                    >
                        <Tooltip content="删除记录">
                            <Button type="text" status="danger" icon={<IconDelete />} />
                        </Tooltip>
                    </Popconfirm>
                </Space>
            )
        }
    ];

    return (
        <Card title="历史会议" extra={<Button type="outline" onClick={handleRefresh} loading={loading}>刷新</Button>} bordered={false}>
            {meetings.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px 0' }}>
                    <Typography.Text type="secondary">暂无会议记录</Typography.Text>
                    <Paragraph type="secondary" style={{ fontSize: '12px' }}>点击「上传音频」或「实时录音」创建第一个会议</Paragraph>
                </div>
            ) : (
                <Table 
                    loading={loading}
                    columns={columns} 
                    data={meetings} 
                    rowKey="id" 
                    pagination={{ pageSize: 10 }}
                />
            )}
        </Card>
    );
}
