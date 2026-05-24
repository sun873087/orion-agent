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
  'settings.tab.instructions': 'Instructions',
  'settings.tab.settings': 'Settings',
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
  'settings.storedValues': 'Stored values',
  'settings.noSettings': 'No settings stored yet.',
  'settings.addOrUpdate': 'Add or update',
  'settings.keyPlaceholder': 'key (e.g. model)',
  'settings.valuePlaceholder':
    'value — JSON or string (e.g. "claude-opus-4-7")',
  'settings.serverRequires':
    'Server-side settings require ORION_DB_URL on the backend.',
  'settings.deleteConfirm': 'Delete setting "{key}"?',

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
  'panel.contextTokens': '~{n} tokens',
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

  'settings.tab.collab': 'Collaborations',
  'settings.collab.title': 'Collaborations',
  'settings.collab.desc':
    'Group conversations into a multi-pane collaboration (your own sessions).',
  'settings.collab.empty': 'No collaborations yet.',
  'settings.collab.namePlaceholder': 'Collaboration name',
  'settings.collab.panes': '{n} panes',
}

export default messages
