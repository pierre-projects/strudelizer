// One store for the whole page: what was dropped in, the options around it, and
// the IR and code that come back. Importer options re-import; everything else
// only re-converts, and both are debounced so typing in a number box does not
// fire a request per keystroke.
import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { ApiError, convert, getCatalog, importSource } from './api';
import type { Catalog, ErrorDetail, PassEntry, Problem, Song } from './types';

export type Source =
  | { kind: 'file'; name: string; file: File }
  | { kind: 'text'; name: string; text: string };

/** Pass order a musician expects: build the parts, change them, then tidy up. */
const PASS_ORDER = ['arrange', 'transpose', 'remap_drums', 'detect_sections', 'quantize', 'dedupe_bars'];
const IMPORT_DELAY = 400;
const CONVERT_DELAY = 250;

export function useStrudelizer() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [source, setSourceState] = useState<Source | null>(null);
  const [importer, setImporter] = useState<string | null>(null);
  const [importerOptions, setImporterOptions] = useState<Record<string, unknown>>({});
  const [passes, setPassesState] = useState<PassEntry[]>([]);
  const [profile, setProfile] = useState('default');
  const [song, setSong] = useState<Song | null>(null);
  const [processed, setProcessed] = useState<Song | null>(null);
  const [code, setCode] = useState('');
  const [editedCode, setEditedCode] = useState<string | null>(null);
  const [muted, setMuted] = useState<string[]>([]);
  const [soloed, setSoloed] = useState<string[]>([]);
  const [importWarnings, setImportWarnings] = useState<Problem[]>([]);
  const [convertWarnings, setConvertWarnings] = useState<Problem[]>([]);
  const [error, setError] = useState<Problem | null>(null);
  const [busy, setBusy] = useState<'import' | 'convert' | null>(null);
  // A line the song view or the problems panel asked the editor to show. The
  // counter makes asking twice for the same line count twice.
  const [revealed, setRevealed] = useState<{ line: number; nth: number } | null>(null);
  // The same, for a line of the pasted source a warning complains about.
  const [revealedSource, setRevealedSource] = useState<{ line: number; nth: number } | null>(null);
  const reveals = useRef(0);

  // The pass list is rebuilt for a new song only while the user has left it alone.
  const passesTouched = useRef(false);
  const importSeq = useRef(0);
  const convertSeq = useRef(0);

  useEffect(() => {
    getCatalog().then(
      (loaded) => {
        setCatalog(loaded);
        setPassesState(initialPasses(loaded));
        const strudel = loaded.emitters.find((emitter) => emitter.name === 'strudel');
        const option = strudel?.options?.find((o) => o.name === 'profile');
        if (typeof option?.default === 'string') setProfile(option.default);
      },
      (reason) => setError(asProblem(reason)),
    );
  }, []);

  const sourceRef = useRef<Source | null>(null);
  const setSource = useCallback((next: Source | null) => {
    const previous = sourceRef.current;
    sourceRef.current = next;
    setSourceState(next);
    setError(null);
    // Editing pasted text is the same source, so it keeps the options the user
    // has set; dropping in a different file starts again.
    if (!previous || !next || previous.kind !== next.kind || previous.name !== next.name) {
      passesTouched.current = false;
      setImporter(null);
      setMuted([]);
      setSoloed([]);
    }
    if (!next) {
      setSong(null);
      setProcessed(null);
      setCode('');
      setEditedCode(null);
      setImportWarnings([]);
      setConvertWarnings([]);
    }
  }, []);

  const setPasses = useCallback((next: PassEntry[]) => {
    passesTouched.current = true;
    setPassesState(next);
  }, []);

  const updatePass = useCallback(
    (name: string, change: Partial<PassEntry>) =>
      setPasses(passes.map((pass) => (pass.name === name ? { ...pass, ...change } : pass))),
    [passes, setPasses],
  );

  const movePass = useCallback(
    (name: string, by: number) => {
      const from = passes.findIndex((pass) => pass.name === name);
      const to = from + by;
      if (from < 0 || to < 0 || to >= passes.length) return;
      const next = passes.slice();
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      setPasses(next);
    },
    [passes, setPasses],
  );

  // ---- import ---------------------------------------------------------------

  const optionsKey = JSON.stringify(importerOptions);
  useEffect(() => {
    if (!source) return;
    const controller = new AbortController();
    const seq = ++importSeq.current;
    const timer = window.setTimeout(async () => {
      setBusy('import');
      try {
        const result = await importSource(
          {
            file: source.kind === 'file' ? source.file : null,
            text: source.kind === 'text' ? source.text : undefined,
            filename: source.name,
            importer,
            options: JSON.parse(optionsKey),
          },
          controller.signal,
        );
        if (seq !== importSeq.current) return;
        setSong(result.ir);
        setImporter(result.importer);
        setImportWarnings(result.warnings.map((w) => ({ ...w, kind: 'warning' as const })));
        setError(null);
        if (!passesTouched.current && catalog) setPassesState(initialPasses(catalog, result.ir));
      } catch (reason) {
        if (seq !== importSeq.current || isAbort(reason)) return;
        setSong(null);
        setProcessed(null);
        setCode('');
        setImportWarnings([]);
        setError(asProblem(reason));
      } finally {
        if (seq === importSeq.current) setBusy(null);
      }
    }, IMPORT_DELAY);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [source, importer, optionsKey, catalog]);

  // ---- convert ---------------------------------------------------------------

  // Mute and solo name the tracks the emitter sees, which is the song after the
  // passes have run: `arrange` adds drums and bass that the import never had.
  const trackIds = useMemo(
    () => ((processed ?? song)?.tracks ?? []).map((track, i) => track.id ?? `track_${i}`),
    [processed, song],
  );
  const playing = useMemo(
    () => (soloed.length ? trackIds.filter((id) => soloed.includes(id)) : trackIds.filter((id) => !muted.includes(id))),
    [trackIds, muted, soloed],
  );
  const passesKey = JSON.stringify(passes.filter((pass) => pass.enabled).map(({ name, options }) => ({ name, options })));
  const tracksKey = playing.length === trackIds.length ? '' : JSON.stringify(playing);

  useEffect(() => {
    if (!song) return;
    const controller = new AbortController();
    const seq = ++convertSeq.current;
    const timer = window.setTimeout(async () => {
      setBusy('convert');
      try {
        const result = await convert(
          { ir: song, passes: JSON.parse(passesKey), profile, tracks: tracksKey ? JSON.parse(tracksKey) : null },
          controller.signal,
        );
        if (seq !== convertSeq.current) return;
        setCode(result.code);
        setEditedCode(null);
        setProcessed(result.ir);
        setConvertWarnings(result.warnings.map((w) => ({ ...w, kind: 'warning' as const })));
        setError(null);
      } catch (reason) {
        if (seq !== convertSeq.current || isAbort(reason)) return;
        setConvertWarnings([]);
        setError(asProblem(reason));
      } finally {
        if (seq === convertSeq.current) setBusy(null);
      }
    }, CONVERT_DELAY);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [song, passesKey, profile, tracksKey]);

  const reconvert = useCallback(() => {
    if (song) setSong({ ...song });  // a new object identity re-runs the effect
  }, [song]);

  const toggle = useCallback(
    (list: string[], setList: (next: string[]) => void, id: string) =>
      setList(list.includes(id) ? list.filter((other) => other !== id) : [...list, id]),
    [],
  );

  const problems = useMemo<Problem[]>(
    () => [...(error ? [error] : []), ...importWarnings, ...convertWarnings],
    [error, importWarnings, convertWarnings],
  );

  return {
    catalog,
    source,
    setSource,
    importer,
    setImporter,
    importerOptions,
    setImporterOptions,
    passes,
    setPasses,
    updatePass,
    movePass,
    profile,
    setProfile,
    song,
    processed,
    code,
    editedCode,
    setEditedCode,
    effectiveCode: editedCode ?? code,
    dirty: editedCode !== null && editedCode !== code,
    trackIds,
    muted,
    soloed,
    playing,
    toggleMute: (id: string) => toggle(muted, setMuted, id),
    toggleSolo: (id: string) => toggle(soloed, setSoloed, id),
    problems,
    error,
    busy,
    reconvert,
    revealed,
    reveal: useCallback((line: number) => setRevealed({ line, nth: ++reveals.current }), []),
    revealedSource,
    revealSource: useCallback((line: number) => setRevealedSource({ line, nth: ++reveals.current }), []),
  };
}

export type Store = ReturnType<typeof useStrudelizer>;

function initialPasses(catalog: Catalog, song?: Song): PassEntry[] {
  const defaults = new Map(catalog.default_passes.map((pass) => [pass.name, pass.options]));
  // A chord sheet or tab with no rhythm section wants `arrange` from the start;
  // a MIDI file that already has drums and bass does not.
  const needsArrange = song ? !song.tracks.some((track) => track.role === 'drums' || track.role === 'bass') : false;
  return catalog.passes
    .map((info) => {
      const options: Record<string, unknown> = {};
      for (const option of info.options ?? []) {
        if (option.default !== null && option.default !== undefined) options[option.name] = option.default;
      }
      return {
        name: info.name,
        options: { ...options, ...(defaults.get(info.name) ?? {}) },
        enabled: defaults.has(info.name) || (info.name === 'arrange' && needsArrange),
      };
    })
    .sort((a, b) => rank(a.name) - rank(b.name));
}

function rank(name: string): number {
  const index = PASS_ORDER.indexOf(name);
  // An unknown pass runs before dedupe_bars, which has to be last.
  return index === -1 ? PASS_ORDER.indexOf('dedupe_bars') - 0.5 : index;
}

function isAbort(reason: unknown): boolean {
  return reason instanceof Error && reason.name === 'AbortError';
}

function asProblem(reason: unknown): Problem {
  const detail: ErrorDetail =
    reason instanceof ApiError
      ? reason.detail
      : {
          stage: 'ui',
          message: String((reason as Error)?.message ?? reason),
          location: null,
          fix: null,
          text: `error [ui]: ${String((reason as Error)?.message ?? reason)}`,
        };
  return { ...detail, kind: 'error' };
}
