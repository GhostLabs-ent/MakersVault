// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import ImportCookiesCard from "./ImportCookiesCard";

type CardProps = Parameters<typeof ImportCookiesCard>[0];

function renderCard(overrides: Partial<CardProps> = {}): CardProps {
  const props: CardProps = {
    label: "MakerWorld",
    summary: "Optional rate-limit workaround for free MakerWorld models.",
    description: "Paste the Cookie header.",
    placeholder: "example: mw_session=...;",
    draft: "",
    editing: false,
    setDraft: vi.fn(),
    setEditing: vi.fn(),
    onSave: vi.fn(),
    ...overrides,
  };
  render(<ImportCookiesCard {...props} />);
  return props;
}

afterEach(() => {
  cleanup();
});

describe("ImportCookiesCard", () => {
  it("labels the field as a rate-limit workaround", () => {
    renderCard();

    expect(screen.getByText(/Session cookie \(rate-limit workaround\)/i)).toBeTruthy();
  });

  it("renders the card description", () => {
    renderCard();

    expect(screen.getByText("Paste the Cookie header.")).toBeTruthy();
  });
});
