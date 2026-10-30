import { describe, expect, it } from "vitest";

import {
  CREATOR_MAX_LENGTH,
  NAME_MAX_LENGTH,
  NOTES_MAX_LENGTH,
  normaliseCreator,
  normaliseName,
  normaliseNotes,
} from "./metadataValidation";

describe("normaliseCreator", () => {
  it("trims and collapses internal whitespace", () => {
    expect(normaliseCreator("  Ada   Lovelace  ")).toEqual({
      value: "Ada Lovelace",
      error: null,
    });
  });

  it("accepts unicode and apostrophes untouched", () => {
    expect(normaliseCreator("Zoë O'Lovelace ✓")).toEqual({
      value: "Zoë O'Lovelace ✓",
      error: null,
    });
  });

  it("clears on blank input without an error", () => {
    expect(normaliseCreator("     ")).toEqual({ value: null, error: null });
  });

  it.each(["bad\u0000creator", "line\nbreak", "carriage\rreturn"])(
    "rejects control characters in %j",
    raw => {
      const result = normaliseCreator(raw);
      expect(result.value).toBeNull();
      expect(result.error).toMatch(/control characters/);
    },
  );

  it("caps the collapsed value at the server limit", () => {
    expect(normaliseCreator("x".repeat(CREATOR_MAX_LENGTH)).value).toHaveLength(
      CREATOR_MAX_LENGTH,
    );
    const tooLong = normaliseCreator("x".repeat(CREATOR_MAX_LENGTH + 1));
    expect(tooLong.value).toBeNull();
    expect(tooLong.error).toContain(String(CREATOR_MAX_LENGTH));
  });
});

describe("normaliseName", () => {
  it("trims and collapses internal whitespace", () => {
    expect(normaliseName("  My   Model  ")).toEqual({ value: "My Model", error: null });
  });

  it("accepts unicode and punctuation", () => {
    expect(normaliseName("Café d'Art (v2)")).toEqual({
      value: "Café d'Art (v2)",
      error: null,
    });
  });

  it.each(["safe/model", "dir\\name", "../../etc/passwd"])(
    "rejects path separators in %j",
    raw => {
      const result = normaliseName(raw);
      expect(result.value).toBeNull();
      expect(result.error).toMatch(/path separators/);
    },
  );

  it("rejects blank input: a provided name must be non-empty", () => {
    for (const raw of ["", "   "]) {
      const result = normaliseName(raw);
      expect(result.value).toBeNull();
      expect(result.error).toMatch(/must not be empty/);
    }
  });

  it("rejects control characters", () => {
    const result = normaliseName("bad\u0007title");
    expect(result.value).toBeNull();
    expect(result.error).toMatch(/control characters/);
  });

  it("caps the collapsed value at the server limit", () => {
    expect(normaliseName("x".repeat(NAME_MAX_LENGTH)).value).toHaveLength(NAME_MAX_LENGTH);
    const tooLong = normaliseName("x".repeat(NAME_MAX_LENGTH + 1));
    expect(tooLong.value).toBeNull();
    expect(tooLong.error).toContain(String(NAME_MAX_LENGTH));
  });
});

describe("normaliseNotes", () => {
  it("strips only the outer whitespace and preserves internal line breaks and tabs", () => {
    expect(normaliseNotes("  line one\n  line two\tend  ")).toEqual({
      value: "line one\n  line two\tend",
      error: null,
    });
  });

  it("clears on blank input without an error", () => {
    expect(normaliseNotes(" \n\t ")).toEqual({ value: null, error: null });
  });

  it.each(["bad\u0000note", "carriage\rreturn"])(
    "rejects control characters other than newline and tab in %j",
    raw => {
      const result = normaliseNotes(raw);
      expect(result.value).toBeNull();
      expect(result.error).toMatch(/control characters/);
    },
  );

  it("caps the trimmed value at the server limit", () => {
    expect(normaliseNotes("x".repeat(NOTES_MAX_LENGTH)).value).toHaveLength(NOTES_MAX_LENGTH);
    const tooLong = normaliseNotes("x".repeat(NOTES_MAX_LENGTH + 1));
    expect(tooLong.value).toBeNull();
    expect(tooLong.error).toContain(String(NOTES_MAX_LENGTH));
  });
});
