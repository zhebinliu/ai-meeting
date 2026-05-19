/**
 * NewConsoleMeeting — 会议纪要列表(Liquid Glass)
 *
 * 功能 100% 等价于生产 `frontend/src/pages/console/ConsoleMeeting.tsx`:
 *   - listMeetings(processing/recording 时 8s 自动刷新)
 *   - 搜索过滤(title / project_name)
 *   - 状态过滤(全部 / processing / completed / failed / recording)+ 计数
 *   - 删除(confirm + invalidate)
 *   - 跳详情 /console/meeting/:id
 *   - 跳新建 /console/meeting/new
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import {
  Mic, Plus, Trash2, FolderKanban, CheckCircle2, Loader2, AlertCircle, Clock, Search,
} from 'lucide-react'
import { listMeetings, deleteMeeting, type Meeting, type MeetingStatus } from '../../api/client'
import GlowCard from '../components/GlowCard'

const STATUS_LABEL: Record<MeetingStatus, string> = {
  recording: '录制中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
}

const STATUS_BADGE_CLS: Record<MeetingStatus, string> = {
  recording:  'is-orange',
  processing: 'is-blue',
  completed:  'is-green',
  failed:     'is-red',
}
const STATUS_ICON: Record<MeetingStatus, typeof Mic> = {
  recording:  Mic,
  processing: Loader2,
  completed:  CheckCircle2,
  failed:     AlertCircle,
}

function StatusBadge({ status }: { status: MeetingStatus }) {
  const cls = STATUS_BADGE_CLS[status] ?? 'is-gray'
  const Icon = STATUS_ICON[status] ?? Clock
  return (
    <span className={`rd-badge ${cls}`} style={{ gap: 5 }}>
      <Icon size={10} className={status === 'processing' ? 'animate-spin' : ''} />
      {STATUS_LABEL[status] || status}
    </span>
  )
}

function formatTime(iso: string | null | undefined) {
  if (!iso) return '-'
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export default function NewConsoleMeeting() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<'' | MeetingStatus>('')

  const { data: meetings, isLoading } = useQuery({
    queryKey: ['meetings'],
    queryFn: listMeetings,
    refetchInterval: (qq) => {
      const items = (qq.state.data ?? []) as Meeting[]
      return items.some(m => m.status === 'processing' || m.status === 'recording') ? 8000 : false
    },
  })

  const filtered = (meetings || []).filter(m => {
    if (statusFilter && m.status !== statusFilter) return false
    if (keyword.trim()) {
      const k = keyword.trim().toLowerCase()
      const hay = `${m.title || ''} ${m.project_name || ''}`.toLowerCase()
      if (!hay.includes(k)) return false
    }
    return true
  })

  const statusCounts = (meetings || []).reduce<Record<string, number>>((acc, m) => {
    acc[m.status] = (acc[m.status] || 0) + 1
    return acc
  }, {})

  const delMutation = useMutation({
    mutationFn: (id: number) => deleteMeeting(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['meetings'] }),
  })

  const handleDelete = (m: Meeting) => {
    if (!window.confirm(`确认删除「${m.title}」?该操作不可撤销。`)) return
    delMutation.mutate(m.id)
  }

  return (
    <div className="rd-page">
      {/* Hero */}
      <div className="rd-stagger" style={{ marginBottom: 22, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <span className="rd-chip is-active" style={{ marginBottom: 10 }}>
            <Mic size={11} /> 会议纪要
          </span>
          <h1 style={{
            fontSize: 28, fontWeight: 800, color: 'var(--rd-text)',
            letterSpacing: '-0.025em', lineHeight: 1.1, margin: 0, marginBottom: 6,
          }}>所有会议</h1>
          <p style={{ fontSize: 13.5, color: 'var(--rd-text-2)', margin: 0, maxWidth: 580, lineHeight: 1.6 }}>
            上传录音 / 粘贴文本,AI 自动提取纪要、待办、需求清单和干系人图谱。
          </p>
        </div>
        <button
          onClick={() => nav('/console/meeting/new')}
          className="rd-btn rd-btn-primary"
          style={{ flexShrink: 0 }}
        >
          <Plus size={14} /> 新建会议
        </button>
      </div>

      {/* 搜索 + 状态 chips */}
      {meetings && meetings.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flex: 1, minWidth: 220, maxWidth: 380 }}>
            <Search size={13} style={{
              position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)',
              color: 'var(--rd-text-3)', pointerEvents: 'none',
            }} />
            <input
              className="rd-input"
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              placeholder="搜标题 / 项目名"
              style={{ paddingLeft: 36, fontSize: 13, padding: '9px 12px 9px 36px' }}
            />
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {(['', 'processing', 'completed', 'failed', 'recording'] as const).map(s => {
              const count = s === '' ? meetings.length : (statusCounts[s] || 0)
              if (s !== '' && count === 0) return null
              const active = statusFilter === s
              return (
                <button
                  key={s || 'all'}
                  onClick={() => setStatusFilter(s)}
                  className={`rd-chip${active ? ' is-active' : ''}`}
                  style={{ gap: 5 }}
                >
                  {s === '' ? '全部' : STATUS_LABEL[s as MeetingStatus]}
                  <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12, opacity: 0.7 }}>{count}</span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* List */}
      {isLoading ? (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '80px 0', color: 'var(--rd-text-3)', fontSize: 13 }}>
          <Loader2 size={16} className="animate-spin" style={{ marginRight: 8 }} /> 加载中…
        </div>
      ) : !meetings || meetings.length === 0 ? (
        <GlowCard style={{
          padding: '48px 24px', textAlign: 'center',
          border: '1px dashed var(--rd-line-strong)',
          background: 'transparent',
        }}>
          <div style={{
            width: 56, height: 56, borderRadius: 16,
            margin: '0 auto 14px',
            background: 'linear-gradient(135deg, rgba(255,141,26,.16), rgba(255,141,26,.04))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--rd-accent-2)',
          }}>
            <Mic size={22} />
          </div>
          <p style={{ fontSize: 14, fontWeight: 600, color: 'var(--rd-text)', margin: '0 0 4px' }}>还没有会议记录</p>
          <p style={{ fontSize: 12.5, color: 'var(--rd-text-3)', margin: '0 0 16px' }}>点击右上角「新建会议」开始第一份纪要。</p>
          <button
            onClick={() => nav('/console/meeting/new')}
            className="rd-btn rd-btn-primary"
          >
            <Plus size={14} /> 新建会议
          </button>
        </GlowCard>
      ) : (
        <GlowCard style={{ padding: 0, overflow: 'hidden' }}>
          <table className="rd-table">
            <thead>
              <tr>
                <th>标题</th>
                <th>关联项目</th>
                <th>状态</th>
                <th>创建时间</th>
                <th style={{ width: 60, textAlign: 'right' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--rd-text-3)', fontSize: 12.5 }}>
                    没有匹配「{keyword || (statusFilter && STATUS_LABEL[statusFilter])}」的会议
                  </td>
                </tr>
              ) : filtered.map(m => (
                <tr key={m.id}>
                  <td>
                    <button
                      onClick={() => nav(`/console/meeting/${m.id}`)}
                      style={{
                        background: 'transparent', border: 'none', padding: 0,
                        textAlign: 'left', fontSize: 13, fontWeight: 500,
                        color: 'var(--rd-text)', cursor: 'pointer',
                        fontFamily: 'inherit',
                      }}
                      onMouseEnter={e => e.currentTarget.style.color = 'var(--rd-accent-2)'}
                      onMouseLeave={e => e.currentTarget.style.color = 'var(--rd-text)'}
                    >
                      {m.title || '(未命名)'}
                    </button>
                  </td>
                  <td>
                    {m.project_name ? (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5, color: 'var(--rd-text-2)' }}>
                        <FolderKanban size={12} color="var(--rd-text-3)" />
                        {m.project_name}
                      </span>
                    ) : (
                      <span style={{ fontSize: 12, color: 'var(--rd-text-3)' }}>未关联</span>
                    )}
                  </td>
                  <td><StatusBadge status={m.status} /></td>
                  <td>
                    <span className="rd-mono" style={{ fontSize: 12, color: 'var(--rd-text-3)' }}>
                      {formatTime(m.created_at)}
                    </span>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div className="rd-row-actions" style={{ display: 'inline-flex', justifyContent: 'flex-end' }}>
                      <button
                        onClick={() => handleDelete(m)}
                        className="rd-icon-btn"
                        style={{ width: 28, height: 28 }}
                        title="删除"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlowCard>
      )}
    </div>
  )
}
