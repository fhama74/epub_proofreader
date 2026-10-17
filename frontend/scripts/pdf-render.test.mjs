import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createRequire } from 'node:module';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';
const require = createRequire(import.meta.url);
const pdfRequire = createRequire(require.resolve('pdfjs-dist/package.json'));
const { createCanvas } = pdfRequire('@napi-rs/canvas');
const assets = resolve(import.meta.dirname, '../public/pdfjs');
async function verifyPages(file, pages) {
  const task = getDocument({
    data: new Uint8Array(readFileSync(file)),
    wasmUrl: `${assets}/wasm/`,
    cMapUrl: `${assets}/cmaps/`, cMapPacked: true,
    standardFontDataUrl: `${assets}/standard_fonts/`,
    useSystemFonts: false,
  });
  try {
    const pdf = await task.promise;
    for (const number of pages) {
      const page = await pdf.getPage(number);
      const viewport = page.getViewport({scale: 2});
      const canvas = createCanvas(Math.ceil(viewport.width), Math.ceil(viewport.height));
      const context = canvas.getContext('2d');
      await page.render({canvas, canvasContext: context, viewport}).promise;
      const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
      let dark = 0;
      for (let i = 0; i < data.length; i += 4) if (data[i] < 100 && data[i + 3] > 0) dark++;
      assert.ok(dark > 100, `page ${number} is blank (${dark} dark pixels)`);
      console.log(`page ${number}: ${dark} dark pixels`);
      page.cleanup();
    }
  } finally { await task.destroy(); }
}
test('bundled CCITT/JBIG2 and JPEG2000 wasm binaries exist', () => {
  for (const name of ['jbig2.wasm', 'openjpeg.wasm']) {
    assert.deepEqual(readFileSync(`${assets}/wasm/${name}`).subarray(0, 4), Buffer.from([0,97,115,109]));
  }
});
test('all six pages render when compression switches from JPEG to CCITT', async () => {
  await verifyPages(resolve(import.meta.dirname, '../../samples/decoder-regression.pdf'), [1,2,3,4,5,6,4,1]);
});
test('user-provided scan renders after page 3', {skip: !process.env.EPROOF_TEST_PDF}, async () => {
  await verifyPages(process.env.EPROOF_TEST_PDF, [4,5,6,10,100,200]);
});
