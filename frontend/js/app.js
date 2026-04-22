/* Main App - uses JSX and Arco Design */
const { useState, useEffect, useCallback } = React;
var { Layout, Menu, Button, Space, Typography } = arco;
var { Header, Content } = Layout;
var MenuItem = Menu.Item;

function AppHeader({ currentView, onNavigate }) {
    return (
        <Header className="app-header" style={{ display: 'flex', alignItems: 'center', padding: '0 24px', background: 'var(--color-bg-2)', borderBottom: '1px solid var(--color-border)' }}>
            <div className="header-brand" onClick={() => onNavigate('home')} style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', marginRight: '40px' }}>
                <Typography.Title heading={4} style={{ margin: 0, color: 'var(--color-text-1)' }}>AI 会议转写</Typography.Title>
            </div>
            <Menu 
                mode="horizontal" 
                selectedKeys={[currentView]} 
                onClickMenuItem={onNavigate}
                style={{ flex: 1 }}
            >
                <MenuItem key="home">会议列表</MenuItem>
                <MenuItem key="upload">上传音频</MenuItem>
                <MenuItem key="recording">实时录音</MenuItem>
            </Menu>
        </Header>
    );
}

function App() {
    const [currentView, setCurrentView] = useState('home');
    const [meetings, setMeetings] = useState([]);
    const [currentMeeting, setCurrentMeeting] = useState(null);

    const loadMeetings = useCallback(async () => {
        try {
            const data = await window.api.getMeetings();
            setMeetings(Array.isArray(data) ? data : data.meetings || []);
        } catch (err) {
            console.error('Failed to load meetings:', err);
        }
    }, []);

    useEffect(() => { loadMeetings(); }, [loadMeetings]);

    const handleSelectMeeting = (meeting) => { setCurrentMeeting(meeting); setCurrentView('meeting'); };
    const handleMeetingCreated = (meetingId) => { loadMeetings(); setCurrentMeeting({ id: meetingId }); setCurrentView('meeting'); };
    const handleNavigate = (view) => { setCurrentView(view); if (view === 'home') loadMeetings(); };

    return (
        <Layout className="app-layout" style={{ minHeight: '100vh' }}>
            <AppHeader currentView={currentView} onNavigate={handleNavigate} />
            <Content className="main-content" style={{ padding: '24px', background: 'var(--color-bg-1)' }}>
                <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
                    {currentView === 'home' && <MeetingList meetings={meetings} onSelect={handleSelectMeeting} onRefresh={loadMeetings} />}
                    {currentView === 'upload' && <Uploader onMeetingCreated={handleMeetingCreated} />}
                    {currentView === 'recording' && <Recorder onMeetingCreated={handleMeetingCreated} />}
                    {currentView === 'meeting' && currentMeeting && <MeetingDetail meeting={currentMeeting} onBack={() => handleNavigate('home')} />}
                </div>
            </Content>
        </Layout>
    );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
