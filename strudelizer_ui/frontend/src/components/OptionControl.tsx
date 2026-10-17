// One control, drawn from one option description. Nothing here knows the name
// of any particular option, so an option a plugin adds appears on its own.
import type { Catalog, OptionSpec } from '../types';

interface Props {
  id: string;
  spec: OptionSpec;
  value: unknown;
  catalog: Catalog;
  onChange: (value: unknown) => void;
}

export function OptionControl({ id, spec, value, catalog, onChange }: Props) {
  // The musician-facing label carries the technical spelling in its tooltip.
  const tooltip = spec.help ? `${spec.name}: ${spec.help}` : spec.name;
  const text = value === undefined || value === null ? '' : String(value);

  return (
    <div class="field">
      <label for={id} title={tooltip}>
        {spec.label}
        {spec.unit && <span class="unit">{spec.unit}</span>}
      </label>
      {spec.type === 'select' ? (
        // An unset option means "use the default", so show the default.
        <select
          id={id}
          title={tooltip}
          value={text === '' && spec.default != null ? String(spec.default) : text}
          onChange={(e) => onChange(e.currentTarget.value)}
        >
          {/* An option whose default is null means "let Strudelizer decide". */}
          {(spec.default === null || spec.default === undefined) && (
            <option value="">{spec.placeholder ?? 'default'}</option>
          )}
          {choicesFor(catalog, spec).map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      ) : spec.type === 'boolean' ? (
        <input
          id={id}
          type="checkbox"
          title={tooltip}
          checked={Boolean(value)}
          onChange={(e) => onChange(e.currentTarget.checked)}
        />
      ) : spec.type === 'text' ? (
        <input
          id={id}
          type="text"
          title={tooltip}
          value={text}
          placeholder={spec.placeholder ?? ''}
          onInput={(e) => onChange(e.currentTarget.value)}
        />
      ) : (
        <input
          id={id}
          type="number"
          title={tooltip}
          value={text}
          min={spec.min}
          max={spec.max}
          step={spec.step ?? (spec.type === 'integer' ? 1 : 'any')}
          placeholder={spec.placeholder ?? ''}
          onInput={(e) => {
            const raw = e.currentTarget.value;
            onChange(raw === '' ? '' : Number(raw));
          }}
        />
      )}
    </div>
  );
}

export function choicesFor(catalog: Catalog, spec: OptionSpec): string[] {
  if (spec.choices_from === 'styles') return catalog.styles.map((style) => style.name);
  if (spec.choices_from === 'profiles') return catalog.profiles.map((profile) => profile.name);
  return spec.choices ?? [];
}

/** Options a plugin declares but nobody describes: a plain key=value box. */
export function CustomOptions({
  id,
  options,
  onChange,
}: {
  id: string;
  options: Record<string, unknown>;
  onChange: (options: Record<string, unknown>) => void;
}) {
  const text = Object.entries(options)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n');
  return (
    <div>
      <label class="small muted" for={id}>
        Options, one <code>key=value</code> a line
      </label>
      <textarea
        id={id}
        rows={2}
        spellcheck={false}
        value={text}
        onChange={(event) => onChange(parsePairs(event.currentTarget.value))}
      />
    </div>
  );
}

function parsePairs(text: string): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const line of text.split('\n')) {
    const at = line.indexOf('=');
    if (at <= 0) continue;
    out[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return out;
}
