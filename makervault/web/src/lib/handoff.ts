export type HandoffTool = "slicer" | "engraver";

export type HandoffGrant = {
  redeem_url: string;
  grant: string;
  filename: string;
  expires_in: number;
};

export function buildHandoffProtocolUrl(
  tool: HandoffTool,
  handoff: HandoffGrant,
  applicationId: string,
): string {
  const scheme = tool === "slicer" ? "makersvault-slicer" : "makersvault-engrave";
  const appParameter = tool === "slicer" ? "slicer" : "engraver";
  const params = new URLSearchParams({
    redeem: handoff.redeem_url,
    grant: handoff.grant,
    filename: handoff.filename || "model",
    [appParameter]: applicationId,
  });
  return `${scheme}://open?${params.toString()}`;
}
