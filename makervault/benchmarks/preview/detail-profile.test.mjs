import assert from 'node:assert/strict';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import { installContextProbe, markDetailPhase } from './detail-profile.mjs';

function fixture(original) {
  class Canvas { closest() { return null; } }
  Canvas.prototype.getContext = original;
  const window = {};
  let time = 0;
  runInNewContext(`(${installContextProbe.toString()})()`, {
    HTMLCanvasElement: Canvas, window, performance: { now: () => time++ },
  });
  return { Canvas, window, original };
}
test('context probe preserves receiver, arguments and return identity', () => {
  const context = {}, options = {};
  let receiver, args;
  const f = fixture(function (...values) { receiver = this; args = values; return context; });
  const canvas = new f.Canvas();
  assert.equal(canvas.getContext('webgl2', options), context);
  assert.equal(receiver, canvas);
  assert.equal(args[1], options);
  assert.equal(f.window.__mvContextCalls[0].duration, 1);
  assert.equal(f.window.__mvContextCalls[0].succeeded, true);
  f.window.__mvRestoreContextProbe();
  assert.equal(f.Canvas.prototype.getContext, f.original);
});
test('context probe preserves null and exception behavior', () => {
  const failure = new Error('fixture');
  const f = fixture(function (kind) { if (kind === 'throw') throw failure; return null; });
  assert.equal(new f.Canvas().getContext('none'), null);
  assert.throws(() => new f.Canvas().getContext('throw'), error => error === failure);
  assert.equal(f.window.__mvContextCalls.length, 2);
  assert(f.window.__mvContextCalls.every(call => !call.succeeded));
});
test('probe is bounded and cleanup does not overwrite a later wrapper', () => {
  const f = fixture(() => ({}));
  const canvas = new f.Canvas();
  for (let i = 0; i < 2010; i++) canvas.getContext('2d');
  assert.equal(f.window.__mvContextCalls.length, 2000);
  const later = () => null;
  f.Canvas.prototype.getContext = later;
  f.window.__mvRestoreContextProbe();
  assert.equal(f.Canvas.prototype.getContext, later);
});
test('invalid receiver does not replace the original exception', () => {
  const failure = new Error('native invalid receiver');
  const f = fixture(() => { throw failure; });
  assert.throws(() => Reflect.apply(f.Canvas.prototype.getContext, null, ['webgl2']), error => error === failure);
});
test('detail marks preserve ordering on the same page clock', () => {
  const window = { __mvProfile: { phases: [] } }, marks = [];
  const globals = { window, performance: { now: () => 12, mark: name => marks.push(name) } };
  runInNewContext(`(${markDetailPhase.toString()})('detail-before-click')`, globals);
  assert.equal(marks[0], 'mv.phase:detail-before-click');
  assert.equal(window.__mvProfile.phases[0].atMs, 12);
});
