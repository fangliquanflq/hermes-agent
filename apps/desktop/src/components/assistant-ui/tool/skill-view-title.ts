import { translateNow } from '@/i18n'
import { firstStringField } from '@/lib/text'

import { parseMaybeObject } from './fallback-model/format'

interface SkillViewCall {
  args?: unknown
  isError?: boolean
  result?: unknown
}

/** A skill_view title shared by the row and its collapsed run summary. */
export function skillViewTitle(call: SkillViewCall): string {
  const args = parseMaybeObject(call.args)
  const result = parseMaybeObject(call.result)
  const name = firstStringField(args, ['name'])

  if (!name) {
    return ''
  }

  const resource = firstStringField(args, ['file_path'])

  const failed =
    call.isError || result.success === false || result.ok === false || Boolean(firstStringField(result, ['error']))

  const state = failed ? 'failed' : call.result === undefined ? 'pending' : 'done'

  return resource
    ? translateNow(`assistant.tool.skill.resource.${state}`, resource, name)
    : translateNow(`assistant.tool.skill.instruction.${state}`, name)
}