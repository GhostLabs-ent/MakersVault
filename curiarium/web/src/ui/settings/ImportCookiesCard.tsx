type Props = {
  label: string;
  summary: string;
  description: string;
  placeholder: string;
  draft: string;
  editing: boolean;
  setDraft: (value: string) => void;
  setEditing: (value: boolean) => void;
  onSave: (draft: string) => void;
};

export default function ImportCookiesCard({
  label,
  summary,
  description,
  placeholder,
  draft,
  editing,
  setDraft,
  setEditing,
  onSave,
}: Props) {
  return (
    <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
      <div>
        <div className="text-lg font-semibold">{label}</div>
        <p className="text-sm opacity-70">{summary}</p>
      </div>
      <p className="text-xs opacity-70">{description}</p>
      <div className="flex items-center justify-between gap-3">
        <label className="text-xs uppercase tracking-wide text-muted">
          Session cookie (rate-limit workaround)
        </label>
        {editing ? (
          <button
            className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
            onClick={() => {
              onSave(draft);
              setEditing(false);
            }}
          >
            Save
          </button>
        ) : (
          <button
            className="text-xs px-2 py-1 rounded-md border border-panel-strong"
            onClick={() => setEditing(true)}
          >
            Edit
          </button>
        )}
      </div>
      <textarea
        rows={4}
        value={draft}
        onChange={e => setDraft(e.target.value)}
        placeholder={placeholder}
        readOnly={!editing}
        className={`px-3 py-2 rounded-md border border-panel-strong bg-panel-soft text-sm ${
          editing ? "" : "opacity-70"
        }`}
      />
    </div>
  );
}
