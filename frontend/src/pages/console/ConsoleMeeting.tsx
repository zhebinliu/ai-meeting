/**
 * ConsoleMeeting — 会议纪要列表(meeting-ai 整合后,2026-05-11)
 *
 * 替代原 iframe 嵌入。展示当前用户的会议列表 + 新建入口 + 状态徽标 + 删除。
 * 状态机:recording / processing / completed / failed
 * 自动刷新:存在 processing 状态时 8s 轮询一次。
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import {
  Mic, Plus, Trash2, FolderKanban, CheckCircle2, Loader2, AlertCircle, Clock, Search,
} from 'lucide-react'
import { listMeetings, deleteMeeting, type Meeting, type MeetingStatus } from '../../api/client'

const BRAND_GRAD = 'linear-gradient(135deg,#FF8D1A,#D96400)'

const STATUS_LABEL: Record<MeetingStatus, string> = {
  recording: '录制中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
}

function StatusBadge({ status }: { status: MeetingStatus }) {
  const cfg = {
    recording:  { cls: 'bg-amber-50 border-amber-200 text-amber-700',     Icon: Mic },
    processing: { cls: 'bg-blue-50 border-blue-200 text-blue-700',         Icon: Loader2 },
    completed:  { cls: 'bg-emerald-50 border-emerald-200 text-emerald-700', Icon: CheckCircle2 },
    failed:     { cls: 'bg-rose-50 border-rose-200 text-rose-700',          Icon: AlertCircle },
  }[status] ?? { cls: 'bg-gray-50 border-line text-ink-muted', Icon: Clock }
  const Icon = cfg.Icon
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border ${cfg.cls}`}>
      <Icon size={11} className={status === 'processing' ? 'animate-spin' : ''} />
      {STATUS_LABEL[status] || status}
    </span>
  )
}

function formatTime(iso: string | null | undefined) {
  if (!iso) return '-'
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export default function ConsoleMeeting() {
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
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Hero */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-extrabold text-ink leading-tight">会议纪要</h1>
          <p className="text-sm text-ink-secondary mt-1">
            上传录音 / 粘贴文本,AI 自动提取纪要、待办、需求清单和干系人图谱。
          </p>
        </div>
        <button
          onClick={() => nav('/console/meeting/new')}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-white text-sm font-medium shadow-sm hover:opacity-90"
          style={{ background: BRAND_GRAD }}
        >
          <Plus size={16} /> 新建会议
        </button>
      </div>

      {/* Search + filter bar */}
      {meetings && meetings.length > 0 && (
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <div className="relative flex-1 min-w-[200px] max-w-md">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted" />
            <input
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              placeholder="搜标题 / 项目名"
              className="w-full text-sm border border-line rounded-md pl-7 pr-3 py-1.5 bg-white focus:outline-none focus:border-orange-300"
            />
          </div>
          <div className="flex gap-1">
            {(['', 'processing', 'completed', 'failed', 'recording'] as const).map(s => {
              const count = s === '' ? (meetings.length) : (statusCounts[s] || 0)
              if (s !== '' && count === 0) return null
              return (
                <button
                  key={s || 'all'}
                  onClick={() => setStatusFilter(s)}
                  className={`px-2.5 py-1.5 rounded-md text-[12px] font-medium border transition-colors ${
                    statusFilter === s
                      ? 'border-orange-300 text-orange-700 bg-orange-50'
                      : 'border-line text-ink-muted hover:text-ink bg-white hover:bg-canvas/60'
                  }`}
                >
                  {s === '' ? '全部' : STATUS_LABEL[s as MeetingStatus]}
                  <span className="ml-1 tabular-nums text-ink-muted">{count}</span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* List */}
      {isLoading ? (
        <div className="text-center py-16 text-ink-muted">
          <Loader2 size={20} className="animate-spin inline mr-2" /> 加载中…
        </div>
      ) : !meetings || meetings.length === 0 ? (
        <div className="rounded-2xl border border-line bg-canvas-elevated p-12 text-center">
          <Mic size={32} className="mx-auto text-ink-muted mb-3" />
          <p className="text-ink font-medium mb-1">还没有会议记录</p>
          <p className="text-sm text-ink-muted mb-4">点击右上角「新建会议」开始第一份纪要。</p>
          <button
            onClick={() => nav('/console/meeting/new')}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-white text-sm font-medium"
            style={{ background: BRAND_GRAD }}
          >
            <Plus size={16} /> 新建会议
          </button>
        </div>
      ) : (
        <div className="rounded-2xl border border-line bg-canvas-elevated overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-canvas border-b border-line text-ink-muted">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium">标题</th>
                <th className="text-left px-4 py-2.5 font-medium">关联项目</th>
                <th className="text-left px-4 py-2.5 font-medium">状态</th>
                <th className="text-left px-4 py-2.5 font-medium">创建时间</th>
                <th className="text-right px-4 py-2.5 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-[12px] text-ink-muted">
                    没有匹配「{keyword || statusFilter}」的会议
                  </td>
                </tr>
              )}
              {filtered.map(m => (
                <tr key={m.id} className="border-b border-line last:border-0 hover:bg-canvas/50">
                  <td className="px-4 py-3">
                    <button
                      onClick={() => nav(`/console/meeting/${m.id}`)}
                      className="text-ink hover:text-brand font-medium text-left"
                    >
                      {m.title || '(未命名)'}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-ink-secondary">
                    {m.project_name ? (
                      <span className="inline-flex items-center gap-1.5">
                        <FolderKanban size={13} className="text-ink-muted" />
                        {m.project_name}
                      </span>
                    ) : (
                      <span className="text-ink-muted text-[12px]">未关联</span>
                    )}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={m.status} /></td>
                  <td className="px-4 py-3 text-ink-muted text-[12px]">{formatTime(m.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleDelete(m)}
                      className="text-ink-muted hover:text-rose-600 p-1"
                      title="删除"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
