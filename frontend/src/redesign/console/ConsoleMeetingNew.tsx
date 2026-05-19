/**
 * NewConsoleMeetingNew — 新建会议(Liquid Glass)
 *
 * 功能 100% 等价于生产 `frontend/src/pages/console/ConsoleMeetingNew.tsx`:
 *   - 两种 mode: upload(音频) / text(粘贴)
 *   - 标题 + 关联项目(可选,listProjects 下拉)
 *   - upload: uploadMeetingAudio
 *   - text:   createMeetingFromText
 *   - 成功跳 /console/meeting/:id
 *   - 失败显示 error
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Upload, Type, ChevronLeft, Loader2, AlertCircle } from 'lucide-react'
import {
  uploadMeetingAudio,
  createMeetingFromText,
  listProjects,
  type Project,
} from '../../api/client'
import GlowCard from '../components/GlowCard'

type Mode = 'upload' | 'text'

export default function NewConsoleMeetingNew() {
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
    <div className="rd-page" style={{ maxWidth: 800 }}>
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

      {/* Hero */}
      <div className="rd-stagger" style={{ marginBottom: 26 }}>
        <h1 style={{
          fontSize: 28, fontWeight: 800, color: 'var(--rd-text)',
          letterSpacing: '-0.025em', lineHeight: 1.1, margin: 0, marginBottom: 6,
        }}>新建会议</h1>
        <p style={{ fontSize: 13.5, color: 'var(--rd-text-2)', margin: 0, maxWidth: 580, lineHeight: 1.6 }}>
          上传录音(自动转写)或直接粘贴会议文本,系统会生成纪要、待办、需求和干系人图谱。
        </p>
      </div>

      {/* Mode tabs(pill switch) */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 22 }}>
        {([
          { v: 'upload' as const, label: '上传录音', Icon: Upload },
          { v: 'text' as const,   label: '粘贴文本', Icon: Type },
        ]).map(t => {
          const active = mode === t.v
          return (
            <button
              key={t.v}
              onClick={() => { setMode(t.v); setError(null) }}
              className={`rd-chip${active ? ' is-active' : ''}`}
              style={{ padding: '8px 14px', fontSize: 12.5 }}
            >
              <t.Icon size={13} /> {t.label}
            </button>
          )
        })}
      </div>

      <GlowCard style={{ padding: 24 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {/* 标题 */}
          <div>
            <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: 'var(--rd-text)', marginBottom: 8 }}>
              会议标题
            </label>
            <input
              className="rd-input"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder={mode === 'upload' ? '默认使用音频文件名' : '默认按时间生成'}
            />
          </div>

          {/* 关联项目 */}
          <div>
            <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: 'var(--rd-text)', marginBottom: 8 }}>
              关联项目(可选)
            </label>
            <select
              className="rd-input"
              value={projectId}
              onChange={e => setProjectId(e.target.value)}
              style={{
                cursor: 'pointer',
                appearance: 'none',
                backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%235C6273' stroke-width='2.5'><polyline points='6 9 12 15 18 9'/></svg>")`,
                backgroundRepeat: 'no-repeat',
                backgroundPosition: 'right 14px center',
                paddingRight: 36,
              }}
            >
              <option value="">(不关联,后续也可在详情页修改)</option>
              {(projects || []).map((p: Project) => (
                <option key={p.id} value={p.id}>
                  {p.name}{p.customer ? ` · ${p.customer}` : ''}
                </option>
              ))}
            </select>
            <p style={{ fontSize: 11, color: 'var(--rd-text-3)', margin: '8px 0 0' }}>
              关联项目后,纪要可一键同步到 KB,干系人可叠加到项目的干系人图谱里。
            </p>
          </div>

          {/* Mode-specific content */}
          {mode === 'upload' ? (
            <div>
              <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: 'var(--rd-text)', marginBottom: 8 }}>
                音频文件
              </label>
              <div style={{
                padding: 20,
                border: '1.5px dashed var(--rd-line-strong)',
                borderRadius: 12,
                background: 'rgba(15, 18, 36, .02)',
                textAlign: 'center',
              }}>
                <input
                  type="file"
                  accept="audio/*,video/*"
                  onChange={e => setFile(e.target.files?.[0] ?? null)}
                  style={{
                    fontSize: 13,
                    fontFamily: 'inherit',
                    color: 'var(--rd-text-2)',
                  }}
                />
                {file && (
                  <p style={{ fontSize: 12, color: 'var(--rd-accent-2)', margin: '10px 0 0', fontWeight: 500 }}>
                    已选:{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                )}
              </div>
              <p style={{ fontSize: 11, color: 'var(--rd-text-3)', margin: '8px 0 0' }}>
                支持 wav / mp3 / m4a / webm 等。50 MB 以内。上传后会异步走 xiaomi ASR 转写,完成后自动跑 AI pipeline。
              </p>
            </div>
          ) : (
            <div>
              <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: 'var(--rd-text)', marginBottom: 8 }}>
                会议文本
              </label>
              <textarea
                className="rd-input"
                value={transcript}
                onChange={e => setTranscript(e.target.value)}
                placeholder="粘贴或输入会议转写内容…"
                rows={12}
                style={{ fontFamily: 'ui-monospace, monospace', resize: 'vertical', lineHeight: 1.6 }}
              />
              <p style={{ fontSize: 11, color: 'var(--rd-text-3)', margin: '8px 0 0' }}>
                提交后立即触发 AI 流水线(润色 / 纪要 / 需求 / 干系人)。一般 30 秒到 2 分钟出结果。
              </p>
            </div>
          )}

          {error && (
            <div style={{
              display: 'flex', alignItems: 'flex-start', gap: 8,
              padding: '10px 14px',
              borderRadius: 10,
              background: 'rgba(220, 38, 38, .08)',
              border: '1px solid rgba(220, 38, 38, .25)',
              color: '#FB7185',
              fontSize: 12.5,
            }}>
              <AlertCircle size={14} style={{ flexShrink: 0, marginTop: 2 }} />
              {error}
            </div>
          )}

          {/* 提交按钮 */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, paddingTop: 6 }}>
            <button
              onClick={() => nav('/console/meeting')}
              disabled={submitting}
              className="rd-btn"
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
              className="rd-btn rd-btn-primary"
            >
              {submitting && <Loader2 size={13} className="animate-spin" />}
              {mode === 'upload' ? '上传并转写' : '提交并生成'}
            </button>
          </div>
        </div>
      </GlowCard>
    </div>
  )
}
