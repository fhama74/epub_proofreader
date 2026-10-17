// Copy runtime assets from the SAME pdfjs-dist version as the worker.
// Used for both Vite dev and production; no CDN/network access at runtime.
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { cpSync, mkdirSync } from 'node:fs';
const require = createRequire(import.meta.url);
const source = dirname(require.resolve('pdfjs-dist/package.json'));
const target = resolve(import.meta.dirname, '../public/pdfjs');
mkdirSync(target, {recursive: true});
for (const dir of ['wasm', 'cmaps', 'standard_fonts']) {
  cpSync(resolve(source, dir), resolve(target, dir), {recursive: true});
}
cpSync(resolve(source, 'LICENSE'), resolve(target, 'LICENSE'));

// Preserve the complete MIT notices for runtime code included in the bundle.
const licenseTarget = resolve(import.meta.dirname, '../public/licenses');
mkdirSync(licenseTarget, {recursive: true});
const reactDomSource = dirname(require.resolve('react-dom/package.json'));
const reactDomRequire = createRequire(resolve(reactDomSource, 'package.json'));
for (const name of ['react', 'react-dom', 'scheduler']) {
  const packagePath = name === 'scheduler'
    ? reactDomRequire.resolve(name + '/package.json')
    : require.resolve(name + '/package.json');
  cpSync(resolve(dirname(packagePath), 'LICENSE'), resolve(licenseTarget, name + '-LICENSE.txt'));
}
