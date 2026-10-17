// Calls to the local backend. Every failure arrives as the same JSON shape, so
// the Problems panel can show the CLI's wording whatever went wrong.
import type { Catalog, ConvertResult, ErrorDetail, ImportResult, PassSpec, Song } from './types';

export class ApiError extends Error {
  constructor(readonly detail: ErrorDetail) {
    super(detail.message);
    this.name = 'ApiError';
  }
}

function fallback(stage: string, message: string): ErrorDetail {
  return { stage, message, location: null, fix: null, text: `error [${stage}]: ${message}` };
}

async function request(path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error;
    throw new ApiError(fallback('ui', 'the Strudelizer server is not responding; is it still running?'));
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.error ?? fallback('ui', `${response.status} ${response.statusText}`));
  }
  return response;
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await request(path, init)).json() as Promise<T>;
}

function post(body: unknown, signal?: AbortSignal): RequestInit {
  return {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  };
}

export function getCatalog(): Promise<Catalog> {
  return json<Catalog>('/api/plugins');
}

export interface ImportInput {
  file?: File | null;
  text?: string;
  filename?: string;
  importer?: string | null;
  options: Record<string, unknown>;
}

export function importSource(input: ImportInput, signal?: AbortSignal): Promise<ImportResult> {
  const form = new FormData();
  if (input.file) form.set('file', input.file, input.file.name);
  if (input.text !== undefined) form.set('text', input.text);
  if (input.filename) form.set('filename', input.filename);
  if (input.importer) form.set('importer', input.importer);
  form.set('options', JSON.stringify(input.options));
  return json<ImportResult>('/api/import', { method: 'POST', body: form, signal });
}

export interface ConvertInput {
  ir: Song;
  passes: PassSpec[];
  profile?: string | null;
  tracks?: string[] | null;
}

export function convert(input: ConvertInput, signal?: AbortSignal): Promise<ConvertResult> {
  return json<ConvertResult>('/api/convert', post(input, signal));
}

export interface ExportInput {
  ir: Song;
  format: string;
  profile?: string | null;
  code?: string | null;
  filename?: string | null;
  tracks?: string[] | null;
}

/** Download a generated file. The browser never uploads anything to do it. */
export async function exportFile(input: ExportInput): Promise<string> {
  const response = await request('/api/export', post(input));
  const name = filenameFrom(response.headers.get('content-disposition')) ?? `song.${input.format}`;
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoking straight away can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return name;
}

function filenameFrom(header: string | null): string | null {
  const match = header?.match(/filename="([^"]+)"/);
  return match ? match[1] : null;
}
