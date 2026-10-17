// Step 1 of the page: a file, or a chord sheet pasted straight in. The accepted
// file types and the importer list both come from /api/plugins, so installing an
// importer is all it takes for its files to be accepted here.
import { useRef, useState } from 'preact/hooks';
import type { Store } from '../state';

export function InputPanel({ store }: { store: Store }) {
  const { catalog, source, setSource, importer, setImporter, busy } = store;
  const [over, setOver] = useState(false);
  const [text, setText] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const accept = catalog?.accept.join(',') ?? '';

  function take(file: File | undefined | null) {
    if (file) setSource({ kind: 'file', name: file.name, file });
  }

  function paste(value: string) {
    setText(value);
    setSource(value.trim() ? { kind: 'text', name: 'pasted.txt', text: value } : null);
  }

  return (
    <section class="panel" aria-labelledby="input-heading">
      <header>
        <h2 id="input-heading">Song</h2>
        <div class="spacer" />
        {busy === 'import' && <span class="spinner" role="status" aria-label="Reading the song" />}
      </header>
      <div class="body">
        <div
          class={`dropzone${over ? ' over' : ''}`}
          onDragOver={(event) => {
            event.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setOver(false);
            take(event.dataTransfer?.files?.[0]);
          }}
        >
          <strong>Drop a song here</strong>
          <span class="muted small">{describe(accept)}</span>
          <button type="button" onClick={() => fileInput.current?.click()}>
            Choose a file
          </button>
          <input
            ref={fileInput}
            class="visually-hidden"
            type="file"
            accept={accept}
            aria-label="Song file"
            onChange={(event) => {
              const input = event.currentTarget;
              take(input.files?.[0]);
              input.value = '';  // picking the same file twice should still reload it
            }}
          />
        </div>

        {source?.kind === 'file' && (
          <p class="row small">
            <span class="filename">{source.name}</span>
            <button type="button" class="link" onClick={() => setSource(null)}>
              remove
            </button>
          </p>
        )}

        <label class="small muted" for="paste">
          Or paste a chord sheet or tab
        </label>
        <textarea
          id="paste"
          rows={5}
          spellcheck={false}
          placeholder={'[Verse]\nAm      F\nC       G'}
          value={text}
          onInput={(event) => paste(event.currentTarget.value)}
        />

        <div class="field">
          <label for="importer" title="The importer that reads this format (--importer)">
            Read it as
          </label>
          <select
            id="importer"
            value={importer ?? ''}
            onChange={(event) => setImporter(event.currentTarget.value || null)}
          >
            <option value="">Detect automatically</option>
            {catalog?.importers.map((info) => (
              <option key={info.name} value={info.name}>
                {info.name}
              </option>
            ))}
          </select>
        </div>

        {catalog?.uninstalled
          .filter((plugin) => plugin.kind === 'importer')
          .map((plugin) => (
            <p key={plugin.name} class="small muted">
              {plugin.extensions.join(', ')} needs <code>{plugin.name}</code>: <code>{plugin.install}</code>
            </p>
          ))}
      </div>
    </section>
  );
}

function describe(accept: string): string {
  return accept ? accept.split(',').join(' ') : 'no importers installed';
}
