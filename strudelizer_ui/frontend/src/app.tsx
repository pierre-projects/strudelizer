import { InputPanel } from './components/InputPanel';
import { useStrudelizer } from './state';

export function App() {
  const store = useStrudelizer();
  const { catalog, song, code, error, busy } = store;

  return (
    <div class="app">
      <header class="topbar">
        <h1>Strudelizer</h1>
        <span class="subtitle">{song?.meta.title ?? 'Turn a song into Strudel'}</span>
        <div class="spacer" />
        <span class="badge">{catalog ? `v${catalog.version}` : 'connecting'}</span>
      </header>

      <div class="layout">
        <div class="column">
          <InputPanel store={store} />
        </div>

        <div class="column">
          <section class="panel" aria-labelledby="code-heading">
            <header>
              <h2 id="code-heading">Strudel code</h2>
              <div class="spacer" />
              {busy === 'convert' && <span class="spinner" role="status" aria-label="Converting" />}
            </header>
            {error ? (
              <pre class="code" style="color:var(--error)">{error.text}</pre>
            ) : code ? (
              <pre class="code">{code}</pre>
            ) : (
              <p class="empty-state">Drop in a song to see its Strudel code.</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
