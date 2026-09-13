import { useEffect, useState } from 'react'
import {
  ApiError,
  approveResume,
  generateResume,
  getLLMStatus,
  getResume,
  getResumeLatex,
  listJobResumes,
  resumePdfUrl,
} from '../api'
import { useAsync } from '../hooks/useAsync'
import { formatDate } from '../format'
import type { ResumeGenerationMode, ResumeVersionDetail } from '../types'

interface Props {
  jobId: string
}

type Tab = 'preview' | 'latex' | 'changes' | 'ai-rewrites' | 'versions'

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Something went wrong.'
}

function statusLabel(status: string): string {
  return status[0].toUpperCase() + status.slice(1)
}

function modeLabel(mode: string): string {
  return mode === 'llm_enhanced' ? 'DGX Enhanced' : 'Safe / Deterministic'
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

/** Compact "DGX LLM: Connected / Model: x" or "DGX LLM: Offline" status,
 * fetched lazily — a DGX being offline must never block deterministic
 * generation or fail the rest of the page. */
function DgxStatusLine() {
  const { data: status, loading } = useAsync(getLLMStatus)
  if (loading || !status) return <span className="dgx-status dgx-status--loading">DGX LLM: checking…</span>
  if (!status.configured) return <span className="dgx-status dgx-status--offline">DGX LLM: not configured</span>
  if (!status.reachable) return <span className="dgx-status dgx-status--offline">DGX LLM: Offline</span>
  return (
    <span className="dgx-status dgx-status--online">
      DGX LLM: Connected {status.model && <>· Model: {status.model}</>}
    </span>
  )
}

export function ResumeWorkspace({ jobId }: Props) {
  const { data: versions, loading: versionsLoading, error: versionsError, reload: reloadVersions } = useAsync(
    () => listJobResumes(jobId),
    [jobId],
  )
  const { data: llmStatus } = useAsync(getLLMStatus)

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [tab, setTab] = useState<Tab>('preview')
  const [generatingMode, setGeneratingMode] = useState<ResumeGenerationMode | null>(null)
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

  async function handleGenerate(mode: ResumeGenerationMode) {
    setGeneratingMode(mode)
    setActionError(null)
    try {
      const created = await generateResume(jobId, mode)
      await reloadVersions()
      setSelectedId(created.id)
      setLatexForId(null)
      setTab('preview')
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setGeneratingMode(null)
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

  const dgxReachable = llmStatus?.configured && llmStatus?.reachable

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
        <div className="resume-generate-choice">
          <button
            type="button"
            className="btn btn--primary"
            disabled={generatingMode !== null}
            onClick={() => handleGenerate('deterministic')}
          >
            {generatingMode === 'deterministic' ? 'Generating…' : 'Safe / Deterministic'}
          </button>
          <button
            type="button"
            className="btn btn--secondary"
            disabled={generatingMode !== null || !dgxReachable}
            title={dgxReachable ? undefined : 'DGX LLM is not reachable'}
            onClick={() => handleGenerate('llm_enhanced')}
          >
            {generatingMode === 'llm_enhanced' ? 'Generating…' : 'DGX Enhanced'}
          </button>
        </div>
        <DgxStatusLine />
        {actionError && <div className="job-card__error">{actionError}</div>}
      </div>
    )
  }

  const tabs: Tab[] = ['preview', 'latex', 'changes', ...(detail?.generation_mode === 'llm_enhanced' ? (['ai-rewrites'] as Tab[]) : []), 'versions']

  return (
    <div className="resume-workspace">
      <div className="resume-tabs">
        {tabs.map((t) => (
          <button
            key={t}
            type="button"
            className={t === tab ? 'resume-tab resume-tab--active' : 'resume-tab'}
            onClick={() => setTab(t)}
          >
            {t === 'ai-rewrites' ? 'AI Rewrites' : t[0].toUpperCase() + t.slice(1)}
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
              {' · '}
              <span className="resume-mode-tag">{modeLabel(detail.generation_mode)}</span>
            </span>
            {detail.page_count != null && <span className="resume-page-count">Compiled to {detail.page_count} page{detail.page_count === 1 ? '' : 's'}.</span>}
            <div className="resume-version-bar__actions">
              <button
                type="button"
                className="btn btn--secondary btn--small"
                disabled={generatingMode !== null}
                onClick={() => handleGenerate('deterministic')}
              >
                {generatingMode === 'deterministic' ? 'Regenerating…' : 'Regenerate (Safe)'}
              </button>
              <button
                type="button"
                className="btn btn--secondary btn--small"
                disabled={generatingMode !== null || !dgxReachable}
                title={dgxReachable ? undefined : 'DGX LLM is not reachable'}
                onClick={() => handleGenerate('llm_enhanced')}
              >
                {generatingMode === 'llm_enhanced' ? 'Regenerating…' : 'Regenerate (DGX)'}
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
          <DgxStatusLine />

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

          {tab === 'ai-rewrites' && (
            <div className="ai-rewrites">
              {detail.rewrite_provenance.length === 0 ? (
                <p className="resume-changes__empty">No rewrites were attempted for this version.</p>
              ) : (
                detail.rewrite_provenance.map((attempt) => (
                  <div key={attempt.evidence_id} className="ai-rewrite-card">
                    <div className="ai-rewrite-card__evidence">Evidence: {attempt.evidence_id}</div>

                    <div className="ai-rewrite-card__block">
                      <div className="ai-rewrite-card__label">Original</div>
                      <p>{attempt.original_text}</p>
                    </div>

                    {attempt.rewritten_text && (
                      <div className="ai-rewrite-card__block">
                        <div className="ai-rewrite-card__label">{attempt.validation_status === 'accepted' ? 'Enhanced' : 'Enhanced attempt'}</div>
                        <p>{attempt.rewritten_text}</p>
                      </div>
                    )}

                    <div className="ai-rewrite-card__validation">
                      {attempt.validation_status === 'accepted' && <span className="ai-rewrite-validation ai-rewrite-validation--accepted">✓ Accepted</span>}
                      {attempt.validation_status === 'rejected' && (
                        <>
                          <span className="ai-rewrite-validation ai-rewrite-validation--rejected">✕ Rejected</span>
                          {attempt.validation_reasons.length > 0 && (
                            <div className="ai-rewrite-card__reasons">Reason: {attempt.validation_reasons.join('; ')}</div>
                          )}
                          <div className="ai-rewrite-card__fallback">Using original bullet instead.</div>
                        </>
                      )}
                      {attempt.validation_status === 'error' && (
                        <>
                          <span className="ai-rewrite-validation ai-rewrite-validation--rejected">✕ Rewrite failed</span>
                          {attempt.validation_reasons.length > 0 && (
                            <div className="ai-rewrite-card__reasons">{attempt.validation_reasons.join('; ')}</div>
                          )}
                          <div className="ai-rewrite-card__fallback">Using original bullet instead.</div>
                        </>
                      )}
                    </div>
                  </div>
                ))
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
                    <th>Mode</th>
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
                      <td>{modeLabel(v.generation_mode)}</td>
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
