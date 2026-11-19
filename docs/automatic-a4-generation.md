# 최종 HTML 생성·저장: 사진 표시와 A4 페이지 이어짐

## Implementation

The real `Processing.report` path now runs: original PDF + saved prompt -> model HTML -> recognized legacy PDF-picker/image-loader cleanup -> source crop binding -> server-side Chromium A4 fragmentation -> offline visibility/layout audit -> append-only artifact save. This is not a download-only repair or a read-time rewrite. Existing SG6 artifacts are not migrated.

The output contract now allows long source-page content to continue on further A4 sheets. The saved HTML itself has 210 x 297 mm border boxes, including short pages; continuations retain the original page number. The server packs DOM blocks, splits long text, splits tables between rows with repeated headers, and fits indivisible images proportionally. No source image crop is changed by pagination. Original body text and image order are checked before accepting a fragmented document. A single table row that cannot fit remains preserved and is flagged; it is not clipped or silently certified.

Image visibility is repaired in the saved final document, including hidden image ancestors. Known obsolete PDF picker/loading scripts are removed by the existing preparation step. Final acceptance still requires the existing JavaScript-on/off, desktop/narrow, offline image and A4 audit to pass. Unresolved slots, unsupported loaders, inaccessible images, or unsplittable overflowing content do not receive a successful completion result.

Raw Terra HTML is immutable. `a4-pagination` records input/final SHA-256, per-source sheet counts, visibility changes, preservation checks and problems. Metadata stores the receipt hash; saved-file reads verify hashes against the original image-binding output and pagination receipt. Text-only later corrections retain their existing parent-report integrity checks. There is no paid API retry.

## Tests

`tests/browser_a4_generation.py` clicks the actual logged-in web generation button against mock HTTP, saves the report, clicks the employee final-report button, downloads the exact file, and renders those downloaded bytes offline with JavaScript disabled. A 25-page synthetic PDF includes a page-9 vector diagram and two page-23 photos; long paragraphs, long tables, the last table row, and short fixed-size pages are checked. The fixture produces 32 A4 sheets, with three visible images, no overflow, and identical narrow-screen dimensions.

Separately, in a private temporary DB, the uploaded SG6 original PDF and its already stored Terra raw response were replayed through that same mocked generation/save/view/download path. It produced 49 A4 sheets with all 28 images visible, including original pages 9 and 23. Customer files and screenshots are excluded from the public repository and source archive. This was not a new model generation, not an operating DB write, and not a new independent verification.

The managed Chromium policy blocks file:// navigation. The downloaded file bytes are therefore rendered in a standalone offline browser document with scripts disabled; direct file:// navigation is not claimed as an executed test. There are no PDF selection controls or external image/PDF.js dependencies in the tested final output.

## Operating limitations

GitHub source deployment, local route verification, and operating server verification remain separate. The connected account exposes no Codespace for the named operating server; its forwarded URL requires a GitHub session. Direct operating confirmation is unavailable. The exact stored independent-verification verdict for SG6 version 1 is **unconfirmed**: the shared screenshot's counts do not establish its stored status value. No new verification was run.

최종 회귀: 단위·HTTP 236개, 실행기 12개 모두 통과. source_sha256 93개와 evidence_sha256 46개 모두 현재 파일과 일치합니다. 실제 유료 모델 호출과 운영 서버 적용은 검증하지 않았습니다.
