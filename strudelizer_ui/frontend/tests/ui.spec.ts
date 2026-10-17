// End to end, the way a musician uses the page: drop a song in, change how it
// sounds, play it, save it. Nothing is stubbed; the server is a real
// `strudelize ui` and the editor is the real Strudel REPL.
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

const FIXTURES = new URL('../../../tests/fixtures/', import.meta.url);
const MIDI = new URL('multitrack_repeats.mid', FIXTURES);
const SHEET = new URL('sheets/night_train.txt', FIXTURES);

/** Console errors are a failure in their own right, so every test collects them. */
function watchConsole(page: Page): string[] {
  const problems: string[] = [];
  page.on('console', (message) => message.type() === 'error' && problems.push(message.text()));
  page.on('pageerror', (error) => problems.push(error.message));
  return problems;
}

function editorCode(page: Page): Promise<string> {
  return page.evaluate(() => {
    const element = document.querySelector('strudel-editor') as { editor?: { code?: string } } | null;
    return element?.editor?.code ?? '';
  });
}

test('a MIDI file becomes code that plays, and saves in every format', async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto('/');
  await page.setInputFiles('input[type=file]', fileURLToPath(MIDI));

  await expect(page.locator('.cm-editor')).toBeVisible();
  // The editor element appears a moment before it holds the code.
  await expect.poll(() => editorCode(page)).toContain('setcps(124/60/4)');
  await expect(page.getByRole('heading', { name: 'Arrangement' }).locator('..')).toContainText('8 bars');
  await expect(page.locator('.tracks > li')).toHaveCount(4);

  await page.getByRole('button', { name: 'Play' }).click();
  await expect(page.locator('.badge.live')).toHaveText('playing');

  for (const [button, suffix] of [
    ['Strudel code', '.js'],
    ['MIDI file', '.mid'],
    ['Song data', '.ir.json'],
  ]) {
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: button }).click();
    expect((await download).suggestedFilename()).toBe(`multitrack_repeats${suffix}`);
  }

  await page.getByRole('button', { name: 'Stop' }).click();
  await expect(page.locator('.badge.live')).toHaveCount(0);
  expect(problems).toEqual([]);
});

test('a pasted chord sheet re-converts when an option changes', async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto('/');
  await page.locator('#paste').fill(await readFile(SHEET, 'utf8'));
  await expect(page.locator('.cm-editor')).toBeVisible();

  // A sheet has no rhythm section, so the page offers to add one.
  await expect(page.locator('#pass-arrange')).toBeChecked();
  await expect.poll(() => editorCode(page)).toContain('// Night Train');
  const lofi = await editorCode(page);

  await page.selectOption('#opt-pass-arrange-style', 'four_on_floor');
  await expect.poll(() => editorCode(page)).not.toBe(lofi);

  // An importer option goes back through the importer, not just the passes.
  await page.fill('#opt-importer-chordsheet-bpm', '140');
  await expect.poll(() => editorCode(page)).toContain('setcps(140/60/4)');

  // Strudel's own keys, from outside the editor, and alt+r to convert again.
  await page.keyboard.press('Control+Enter');
  await expect(page.locator('.badge.live')).toHaveText('playing');
  const again = page.waitForRequest('**/api/convert');
  await page.keyboard.press('Alt+r');
  await again;
  await page.keyboard.press('Control+Period');
  await expect(page.locator('.badge.live')).toHaveCount(0);

  expect(problems).toEqual([]);
});

test('the problems panel points at the line it could not read', async ({ page }) => {
  await page.goto('/');
  await page.locator('#paste').fill(await readFile(SHEET, 'utf8'));

  const problem = page.locator('.problems li', { hasText: 'unparsed' });
  await expect(problem).toContainText("not chords: 'Fxx7'");
  await problem.getByRole('button', { name: 'line 16' }).click();
  // The selection is set in an effect after the next render, so wait for it.
  await expect
    .poll(() =>
      page.evaluate(() => {
        const box = document.querySelector('#paste') as HTMLTextAreaElement;
        return box.value.slice(box.selectionStart, box.selectionEnd);
      }),
    )
    .toBe('| Cm | Fxx7 | G7 |');
});

test('clicking a bar shows the code that bar came from', async ({ page }) => {
  await page.goto('/');
  await page.locator('#paste').fill(await readFile(SHEET, 'utf8'));
  await expect.poll(() => editorCode(page)).toContain('const verse');

  await page.locator('.lane.ruler .bar', { hasText: /^6$/ }).click();
  const line = await page.evaluate(() => {
    const element = document.querySelector('strudel-editor') as { editor?: { editor?: any } } | null;
    const view = element?.editor?.editor;
    return view.state.doc.lineAt(view.state.selection.main.head).number;
  });
  // Bar 6 is in the verse, which is the second const in the file.
  const code = (await editorCode(page)).split('\n');
  expect(code.slice(0, line).reverse().find((text) => text.startsWith('const '))).toContain('verse');
});

test('an unreadable file is reported the way the CLI reports it', async ({ page }) => {
  await page.goto('/');
  await page.locator('#paste').fill('| C | G |');
  await expect(page.locator('.cm-editor')).toBeVisible();

  await page.selectOption('#importer', 'midi');
  const problem = page.locator('.problems li.error');
  await expect(problem).toContainText('not a readable MIDI file');
  await expect(problem).toContainText('fix: re-export the file from your DAW');
  await expect(page.getByRole('button', { name: 'Play' })).toBeDisabled();
});

test('the page works at tablet width and remembers the theme', async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1100 });
  await page.goto('/');
  // One column, and nothing spilling out of it.
  const layout = page.locator('.layout');
  const width = (await layout.boundingBox())!.width;
  for (const panel of await page.locator('.panel').all()) {
    expect((await panel.boundingBox())!.width).toBeLessThanOrEqual(width + 1);
  }

  await page.getByRole('button', { name: /theme/ }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.getByRole('button', { name: /theme/ }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});
