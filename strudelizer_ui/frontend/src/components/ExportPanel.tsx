// One button per installed emitter, so a new emitter needs no change here. The
// file is built by the local server and saved by the browser: nothing is
// uploaded anywhere.
import { useState } from 'preact/hooks';
import { exportFile } from '../api';
import type { Store } from '../state';
import type { Catalog, EmitterInfo } from '../types';

export function ExportPanel({ store }: { store: Store }) {
  const { catalog, processed, song, profile, dirty } = store;
  const [saved, setSaved] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const ir = processed ?? song;

  async function save(emitter: EmitterInfo) {
    if (!ir) return;
    setBusy(emitter.format);
    setFailed(null);
    try {
      const name = await exportFile({
        ir,
        format: emitter.format,
        profile,
        // The user's own edits are what they hear, so they are what they get.
        code: dirty ? store.effectiveCode : null,
        filename: store.source?.name ?? null,
        tracks: store.playing.length === store.trackIds.length ? null : store.playing,
      });
      setSaved(name);
    } catch (reason) {
      setFailed((reason as Error).message);
      setSaved(null);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section class="panel" aria-labelledby="export-heading">
      <header>
        <h2 id="export-heading">Save</h2>
      </header>
      <div class="body">
        <div class="row">
          {sorted(catalog?.emitters, catalog?.default_emitter).map((emitter) => (
            <button
              key={emitter.name}
              type="button"
              disabled={!ir || busy !== null}
              title={`${emitter.name}: ${emitter.summary}`}
              onClick={() => void save(emitter)}
            >
              {emitter.label} <span class="muted">{emitter.extension}</span>
            </button>
          ))}
        </div>
        {dirty && <p class="small muted">Your edits go into the saved {codeFormat(catalog)} file.</p>}
        {saved && <p class="small">Saved {saved} to your downloads.</p>}
        {failed && <p class="small" style="color:var(--error)">{failed}</p>}
        {!ir && <p class="small muted">Load a song to save it.</p>}
      </div>
    </section>
  );
}

/** The code emitter first: it is what most people came for. */
function sorted(emitters: EmitterInfo[] | undefined, first: string | undefined): EmitterInfo[] {
  return [...(emitters ?? [])].sort(
    (a, b) => Number(b.name === first) - Number(a.name === first) || a.name.localeCompare(b.name),
  );
}

function codeFormat(catalog: Catalog | null): string {
  return catalog?.emitters.find((emitter) => emitter.name === catalog.default_emitter)?.extension ?? '.js';
}
