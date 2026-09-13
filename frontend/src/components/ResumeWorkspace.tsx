import { useEffect, useState } from 'react'
import {
  ApiError,
  approveResume,
  generateResume,
  getResume,
  getResumeLatex,
  listJobResumes,
  resumePdfUrl,
} from '../api'
import { useAsync } from '../hooks/useAsync'
import { formatDate } from '../format'
import type { ResumeVersionDetail } from '../types'

interface Props {
  jobId: string
}

type Tab = 'preview' | 'latex' | 'changes' | 'versions'

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Something went wrong.'
}

function statusLabel(status: string): string {
  return status[0].toUpperCase() + status.slice(1)
}

function downloadTextFile(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export function ResumeWorkspace({ jobId }: Props) {
  const { data: versions, loading: versionsLoading, error: versionsError, reload: reloadVersions } = useAsync(
    () => listJobResumes(jobId),
    [jobId],
  )

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [tab, setTab] = useState<Tab>('preview')
  const [generating, setGenerating] = useState(false)
  const [approving, setApproving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [latexText, setLatexText] = useState<string | null>(null)
  const [latexForId, setLatexForId] = useState<number | null>(null)
  const [latexLoading, setLatexLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  // Default to the newest version once the list has loaded (versions come
  // back newest-first from the API).
  useEffect(() => {
    if (versions && versions.length > 0 && selectedId === null) {
      setSelectedId(versions[0].id)
    }
  }, [versions, selectedId])

  const {
    data: detail,
    loading: detailLoading,
    reload: reloadDetail,
  } = useAsync<ResumeVersionDetail | null>(
    () => (selectedId !== null ? getResume(selectedId) : Promise.resolve(null)),
    [selectedId],
  )

  useEffect(() => {
    if (tab !== 'latex' || selectedId === null || latexForId === selectedId) return
    setLatexLoading(true)
    getResumeLatex(selectedId)
      .then((res) => {
        setLatexText(res.latex_source)
        setLatexForId(selectedId)
      })
      .catch((err) => setActionError(errorMessage(err)))
      .finally(() => setLatexLoading(false))
  }, [tab, selectedId, latexForId])

  async function handleGenerate() {
    setGenerating(true)
    setActionError(null)
    try {
      const created = await generateResume(jobId)
      await reloadVersions()
      setSelectedId(created.id)
      setLatexForId(null)
      setTab('preview')
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setGenerating(false)
    }
  }

  async function handleApprove() {
    if (selectedId === null) return
    setApproving(true)
    setActionError(null)
    try {
      await approveResume(selectedId)
      await Promise.all([reloadVersions(), reloadDetail()])
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setApproving(false)
    }
  }

  async function handleDownloadTex() {
    if (selectedId === null || !detail) return
    const source = latexForId === selectedId && latexText ? latexText : (await getResumeLatex(selectedId)).latex_source
    downloadTextFile(`resume-v${detail.version}.tex`, source, 'application/x-tex')
  }

  async function handleCopyLatex() {
    if (selectedId === null) return
    const source = latexForId === selectedId && latexText ? latexText : (await getResumeLatex(selectedId)).latex_source
    await navigator.clipboard.writeText(source)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (versionsLoading) {
    return <div className="state state-loading">Loading resume versions…</div>
  }
  if (versionsError) {
    return (
      <div className="state state-error">
        <strong>Couldn't load resume versions.</strong>
        <span>{versionsError}</span>
      </div>
    )
  }

  if (!versions || versions.length === 0) {
    return (
      <div className="resume-workspace resume-workspace--empty">
        <p>No resume generated yet.</p>
        <button type="button" className="btn btn--primary" disabled={generating} onClick={handleGenerate}>
          {generating ? 'Generating…' : 'Generate Resume'}
        </button>
        {actionError && <div className="job-card__error">{actionError}</div>}
      </div>
    )
  }

  return (
    <div className="resume-workspace">
      <div className="resume-tabs">
        {(['preview', 'latex', 'changes', 'versions'] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            className={t === tab ? 'resume-tab resume-tab--active' : 'resume-tab'}
            onClick={() => setTab(t)}
          >
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {actionError && <div className="job-card__error">{actionError}</div>}

      {detailLoading || !detail ? (
        <div className="state state-loading">Loading version…</div>
      ) : (
        <>
          <div className="resume-version-bar">
            <span>
              Version {detail.version} · <span className={`resume-status resume-status--${detail.status}`}>{statusLabel(detail.status)}</span>
            </span>
            {detail.page_count != null && <span className="resume-page-count">Compiled to {detail.page_count} page{detail.page_count === 1 ? '' : 's'}.</span>}
            <div className="resume-version-bar__actions">
              <button type="button" className="btn btn--secondary btn--small" disabled={generating} onClick={handleGenerate}>
                {generating ? 'Regenerating…' : 'Regenerate'}
              </button>
              <button
                type="button"
                className="btn btn--primary btn--small"
                disabled={approving || detail.status === 'approved'}
                onClick={handleApprove}
              >
                {detail.status === 'approved' ? 'Approved' : approving ? 'Approving…' : 'Approve'}
              </button>
            </div>
          </div>

          {tab === 'preview' && (
            <div className="resume-preview">
              {detail.compiler_status === 'compiled' && (
                <>
                  <iframe title="Resume PDF preview" src={resumePdfUrl(detail.id)} className="resume-pdf-frame" />
                  <div className="resume-preview__actions">
                    <a className="btn btn--secondary" href={resumePdfUrl(detail.id)} target="_blank" rel="noreferrer noopener">
                      Download PDF
                    </a>
                    <button type="button" className="btn btn--secondary" onClick={handleDownloadTex}>
                      Download .tex
                    </button>
                  </div>
                </>
              )}
              {detail.compiler_status === 'unavailable' && (
                <div className="state state-empty">
                  No local LaTeX compiler was found, so this version couldn't be compiled to a PDF. The LaTeX
                  source is still available on the LaTeX tab — paste it into Overleaf, or install a compiler
                  locally (see the README) and regenerate.
                  <div className="resume-preview__actions">
                    <button type="button" className="btn btn--secondary" onClick={handleDownloadTex}>
                      Download .tex
                    </button>
                  </div>
                </div>
              )}
              {detail.compiler_status === 'failed' && (
                <div className="state state-error">
                  <strong>LaTeX compilation failed for this version.</strong>
                  {detail.compile_log && <pre className="resume-log">{detail.compile_log}</pre>}
                  <div className="resume-preview__actions">
                    <button type="button" className="btn btn--secondary" onClick={handleDownloadTex}>
                      Download .tex
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === 'latex' && (
            <div className="resume-latex">
              <div className="resume-latex__actions">
                <button type="button" className="btn btn--secondary btn--small" onClick={handleCopyLatex}>
                  {copied ? 'Copied!' : 'Copy LaTeX'}
                </button>
                <button type="button" className="btn btn--secondary btn--small" onClick={handleDownloadTex}>
                  Download .tex
                </button>
              </div>
              {latexLoading ? (
                <div className="state state-loading">Loading LaTeX source…</div>
              ) : (
                <pre className="resume-code">{latexText}</pre>
              )}
            </div>
          )}

          {tab === 'changes' && (
            <div className="resume-changes">
              <section>
                <h3>Strong matches</h3>
                <p className="page-section__hint">Skills the job description asks for that your experience directly demonstrates.</p>
                <TagList items={detail.tailoring_analysis.strong_matches} tone="accent" empty="No strong keyword matches found." />
              </section>
              <section>
                <h3>Supported, but underemphasized</h3>
                <p className="page-section__hint">Skills you have, but no bullet in your resume calls out explicitly.</p>
                <TagList items={detail.tailoring_analysis.supported_but_underemphasized} empty="None." />
              </section>
              <section>
                <h3>Not added — unsupported by your resume</h3>
                <p className="page-section__hint">
                  The job description mentions these, but nothing in your master resume supports them, so they
                  were not added to this tailored resume.
                </p>
                <TagList items={detail.tailoring_analysis.unsupported_requirements} tone="muted" empty="Nothing unsupported — good match." />
              </section>
              {detail.tailoring_analysis.selected_experience.length > 0 && (
                <section>
                  <h3>Experience emphasized for this role</h3>
                  <p className="page-section__hint">
                    All of your experience is included — these entries had the strongest keyword matches for this
                    job, so their most relevant bullets were moved to the top.
                  </p>
                  <TagList items={detail.tailoring_analysis.selected_experience} empty="" />
                </section>
              )}
            </div>
          )}

          {tab === 'versions' && (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Compiler</th>
                    <th>Created</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {versions.map((v) => (
                    <tr key={v.id}>
                      <td>v{v.version}</td>
                      <td>
                        <span className={`resume-status resume-status--${v.status}`}>{statusLabel(v.status)}</span>
                      </td>
                      <td>{v.compiler_status}</td>
                      <td>{formatDate(v.created_at)}</td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--secondary btn--small"
                          onClick={() => {
                            setSelectedId(v.id)
                            setTab('preview')
                          }}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function TagList({ items, tone, empty }: { items: string[]; tone?: 'accent' | 'muted'; empty: string }) {
  if (items.length === 0) return <p className="resume-changes__empty">{empty}</p>
  return (
    <div className="job-card__skills">
      {items.map((item) => (
        <span key={item} className={tone === 'accent' ? 'skill-tag skill-tag--accent' : tone === 'muted' ? 'skill-tag skill-tag--muted' : 'skill-tag'}>
          {item}
        </span>
      ))}
    </div>
  )
}
