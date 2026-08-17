# Vendored assets

The `.html` architecture pages load Mermaid from **this directory**, not from a Content Delivery
Network:

```html
<script src="assets/mermaid.min.js"></script>
```

**Status: vendored.** `mermaid.min.js` is present here (3,337,857 bytes, Mermaid 10 unified
minified bundle) and an identical copy sits in `frontend/Architecture/assets/`. The diagrams render
with the network disabled — verified by extracting the Mermaid blocks from the built HTML and
parsing them through this bundle headlessly.

## Why local, and not a Content Delivery Network

This is a Final Year Project that gets demonstrated in a viva room. A diagram that fails to render
because the network is unreliable is worse than a static image. Vendoring also means the pages open
correctly from the filesystem with the network off, which is one of the Phase 0 verification steps.

A deliberate departure from the house pattern at `MySwiftlyApp`, which loads Mermaid from
`cdn.jsdelivr.net` and tells the reader to open the pages online.

## Re-fetching or upgrading

Only needed to move off Mermaid 10. **Pin the major version to 10** — the pages call
`mermaid.initialize({ startOnLoad: true, … })` with an `er:` block, which is the Mermaid 10
application programming interface.

```bash
curl -L https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js -o backend/Architecture/assets/mermaid.min.js
```

```bash
cp backend/Architecture/assets/mermaid.min.js frontend/Architecture/assets/mermaid.min.js
```

## Theme note — do not lose this

The shared HTML shell sets `primaryTextColor: '#e6edf3'` for the dark page, but Mermaid's base
theme leaves the entity-relationship **attribute rows** light. Together those produced near-white
text on near-white rows, and every column in every table was unreadable. Both backend pages and the
frontend page therefore set the row colours explicitly:

```js
attributeBackgroundColorOdd: '#161b22',
attributeBackgroundColorEven: '#1c2230',
```

Removing those two lines silently makes every entity-relationship diagram illegible again. If the
white-table look is ever wanted instead, flip them to `#ffffff`/`#f2f2f2` **and** find the correct
selector for the attribute text by rendering headlessly — do not guess it.

## Tooling

Both `Architecture/assets/**` (ESLint) and `Architecture/` (Prettier) are excluded on the frontend
side, because linting a 3.3 MB minified bundle produces hundreds of errors and reformatting the
HTML rewrites the indentation-significant Mermaid blocks so the diagrams stop parsing.

`.gitignore` does not exclude this directory, so `git add backend/Architecture/assets/mermaid.min.js`
commits it. Roughly 3 MB per copy; that is the price of the pages working offline, paid once.
