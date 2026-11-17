import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  archiveKbDocument,
  createKbDocument,
  listKbDocuments,
  listPlans,
  publishKbDraft,
  readKbDocument,
  republishKbVersion,
  saveKbDraft,
  updateKbDocumentDetails,
  type AdminSession,
  type KbDocumentDetail,
  type KbDocumentItem,
  type PlanItem,
} from "./api";
import { messageFor } from "./config";
import {
  DOC_TYPES,
  canSaveNewDocument,
  detailsChanged,
  detailsPayload,
  editorContent,
  fitLabel,
  kbMessageFor,
  planOptions,
  tokenLine,
} from "./knowledge";
import { MarkdownPreview } from "./MarkdownPreview";

interface Props {
  session: AdminSession;
  tenantId: string;
  onExpired: () => void;
}

const NEW = "new";
const EMPTY_FIELDS = { title: "", doc_type: DOC_TYPES[0] as string, plan_scope: "", when_to_use: "" };

export function KnowledgePage({ session, tenantId, onExpired }: Props) {
  const [items, setItems] = useState<KbDocumentItem[] | null>(null);
  const [plans, setPlans] = useState<PlanItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<KbDocumentDetail | null>(null);
  const [fields, setFields] = useState(EMPTY_FIELDS);
  const [content, setContent] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canWrite = session.permissions.includes("kb:write");
  const creating = selected === NEW;

  const fail = useCallback(
    (failure: unknown) => {
      if (failure instanceof ApiError && failure.status === 401) return onExpired();
      setMessage(null);
      setError(
        failure instanceof ApiError
          ? (kbMessageFor(failure.code) ?? messageFor(failure.status, failure.code))
          : "Request failed.",
      );
    },
    [onExpired],
  );

  const refreshList = useCallback(
    () =>
      listKbDocuments(session.token, tenantId)
        .then(setItems)
        .catch(fail),
    [session.token, tenantId, fail],
  );

  useEffect(() => {
    refreshList();
  }, [refreshList]);

  useEffect(() => {
    listPlans(session.token, tenantId).then(setPlans).catch(fail);
  }, [session.token, tenantId, fail]);

  const show = (loaded: KbDocumentDetail) => {
    setDetail(loaded);
    setSelected(loaded.id);
    setFields({
      title: loaded.title,
      doc_type: loaded.doc_type,
      plan_scope: loaded.plan_scope ?? "",
      when_to_use: loaded.when_to_use,
    });
    setContent(editorContent(loaded));
  };

  const open = (id: string) => {
    setMessage(null);
    setError(null);
    setDetail(null);
    setSelected(id);
    readKbDocument(session.token, tenantId, id).then(show).catch(fail);
  };

  const startNew = () => {
    setMessage(null);
    setError(null);
    setDetail(null);
    setFields(EMPTY_FIELDS);
    setContent("");
    setSelected(NEW);
  };

  const run = (call: () => Promise<KbDocumentDetail>, done: string) => {
    setBusy(true);
    setError(null);
    return call()
      .then((loaded) => {
        show(loaded);
        setMessage(done);
        return refreshList();
      })
      .catch(fail)
      .finally(() => setBusy(false));
  };

  const storeDraft = () =>
    creating
      ? createKbDocument(session.token, tenantId, { ...detailsPayload(fields), content })
      : saveKbDraft(session.token, tenantId, detail!.id, content);

  const saveDetails = () =>
    run(
      () => updateKbDocumentDetails(session.token, tenantId, detail!.id, detailsPayload(fields)),
      "Details saved. The assistant uses them now.",
    );

  const saveDraft = () => run(storeDraft, "Draft saved.");

  const publish = () =>
    run(
      () => storeDraft().then((saved) => publishKbDraft(session.token, tenantId, saved.id)),
      "Published. The assistant uses it now.",
    );

  const republish = (versionId: string, version: number) =>
    run(() => republishKbVersion(session.token, tenantId, detail!.id, versionId), `Version ${version} is published again.`);

  const archive = () =>
    run(() => archiveKbDocument(session.token, tenantId, detail!.id), "Archived. The assistant no longer uses it.");

  if (!items) return <p>{error ?? "Loading…"}</p>;

  const ready = creating ? canSaveNewDocument(fields) : detail !== null;
  const detailsReady =
    detail !== null && canSaveNewDocument(fields) && detailsChanged(detail, fields);
  const loadedDetail = creating || detail !== null;

  return (
    <section className="conversations kb-view">
      <div className="list">
        <h2>Knowledge base</h2>
        <button className="primary" onClick={startNew} disabled={!canWrite}>
          New document
        </button>
        {error && !loadedDetail && <p className="error">{error}</p>}
        {items.length === 0 && <p className="hint">No documents yet.</p>}
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              <button className={selected === item.id ? "item active" : "item"} onClick={() => open(item.id)}>
                <strong>{item.title}</strong>
                <span className="hint">
                  {item.doc_type} · {item.plan_scope ?? "all plans"} ·{" "}
                  {item.published_version ? `published v${item.published_version}` : "not published"}
                  {item.has_draft && <span className="chip draft-badge"> draft</span>}
                </span>
                <span className="hint">
                  ~{item.estimated_tokens} tokens, {fitLabel(item.estimated_tokens)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="detail">
        {loadedDetail ? (
          <>
            <div className="detail-head">
              <h3>{creating ? "New document" : detail!.title}</h3>
              {!creating && detail!.has_draft && <span className="chip waiting">Draft</span>}
              {!creating && detail!.published_version && (
                <span className="chip active">Published v{detail!.published_version}</span>
              )}
            </div>
            <label className="field">
              Title
              <input
                value={fields.title}
                onChange={(event) => setFields({ ...fields, title: event.target.value })}
                disabled={!canWrite}
              />
            </label>
            <div className="reply">
              <label className="field">
                Type
                <select
                  value={fields.doc_type}
                  onChange={(event) => setFields({ ...fields, doc_type: event.target.value })}
                  disabled={!canWrite}
                >
                  {DOC_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                Plan scope
                <select
                  value={fields.plan_scope}
                  onChange={(event) => setFields({ ...fields, plan_scope: event.target.value })}
                  disabled={!canWrite}
                >
                  {planOptions(plans, detail?.plan_scope ?? null).map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="field">
              When to use
              <input
                value={fields.when_to_use}
                maxLength={1000}
                onChange={(event) => setFields({ ...fields, when_to_use: event.target.value })}
                placeholder="One short line: when should the assistant read this?"
                disabled={!canWrite}
              />
            </label>
            <div className="kb-editor">
              <label className="field">
                Content (markdown)
                <textarea
                  rows={18}
                  value={content}
                  onChange={(event) => setContent(event.target.value)}
                  disabled={!canWrite}
                />
                <span className="hint" data-testid="token-counter">
                  {tokenLine(content)}
                </span>
              </label>
              <div>
                <span className="hint">Preview</span>
                <MarkdownPreview text={content} />
              </div>
            </div>
            <div className="actions">
              <button onClick={saveDraft} disabled={!canWrite || busy || !ready}>
                Save draft
              </button>
              <button className="primary" onClick={publish} disabled={!canWrite || busy || !ready}>
                Publish
              </button>
              {!creating && (
                <button onClick={saveDetails} disabled={!canWrite || busy || !detailsReady}>
                  Save details
                </button>
              )}
              {!creating && (
                <button onClick={archive} disabled={!canWrite || busy || !detail!.published_version_id}>
                  Archive
                </button>
              )}
              {!canWrite && <span className="hint">Your role can read the knowledge base but not change it.</span>}
            </div>
            {message && <p role="status" className="saved">{message}</p>}
            {error && <p className="error">{error}</p>}
            {!creating && (
              <>
                <h3>Versions</h3>
                <ul className="versions" aria-label="Version history">
                  {detail!.versions.map((version) => (
                    <li key={version.id}>
                      <span>
                        v{version.version} · {version.status} · ~{version.estimated_tokens} tokens
                        {version.published_by ? ` · by ${version.published_by}` : ""}
                      </span>
                      {version.status === "archived" && (
                        <button
                          onClick={() => republish(version.id, version.version)}
                          disabled={!canWrite || busy}
                          aria-label={`Republish version ${version.version}`}
                        >
                          Republish
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        ) : (
          <p className="hint">{selected ? "Loading…" : "Pick a document."}</p>
        )}
      </div>
    </section>
  );
}
