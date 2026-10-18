import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: false })
markdown.disable('image')
const defaultLink =
  markdown.renderer.rules.link_open ||
  ((tokens, index, options, env, renderer) => renderer.renderToken(tokens, index, options))
markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return defaultLink(tokens, index, options, env, renderer)
}
markdown.renderer.rules.table_open = () =>
  '<div class="ai-table-scroll" tabindex="0" role="region" aria-label="回答中的表格"><table>\n'
markdown.renderer.rules.table_close = () => '</table></div>\n'

export function renderAiMarkdown(content) {
  return markdown.render(content || '')
}
