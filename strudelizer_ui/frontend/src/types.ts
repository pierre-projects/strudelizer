// The shapes the API sends. The Song IR mirrors strudelizer/core/schema.json;
// times are exact fractions written as strings ("0", "7/2", "1/3").

export type Frac = string;

export interface NoteEvent {
  type: 'note';
  start: Frac;
  duration: Frac;
  pitch: number;
  velocity?: number;
}

export interface HitEvent {
  type: 'hit';
  start: Frac;
  drum: string;
  velocity?: number;
}

export interface ChordEvent {
  type: 'chord';
  start: Frac;
  duration: Frac;
  symbol: string;
  root?: string;
  quality?: string;
  extensions?: string[];
  bass?: string;
  pitches?: number[];
}

export type IrEvent = NoteEvent | HitEvent | ChordEvent;

export interface IrTrack {
  id?: string;
  role?: string;
  instrument?: string;
  bars?: number[];
  events: IrEvent[];
}

export interface IrSection {
  name?: string;
  start_bar: number;
  length: number;
}

export interface IrMeta {
  title?: string;
  bpm?: number;
  time_signature?: [number, number];
  key?: string;
  source?: string;
  pickup_beats?: Frac;
}

export interface Song {
  version: string;
  meta: IrMeta;
  sections: IrSection[];
  tracks: IrTrack[];
}

// ---- plugins and their options ---------------------------------------------

export type OptionType = 'number' | 'integer' | 'text' | 'select' | 'boolean';

export interface OptionSpec {
  name: string;
  label: string;
  type: OptionType;
  default: unknown;
  help: string;
  group: 'common' | 'advanced';
  choices?: string[];
  /** Fill the choices from another part of the catalog, e.g. the styles. */
  choices_from?: 'styles' | 'profiles';
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
}

export interface PluginInfo {
  name: string;
  /** What to call it on screen; `name` is the technical spelling. */
  label: string;
  summary: string;
  distribution: string;
  /** null when nobody describes this plugin's options: see `custom`. */
  options: OptionSpec[] | null;
  /** The options are unknown, so offer a key=value editor. */
  custom: boolean;
  broken: boolean;
}

export interface ImporterInfo extends PluginInfo {
  extensions: string[];
}

export interface PassInfo extends PluginInfo {
  default_option: string | null;
}

export interface EmitterInfo extends PluginInfo {
  extension: string;
  format: string;
  binary: boolean;
  writes_ir: boolean;
}

export interface UninstalledInfo {
  kind: string;
  name: string;
  extensions: string[];
  install: string;
  missing: string[];
}

export interface Catalog {
  version: string;
  importers: ImporterInfo[];
  passes: PassInfo[];
  emitters: EmitterInfo[];
  profiles: PluginInfo[];
  styles: PluginInfo[];
  default_passes: { name: string; options: Record<string, unknown> }[];
  /** The emitter the pipeline uses unless told otherwise, usually `strudel`. */
  default_emitter: string;
  accept: string[];
  uninstalled: UninstalledInfo[];
}

// ---- problems ---------------------------------------------------------------

export interface Problem {
  kind: 'warning' | 'error';
  stage: string;
  message: string;
  text: string;
  location?: string | null;
  fix?: string | null;
  /** Source line of pasted text, when the message names one. */
  line?: number;
  bar?: number;
}

export interface ErrorDetail {
  stage: string;
  message: string;
  location: string | null;
  fix: string | null;
  text: string;
  line?: number;
  bar?: number;
}

// ---- requests ----------------------------------------------------------------

export interface PassSpec {
  name: string;
  options: Record<string, unknown>;
}

/** A pass in the UI's list: same as PassSpec plus whether it runs. */
export interface PassEntry extends PassSpec {
  enabled: boolean;
}

export interface ImportResult {
  ir: Song;
  importer: string;
  warnings: Omit<Problem, 'kind'>[];
}

export interface ConvertResult {
  code: string;
  ir: Song;
  warnings: Omit<Problem, 'kind'>[];
}
