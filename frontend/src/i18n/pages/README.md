One file per module/page group: `export const en = {...}; export const hi = {...}; export const ta = {...};`
Keys are namespaced by module (e.g. "jobs.title"). They are merged into the main bundles by
`i18n/index.tsx` (`import.meta.glob("./pages/*.ts")`), so modules never edit a shared file.
