/** Mirrors the notice AuditLog shows for a 403, so both read the same. */
const FORBIDDEN_NOTICE = "Administrator access required.";

/**
 * The clean stand-in for a page this account may not open. The API is still
 * the gate; this only replaces a raw 403 with an honest explanation.
 */
export default function NotPermitted() {
  return (
    <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
      <div className="text-lg font-semibold">Not permitted</div>
      <p className="text-sm text-muted">{FORBIDDEN_NOTICE}</p>
    </div>
  );
}
