// The generated code, live in a real Strudel editor: play it, edit it, put it
// back. Everything the page generates goes through `pushCode`, so changing an
// option while it plays swaps the pattern without stopping the music.
import { useEffect, useRef, useState } from 'preact/hooks';
import { createEditor, pushCode, revealLine, setTheme, shareUrl } from '../strudel';
import type { StrudelEditorElement, StrudelState } from '../strudel';
import type { Store } from '../state';

export function CodePanel({ store, theme }: { store: Store; theme: string }) {
  const { code, effectiveCode, dirty, setEditedCode, busy, error, revealed } = store;
  const host = useRef<HTMLDivElement>(null);
  const element = useRef<StrudelEditorElement | null>(null);
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [strudelError, setStrudelError] = useState<string | null>(null);
  const lastPushed = useRef('');

  // Create the editor once, as soon as there is code to put in it, and take it
  // down again when the song is removed.
  useEffect(() => {
    if (!code) {
      element.current?.editor?.stop();
      element.current?.remove();
      element.current = null;
      setReady(false);
      return;
    }
    if (element.current || !host.current) return;
    let cancelled = false;
    lastPushed.current = code;
    createEditor(host.current, code).then(
      (created) => {
        if (cancelled) {
          created.remove();
          return;
        }
        element.current = created;
        setReady(true);
      },
      (reason: Error) => setFailed(reason.message),
    );
    return () => {
      cancelled = true;
    };
  }, [code]);

  // New generated code replaces what is in the editor.
  useEffect(() => {
    const editor = element.current?.editor;
    if (!editor || !ready || code === lastPushed.current) return;
    lastPushed.current = code;
    pushCode(editor, code);
  }, [code, ready]);

  // The component reports every state change (the user typing, ctrl+enter
  // inside the editor, an evaluation error) as an `update` event.
  useEffect(() => {
    const host = element.current;
    if (!ready || !host) return;
    const onUpdate = (event: Event) => {
      const state = (event as CustomEvent<StrudelState>).detail;
      setPlaying(Boolean(state.started));
      setStrudelError(state.error ? String(state.error) : null);
      const current = state.code ?? '';
      setEditedCode(current === lastPushed.current ? null : current);
    };
    host.addEventListener('update', onUpdate);
    return () => host.removeEventListener('update', onUpdate);
  }, [ready, setEditedCode]);

  useEffect(() => {
    const editor = element.current?.editor;
    if (editor && revealed) revealLine(editor, revealed.line);
  }, [revealed]);

  // The editor brings its own themes; use the one that matches the page.
  useEffect(() => {
    const editor = element.current?.editor;
    if (editor && ready) setTheme(editor, theme);
  }, [theme, ready]);

  function play() {
    const editor = element.current?.editor;
    if (editor) void editor.evaluate();
  }

  function stop() {
    element.current?.editor?.stop();
  }

  // Strudel's own keys, from anywhere on the page. Inside the editor they are
  // already bound, so there they are left alone.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || host.current?.contains(event.target as Node)) return;
      if (event.key === 'Enter') {
        event.preventDefault();
        play();
      } else if (event.key === '.') {
        event.preventDefault();
        stop();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [ready]);

  function reset() {
    const editor = element.current?.editor;
    if (editor) pushCode(editor, code);
    setEditedCode(null);
  }

  return (
    <section class="panel" aria-labelledby="code-heading">
      <header>
        <h2 id="code-heading">Code</h2>
        {dirty && <span class="badge">edited</span>}
        {playing && <span class="badge live">playing</span>}
        <div class="spacer" />
        {busy === 'convert' && <span class="spinner" role="status" aria-label="Converting" />}
        <button type="button" class="primary" onClick={play} disabled={!ready} title="ctrl+enter">
          Play
        </button>
        <button type="button" onClick={stop} disabled={!ready} title="ctrl+.">
          Stop
        </button>
        {dirty && (
          <button type="button" onClick={reset}>
            Reset to generated
          </button>
        )}
        {effectiveCode && (
          <a class="small" href={shareUrl(effectiveCode)} target="_blank" rel="noreferrer">
            Open in strudel.cc
          </a>
        )}
      </header>

      {error && <pre class="code" style="color:var(--error)">{error.text}</pre>}
      {strudelError && (
        <p class="small" style="color:var(--error);padding:8px 14px 0">
          Strudel could not play this code: {strudelError}
        </p>
      )}
      {!code && !error && <p class="empty-state">Drop in a song to see its Strudel code.</p>}
      {code && !ready && !failed && <p class="empty-state">Loading the Strudel editor…</p>}
      {failed && (
        <>
          <p class="empty-state">
            The Strudel editor could not load ({failed}), so here is the code on its own.
            "Open in strudel.cc" still works.
          </p>
          <pre class="code">{effectiveCode}</pre>
        </>
      )}
      {/* The web component is appended here imperatively, so it has no Preact children. */}
      {code && <div class="editor-wrap" ref={host} />}
    </section>
  );
}
