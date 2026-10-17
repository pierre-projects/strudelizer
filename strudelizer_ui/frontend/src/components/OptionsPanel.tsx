// Every control on this panel is generated from /api/plugins: the importer's
// own options, the sound profile, and the ordered list of passes with theirs.
// Installing a plugin is enough to make its options appear here.
import { CustomOptions, OptionControl } from './OptionControl';
import type { Store } from '../state';
import type { Catalog, OptionSpec, PluginInfo } from '../types';

export function OptionsPanel({ store }: { store: Store }) {
  const {
    catalog,
    importer,
    importerOptions,
    setImporterOptions,
    passes,
    updatePass,
    movePass,
    profile,
    setProfile,
    song,
  } = store;
  if (!catalog) return null;

  const importerInfo = catalog.importers.find((info) => info.name === importer);
  const strudel = catalog.emitters.find((info) => info.name === 'strudel');
  // The pipeline hands emitters only the profile, so that is the one to show.
  const profileSpec = strudel?.options?.find((option) => option.name === 'profile');

  return (
    <section class="panel" aria-labelledby="options-heading">
      <header>
        <h2 id="options-heading">Options</h2>
      </header>
      <div class="body">
        {!song && <p class="small muted">Options appear once a song is loaded.</p>}

        {profileSpec && (
          <OptionControl
            id="opt-profile"
            spec={profileSpec}
            value={profile}
            catalog={catalog}
            onChange={(value) => setProfile(String(value) || 'default')}
          />
        )}

        {importerInfo && (importerInfo.options?.length || importerInfo.custom) && (
          <>
            <h3 title={importerInfo.summary}>{importerInfo.label}</h3>
            <PluginOptions
              kind="importer"
              info={importerInfo}
              catalog={catalog}
              options={importerOptions}
              onChange={setImporterOptions}
            />
          </>
        )}

        <h3>Steps</h3>
        <ul class="passes">
          {passes.map((pass, index) => {
            const info = catalog.passes.find((candidate) => candidate.name === pass.name);
            if (!info) return null;
            return (
              <li key={pass.name} class={pass.enabled ? '' : 'off'}>
                <div class="row">
                  <input
                    type="checkbox"
                    id={`pass-${pass.name}`}
                    checked={pass.enabled}
                    onChange={(event) => updatePass(pass.name, { enabled: event.currentTarget.checked })}
                  />
                  <label class="pass-name" for={`pass-${pass.name}`} title={`${pass.name}: ${info.summary}`}>
                    {info.label}
                  </label>
                  <span class="handle">
                    <button
                      type="button"
                      aria-label={`Run ${info.label} earlier`}
                      disabled={index === 0}
                      onClick={() => movePass(pass.name, -1)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      aria-label={`Run ${info.label} later`}
                      disabled={index === passes.length - 1}
                      onClick={() => movePass(pass.name, 1)}
                    >
                      ↓
                    </button>
                  </span>
                </div>
                {pass.enabled && (
                  <PluginOptions
                    kind="pass"
                    info={info}
                    catalog={catalog}
                    options={pass.options}
                    onChange={(options) => updatePass(pass.name, { options })}
                  />
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

function PluginOptions({
  kind,
  info,
  catalog,
  options,
  onChange,
}: {
  kind: string;
  info: PluginInfo;
  catalog: Catalog;
  options: Record<string, unknown>;
  onChange: (options: Record<string, unknown>) => void;
}) {
  const specs = info.options ?? [];
  const common = specs.filter((spec) => spec.group !== 'advanced');
  const advanced = specs.filter((spec) => spec.group === 'advanced');
  const set = (spec: OptionSpec, value: unknown) => onChange({ ...options, [spec.name]: value });
  const id = (spec: OptionSpec) => `opt-${kind}-${info.name}-${spec.name}`;

  return (
    <>
      {common.map((spec) => (
        <OptionControl
          key={spec.name}
          id={id(spec)}
          spec={spec}
          value={options[spec.name]}
          catalog={catalog}
          onChange={(value) => set(spec, value)}
        />
      ))}
      {advanced.length > 0 && (
        <details>
          <summary class="small muted">More</summary>
          {advanced.map((spec) => (
            <OptionControl
              key={spec.name}
              id={id(spec)}
              spec={spec}
              value={options[spec.name]}
              catalog={catalog}
              onChange={(value) => set(spec, value)}
            />
          ))}
        </details>
      )}
      {info.custom && <CustomOptions id={`opt-${kind}-${info.name}-custom`} options={options} onChange={onChange} />}
    </>
  );
}

