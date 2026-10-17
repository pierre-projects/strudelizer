import { CodePanel } from './components/CodePanel';
import { InputPanel } from './components/InputPanel';
import { useStrudelizer } from './state';

export function App() {
  const store = useStrudelizer();
  const { catalog, song } = store;

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
          <CodePanel store={store} reveal={null} />
        </div>
      </div>
    </div>
  );
}
