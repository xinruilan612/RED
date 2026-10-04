const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('frontend/walkthrough-recorder.js', 'utf8');
function setup({reject = false, supported = true} = {}) {
  const elements = Object.fromEntries(['startRecording', 'stopRecording', 'downloadRecording', 'recordingStatus', 'recordingTimer'].map(id => [id, {hidden: true, addEventListener(name, fn) {this[name] = fn;}}]));
  let captureCalls = 0, options, lastRecorder, ended, stopped = 0, blob;
  const track = {stop() {stopped++;}, addEventListener(name, fn) {ended = fn;}};
  class Recorder {
    static isTypeSupported() {return true;}
    constructor(stream, args) {this.state = 'inactive'; this.mimeType = args.mimeType; lastRecorder = this;}
    start() {this.state = 'recording';}
    stop() {this.state = 'inactive'; this.ondataavailable({data: new Blob(['actual frames'])}); this.onstop();}
  }
  const context = {document: {getElementById: id => elements[id], body: {classList: {add() {}, remove() {}}}}, navigator: {mediaDevices: supported ? {async getDisplayMedia(args) {captureCalls++; options = args; if (reject) throw Object.assign(new Error('denied'), {name: 'NotAllowedError'}); return {getTracks: () => [track], getVideoTracks: () => [track]};}} : undefined}, MediaRecorder: Recorder, Blob, Date, URL: {createObjectURL(value) {blob = value; return 'blob:recorded';}, revokeObjectURL() {}}, window: {addEventListener() {}}, setInterval: () => 1, clearInterval() {}};
  vm.runInNewContext(code, context);
  return {elements, get captureCalls() {return captureCalls;}, get options() {return options;}, get recorder() {return lastRecorder;}, get stopped() {return stopped;}, get blob() {return blob;}, end: () => ended()};
}
test('recording requires explicit click and uses no audio', async () => {
  const app = setup(); assert.equal(app.captureCalls, 0);
  await app.elements.startRecording.click();
  assert.equal(app.captureCalls, 1); assert.equal(app.options.audio, false);
  assert.equal(app.options.selfBrowserSurface, 'include'); assert.equal(app.elements.stopRecording.disabled, false);
  await app.elements.startRecording.click(); assert.equal(app.captureCalls, 1);
});
test('stop exposes real captured bytes as a downloadable webm and closes capture', async () => {
  const app = setup(); await app.elements.startRecording.click(); app.elements.stopRecording.click();
  assert.equal(app.elements.downloadRecording.hidden, false); assert.match(app.elements.downloadRecording.download, /\.webm$/);
  assert.equal(await app.blob.text(), 'actual frames'); assert.equal(app.stopped, 1);
  assert.equal(app.elements.startRecording.disabled, false);
});
test('browser stop sharing finalizes the recording', async () => {
  const app = setup(); await app.elements.startRecording.click(); app.end();
  assert.equal(app.elements.downloadRecording.hidden, false); assert.equal(app.recorder.state, 'inactive');
});
test('denied permission restores controls and does not produce pretend video', async () => {
  const app = setup({reject: true}); await app.elements.startRecording.click();
  assert.equal(app.elements.startRecording.disabled, false); assert.equal(app.elements.downloadRecording.hidden, true);
  assert.match(app.elements.recordingStatus.textContent, /未获得权限/);
});
test('unsupported browser gives actionable explanation without requesting capture', async () => {
  const app = setup({supported: false}); await app.elements.startRecording.click();
  assert.equal(app.captureCalls, 0); assert.match(app.elements.recordingStatus.textContent, /Chrome/);
});
