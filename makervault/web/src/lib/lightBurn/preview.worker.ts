import {
  parseLightBurn,
  type LightBurnLimits,
  type LightBurnModel,
} from "./parse";

type LightBurnWorkerRequest = {
  id: number;
  bytes: ArrayBuffer;
  limits: LightBurnLimits;
};

type LightBurnWorkerResponse =
  | { id: number; ok: true; model: LightBurnModel }
  | { id: number; ok: false; error: string };

type WorkerScope = {
  onmessage: ((event: MessageEvent<LightBurnWorkerRequest>) => void) | null;
  postMessage(message: LightBurnWorkerResponse, transfer?: Transferable[]): void;
};

const scope = globalThis as unknown as WorkerScope;

scope.onmessage = event => {
  const { id, bytes, limits } = event.data;
  try {
    const model = parseLightBurn(new Uint8Array(bytes), limits);
    const transfer: Transferable[] = [];
    if (model.thumbnail) {
      const copy = model.thumbnail.data.slice();
      model.thumbnail = { data: copy, mime: model.thumbnail.mime };
      transfer.push(copy.buffer);
    }
    scope.postMessage({ id, ok: true, model }, transfer);
  } catch (error) {
    scope.postMessage({
      id,
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
};
