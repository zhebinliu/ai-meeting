/* StakeholderTab — cards + interactive graph (vis-network) + manual edit + KB sync */

(function () {
    var {
        Button, Tag, Space, Tooltip, Empty, Typography, Message, Alert,
        Modal, Radio, Input, Select, Popconfirm, Card,
    } = arco;
    const _icons = window.arcoIcon || window.ArcoIcon || {};
    const { IconRefresh = () => null, IconUpload = () => null, IconEdit = () => null } = _icons;

    const SIDE_META = {
        internal: { label: '我方', color: 'arcoblue' },
        customer: { label: '客户', color: 'orange' },
        vendor: { label: '供应商', color: 'purple' },
        unknown: { label: '未知', color: 'gray' },
    };

    const SIDE_OPTIONS = ['internal', 'customer', 'vendor', 'unknown'];

    function initialsFromName(name) {
        const s = (name || '').trim();
        if (!s) return '?';
        if (/[\u4e00-\u9fff]/.test(s)) return s.slice(0, 2);
        const parts = s.split(/\s+/).filter(Boolean);
        if (parts.length >= 2) {
            return (parts[0][0] + parts[1][0]).toUpperCase();
        }
        return s.slice(0, 2).toUpperCase();
    }

    function sourceTagMeta(s) {
        const t = (s && s.type) || 'meeting';
        if (t === 'kb_doc') return { color: 'cyan', label: '知识库' };
        if (t === 'prior_meeting') return { color: 'orangered', label: '历史会议' };
        return { color: 'green', label: '本场会议' };
    }

    function cloneGraph(obj) {
        const g = obj && typeof obj === 'object' ? obj : { stakeholders: [], relations: [] };
        try {
            return JSON.parse(JSON.stringify({
                stakeholders: Array.isArray(g.stakeholders) ? g.stakeholders : [],
                relations: Array.isArray(g.relations) ? g.relations : [],
            }));
        } catch (e) {
            return { stakeholders: [], relations: [] };
        }
    }

    function buildVisData(people, relations) {
        const nodes = [];
        const edges = [];
        const list = Array.isArray(people) ? people : [];
        const rels = Array.isArray(relations) ? relations : [];

        list.forEach((p, i) => {
            const side = SIDE_OPTIONS.includes(p.side) ? p.side : 'unknown';
            const name = (p.name || '').trim();
            const label = name || ('人员 ' + (i + 1));
            const sub = (p.role || '').trim();
            nodes.push({
                id: 'p' + i,
                label: sub ? label + '\n' + sub : label,
                group: side,
                title: (p.organization || '').trim() || undefined,
            });
        });

        const extraIdByName = new Map();
        function resolveId(rawName) {
            const n = (rawName || '').trim();
            if (!n) return null;
            const idx = list.findIndex((p) => (p.name || '').trim() === n);
            if (idx >= 0) return 'p' + idx;
            if (extraIdByName.has(n)) return extraIdByName.get(n);
            const xid = 'x' + extraIdByName.size;
            extraIdByName.set(n, xid);
            nodes.push({
                id: xid,
                label: n + '\n(仅关系中出现)',
                group: 'unknown',
                color: { background: '#F7F8FA', border: '#C9CDD4' },
            });
            return xid;
        }

        rels.forEach((r, i) => {
            const a = resolveId(r.from);
            const b = resolveId(r.to);
            if (!a || !b) return;
            let lab = (r.type || '关系').trim();
            if (r.description) lab += ': ' + String(r.description).slice(0, 36);
            if (lab.length > 48) lab = lab.slice(0, 45) + '…';
            edges.push({ id: 'e' + i, from: a, to: b, label: lab });
        });

        return { nodes, edges };
    }

    function StakeholderGraphView({ people, relations }) {
        const containerRef = React.useRef(null);
        const networkRef = React.useRef(null);
        const sig = JSON.stringify({ people, relations });

        React.useEffect(() => {
            const el = containerRef.current;
            if (!el || typeof vis === 'undefined') return;

            if (networkRef.current) {
                try { networkRef.current.destroy(); } catch (e) {}
                networkRef.current = null;
            }

            const { nodes, edges } = buildVisData(people, relations);
            if (nodes.length === 0) return;

            const data = {
                nodes: new vis.DataSet(nodes),
                edges: new vis.DataSet(edges),
            };
            const options = {
                nodes: {
                    shape: 'box',
                    margin: 12,
                    font: { size: 13, multi: true, align: 'center' },
                    borderWidth: 2,
                    shadow: true,
                },
                edges: {
                    arrows: 'to',
                    font: { size: 11, align: 'middle', strokeWidth: 0 },
                    smooth: { type: 'dynamic' },
                },
                physics: {
                    enabled: true,
                    stabilization: { iterations: 120 },
                    barnesHut: {
                        gravitationalConstant: -2200,
                        centralGravity: 0.35,
                        springLength: 140,
                    },
                },
                interaction: { hover: true, tooltipDelay: 120 },
                groups: {
                    internal: { color: { background: '#E8F4FF', border: '#165DFF' } },
                    customer: { color: { background: '#FFF5EB', border: '#FF9A2E' } },
                    vendor: { color: { background: '#F7EEFF', border: '#9B51E0' } },
                    unknown: { color: { background: '#F7F8FA', border: '#A9AEB8' } },
                },
            };

            networkRef.current = new vis.Network(el, data, options);
            return () => {
                if (networkRef.current) {
                    try { networkRef.current.destroy(); } catch (e) {}
                    networkRef.current = null;
                }
            };
        }, [sig]);

        if (typeof vis === 'undefined') {
            return (
                <Alert
                    type="warning"
                    content="关系图依赖 vis-network 脚本，请检查网络或刷新页面。"
                />
            );
        }

        const { nodes } = buildVisData(people, relations);
        if (nodes.length === 0) {
            return (
                <Empty description="暂无节点。请先抽取干系人或在「手动编辑」中添加。" />
            );
        }

        return (
            <div className="stakeholder-graph-wrap">
                <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 10 }}>
                    可拖拽节点、滚轮缩放；边标签为关系类型。节点颜色表示立场（我方 / 客户 / 供应商）。
                </Typography.Text>
                <div ref={containerRef} className="stakeholder-graph-canvas" />
            </div>
        );
    }

    function PersonCard({ person }) {
        const sideKey = SIDE_OPTIONS.includes(person.side) ? person.side : 'unknown';
        const sideMeta = SIDE_META[sideKey] || SIDE_META.unknown;
        const sources = Array.isArray(person.sources) ? person.sources : [];
        const meetingSrcCount = sources.filter((s) => s.type === 'meeting').length;
        const kbSrcCount = sources.filter((s) => s.type === 'kb_doc').length;
        const priorSrcCount = sources.filter((s) => s.type === 'prior_meeting').length;

        return (
            <div className={'stakeholder-card stakeholder-card--' + sideKey}>
                <div className="stakeholder-card-head">
                    <div className="stakeholder-card-leading">
                        <div className="stakeholder-avatar" aria-hidden="true">
                            {initialsFromName(person.name)}
                        </div>
                        <div className="stakeholder-card-titles">
                            <div className="stakeholder-name">{person.name || '(未具名)'}</div>
                            <div className="stakeholder-role">
                                {[person.role, person.organization].filter(Boolean).join(' · ') || '—'}
                            </div>
                        </div>
                    </div>
                    <div className="stakeholder-tags">
                        <Tag color={sideMeta.color}>{sideMeta.label}</Tag>
                        {meetingSrcCount > 0 && (
                            <Tooltip content={'本场会议材料中提及 ' + meetingSrcCount + ' 次'}>
                                <Tag color="green" bordered>本场 ×{meetingSrcCount}</Tag>
                            </Tooltip>
                        )}
                        {priorSrcCount > 0 && (
                            <Tooltip content={'与其它内部历史会议纪要交叉出现 ' + priorSrcCount + ' 次'}>
                                <Tag color="orangered" bordered>历史 ×{priorSrcCount}</Tag>
                            </Tooltip>
                        )}
                        {kbSrcCount > 0 && (
                            <Tooltip content={'实施知识库文档中出现 ' + kbSrcCount + ' 次'}>
                                <Tag color="cyan" bordered>知识库 ×{kbSrcCount}</Tag>
                            </Tooltip>
                        )}
                    </div>
                </div>

                {Array.isArray(person.aliases) && person.aliases.length > 0 && (
                    <div className="stakeholder-row">
                        <span className="stakeholder-label">别名</span>
                        <span className="stakeholder-value">{person.aliases.join('、')}</span>
                    </div>
                )}

                {person.contact && (
                    <div className="stakeholder-row">
                        <span className="stakeholder-label">联系方式</span>
                        <span className="stakeholder-value">{person.contact}</span>
                    </div>
                )}

                {Array.isArray(person.responsibilities) && person.responsibilities.length > 0 && (
                    <div className="stakeholder-row">
                        <span className="stakeholder-label">职责</span>
                        <ul className="stakeholder-bullet">
                            {person.responsibilities.map((r, i) => <li key={i}>{r}</li>)}
                        </ul>
                    </div>
                )}

                {Array.isArray(person.key_points) && person.key_points.length > 0 && (
                    <div className="stakeholder-row">
                        <span className="stakeholder-label">关键观点</span>
                        <ul className="stakeholder-bullet">
                            {person.key_points.map((k, i) => <li key={i}>{k}</li>)}
                        </ul>
                    </div>
                )}

                {sources.length > 0 && (
                    <div className="stakeholder-row">
                        <span className="stakeholder-label">来源</span>
                        <ul className="stakeholder-bullet stakeholder-source">
                            {sources.map((s, i) => {
                                const sm = sourceTagMeta(s);
                                return (
                                    <li key={i}>
                                        <Tag size="small" color={sm.color} bordered>{sm.label}</Tag>
                                        {s.snippet ? <span>「{s.snippet}」</span> : <span style={{ color: 'var(--ds-text-3)' }}>{s.ref}</span>}
                                    </li>
                                );
                            })}
                        </ul>
                    </div>
                )}
            </div>
        );
    }

    function emptyPerson() {
        return {
            name: '',
            role: '',
            organization: '',
            side: 'unknown',
            contact: '',
            aliases: [],
            key_points: [],
            responsibilities: [],
            sources: [],
        };
    }

    function StakeholderTab(props) {
        const { meeting, onRefresh, onSyncedKb, onProjectClick } = props;

        const [extracting, setExtracting] = React.useState(false);
        const [syncing, setSyncing] = React.useState(false);
        const [saving, setSaving] = React.useState(false);
        const [panel, setPanel] = React.useState('cards');
        const [draft, setDraft] = React.useState(null);
        const [draftDirty, setDraftDirty] = React.useState(false);

        const graph = meeting?.stakeholders || { stakeholders: [], relations: [] };
        const people = Array.isArray(graph.stakeholders) ? graph.stakeholders : [];
        const relations = Array.isArray(graph.relations) ? graph.relations : [];
        const hasGraph = people.length > 0;

        const projectName = meeting?.kb_project_name || meeting?.kb_project_id || null;
        const extractTip = projectName
            ? '基于当前转录、纪要及已关联项目的实施知识库文档重新抽取。'
            : '基于当前转录、纪要及本系统中其它已完成的内部会议摘录重新抽取（未关联项目时自动使用历史会议）。';

        const nameOptions = (draft && Array.isArray(draft.stakeholders) ? draft.stakeholders : people)
            .map((p, i) => {
                const n = (p.name || '').trim();
                return { value: n, label: n || ('(未命名 ' + (i + 1) + ')') };
            })
            .filter((o) => o.value);

        const enterEdit = () => {
            setDraft(cloneGraph(meeting?.stakeholders || graph));
            setDraftDirty(false);
            setPanel('edit');
        };

        const requestPanel = (next) => {
            if (next === 'edit') {
                enterEdit();
                return;
            }
            if (panel === 'edit' && draftDirty) {
                Modal.confirm({
                    title: '放弃未保存的修改？',
                    content: '当前手动编辑尚未保存到服务器。',
                    okText: '放弃',
                    cancelText: '继续编辑',
                    okButtonProps: { status: 'danger' },
                    onOk: () => {
                        setDraft(null);
                        setDraftDirty(false);
                        setPanel(next);
                    },
                });
                return;
            }
            if (panel === 'edit') {
                setDraft(null);
            }
            setPanel(next);
        };

        const handleExtract = async () => {
            setExtracting(true);
            try {
                await window.api.extractStakeholders(meeting.id);
                Message.success('已开始重新抽取干系人，约需 30–60 秒，页面将自动刷新');
                setTimeout(() => onRefresh && onRefresh(), 8000);
                setTimeout(() => onRefresh && onRefresh(), 25000);
            } catch (err) {
                Message.error('抽取失败：' + (err.message || err));
            } finally {
                setExtracting(false);
            }
        };

        const handleSync = async () => {
            if (!hasGraph) {
                Message.warning('图谱为空，请先抽取或手动添加后保存');
                return;
            }
            setSyncing(true);
            try {
                const res = await window.api.syncStakeholderMapToKb(meeting.id, {
                    project_id: meeting.kb_project_id || undefined,
                });
                Message.success({
                    content: res.replaced_old_doc
                        ? '已重新同步到实施知识库（旧版本已替换）'
                        : '干系人图谱已同步到实施知识库',
                    footer: res.kb_url ? (
                        <Button size="mini" type="text" onClick={() => window.open(res.kb_url, '_blank')}>
                            打开文档
                        </Button>
                    ) : null,
                });
                onSyncedKb && onSyncedKb(res);
            } catch (err) {
                Message.error('同步失败：' + (err.message || err));
            } finally {
                setSyncing(false);
            }
        };

        const handleSaveDraft = async () => {
            if (!window.api || typeof window.api.updateStakeholderMap !== 'function') {
                Message.error('请强制刷新页面以加载最新 api.js');
                return;
            }
            setSaving(true);
            try {
                await window.api.updateStakeholderMap(meeting.id, {
                    stakeholders: draft.stakeholders,
                    relations: draft.relations,
                });
                Message.success('干系人图谱已保存');
                setDraftDirty(false);
                setDraft(null);
                setPanel('cards');
                onRefresh && onRefresh();
            } catch (err) {
                Message.error('保存失败：' + (err.message || err));
            } finally {
                setSaving(false);
            }
        };

        const updatePerson = (idx, field, value) => {
            setDraft((d) => {
                const next = cloneGraph(d);
                if (!next.stakeholders[idx]) return d;
                next.stakeholders[idx] = { ...next.stakeholders[idx], [field]: value };
                return next;
            });
            setDraftDirty(true);
        };

        const removePerson = (idx) => {
            setDraft((d) => {
                const next = cloneGraph(d);
                const removed = (next.stakeholders[idx].name || '').trim();
                next.stakeholders.splice(idx, 1);
                if (removed) {
                    next.relations = next.relations.filter(
                        (r) => (r.from || '').trim() !== removed && (r.to || '').trim() !== removed
                    );
                }
                return next;
            });
            setDraftDirty(true);
        };

        const addPerson = () => {
            setDraft((d) => {
                const next = cloneGraph(d);
                next.stakeholders.push(emptyPerson());
                return next;
            });
            setDraftDirty(true);
        };

        const updateRelation = (idx, field, value) => {
            setDraft((d) => {
                const next = cloneGraph(d);
                if (!next.relations[idx]) return d;
                next.relations[idx] = { ...next.relations[idx], [field]: value };
                return next;
            });
            setDraftDirty(true);
        };

        const addRelation = () => {
            setDraft((d) => {
                const next = cloneGraph(d);
                const names = next.stakeholders.map((p) => (p.name || '').trim()).filter(Boolean);
                const a = names[0] || '';
                const b = names[1] || names[0] || '';
                next.relations.push({ from: a, to: b, type: 'works_with', description: '' });
                return next;
            });
            setDraftDirty(true);
        };

        const removeRelation = (idx) => {
            setDraft((d) => {
                const next = cloneGraph(d);
                next.relations.splice(idx, 1);
                return next;
            });
            setDraftDirty(true);
        };

        return (
            <div className="stakeholder-tab">
                <div className="stakeholder-hero">
                    <div className="stakeholder-header">
                        <div style={{ flex: 1, minWidth: 200 }}>
                            <div className="stakeholder-hero-kicker">人员与协作网络</div>
                            <Typography.Title heading={5} className="stakeholder-hero-title" style={{ margin: '6px 0 0' }}>
                                干系人图谱
                                <span className="stakeholder-hero-stat">
                                    {people.length} 人
                                    {relations.length > 0 ? ' · ' + relations.length + ' 条关系' : ''}
                                </span>
                            </Typography.Title>
                            <div className="stakeholder-subhead">
                                {projectName ? (
                                    <span>
                                        已关联实施知识库项目：<strong>{projectName}</strong>
                                        {' '}
                                        <Button type="text" size="mini" onClick={onProjectClick}>更换</Button>
                                    </span>
                                ) : (
                                    <span style={{ color: 'var(--ds-text-2)' }}>
                                        未关联项目：抽取时会自动参考本系统中其它已完成的会议纪要，便于识别跨会议重复出现的同事。
                                        {' '}
                                        <Button type="text" size="mini" onClick={onProjectClick}>
                                            关联项目（可选）
                                        </Button>
                                    </span>
                                )}
                            </div>

                            <div className="stakeholder-view-toggle">
                                <Radio.Group type="button" value={panel} onChange={requestPanel} size="small">
                                    <Radio value="cards">卡片视图</Radio>
                                    <Radio value="graph">关系图</Radio>
                                    <Radio value="edit">手动编辑</Radio>
                                </Radio.Group>
                            </div>
                        </div>
                        <Space>
                        <Tooltip content={extractTip}>
                            <Button
                                type="outline"
                                icon={<IconRefresh />}
                                onClick={handleExtract}
                                loading={extracting}
                            >
                                重新抽取
                            </Button>
                        </Tooltip>
                        <Tooltip content="把当前图谱以 Markdown 上传到实施知识库（旧版本会自动替换）">
                            <Button
                                type="primary"
                                icon={<IconUpload />}
                                onClick={handleSync}
                                loading={syncing}
                                status={meeting?.stakeholder_kb_synced_at ? 'success' : undefined}
                                disabled={!hasGraph}
                            >
                                {meeting?.stakeholder_kb_synced_at ? '✓ 重新同步图谱' : '↗ 同步图谱到知识库'}
                            </Button>
                        </Tooltip>
                        </Space>
                    </div>
                </div>

                {meeting?.stakeholder_kb_synced_at && meeting?.stakeholder_kb_url && (
                    <Alert
                        type="success"
                        showIcon
                        style={{ marginTop: 12 }}
                        content={
                            <span>
                                上次同步：{new Date(meeting.stakeholder_kb_synced_at).toLocaleString('zh-CN')}
                                {' · '}
                                <a href={meeting.stakeholder_kb_url} target="_blank" rel="noreferrer">打开知识库文档</a>
                            </span>
                        }
                    />
                )}

                {panel === 'cards' && (
                    !hasGraph ? (
                        <div className="stakeholder-empty">
                            <Empty
                                description={
                                    <span style={{ color: 'var(--ds-text-3)' }}>
                                        还没有干系人数据。可使用「重新抽取」，或切换到「手动编辑」自行添加。
                                    </span>
                                }
                            />
                        </div>
                    ) : (
                        <div className="stakeholder-grid">
                            {people.map((p, i) => <PersonCard key={(p.name || '') + '-' + i} person={p} />)}
                        </div>
                    )
                )}

                {panel === 'graph' && (
                    <Card className="stakeholder-graph-shell" bordered={false} bodyStyle={{ padding: '18px 18px 14px' }}>
                        <StakeholderGraphView people={people} relations={relations} />
                    </Card>
                )}

                {panel === 'edit' && draft && (
                    <div style={{ marginTop: 16 }}>
                        <Alert
                            type="info"
                            style={{ marginBottom: 12 }}
                            content="修改后请点击「保存到服务器」。保存后「关系图」「同步知识库」均使用最新数据。重新「抽取」会与 AI 结果合并，可能覆盖部分手动修改。"
                        />
                        <Space style={{ marginBottom: 12 }}>
                            <Button type="primary" onClick={handleSaveDraft} loading={saving} icon={<IconEdit />}>
                                保存到服务器
                            </Button>
                            <Button
                                onClick={() => {
                                    setDraft(cloneGraph(meeting?.stakeholders || graph));
                                    setDraftDirty(false);
                                }}
                            >
                                重置为上次保存
                            </Button>
                            <Button onClick={addPerson}>＋ 添加干系人</Button>
                            <Button onClick={addRelation}>＋ 添加关系</Button>
                        </Space>

                        <Typography.Title heading={6} style={{ margin: '16px 0 8px' }}>干系人</Typography.Title>
                        {draft.stakeholders.map((p, idx) => (
                            <Card key={'edit-p-' + idx} size="small" style={{ marginBottom: 10 }} bordered>
                                <Space align="start" style={{ width: '100%' }} direction="vertical">
                                    <Space wrap style={{ width: '100%' }}>
                                        <Input
                                            addBefore="姓名"
                                            style={{ width: 200 }}
                                            value={p.name || ''}
                                            onChange={(v) => updatePerson(idx, 'name', v)}
                                            placeholder="必填"
                                        />
                                        <Select
                                            style={{ width: 160 }}
                                            value={p.side || 'unknown'}
                                            onChange={(v) => updatePerson(idx, 'side', v || 'unknown')}
                                            placeholder="立场"
                                            getPopupContainer={() => document.body}
                                        >
                                            {SIDE_OPTIONS.map((s) => (
                                                <Select.Option key={s} value={s}>{SIDE_META[s].label}</Select.Option>
                                            ))}
                                        </Select>
                                        <Popconfirm title="删除该干系人及相关关系？" onOk={() => removePerson(idx)}>
                                            <Button status="danger" size="small">删除</Button>
                                        </Popconfirm>
                                    </Space>
                                    <Input
                                        addBefore="角色"
                                        value={p.role || ''}
                                        onChange={(v) => updatePerson(idx, 'role', v)}
                                        placeholder="职务/角色"
                                    />
                                    <Input
                                        addBefore="组织"
                                        value={p.organization || ''}
                                        onChange={(v) => updatePerson(idx, 'organization', v)}
                                        placeholder="公司或部门"
                                    />
                                    <Input
                                        addBefore="联系"
                                        value={p.contact || ''}
                                        onChange={(v) => updatePerson(idx, 'contact', v)}
                                        placeholder="选填"
                                    />
                                </Space>
                            </Card>
                        ))}

                        <Typography.Title heading={6} style={{ margin: '20px 0 8px' }}>协作关系</Typography.Title>
                        {draft.relations.length === 0 && (
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>暂无关系，可点击「＋ 添加关系」。</Typography.Text>
                        )}
                        {draft.relations.map((r, idx) => (
                            <div key={'rel-' + idx} className="stakeholder-edit-relation-row">
                                <Select
                                    placeholder="从"
                                    style={{ width: 160 }}
                                    value={r.from || undefined}
                                    onChange={(v) => updateRelation(idx, 'from', v || '')}
                                    getPopupContainer={() => document.body}
                                >
                                    {nameOptions.map((o) => (
                                        <Select.Option key={o.value} value={o.value}>{o.label}</Select.Option>
                                    ))}
                                </Select>
                                <span className="stakeholder-edit-arrow">→</span>
                                <Select
                                    placeholder="到"
                                    style={{ width: 160 }}
                                    value={r.to || undefined}
                                    onChange={(v) => updateRelation(idx, 'to', v || '')}
                                    getPopupContainer={() => document.body}
                                >
                                    {nameOptions.map((o) => (
                                        <Select.Option key={'t-' + o.value} value={o.value}>{o.label}</Select.Option>
                                    ))}
                                </Select>
                                <Input
                                    style={{ width: 140 }}
                                    value={r.type || ''}
                                    onChange={(v) => updateRelation(idx, 'type', v)}
                                    placeholder="关系类型"
                                />
                                <Input
                                    style={{ flex: 1, minWidth: 120 }}
                                    value={r.description || ''}
                                    onChange={(v) => updateRelation(idx, 'description', v)}
                                    placeholder="说明（选填）"
                                />
                                <Button size="small" status="danger" onClick={() => removeRelation(idx)}>删除</Button>
                            </div>
                        ))}
                    </div>
                )}

                {panel === 'cards' && relations.length > 0 && (
                    <Card className="stakeholder-relations-shell" title="协作关系" style={{ marginTop: 18 }} bordered={false} bodyStyle={{ paddingTop: 8 }}>
                        <ul className="stakeholder-relations">
                            {relations.map((r, i) => (
                                <li key={i}>
                                    <Tag color="arcoblue">{r.from}</Tag>
                                    <span style={{ margin: '0 6px', color: 'var(--ds-text-3)' }}>→</span>
                                    <Tag color="orange">{r.to}</Tag>
                                    <span style={{ margin: '0 8px', fontSize: 12, color: 'var(--ds-text-3)' }}>
                                        ({r.type})
                                    </span>
                                    {r.description && <span>{r.description}</span>}
                                </li>
                            ))}
                        </ul>
                    </Card>
                )}
            </div>
        );
    }

    window.StakeholderTab = StakeholderTab;
})();
