import { useEffect, useState } from 'react'
import {
  ApiError,
  addApplicationQuestion,
  createApplicationPreparation,
  generateApplicationPreparation,
  getApplicationPreparation,
  getResume,
  listApplicationPreparations,
  updateApplicationAnswer,
} from '../api'
import { useAsync } from '../hooks/useAsync'
import type { ApplicationAnswer, ApplicationPreparationDetail, QuestionCategory, QuestionType } from '../types'

interface Props {
  jobId: string
}

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Something went wrong.'
}

const QUESTION_TYPES: QuestionType[] = ['text', 'textarea', 'number', 'boolean', 'single_select', 'multi_select', 'date']
const QUESTION_CATEGORIES: QuestionCategory[] = [
  'identity', 'contact', 'work_authorization', 'sponsorship', 'location', 'relocation',
  'availability', 'salary', 'education', 'experience', 'skills',
  'company_motivation', 'role_motivation', 'behavioral', 'demographic_optional', 'other',
]

type Section = 'Personal Details' | 'Work Authorization' | 'Logistics' | 'Job Questions'

function sectionForCategory(category: QuestionCategory): Section {
  if (['identity', 'contact', 'location', 'education'].includes(category)) return 'Personal Details'
  if (['work_authorization', 'sponsorship'].includes(category)) return 'Work Authorization'
  if (['relocation', 'availability', 'salary'].includes(category)) return 'Logistics'
  return 'Job Questions'
}

const SECTION_ORDER: Section[] = ['Personal Details', 'Work Authorization', 'Logistics', 'Job Questions']

function sourceLabel(answer: ApplicationAnswer): string {
  if (answer.answer_source === 'generated_from_evidence' && answer.evidence_ids.length > 0) {
    return `Evidence: ${answer.evidence_ids.join(', ')}`
  }
  switch (answer.answer_source) {
    case 'applicant_profile':
      return 'Applicant profile'
    case 'master_resume':
      return 'Master resume'
    case 'approved_resume':
      return 'Approved resume'
    case 'generated_from_evidence':
      return 'Generated from evidence'
    case 'user_edited':
      return 'Edited by you'
    default:
      return 'Needs your input'
  }
}

