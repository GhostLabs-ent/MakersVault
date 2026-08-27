import { describe, expect, it } from "vitest";

import { buildGeneralHandoffProtocolUrl, buildHandoffProtocolUrl } from "./handoff";


describe("bridge handoff protocol", () => {
  it("contains only the scoped grant and fixed redemption URL", () => {
    const protocol = buildHandoffProtocolUrl(
      "slicer",
      {
        redeem_url: "https://vault.example/api/handoff/redeem",
        grant: "scoped.handoff.grant",
        filename: "plate.gcode.3mf",
        expires_in: 90,
      },
      "orca",
    );
    const parsed = new URL(protocol);

    expect(parsed.protocol).toBe("makersvault-slicer:");
    expect(parsed.searchParams.get("redeem")).toBe("https://vault.example/api/handoff/redeem");
    expect(parsed.searchParams.get("grant")).toBe("scoped.handoff.grant");
    expect(parsed.searchParams.get("slicer")).toBe("orca");
    expect(parsed.searchParams.has("url")).toBe(false);
    expect(parsed.searchParams.has("token")).toBe(false);
  });

  it("uses the engraving scheme and role-specific application parameter", () => {
    const protocol = buildHandoffProtocolUrl(
      "engraver",
      {
        redeem_url: "http://vault.lan:8000/handoff/redeem",
        grant: "grant",
        filename: "design.svg",
        expires_in: 90,
      },
      "lightburn",
    );
    const parsed = new URL(protocol);

    expect(parsed.protocol).toBe("makersvault-engrave:");
    expect(parsed.searchParams.get("engraver")).toBe("lightburn");
    expect(parsed.searchParams.has("slicer")).toBe(false);
  });

  it("builds a role-bound general adapter URL without file or session authority", () => {
    const protocol = buildGeneralHandoffProtocolUrl({
      redeem_url: "https://vault.example/api/handoff/redeem",
      grant: "one.file.grant",
      filename: "historical.step",
      expires_in: 90,
      adapter_id: "freecad",
      content_role: "revision_primary",
    });
    const parsed = new URL(protocol);

    expect(parsed.protocol).toBe("makersvault-open:");
    expect(parsed.searchParams.get("adapter")).toBe("freecad");
    expect(parsed.searchParams.get("role")).toBe("revision_primary");
    expect(parsed.searchParams.get("filename")).toBe("historical.step");
    expect(parsed.searchParams.has("url")).toBe(false);
    expect(parsed.searchParams.has("token")).toBe(false);
  });
});
