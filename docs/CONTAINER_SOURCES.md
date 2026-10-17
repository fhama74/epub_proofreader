# Container sources and licenses

This release accompanies the container built from its target commit.
The image is an aggregate of separately licensed components; the MIT license
applies to the original EPUB Proofreader code only.

Each architecture's source archive includes the exact Debian source packages
for installed packages whose copyright notices refer to GPL/LGPL, including
OpenJDK, with upstream sources, Debian patches and build instructions. It also
contains Debian package versions and copyright notices, and the matching
Saxon-HE 11.4 source archive (MPL-2.0). SHA-256 files identify each archive.
Unmodified certifi source (MPL-2.0) is installed as Python source in the image.

Application sources, Dockerfile and build scripts are available at the exact
commit of this release using GitHub's source archive downloads. Component
licenses remain inside the image: `/app/LICENSE`, `/app/THIRD_PARTY_NOTICES.md`,
`/app/frontend/dist/licenses`, `/app/frontend/dist/pdfjs`, installed Python
package metadata, `/app/.tools/epubcheck-5.4.0`, `/usr/share/doc` and
`/usr/share/common-licenses`.

Retain these releases while distributing their images. Rebuilding an image
requires collecting new matching sources; do not substitute source archives
from an older image. Sources are separate downloads so normal installation
does not download large source archives.
