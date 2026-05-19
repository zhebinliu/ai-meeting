/**
 * NewConsoleMeetingDetail — uat 下的会议详情页(Liquid Glass)
 *
 * 实用策略:**主壳新 UI + 6 个 Tab 复用老组件**
 *   - 主组件 1931 行里 1776 行是 6 个 Tab Panel(复杂业务逻辑)
 *   - 一次性重写所有 Tab 风险高 + token 不够
 *   - 把生产文件里的 6 个 Tab 加了 export,这里直接 import 它们
 *   - 仅重写主壳(Header / 进度条 / Tab 栏 / 容器)为 Liquid Glass
 *
 * 功能 100% 等价:6 个 Tab 直接用老实现 + 主壳真功能(返回/重新处理/删除/进度)
 * 视觉:外壳是 Liquid Glass,Tab 内部仍是老 UI(可读但视觉不一致 — 等待下次细化)
 */
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import {
  ChevronLeft, Loader2, RefreshCw, Trash2, FolderKanban,
  FileText, ListChecks, Users, Settings as SettingsIcon, Info,
  type LucideIcon,
} from 'lucide-react'
import {
  getMeeting, deleteMeeting, processMeeting,
  type Meeting,
} from '../../api/client'
import {
  StatusBadge, fmt,
  OverviewTab, TranscriptTab, MinutesTab,
  RequirementsTab, StakeholdersTab, ActionsTab,
} from '../../pages/console/ConsoleMeetingDetail'
import GlowCard from '../components/GlowCard'

type Tab = 'overview' | 'transcript' | 'minutes' | 'requirements' | 'stakeholders' | 'actions'

const TABS: Array<{ key: Tab; label: string; Icon: LucideIcon }> = [
  { key: 'overview',     label: '概览',     Icon: Info },
  { key: 'transcript',   label: '转录',     Icon: FileText },
  { key: 'minutes',      label: '纪要',     Icon: ListChecks },
  { key: 'requirements', label: '需求清单', Icon: ListChecks },
  { key: 'stakeholders', label: '干系人',   Icon: Users },
  { key: 'actions',      label: '操作',     Icon: SettingsIcon },
]

