import { useEffect } from 'preact/hooks';
import { CodePanel } from './components/CodePanel';
import { ExportPanel } from './components/ExportPanel';
import { InputPanel } from './components/InputPanel';
import { OptionsPanel } from './components/OptionsPanel';
import { ProblemsPanel } from './components/ProblemsPanel';
import { SongView } from './components/SongView';
import { useStrudelizer } from './state';
import { useTheme } from './theme';

export function App() {
  const store = useStrudelizer();
  const { catalog, song, reconvert } = store;
  const [theme, toggleTheme] = useTheme();

  // alt+r: convert again, for when a pass is not deterministic or a plugin
  // changed under the running server.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey && event.key.toLowerCase() === 'r') {
        event.preventDefault();
        reconvert();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [reconvert]);

  return (
    <div class="app">
      <header class="topbar">
        <h1>Strudelizer</h1>
        <span class="subtitle">{song?.meta.title ?? 'Turn a song into Strudel'}</span>
        <div class="spacer" />
        <button
          type="button"
          class="tiny"
          aria-pressed={theme === 'light'}
          title="Switch between the dark and light theme"
          onClick={toggleTheme}
        >
          {theme === 'dark' ? 'Light' : 'Dark'} theme
        </button>
        <span class="badge" title="The Strudelizer this page is talking to">
          {catalog ? `v${catalog.version}` : 'connecting'}
        </span>
      </header>

      <div class="layout">
        <div class="column">
          <InputPanel store={store} />
          <OptionsPanel store={store} />
        </div>

        <div class="column">
          <CodePanel store={store} theme={theme} />
          <SongView store={store} />
          <ProblemsPanel store={store} />
          <ExportPanel store={store} />
        </div>
      </div>
    </div>
  );
}
