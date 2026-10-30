/**
 * Client-side mirrors of the API's editable-metadata rules (Mf-pnc2).
 *
 * The server remains the authority: these validators exist so a card or the
 * batch dialog can explain a refusal inline instead of sending a request that
 * comes back as a 422. Each returns the value to send (or `null` to clear) and
 * a user-facing error, never throws. `collection` is deliberately absent - ADR
 * 0003 retires it, so it keeps its legacy behaviour and is not validated here.
 */

export const CREATOR_MAX_LENGTH = 120;
export const NAME_MAX_LENGTH = 120;
export const NOTES_MAX_LENGTH = 4000;

/** A model name becomes a path component, so a separator is refused outright. */
const NAME_SEPARATORS = ["/", "\\"];
/** Notes are prose: line breaks and tabs are meaningful, other controls are not. */
const NOTES_ALLOWED_CONTROLS = new Set(["\n", "\t"]);

export type MetadataValidation = {
  value: string | null;
  error: string | null;
};

/** Python's `str.split()`/`" ".join(...)` collapse: all whitespace runs become one space. */
function collapseWhitespace(value: string): string {
  return value.trim().split(/\s+/).filter(Boolean).join(" ");
}

function hasControlCharacter(value: string, allowed: Set<string> = new Set()): boolean {
  for (const char of value) {
    if (allowed.has(char)) continue;
    if (/\p{Cc}/u.test(char)) return true;
  }
  return false;
}

/** Trim, collapse whitespace and cap a creator; blank clears the field. */
export function normaliseCreator(raw: string): MetadataValidation {
  if (hasControlCharacter(raw)) {
    return { value: null, error: "Creator must not contain control characters." };
  }
  const value = collapseWhitespace(raw);
  if (!value) return { value: null, error: null };
  if (value.length > CREATOR_MAX_LENGTH) {
    return { value: null, error: `Creator must be at most ${CREATOR_MAX_LENGTH} characters.` };
  }
  return { value, error: null };
}

/** Trim, collapse, reject separators and cap a model name or title. */
export function normaliseName(raw: string): MetadataValidation {
  if (hasControlCharacter(raw)) {
    return { value: null, error: "Name must not contain control characters." };
  }
  if (NAME_SEPARATORS.some(separator => raw.includes(separator))) {
    return { value: null, error: "Name must not contain path separators." };
  }
  const value = collapseWhitespace(raw);
  if (!value) return { value: null, error: "Name must not be empty." };
  if (value.length > NAME_MAX_LENGTH) {
    return { value: null, error: `Name must be at most ${NAME_MAX_LENGTH} characters.` };
  }
  return { value, error: null };
}

/** Strip outer whitespace and cap notes; internal line breaks and tabs stay. */
export function normaliseNotes(raw: string): MetadataValidation {
  if (hasControlCharacter(raw, NOTES_ALLOWED_CONTROLS)) {
    return { value: null, error: "Notes must not contain control characters." };
  }
  const value = raw.trim();
  if (!value) return { value: null, error: null };
  if (value.length > NOTES_MAX_LENGTH) {
    return { value: null, error: `Notes must be at most ${NOTES_MAX_LENGTH} characters.` };
  }
  return { value, error: null };
}
