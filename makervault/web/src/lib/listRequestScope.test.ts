import { describe, expect, it, vi } from "vitest";
import { ListRequestScope } from "./listRequestScope";

function activeScope() {
  const scope = new ListRequestScope();
  scope.activate();
  return scope;
}

describe("library request ownership", () => {
  it("new refresh invalidates the old result and old completion cannot finish new work", () => {
    const scope = activeScope();
    const old = scope.refresh()!;
    const latest = scope.refresh()!;
    expect(old.isCurrent()).toBe(false);
    old.finish();
    expect(latest.isCurrent()).toBe(true);
    expect(scope.loadMore()).toBeNull();
    latest.finish();
    expect(scope.loadMore()).not.toBeNull();
  });

  it("guards the joined result even when only old tags arrive late", async () => {
    const scope = activeScope();
    const old = scope.refresh()!;
    let release!: (tags: string[]) => void;
    const tags = new Promise<string[]>(resolve => { release = resolve; });
    const apply = vi.fn();
    const pending = Promise.allSettled([Promise.resolve(["old asset"]), tags]).then(results => {
      if (old.isCurrent()) apply(results);
      old.finish();
    });
    const latest = scope.refresh()!;
    apply("new search");
    release(["old tag"]);
    await pending;
    expect(apply.mock.calls).toEqual([["new search"]]);
    expect(latest.isCurrent()).toBe(true);
  });

  it("new refresh invalidates an in-flight load-more and its stale error/finally", () => {
    const scope = activeScope();
    const more = scope.loadMore()!;
    const refresh = scope.refresh()!;
    const staleError = vi.fn();
    const staleLoading = vi.fn();
    if (more.isCurrent()) { staleError(); staleLoading(); }
    more.finish();
    expect(staleError).not.toHaveBeenCalled();
    expect(staleLoading).not.toHaveBeenCalled();
    expect(refresh.isCurrent()).toBe(true);
  });

  it("serializes next-page requests without waiting for a React render", () => {
    const scope = activeScope();
    const first = scope.loadMore()!;
    expect(scope.loadMore()).toBeNull();
    first.finish();
    expect(scope.loadMore()).not.toBeNull();
    expect(first.isCurrent()).toBe(false);
  });

  it("unmount and StrictMode reactivation never revive old requests", () => {
    const scope = activeScope();
    const old = scope.refresh()!;
    scope.deactivate();
    expect(scope.refresh()).toBeNull();
    expect(scope.loadMore()).toBeNull();
    scope.activate();
    expect(old.isCurrent()).toBe(false);
    expect(scope.refresh()!.isCurrent()).toBe(true);
  });

  it("a departed scope cannot invalidate the new folder's request", () => {
    const oldScope = activeScope();
    const old = oldScope.refresh()!;
    oldScope.deactivate();
    const nextScope = activeScope();
    const next = nextScope.refresh()!;
    old.finish();
    expect(oldScope.refresh()).toBeNull();
    expect(next.isCurrent()).toBe(true);
  });
});