export default function NewConsoleMeetingDetail() {
  const { id } = useParams<{ id: string }>()
  const meetingId = Number(id)
  const nav = useNavigate()
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('overview')

  const { data: meeting, isLoading, error } = useQuery({
    queryKey: ['meeting', meetingId],
    queryFn: () => getMeeting(meetingId),
    enabled: Number.isFinite(meetingId),
    refetchInterval: (qq) => {
      const m = qq.state.data as Meeting | undefined
      return m && (m.status === 'processing' || m.status === 'recording') ? 5000 : false
    },
  })

  const processMut = useMutation({
    mutationFn: () => processMeeting(meetingId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['meeting', meetingId] }),
  })

  const delMut = useMutation({
    mutationFn: () => deleteMeeting(meetingId),
    onSuccess: () => nav('/console/meeting'),
  })

  if (!Number.isFinite(meetingId)) {
    return <div className="rd-page" style={{ textAlign: 'center', color: 'var(--rd-text-3)', fontSize: 13 }}>无效的会议 ID</div>
  }
  if (isLoading) {
    return (
      <div className="rd-page" style={{ textAlign: 'center', color: 'var(--rd-text-3)', fontSize: 13 }}>
        <Loader2 size={16} className="animate-spin" style={{ display: 'inline', marginRight: 8 }} /> 加载中…
      </div>
    )
  }
  if (error || !meeting) {
    return <div className="rd-page" style={{ textAlign: 'center', color: '#F87171', fontSize: 13 }}>会议不存在或无权访问</div>
  }

  return (
    <div className="rd-page" style={{ maxWidth: 1280 }}>
      {/* 返回 */}
      <button
        onClick={() => nav('/console/meeting')}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          background: 'transparent', border: 'none', padding: '4px 0',
          color: 'var(--rd-text-3)', fontSize: 13, cursor: 'pointer',
          marginBottom: 14, fontFamily: 'inherit',
        }}
        onMouseEnter={e => e.currentTarget.style.color = 'var(--rd-text)'}
        onMouseLeave={e => e.currentTarget.style.color = 'var(--rd-text-3)'}
      >
        <ChevronLeft size={14} /> 返回列表
      </button>

      {/* Header 卡 */}
      <GlowCard style={{ padding: '18px 22px', marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{
              fontSize: 20, fontWeight: 800, color: 'var(--rd-text)',
              letterSpacing: '-0.015em', margin: 0,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>{meeting.title}</h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8, fontSize: 12, color: 'var(--rd-text-3)' }}>
              <StatusBadge status={meeting.status} />
              <span>·</span>
              <span className="rd-mono">{fmt(meeting.created_at)}</span>
              {meeting.project_name && (
                <>
                  <span>·</span>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <FolderKanban size={11} /> {meeting.project_name}
                  </span>
                </>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
            <button
              onClick={() => processMut.mutate()}
              disabled={processMut.isPending || !meeting.raw_transcript}
              className="rd-btn"
              style={{ fontSize: 12, padding: '7px 14px' }}
              title="重新跑完整 AI pipeline"
            >
              {processMut.isPending ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              重新处理
            </button>
            <button
              onClick={() => {
                if (window.confirm(`确认删除「${meeting.title}」?`)) delMut.mutate()
              }}
              className="rd-btn"
              style={{ fontSize: 12, padding: '7px 12px', color: '#F87171' }}
              title="删除"
            >
              <Trash2 size={13} />
            </button>
          </div>
        </div>
      </GlowCard>

      {/* 转写进度条 — processing + total_chunks > 0 才显示 */}
      {meeting.status === 'processing' && meeting.total_chunks > 0 && (
        <GlowCard glow style={{ padding: '14px 20px', marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, fontSize: 12 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--rd-text-2)' }}>
              <Loader2 size={12} className="animate-spin" color="var(--rd-accent)" />
              正在切片并发转写 · {meeting.asr_engine || 'xiaomi'} ASR
            </span>
            <span className="rd-mono" style={{ color: 'var(--rd-text-3)' }}>
              {meeting.done_chunks} / {meeting.total_chunks} 片
              ({Math.round((meeting.done_chunks / meeting.total_chunks) * 100)}%)
            </span>
          </div>
          <div style={{
            height: 5, borderRadius: 999, overflow: 'hidden',
            background: 'rgba(255, 141, 26, 0.10)',
          }}>
            <div
              style={{
                height: '100%',
                width: `${(meeting.done_chunks / meeting.total_chunks) * 100}%`,
                background: 'linear-gradient(90deg, var(--rd-accent), var(--rd-accent-2))',
                boxShadow: '0 0 8px var(--rd-accent)',
                transition: 'width .5s var(--rd-ease)',
              }}
            />
          </div>
          {meeting.raw_transcript && (
            <div style={{
              marginTop: 10, fontSize: 12, color: 'var(--rd-text-2)',
              maxHeight: 96, overflowY: 'auto',
              background: 'rgba(15, 18, 36, .025)',
              border: '1px solid var(--rd-line)',
              borderRadius: 8, padding: '8px 10px',
              lineHeight: 1.6,
            }}>
              {meeting.raw_transcript.slice(-400)}
              <span style={{
                display: 'inline-block', width: 2, height: 12,
                background: 'var(--rd-accent)', marginLeft: 2, verticalAlign: 'middle',
                animation: 'rd-blink 0.85s steps(2) infinite',
              }} />
            </div>
          )}
        </GlowCard>
      )}

      {/* Tabs + 内容容器 */}
      <GlowCard style={{ padding: 0, overflow: 'hidden' }}>
        {/* Tab bar */}
        <div style={{
          borderBottom: '1px solid var(--rd-line)',
          display: 'flex', overflowX: 'auto',
        }}>
          {TABS.map(t => {
            const Icon = t.Icon
            const active = tab === t.key
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  padding: '13px 22px',
                  fontSize: 13, fontWeight: active ? 700 : 500,
                  color: active ? 'var(--rd-accent-2)' : 'var(--rd-text-2)',
                  background: active
                    ? 'linear-gradient(180deg, rgba(255,141,26,.10) 0%, rgba(255,141,26,.02) 100%)'
                    : 'transparent',
                  border: 'none',
                  borderBottom: `2px solid ${active ? 'var(--rd-accent)' : 'transparent'}`,
                  marginBottom: -1,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  transition: 'all .2s',
                  fontFamily: 'inherit',
                }}
                onMouseEnter={e => { if (!active) e.currentTarget.style.color = 'var(--rd-text)' }}
                onMouseLeave={e => { if (!active) e.currentTarget.style.color = 'var(--rd-text-2)' }}
              >
                <Icon size={13} /> {t.label}
              </button>
            )
          })}
        </div>

        {/* Tab content — 内嵌老组件,功能 100% 等价 */}
        <div style={{ padding: '20px 24px' }}>
          {tab === 'overview' && <OverviewTab meeting={meeting} />}
          {tab === 'transcript' && <TranscriptTab meeting={meeting} />}
          {tab === 'minutes' && <MinutesTab meeting={meeting} />}
          {tab === 'requirements' && <RequirementsTab meeting={meeting} />}
          {tab === 'stakeholders' && <StakeholdersTab meeting={meeting} />}
          {tab === 'actions' && <ActionsTab meeting={meeting} />}
        </div>
      </GlowCard>
    </div>
  )
}
