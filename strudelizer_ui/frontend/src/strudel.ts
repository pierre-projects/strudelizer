// The embedded Strudel REPL: @strudel/repl's <strudel-editor> web component,
// pinned to 1.2.6 to match the version the repo's tests evaluate against and
// served from our own origin (see scripts/vendor-strudel.mjs).
//
// The component exposes the StrudelMirror instance it runs as `.editor`, which
// is how the generated code gets in and playback is driven from the page.

/** The slice of StrudelMirror this app uses. */
interface StrudelMirror {
  code: string;
  setCode(code: string): void;
  evaluate(): void | Promise<void>;
  start(): void | Promise<void>;
  stop(): void;
  /** The CodeMirror view, used to reveal the line a bar maps to. */
  editor?: {
    state: { doc: { lines: number; line(n: number): { from: number; to: number } } };
    dispatch(spec: unknown): void;
  };
  repl?: { scheduler?: { started?: boolean } };
}

export interface StrudelEditorElement extends HTMLElement {
  editor?: StrudelMirror;
}

/**
 * What the component sends with its `update` event (the REPL's state).
 * `code` is what is in the editor now, `activeCode` what last evaluated.
 */
export interface StrudelState {
  code?: string;
  activeCode?: string;
  started?: boolean;
  pending?: boolean;
  isDirty?: boolean;
  error?: unknown;
}

const BUNDLE = '/strudel/index.js';
let loading: Promise<void> | null = null;

/** Load the bundle once, on demand: it is 1.8 MB, so not before it is needed. */
export function loadStrudel(): Promise<void> {
  if (!loading) {
    loading = new Promise<void>((resolve, reject) => {
      const script = document.createElement('script');
      script.src = BUNDLE;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error(`could not load ${BUNDLE}`));
      document.head.append(script);
    }).then(() => customElements.whenDefined('strudel-editor').then(() => undefined));
  }
  return loading;
}

/** Create the editor element with its first code, and wait for it to come up. */
export async function createEditor(parent: HTMLElement, code: string): Promise<StrudelEditorElement> {
  await loadStrudel();
  const element = document.createElement('strudel-editor') as StrudelEditorElement;
  element.setAttribute('code', code);
  parent.append(element);
  for (let attempt = 0; attempt < 100 && !element.editor; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  if (!element.editor) throw new Error('the Strudel editor did not start');
  return element;
}

export function isPlaying(editor: StrudelMirror | undefined): boolean {
  return Boolean(editor?.repl?.scheduler?.started);
}

/** Put new code in the editor, and keep it playing if it already was. */
export function pushCode(editor: StrudelMirror, code: string): void {
  editor.setCode(code);
  if (isPlaying(editor)) void editor.evaluate();
}

/** Select a line and scroll to it, without stealing focus from the page. */
export function revealLine(editor: StrudelMirror, line: number): void {
  const view = editor.editor;
  if (!view) return;
  const found = view.state.doc.line(Math.max(1, Math.min(line, view.state.doc.lines)));
  view.dispatch({ selection: { anchor: found.from, head: found.to }, scrollIntoView: true });
}

/**
 * strudel.cc's share format, as `code2hash` in @strudel/core writes it:
 * the UTF-8 bytes in base64, URL-encoded, after the `#`.
 */
export function shareUrl(code: string): string {
  const bytes = new TextEncoder().encode(code);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return `https://strudel.cc/#${encodeURIComponent(btoa(binary))}`;
}
