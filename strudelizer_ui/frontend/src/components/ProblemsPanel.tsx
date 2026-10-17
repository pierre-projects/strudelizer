// Everything Strudelizer had to say about this song, worded exactly as the CLI
// words it, and clickable: a problem that names a line of the pasted sheet
// selects that line, one that names a bar scrolls the code to it.
import { barIndex, locateBar } from '../song';
import type { Store } from '../state';
import type { Problem } from '../types';

export function ProblemsPanel({ store }: { store: Store }) {
  const { problems, source } = store;
  const song = store.processed ?? store.song;

  // Only pasted text has lines the user can be shown; a file has none.
  function target(problem: Problem): { label: string; go: () => void } | null {
    if (problem.line !== undefined && source?.kind === 'text') {
      return { label: `line ${problem.line}`, go: () => store.revealSource(problem.line as number) };
    }
    if (problem.bar !== undefined && song) {
      const line = locateBar(store.effectiveCode, song, barIndex(song, problem.bar));
      if (line) return { label: `bar ${problem.bar}`, go: () => store.reveal(line) };
    }
    return null;
  }

  return (
    <section class="panel" aria-labelledby="problems-heading">
      <header>
        <h2 id="problems-heading">Problems</h2>
        {problems.length > 0 && <span class="badge">{problems.length}</span>}
      </header>
      <div class="body">
        {problems.length === 0 ? (
          <p class="small muted">
            {song ? 'Nothing to report: the whole song was understood.' : 'Warnings about the song appear here.'}
          </p>
        ) : (
          <ul class="problems">
            {problems.map((problem, index) => {
              const where = target(problem);
              return (
                <li key={`${problem.text}-${index}`} class={problem.kind}>
                  <div class="row">
                    <span class="tag">{problem.kind}</span>
                    <code class="small">{problem.stage}</code>
                    {where && (
                      <button type="button" class="link small" onClick={where.go}>
                        {where.label}
                      </button>
                    )}
                  </div>
                  <p>{problem.message}</p>
                  {problem.location && <p class="small muted">at {problem.location}</p>}
                  {problem.fix && <p class="small fix">fix: {problem.fix}</p>}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
