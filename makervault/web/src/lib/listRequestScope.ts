export type ListRequest = {
  isCurrent(): boolean;
  finish(): void;
};

/** A mounted library scope owns at most one refresh or next-page request. */
export class ListRequestScope {
  private active = false;
  private current: ListRequest | null = null;

  activate() { this.active = true; }

  deactivate() {
    this.active = false;
    this.current = null;
  }

  refresh(): ListRequest | null { return this.begin(true); }
  loadMore(): ListRequest | null { return this.begin(false); }

  private begin(replace: boolean): ListRequest | null {
    if (!this.active || (!replace && this.current)) return null;
    const request: ListRequest = {
      isCurrent: () => this.active && this.current === request,
      finish: () => { if (this.current === request) this.current = null; },
    };
    this.current = request;
    return request;
  }
}