function AnswerRow({ answer, onSaved }: { answer: ApplicationAnswer; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(answer.answer ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await updateApplicationAnswer(answer.id, draft)
      setEditing(false)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`app-question ${answer.needs_user_input ? 'app-question--needs-input' : ''}`}>
      <div className="app-question__text">
        {answer.needs_user_input ? '⚠ ' : '✓ '}
        {answer.question_text}
        {!answer.required && <span className="app-question__optional"> (optional)</span>}
      </div>

      {editing ? (
        <div className="app-question__edit">
          {answer.question_type === 'textarea' ? (
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={4} />
          ) : (
            <input type="text" value={draft} onChange={(e) => setDraft(e.target.value)} />
          )}
          <div className="app-question__edit-actions">
            <button type="button" className="btn btn--primary btn--small" disabled={saving} onClick={save}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="btn btn--ghost btn--small" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          {error && <div className="job-card__error">{error}</div>}
        </div>
      ) : answer.needs_user_input ? (
        <div className="app-question__body">
          <p className="app-question__hint">Needs your input.</p>
          <button type="button" className="btn btn--secondary btn--small" onClick={() => setEditing(true)}>
            Answer
          </button>
        </div>
      ) : (
        <div className="app-question__body">
          <p className="app-question__answer">{answer.answer}</p>
          <div className="app-question__meta">
            <span className="app-question__source">Source: {sourceLabel(answer)}</span>
            <button type="button" className="btn btn--ghost btn--small" onClick={() => setEditing(true)}>
              Edit
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function AddQuestionForm({ preparationId, onAdded }: { preparationId: number; onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [type, setType] = useState<QuestionType>('text')
  const [category, setCategory] = useState<QuestionCategory>('other')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!text.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await addApplicationQuestion(preparationId, { question_text: text, question_type: type, category })
      setText('')
      setOpen(false)
      onAdded()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) {
    return (
      <button type="button" className="btn btn--secondary btn--small" onClick={() => setOpen(true)}>
        + Add Question
      </button>
    )
  }

  return (
    <div className="app-add-question">
      <input type="text" placeholder="Question text" value={text} onChange={(e) => setText(e.target.value)} />
      <select value={type} onChange={(e) => setType(e.target.value as QuestionType)}>
        {QUESTION_TYPES.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>
      <select value={category} onChange={(e) => setCategory(e.target.value as QuestionCategory)}>
        {QUESTION_CATEGORIES.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
      <div className="app-add-question__actions">
        <button type="button" className="btn btn--primary btn--small" disabled={submitting} onClick={submit}>
          {submitting ? 'Adding…' : 'Add'}
        </button>
        <button type="button" className="btn btn--ghost btn--small" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error && <div className="job-card__error">{error}</div>}
    </div>
  )
}

function ResumeBadge({ resumeVersionId }: { resumeVersionId: number | null }) {
  const { data } = useAsync(
    () => (resumeVersionId !== null ? getResume(resumeVersionId) : Promise.resolve(null)),
    [resumeVersionId],
  )
  if (resumeVersionId === null) return <p className="app-question__hint">No resume selected.</p>
  if (!data) return null
  return (
    <p className="app-resume-badge">
      ✓ v{data.version} {data.status}
    </p>
  )
}

export function ApplicationPreparation({ jobId }: Props) {
  const { data: preparations, loading, error, reload } = useAsync(() => listApplicationPreparations(jobId), [jobId])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<ApplicationPreparationDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (preparations && preparations.length > 0 && selectedId === null) {
      setSelectedId(preparations[0].id)
    }
  }, [preparations, selectedId])

  async function refreshDetail(id: number) {
    setDetailLoading(true)
    try {
      const data = await getApplicationPreparation(id)
      setDetail(data)
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setDetailLoading(false)
    }
  }

  useEffect(() => {
    if (selectedId !== null) refreshDetail(selectedId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  async function handlePrepare() {
    setBusy(true)
    setActionError(null)
    try {
      const created = await createApplicationPreparation(jobId)
      await generateApplicationPreparation(created.id)
      await reload()
      setSelectedId(created.id)
      await refreshDetail(created.id)
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function handleRegenerate() {
    if (selectedId === null) return
    setBusy(true)
    setActionError(null)
    try {
      await generateApplicationPreparation(selectedId)
      await refreshDetail(selectedId)
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <div className="state state-loading">Loading application preparation…</div>
  if (error) {
    return (
      <div className="state state-error">
        <strong>Couldn't load application preparation.</strong>
        <span>{error}</span>
      </div>
    )
  }

  if (!preparations || preparations.length === 0) {
    return (
      <div className="app-prep app-prep--empty">
        <p>No preparation yet.</p>
        <button type="button" className="btn btn--primary" disabled={busy} onClick={handlePrepare}>
          {busy ? 'Preparing…' : 'Prepare Application'}
        </button>
        {actionError && <div className="job-card__error">{actionError}</div>}
      </div>
    )
  }

  const readyCount = detail ? detail.answers.filter((a) => !a.needs_user_input).length : 0
  const totalCount = detail ? detail.answers.length : 0

  const grouped: Record<Section, ApplicationAnswer[]> = {
    'Personal Details': [], 'Work Authorization': [], 'Logistics': [], 'Job Questions': [],
  }
  detail?.answers.forEach((a) => grouped[sectionForCategory(a.category)].push(a))

  return (
    <div className="app-prep">
      {actionError && <div className="job-card__error">{actionError}</div>}

      <div className="app-prep__header">
        <span className={`app-prep__status app-prep__status--${detail?.status ?? 'draft'}`}>
          {detail?.status ?? 'draft'}
        </span>
        <span className="app-prep__ready-count">Ready: {readyCount} / {totalCount}</span>
        <div className="app-prep__header-actions">
          <button type="button" className="btn btn--secondary btn--small" disabled={busy} onClick={handleRegenerate}>
            {busy ? 'Regenerating…' : 'Regenerate'}
          </button>
        </div>
      </div>

      <section className="page-section">
        <h3>Resume</h3>
        <ResumeBadge resumeVersionId={detail?.resume_version_id ?? null} />
      </section>

      {detailLoading ? (
        <div className="state state-loading">Loading…</div>
      ) : (
        SECTION_ORDER.map((section) =>
          grouped[section].length === 0 ? null : (
            <section className="page-section" key={section}>
              <h3>{section}</h3>
              {grouped[section].map((answer) => (
                <AnswerRow key={answer.id} answer={answer} onSaved={() => selectedId !== null && refreshDetail(selectedId)} />
              ))}
            </section>
          ),
        )
      )}

      <section className="page-section">
        {selectedId !== null && (
          <AddQuestionForm preparationId={selectedId} onAdded={() => selectedId !== null && refreshDetail(selectedId)} />
        )}
      </section>
    </div>
  )
}
