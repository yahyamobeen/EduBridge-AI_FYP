'use client'

import 'katex/dist/katex.min.css'
import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'

/**
 * Renders a tutor answer's markdown and LaTeX.
 *
 * The generator returns real markdown and real maths — `**bold**`, `###` headings,
 * bullet and numbered lists, and `$...$` / `$$...$$` carrying `\frac`, `\times` and
 * `^\circ\text{C}`. Rendered as plain text those arrive as literal asterisks and raw
 * `$10^{12}$`, which for a physics tutor means the formulas — the actual content —
 * are the least readable thing on screen.
 *
 * ⚠️ ASSISTANT TEXT ONLY. A student's own message is rendered as plain text by the
 * caller: running their typed input through a markdown pipeline gains nothing and
 * widens what their keystrokes can reach.
 *
 * ⚠️ MODEL OUTPUT IS DATA, NOT MARKUP (`tdd.md` §4.6, prd.md MM-2), so the pipeline
 * is deliberately narrow:
 *   - `rehype-raw` is NOT installed and must never be added. Without it react-markdown
 *     escapes embedded HTML, so a `<script>` or an `onerror=` in a generated answer is
 *     text. Adding it to "support HTML in answers" would make model output executable.
 *   - Links render as TEXT with the href dropped. The system prompt forbids answering
 *     from anything but the pages shown, so any URL here is invented; a fabricated
 *     link presented to a 14-year-old as a textbook citation is the risk, and there is
 *     no legitimate case to weigh against it.
 *   - Images are dropped for the same reason, and would be blocked by the CSP
 *     (`img-src 'self' data:`) anyway. The real figure arrives via `/tutor/figures/{id}`.
 *
 * ⚠️ `throwOnError: false` is what makes this safe to stream. Frames arrive mid-token,
 * so the tree is re-parsed on every chunk against half-written maths — `$$T_F = \frac{9`
 * is a parse error for a few hundred milliseconds on the way to being valid. KaTeX
 * renders the fragment in place instead of throwing, and it resolves as the rest lands.
 */
export function TutorMarkdown({ content }: { content: string }) {
  return (
    <div className="tutor-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
        components={{
          // Headings: the bubble is small, so these are weight and spacing rather
          // than size steps — a `###` inside a chat bubble should not outsize the
          // surrounding page.
          h1: ({ children }) => (
            <p className="mb-1 mt-3 font-semibold first:mt-0">{children}</p>
          ),
          h2: ({ children }) => (
            <p className="mb-1 mt-3 font-semibold first:mt-0">{children}</p>
          ),
          h3: ({ children }) => (
            <p className="mb-1 mt-3 font-semibold first:mt-0">{children}</p>
          ),
          h4: ({ children }) => (
            <p className="mb-1 mt-3 font-semibold first:mt-0">{children}</p>
          ),
          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          ul: ({ children }) => (
            <ul className="mb-2 list-disc space-y-1 ps-5 last:mb-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-2 list-decimal space-y-1 ps-5 last:mb-0">{children}</ol>
          ),
          li: ({ children }) => <li className="[&>p]:mb-0">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          code: ({ children }) => (
            <code className="rounded bg-surface-container-highest px-1 py-0.5 text-body-sm">
              {children}
            </code>
          ),
          pre: ({ children }) => (
            <pre className="mb-2 overflow-x-auto rounded bg-surface-container-highest p-2 text-body-sm last:mb-0">
              {children}
            </pre>
          ),
          hr: () => <hr className="my-3 border-outline-variant/40" />,
          blockquote: ({ children }) => (
            <blockquote className="mb-2 border-s-2 border-outline-variant/50 ps-3 last:mb-0">
              {children}
            </blockquote>
          ),
          // A generated table is wrapped so a wide one scrolls inside the bubble
          // instead of stretching it past the conversation column.
          table: ({ children }) => (
            <div className="mb-2 overflow-x-auto last:mb-0">
              <table className="w-full text-body-sm">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-outline-variant/40 px-2 py-1 text-start font-semibold">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-outline-variant/40 px-2 py-1">{children}</td>
          ),
          // See the href/image note above.
          a: ({ children }) => <>{children}</>,
          img: () => null,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
