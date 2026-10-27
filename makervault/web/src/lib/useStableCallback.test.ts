// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, renderHook } from "@testing-library/react";

import { useStableCallback } from "./useStableCallback";

describe("useStableCallback", () => {
  afterEach(cleanup);

  it("returns the same function identity across re-renders", () => {
    const { result, rerender } = renderHook(
      ({ captured }) => useStableCallback(() => captured),
      { initialProps: { captured: "first" } },
    );
    const first = result.current;

    rerender({ captured: "second" });

    expect(result.current).toBe(first);
  });

  it("invokes the latest render's captured value after a re-render", () => {
    const { result, rerender } = renderHook(
      ({ captured }) => useStableCallback(() => captured),
      { initialProps: { captured: "first" } },
    );
    const stable = result.current;
    expect(stable()).toBe("first");

    rerender({ captured: "second" });

    expect(result.current).toBe(stable);
    expect(stable()).toBe("second");
  });
});
