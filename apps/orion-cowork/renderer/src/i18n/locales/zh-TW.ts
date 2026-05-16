/** Traditional Chinese — Cowork 預設語言。 */
export default {
  // App / Header
  'app.title': 'Orion Cowork',
  'app.initializing': '初始化中⋯',

  // Sidebar
  'sidebar.newChat': '新對話',
  'sidebar.empty': '尚無對話',
  'sidebar.newConversation': '(新對話)',
  'sidebar.deleteConfirm': '確定刪除這個對話?',
  'sidebar.deleteTooltip': '刪除',
  'sidebar.settings': '設定',
  'sidebar.localUser': '本機使用者',
  'sidebar.openMenu': '開啟選單',

  // User menu
  'menu.settings': '設定',
  'menu.language': '語言',
  'language.title': '語言',

  // Settings page
  'settings.back': '返回',
  'settings.group.general': '一般',
  'settings.group.desktop': '桌面應用',

  // Session label
  'session.label': 'session: {id}',

  // InputBox
  'input.placeholder.disabled': 'sidecar 無法連線',
  'input.placeholder.busy': '模型思考中 — 按 Stop 中止',
  'input.placeholder.normal': '輸入訊息 (Enter 送出 · Shift+Enter 換行 · 貼上 / 拖入圖片可附檔)',
  'input.send': '送出 (Enter)',
  'input.sendDisabled': '請先輸入訊息',
  'input.stop': '停止 (中止當前回合)',
  'input.attach': '附加圖片 (PNG/JPEG/GIF/WebP, 每張 ≤ 20 MB)',
  'input.attach.unsupported': '{name}:格式不支援 (只接受 PNG / JPEG / GIF / WebP)',
  'input.attach.tooBig': '{name}:檔案 > 20 MB (provider 上限)',
  'input.attach.readFail': '{name}:讀取失敗',
  'input.attach.remove': '移除',
  'input.lastTurn': '上一次:{reason} · {turns} 個回合',
  'input.lastTurn.singular': '上一次:{reason} · {turns} 個回合',

  // SettingsPanel
  'settings.title': '設定',
  'settings.close': '關閉',
  'settings.section.appearance': '外觀',
  'settings.section.language': '語言',
  'settings.section.model': '模型',
  'settings.section.mcp': 'MCP 伺服器',
  'settings.section.about': '關於',
  'settings.theme.dark': '深色模式',
  'settings.theme.light': '淺色模式',
  'settings.theme.toggleHint': '— 點擊切換',
  'settings.model.loading': '載入模型清單中⋯',
  'settings.model.failed': '無法載入清單,請確認 sidecar 已啟動。',
  'settings.model.apiKeySet': 'API 金鑰已設定',
  'settings.model.apiKeyMissing': '尚未設 API 金鑰 — 請在 .env 中設定',
  'settings.model.reasoning': '推理',
  'settings.mcp.config': '設定檔:',
  'settings.mcp.refresh': '重新整理',
  'settings.mcp.refreshTitle': '重新載入狀態',
  'settings.mcp.loading': '載入中⋯',
  'settings.mcp.failed': '無法取得 MCP 狀態。',
  'settings.mcp.none': '尚未設定任何 MCP 伺服器。\n請編輯 ~/.orion-cowork/mcp.json 後重新整理。',
  'settings.mcp.tools': '{n} 個工具',
  'settings.mcp.reconnect': '重新連線',
  'settings.about.text': 'Orion Cowork · Phase 31。模型與外觀偏好存於 localStorage。MCP 伺服器設定於 ~/.orion-cowork/mcp.json。',

  // Language names
  'lang.zh-TW': '繁體中文',
  'lang.en': 'English',
  'lang.zh-CN': '简体中文',
  'lang.ja': '日本語',

  // Message
  'message.regenerate': '重新生成',
  'message.failedHistory': '對話歷史載入失敗:{msg}',
}
