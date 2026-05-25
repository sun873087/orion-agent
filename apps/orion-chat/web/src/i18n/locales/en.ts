/** English messages. 加 key 時 4 個 locale(zh-TW/zh-CN/en/ja)都要同步。 */

const messages: Record<string, string> = {
  'common.loading': 'Loading…',
  'common.save': 'Save',
  'common.saving': 'Saving…',
  'common.cancel': 'Cancel',
  'common.delete': 'Delete',
  'common.close': 'Close',
  'common.error': 'Error',

  'sidebar.newChat': 'New chat',
  'sidebar.recents': 'Recents',
  'sidebar.noConversations': 'No conversations yet.',
  'sidebar.deleteConfirm': 'Delete this conversation?',
  'sidebar.expand': 'Expand sidebar',
  'sidebar.collapse': 'Collapse sidebar',
  'sidebar.userMenu': 'User menu',
  'sidebar.settings': 'Settings',
  'sidebar.logout': 'Log out',
  'sidebar.msgCount': '{n} msg',
  'sidebar.untitled': 'Untitled',
  'sidebar.rename': 'Rename',
  'sidebar.renamePrompt': 'New conversation title:',
  'sidebar.star': 'Star',
  'sidebar.unstar': 'Unstar',
  'sidebar.branch': 'Branch',

  'settings.title': 'Settings',
  'settings.tab.general': 'General',
  'settings.avatar.title': 'Avatar / icon',
  'settings.avatar.hint':
    'Shown as you in the sidebar. Cropped to a 256×256 square, stored in this browser.',
  'settings.avatar.pick': 'Pick image',
  'settings.avatar.change': 'Change',
  'settings.avatar.remove': 'Remove',
  'settings.tab.models': 'Model',
  'settings.model.defaultHeading': 'Default model for new chats',
  'settings.model.defaultHint':
    'Applies to chats you start next; existing chats are unchanged.',
  'settings.model.loading': 'Loading models…',
  'settings.model.failed': 'Failed to load the model list.',
  'settings.model.keySet': 'API key set',
  'settings.model.keyMissing': 'No API key',
  'settings.model.voiceHeading': 'Voice input (STT)',
  'settings.model.sttOn': 'Available — a mic button shows in the composer.',
  'settings.model.sttOff': 'No voice provider key configured; mic button hidden.',
  'chat.readAloud': 'Read aloud',
  'chat.role.title': 'Role / persona (injected into the system prompt)',
  'chat.role.none': 'No role',
  'chat.project.title': 'Project (shared instructions / workspace)',
  'chat.project.none': 'No project',
  'chat.slash.compact': 'Compact the conversation to free up context',
  'chat.slash.plan': 'Enter Plan Mode — plan first, then act',
  'chat.slash.context': 'Open the side panel to see context usage',
  'chat.slash.schedule': 'Manage scheduled tasks',
  'chat.slash.skill': 'Skill',
  'settings.tab.memory': 'Memory',
  'settings.tab.connections': 'Connections',
  'settings.appearance.title': 'Appearance',
  'settings.appearance.system': 'Follow system',
  'settings.appearance.light': 'Light',
  'settings.appearance.dark': 'Dark',
  'settings.appearance.current': 'Currently {theme}.',
  'settings.appearance.currentSystem':
    'Currently {theme} (from OS preference).',
  'settings.language.title': 'Language',
  'settings.instructions.dbRequired':
    'Custom Instructions require ORION_DB_URL on the backend.',
  'settings.instructions.aboutYou': 'About you',
  'settings.instructions.aboutYouHint':
    'Persistent across all conversations. Tell Orion how to address you, your role, your preferences.',
  'settings.instructions.aboutYouPlaceholder':
    "e.g. I'm a senior Python engineer; prefer terse explanations.",
  'settings.instructions.saved': '✓ Saved {time}',

  'common.new': 'New',
  'common.edit': 'Edit',

  'settings.tab.skills': 'Skills',
  'settings.tab.roles': 'Roles',
  'settings.tab.soul': 'Soul',
  'settings.tab.projects': 'Projects',
  'settings.tab.schedules': 'Schedules',

  'settings.schedules.title': 'Schedules',
  'settings.schedules.desc':
    'Cron schedules that run a prompt automatically (background runner is a follow-up).',
  'settings.schedules.empty': 'No schedules yet.',
  'settings.schedules.runNow': 'Run now',
  'settings.schedules.namePlaceholder': 'Schedule name',
  'settings.schedules.payloadPlaceholder': 'Prompt to run',

  'settings.projects.title': 'Projects',
  'settings.projects.desc':
    'Group conversations and attach project instructions.',
  'settings.projects.empty': 'No projects yet.',
  'settings.projects.namePlaceholder': 'Project name',
  'settings.projects.instructionsPlaceholder':
    'Project instructions (optional)',
  'settings.projects.deleteConfirm': 'Delete this project?',

  'settings.skills.title': 'Skills',
  'settings.skills.desc':
    'Reusable instructions Orion can load on demand. Stored per-user.',
  'settings.skills.empty': 'No editable skills yet.',
  'settings.skills.readonly': 'built-in',
  'settings.skills.nameLabel': 'Name',
  'settings.skills.nameHint': 'identifier — letters, digits, . _ -',
  'settings.skills.descLabel': 'Description',
  'settings.skills.bodyLabel': 'Instructions',
  'settings.skills.coworkVisible': 'Show in skill menu',
  'settings.skills.newTitle': 'New skill',
  'settings.skills.editTitle': 'Edit skill',
  'settings.skills.deleteConfirm': 'Delete skill "{name}"?',

  'settings.roles.title': 'Roles',
  'settings.roles.desc':
    'Personas that adjust the system prompt and default tools.',
  'settings.roles.empty': 'No editable roles yet.',
  'settings.roles.bodyLabel': 'Prompt addendum',
  'settings.roles.disabledTools': 'Disabled tools (comma-separated)',
  'settings.roles.permissionMode': 'Default permission mode',
  'settings.roles.modeDefault': '— default —',
  'settings.roles.newTitle': 'New role',
  'settings.roles.editTitle': 'Edit role',
  'settings.roles.deleteConfirm': 'Delete role "{name}"?',

  'settings.soul.title': 'Soul',
  'settings.soul.desc':
    'A first-person note Orion keeps about you, injected into every new conversation.',
  'settings.soul.placeholder': 'What should Orion remember about you?',
  'settings.soul.clear': 'Clear',
  'settings.soul.clearConfirm': 'Clear your soul note?',

  'chat.budget': 'Budget',
  'chat.budgetPrompt':
    'Cost cap for this conversation in USD (blank = no limit):',
  'chat.budgetBanner': 'Budget cap reached — raise it to keep chatting.',
  'chat.autoCompactBanner':
    'Context is getting long. Compact to free up space.',
  'chat.compactNow': 'Compact now',

  'panel.toggle': 'Details',
  'panel.progress': 'Progress',
  'panel.skills': 'Skills used',
  'panel.cost': 'Tokens & cost',
  'panel.empty': 'Nothing yet',
  'panel.tokensTotal': '{n} tokens total',
  'panel.tokensIO': 'in {in} · out {out}',
  'panel.tokensCache': 'cache {n}',
  'panel.noUsage': 'No usage yet',
  'panel.origin.chat': 'Chat',
  'panel.origin.title': 'Title gen',
  'panel.origin.followUps': 'Follow-ups',
  'panel.messages': '{n} messages',

  'chat.permMode': 'Permission mode',
  'chat.permAsk': 'Ask',
  'chat.permAct': 'Auto',

  'chat.plan': 'Plan',
  'chat.planActive': 'Planning',
  'plan.approveTitle': 'Review plan',
  'plan.approve': 'Approve & run',
  'plan.reject': 'Keep planning',
  'plan.empty': 'No plan content yet.',

  'mcp.title': 'MCP servers',
  'mcp.desc':
    'Connect remote MCP servers (sse / http / ws). stdio is not allowed.',
  'mcp.namePlaceholder': 'name',
  'mcp.empty': 'No MCP servers configured.',
}

export default messages
