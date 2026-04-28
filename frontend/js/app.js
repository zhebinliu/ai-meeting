/* Main App — hash-based router + DS-styled shell */
const { useState, useEffect, useCallback } = React;
var { Layout, Menu, Button, Dropdown, Typography, Space, Tooltip } = arco;
var { Header, Content } = Layout;
var MenuItem = Menu.Item;

const _appIcons = window.arcoIcon || window.ArcoIcon || {};
const { IconPlus = () => null, IconDown = () => null } = _appIcons;

// ---------------------------------------------------------------
// Hash router — single source of truth for which view is shown.
// Keeps meeting id + tab in the URL so F5 / back / share all work.
//
//   #/                       -> home (meeting list)
//   #/new/record             -> recorder
//   #/new/upload             -> uploader
//   #/new/text               -> text ingest
//   #/meeting/42             -> meeting detail (default tab)
//   #/meeting/42/transcript  -> meeting detail on a specific tab
// ---------------------------------------------------------------
function parseHash() {
    const raw = (window.location.hash || '').replace(/^#\/?/, '');
    const parts = raw.split('/').filter(Boolean);
    if (parts.length === 0) return { view: 'home' };
    if (parts[0] === 'new') {
        const sub = parts[1];
        if (sub === 'upload') return { view: 'upload' };
        if (sub === 'record') return { view: 'recording' };
        if (sub === 'text') return { view: 'text' };
        return { view: 'home' };
    }
    if (parts[0] === 'meeting' && parts[1]) {
        return { view: 'meeting', id: Number(parts[1]), tab: parts[2] || null };
    }
    return { view: 'home' };
}

function navigate(path) {
    // Always write via hash so we never touch server-side routing.
    if (path.startsWith('#')) window.location.hash = path.slice(1);
    else window.location.hash = path;
}

// Expose a tiny helper so any component can call navigate() without
// prop-drilling. Intentionally simple, not a router library.
window.appNav = { go: navigate, parse: parseHash };

// ---------------------------------------------------------------
// Header: brand + single "会议列表" tab + right-side CTA dropdown
// ---------------------------------------------------------------
function AppHeader({ currentView, onNavigate }) {
    const [manualOpen, setManualOpen] = useState(false);
    const Manual = window.UserManualDrawer;

    const newMeetingMenu = (
        <Menu onClickMenuItem={(key) => onNavigate(`/new/${key}`)}>
            <MenuItem key="record">🎙 &nbsp;实时录音</MenuItem>
            <MenuItem key="upload">📁 &nbsp;上传音频</MenuItem>
            <MenuItem key="text">📝 &nbsp;粘贴 / 上传文本</MenuItem>
        </Menu>
    );

    return (
        <Header className="app-header" style={{ display: 'flex', alignItems: 'center', padding: '0 24px' }}>
            <div
                className="header-brand"
                onClick={() => onNavigate('/')}
                style={{ cursor: 'pointer', marginRight: 36 }}
            >
                <span className="header-brand-mark">AI</span>
                <Typography.Title heading={5} style={{ margin: 0, color: 'var(--ds-text)' }}>
                    会议转写 <span style={{ color: 'var(--ds-text-3)', fontWeight: 400, fontSize: 13, marginLeft: 4 }}>Meeting</span>
                </Typography.Title>
            </div>

            <Menu
                mode="horizontal"
                selectedKeys={[currentView === 'meeting' ? 'home' : currentView]}
                onClickMenuItem={(key) => onNavigate(key === 'home' ? '/' : `/${key}`)}
                style={{ flex: 1, borderBottom: 'none', background: 'transparent' }}
            >
                <MenuItem key="home">会议列表</MenuItem>
            </Menu>

            <Space size={10}>
                <Tooltip content="操作手册">
                    <Button
                        type="outline"
                        shape="circle"
                        className="user-manual-trigger"
                        onClick={() => setManualOpen(true)}
                        aria-label="打开操作手册"
                    >
                        ?
                    </Button>
                </Tooltip>
                <Dropdown droplist={newMeetingMenu} position="br" trigger="click">
                    <Button type="primary" icon={<IconPlus />}>
                        新建会议
                    </Button>
                </Dropdown>
            </Space>
            {Manual ? (
                <Manual visible={manualOpen} onClose={() => setManualOpen(false)} />
            ) : null}
        </Header>
    );
}

// ---------------------------------------------------------------
function App() {
    const [route, setRoute] = useState(() => parseHash());
    const [meetings, setMeetings] = useState([]);

    const loadMeetings = useCallback(async () => {
        try {
            const data = await window.api.getMeetings();
            setMeetings(Array.isArray(data) ? data : data.meetings || []);
        } catch (err) {
            console.error('Failed to load meetings:', err);
        }
    }, []);

    // Subscribe to hash changes — this is our single navigation channel.
    useEffect(() => {
        const onHash = () => setRoute(parseHash());
        window.addEventListener('hashchange', onHash);
        // Normalise empty hash to #/ on first load.
        if (!window.location.hash) {
            window.location.hash = '/';
        }
        return () => window.removeEventListener('hashchange', onHash);
    }, []);

    // Reload meeting list whenever we return to home.
    useEffect(() => {
        if (route.view === 'home') loadMeetings();
    }, [route.view, loadMeetings]);

    // Also load once on app start so header badge counts etc. are ready.
    useEffect(() => { loadMeetings(); }, [loadMeetings]);

    const handleNavigate = (path) => navigate(path);

    const handleSelectMeeting = (meeting) => navigate(`/meeting/${meeting.id}`);
    const handleMeetingCreated = (meetingId) => {
        loadMeetings();
        navigate(`/meeting/${meetingId}`);
    };

    return (
        <Layout className="app-layout" style={{ minHeight: '100vh' }}>
            <AppHeader currentView={route.view} onNavigate={handleNavigate} />
            <Content className="main-content" style={{ padding: '24px' }}>
                <div style={{ maxWidth: 1200, margin: '0 auto' }}>
                    {route.view === 'home' && (
                        <MeetingList
                            meetings={meetings}
                            onSelect={handleSelectMeeting}
                            onRefresh={loadMeetings}
                            onNavigate={handleNavigate}
                        />
                    )}
                    {route.view === 'upload' && (
                        <Uploader onMeetingCreated={handleMeetingCreated} />
                    )}
                    {route.view === 'recording' && (
                        <Recorder onMeetingCreated={handleMeetingCreated} />
                    )}
                    {route.view === 'text' && (
                        <TextIngest onMeetingCreated={handleMeetingCreated} />
                    )}
                    {route.view === 'meeting' && route.id && (
                        <MeetingDetail
                            key={route.id}
                            meeting={{ id: route.id }}
                            initialTab={route.tab}
                            onBack={() => navigate('/')}
                            onTabChange={(tab) =>
                                navigate(`/meeting/${route.id}${tab ? '/' + tab : ''}`)
                            }
                        />
                    )}
                </div>
            </Content>
        </Layout>
    );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
