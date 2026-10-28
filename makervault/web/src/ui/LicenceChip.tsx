import type { ReactElement } from "react";
import { ExternalLink } from "lucide-react";

/**
 * The shared licence pill. It lives here so the project cards and the landing
 * page cannot drift apart; consumers may compose it with their own spacing.
 */
const LICENCE_CHIP_CLASS =
  "inline-flex items-center gap-1 rounded-full border border-panel-strong bg-panel-soft px-2.5 py-0.5 text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";

/** A missing licence is dashed and muted so it never reads as a real term. */
const UNKNOWN_CHIP_CLASS = `${LICENCE_CHIP_CLASS} border-dashed text-subtle`;
const LINKABLE_CHIP_CLASS = `${LICENCE_CHIP_CLASS} hover:bg-panel`;

const UNKNOWN_LICENCE_TITLE = "No licence is recorded for this project";

type Props = {
  licence: string | null | undefined;
  licenceUrl?: string | null;
  /** False inside a card button: a nested link would be invalid HTML. */
  linkable?: boolean;
};

/**
 * Licence term for a project, or an explicit "Licence unknown" when none was
 * recorded. Only the landing page links it (`linkable`): a card is one big
 * `<button>`, so a chip link inside it would be invalid and would trap focus.
 */
export default function LicenceChip({
  licence,
  licenceUrl,
  linkable = false,
}: Props): ReactElement {
  // Blank after trimming means "not recorded", the same rule the editor uses.
  const label = (licence ?? "").trim();
  if (!label) {
    return (
      <span
        data-licence-unknown="true"
        title={UNKNOWN_LICENCE_TITLE}
        className={UNKNOWN_CHIP_CLASS}
      >
        Licence unknown
      </span>
    );
  }

  const href = (licenceUrl ?? "").trim();
  if (linkable && href) {
    return (
      <a
        data-licence-chip="true"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={LINKABLE_CHIP_CLASS}
      >
        {label}
        <ExternalLink className="h-3 w-3" aria-hidden="true" />
      </a>
    );
  }

  return (
    <span data-licence-chip="true" className={LICENCE_CHIP_CLASS}>
      {label}
    </span>
  );
}
