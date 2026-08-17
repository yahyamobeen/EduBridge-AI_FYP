# Vendored assets

`mermaid.min.js` here is an **identical copy** of
[`../../../backend/Architecture/assets/mermaid.min.js`](../../../backend/Architecture/assets/mermaid.min.js)
(3,337,857 bytes, Mermaid 10 unified minified bundle). Two copies rather than a shared one, so
neither `Architecture/` folder depends on the other's path surviving a move.

The reasoning, the upgrade commands, and the entity-relationship theme note that must not be lost
all live in [the backend copy's README](../../../backend/Architecture/assets/README.md). Read that
one; keep the two bundles at the same version.

`Architecture/assets/**` is excluded from ESLint and `Architecture/` from Prettier — linting a
3.3 MB minified bundle produces hundreds of errors, and reformatting the HTML rewrites the
indentation-significant Mermaid blocks so the diagrams stop parsing.
