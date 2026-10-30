import {
  collectTransferables,
  type StepWorkerRequest,
  type StepWorkerResponse,
} from "./protocol";
import { readStepMeshes } from "./readStep";

/**
 * Worker entry for STEP previews. It exists so occt's WASM parsing (the only
 * genuinely blocking part of a STEP preview) never runs on the main thread.
 * A crash here is isolated to the worker; the main thread notices through
 * `onerror` and stops spawning workers for the rest of the session.
 */
type WorkerScope = {
  onmessage: ((event: MessageEvent<StepWorkerRequest>) => void) | null;
  postMessage(message: StepWorkerResponse, transfer?: Transferable[]): void;
};

const scope = globalThis as unknown as WorkerScope;

async function handleRequest(event: MessageEvent<StepWorkerRequest>): Promise<void> {
  const { id, bytes } = event.data;
  try {
    const geometry = await readStepMeshes(new Uint8Array(bytes));
    scope.postMessage({ id, ok: true, geometry }, collectTransferables(geometry));
  } catch (error) {
    scope.postMessage({
      id,
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

scope.onmessage = event => {
  void handleRequest(event);
};
