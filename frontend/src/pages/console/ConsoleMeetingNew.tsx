/**
 * ConsoleMeetingNew — 新建会议(2026-05-11)
 *
 * 提供两种入口:
 *  - upload:上传音频文件 → MinIO → xiaomi ASR → AI pipeline
 *  - text:粘贴/输入文本 → 直接走 AI pipeline(跳 ASR)
 *
 * 录音(WS 实时流)在 Block D 已用户拍板延期。
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Upload, Type, ChevronLeft, Loader2 } from 'lucide-react'
import {
  uploadMeetingAudio,
  createMeetingFromText,
  listProjects,
  type Project,
} from '../../api/client'

const BRAND_GRAD = 'linear-gradient(135deg,#FF8D1A,#D96400)'
type Mode = 'upload' | 'text'

export default function ConsoleMeetingNew() {
  const nav = useNavigate()
  const [mode, setMode] = useState<Mode>('upload')
  const [title, setTitle] = useState('')
  const [projectId, setProjectId] = useState<string>('')
  const [file, setFile] = useState<File | null>(null)
  const [transcript, setTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)

  const { data: projects } = useQuery({ queryKey: ['projects'], queryFn: () => listProjects() })

  const uploadMut = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('请选择音频文件')
      return uploadMeetingAudio(file, {
        title: title || file.name,
        project_id: projectId || null,
      })
    },
    onSuccess: (res) => nav(`/console/meeting/${res.meeting_id}`),
    onError: (e: Error) => setError(e?.message || '上传失败'),
  })

  const textMut = useMutation({
    mutationFn: () => {
      if (!transcript.trim()) throw new Error('请输入文本')
      return createMeetingFromText({
        title: title || '文本会议 ' + new Date().toLocaleString(),
        transcript: transcript.trim(),
        project_id: projectId || null,
      })
    },
    onSuccess: (m) => nav(`/console/meeting/${m.id}`),
    onError: (e: Error) => setError(e?.message || '创建失败'),
  })

  const submitting = uploadMut.isPending || textMut.isPending

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <button
        onClick={() => nav('/console/meeting')}
        className="inline-flex items-center gap-1 text-ink-muted hover:text-ink text-sm mb-4"
      >
        <ChevronLeft size={16} /> 返回列表
      </button>

      <h1 className="text-2xl font-extrabold text-ink mb-1">新建会议</h1>
      <p className="text-sm text-ink-secondary mb-6">
        上传录音(自动转写)或直接粘贴会议文本,系统会生成纪要、待办、需求和干系人图谱。
      </p>

      {/* Mode tabs */}
      <div className="flex border-b border-line mb-6">
        {([
          { v: 'upload' as const, label: '上传录音', Icon: Upload },
          { v: 'text' as const, label: '粘贴文本', Icon: Type },
        ]).map(t => (
          <button
            key={t.v}
            onClick={() => { setMode(t.v); setError(null) }}
            className={`px-4 py-2.5 text-sm font-medium flex items-center gap-2 border-b-2 -mb-px ${
              mode === t.v
                ? 'border-brand text-brand'
                : 'border-transparent text-ink-muted hover:text-ink'
            }`}
          >
            <t.Icon size={14} /> {t.label}
          </button>
        ))}
      </div>

      <div className="space-y-4">
        {/* 标题 */}
        <div>
          <label className="block text-sm font-medium text-ink mb-1.5">会议标题</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={mode === 'upload' ? '默认使用音频文件名' : '默认按时间生成'}
            className="w-full px-3 py-2 rounded-lg border border-line text-sm focus:outline-none focus:border-brand"
          />
        </div>

        {/* 关联项目 */}
        <div>
          <label className="block text-sm font-medium text-ink mb-1.5">关联项目(可选)</label>
          <select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-line text-sm bg-white focus:outline-none focus:border-brand"
          >
            <option value="">(不关联,后续也可在详情页修改)</option>
            {(projects || []).map((p: Project) => (
              <option key={p.id} value={p.id}>
                {p.name}{p.customer ? ` · ${p.customer}` : ''}
              </option>
            ))}
          </select>
          <p className="text-[11px] text-ink-muted mt-1">
            关联项目后,纪要可一键同步到 KB,干系人可叠加到项目的干系人图谱里。
          </p>
        </div>

        {/* Mode-specific content */}
        {mode === 'upload' ? (
          <div>
            <label className="block text-sm font-medium text-ink mb-1.5">音频文件</label>
            <input
              type="file"
              accept="audio/*,video/*"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="w-full text-sm file:mr-3 file:px-3 file:py-1.5 file:rounded-md file:border file:border-line file:bg-canvas file:text-ink hover:file:bg-canvas-elevated"
            />
            <p className="text-[11px] text-ink-muted mt-1">
              支持 wav / mp3 / m4a / webm 等。50 MB 以内。上传后会异步走 xiaomi ASR 转写,完成后自动跑 AI pipeline。
            </p>
          </div>
        ) : (
          <div>
            <label className="block text-sm font-medium text-ink mb-1.5">会议文本</label>
            <textarea
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              placeholder="粘贴或输入会议转写内容…"
              rows={12}
              className="w-full px-3 py-2 rounded-lg border border-line text-sm font-mono focus:outline-none focus:border-brand resize-y"
            />
            <p className="text-[11px] text-ink-muted mt-1">
              提交后立即触发 AI 流水线(润色 / 纪要 / 需求 / 干系人)。一般 30 秒到 2 分钟出结果。
            </p>
          </div>
        )}

        {error && (
          <div className="rounded-md border border-rose-200 bg-rose-50 text-rose-700 text-sm px-3 py-2">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-3 pt-2">
          <button
            onClick={() => nav('/console/meeting')}
            disabled={submitting}
            className="px-4 py-2 rounded-lg border border-line text-sm text-ink hover:bg-canvas disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={() => {
              setError(null)
              if (mode === 'upload') uploadMut.mutate()
              else textMut.mutate()
            }}
            disabled={submitting || (mode === 'upload' ? !file : !transcript.trim())}
            className="px-4 py-2 rounded-lg text-white text-sm font-medium disabled:opacity-50 inline-flex items-center gap-2"
            style={{ background: BRAND_GRAD }}
          >
            {submitting && <Loader2 size={14} className="animate-spin" />}
            {mode === 'upload' ? '上传并转写' : '提交并生成'}
          </button>
        </div>
      </div>
    </div>
  )
}
