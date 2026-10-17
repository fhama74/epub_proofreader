# Third-party components

The MIT license in LICENSE applies to this project's original code. It does
not replace the licenses of dependencies, fonts, Java, or EPUBCheck.
Dependencies are downloaded during installation/build; they are not vendored
in this source repository. Redistribution of a built application or container
must retain upstream notices and comply with the licenses of its contents.

## Frontend runtime

- React, React DOM, Scheduler: MIT (https://github.com/facebook/react).
- PDF.js / pdfjs-dist: Apache-2.0 (https://github.com/mozilla/pdf.js).
- PDF.js CMaps: Adobe BSD-style terms; Foxit fonts and JBIG2/PDFium: BSD-style;
  Liberation fonts: SIL Open Font License 1.1; OpenJPEG: BSD-style;
  QCMS: MIT. See the upstream license files shipped with each asset.

The asset preparation script preserves PDF.js and its font/CMap/WASM notices
and copies React runtime license texts to the built frontend's licenses folder.

## Python runtime

FastAPI, Uvicorn, Pydantic and several supporting packages use MIT or BSD
licenses. lxml, HTTPX, Starlette, tinycss2 and cssselect2 use BSD-style licenses.
cryptography uses Apache-2.0 OR BSD-3-Clause; python-multipart uses Apache-2.0;
certifi uses MPL-2.0; typing_extensions uses PSF-2.0. Consult the installed
package metadata and license files for exact versions and transitive notices.

## EPUBCheck and Java

EPUBCheck 5.4.0: BSD-3-Clause, with dependencies under other licenses including
Apache-2.0 and MPL-2.0 (Saxon). The installer keeps the complete official
release, including LICENSE.txt, THIRD-PARTY.txt and licenses/.
https://github.com/w3c/epubcheck

Java is installed separately (by the system package manager in Docker).
OpenJDK uses GPL-2.0 with the Classpath Exception and additional component
notices. This does not change this application's own MIT license. Keep Java
and system package notices and meet applicable source distribution obligations
when redistributing container images. Published images have corresponding
source archives in the matching container-<commit> GitHub release (see
docs/CONTAINER_SOURCES.md). A container includes separately licensed OS packages;
it must not be described as entirely MIT-licensed.
