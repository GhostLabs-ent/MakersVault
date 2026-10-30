import type { ReactElement, ReactNode } from "react";

import { fileUrl } from "../lib/api";
import { useLiveFileGrants } from "../lib/useFileGrants";

type FileDownloadLinkProps = {
  /** The API-relative path to download (a rel `fileUrl` can sign). */
  rel: string;
  /** Goes on the `download` attribute: the name the browser saves it under. */
  filename: string;
  className?: string;
  children: ReactNode;
};

/**
 * A download anchor that keeps its own grant warm. A grant lives 60 s, and this
 * link is usually clicked long after the fetch that minted it, so it re-mints
 * itself just before each expiry and re-renders with the fresh URL — an
 * unsigned `href` would 401 the download (Mf-1vxh).
 */
export default function FileDownloadLink({
  rel,
  filename,
  className,
  children,
}: FileDownloadLinkProps): ReactElement {
  useLiveFileGrants([rel]);
  return (
    <a className={className} href={fileUrl(rel)} download={filename}>
      {children}
    </a>
  );
}
