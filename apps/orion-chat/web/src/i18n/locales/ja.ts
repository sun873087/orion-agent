/** 日本語 messages。加 key 時 4 個 locale(zh-TW/zh-CN/en/ja)都要同步。 */

const messages: Record<string, string> = {
  'common.loading': '読み込み中…',
  'common.save': '保存',
  'common.saving': '保存中…',
  'common.cancel': 'キャンセル',
  'common.delete': '削除',
  'common.close': '閉じる',
  'common.error': 'エラー',

  'sidebar.newChat': '新しいチャット',
  'sidebar.recents': '最近',
  'sidebar.noConversations': 'まだ会話がありません。',
  'sidebar.deleteConfirm': 'この会話を削除しますか?',
  'sidebar.expand': 'サイドバーを展開',
  'sidebar.collapse': 'サイドバーを折りたたむ',
  'sidebar.userMenu': 'ユーザーメニュー',
  'sidebar.settings': '設定',
  'sidebar.logout': 'ログアウト',
  'sidebar.msgCount': '{n} 件',
  'sidebar.untitled': '無題',
  'sidebar.rename': '名前を変更',
  'sidebar.renamePrompt': '新しいタイトル:',
  'sidebar.star': 'スター',
  'sidebar.unstar': 'スター解除',
  'sidebar.branch': 'ブランチ',

  'settings.title': '設定',
  'settings.tab.instructions': '指示',
  'settings.tab.settings': '設定',
  'settings.tab.memory': 'メモリ',
  'settings.tab.connections': '接続',
  'settings.appearance.title': '外観',
  'settings.appearance.system': 'システムに従う',
  'settings.appearance.light': 'ライト',
  'settings.appearance.dark': 'ダーク',
  'settings.appearance.current': '現在は{theme}です。',
  'settings.appearance.currentSystem': '現在は{theme}です(OS の設定に従う)。',
  'settings.language.title': '言語',
  'settings.storedValues': '保存された値',
  'settings.noSettings': '保存された設定はまだありません。',
  'settings.addOrUpdate': '追加または更新',
  'settings.keyPlaceholder': 'key(例:model)',
  'settings.valuePlaceholder':
    'value — JSON または文字列(例:"claude-opus-4-7")',
  'settings.serverRequires':
    'サーバー側の設定にはバックエンドの ORION_DB_URL が必要です。',
  'settings.deleteConfirm': '設定「{key}」を削除しますか?',

  'common.new': '新規',
  'common.edit': '編集',

  'settings.tab.skills': 'スキル',
  'settings.tab.roles': 'ロール',
  'settings.tab.soul': 'ソウル',
  'settings.tab.projects': 'プロジェクト',
  'settings.tab.schedules': 'スケジュール',

  'settings.schedules.title': 'スケジュール',
  'settings.schedules.desc':
    'プロンプトを自動実行する cron スケジュール(バックグラウンド実行は今後)。',
  'settings.schedules.empty': 'スケジュールはまだありません。',
  'settings.schedules.namePlaceholder': 'スケジュール名',
  'settings.schedules.payloadPlaceholder': '実行するプロンプト',

  'settings.projects.title': 'プロジェクト',
  'settings.projects.desc': '会話をまとめ、プロジェクト指示を付けられます。',
  'settings.projects.empty': 'プロジェクトはまだありません。',
  'settings.projects.namePlaceholder': 'プロジェクト名',
  'settings.projects.instructionsPlaceholder': 'プロジェクト指示(任意)',
  'settings.projects.deleteConfirm': 'このプロジェクトを削除しますか?',

  'settings.skills.title': 'スキル',
  'settings.skills.desc':
    'Orion が必要に応じて読み込む再利用可能な指示。ユーザーごとに保存。',
  'settings.skills.empty': '編集可能なスキルはまだありません。',
  'settings.skills.readonly': '組み込み',
  'settings.skills.nameLabel': '名前',
  'settings.skills.nameHint': '識別子 — 英数字、. _ -',
  'settings.skills.descLabel': '説明',
  'settings.skills.bodyLabel': '指示内容',
  'settings.skills.coworkVisible': 'スキルメニューに表示',
  'settings.skills.newTitle': '新しいスキル',
  'settings.skills.editTitle': 'スキルを編集',
  'settings.skills.deleteConfirm': 'スキル「{name}」を削除しますか?',

  'settings.roles.title': 'ロール',
  'settings.roles.desc':
    'システムプロンプトとデフォルトツールを調整するペルソナ。',
  'settings.roles.empty': '編集可能なロールはまだありません。',
  'settings.roles.bodyLabel': 'プロンプト追記',
  'settings.roles.disabledTools': '無効なツール(カンマ区切り)',
  'settings.roles.permissionMode': 'デフォルトの権限モード',
  'settings.roles.modeDefault': '— デフォルト —',
  'settings.roles.newTitle': '新しいロール',
  'settings.roles.editTitle': 'ロールを編集',
  'settings.roles.deleteConfirm': 'ロール「{name}」を削除しますか?',

  'settings.soul.title': 'ソウル',
  'settings.soul.desc':
    'Orion があなたについて一人称で覚えているメモ。新しい会話ごとに注入されます。',
  'settings.soul.placeholder': 'Orion に覚えておいてほしいことは?',
  'settings.soul.clear': 'クリア',
  'settings.soul.clearConfirm': 'ソウルのメモをクリアしますか?',

  'chat.budget': '予算',
  'chat.budgetPrompt': 'この会話のコスト上限(USD、空欄 = 無制限):',
  'chat.budgetBanner':
    '予算の上限に達しました — 続けるには上限を上げてください。',
  'chat.autoCompactBanner':
    'コンテキストが長くなっています。圧縮して空き容量を確保しましょう。',
  'chat.compactNow': '今すぐ圧縮',

  'panel.toggle': '詳細',
  'panel.progress': '進捗',
  'panel.skills': '使用したスキル',
  'panel.cost': 'トークンとコスト',
  'panel.empty': 'まだありません',
  'panel.contextTokens': '約 {n} トークン',
  'panel.messages': '{n} 件のメッセージ',

  'chat.permMode': '権限モード',
  'chat.permAsk': '確認',
  'chat.permAct': '自動',

  'chat.plan': 'プラン',
  'chat.planActive': '計画中',
  'plan.approveTitle': 'プランを確認',
  'plan.approve': '承認して実行',
  'plan.reject': '計画を続ける',
  'plan.empty': 'プラン内容はまだありません。',

  'mcp.title': 'MCP サーバー',
  'mcp.desc': 'リモート MCP サーバー(sse / http / ws)を接続。stdio は不可。',
  'mcp.namePlaceholder': '名前',
  'mcp.empty': 'MCP サーバーは未設定です。',

  'settings.tab.collab': 'コラボ',
  'settings.collab.title': 'コラボレーション',
  'settings.collab.desc':
    '複数の会話をマルチペインのコラボにまとめます(自分の session)。',
  'settings.collab.empty': 'コラボはまだありません。',
  'settings.collab.namePlaceholder': 'コラボ名',
  'settings.collab.panes': '{n} ペイン',
}

export default messages
