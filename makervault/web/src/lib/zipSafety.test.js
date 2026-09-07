import { createRequire } from "node:module";
import { Worker } from "node:worker_threads";
import { describe, expect, it } from "vitest";
import { strToU8, zipSync } from "fflate";

const modulePath = createRequire(import.meta.url).resolve("fflate");
const name = "fixture.stl";
const content = "solid fixture\nendsolid fixture\n";

// A tiny, in-memory ZIP64 fixture. No files are extracted or uploaded. Its central
// directory asks for ZIP64 sizes; the caller chooses the corresponding extra field.
function zip64(extra) {
  const archive = zipSync({ [name]: strToU8(content) }, { level: 0 });
  const source = new DataView(archive.buffer);
  const end = archive.length - 22;
  const central = source.getUint32(end + 16, true);
  expect(source.getUint16(central + 30, true)).toBe(0);
  expect(source.getUint16(central + 32, true)).toBe(0);
  const result = new Uint8Array(end + extra.length + 56 + 20 + 22);
  const view = new DataView(result.buffer);
  result.set(archive.subarray(0, end));
  result.set(extra, end);
  view.setUint16(central + 30, extra.length, true);
  for (const offset of [20, 24, 42]) view.setUint32(central + offset, 0xffffffff, true);
  const record = end + extra.length;
  view.setUint32(record, 0x06064b50, true);
  view.setBigUint64(record + 4, 44n, true);
  view.setUint16(record + 12, 45, true);
  view.setUint16(record + 14, 45, true);
  view.setBigUint64(record + 24, 1n, true);
  view.setBigUint64(record + 32, 1n, true);
  view.setBigUint64(record + 40, BigInt(record - central), true);
  view.setBigUint64(record + 48, BigInt(central), true);
  const locator = record + 56;
  view.setUint32(locator, 0x07064b50, true);
  view.setBigUint64(locator + 8, BigInt(record), true);
  view.setUint32(locator + 16, 1, true);
  const footer = locator + 20;
  result.set(archive.subarray(end), footer);
  view.setUint16(footer + 8, 0xffff, true);
  view.setUint16(footer + 10, 0xffff, true);
  view.setUint32(footer + 12, 0xffffffff, true);
  view.setUint32(footer + 16, 0xffffffff, true);
  return result;
}

async function boundedUnzip(bytes) {
  // A broken pin must fail this test, not hang Vitest's thread indefinitely.
  const worker = new Worker(`
    const { parentPort, workerData } = require("node:worker_threads");
    const { unzipSync, strFromU8 } = require(workerData.modulePath);
    try {
      const files = unzipSync(workerData.bytes);
      parentPort.postMessage({ ok: true, files: Object.fromEntries(
        Object.entries(files).map(([name, data]) => [name, strFromU8(data)])) });
    } catch (error) {
      parentPort.postMessage({ ok: false, code: error.code });
    }
  `, { eval: true, workerData: { bytes, modulePath },
    resourceLimits: { maxOldGenerationSizeMb: 32, maxYoungGenerationSizeMb: 8 } });
  let timer;
  try {
    return await new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(new Error("ZIP parser exceeded the 2-second test deadline")), 2000);
      worker.once("message", resolve);
      worker.once("error", reject);
      worker.once("exit", code => reject(new Error(`ZIP worker exited without a result (${code})`)));
    });
  } finally {
    clearTimeout(timer);
    await worker.terminate();
  }
}

describe("ZIP dependency safety (GHSA-px8p-9vwx-vf98)", () => {
  it("preserves an ordinary stored archive", async () => {
    expect(await boundedUnzip(zipSync({ [name]: strToU8(content) }, { level: 0 })))
      .toEqual({ ok: true, files: { [name]: content } });
  });

  it("still reads a valid ZIP64 central-directory extra field", async () => {
    const extra = new Uint8Array(28);
    const view = new DataView(extra.buffer);
    view.setUint16(0, 1, true);
    view.setUint16(2, 24, true);
    view.setBigUint64(4, BigInt(strToU8(content).length), true);
    view.setBigUint64(12, BigInt(strToU8(content).length), true);
    view.setBigUint64(20, 0n, true);
    expect(await boundedUnzip(zip64(extra))).toEqual({ ok: true, files: { [name]: content } });
  });

  it.each([
    ["absent", []],
    ["unrelated", [0x99, 0x99, 0, 0]],
    ["truncated unrelated", [0x99, 0x99]],
  ])("rejects a %s ZIP64 extra field without looping", async (_description, bytes) => {
    expect(await boundedUnzip(zip64(new Uint8Array(bytes)))).toEqual({ ok: false, code: 13 });
  });
});
